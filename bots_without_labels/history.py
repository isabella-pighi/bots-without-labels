"""Run-history persistence and drift awareness across runs (roadmap item 7).

Thresholds are batch-relative, which suits a self-contained log; across *runs*
an operator still wants to know when traffic or score distributions shift
sharply. This module keeps a compact per-run record next to the other
artefacts and compares each new run with the previous recorded run in the same
output location.

**Decision-neutral by contract.** Everything here runs strictly *after*
detection; nothing read from or written to the history can change detection
booleans, scores, thresholds, or artefact contents other than the history file
itself and the ``drift`` summary field. The drift criteria below are
**operational warnings only** — "look at this run before trusting it" — never
model calibration, never a fraud or probability claim (the detector has no
labels and cannot know; see ``evaluation/FINDINGS.md``).

Determinism: records carry a monotonically increasing ``run_index`` rather
than a wall-clock timestamp, so repeated runs of the same input produce
byte-identical history records and the artefact stays reproducible. Ordering
is the file's line order. History is local JSON-lines, capped, atomically
rewritten — no service, database, or dependency.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

from .atomic import atomic_text_writer

HISTORY_FILENAME = "run_history.jsonl"
"""History artefact name, written under the run's ``artifacts/`` directory."""

HISTORY_MAX_RECORDS = 50
"""Records kept after appending; the oldest are dropped first. Keeps the
artefact compact however many times a directory is reused."""

SCORE_QUANTILES = (0.5, 0.9, 0.99)
"""Score quantiles recorded per run, for both the heuristic and ML scores."""

TOP_RULES_RECORDED = 3
"""Rules recorded per run, ranked by the number of rows they fired on."""

TOP_REASONS_RECORDED = 5
"""Human-readable flagged-row reasons kept per record."""

DRIFT_FLAG_RATE_DELTA = 0.05
"""Absolute change in a flag rate (overall, heuristic, or ML) treated as
sharp. An operational guardrail chosen for a low false-warning rate (five
points of flag-rate movement is far beyond seed-level jitter on the tracked
captures, whose rates are stable to the third decimal), NOT a calibrated or
scale-free constant."""

DRIFT_QUANTILE_DELTA = 0.15
"""Absolute change in any recorded score quantile treated as sharp. Same
status as :data:`DRIFT_FLAG_RATE_DELTA`: an operational guardrail, not model
calibration."""


def build_record(summary: dict, rule_fires: Counter) -> dict:
    """Build the compact history record for the current run.

    Args:
        summary: The run summary assembled by ``pipeline.run_pipeline`` (must
            already hold rates, tier counts, and top reasons).
        rule_fires: Per-rule fired-row counts for the run.

    Returns:
        A JSON-ready dict; ``run_index`` is assigned by :func:`append_record`.
    """

    return {
        "run_index": None,
        "input_path": summary["input_path"],
        "total_events": summary["total_events"],
        "bot_events": summary["bot_events"],
        "flag_rate": summary["bot_rate"],
        "heuristic_flag_rate": summary["heuristic_flag_rate"],
        "ml_flag_rate": summary["ml_flag_rate"],
        "ml_threshold": summary["ml_threshold"],
        "heuristic_score_quantiles": summary["heuristic_score_quantiles"],
        "ml_score_quantiles": summary["ml_score_quantiles"],
        "evidence_tier_counts": summary["evidence_tier_counts"],
        "top_rules": [
            [rule_id, count]
            for rule_id, count in rule_fires.most_common(TOP_RULES_RECORDED)
        ],
        "top_reasons": summary["top_reasons"][:TOP_REASONS_RECORDED],
    }


def score_quantiles(scores: np.ndarray) -> dict[str, float]:
    """Return the recorded quantiles of ``scores`` as a JSON-ready mapping."""

    if len(scores) == 0:
        return {f"q{int(q * 100)}": 0.0 for q in SCORE_QUANTILES}
    return {
        f"q{int(q * 100)}": float(np.quantile(np.asarray(scores, float), q))
        for q in SCORE_QUANTILES
    }


def read_history(path: Path) -> tuple[list[dict], str | None]:
    """Read prior records, tolerating absence and corruption.

    A missing file is a normal first run. An unreadable or partly-unreadable
    file must never fail the run (the history is an operational aid, not an
    input to detection): readable records are kept, the problem is reported as
    a non-fatal warning string, and the caller proceeds.

    Returns:
        ``(records, warning)`` where ``warning`` is ``None`` when the file was
        absent or fully readable.
    """

    if not path.exists():
        return [], None
    warning = None
    records: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], f"run history unreadable, ignored ({exc})"
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            warning = (
                "run history contains unreadable records; they were ignored "
                "(detections are unaffected)"
            )
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            warning = (
                "run history contains unreadable records; they were ignored "
                "(detections are unaffected)"
            )
    return records, warning


def append_record(path: Path, record: dict, history: list[dict]) -> None:
    """Assign ``run_index``, append ``record``, and atomically rewrite.

    The file is rewritten as a whole (capped to :data:`HISTORY_MAX_RECORDS`)
    through the shared atomic writer, so a crashed run never leaves a
    half-written history behind.
    """

    last_index = history[-1].get("run_index") if history else None
    record["run_index"] = (
        (last_index + 1) if isinstance(last_index, int) else (len(history))
    )
    kept = (history + [record])[-HISTORY_MAX_RECORDS:]
    with atomic_text_writer(path) as handle:
        for row in kept:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def assess_drift(previous: dict | None, record: dict) -> dict:
    """Compare this run's record with the previous one.

    Returns a JSON-ready mapping: ``status`` is ``"no_history"``, ``"stable"``
    or ``"drift"``; ``warnings`` lists one plain-English line per sharp shift.
    The criteria are the documented operational guardrails above — a warning
    means "inspect this run against the last one", never "the model recalibrated"
    and never a statement about fraud.
    """

    if previous is None:
        return {"status": "no_history", "warnings": [], "previous_run_index": None}

    warnings: list[str] = []
    for key, label in (
        ("flag_rate", "overall flag rate"),
        ("heuristic_flag_rate", "heuristic flag rate"),
        ("ml_flag_rate", "ML flag rate"),
    ):
        before, after = previous.get(key), record.get(key)
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            delta = abs(after - before)
            if delta >= DRIFT_FLAG_RATE_DELTA:
                warnings.append(
                    f"{label} moved {before:.3f} -> {after:.3f} "
                    f"(|delta| {delta:.3f} >= {DRIFT_FLAG_RATE_DELTA})"
                )

    for key, label in (
        ("ml_score_quantiles", "ML score"),
        ("heuristic_score_quantiles", "heuristic score"),
    ):
        before_q, after_q = previous.get(key), record.get(key)
        if isinstance(before_q, dict) and isinstance(after_q, dict):
            for name in sorted(set(before_q) & set(after_q)):
                before, after = before_q[name], after_q[name]
                if not isinstance(before, (int, float)):
                    continue
                if not isinstance(after, (int, float)):
                    continue
                delta = abs(after - before)
                if delta >= DRIFT_QUANTILE_DELTA:
                    warnings.append(
                        f"{label} {name} moved {before:.3f} -> {after:.3f} "
                        f"(|delta| {delta:.3f} >= {DRIFT_QUANTILE_DELTA})"
                    )

    prev_rules = {rule for rule, _ in previous.get("top_rules", []) if rule}
    new_rules = {rule for rule, _ in record.get("top_rules", []) if rule}
    if prev_rules and new_rules and prev_rules.isdisjoint(new_rules):
        warnings.append(
            "top firing rules changed completely: "
            f"{sorted(prev_rules)} -> {sorted(new_rules)}"
        )

    return {
        "status": "drift" if warnings else "stable",
        "warnings": warnings,
        "previous_run_index": previous.get("run_index"),
    }

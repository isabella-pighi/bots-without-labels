"""Trace one detection run end-to-end on any log, using only the public API.

Prints, in order:
  1. the inferred schema (column roles table),
  2. decision-state highlights from ``RulesResult.thresholds`` plus the ML
     threshold actually applied,
  3. per-rule fire counts (all rows vs flagged rows),
  4. evidence-tier counts (1 = both paths, 2 = rules only, 3 = ML only),
  5. the top-N flagged rows with rule reasons and top feature deviations.

Usage (from the repository root):
    uv run python .claude/skills/bwl-diagnostics-and-tooling/scripts/trace_detection.py <log> [--top N]

Read-only: nothing is written anywhere. Depends only on the
``bots_without_labels`` package (and its own dependencies, numpy/pandas).
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from bots_without_labels.ingest import load
from bots_without_labels.pipeline import HEURISTIC_CUTOFF, detect

# Scalar/flag keys worth surfacing from RulesResult.thresholds, in print order.
_HIGHLIGHT_KEYS = (
    "timestamp_grid",
    "dense_timing_gated",
    "entity_columns",
    "entity_diversity_cut",
    "entity_graph_active",
    "min_hub_degree",
    "actor_columns",
    "actor_graph_active",
    "degree_floor",
)
# Per-column threshold maps: print only their size, not every entry.
_MAP_KEYS = ("text_repeat", "categorical_concentration", "numeric_reuse")


def _section(title: str) -> None:
    print()
    print(f"== {title} " + "=" * max(0, 60 - len(title)))


def trace(log_path: Path, top_n: int) -> int:
    loaded = load(log_path)
    frame, schema = loaded.frame, loaded.schema

    _section("Inferred schema")
    print(schema.describe())

    result = detect(frame, schema)
    thresholds = result.rules_result.thresholds

    _section("Decision state (thresholds dict + ML threshold)")
    print(f"  decision: is_bot = heuristic >= {HEURISTIC_CUTOFF:.2f} OR ml_score > ml_threshold")
    print(
        f"  ml_threshold={result.ml_threshold:.6f} "
        f"(method={result.ml_threshold_method}, backend={result.ml_backend})"
    )
    for key in _HIGHLIGHT_KEYS:
        print(f"  {key} = {thresholds.get(key)!r}")
    for key in _MAP_KEYS:
        value = thresholds.get(key)
        if isinstance(value, dict):
            print(f"  {key}: adaptive per-column thresholds on {len(value)} column(s)")
    for key in ("context_cluster", "same_instant", "local_burst"):
        if key in thresholds:
            print(f"  {key} = {thresholds[key]!r}")

    _section("Rule fire counts")
    hits = result.rules_result.hits
    flagged_rows = {i for i in range(len(hits)) if result.is_bot[i]}
    fired_all: Counter[str] = Counter()
    fired_flagged: Counter[str] = Counter()
    for row, row_hits in enumerate(hits):
        for rule_id in {hit.rule_id for hit in row_hits}:
            fired_all[rule_id] += 1
            if row in flagged_rows:
                fired_flagged[rule_id] += 1
    if not fired_all:
        print("  (no heuristic rule fired on any row)")
    else:
        print(f"  {'rule':<24}{'fired_rows':>12}{'fired_in_flagged':>18}")
        # Sort ties alphabetically so the output is stable across runs
        # (set iteration order is hash-randomised between processes).
        for rule_id, count in sorted(fired_all.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {rule_id:<24}{count:>12}{fired_flagged.get(rule_id, 0):>18}")

    _section("Evidence tiers")
    n_rows = len(result.is_bot)
    n_flagged = int(result.is_bot.sum())
    print(f"  rows={n_rows}  flagged={n_flagged}  flag_rate={n_flagged / max(n_rows, 1):.4f}")
    labels = {
        1: "tier 1 (rules AND ml agree)",
        2: "tier 2 (rules only)",
        3: "tier 3 (ml only — no rule reason)",
        0: "tier 0 (not selected)",
    }
    for tier in (1, 2, 3, 0):
        print(f"  {labels[tier]:<36}{int((result.evidence_tier == tier).sum()):>8}")

    _section(f"Top {top_n} flagged rows (by combined score)")
    selected = sorted(flagged_rows, key=lambda i: result.combined[i], reverse=True)[:top_n]
    if not selected:
        print("  (nothing flagged)")
        return 0
    reasons = result.reasons()
    deviations = result.feature_deviations(selected)
    for row, row_devs in zip(selected, deviations):
        print(
            f"  row {row}: tier={int(result.evidence_tier[row])} "
            f"heuristic={result.heuristic[row]:.3f} ml={result.ml_scores[row]:.3f}"
        )
        for reason in reasons[row][:4]:
            print(f"    reason: {reason}")
        if not reasons[row]:
            print("    reason: (none — ML-only flag; read the deviations below)")
        for dev in row_devs[:3]:
            print(
                f"    deviation: {dev['feature']}={dev['value']:.4g} "
                f"robust_z={dev['robust_z']:+.2f} "
                f"batch_percentile={dev['batch_percentile']:.3f}"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trace_detection",
        description="Trace a detection run: schema, thresholds, rule fires, tiers, top flags.",
    )
    parser.add_argument("log", type=Path, help="path to a CSV/TSV/JSON/JSONL log")
    parser.add_argument("--top", type=int, default=5, help="flagged rows to detail (default 5)")
    args = parser.parse_args(argv)
    if not args.log.is_file():
        parser.error(f"log file not found: {args.log}")
    return trace(args.log, args.top)


if __name__ == "__main__":
    raise SystemExit(main())

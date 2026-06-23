"""Per-rule false-positive attribution on a labelled benchmark.

The headline precision of the detector is a property of the *whole* decision
(``heuristic_score >= 0.70 OR ml_score > threshold``), but the levers we can pull
are individual rules. This diagnostic attributes the flagged rows -- true and
false positives -- to the rules responsible for them, so calibration targets the
rules that cost precision without carrying recall.

Two views are produced per rule:

* **Fire view** -- rows where the rule appears in the evidence at all, split by
  ground truth. This is the rule's stand-alone precision, independent of whether
  the row cleared the decision threshold.
* **Counterfactual view** -- recompute the *whole* decision with this rule's
  evidence removed (heuristic re-summed and re-capped; the ML signal is
  unchanged because it does not depend on the heuristic rules). A row that was
  flagged but is no longer flagged is *carried* by this rule. Splitting those
  carried rows by ground truth gives, exactly:

  - ``fp_eliminated`` -- false positives that removing the rule would remove;
  - ``tp_lost`` -- true positives that *only* this rule flags (its unique recall
    carry).

The counterfactual is the actionable one: a rule with a large ``fp_eliminated``
and a small ``tp_lost`` is a precision drag we can calibrate or scope down with
little recall risk. The ML-only flags (rows no heuristic rule carries) are
reported separately so the heuristic and the anomaly model are not conflated.

Run:
    uv run --extra eif python -m evaluation.rule_diagnostic \
        --zip data/GeneratedLabelledFlows.zip
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np

from bots_without_labels.ingest import load
from bots_without_labels.pipeline import HEURISTIC_CUTOFF, detect
from bots_without_labels.rules import RuleHit, _cap_and_sum

from evaluation.cicids_bot_benchmark import DEFAULT_ZIP, N_BENIGN, SEED, build_mix


def _heuristic_without(hits: list[RuleHit], rule_id: str) -> float:
    """Re-sum a row's capped heuristic score with one rule's evidence removed."""

    kept = [hit for hit in hits if hit.rule_id != rule_id]
    if not kept:
        return 0.0
    return _cap_and_sum(kept)


def attribute(result, truth: np.ndarray) -> dict:
    """Attribute flagged rows to rules on an already-scored frame.

    Args:
        result: A :class:`~bots_without_labels.pipeline.DetectionResult`.
        truth: ``(n_rows,)`` 0/1 ground-truth labels aligned to the frame.

    Returns:
        A JSON-ready dict with overall counts, per-rule fire/counterfactual
        stats, and the ML-only flag breakdown.
    """

    truth = np.asarray(truth).astype(bool)
    is_bot = result.is_bot.astype(bool)
    heuristic = result.heuristic
    ml_flag = result.ml_scores > result.ml_threshold
    hits = result.rules_result.hits

    flagged = is_bot
    flagged_fp = flagged & ~truth
    flagged_tp = flagged & truth
    n_flag = int(flagged.sum())
    n_fp = int(flagged_fp.sum())
    n_tp = int(flagged_tp.sum())

    rule_ids = sorted({hit.rule_id for row in hits for hit in row})

    per_rule: dict[str, dict] = {}
    for rule_id in rule_ids:
        fired = np.array(
            [any(h.rule_id == rule_id for h in row) for row in hits], dtype=bool
        )
        fired_tp = int((fired & truth).sum())
        fired_fp = int((fired & ~truth).sum())
        n_fired = int(fired.sum())

        # Counterfactual: recompute the decision with this rule's evidence gone,
        # but only where it could matter (the rule fired and the row was flagged).
        fp_eliminated = 0
        tp_lost = 0
        for row in np.nonzero(fired & flagged)[0]:
            new_heuristic = _heuristic_without(hits[row], rule_id)
            still_flagged = (new_heuristic >= HEURISTIC_CUTOFF) or bool(ml_flag[row])
            if not still_flagged:
                if truth[row]:
                    tp_lost += 1
                else:
                    fp_eliminated += 1

        per_rule[rule_id] = {
            "n_fired": n_fired,
            "fired_tp": fired_tp,
            "fired_fp": fired_fp,
            "fire_precision": fired_tp / n_fired if n_fired else 0.0,
            "fp_eliminated": fp_eliminated,
            "tp_lost": tp_lost,
            "fp_share": fp_eliminated / n_fp if n_fp else 0.0,
        }

    # ML-only flags: flagged rows whose heuristic never reached the cutoff, so no
    # heuristic rule carries them. Reported apart so heuristic calibration is not
    # blamed for (or credited with) the anomaly model's decisions.
    heuristic_flag = heuristic >= HEURISTIC_CUTOFF
    ml_only = flagged & ~heuristic_flag
    ml_only_fp = int((ml_only & ~truth).sum())
    ml_only_tp = int((ml_only & truth).sum())

    return {
        "n_rows": int(len(truth)),
        "n_flagged": n_flag,
        "n_tp": n_tp,
        "n_fp": n_fp,
        "precision": n_tp / n_flag if n_flag else 0.0,
        "recall": n_tp / int(truth.sum()) if truth.sum() else 0.0,
        "ml_only": {
            "n_flagged": int(ml_only.sum()),
            "tp": ml_only_tp,
            "fp": ml_only_fp,
        },
        "per_rule": per_rule,
    }


def run(
    zip_path: Path = DEFAULT_ZIP, *, n_benign: int = N_BENIGN, seed: int = SEED
) -> dict:
    """Build the benchmark mix, score it, and return the rule attribution."""

    frame, truth = build_mix(zip_path, n_benign=n_benign, seed=seed)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cicids_bot_mix.csv"
        frame.to_csv(path, index=False)
        loaded = load(path)
    result = detect(loaded.frame, loaded.schema)
    return attribute(result, truth)


def _print(report: dict) -> None:
    print("CICIDS2017 per-rule false-positive attribution")
    print(
        f"  rows {report['n_rows']}  flagged {report['n_flagged']}  "
        f"tp {report['n_tp']}  fp {report['n_fp']}  "
        f"precision {report['precision']:.3f}  recall {report['recall']:.3f}"
    )
    ml = report["ml_only"]
    print(
        f"  ml-only flags {ml['n_flagged']}  (tp {ml['tp']}  fp {ml['fp']})  "
        "-- not attributable to any heuristic rule"
    )
    print()
    header = (
        f"  {'rule':<22} {'fired':>6} {'fire_p':>7} "
        f"{'fp_elim':>8} {'tp_lost':>8} {'fp_share':>9}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    rows = sorted(
        report["per_rule"].items(),
        key=lambda kv: kv[1]["fp_eliminated"],
        reverse=True,
    )
    for rule_id, stat in rows:
        print(
            f"  {rule_id:<22} {stat['n_fired']:>6} {stat['fire_precision']:>7.3f} "
            f"{stat['fp_eliminated']:>8} {stat['tp_lost']:>8} {stat['fp_share']:>9.3f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rule_diagnostic")
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--benign", type=int, default=N_BENIGN)
    args = parser.parse_args(argv)
    _print(run(args.zip, n_benign=args.benign))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

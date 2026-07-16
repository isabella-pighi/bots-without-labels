"""End-to-end detection pipeline over an arbitrary log.

Ties the pieces together: load any log (:mod:`ingest`), derive features
(:mod:`features`), score with the explainable rules (:mod:`rules`) and the
unsupervised anomaly model (:mod:`anomaly`), pick a self-tuned threshold
(:mod:`threshold`), and decide.

The decision is deliberately simple and inspectable::

    is_bot = heuristic_score >= 0.70 OR ml_score > dynamic_ml_threshold

:func:`detect` runs the whole thing in memory on a typed frame and is what the
notebook, label-injection evaluation, and tests use. :func:`run_pipeline` wraps
it with file loading and artefact writing for the CLI.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import history
from .anomaly import TOP_DEVIATION_FEATURES, feature_deviations, score_matrix
from .atomic import atomic_path_writer, atomic_text_writer
from .features import FeatureSet, build_features
from .ingest import Schema, load
from .rules import RulesResult, apply_rules
from .threshold import dynamic_knee_threshold

CANONICAL_RUN_OUTPUT_DIR = Path("run-output")

HEURISTIC_CUTOFF = 0.70
"""Rule-score decision cutoff. The rule weights in :mod:`rules` are calibrated
against this value: no single rule reaches it alone, so a flag always needs
corroborating evidence. Change the weights and this cutoff together."""

MAX_ML_FLAG_RATE = 0.02
"""Upper bound on the share of rows the anomaly model may flag *on its own*
(without rule support), so a loose threshold elbow cannot flood the output."""

MAX_SELECTED_EVENTS = 500
"""Cap on rows written to ``selected_events.json``; keeps the artefact
reviewable (it is a triage sample, not the full prediction set, which
``predictions.tsv`` already holds)."""

DECISION_RULE = (
    f"is_bot = heuristic_score >= {HEURISTIC_CUTOFF:.2f} "
    "OR ml_score > dynamic_ml_threshold"
)

# Threshold-plot styling.
_PLOT_FIGSIZE = (10, 5)
_PLOT_DPI = 160
_PLOT_Y_LIMITS = (0.0, 1.02)  # headroom so a score of 1.0 is not clipped


@dataclass
class DetectionResult:
    """The outcome of scoring a frame.

    Attributes:
        is_bot: ``(n_rows,)`` int array of 0/1 decisions.
        heuristic: Rule scores in ``[0, 1]``.
        ml_scores: Anomaly scores in ``[0, 1]``.
        combined: ``max(heuristic, ml)`` per row, used for ranking.
        evidence_tier: 1 = both classifiers, 2 = heuristic only, 3 = ML only,
            0 = not selected.
        ml_threshold: The anomaly threshold actually applied.
        ml_threshold_method: How the threshold was chosen.
        ml_backend: ``"eif"``, ``"fallback"``, or ``"degenerate"``.
        feature_set: The features used.
        rules_result: The rule hits and thresholds.
    """

    is_bot: np.ndarray
    heuristic: np.ndarray
    ml_scores: np.ndarray
    combined: np.ndarray
    evidence_tier: np.ndarray
    ml_threshold: float
    ml_threshold_method: str
    ml_backend: str
    feature_set: FeatureSet
    rules_result: RulesResult

    def reasons(self) -> list[list[str]]:
        """Return the per-row reason strings."""

        return self.rules_result.reasons()

    def feature_deviations(
        self, rows: list[int], *, top_k: int = TOP_DEVIATION_FEATURES
    ) -> list[list[dict[str, object]]]:
        """Report rows' largest marginal feature deviations from the batch.

        The readable counterpart of :meth:`reasons` for the ML path: an ML-only
        flag (evidence tier 3) has no rule reason, but its top robust-z
        deviations say *which* feature values sit in the batch's extreme tail.
        See :func:`bots_without_labels.anomaly.feature_deviations` for the
        entry format.

        Args:
            rows: Row indices to explain.
            top_k: Deviations to report per row.

        Returns:
            One deviation list per requested row, in the same order.
        """

        return feature_deviations(
            self.feature_set.matrix, self.feature_set.names, rows, top_k=top_k
        )


def detect(
    frame: pd.DataFrame,
    schema: Schema,
    *,
    max_ml_flag_rate: float = MAX_ML_FLAG_RATE,
    heuristic_cutoff: float = HEURISTIC_CUTOFF,
) -> DetectionResult:
    """Score a typed frame and return per-row decisions and evidence.

    Args:
        frame: A typed table from :func:`~bots_without_labels.ingest.load`.
        schema: Its inferred schema.
        max_ml_flag_rate: Upper bound on the share of rows the anomaly model may
            flag on its own, so a loose elbow cannot flood the output.
        heuristic_cutoff: Rule-score decision cutoff. The default is calibrated
            to the rule weights (see :data:`HEURISTIC_CUTOFF`); override for
            ablation/tuning studies only.

    Returns:
        A :class:`DetectionResult`. Its ``evidence_tier`` array encodes why each
        row was selected: 1 = both classifiers agree, 2 = heuristic rules only,
        3 = anomaly model only, 0 = not selected.
    """

    feature_set = build_features(frame, schema)
    rules_result = apply_rules(frame, schema, feature_set)
    heuristic = rules_result.scores

    ml_scores, backend = score_matrix(feature_set.matrix)
    ml_cutoff, ml_method = dynamic_knee_threshold(ml_scores.tolist())
    if ml_scores.size:
        rate_floor = float(np.quantile(ml_scores, 1.0 - max_ml_flag_rate))
        if rate_floor > ml_cutoff:
            ml_cutoff, ml_method = rate_floor, f"{ml_method}+rate_capped"

    heuristic_flag = heuristic >= heuristic_cutoff
    ml_flag = ml_scores > ml_cutoff
    is_bot = (heuristic_flag | ml_flag).astype(int)
    combined = np.maximum(heuristic, ml_scores)
    evidence_tier = _evidence_tiers(heuristic_flag, ml_flag)

    return DetectionResult(
        is_bot=is_bot,
        heuristic=heuristic,
        ml_scores=ml_scores,
        combined=combined,
        evidence_tier=evidence_tier,
        ml_threshold=ml_cutoff,
        ml_threshold_method=ml_method,
        ml_backend=backend,
        feature_set=feature_set,
        rules_result=rules_result,
    )


def run_pipeline(
    input_path: str | Path,
    output_dir: str | Path = CANONICAL_RUN_OUTPUT_DIR,
    *,
    display_input_path: str | Path | None = None,
    max_output_events: int = MAX_SELECTED_EVENTS,
    entity_columns: Sequence[str] = (),
    content_columns: Sequence[str] = (),
    timestamp_column: str | None = None,
) -> dict[str, object]:
    """Load a log, run detection, and write predictions and artefacts.

    Args:
        input_path: Path to a CSV/TSV/JSON log.
        output_dir: Directory for ``predictions.tsv`` and the ``artifacts/``
            folder.
        display_input_path: Optional path/name to record in the summary.
        max_output_events: Cap on the flagged rows written to
            ``artifacts/selected_events.json`` (highest combined score first).
        entity_columns: Explicit, default-off ``--entity-column`` schema
            overrides forwarded to :func:`~bots_without_labels.ingest.load`.
        content_columns: Explicit, default-off ``--content-column`` schema
            overrides forwarded to :func:`~bots_without_labels.ingest.load`.
        timestamp_column: Explicit, default-off ``--timestamp-column`` schema
            override forwarded to :func:`~bots_without_labels.ingest.load`.

    Returns:
        A summary dictionary, also written to ``artifacts/summary.json``.

    Writes into ``output_dir``:
        * ``predictions.tsv`` — id + 0/1 decision per row.
        * ``predictions-extended.tsv`` — scores, evidence tier, top reason.
        * ``artifacts/summary.json`` — the returned summary.
        * ``artifacts/features.tsv`` — the numeric feature matrix.
        * ``artifacts/selected_events.json`` — top flagged rows with reasons and
          their top feature deviations from the batch baseline.
        * ``artifacts/ml_score_threshold.png`` — sorted-score threshold plot.
    """

    root = Path(output_dir)
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    loaded = load(
        input_path,
        entity_columns=entity_columns,
        content_columns=content_columns,
        timestamp_column=timestamp_column,
    )
    frame, schema = loaded.frame, loaded.schema
    result = detect(frame, schema)

    id_name, ids = _row_ids(frame, schema)
    reasons = result.reasons()
    n_rows = len(ids)
    bot_count = int(result.is_bot.sum())

    reason_counter: Counter[str] = Counter()
    for row in range(n_rows):
        if result.is_bot[row]:
            for reason in reasons[row]:
                reason_counter[reason] += 1

    summary: dict[str, object] = {
        "input_path": str(
            Path(display_input_path if display_input_path is not None else input_path)
        ),
        "total_events": n_rows,
        "bot_events": bot_count,
        "bot_rate": bot_count / max(n_rows, 1),
        "decision_rule": DECISION_RULE,
        "heuristic_cutoff": HEURISTIC_CUTOFF,
        "entity_column_overrides": list(entity_columns),
        "content_column_overrides": list(content_columns),
        "timestamp_column_override": timestamp_column,
        "ml_threshold": result.ml_threshold,
        "ml_threshold_method": result.ml_threshold_method,
        "ml_backend": result.ml_backend,
        "heuristic_flag_rate": (
            float((result.heuristic >= HEURISTIC_CUTOFF).mean()) if n_rows else 0.0
        ),
        "ml_flag_rate": (
            float((result.ml_scores > result.ml_threshold).mean()) if n_rows else 0.0
        ),
        "heuristic_score_quantiles": history.score_quantiles(result.heuristic),
        "ml_score_quantiles": history.score_quantiles(result.ml_scores),
        "evidence_tier_counts": {
            "tier_1_both": int((result.evidence_tier == 1).sum()),
            "tier_2_heuristic_only": int((result.evidence_tier == 2).sum()),
            "tier_3_ml_only": int((result.evidence_tier == 3).sum()),
            "not_selected": int((result.evidence_tier == 0).sum()),
        },
        "id_column": id_name,
        "feature_names": result.feature_set.names,
        "schema": schema.to_dict(),
        "rule_thresholds": result.rules_result.thresholds,
        "top_reasons": reason_counter.most_common(10),
    }

    # Drift awareness (roadmap item 7): strictly decision-neutral — computed
    # from the finished result AFTER every detection decision is made, and
    # nothing read from the history feeds back into detection.
    rule_fires = Counter(hit.rule_id for row in result.rules_result.hits for hit in row)
    history_path = artifacts / history.HISTORY_FILENAME
    records, history_warning = history.read_history(history_path)
    record = history.build_record(summary, rule_fires)
    drift = history.assess_drift(records[-1] if records else None, record)
    if history_warning:
        drift["warnings"] = [history_warning, *drift["warnings"]]
    summary["drift"] = drift
    history.append_record(history_path, record, records)

    _write_predictions(root / "predictions.tsv", id_name, ids, result.is_bot)
    _write_extended(root / "predictions-extended.tsv", id_name, ids, result, reasons)
    _write_json(artifacts / "summary.json", summary)
    _write_features(artifacts / "features.tsv", id_name, ids, result.feature_set)
    _write_selected(
        artifacts / "selected_events.json", ids, result, reasons, max_output_events
    )
    _write_threshold_plot(
        artifacts / "ml_score_threshold.png", result.ml_scores, result.ml_threshold
    )
    _log_summary(summary)
    return summary


def _row_ids(frame: pd.DataFrame, schema: Schema) -> tuple[str, list[str]]:
    if schema.row_id is not None:
        return schema.row_id, frame[schema.row_id].astype("string").fillna("").tolist()
    return "row_id", [f"row_{index}" for index in range(frame.shape[0])]


def _evidence_tiers(heuristic_flag: np.ndarray, ml_flag: np.ndarray) -> np.ndarray:
    tiers = np.zeros(len(heuristic_flag), dtype=int)
    tiers[heuristic_flag & ml_flag] = 1
    tiers[heuristic_flag & ~ml_flag] = 2
    tiers[~heuristic_flag & ml_flag] = 3
    return tiers


def _write_predictions(path: Path, id_name: str, ids, is_bot: np.ndarray) -> None:
    with atomic_text_writer(path) as handle:
        handle.write(f"{id_name}\tis_bot\n")
        for identifier, flag in zip(ids, is_bot):
            handle.write(f"{identifier}\t{int(flag)}\n")


def _write_extended(
    path: Path, id_name: str, ids, result: DetectionResult, reasons
) -> None:
    header = [
        id_name,
        "is_bot",
        "evidence_tier",
        "heuristic_score",
        "ml_score",
        "combined_score",
        "top_reason",
    ]
    with atomic_text_writer(path) as handle:
        handle.write("\t".join(header) + "\n")
        for row, identifier in enumerate(ids):
            top_reason = reasons[row][0] if reasons[row] else ""
            handle.write(
                "\t".join(
                    [
                        str(identifier),
                        str(int(result.is_bot[row])),
                        str(int(result.evidence_tier[row])),
                        f"{result.heuristic[row]:.6f}",
                        f"{result.ml_scores[row]:.6f}",
                        f"{result.combined[row]:.6f}",
                        top_reason,
                    ]
                )
                + "\n"
            )


def _write_features(path: Path, id_name: str, ids, feature_set: FeatureSet) -> None:
    with atomic_text_writer(path) as handle:
        handle.write("\t".join([id_name, *feature_set.names]) + "\n")
        for row, identifier in enumerate(ids):
            values = [f"{value:.6f}" for value in feature_set.matrix[row]]
            handle.write("\t".join([str(identifier), *values]) + "\n")


def _write_selected(
    path: Path, ids, result: DetectionResult, reasons, max_events: int
) -> None:
    selected = [row for row in range(len(ids)) if result.is_bot[row]]
    selected.sort(key=lambda row: result.combined[row], reverse=True)
    written = selected[:max_events]
    # Deviations are computed only for the rows actually written (pay-per-use);
    # they are what makes a reasonless ML-only flag (tier 3) reviewable.
    deviations = result.feature_deviations(written)
    records = [
        {
            "event_id": str(ids[row]),
            "evidence_tier": int(result.evidence_tier[row]),
            "heuristic_score": round(float(result.heuristic[row]), 4),
            "ml_score": round(float(result.ml_scores[row]), 4),
            "combined_score": round(float(result.combined[row]), 4),
            "reasons": reasons[row][:6],
            "feature_deviations": [
                {
                    "feature": dev["feature"],
                    "value": round(float(dev["value"]), 4),
                    "robust_z": round(float(dev["robust_z"]), 2),
                    "batch_percentile": round(float(dev["batch_percentile"]), 4),
                }
                for dev in row_devs
            ],
        }
        for row, row_devs in zip(written, deviations)
    ]
    _write_json(path, records)


def _write_threshold_plot(path: Path, ml_scores: np.ndarray, cutoff: float) -> None:
    ordered = sorted((float(score) for score in ml_scores), reverse=True)
    if not ordered:
        return
    # pylint: disable=import-outside-toplevel
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    index = next(
        (i for i, score in enumerate(ordered) if score <= cutoff), len(ordered) - 1
    )
    figure, axis = plt.subplots(figsize=_PLOT_FIGSIZE)
    axis.plot(range(len(ordered)), ordered, color="#2f7d59", linewidth=1.4)
    axis.axvline(
        index,
        color="#b3261e",
        linestyle="--",
        linewidth=1.5,
        label=f"threshold {cutoff:.4f}",
    )
    axis.axhline(cutoff, color="#b3261e", linestyle=":", linewidth=1.0)
    axis.set_title("Sorted anomaly scores with dynamic threshold")
    axis.set_xlabel("Events sorted by anomaly score, descending")
    axis.set_ylabel("Anomaly score")
    axis.set_ylim(*_PLOT_Y_LIMITS)
    axis.legend(loc="best")
    axis.grid(True, alpha=0.25)
    figure.tight_layout()
    with atomic_path_writer(path, "wb") as tmp_path:
        figure.savefig(tmp_path, dpi=_PLOT_DPI, format="png")
    plt.close(figure)


def _write_json(path: Path, payload: object) -> None:
    with atomic_text_writer(path) as handle:
        handle.write(json.dumps(payload, indent=2))


def _log_summary(summary: dict[str, object]) -> None:
    print(
        "Detection summary: "
        f"{summary['bot_events']}/{summary['total_events']} flagged "
        f"({summary['bot_rate']:.2%}); "
        f"ml_threshold={summary['ml_threshold']:.6f} "
        f"({summary['ml_threshold_method']}); backend={summary['ml_backend']}"
    )
    drift = summary.get("drift")
    if isinstance(drift, dict) and drift.get("warnings"):
        # Operational warnings only (see the history module header): they flag
        # a sharp run-to-run shift for inspection and never change decisions.
        for warning in drift["warnings"]:
            print(f"Drift warning: {warning}")

"""End-to-end Bots Without Labels pipeline orchestration and artifact writing."""

# pylint: disable=too-many-lines

from __future__ import annotations

from collections.abc import Iterable, Sequence
from collections import Counter
import json
import math
import re
from pathlib import Path
from typing import Callable

from bots_without_labels.atomic import atomic_text_writer

from .data import (
    ClickEvent,
    build_features,
    iter_event_dicts,
    parse_clicks,
    select_ml_feature_names,
    select_ml_feature_weights,
)
from .heuristics import STRONG, SUPPORTING, SUPPORTING_RULE_CAP, apply_heuristics
from .ml import score_anomalies

CANONICAL_RUN_OUTPUT_DIR = Path("run-output")

# These are conservative operating thresholds for the two requested classifiers.
SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD = 0.70
HEURISTIC_ML_AGREEMENT_FLOOR = SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
ML_AGREEMENT_THRESHOLD = 0.975
THRESHOLD_SENSITIVITY_PERCENTILES = (0.95, 0.975, 0.99, 0.995)
CONFIDENCE_BY_TIER = {1: "HIGH", 2: "MEDIUM", 3: "LOW"}
METHOD_BUCKETS = (
    "Heuristic + ML",
    "Heuristic only",
    "ML only",
    "Neither strong",
)


def run_pipeline(
    input_path: str | Path,
    output_dir: str | Path = CANONICAL_RUN_OUTPUT_DIR,
    display_input_path: str | Path | None = None,
) -> dict[str, object]:
    # pylint: disable=too-many-locals
    """Run parsing, feature engineering, scoring, and artifact generation.

    Args:
        input_path: Raw click TSV input.
        output_dir: Directory where ``predictions.tsv`` and artifact folders are
            written. The canonical run-specific repository location is
            ``run-output/``.
        display_input_path: Optional original TSV path or filename to show in
            generated artefacts when processing uses a temporary file.

    Returns:
        Summary dictionary also written to
        ``<output_dir>/artifacts/summary.json``.

    Raises:
        ValueError: If input parsing, scoring, or feature validation fails.
        OSError: If output artifacts cannot be written.
    """

    root = Path(output_dir)
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    events = parse_clicks(input_path)
    feature_names, counters = build_features(events)
    ml_feature_names = select_ml_feature_names(feature_names)
    ml_feature_weights = select_ml_feature_weights(feature_names)
    heuristic_thresholds = apply_heuristics(events, counters)
    ml_backend_used = score_anomalies(events)
    _bound_base_scores(events)
    ml_cutoff, ml_threshold_method = _dynamic_knee_threshold(
        [event.ml_score for event in events]
    )
    cutoff = ml_cutoff
    threshold_method = "two_classifier_agreement"
    threshold_options = optimize_threshold(
        [max(event.heuristic_score, event.ml_score) for event in events],
        [event.heuristic_score for event in events],
    )
    for event in events:
        event.heuristic_flag = (
            event.heuristic_score >= SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
        )
        event.ml_flag = event.ml_score > ml_cutoff
        event.flags_assigned = True
        event.combined_score = max(event.heuristic_score, event.ml_score)
        event.is_bot = 1 if event.heuristic_flag or event.ml_flag else 0
        event.evidence_tier = _assign_evidence_tier(event) if event.is_bot else 0
        event.confidence_proxy = CONFIDENCE_BY_TIER.get(event.evidence_tier, "NONE")
        event.operational_tier = _assign_operational_tier(event)

    bot_events = [event for event in events if event.is_bot]
    score_diagnostics = _score_diagnostics(events)
    _assert_decision_contract(events, cutoff)
    plot_artifact = "artifacts/risk_score_threshold.png"
    ml_plot_artifact = "artifacts/ml_score_threshold.png"
    _write_threshold_plot(
        artifacts / "risk_score_threshold.png",
        events,
        cutoff,
        title="Sorted Classifier Risk Scores",
        ylabel="Max heuristic/ML score",
    )
    _write_threshold_plot(
        artifacts / "ml_score_threshold.png",
        events,
        ml_cutoff,
        score_getter=_ml_score,
        title="Sorted EIF Scores With Dynamic Elbow Threshold",
        ylabel="EIF ML score",
    )
    _log_score_diagnostics(
        score_diagnostics,
        cutoff,
        len(bot_events),
        len(events),
    )

    reason_counter: Counter[str] = Counter()
    for event in bot_events:
        for reason in event.reasons:
            reason_counter[_normalize_reason(reason)] += 1

    top_domains = counters["domain"].most_common(12)
    top_queries = counters["query"].most_common(12)
    top_regions = Counter(event.region for event in bot_events).most_common(8)
    tier_counts = Counter(event.operational_tier for event in events)
    evidence_tier_counts = Counter(event.evidence_tier for event in events)
    displayed_input_path = (
        str(Path(display_input_path).expanduser())
        if display_input_path is not None
        else str(Path(input_path).expanduser())
    )
    summary = {
        "input_path": displayed_input_path,
        "total_events": len(events),
        "bot_events": len(bot_events),
        "bot_rate": len(bot_events) / max(len(events), 1),
        "threshold": ml_cutoff,
        "threshold_method": threshold_method,
        "ml_dynamic_elbow_threshold": ml_cutoff,
        "ml_threshold_method": ml_threshold_method,
        "score_blending": {
            "method": "no_blending_two_classifier_rule",
            "formula": (
                "is_bot = heuristic_score >= 0.70 OR " "ml_score > dynamic_ml_threshold"
            ),
            "note": (
                "The binary decision is made by the two "
                "classifiers directly. combined_score is retained only as a "
                "display/ranking score: max(heuristic_score, ml_score)."
            ),
        },
        "score_diagnostics": score_diagnostics,
        "threshold_plot_artifact": plot_artifact,
        "ml_threshold_plot_artifact": ml_plot_artifact,
        "heuristic_flag_rate": sum(1 for event in events if event.heuristic_flag)
        / max(len(events), 1),
        "ml_tail_rate": sum(1 for event in events if event.ml_flag)
        / max(len(events), 1),
        "ml_backend": ml_backend_used,
        "feature_artifact": "artifacts/features.tsv",
        "selected_events_artifact": "artifacts/selected_events.json",
        "feature_names": feature_names,
        "ml_feature_names": ml_feature_names,
        "ml_feature_weights": dict(zip(ml_feature_names, ml_feature_weights)),
        "operational_tiers": {
            "suppress": (
                "High-confidence bot traffic suitable for automatic suppression "
                "after policy approval."
            ),
            "quarantine": "Bot traffic that should be held for review before suppression.",
            "monitor": (
                "Traffic not selected for bot action; keep for trend monitoring "
                "and future labels."
            ),
        },
        "evidence_tiers": {
            "scope": (
                "Classifier agreement tiers. They are review-priority proxies, "
                "not proof of fraud or measured accuracy claims."
            ),
            "counts": {
                "tier_1_high": evidence_tier_counts.get(1, 0),
                "tier_2_medium": evidence_tier_counts.get(2, 0),
                "tier_3_low": evidence_tier_counts.get(3, 0),
                "not_selected": evidence_tier_counts.get(0, 0),
            },
            "definitions": [
                {
                    "evidence_tier": 1,
                    "label": "Tier 1 (High Confidence)",
                    "confidence_proxy": "HIGH",
                    "definition": "Both heuristic and ML classifiers flagged the event.",
                },
                {
                    "evidence_tier": 2,
                    "label": "Tier 2 (Medium Confidence)",
                    "confidence_proxy": "MEDIUM",
                    "definition": "Only the rules-based heuristic classifier flagged the event.",
                },
                {
                    "evidence_tier": 3,
                    "label": "Tier 3 (Low Confidence / Quarantine)",
                    "confidence_proxy": "LOW",
                    "definition": "Only the ML classifier flagged the event.",
                },
            ],
        },
        "method_disagreement": _method_disagreement(events, ml_threshold=ml_cutoff),
        "selected_method_counts": _selected_method_counts(bot_events),
        "threshold_sensitivity": _threshold_sensitivity(events, cutoff),
        "cost_sensitive_thresholds": threshold_options,
        "feature_lift_analysis": _feature_lift_analysis(events, feature_names),
        "derived_feature_stats": _derived_feature_stats(events),
        "query_entropy_distribution": _query_entropy_distribution(events),
        "anomaly_classes": _anomaly_classes(events),
        "tier_thresholds": {
            "suppress_agreement_heuristic_score": SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD,
            "heuristic_ml_agreement_floor": HEURISTIC_ML_AGREEMENT_FLOOR,
            "ml_agreement_score": ml_cutoff,
            "combined_score_cutoff": None,
            "ml_score_cutoff": ml_cutoff,
            "threshold_method": threshold_method,
            "ml_threshold_method": ml_threshold_method,
            "is_bot": ("heuristic_score >= 0.70 OR ml_score > dynamic ML threshold"),
            "evidence_tier_1": "heuristic_flag and ml_flag",
            "evidence_tier_2": "heuristic_flag and not ml_flag",
            "evidence_tier_3": "ml_flag and not heuristic_flag",
            "quarantine": "is_bot == 1 and suppress conditions are not met",
            "monitor": "is_bot == 0",
        },
        "heuristic_thresholds": heuristic_thresholds,
        "rule_strengths": {
            STRONG: "Direct mechanical or replay evidence; applied at full weight.",
            SUPPORTING: (
                "Contextual or weaker evidence; combined applied weight is capped."
            ),
            "supporting_cap": SUPPORTING_RULE_CAP,
        },
        "tier_counts": {
            tier: tier_counts.get(tier, 0)
            for tier in ("suppress", "quarantine", "monitor")
        },
        "top_reasons": reason_counter.most_common(10),
        "top_domains": top_domains,
        "top_queries": top_queries,
        "bot_regions": top_regions,
    }

    _write_predictions(root / "predictions.tsv", events)
    _write_extended_predictions(root / "predictions-extended.tsv", events)
    _write_json(artifacts / "summary.json", summary)
    _write_features(artifacts / "features.tsv", feature_names, events)
    selected = sorted(bot_events, key=lambda event: event.combined_score, reverse=True)
    _write_json(artifacts / "selected_events.json", _selected_event_dicts(selected))
    sample = sorted(events, key=lambda event: event.combined_score, reverse=True)[:250]
    _write_json(artifacts / "sample_events.json", list(iter_event_dicts(sample)))
    return summary


def _bound_base_scores(events: list[ClickEvent]) -> None:
    """Defensively bound heuristic and EIF scores before final decisioning."""

    for event in events:
        event.heuristic_score = _bounded_score(event.heuristic_score, "heuristic_score")
        event.ml_score = _bounded_score(event.ml_score, "ml_score")


def _bounded_score(value: float, field_name: str) -> float:
    """Return a finite score bounded to ``[0, 1]``.

    Args:
        value: Score to validate and clamp.
        field_name: Name used in error messages.

    Returns:
        A finite score within ``[0, 1]``.

    Raises:
        ValueError: If ``value`` is not finite.
    """

    score = float(value)
    if not math.isfinite(score):
        raise ValueError(f"{field_name} must be finite")
    return min(max(score, 0.0), 1.0)


def _score_diagnostics(events: list[ClickEvent]) -> dict[str, dict[str, float]]:
    """Return min, max, and mean diagnostics for scaled scores."""

    return {
        "ml_score": _score_stats([event.ml_score for event in events]),
        "combined_score": _score_stats([event.combined_score for event in events]),
    }


def _score_stats(scores: Sequence[float]) -> dict[str, float]:
    finite_scores = [float(score) for score in scores if math.isfinite(float(score))]
    if not finite_scores:
        return {"min": 0.0, "max": 0.0, "mean": 0.0}
    return {
        "min": min(finite_scores),
        "max": max(finite_scores),
        "mean": sum(finite_scores) / len(finite_scores),
    }


def _log_score_diagnostics(
    diagnostics: dict[str, dict[str, float]],
    threshold: float,
    bot_events: int,
    total_events: int,
) -> None:
    """Print score scaling and threshold diagnostics for CLI users."""

    ml_stats = diagnostics["ml_score"]
    combined_stats = diagnostics["combined_score"]
    selected_rate = bot_events / max(total_events, 1)
    print(
        "Score diagnostics: "
        f"ml_score min={ml_stats['min']:.6f}, max={ml_stats['max']:.6f}, "
        f"mean={ml_stats['mean']:.6f}; "
        f"combined_score min={combined_stats['min']:.6f}, "
        f"max={combined_stats['max']:.6f}, "
        f"mean={combined_stats['mean']:.6f}; "
        f"dynamic_elbow_threshold={threshold:.6f}; "
        f"is_bot volume={bot_events:,}/{total_events:,} ({selected_rate:.2%})"
    )


def _assert_decision_contract(events: Sequence[ClickEvent], threshold: float) -> None:
    """Assert final decisions use the two requested classifiers only."""

    if not events:
        return
    combined_scores = [event.combined_score for event in events]
    assert max(combined_scores) <= 1.0, (
        "CRITICAL ERROR: Combined score exceeds 1.0! Linear blending formula "
        "was not successfully removed."
    )
    assert min(combined_scores) >= 0.0, "CRITICAL ERROR: Combined score is negative!"
    if len(events) >= 10 and len({event.ml_score for event in events}) >= 3:
        assert (
            0.0 < threshold < 1.0
        ), f"CRITICAL ERROR: ML threshold ({threshold}) is mathematically invalid!"
    mismatched_event_ids = [
        event.event_id
        for event in events
        if event.is_bot
        != int(
            event.heuristic_score >= SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
            or event.ml_score > threshold
        )
    ]
    assert not mismatched_event_ids, (
        "CRITICAL ERROR: Final 'is_bot' classification is disconnected from "
        "the heuristic/ML classifier rule! "
        f"Example mismatched event IDs: {mismatched_event_ids[:5]}"
    )
    expected_bot_count = sum(
        1
        for event in events
        if event.heuristic_score >= SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
        or event.ml_score > threshold
    )
    actual_bot_count = sum(event.is_bot for event in events)
    assert actual_bot_count == expected_bot_count, (
        "CRITICAL ERROR: Final 'is_bot' classification is disconnected from "
        "the heuristic/ML classifier rule!"
    )


def _write_threshold_plot(
    path: Path,
    events: Sequence[ClickEvent],
    threshold: float,
    *,
    score_getter: Callable[[ClickEvent], float] | None = None,
    title: str = "Sorted Combined Scores With Dynamic Elbow Threshold",
    ylabel: str = "Combined score",
) -> None:
    """Write a sorted-score plot with the Kneedle threshold marker."""

    if score_getter is None:
        score_getter = _combined_score
    scores = sorted(
        (
            float(score_getter(event))
            for event in events
            if _finite_event_score(event, score_getter)
        ),
        reverse=True,
    )
    if not scores:
        return

    # pylint: disable=import-outside-toplevel
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    threshold_index = _first_descending_threshold_index(scores, threshold)
    figure, axis = plt.subplots(figsize=(10, 5))
    axis.plot(range(len(scores)), scores, color="#2f7d59", linewidth=1.4)
    axis.axvline(
        threshold_index,
        color="#b3261e",
        linestyle="--",
        linewidth=1.5,
        label=f"Kneedle threshold {threshold:.4f}",
    )
    axis.axhline(threshold, color="#b3261e", linestyle=":", linewidth=1.0)
    axis.set_title(title)
    axis.set_xlabel("Events sorted by score, descending")
    axis.set_ylabel(ylabel)
    axis.set_ylim(0.0, 1.02)
    axis.legend(loc="best")
    axis.grid(True, alpha=0.25)
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _combined_score(event: ClickEvent) -> float:
    """Return the event's combined score for plotting."""

    return event.combined_score


def _ml_score(event: ClickEvent) -> float:
    """Return the event's ML score for plotting."""

    return event.ml_score


def _finite_event_score(
    event: ClickEvent,
    score_getter: Callable[[ClickEvent], float],
) -> bool:
    """Return whether ``score_getter`` produces a finite value for ``event``."""

    return math.isfinite(float(score_getter(event)))


def _first_descending_threshold_index(scores: Sequence[float], threshold: float) -> int:
    """Return the first descending index at or below ``threshold``."""

    for index, score in enumerate(scores):
        if score <= threshold:
            return index
    return max(len(scores) - 1, 0)


def _quantile(values: list[float], q: float) -> float:
    """Return the rounded-index quantile used for the combined-score cutoff."""

    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return ordered[idx]


def _dynamic_knee_threshold(scores: Sequence[float]) -> tuple[float, str]:
    """Return a self-tuned anomaly threshold using Kneedle.

    The score distribution is sorted from most anomalous to least anomalous,
    with non-finite values removed. Kneedle is then applied with a convex,
    decreasing curve to identify the elbow between the anomaly tail and the
    ordinary traffic body.
    """

    ordered = sorted(
        (float(score) for score in scores if math.isfinite(float(score))),
        reverse=True,
    )
    if not ordered:
        return 0.0, "empty_input"
    if len(ordered) < 10:
        return max(ordered), "small_input_fallback"
    if len(set(ordered)) < 3:
        return max(ordered), "tied_score_fallback"
    kneedle_threshold = _kneedle_locator_threshold(ordered)
    if kneedle_threshold is not None:
        return kneedle_threshold, "kneedle_descending"
    fallback_threshold = _max_distance_knee_threshold(ordered)
    return fallback_threshold, "max_distance_descending_fallback"


def _kneedle_locator_threshold(ordered_scores: Sequence[float]) -> float | None:
    """Return the Kneedle threshold, or ``None`` when it degenerates."""

    # pylint: disable=import-outside-toplevel
    try:
        from kneed import KneeLocator
    except ImportError:
        return None
    x_values = _normalised_positions(len(ordered_scores))
    locator = KneeLocator(
        x_values,
        list(ordered_scores),
        curve="convex",
        direction="decreasing",
        online=False,
    )
    if locator.knee is None:
        return None
    index = _nearest_position_index(x_values, float(locator.knee))
    if index <= 0 or index >= len(ordered_scores) - 1:
        return None
    return float(ordered_scores[index])


def _max_distance_knee_threshold(ordered_scores: Sequence[float]) -> float:
    """Return the descending elbow with the largest distance from the diagonal."""

    x_values = _normalised_positions(len(ordered_scores))
    y_values = _normalise_values(ordered_scores)
    distances = [
        abs(y_value - (1.0 - x_value)) for x_value, y_value in zip(x_values, y_values)
    ]
    index = max(range(len(distances)), key=distances.__getitem__)
    return float(ordered_scores[index])


def _normalised_positions(length: int) -> list[float]:
    if length <= 1:
        return [0.0]
    return [index / (length - 1) for index in range(length)]


def _normalise_values(values: Sequence[float]) -> list[float]:
    minimum = min(values)
    maximum = max(values)
    spread = maximum - minimum
    if spread <= 0.0:
        return [0.0 for _ in values]
    return [(value - minimum) / spread for value in values]


def _nearest_position_index(values: Sequence[float], needle: float) -> int:
    return min(range(len(values)), key=lambda index: abs(values[index] - needle))


def _threshold_sensitivity(
    events: list[ClickEvent], current_threshold: float | None = None
) -> list[dict[str, object]]:
    """Return advisory selected-volume scenarios for alternate cutoffs.

    The current classifier decisions remain untouched. Each scenario recomputes
    what the selected population would be if the display risk-score cutoff
    changed. This is advisory capacity planning, not a third classifier.

    Args:
        events: Scored events from the current pipeline run.

    Returns:
        JSON-ready scenario rows for notebook and review presentation.
    """

    scores = [event.combined_score for event in events]
    total = len(events)
    if current_threshold is None:
        current_threshold, _ = _dynamic_knee_threshold(scores)
    rows = [
        _threshold_sensitivity_row(
            events,
            threshold=current_threshold,
            total=total,
            label="Kneedle dynamic cutoff",
            percentile=None,
            current=True,
        )
    ]
    for percentile in THRESHOLD_SENSITIVITY_PERCENTILES:
        threshold = _quantile(scores, percentile) if scores else 0.0
        rows.append(
            _threshold_sensitivity_row(
                events,
                threshold=threshold,
                total=total,
                label=_percentile_label(percentile),
                percentile=percentile,
                current=False,
            )
        )
    return rows


# pylint: disable=too-many-arguments
def _threshold_sensitivity_row(
    events: list[ClickEvent],
    *,
    threshold: float,
    total: int,
    label: str,
    percentile: float | None,
    current: bool,
) -> dict[str, object]:
    """Return one advisory threshold-sensitivity row.

    The ML cutoff is held at ``threshold`` while the rules path stays fixed at
    ``SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD``. Each row reports the ML-tail size,
    the (constant) rules-path size, and the resulting final OR selection, so every
    row is computed the same way and the selected Kneedle row stays comparable to
    the alternatives. Changing the ML threshold does not change the rules path.
    """

    rules_path_events = sum(
        1
        for event in events
        if event.heuristic_score >= SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
    )
    ml_tail_events = sum(1 for event in events if event.ml_score > threshold)
    selected_events = [
        event
        for event in events
        if event.heuristic_score >= SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
        or event.ml_score > threshold
    ]
    selected_ids = {event.event_id for event in selected_events}
    tier_counts = Counter(
        _advisory_tier(event, event.event_id in selected_ids) for event in events
    )
    return {
        "percentile": percentile,
        "label": label,
        "threshold": threshold,
        "ml_tail_events": ml_tail_events,
        "rules_path_events": rules_path_events,
        "final_or_events": len(selected_events),
        "selected_events": len(selected_events),
        "selected_rate": len(selected_events) / max(total, 1),
        "suppress": tier_counts.get("suppress", 0),
        "quarantine": tier_counts.get("quarantine", 0),
        "monitor": tier_counts.get("monitor", 0),
        "current": current,
        "estimated_human_false_positive_risk": (
            "Run-specific"
            if current
            else _threshold_false_positive_risk(percentile or 0.0)
        ),
        "primary_characteristics_captured": (
            "Dynamic elbow between ordinary traffic and the anomaly tail"
            if current
            else _threshold_primary_characteristics(percentile or 0.0)
        ),
    }


def _feature_lift_analysis(
    events: list[ClickEvent],
    feature_names: Sequence[str],
) -> list[dict[str, object]]:
    """Compare selected and non-selected feature distributions.

    This is a post-run lift diagnostic for an unlabelled model. It does not
    claim causal importance or model weighting; it reports which engineered
    fields separate flagged traffic from monitor traffic most strongly in the
    current batch.
    """

    feature_index = {name: idx for idx, name in enumerate(feature_names)}
    selected = [event for event in events if event.is_bot]
    monitor = [event for event in events if not event.is_bot]
    candidates = (
        ("log_query_domain_count", "Repeated query/domain concentration"),
        ("log_query_apex_domain_count", "Repeated query/apex-domain concentration"),
        ("log_apex_domain_count", "Registrable-domain concentration"),
        ("std_dev_ttc", "Mechanical timing regularity"),
        ("coefficient_variation_ttc", "Scale-invariant timing regularity"),
        ("query_entropy", "Query text randomness or repetition"),
        ("log_same_second_count", "Same-second burst behaviour"),
        ("log_device_count", "Region/browser/OS concentration"),
        ("query_is_nonsense", "Suspect query seed pattern"),
    )
    rows = []
    for feature_name, interpretation in candidates:
        if feature_name not in feature_index:
            continue
        idx = feature_index[feature_name]
        flagged_mean = _mean_feature(selected, idx)
        monitor_mean = _mean_feature(monitor, idx)
        higher_in_flagged = flagged_mean >= monitor_mean
        denominator = max(min(abs(flagged_mean), abs(monitor_mean)), 0.01)
        separation_lift = max(abs(flagged_mean), abs(monitor_mean)) / denominator
        rows.append(
            {
                "feature": feature_name,
                "flagged_mean": flagged_mean,
                "monitor_mean": monitor_mean,
                "separation_lift": separation_lift,
                "direction": "higher" if higher_in_flagged else "lower",
                "interpretation": interpretation,
            }
        )
    return sorted(
        rows,
        key=lambda row: float(row["separation_lift"]),
        reverse=True,
    )


def _mean_feature(events: Sequence[ClickEvent], feature_index: int) -> float:
    values = [
        event.features[feature_index]
        for event in events
        if feature_index < len(event.features)
    ]
    return sum(values) / len(values) if values else 0.0


def _derived_feature_stats(events: list[ClickEvent]) -> dict[str, object]:
    """Return report-ready statistics for new derivative features."""

    selected = [event for event in events if event.is_bot]
    monitor = [event for event in events if not event.is_bot]
    selected_queries = Counter(event.query for event in selected if event.query)
    top_query, top_query_count = (
        selected_queries.most_common(1)[0] if selected_queries else ("", 0)
    )
    low_std_count = sum(1 for event in selected if event.std_dev_ttc < 0.5)
    nonsense_count = sum(1 for event in selected if event.query_is_nonsense)
    return {
        "flagged_std_dev_ttc_mean": _mean_attr(selected, "std_dev_ttc"),
        "monitor_std_dev_ttc_mean": _mean_attr(monitor, "std_dev_ttc"),
        "flagged_low_std_dev_ttc_rate": low_std_count / max(len(selected), 1),
        "top_flagged_query": top_query,
        "top_flagged_query_count": top_query_count,
        "flagged_query_entropy_mean": _mean_attr(selected, "query_entropy"),
        "monitor_query_entropy_mean": _mean_attr(monitor, "query_entropy"),
        "flagged_nonsense_query_rate": nonsense_count / max(len(selected), 1),
    }


def _query_entropy_distribution(events: list[ClickEvent]) -> list[dict[str, object]]:
    """Return selected-versus-monitor query entropy distribution bins."""

    bins = (
        ("0.0-1.0", 0.0, 1.0),
        ("1.0-2.0", 1.0, 2.0),
        ("2.0-3.0", 2.0, 3.0),
        ("3.0-4.0", 3.0, 4.0),
        ("4.0+", 4.0, float("inf")),
    )
    selected_total = sum(1 for event in events if event.is_bot)
    monitor_total = sum(1 for event in events if not event.is_bot)
    rows: list[dict[str, object]] = []
    for label, lower, upper in bins:
        selected_count = sum(
            1
            for event in events
            if event.is_bot and lower <= event.query_entropy < upper
        )
        monitor_count = sum(
            1
            for event in events
            if not event.is_bot and lower <= event.query_entropy < upper
        )
        rows.append(
            {
                "bin": label,
                "selected_events": selected_count,
                "selected_rate": selected_count / max(selected_total, 1),
                "monitor_events": monitor_count,
                "monitor_rate": monitor_count / max(monitor_total, 1),
            }
        )
    return rows


def _mean_attr(events: Sequence[ClickEvent], attr_name: str) -> float:
    values = [float(getattr(event, attr_name)) for event in events]
    return sum(values) / len(values) if values else 0.0


def _threshold_false_positive_risk(percentile: float) -> str:
    """Return advisory human false-positive risk for a percentile scenario."""

    if percentile < 0.975:
        return "High"
    if percentile < 0.99:
        return "Moderate"
    if percentile < 0.995:
        return "Low"
    return "Very low"


def _threshold_primary_characteristics(percentile: float) -> str:
    """Return the expected pattern emphasis for a percentile scenario."""

    if percentile < 0.975:
        return "Broad behavioural shifts and moderate-speed anomalies"
    if percentile < 0.99:
        return (
            "Stronger classifier evidence around mechanical and high-velocity clusters"
        )
    if percentile < 0.995:
        return "Extreme anomalies and stronger timing or repetition evidence"
    return "Strictest structural automation and scripted repetition patterns"


def _advisory_tier(event: ClickEvent, selected: bool) -> str:
    """Return the tier an event would have in an advisory scenario."""

    if not selected:
        return "monitor"
    if _assign_evidence_tier(event) == 1:
        return "suppress"
    return "quarantine"


def _percentile_label(percentile: float) -> str:
    """Return a compact display label for a percentile scenario."""

    value = percentile * 100
    if value.is_integer():
        return f"{int(value)}th percentile"
    return f"{value:g}th percentile"


def _assign_operational_tier(event: ClickEvent) -> str:
    """Assign the operational handling tier for a scored event."""

    if not event.is_bot:
        return "monitor"
    tier = event.evidence_tier or _assign_evidence_tier(event)
    if tier == 1:
        return "suppress"
    return "quarantine"


def _assign_evidence_tier(event: ClickEvent) -> int:
    """Assign review tiers from classifier agreement."""

    if not event.is_bot:
        return 0
    heuristic_flag = (
        event.heuristic_flag
        if event.flags_assigned
        else event.heuristic_score >= SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
    )
    ml_flag = (
        event.ml_flag
        if event.flags_assigned
        else event.ml_score > ML_AGREEMENT_THRESHOLD
    )
    if heuristic_flag and ml_flag:
        return 1
    if heuristic_flag:
        return 2
    if ml_flag:
        return 3
    return 0


def optimize_threshold(
    risk_scores: Sequence[float],
    heuristic_scores: Sequence[float],
    fp_weight: float = 5.0,
    fn_weight: float = 1.0,
) -> dict[str, dict[str, float | int | str]]:
    """Return cost-sensitive proxy thresholds for stakeholder review.

    Labels are not fabricated. Instead, the top one percent of
    heuristic scores are treated as a proxy-positive set for threshold planning.
    The equal-cost baseline uses equal false-positive and false-negative proxy
    costs. The conservative threshold is retained only as optional sensitivity
    analysis when false positives are more expensive.

    Args:
        risk_scores: Bounded combined scores.
        heuristic_scores: Rule-based scores aligned to ``risk_scores``.
        fp_weight: Relative cost of flagging legitimate traffic.
        fn_weight: Relative cost of missing bot traffic.

    Returns:
        Advisory thresholds. They support reporting and operational tuning but
        do not create calibrated fraud probabilities.
    """

    if not risk_scores:
        return {}
    heuristic_cutoff = _quantile(list(heuristic_scores), 0.99)
    proxy_positive = [score >= heuristic_cutoff for score in heuristic_scores]
    candidate_thresholds = _proxy_candidate_thresholds(risk_scores)
    equal_cost = _best_proxy_threshold(
        candidate_thresholds,
        risk_scores,
        proxy_positive,
        fp_weight=1.0,
        fn_weight=1.0,
        recall_weight=1.0,
    )
    conservative = _best_proxy_threshold(
        candidate_thresholds,
        risk_scores,
        proxy_positive,
        fp_weight=fp_weight,
        fn_weight=fn_weight,
        recall_weight=0.5,
    )
    recall_sensitivity = _best_proxy_threshold(
        candidate_thresholds,
        risk_scores,
        proxy_positive,
        fp_weight=1.0,
        fn_weight=max(fn_weight, 1.0),
        recall_weight=2.0,
    )
    return {
        "equal_cost_baseline": {
            **equal_cost,
            "label": "Equal-cost baseline",
            "fp_weight": 1.0,
            "fn_weight": 1.0,
            "scenario_role": "equal_cost_baseline",
        },
        "fp_avoidant_sensitivity": {
            **conservative,
            "label": "Optional FP-avoidant sensitivity (5:1)",
            "fp_weight": fp_weight,
            "fn_weight": fn_weight,
            "scenario_role": "optional_sensitivity",
        },
        "recall_sensitivity": {
            **recall_sensitivity,
            "label": "Optional recall sensitivity",
            "fp_weight": 1.0,
            "fn_weight": max(fn_weight, 1.0),
            "scenario_role": "optional_sensitivity",
        },
    }


def _proxy_candidate_thresholds(scores: Sequence[float]) -> list[float]:
    """Return bounded percentile candidates for cost-threshold simulation."""

    if not scores:
        return [1.0]
    percentiles = (
        0.90,
        0.925,
        0.95,
        0.965,
        0.975,
        0.985,
        0.99,
        0.995,
        0.9975,
        0.999,
    )
    return sorted({_quantile(list(scores), percentile) for percentile in percentiles})


# pylint: disable=too-many-arguments,too-many-locals
def _best_proxy_threshold(
    thresholds: Sequence[float],
    combined_scores: Sequence[float],
    proxy_positive: Sequence[bool],
    *,
    fp_weight: float,
    fn_weight: float,
    recall_weight: float,
) -> dict[str, float | int]:
    best: dict[str, float | int] | None = None
    best_utility: float | None = None
    total_positive = max(sum(proxy_positive), 1)
    for threshold in thresholds:
        predicted = [score >= threshold for score in combined_scores]
        true_positive = sum(
            1
            for is_predicted, is_positive in zip(predicted, proxy_positive)
            if is_predicted and is_positive
        )
        false_positive = sum(
            1
            for is_predicted, is_positive in zip(predicted, proxy_positive)
            if is_predicted and not is_positive
        )
        false_negative = sum(
            1
            for is_predicted, is_positive in zip(predicted, proxy_positive)
            if not is_predicted and is_positive
        )
        selected = sum(predicted)
        precision = true_positive / max(selected, 1)
        recall = true_positive / total_positive
        error_cost = (fp_weight * false_positive) + (fn_weight * false_negative)
        utility = (
            precision
            + (recall_weight * recall)
            - (error_cost / max(len(combined_scores), 1))
        )
        row: dict[str, float | int] = {
            "combined_score_threshold": threshold,
            "selected_events": selected,
            "proxy_precision": precision,
            "proxy_recall": recall,
            "proxy_error_cost": error_cost,
            "proxy_utility": utility,
        }
        if best_utility is None or utility > best_utility:
            best = row
            best_utility = utility
    return best or {
        "combined_score_threshold": 1.0,
        "selected_events": 0,
        "proxy_precision": 0.0,
        "proxy_recall": 0.0,
        "proxy_error_cost": 0.0,
        "proxy_utility": 0.0,
    }


def _method_disagreement(
    events: Iterable[ClickEvent],
    ml_threshold: float = ML_AGREEMENT_THRESHOLD,
) -> list[tuple[str, int]]:
    """Count whether heuristic and ML evidence agree at action thresholds."""

    counts: Counter[str] = Counter()
    for event in events:
        heuristic_high = event.heuristic_score >= SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
        ml_high = event.ml_score > ml_threshold
        if heuristic_high and ml_high:
            counts["Heuristic + ML"] += 1
        elif heuristic_high:
            counts["Heuristic only"] += 1
        elif ml_high:
            counts["ML only"] += 1
        else:
            counts["Neither strong"] += 1
    return [(bucket, counts.get(bucket, 0)) for bucket in METHOD_BUCKETS]


def _selected_method_counts(events: list[ClickEvent]) -> dict[str, int]:
    """Return selected-event method buckets in report display order."""

    return _ordered_counter(
        Counter(_event_method_bucket(event) for event in events),
        METHOD_BUCKETS,
    )


def _anomaly_classes(events: list[ClickEvent]) -> dict[str, object]:
    """Build honest agreement-tier summaries for selected events."""

    selected_events = [event for event in events if event.is_bot]
    tier_metadata = {
        1: {
            "class_id": "tier_1_high_confidence",
            "label": "Tier 1 (High Confidence)",
            "description": "Both the heuristic and ML classifiers flagged the event.",
            "filter": "evidence_tier == 1",
            "review_action": "Prioritise for suppression review after policy approval.",
        },
        2: {
            "class_id": "tier_2_medium_confidence",
            "label": "Tier 2 (Medium Confidence)",
            "description": "Only the rules-based heuristic classifier flagged the event.",
            "filter": "evidence_tier == 2",
            "review_action": "Quarantine or sample selected anomalies before action.",
        },
        3: {
            "class_id": "tier_3_low_confidence_quarantine",
            "label": "Tier 3 (Low Confidence / Quarantine)",
            "description": "Only the ML classifier flagged the event.",
            "filter": "evidence_tier == 3",
            "review_action": "Quarantine, sample, or monitor; do not suppress automatically.",
        },
    }
    class_groups: dict[int, list[ClickEvent]] = {tier: [] for tier in tier_metadata}
    for event in selected_events:
        evidence_tier = event.evidence_tier or _assign_evidence_tier(event)
        if evidence_tier in class_groups:
            class_groups[evidence_tier].append(event)

    ml_only_population = [
        event for event in selected_events if _event_method_bucket(event) == "ML only"
    ]
    class_rows = []
    for tier, metadata in tier_metadata.items():
        class_events = class_groups[tier]
        row = {
            **metadata,
            "evidence_tier": tier,
            "confidence_proxy": CONFIDENCE_BY_TIER[tier],
            "count": len(class_events),
            "tier_counts": _ordered_counter(
                Counter(event.operational_tier for event in class_events),
                ("suppress", "quarantine", "monitor"),
            ),
            "method_counts": _ordered_counter(
                Counter(_event_method_bucket(event) for event in class_events),
                METHOD_BUCKETS,
            ),
            "dominant_rules": _dominant_rule_counts(class_events),
            "examples": _anomaly_examples(class_events),
        }
        if tier == 3:
            row["dominant_rules"] = []
            row["examples"] = _anomaly_examples(class_events, include_rules=False)
            row["population_count"] = len(ml_only_population)
            row["population_scope"] = (
                "All selected events flagged by the ML classifier without the "
                "heuristic classifier also firing."
            )
            row["rule_evidence_note"] = (
                "Low-weight heuristic rules may be present, but the event did "
                "not cross the heuristic classifier threshold."
            )
        class_rows.append(row)

    return {
        "scope": (
            "Operational evidence tiers derived from agreement between the "
            "rules-based heuristic classifier and the ML classifier; these are "
            "not proven fraud labels."
        ),
        "selected_event_count": len(selected_events),
        "classified_selected_event_count": sum(
            len(group) for group in class_groups.values()
        ),
        "ml_only_population_count": len(ml_only_population),
        "classes": class_rows,
        "filtering_options": _anomaly_filtering_options(),
    }


def _event_method_bucket(event: ClickEvent) -> str:
    """Return the heuristic/ML agreement bucket for one event."""

    if event.flags_assigned:
        heuristic_flag = event.heuristic_flag
        ml_flag = event.ml_flag
    else:
        heuristic_flag = event.heuristic_score >= SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
        ml_flag = event.ml_score > ML_AGREEMENT_THRESHOLD
    if heuristic_flag and ml_flag:
        return "Heuristic + ML"
    if heuristic_flag:
        return "Heuristic only"
    if ml_flag:
        return "ML only"
    return "Neither strong"


def _ordered_counter(counter: Counter, keys: tuple[str, ...]) -> dict[str, int]:
    return {key: counter.get(key, 0) for key in keys if counter.get(key, 0)}


def _dominant_rule_counts(events: list[ClickEvent]) -> list[dict[str, object]]:
    """Return the most common rule IDs among a set of events."""

    counter: Counter[str] = Counter(
        contribution.rule_id
        for event in events
        for contribution in event.rule_contributions
    )
    metadata = {
        contribution.rule_id: {
            "label": contribution.label,
            "family": contribution.family,
            "strength": contribution.strength,
        }
        for event in events
        for contribution in event.rule_contributions
    }
    return [
        {"rule_id": rule_id, "count": count, **metadata.get(rule_id, {})}
        for rule_id, count in counter.most_common(8)
    ]


def _anomaly_examples(
    events: list[ClickEvent],
    *,
    include_rules: bool = True,
) -> list[dict[str, object]]:
    """Return compact, high-scoring examples for a report class."""

    examples = sorted(events, key=lambda event: event.combined_score, reverse=True)[:3]
    rows = [
        {
            "event_id": event.event_id,
            "operational_tier": event.operational_tier,
            "domain": event.domain,
            "query": event.query,
            "heuristic_score": round(event.heuristic_score, 4),
            "ml_score": round(event.ml_score, 4),
            "combined_score": round(event.combined_score, 4),
            "method_bucket": _event_method_bucket(event),
            "reasons": event.reasons[:5],
            "rule_contributions": [
                {
                    "rule_id": contribution.rule_id,
                    "label": contribution.label,
                    "reason": contribution.reason,
                    "family": contribution.family,
                    "strength": contribution.strength,
                    "applied_weight": round(contribution.applied_weight, 4),
                }
                for contribution in sorted(
                    event.rule_contributions,
                    key=lambda item: item.applied_weight,
                    reverse=True,
                )[:5]
            ],
        }
        for event in examples
    ]
    if include_rules:
        for row, event in zip(rows, examples):
            row["rule_ids"] = [
                contribution.rule_id for contribution in event.rule_contributions
            ]
    return rows


def _anomaly_filtering_options() -> list[dict[str, str]]:
    return [
        {
            "name": "Tier 1 suppression review",
            "filter": "evidence_tier == 1",
            "use": (
                "Start with events where both classifiers agree. "
                "Still requires policy approval because labels are unavailable."
            ),
        },
        {
            "name": "Tier 2 rules-only review",
            "filter": "evidence_tier == 2",
            "use": "Review transparent heuristic-only detections before suppression.",
        },
        {
            "name": "Tier 3 ML quarantine",
            "filter": "evidence_tier == 3",
            "use": (
                "Sample or quarantine ML-only detections; "
                "do not treat it as proven fraud without labels."
            ),
        },
    ]


def _selected_event_dicts(events: list[ClickEvent]) -> list[dict[str, object]]:
    """Return selected events with review classification fields attached."""

    rows = []
    for event in events:
        row = next(iter_event_dicts([event]))
        evidence_tier = event.evidence_tier or _assign_evidence_tier(event)
        row["evidence_tier"] = evidence_tier
        row["confidence_proxy"] = CONFIDENCE_BY_TIER.get(evidence_tier, "NONE")
        row["method_bucket"] = _event_method_bucket(event)
        rows.append(row)
    return rows


def _write_predictions(path: Path, events: Iterable[ClickEvent]) -> None:
    with atomic_text_writer(path) as handle:
        handle.write("event_id\tis_bot\n")
        for event in events:
            handle.write(f"{event.event_id}\t{event.is_bot}\n")


def _write_extended_predictions(path: Path, events: Iterable[ClickEvent]) -> None:
    """Write the review-facing extended prediction file."""

    header = [
        "event_id",
        "is_bot",
        "evidence_tier",
        "confidence_proxy",
        "heuristic_score",
        "ml_score",
        "method_bucket",
        "std_dev_ttc",
        "query_entropy",
    ]
    with atomic_text_writer(path) as handle:
        handle.write("\t".join(header) + "\n")
        for event in events:
            row = [
                event.event_id,
                str(event.is_bot),
                str(event.evidence_tier),
                event.confidence_proxy,
                f"{event.heuristic_score:.6f}",
                f"{event.ml_score:.6f}",
                _event_method_bucket(event),
                f"{event.std_dev_ttc:.6f}",
                f"{event.query_entropy:.6f}",
            ]
            handle.write("\t".join(row) + "\n")


def _write_json(path: Path, payload: object) -> None:
    _write_text_atomic(path, json.dumps(payload, indent=2))


def _write_features(
    path: Path, feature_names: list[str], events: Sequence[ClickEvent]
) -> None:
    """Write feature vectors after validating feature-name alignment.

    Raises:
        ValueError: If any event's feature vector length differs from
            ``feature_names``.
    """

    for event in events:
        if len(event.features) != len(feature_names):
            raise ValueError(
                f"{event.event_id} has {len(event.features)} features; "
                f"expected {len(feature_names)}"
            )
    with atomic_text_writer(path) as handle:
        handle.write("\t".join(["event_id", *feature_names]) + "\n")
        for event in events:
            values = [f"{value:.6f}" for value in event.features]
            handle.write("\t".join([event.event_id, *values]) + "\n")


def _write_text_atomic(path: Path, text: str) -> None:
    with atomic_text_writer(path) as handle:
        handle.write(text)


def _normalize_reason(reason: str) -> str:
    """Collapse event-specific reason strings into stable summary labels."""

    reason = re.sub(r"\d+ clicks in the same second", "same-second click burst", reason)
    reason = re.sub(
        r"query/domain repeated \d+ times", "repeated query/domain pair", reason
    )
    reason = re.sub(r"query repeated \d+ times", "repeated query", reason)
    reason = re.sub(
        r"confirmed query repetition \(query/domain \d+, query \d+\)",
        "confirmed query repetition",
        reason,
    )
    reason = re.sub(
        r"exact time-to-click reused \d+ times", "reused exact time-to-click", reason
    )
    reason = re.sub(
        r"high-volume clicked domain \(\d+\)", "high-volume clicked domain", reason
    )
    reason = re.sub(
        r"heavy region/browser/os cluster \(\d+\)",
        "heavy region/browser/OS cluster",
        reason,
    )
    reason = re.sub(
        r"dense burst repetition cluster \(device \d+, same-second \d+, (query/domain|query) \d+\)",
        "dense burst repetition cluster",
        reason,
    )
    reason = re.sub(
        r"concentrated ct context \([^)]+\)",
        "concentrated ct context",
        reason,
    )
    reason = re.sub(
        r"regular inter-arrival timing \(\d+ clicks, mean [\d.]+s, cv [\d.]+\)",
        "regular inter-arrival timing",
        reason,
    )
    return reason

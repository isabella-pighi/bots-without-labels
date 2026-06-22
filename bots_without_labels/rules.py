"""Explainable, role-driven heuristic rules.

The rule detector is the transparent half of the system: every contribution to a
row's score carries a human-readable reason, so a reviewer can see *why* an event
was flagged. Rules are derived from column roles and adapt their thresholds to
the batch, which is how the click-specific behaviour (repeated query/domain,
reused time-to-click, same-second bursts, mechanical timing) emerges on a click
log without being hardcoded.

Each rule is either ``strong`` (direct mechanical or replay evidence, applied at
full weight) or ``supporting`` (weaker context, whose combined weight is capped),
mirroring how an analyst weighs evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

import numpy as np

from .features import FeatureSet
from .ingest import Schema

# Evidence strengths.
STRONG = "strong"
SUPPORTING = "supporting"
SUPPORTING_CAP = 0.24

# Rule weights. No single strong rule reaches the 0.70 heuristic cutoff, so one
# signal never flags alone; two strong replay signals, or a burst plus timing,
# clear it. Exact replay (a repeated free-text string, a reused exact value) is
# weighted highest because legitimate users rarely repeat either many times.
W_TEXT_REPEAT = 0.45
W_NUMERIC_REUSE = 0.30
W_SAME_INSTANT_BURST = 0.22
W_LOCAL_BURST = 0.20
W_REGULAR_TIMING = 0.20
W_CATEGORICAL_CONCENTRATION = 0.10
W_CONTEXT_CLUSTER = 0.10
W_LOW_ENTROPY = 0.10

# Adaptive-threshold guardrails.
COUNT_PERCENTILE = 0.99
TEXT_REPEAT_FLOOR = 10
NUMERIC_REUSE_FLOOR = 10
CONCENTRATION_FLOOR = 50
SAME_INSTANT_FLOOR = 4
LOCAL_BURST_FLOOR = 5
MIN_CARDINALITY_FOR_CONCENTRATION = 20
REGULAR_TIMING_MIN_EVENTS = 8
REGULAR_TIMING_MAX_CV = 0.50
LOW_ENTROPY_MAX = 1.5
LOW_ENTROPY_MIN_LENGTH = 5


@dataclass
class RuleHit:
    """One rule's contribution to a single row's score."""

    rule_id: str
    label: str
    reason: str
    weight: float
    strength: str
    family: str
    applied_weight: float = 0.0


@dataclass
class RulesResult:
    """Per-row heuristic scores, reasons, and the thresholds used.

    Attributes:
        scores: ``(n_rows,)`` heuristic scores in ``[0, 1]``.
        hits: Per-row list of :class:`RuleHit` contributions.
        thresholds: JSON-ready adaptive threshold metadata.
    """

    scores: np.ndarray
    hits: list[list[RuleHit]]
    thresholds: dict[str, object] = field(default_factory=dict)

    def reasons(self) -> list[list[str]]:
        """Return the per-row reason strings."""

        return [[hit.reason for hit in row] for row in self.hits]


def apply_rules(frame, schema: Schema, feature_set: FeatureSet) -> RulesResult:
    """Score every row with the adaptive heuristic rules.

    Args:
        frame: The typed table.
        schema: Its inferred schema.
        feature_set: Features and context from
            :func:`~bots_without_labels.features.build_features`.

    Returns:
        A :class:`RulesResult`.
    """

    context = feature_set.context
    n_rows = context.n_rows
    thresholds: dict[str, object] = {}

    text_cols = _eligible(context.text_columns, context, any_cardinality=True)
    conc_cols = _eligible(context.categorical_columns, context)
    numeric_cols = _eligible(context.numeric_columns, context)

    text_thr = {
        c: _adaptive(context.count_values[c], TEXT_REPEAT_FLOOR, n_rows)
        for c in text_cols
    }
    conc_thr = {
        c: _adaptive(context.count_values[c], CONCENTRATION_FLOOR, n_rows)
        for c in conc_cols
    }
    num_thr = {
        c: _adaptive(context.count_values[c], NUMERIC_REUSE_FLOOR, n_rows)
        for c in numeric_cols
    }
    thresholds.update(
        {
            "text_repeat": text_thr,
            "categorical_concentration": conc_thr,
            "numeric_reuse": num_thr,
            "same_instant": SAME_INSTANT_FLOOR,
            "local_burst": LOCAL_BURST_FLOOR,
        }
    )

    context_thr = _distinct_percentile(context.context_count, CONCENTRATION_FLOOR)
    same_instant_thr = max(
        SAME_INSTANT_FLOOR, _distinct_percentile(context.timestamp_count, 0)
    )
    thresholds["context_cluster"] = context_thr

    entropy = _entropy_lookup(feature_set)
    lengths = {
        c: frame[c].astype("string").fillna("").str.len().to_numpy() for c in text_cols
    }

    hits: list[list[RuleHit]] = []
    scores = np.zeros(n_rows, dtype=float)
    for row in range(n_rows):
        row_hits: list[RuleHit] = []

        for col in text_cols:
            count = int(context.row_counts[col][row])
            if count > 1 and count >= text_thr[col]:
                row_hits.append(
                    _hit(
                        "repeat_value",
                        f"repeated {col} value",
                        f"{col} repeated {count} times",
                        W_TEXT_REPEAT,
                        STRONG,
                        "repetition",
                    )
                )
            ent = entropy.get(col)
            if (
                ent is not None
                and 0.0 < ent[row] <= LOW_ENTROPY_MAX
                and lengths[col][row] >= LOW_ENTROPY_MIN_LENGTH
            ):
                row_hits.append(
                    _hit(
                        "low_entropy",
                        f"low-entropy {col}",
                        f"low-entropy {col} string",
                        W_LOW_ENTROPY,
                        SUPPORTING,
                        "text",
                    )
                )

        for col in conc_cols:
            count = int(context.row_counts[col][row])
            if count >= conc_thr[col]:
                row_hits.append(
                    _hit(
                        "concentration",
                        f"high-volume {col} value",
                        f"high-volume {col} value ({count})",
                        W_CATEGORICAL_CONCENTRATION,
                        SUPPORTING,
                        "concentration",
                    )
                )

        for col in numeric_cols:
            count = int(context.row_counts[col][row])
            if count > 1 and count >= num_thr[col]:
                row_hits.append(
                    _hit(
                        "numeric_reuse",
                        f"reused {col} value",
                        f"exact {col} value reused {count} times",
                        W_NUMERIC_REUSE,
                        STRONG,
                        "repetition",
                    )
                )

        if context.context_count is not None:
            count = int(context.context_count[row])
            if count >= context_thr:
                row_hits.append(
                    _hit(
                        "context_cluster",
                        "heavy context cluster",
                        f"heavy context cluster ({count})",
                        W_CONTEXT_CLUSTER,
                        SUPPORTING,
                        "concentration",
                    )
                )

        if context.timestamp_count is not None:
            count = int(context.timestamp_count[row])
            if count >= same_instant_thr:
                row_hits.append(
                    _hit(
                        "same_instant_burst",
                        "same-instant burst",
                        f"{count} events in the same instant",
                        W_SAME_INSTANT_BURST,
                        STRONG,
                        "timing",
                    )
                )

        if context.burst_count is not None:
            burst = int(context.burst_count[row])
            if burst >= LOCAL_BURST_FLOOR:
                row_hits.append(
                    _hit(
                        "local_burst",
                        "dense burst",
                        f"dense local burst ({burst} events)",
                        W_LOCAL_BURST,
                        STRONG,
                        "timing",
                    )
                )

        if context.dt_cv is not None and context.group_size is not None:
            if (
                context.group_size[row] >= REGULAR_TIMING_MIN_EVENTS
                and context.dt_cv[row] <= REGULAR_TIMING_MAX_CV
            ):
                row_hits.append(
                    _hit(
                        "regular_timing",
                        "regular inter-arrival timing",
                        f"regular inter-arrival timing (cv {context.dt_cv[row]:.3f})",
                        W_REGULAR_TIMING,
                        STRONG,
                        "timing",
                    )
                )

        scores[row] = _cap_and_sum(row_hits)
        hits.append(row_hits)

    return RulesResult(scores=scores, hits=hits, thresholds=thresholds)


def _eligible(
    columns: list[str], context, *, any_cardinality: bool = False
) -> list[str]:
    """Filter columns that have enough distinct values for a count rule.

    Concentration and reuse only make sense when a value being frequent is
    surprising; on a low-cardinality column (a handful of categories) it is not.
    Text columns are always eligible because repeating a free-text string is
    itself the signal.
    """

    out = []
    for col in columns:
        distinct = len(context.count_values.get(col, []))
        if any_cardinality or distinct >= MIN_CARDINALITY_FOR_CONCENTRATION:
            out.append(col)
    return out


def _adaptive(count_values: list[int], absolute_floor: int, n_rows: int) -> int:
    percentile = _nearest_rank(count_values, COUNT_PERCENTILE)
    return max(absolute_floor, percentile)


def _distinct_percentile(counts, floor: int) -> int:
    """Return the percentile of distinct count values, bounded below by floor."""

    if counts is None:
        return floor
    distinct = sorted({int(value) for value in counts})
    percentile = _nearest_rank(distinct, COUNT_PERCENTILE) if distinct else 0
    return max(floor, percentile)


def _nearest_rank(values: list[int], percentile: float) -> int:
    positive = sorted(value for value in values if value > 0)
    if not positive:
        return 0
    index = max(0, ceil(len(positive) * percentile) - 1)
    return int(positive[index])


def _entropy_lookup(feature_set: FeatureSet) -> dict[str, np.ndarray]:
    lookup: dict[str, np.ndarray] = {}
    for col in feature_set.context.text_columns:
        name = f"{col}__entropy"
        if name in feature_set.names:
            lookup[col] = feature_set.matrix[:, feature_set.names.index(name)]
    return lookup


def _hit(
    rule_id: str, label: str, reason: str, weight: float, strength: str, family: str
) -> RuleHit:
    return RuleHit(
        rule_id=rule_id,
        label=label,
        reason=reason,
        weight=weight,
        strength=strength,
        family=family,
        applied_weight=weight,
    )


def _cap_and_sum(hits: list[RuleHit]) -> float:
    """Apply the supporting-evidence cap and return the bounded score."""

    for hit in hits:
        hit.applied_weight = hit.weight
    supporting = [hit for hit in hits if hit.strength == SUPPORTING]
    supporting_total = sum(hit.weight for hit in supporting)
    if supporting_total > SUPPORTING_CAP:
        scale = SUPPORTING_CAP / supporting_total
        for hit in supporting:
            hit.applied_weight = hit.weight * scale
    return float(min(sum(hit.applied_weight for hit in hits), 1.0))

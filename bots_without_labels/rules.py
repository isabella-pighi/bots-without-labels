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

from math import ceil
from dataclasses import dataclass, field

import numpy as np

from .features import FeatureSet
from .ingest import Schema

# Evidence strengths.
STRONG = "strong"
SUPPORTING = "supporting"
SUPPORTING_CAP = 0.24

# Rule weights. Only *timing* evidence is strong, because a same-instant cluster
# in a narrow context or mechanically regular pacing is genuinely rare in
# legitimate traffic. Repetition, concentration, and low entropy are *supporting*
# only (their combined weight is capped) because popular legitimate content
# repeats values and concentrates on popular contexts too -- a viral query or a
# common latency looks exactly like a low-volume replay to a count-based rule, so
# repetition alone must never flag. No single strong rule reaches the 0.70 cutoff;
# two corroborating timing signals (same-instant *and* a local burst, or regular
# pacing *and* a local burst) are required.
W_SAME_INSTANT_BURST = 0.40
W_LOCAL_BURST = 0.35
W_REGULAR_TIMING = 0.40
W_TEXT_REPEAT = 0.12
W_NUMERIC_REUSE = 0.12
W_CATEGORICAL_CONCENTRATION = 0.08
W_CONTEXT_CLUSTER = 0.10
W_LOW_ENTROPY = 0.06

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

    counts = context.count_values
    text_thr = {c: _adaptive(counts.get(c), TEXT_REPEAT_FLOOR) for c in text_cols}
    conc_thr = {c: _adaptive(counts.get(c), CONCENTRATION_FLOOR) for c in conc_cols}
    num_thr = {c: _adaptive(counts.get(c), NUMERIC_REUSE_FLOOR) for c in numeric_cols}
    context_thr = _adaptive(counts.get("__context__"), CONCENTRATION_FLOOR)
    same_instant_thr = _adaptive(counts.get("__timestamp__"), SAME_INSTANT_FLOOR)
    thresholds.update(
        {
            "text_repeat": text_thr,
            "categorical_concentration": conc_thr,
            "numeric_reuse": num_thr,
            "context_cluster": context_thr,
            "same_instant": same_instant_thr,
            "local_burst": LOCAL_BURST_FLOOR,
        }
    )

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
                        SUPPORTING,
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
                        SUPPORTING,
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

        if context.dt_cv is not None and context.run_size is not None:
            if (
                context.run_size[row] >= REGULAR_TIMING_MIN_EVENTS
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


def _adaptive(count_values, floor: int) -> int:
    """Return an adaptive count threshold, bounded below by ``floor``.

    The percentile is taken over the **distinct group sizes** (how often each
    distinct value occurs), not over per-row counts. This has two important
    properties:

    * On a flat/uniform log almost every value is unique, so the percentile is
      ~1 and the ``floor`` governs.
    * On a heavy-tailed log (a power-law of value popularity, as real logs have)
      the percentile rises above the floor, so a rule fires only on the
      genuinely over-represented tail and the false-positive rate stays bounded
      as the batch grows.

    Crucially it is robust to the bot fraction: bots that repeat are a *few
    distinct* values, so they barely move the distinct-size distribution and
    therefore do not inflate the very threshold meant to catch them.
    """

    if not count_values:
        return floor
    ordered = sorted(int(value) for value in count_values if value > 0)
    if not ordered:
        return floor
    index = max(0, ceil(len(ordered) * COUNT_PERCENTILE) - 1)
    return max(floor, ordered[index])


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

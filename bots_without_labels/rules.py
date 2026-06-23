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

from .features import BURST_WINDOW_SECONDS, FeatureSet
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

# Per-entity monotony: a high-volume actor whose own events are highly
# self-similar (low behavioural diversity) is automation evidence -- the botnet
# host beaconing to one C2, the scraper replaying one request shape. It is the
# per-entity, baseline-relative form of the concentration signal that the global
# concentration rule (rightly) keeps weak.
#
# But low diversity alone is not enough to escalate to a strong, on-its-own flag:
# a busy *legitimate* automated channel (a backup job, a keepalive, one client
# hammering one server) is just as monotonous as a beacon, and on real traffic
# these dominate the monotonous tail. When the log exposes a relational structure
# (>= 2 stable entity columns, e.g. source and destination), we therefore only
# escalate a monotonous entity that is also a *hub*: one that communicates with
# many distinct counterparts (a fan-in/fan-out star), which is what separates a
# C2 fanned to by many hosts from a single point-to-point channel. When no such
# structure can be detected, the rule falls back to firing on monotony alone.
W_ENTITY_MONOTONY = 0.70
ENTITY_MIN_EVENTS = 12
# Absolute ceiling: only an entity doing essentially *one* thing qualifies. It
# also keeps the rule dormant on low-dimensional logs (few columns -> every
# actor looks monotonous), where per-entity diversity carries no signal.
ENTITY_DIVERSITY_CEILING = 0.20
ENTITY_DIVERSITY_PERCENTILE = 0.10
# A hub/fan-in is convergence from (or to) *more than a pair* of distinct
# counterparts: a star needs at least this many spokes. Deliberately a small
# structural minimum, not tuned to any particular dataset's hub degree -- raising
# it toward a specific botnet's observed fan-out would be overfitting.
MIN_HUB_DEGREE = 3

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

    # Dense-timing evidence -- a same-instant collision (`same_instant_burst`) or
    # a short-window pile-up (`local_burst`) -- assumes the clock is fine enough
    # that within-window co-occurrence reflects genuine simultaneity. When the
    # timestamps are quantised to a grid at least as coarse as the burst window
    # (e.g. a minute-resolution flow log), a "same instant" is really a wide bin
    # holding many independent events, so every busy bin trips these rules on
    # benign volume. We therefore gate both on the measured timestamp resolution
    # and let the resolution-independent evidence (per-entity monotony, the hub
    # gate) carry the decision. The cost is that on such logs a bot whose *only*
    # tell is sub-window timing is unobservable at this grid -- but so is any
    # genuine burst, so the rules could not separate it from benign traffic
    # anyway. Resolution unknown (no or degenerate timestamp) leaves them active.
    resolution = context.timestamp_resolution
    dense_timing_active = resolution is None or resolution < BURST_WINDOW_SECONDS
    thresholds["timestamp_resolution"] = resolution
    thresholds["dense_timing_active"] = dense_timing_active

    # Adaptive per-entity diversity cut: the low tail of behavioural diversity
    # among entities with enough volume to baseline, capped by an absolute
    # ceiling so a log with no monotonous actors flags none.
    entity_cut = 0.0
    if context.entity_diversity is not None and context.entity_volume is not None:
        qualified = context.entity_volume >= ENTITY_MIN_EVENTS
        if qualified.any():
            entity_cut = min(
                ENTITY_DIVERSITY_CEILING,
                float(
                    np.quantile(
                        context.entity_diversity[qualified],
                        ENTITY_DIVERSITY_PERCENTILE,
                    )
                ),
            )
    thresholds["entity_diversity_cut"] = entity_cut
    thresholds["entity_columns"] = context.entity_columns

    # The relational hub discriminator is only meaningful when at least two stable
    # entity columns exist, so edges (entity -> counterpart) can be formed. With
    # one (or no) entity column there is no source/destination structure to read,
    # and the rule falls back to firing on monotony alone.
    entity_graph_active = (
        len(context.entity_columns) >= 2 and bool(context.entity_degree_by_col)
    )
    thresholds["entity_graph_active"] = entity_graph_active
    thresholds["min_hub_degree"] = MIN_HUB_DEGREE if entity_graph_active else None
    entity_value_arrays = {
        col: frame[col].astype("string").fillna("").to_numpy()
        for col in context.entity_columns
    }

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

        if dense_timing_active and context.timestamp_count is not None:
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

        if dense_timing_active and context.burst_count is not None:
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

        if context.entity_diversity is not None and context.entity_volume is not None:
            if entity_graph_active:
                hub = _hub_entity(row, context, entity_value_arrays, entity_cut)
                if hub is not None:
                    col, value, diversity, volume, degree = hub
                    row_hits.append(
                        _hit(
                            "entity_monotony",
                            "low-diversity high-volume hub entity",
                            f"{col} '{value}' repeats near-identical events "
                            f"(diversity {diversity:.2f} over {volume} events) while "
                            f"converging with {degree} distinct counterparts",
                            W_ENTITY_MONOTONY,
                            STRONG,
                            "entity",
                        )
                    )
            elif (
                context.entity_volume[row] >= ENTITY_MIN_EVENTS
                and context.entity_diversity[row] <= entity_cut
            ):
                row_hits.append(
                    _hit(
                        "entity_monotony",
                        "low-diversity high-volume entity",
                        f"entity repeats near-identical events "
                        f"(diversity {context.entity_diversity[row]:.2f} over "
                        f"{int(context.entity_volume[row])} events)",
                        W_ENTITY_MONOTONY,
                        STRONG,
                        "entity",
                    )
                )

        scores[row] = _cap_and_sum(row_hits)
        hits.append(row_hits)

    return RulesResult(scores=scores, hits=hits, thresholds=thresholds)


def _hub_entity(
    row: int,
    context,
    entity_value_arrays: dict[str, np.ndarray],
    entity_cut: float,
) -> tuple[str, str, float, int, int] | None:
    """Return the row's monotonous *hub* entity, or ``None`` if it has none.

    A qualifying entity is, in some entity column, high-volume
    (``>= ENTITY_MIN_EVENTS``), low-diversity (``<= entity_cut``), and a hub --
    communicating with at least :data:`MIN_HUB_DEGREE` distinct counterparts.
    When several entity columns qualify, the one with the highest degree (the
    most hub-like view of the row) is chosen.

    Returns ``(column, value, diversity, volume, degree)``.
    """

    best: tuple[str, str, float, int, int] | None = None
    for col in context.entity_columns:
        diversity = context.entity_diversity_by_col.get(col)
        volume = context.entity_volume_by_col.get(col)
        degree = context.entity_degree_by_col.get(col)
        if diversity is None or volume is None or degree is None:
            continue
        deg = int(degree[row])
        if (
            volume[row] >= ENTITY_MIN_EVENTS
            and diversity[row] <= entity_cut
            and deg >= MIN_HUB_DEGREE
        ):
            if best is None or deg > best[4]:
                best = (
                    col,
                    str(entity_value_arrays[col][row]),
                    float(diversity[row]),
                    int(volume[row]),
                    deg,
                )
    return best


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

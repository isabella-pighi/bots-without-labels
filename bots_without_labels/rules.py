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

# Asymmetric high-degree SOURCE endpoint (fan-out broadcaster): a value whose
# *out*-degree -- distinct counterparts it reaches from the source endpoint
# column -- is unusually large while its *in*-degree (reverse role) is far smaller,
# on a monotone service. The source column is the originating endpoint, taken by
# schema column order (source precedes destination in flow logs: SrcAddr before
# DstAddr, Source IP before Destination IP) -- a schema-driven signal, not a name
# match. This is the spam/scan/click-fraud broadcaster shape (a diverse directional
# bot reaching out to many peers), which the entity hub view misses because
# connecting to many counterparts inflates overall diversity.
#
# It deliberately does NOT fire on a passive fan-IN hub (a destination reached by
# many): a benign DNS resolver, NTP source, or load balancer is exactly that shape,
# and on real captures (CTU-13 / Rbot) those infra hubs were the dominant false
# positive when the rule was undirected. Fan-in command-and-control coverage is
# owned by the direction-agnostic hub escalation in entity_monotony, not here; this
# rule is aligned with its measured role (it fires 0 on the CICIDS fan-in C2, which
# entity_monotony carries). Strong, like entity monotony.
W_ASYMMETRIC_DEGREE = 0.70
# The degree floor is data-relative, not a fixed magic count: the upper-tail
# quantile of the *hub-subset* degrees (endpoints already reaching at least
# MIN_HUB_DEGREE counterparts), so the cut tracks the batch's own connectivity
# rather than a number tuned to one capture. The asymmetry factor requires the
# heavy-degree role to exceed the reverse role by an order of magnitude.
#
# These two are GUARDRAILS calibrated against limited evidence, NOT established
# general constants. On the one labelled split tested (CTU-13 / Neris) plus a
# synthetic broadcaster, the result is unchanged for asymmetry factors ~10-100,
# over-fires below ~10, and the rule disappears at >=200 (it exceeds Neris's own
# ratio). Generality to other families/scenarios is unproven and is a tracked
# follow-up; do not read these as scale-free.
DEGREE_FLOOR_PERCENTILE = 0.99
DEGREE_ASYMMETRY = 10

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


# ``schema`` is part of the stable detector-stage signature (load -> features ->
# rules) even though the rules currently read everything via the FeatureContext.
# pylint: disable-next=unused-argument
def apply_rules(frame, schema: Schema, feature_set: FeatureSet) -> RulesResult:
    """Score every row with the adaptive heuristic rules.

    Args:
        frame: The typed table.
        schema: Its inferred schema.
        feature_set: Features and context from
            :func:`~bots_without_labels.features.build_features`.

    Returns:
        A :class:`RulesResult`. Its ``thresholds`` dict is JSON-ready metadata on
        the adaptive thresholds actually applied: per-column maps under
        ``"text_repeat"``, ``"categorical_concentration"``, and
        ``"numeric_reuse"``, scalars under ``"context_cluster"``,
        ``"same_instant"``, and ``"local_burst"``, plus entity/actor-rule
        entries added below when those rules are active.
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
    # (e.g. a minute-resolution flow log), an *on-grid* "same instant" is really a
    # wide bin holding many independent events, so every busy bin would trip these
    # rules on benign volume. We therefore suppress them *per collision*, only
    # where the shared timestamp lies on that coarse grid -- a binning artifact.
    # An *off-grid* pile (e.g. many events at one sub-minute instant the clock did
    # record precisely) is genuine simultaneity and still fires, so a real burst
    # injected into a coarse-grid log stays observable. Grid unknown, or a grid
    # finer than the burst window, leaves the rules fully active.
    #
    # Limitation: on a coarse clock an *on-grid* burst is indistinguishable from a
    # busy bin and is suppressed; mixed-resolution or off-grid clock artefacts can
    # still surface co-occurrence that warrants review. Resolution-independent
    # evidence (per-entity monotony, the hub gate) carries the decision elsewhere.
    grid = context.timestamp_grid
    on_grid = context.timestamp_on_grid
    dense_timing_gated = on_grid is not None
    thresholds["timestamp_grid"] = grid
    thresholds["dense_timing_gated"] = dense_timing_gated

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
    entity_graph_active = len(context.entity_columns) >= 2 and bool(
        context.entity_degree_by_col
    )
    thresholds["entity_graph_active"] = entity_graph_active
    thresholds["min_hub_degree"] = MIN_HUB_DEGREE if entity_graph_active else None
    entity_value_arrays = {
        col: frame[col].astype("string").fillna("").to_numpy()
        for col in context.entity_columns
    }

    # Adaptive degree floor: the upper-tail quantile of degrees among endpoints
    # that are already hubs (>= MIN_HUB_DEGREE counterparts), so the cut is relative
    # to the batch's connectivity, not a fixed count.
    actor_graph_active = len(context.actor_columns) >= 2 and bool(
        context.actor_degree_by_col
    )
    degree_floor = _degree_floor(context) if actor_graph_active else None
    thresholds["actor_columns"] = context.actor_columns
    thresholds["actor_graph_active"] = actor_graph_active
    thresholds["degree_floor"] = degree_floor
    actor_value_arrays = {
        col: frame[col].astype("string").fillna("").to_numpy()
        for col in context.actor_columns
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

        suppressed = dense_timing_gated and bool(on_grid[row])
        if not suppressed and context.timestamp_count is not None:
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

        if not suppressed and context.burst_count is not None:
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

        if actor_graph_active and degree_floor is not None:
            star = _asymmetric_endpoint(row, context, degree_floor)
            if star is not None:
                col, degree, reverse, diversity, volume = star
                value = actor_value_arrays[col][row]
                row_hits.append(
                    _hit(
                        "asymmetric_degree",
                        "asymmetric high-degree source endpoint",
                        f"{col} '{value}' reaches {degree} distinct counterparts "
                        f"as a source while only {reverse} reach it back, on a "
                        f"monotone service "
                        f"(context diversity {diversity:.2f} over {volume} events)",
                        W_ASYMMETRIC_DEGREE,
                        STRONG,
                        "actor",
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

    Returns ``(column: str, value: str, diversity: float, volume: int,
    degree: int)``.
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
            # False positive: short-circuit guarantees ``best`` is a tuple here.
            # pylint: disable-next=unsubscriptable-object
            if best is None or deg > best[4]:
                best = (
                    col,
                    str(entity_value_arrays[col][row]),
                    float(diversity[row]),
                    int(volume[row]),
                    deg,
                )
    return best


def _degree_floor(context) -> float | None:
    """Adaptive degree cut: upper-tail quantile of hub-subset degrees.

    Takes the *per-node* degrees (one per distinct endpoint value, so a
    high-volume hub does not dominate by recurring on many rows), keeps those
    already hubs (``>= MIN_HUB_DEGREE``), and returns the
    :data:`DEGREE_FLOOR_PERCENTILE` quantile -- the connectivity an endpoint must
    exceed to be an unusually high degree for *this* batch. ``None`` when no
    endpoint reaches the structural hub minimum (no star to speak of).
    """

    hub = [value for value in context.actor_node_degrees if value >= MIN_HUB_DEGREE]
    if not hub:
        return None
    return float(np.quantile(hub, DEGREE_FLOOR_PERCENTILE))


def _asymmetric_endpoint(
    row: int, context, degree_floor: float
) -> tuple[str, int, int, float, int] | None:
    """Return the row's asymmetric high-degree *source* endpoint, or ``None``.

    A qualifying endpoint is, in the **source** actor column, high-volume
    (``>= ENTITY_MIN_EVENTS``), an unusually high *out*-degree
    (``degree >= degree_floor``), strongly *asymmetric* -- its out-degree exceeds
    its in-degree (reverse-role degree) by an order of magnitude
    (``degree >= DEGREE_ASYMMETRY * (reverse + 1)``) -- and monotone in service
    (context-only diversity ``<= ENTITY_DIVERSITY_CEILING``). This is the fan-out
    broadcaster shape (a source reaching many distinct counterparts).

    The source column is the originating endpoint, identified by schema column
    order: ``context.actor_columns`` is built in schema order, and the first actor
    endpoint column is the source (source precedes destination in flow logs --
    ``SrcAddr`` before ``DstAddr``, ``Source IP`` before ``Destination IP``). A
    schema-driven signal, not a name match, and not a magic constant.

    It deliberately does NOT fire on a passive fan-IN hub (a high in-degree
    destination reached by many) -- a benign DNS/NTP/load-balancer is exactly that
    shape and dominates the false positives on real captures. Fan-in C2 coverage is
    owned by the direction-agnostic hub escalation in ``entity_monotony``.

    Returns ``(source_column: str, out_degree: int, in_degree: int,
    diversity: float, volume: int)``.
    """

    if not context.actor_columns:
        return None
    source_col = context.actor_columns[0]
    deg = context.actor_degree_by_col.get(source_col)
    rev = context.actor_reverse_degree_by_col.get(source_col)
    vol = context.actor_volume_by_col.get(source_col)
    div = context.actor_ctx_diversity_by_col.get(source_col)
    if deg is None or rev is None or vol is None or div is None:
        return None
    degree = int(deg[row])
    reverse = int(rev[row])
    if (
        vol[row] >= ENTITY_MIN_EVENTS
        and degree >= degree_floor
        and degree >= DEGREE_ASYMMETRY * (reverse + 1)
        and div[row] <= ENTITY_DIVERSITY_CEILING
    ):
        return (source_col, degree, reverse, float(div[row]), int(vol[row]))
    return None


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

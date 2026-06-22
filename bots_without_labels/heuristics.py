"""Rule-based anomaly heuristics for Bots Without Labels click events."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from math import ceil, sqrt

from .data import ClickEvent, RuleContribution, pseudo_session_groups

REGULAR_INTERARRIVAL_MIN_EVENTS = 8
REGULAR_INTERARRIVAL_MAX_MEAN_SECONDS = 300.0
REGULAR_INTERARRIVAL_MAX_CV = 0.50
REGULAR_INTERARRIVAL_WEIGHT = 0.10
MODERATE_LONG_TTC_MIN_MS = 20_000
MODERATE_LONG_TTC_MAX_MS = 60_000
MODERATE_LONG_TTC_WEIGHT = 0.06
TTC_REUSE_COUNT_FLOOR = 40
TTC_REUSE_COUNT_PERCENTILE = 0.99
DENSE_BURST_REPETITION_MIN_SAME_SECOND = 5
DENSE_BURST_REPETITION_WEIGHT = 0.12
CONFIRMED_QUERY_REPETITION_WEIGHT = 0.12
COUNTRY_CONTEXT_MIN_COUNT = 1_000
COUNTRY_CONTEXT_MIN_RATE = 0.10
COUNTRY_CONTEXT_WEIGHT = 0.06
COUNTRY_CONTEXT_CONDITION = (
    "ct count >= adaptive percentile threshold and "
    "(query_count >= adaptive percentile threshold or "
    "query_domain_count >= adaptive percentile threshold) "
    "and (device_count >= adaptive percentile threshold "
    "or same_second_count >= 5)"
)
ADAPTIVE_COUNT_PERCENTILE = 0.99
SAME_SECOND_COUNT_FLOOR = 4
SUPPORTING_RULE_CAP = 0.24
STRONG = "strong"
SUPPORTING = "supporting"


@dataclass(frozen=True)
class AdaptiveThreshold:  # pylint: disable=too-many-instance-attributes
    """Threshold selected from the current batch with fixed guardrails."""

    rule_id: str
    label: str
    threshold: int
    threshold_mode: str
    percentile: float
    absolute_floor: int
    rate_floor: int | None
    selected_from: str

    def to_dict(self) -> dict[str, int | float | str | None]:
        """Return a JSON-serialisable representation of the threshold."""

        return asdict(self)


def apply_heuristics(
    events: list[ClickEvent],
    counters: dict[str, Counter],
) -> dict[str, dict[str, int | float | str | None]]:
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """Apply rule-based anomaly evidence to each event.

    The function mutates each event with reasons, rule contributions, and a
    capped heuristic score. Threshold values are derived once from the batch so
    all events in the run are scored against the same guardrails.

    Args:
        events: Click events to score in place.
        counters: Batch counters returned by ``build_features``.

    Returns:
        JSON-ready adaptive threshold metadata keyed by rule ID.

    Raises:
        ValueError: If a regular-interarrival contribution violates the
            strong-only invariant used by contribution capping.
    """

    total = max(len(events), 1)
    threshold_summary = _adaptive_thresholds(counters, total)
    domain_hi = int(threshold_summary["high_volume_domain"]["threshold"])
    query_hi = int(threshold_summary["repeat_query"]["threshold"])
    query_domain_hi = int(threshold_summary["repeat_query_domain"]["threshold"])
    device_hi = int(threshold_summary["heavy_device_cluster"]["threshold"])
    same_second_hi = int(threshold_summary["same_second_burst"]["threshold"])
    country_hi = int(threshold_summary["concentrated_ct_context"]["threshold"])
    ttc_hi = int(threshold_summary["reused_ttc"]["threshold"])
    regular_interarrival = _regular_interarrival_contributions(events)
    country_counts = counters.get("country", Counter())

    for event in events:
        reasons: list[str] = []
        contributions: list[RuleContribution] = []

        qd_count = counters["query_domain"][(event.query, event.domain)]
        if qd_count >= query_domain_hi:
            reason = f"query/domain repeated {qd_count} times"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "repeat_query_domain",
                    "Repeated query/domain pair",
                    reason,
                    0.32,
                    qd_count,
                    query_domain_hi,
                    "query_domain_count >= adaptive percentile threshold",
                    "adaptive_percentile",
                    family="repetition",
                )
            )

        q_count = counters["query"][event.query]
        if q_count >= query_hi:
            reason = f"query repeated {q_count} times"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "repeat_query",
                    "Repeated query",
                    reason,
                    0.18,
                    q_count,
                    query_hi,
                    "query_count >= adaptive percentile threshold",
                    "adaptive_percentile",
                    family="repetition",
                )
            )

        if qd_count >= query_domain_hi and q_count >= query_hi:
            reason = (
                f"confirmed query repetition (query/domain {qd_count}, query {q_count})"
            )
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "confirmed_query_repetition",
                    "Confirmed query repetition",
                    reason,
                    CONFIRMED_QUERY_REPETITION_WEIGHT,
                    f"query_domain={qd_count}; query={q_count}",
                    f"query_domain>={query_domain_hi}; query>={query_hi}",
                    (
                        "query_domain_count >= adaptive percentile threshold "
                        "and query_count >= adaptive percentile threshold"
                    ),
                    "adaptive_percentile",
                    family="repetition",
                )
            )

        d_count = counters["domain"][event.domain]
        if d_count >= domain_hi:
            reason = f"high-volume clicked domain ({d_count})"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "high_volume_domain",
                    "High-volume clicked domain",
                    reason,
                    0.10,
                    d_count,
                    domain_hi,
                    "domain_count >= adaptive percentile threshold",
                    "adaptive_percentile",
                    SUPPORTING,
                    "volume",
                )
            )

        device_count = counters["device"][(event.region, event.browser, event.os)]
        if device_count >= device_hi:
            reason = f"heavy region/browser/os cluster ({device_count})"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "heavy_device_cluster",
                    "Heavy region/browser/os cluster",
                    reason,
                    0.08,
                    device_count,
                    device_hi,
                    "device_count >= adaptive percentile threshold",
                    "adaptive_percentile",
                    SUPPORTING,
                    "cluster",
                )
            )

        ttc_count = counters["ttc"][event.ttc]
        if event.ttc >= 0 and ttc_count >= ttc_hi:
            reason = f"exact time-to-click reused {ttc_count} times"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "reused_ttc",
                    "Reused exact time-to-click",
                    reason,
                    0.16,
                    ttc_count,
                    ttc_hi,
                    (
                        "ttc >= 0 and ttc_count >= adaptive 99th percentile "
                        "threshold with absolute floor 40"
                    ),
                    "adaptive_percentile",
                    family="timing",
                )
            )

        same_second = counters["second"][event.event_time]
        if same_second >= same_second_hi:
            reason = f"{same_second} clicks in the same second"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "same_second_burst",
                    "Same-second click burst",
                    reason,
                    0.12,
                    same_second,
                    same_second_hi,
                    "same_second_count >= adaptive percentile threshold",
                    "adaptive_percentile",
                    family="timing",
                )
            )

        if (
            device_count >= device_hi
            and same_second >= DENSE_BURST_REPETITION_MIN_SAME_SECOND
            and (q_count >= query_hi or qd_count >= query_domain_hi)
        ):
            repeated_observed = max(q_count, qd_count)
            repeated_label = "query/domain" if qd_count >= query_domain_hi else "query"
            reason = (
                "dense burst repetition cluster "
                f"(device {device_count}, same-second {same_second}, "
                f"{repeated_label} {repeated_observed})"
            )
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "dense_burst_repetition_cluster",
                    "Dense burst repetition cluster",
                    reason,
                    DENSE_BURST_REPETITION_WEIGHT,
                    (
                        f"device={device_count}; same_second={same_second}; "
                        f"{repeated_label}={repeated_observed}"
                    ),
                    (
                        f"device>={device_hi}; "
                        f"same_second>={DENSE_BURST_REPETITION_MIN_SAME_SECOND}; "
                        "repeated_query_pattern"
                    ),
                    (
                        "device_count >= adaptive percentile threshold "
                        "and same_second_count >= 5 and "
                        "(query_count >= adaptive percentile threshold or "
                        "query_domain_count >= adaptive percentile threshold)"
                    ),
                    "adaptive_percentile",
                    family="compound",
                )
            )

        country = event.params.get("ct", "")
        country_count = country_counts[country] if country else 0
        has_repetition = q_count >= query_hi or qd_count >= query_domain_hi
        has_cluster_or_burst = (
            device_count >= device_hi
            or same_second >= DENSE_BURST_REPETITION_MIN_SAME_SECOND
        )
        if country_count >= country_hi and has_repetition and has_cluster_or_burst:
            repeated_observed = max(q_count, qd_count)
            repeated_label = "query/domain" if qd_count >= query_domain_hi else "query"
            cluster_label = (
                f"device {device_count}"
                if device_count >= device_hi
                else f"same-second {same_second}"
            )
            reason = (
                "concentrated ct context "
                f"({country} {country_count}, {cluster_label}, "
                f"{repeated_label} {repeated_observed})"
            )
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "concentrated_ct_context",
                    "Concentrated ct context",
                    reason,
                    COUNTRY_CONTEXT_WEIGHT,
                    (
                        f"ct={country}; ct_count={country_count}; "
                        f"{cluster_label}; {repeated_label}={repeated_observed}"
                    ),
                    (
                        f"ct_count>={country_hi}; repeated_query_pattern; "
                        "device_or_same_second_cluster"
                    ),
                    COUNTRY_CONTEXT_CONDITION,
                    "adaptive_percentile",
                    SUPPORTING,
                    "context",
                )
            )

        if 0 <= event.ttc <= 250:
            reason = "implausibly fast click"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "fast_click",
                    "Implausibly fast click",
                    reason,
                    0.18,
                    event.ttc,
                    250,
                    "0 <= ttc <= threshold",
                    family="timing",
                )
            )
        elif MODERATE_LONG_TTC_MIN_MS <= event.ttc <= MODERATE_LONG_TTC_MAX_MS:
            reason = "moderately long time-to-click"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "moderate_long_ttc",
                    "Moderately long time-to-click",
                    reason,
                    MODERATE_LONG_TTC_WEIGHT,
                    event.ttc,
                    f"{MODERATE_LONG_TTC_MIN_MS}-{MODERATE_LONG_TTC_MAX_MS}",
                    "20000 <= ttc <= 60000",
                    strength=SUPPORTING,
                    family="timing",
                )
            )
        elif event.ttc > 120000:
            reason = "extreme time-to-click"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "extreme_ttc",
                    "Extreme time-to-click",
                    reason,
                    0.08,
                    event.ttc,
                    120000,
                    "ttc > threshold",
                    strength=SUPPORTING,
                    family="timing",
                )
            )

        query_terms = len(event.query.split())
        if query_terms <= 1:
            reason = "very short query"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "short_query",
                    "Very short query",
                    reason,
                    0.04,
                    query_terms,
                    1,
                    "query_terms <= threshold",
                    strength=SUPPORTING,
                    family="query",
                )
            )

        interarrival_contribution = regular_interarrival.get(id(event))
        if interarrival_contribution:
            reasons.append(interarrival_contribution.reason)
            contributions.append(interarrival_contribution)

        event.heuristic_score = _apply_contribution_caps(contributions)
        event.reasons = reasons
        event.rule_contributions = contributions
    return threshold_summary


def _adaptive_thresholds(
    counters: dict[str, Counter],
    total: int,
) -> dict[str, dict[str, int | float | str | None]]:
    """Build all batch-adaptive count thresholds with fixed guardrails."""

    domain = _adaptive_count_threshold(
        counters.get("domain", Counter()),
        rule_id="high_volume_domain",
        label="High-volume clicked domain",
        absolute_floor=200,
        rate_floor=int(total * 0.015),
    )
    query = _adaptive_count_threshold(
        counters.get("query", Counter()),
        rule_id="repeat_query",
        label="Repeated query",
        absolute_floor=12,
        rate_floor=int(total * 0.001),
    )
    query_domain = _adaptive_count_threshold(
        counters.get("query_domain", Counter()),
        rule_id="repeat_query_domain",
        label="Repeated query/domain pair",
        absolute_floor=4,
        rate_floor=int(total * 0.00025),
    )
    device = _adaptive_count_threshold(
        counters.get("device", Counter()),
        rule_id="heavy_device_cluster",
        label="Heavy region/browser/OS cluster",
        absolute_floor=600,
        rate_floor=int(total * 0.035),
    )
    same_second = _adaptive_count_threshold(
        counters.get("second", Counter()),
        rule_id="same_second_burst",
        label="Same-second click burst",
        absolute_floor=SAME_SECOND_COUNT_FLOOR,
        rate_floor=None,
    )
    country = _adaptive_count_threshold(
        Counter(
            {
                country: count
                for country, count in counters.get("country", Counter()).items()
                if country
            }
        ),
        rule_id="concentrated_ct_context",
        label="Concentrated ct context",
        absolute_floor=COUNTRY_CONTEXT_MIN_COUNT,
        rate_floor=int(total * COUNTRY_CONTEXT_MIN_RATE),
    )
    ttc = _adaptive_count_threshold(
        Counter(
            {
                ttc: count
                for ttc, count in counters.get("ttc", Counter()).items()
                if isinstance(ttc, int) and ttc >= 0
            }
        ),
        rule_id="reused_ttc",
        label="Reused exact time-to-click",
        absolute_floor=TTC_REUSE_COUNT_FLOOR,
        rate_floor=None,
        percentile=TTC_REUSE_COUNT_PERCENTILE,
    )
    return {
        item.rule_id: item.to_dict()
        for item in (query_domain, query, domain, device, same_second, country, ttc)
    }


def _adaptive_count_threshold(
    counts: Counter,
    *,
    rule_id: str,
    label: str,
    absolute_floor: int,
    rate_floor: int | None,
    percentile: float = ADAPTIVE_COUNT_PERCENTILE,
) -> AdaptiveThreshold:
    # pylint: disable=too-many-arguments
    """Select a threshold from absolute, rate, and percentile guardrails."""

    percentile_threshold = _counter_percentile(counts, percentile)
    guardrails = [absolute_floor, percentile_threshold]
    if rate_floor is not None:
        guardrails.append(rate_floor)
    threshold = max(guardrails)
    return AdaptiveThreshold(
        rule_id=rule_id,
        label=label,
        threshold=threshold,
        threshold_mode="adaptive_percentile",
        percentile=percentile,
        absolute_floor=absolute_floor,
        rate_floor=rate_floor,
        selected_from="current batch counts with fixed guardrails",
    )


def _counter_percentile(counts: Counter, percentile: float) -> int:
    """Return a nearest-rank percentile over positive counter values."""

    values = sorted(count for count in counts.values() if count > 0)
    if not values:
        return 0
    percentile_idx = max(0, ceil(len(values) * percentile) - 1)
    return int(values[percentile_idx])


def _regular_interarrival_contributions(
    events: list[ClickEvent],
) -> dict[int, RuleContribution]:
    """Return timing-regularity contributions for pseudo-session groups.

    Groups must have enough events, a positive mean inter-arrival time, and low
    coefficient of variation. Each event receives its own contribution object so
    later per-event cap mutation cannot leak across the group.
    """

    contributions: dict[int, RuleContribution] = {}
    for group_events in pseudo_session_groups(events).values():
        if len(group_events) < REGULAR_INTERARRIVAL_MIN_EVENTS:
            continue
        ordered = sorted(group_events, key=lambda event: event.event_time)
        deltas = [
            (current.event_time - previous.event_time).total_seconds()
            for previous, current in zip(ordered, ordered[1:])
        ]
        if not deltas:
            continue
        mean_delta = sum(deltas) / len(deltas)
        if mean_delta <= 0 or mean_delta > REGULAR_INTERARRIVAL_MAX_MEAN_SECONDS:
            continue
        variance = sum((delta - mean_delta) ** 2 for delta in deltas) / len(deltas)
        cv = sqrt(variance) / mean_delta
        if cv > REGULAR_INTERARRIVAL_MAX_CV:
            continue

        reason = (
            f"regular inter-arrival timing ({len(group_events)} clicks, "
            f"mean {mean_delta:.1f}s, cv {cv:.3f})"
        )
        for event in group_events:
            contributions[id(event)] = _contribution(
                "regular_interarrival",
                "Regular inter-arrival timing",
                reason,
                REGULAR_INTERARRIVAL_WEIGHT,
                round(cv, 3),
                REGULAR_INTERARRIVAL_MAX_CV,
                "events >= 8 and mean_delta_seconds <= 300 and cv <= 0.50",
                family="timing",
            )
    return contributions


def _apply_contribution_caps(contributions: list[RuleContribution]) -> float:
    """Apply the supporting-rule cap and return the event heuristic score.

    Strong evidence keeps its full weight. Supporting evidence is scaled down
    proportionally only when its combined weight exceeds ``SUPPORTING_RULE_CAP``.

    Raises:
        ValueError: If regular-interarrival evidence is marked as supporting.
            That rule is intentionally strong-only because cap mutation happens
            on contribution objects.
    """

    for contribution in contributions:
        if contribution.rule_id == "regular_interarrival":
            if contribution.strength != STRONG:
                raise ValueError(
                    "regular_interarrival contributions must remain strong "
                    "because supporting caps mutate contribution weights"
                )
        contribution.applied_weight = contribution.weight
        contribution.capped = False

    supporting = [
        contribution
        for contribution in contributions
        if contribution.strength == SUPPORTING
    ]
    supporting_total = sum(contribution.weight for contribution in supporting)
    if supporting_total > SUPPORTING_RULE_CAP:
        scale = SUPPORTING_RULE_CAP / supporting_total
        for contribution in supporting:
            contribution.applied_weight = contribution.weight * scale
            contribution.capped = True

    return min(sum(contribution.applied_weight for contribution in contributions), 1.0)


def _contribution(
    rule_id: str,
    label: str,
    reason: str,
    weight: float,
    observed: int | float | str,
    threshold: int | float | str | None,
    condition: str,
    threshold_mode: str = "absolute",
    strength: str = STRONG,
    family: str = "general",
) -> RuleContribution:
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    """Construct a rule contribution with the common default fields."""

    return RuleContribution(
        rule_id=rule_id,
        label=label,
        reason=reason,
        weight=weight,
        observed=observed,
        threshold=threshold,
        threshold_mode=threshold_mode,
        condition=condition,
        strength=strength,
        family=family,
        applied_weight=weight,
    )

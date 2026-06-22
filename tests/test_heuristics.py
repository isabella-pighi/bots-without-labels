"""Tests for rule-based heuristic scoring and adaptive thresholds."""

from collections import Counter
from datetime import datetime, timedelta

import pytest

from bots_without_labels.data import ClickEvent, RuleContribution, build_features
from bots_without_labels.heuristics import (
    COUNTRY_CONTEXT_CONDITION,
    SUPPORTING_RULE_CAP,
    SUPPORTING,
    _adaptive_thresholds,
    _apply_contribution_caps,
    apply_heuristics,
)


def _event(
    idx: int,
    event_time: datetime,
    *,
    region: str = "Mars",
    browser: str = "Chrome",
    os_name: str = "Android",
    query: str = "human search",
    domain: str = "example.com",
) -> ClickEvent:
    # pylint: disable=too-many-arguments
    return ClickEvent(
        event_id=f"evt_{idx}",
        event_time=event_time,
        region=region,
        browser=browser,
        os=os_name,
        url=f"/ad_click?d={domain}&ttc={1000 + idx}&q={query.replace(' ', '%20')}",
        params={"d": domain, "ttc": str(1000 + idx), "q": query},
    )


def test_rule_contributions_preserve_reasons_and_score() -> None:
    events = [
        ClickEvent(
            event_id=f"evt_{idx}",
            event_time=datetime(2019, 12, 2, 8, 0, 0),
            region="Mars",
            browser="Chrome",
            os="Android",
            url="/ad_click?d=a.com&ttc=10&q=foo",
            params={"d": "a.com", "ttc": "10", "q": "foo"},
        )
        for idx in range(4)
    ]
    _, counters = build_features(events)

    apply_heuristics(events, counters)

    event = events[0]
    assert event.reasons == [
        "query/domain repeated 4 times",
        "4 clicks in the same second",
        "implausibly fast click",
        "very short query",
    ]
    assert event.heuristic_score == 0.66
    assert [contribution.rule_id for contribution in event.rule_contributions] == [
        "repeat_query_domain",
        "same_second_burst",
        "fast_click",
        "short_query",
    ]
    assert (
        sum(contribution.applied_weight for contribution in event.rule_contributions)
        == event.heuristic_score
    )
    assert event.rule_contributions[0].reason == "query/domain repeated 4 times"
    assert event.rule_contributions[0].label == "Repeated query/domain pair"
    assert event.rule_contributions[0].weight == 0.32
    assert event.rule_contributions[0].applied_weight == 0.32
    assert event.rule_contributions[0].strength == "strong"
    assert event.rule_contributions[0].family == "repetition"
    assert event.rule_contributions[0].observed == 4
    assert event.rule_contributions[0].threshold == 4
    assert (
        event.rule_contributions[0].condition
        == "query_domain_count >= adaptive percentile threshold"
    )
    assert event.rule_contributions[0].threshold_mode == "adaptive_percentile"
    assert event.rule_contributions[2].observed == 10
    assert event.rule_contributions[2].threshold == 250


def test_high_volume_rule_contribution_fields() -> None:
    event = ClickEvent(
        event_id="evt",
        event_time=datetime(2019, 12, 2, 8, 0, 0),
        region="Mars",
        browser="Chrome",
        os="Android",
        url="/ad_click?d=a.com&ttc=3000&q=human%20search",
        params={"d": "a.com", "ttc": "3000", "q": "human search"},
    )
    counters = {
        "query_domain": Counter({("human search", "a.com"): 1}),
        "query": Counter({"human search": 1}),
        "domain": Counter({"a.com": 200}),
        "device": Counter({("Mars", "Chrome", "Android"): 1}),
        "ttc": Counter({3000: 1}),
        "second": Counter({event.event_time: 1}),
    }

    apply_heuristics([event], counters)

    assert event.reasons == ["high-volume clicked domain (200)"]
    assert event.heuristic_score == 0.10
    assert len(event.rule_contributions) == 1
    contribution = event.rule_contributions[0]
    assert contribution.rule_id == "high_volume_domain"
    assert contribution.label == "High-volume clicked domain"
    assert contribution.reason == "high-volume clicked domain (200)"
    assert contribution.weight == 0.10
    assert contribution.applied_weight == 0.10
    assert contribution.strength == "supporting"
    assert contribution.family == "volume"
    assert not contribution.capped
    assert contribution.observed == 200
    assert contribution.threshold == 200
    assert contribution.condition == "domain_count >= adaptive percentile threshold"
    assert contribution.threshold_mode == "adaptive_percentile"


def test_supporting_only_rules_are_capped_as_a_group() -> None:
    event = ClickEvent(
        event_id="evt",
        event_time=datetime(2019, 12, 2, 8, 0, 0),
        region="Mars",
        browser="Chrome",
        os="Android",
        url="/ad_click?d=a.com&ttc=120001&q=foo",
        params={"d": "a.com", "ttc": "120001", "q": "foo"},
    )
    counters = {
        "query_domain": Counter({("foo", "a.com"): 1}),
        "query": Counter({"foo": 1}),
        "domain": Counter({"a.com": 200}),
        "device": Counter({("Mars", "Chrome", "Android"): 600}),
        "ttc": Counter({120001: 1}),
        "second": Counter({event.event_time: 1}),
    }

    apply_heuristics([event], counters)

    assert [item.rule_id for item in event.rule_contributions] == [
        "high_volume_domain",
        "heavy_device_cluster",
        "extreme_ttc",
        "short_query",
    ]
    assert event.heuristic_score == pytest.approx(SUPPORTING_RULE_CAP)
    assert all(item.strength == "supporting" for item in event.rule_contributions)
    assert sum(item.weight for item in event.rule_contributions) == pytest.approx(0.30)
    assert sum(item.applied_weight for item in event.rule_contributions) == (
        pytest.approx(SUPPORTING_RULE_CAP)
    )
    assert all(item.capped for item in event.rule_contributions)


def test_strong_rules_keep_full_weight_when_supporting_cap_binds() -> None:
    event = ClickEvent(
        event_id="evt",
        event_time=datetime(2019, 12, 2, 8, 0, 0),
        region="Mars",
        browser="Chrome",
        os="Android",
        url="/ad_click?d=a.com&ttc=120001&q=foo",
        params={"d": "a.com", "ttc": "120001", "q": "foo"},
    )
    counters = {
        "query_domain": Counter({("foo", "a.com"): 4}),
        "query": Counter({"foo": 1}),
        "domain": Counter({"a.com": 200}),
        "device": Counter({("Mars", "Chrome", "Android"): 600}),
        "ttc": Counter({120001: 1}),
        "second": Counter({event.event_time: 1}),
    }

    apply_heuristics([event], counters)

    strong = [item for item in event.rule_contributions if item.strength == "strong"]
    supporting = [
        item for item in event.rule_contributions if item.strength == "supporting"
    ]
    assert [item.rule_id for item in strong] == ["repeat_query_domain"]
    assert strong[0].weight == 0.32
    assert strong[0].applied_weight == 0.32
    assert not strong[0].capped
    assert sum(item.applied_weight for item in supporting) == pytest.approx(
        SUPPORTING_RULE_CAP
    )
    assert event.heuristic_score == pytest.approx(0.32 + SUPPORTING_RULE_CAP)


def test_dense_burst_repetition_cluster_requires_all_signals() -> None:
    event = ClickEvent(
        event_id="evt",
        event_time=datetime(2019, 12, 2, 8, 0, 0),
        region="Mars",
        browser="Chrome",
        os="Android",
        url="/ad_click?d=a.com&ttc=3000&q=human%20search",
        params={"d": "a.com", "ttc": "3000", "q": "human search"},
    )
    counters = {
        "query_domain": Counter({("human search", "a.com"): 1}),
        "query": Counter({"human search": 12}),
        "domain": Counter({"a.com": 1}),
        "device": Counter({("Mars", "Chrome", "Android"): 600}),
        "ttc": Counter({3000: 1}),
        "second": Counter({event.event_time: 5}),
    }

    apply_heuristics([event], counters)

    assert event.reasons == [
        "query repeated 12 times",
        "heavy region/browser/os cluster (600)",
        "5 clicks in the same second",
        "dense burst repetition cluster (device 600, same-second 5, query 12)",
    ]
    assert event.heuristic_score == 0.50
    contribution = event.rule_contributions[-1]
    assert contribution.rule_id == "dense_burst_repetition_cluster"
    assert contribution.label == "Dense burst repetition cluster"
    assert contribution.weight == 0.12
    assert contribution.applied_weight == 0.12
    assert contribution.strength == "strong"
    assert contribution.family == "compound"
    assert contribution.observed == "device=600; same_second=5; query=12"
    assert (
        contribution.threshold == "device>=600; same_second>=5; repeated_query_pattern"
    )
    assert contribution.condition == (
        "device_count >= adaptive percentile threshold "
        "and same_second_count >= 5 and "
        "(query_count >= adaptive percentile threshold or "
        "query_domain_count >= adaptive percentile threshold)"
    )
    assert contribution.threshold_mode == "adaptive_percentile"


def test_dense_burst_repetition_cluster_does_not_fire_without_dense_burst() -> None:
    event = ClickEvent(
        event_id="evt",
        event_time=datetime(2019, 12, 2, 8, 0, 0),
        region="Mars",
        browser="Chrome",
        os="Android",
        url="/ad_click?d=a.com&ttc=3000&q=human%20search",
        params={"d": "a.com", "ttc": "3000", "q": "human search"},
    )
    counters = {
        "query_domain": Counter({("human search", "a.com"): 1}),
        "query": Counter({"human search": 12}),
        "domain": Counter({"a.com": 1}),
        "device": Counter({("Mars", "Chrome", "Android"): 600}),
        "ttc": Counter({3000: 1}),
        "second": Counter({event.event_time: 4}),
    }

    apply_heuristics([event], counters)

    assert "dense_burst_repetition_cluster" not in {
        contribution.rule_id for contribution in event.rule_contributions
    }


def test_concentrated_ct_context_is_supporting_evidence_only() -> None:
    event = ClickEvent(
        event_id="evt",
        event_time=datetime(2019, 12, 2, 8, 0, 0),
        region="Mars",
        browser="Chrome",
        os="Android",
        url="/ad_click?d=a.com&ttc=3000&q=human%20search&ct=US",
        params={"d": "a.com", "ttc": "3000", "q": "human search", "ct": "US"},
    )
    counters = {
        "query_domain": Counter({("human search", "a.com"): 1}),
        "query": Counter({"human search": 12}),
        "domain": Counter({"a.com": 1}),
        "device": Counter({("Mars", "Chrome", "Android"): 600}),
        "ttc": Counter({3000: 1}),
        "second": Counter({event.event_time: 1}),
        "country": Counter({"US": 1_000}),
    }

    apply_heuristics([event], counters)

    assert event.reasons == [
        "query repeated 12 times",
        "heavy region/browser/os cluster (600)",
        "concentrated ct context (US 1000, device 600, query 12)",
    ]
    assert event.heuristic_score == 0.32
    contribution = event.rule_contributions[-1]
    assert contribution.rule_id == "concentrated_ct_context"
    assert contribution.label == "Concentrated ct context"
    assert contribution.weight == 0.06
    assert contribution.applied_weight == 0.06
    assert contribution.strength == "supporting"
    assert contribution.family == "context"
    assert contribution.observed == "ct=US; ct_count=1000; device 600; query=12"
    assert contribution.threshold == (
        "ct_count>=1000; repeated_query_pattern; device_or_same_second_cluster"
    )
    assert contribution.condition == COUNTRY_CONTEXT_CONDITION
    assert contribution.threshold_mode == "adaptive_percentile"


def test_concentrated_ct_context_does_not_fire_without_repetition() -> None:
    event = ClickEvent(
        event_id="evt",
        event_time=datetime(2019, 12, 2, 8, 0, 0),
        region="Mars",
        browser="Chrome",
        os="Android",
        url="/ad_click?d=a.com&ttc=3000&q=human%20search&ct=US",
        params={"d": "a.com", "ttc": "3000", "q": "human search", "ct": "US"},
    )
    counters = {
        "query_domain": Counter({("human search", "a.com"): 1}),
        "query": Counter({"human search": 1}),
        "domain": Counter({"a.com": 1}),
        "device": Counter({("Mars", "Chrome", "Android"): 600}),
        "ttc": Counter({3000: 1}),
        "second": Counter({event.event_time: 1}),
        "country": Counter({"US": 1_000}),
    }

    apply_heuristics([event], counters)

    assert "concentrated_ct_context" not in {
        contribution.rule_id for contribution in event.rule_contributions
    }


def test_confirmed_query_repetition_requires_query_and_query_domain_repetition() -> (
    None
):
    event = ClickEvent(
        event_id="evt",
        event_time=datetime(2019, 12, 2, 8, 0, 0),
        region="Mars",
        browser="Chrome",
        os="Android",
        url="/ad_click?d=a.com&ttc=3000&q=human%20search",
        params={"d": "a.com", "ttc": "3000", "q": "human search"},
    )
    counters = {
        "query_domain": Counter({("human search", "a.com"): 4}),
        "query": Counter({"human search": 12}),
        "domain": Counter({"a.com": 1}),
        "device": Counter({("Mars", "Chrome", "Android"): 1}),
        "ttc": Counter({3000: 1}),
        "second": Counter({event.event_time: 1}),
    }

    apply_heuristics([event], counters)

    assert event.reasons == [
        "query/domain repeated 4 times",
        "query repeated 12 times",
        "confirmed query repetition (query/domain 4, query 12)",
    ]
    assert event.heuristic_score == 0.62
    contribution = event.rule_contributions[-1]
    assert contribution.rule_id == "confirmed_query_repetition"
    assert contribution.label == "Confirmed query repetition"
    assert contribution.weight == 0.12
    assert contribution.observed == "query_domain=4; query=12"
    assert contribution.threshold == "query_domain>=4; query>=12"
    assert contribution.condition == (
        "query_domain_count >= adaptive percentile threshold "
        "and query_count >= adaptive percentile threshold"
    )
    assert contribution.threshold_mode == "adaptive_percentile"


def test_regular_interarrival_contribution_cap_invariant_rejects_supporting() -> None:
    contribution = RuleContribution(
        rule_id="regular_interarrival",
        label="Regular inter-arrival timing",
        reason="regular inter-arrival timing",
        weight=0.10,
        observed=0.1,
        strength=SUPPORTING,
    )

    with pytest.raises(ValueError, match="regular_interarrival contributions"):
        _apply_contribution_caps([contribution])


def test_confirmed_query_repetition_does_not_fire_for_query_only_repetition() -> None:
    event = ClickEvent(
        event_id="evt",
        event_time=datetime(2019, 12, 2, 8, 0, 0),
        region="Mars",
        browser="Chrome",
        os="Android",
        url="/ad_click?d=a.com&ttc=3000&q=human%20search",
        params={"d": "a.com", "ttc": "3000", "q": "human search"},
    )
    counters = {
        "query_domain": Counter({("human search", "a.com"): 3}),
        "query": Counter({"human search": 12}),
        "domain": Counter({"a.com": 1}),
        "device": Counter({("Mars", "Chrome", "Android"): 1}),
        "ttc": Counter({3000: 1}),
        "second": Counter({event.event_time: 1}),
    }

    apply_heuristics([event], counters)

    assert [contribution.rule_id for contribution in event.rule_contributions] == [
        "repeat_query"
    ]


def test_reused_ttc_threshold_uses_adaptive_thresholds_path() -> None:
    counters = _minimal_threshold_counters()
    counters["ttc"] = Counter({-1: 1000})
    counters["ttc"].update({ttc: 1 for ttc in range(98)})
    counters["ttc"][10_000] = 70
    counters["ttc"][20_000] = 100

    empty_counters = _minimal_threshold_counters()
    empty_counters["ttc"] = Counter()
    small_counters = _minimal_threshold_counters()
    small_counters["ttc"] = Counter({idx: 1 for idx in range(10)})

    assert (
        _adaptive_thresholds(empty_counters, total=0)["reused_ttc"]["threshold"] == 40
    )
    assert (
        _adaptive_thresholds(small_counters, total=10)["reused_ttc"]["threshold"] == 40
    )
    assert _adaptive_thresholds(counters, total=200)["reused_ttc"]["threshold"] == 70


def _minimal_threshold_counters() -> dict[str, Counter]:
    return {
        "query_domain": Counter(),
        "query": Counter(),
        "domain": Counter(),
        "device": Counter(),
        "second": Counter(),
        "ttc": Counter(),
        "country": Counter(),
    }


def test_adaptive_thresholds_keep_small_input_guardrails() -> None:
    counters = {
        "query_domain": Counter({("human search", "a.com"): 2}),
        "query": Counter({"human search": 2}),
        "domain": Counter({"a.com": 2}),
        "device": Counter({("Mars", "Chrome", "Android"): 2}),
        "ttc": Counter({3000: 2}),
        "country": Counter({"US": 2}),
    }

    thresholds = _adaptive_thresholds(counters, total=2)

    assert thresholds["repeat_query_domain"]["threshold"] == 4
    assert thresholds["repeat_query"]["threshold"] == 12
    assert thresholds["high_volume_domain"]["threshold"] == 200
    assert thresholds["heavy_device_cluster"]["threshold"] == 600
    assert thresholds["same_second_burst"]["threshold"] == 4
    assert thresholds["concentrated_ct_context"]["threshold"] == 1000
    assert thresholds["reused_ttc"]["threshold"] == 40


def test_adaptive_thresholds_use_percentile_for_larger_inputs() -> None:
    counters = {
        "query_domain": Counter({("rare", "a.com"): 2, ("hot", "b.com"): 90}),
        "query": Counter({"rare": 2, "hot": 120}),
        "domain": Counter({"a.com": 2, "b.com": 450}),
        "device": Counter(
            {("Mars", "Chrome", "Android"): 2, ("Venus", "Safari", "iOS"): 800}
        ),
        "second": Counter(
            {datetime(2019, 12, 2, 8, 0, 0): 2, datetime(2019, 12, 2, 8, 0, 1): 9}
        ),
        "ttc": Counter({3000: 2, 777: 70}),
        "country": Counter({"US": 1_250}),
    }

    thresholds = _adaptive_thresholds(counters, total=10_000)

    assert thresholds["repeat_query_domain"]["threshold"] == 90
    assert thresholds["repeat_query"]["threshold"] == 120
    assert thresholds["high_volume_domain"]["threshold"] == 450
    assert thresholds["heavy_device_cluster"]["threshold"] == 800
    assert thresholds["same_second_burst"]["threshold"] == 9
    assert thresholds["concentrated_ct_context"]["threshold"] == 1250
    assert thresholds["reused_ttc"]["threshold"] == 70


def test_reused_ttc_rule_reports_adaptive_threshold_mode() -> None:
    start = datetime(2019, 12, 2, 8, 0, 0)
    events = [
        _event(
            idx,
            start + timedelta(seconds=idx),
            query=f"human search {idx}",
            domain=f"example-{idx}.com",
        )
        for idx in range(70)
    ]
    for event in events:
        event.params["ttc"] = "777"
    _, counters = build_features(events)
    counters["ttc"] = Counter(
        {777: 70, **{10_000 + idx: 1 for idx in range(98)}, 20_000: 100}
    )

    apply_heuristics(events, counters)

    contribution = next(
        item for item in events[0].rule_contributions if item.rule_id == "reused_ttc"
    )
    assert contribution.reason == "exact time-to-click reused 70 times"
    assert contribution.observed == 70
    assert contribution.threshold == 70
    assert contribution.threshold_mode == "adaptive_percentile"
    assert contribution.condition == (
        "ttc >= 0 and ttc_count >= adaptive 99th percentile threshold with absolute floor 40"
    )


def test_reused_ttc_rule_uses_adaptive_cutoff_not_old_total_rate() -> None:
    start = datetime(2019, 12, 2, 8, 0, 0)
    events = [
        _event(
            idx,
            start + timedelta(seconds=idx),
            query=f"human search {idx}",
            domain=f"example-{idx}.com",
        )
        for idx in range(45)
    ]
    for event in events:
        event.params["ttc"] = "777"
    _, counters = build_features(events)
    counters["ttc"] = Counter(
        {777: 45, **{10_000 + idx: 1 for idx in range(98)}, 20_000: 80, 30_000: 100}
    )

    apply_heuristics(events, counters)

    assert "reused_ttc" not in {
        contribution.rule_id
        for event in events
        for contribution in event.rule_contributions
    }


def test_moderate_long_ttc_rule_triggers_only_in_inclusive_band() -> None:
    start = datetime(2019, 12, 2, 8, 0, 0)
    ttc_values = [19_999, 20_000, 60_000, 60_001]
    events = [
        ClickEvent(
            event_id=f"evt_{idx}",
            event_time=start + timedelta(seconds=idx),
            region="Mars",
            browser="Chrome",
            os="Android",
            url=f"/ad_click?d=example-{idx}.com&ttc={ttc}&q=human%20search%20{idx}",
            params={
                "d": f"example-{idx}.com",
                "ttc": str(ttc),
                "q": f"human search {idx}",
            },
        )
        for idx, ttc in enumerate(ttc_values)
    ]
    _, counters = build_features(events)

    apply_heuristics(events, counters)

    assert "moderate_long_ttc" not in {
        item.rule_id for item in events[0].rule_contributions
    }
    assert "moderate_long_ttc" not in {
        item.rule_id for item in events[3].rule_contributions
    }

    for event, expected_ttc in [(events[1], 20_000), (events[2], 60_000)]:
        assert event.reasons == ["moderately long time-to-click"]
        assert event.heuristic_score == 0.06
        contribution = event.rule_contributions[0]
        assert contribution.rule_id == "moderate_long_ttc"
        assert contribution.label == "Moderately long time-to-click"
        assert contribution.reason == "moderately long time-to-click"
        assert contribution.weight == 0.06
        assert contribution.observed == expected_ttc
        assert contribution.threshold == "20000-60000"
        assert contribution.condition == "20000 <= ttc <= 60000"


def test_extreme_ttc_rule_remains_separate_from_moderate_long_band() -> None:
    event = ClickEvent(
        event_id="evt",
        event_time=datetime(2019, 12, 2, 8, 0, 0),
        region="Mars",
        browser="Chrome",
        os="Android",
        url="/ad_click?d=example.com&ttc=120001&q=human%20search",
        params={"d": "example.com", "ttc": "120001", "q": "human search"},
    )
    _, counters = build_features([event])

    apply_heuristics([event], counters)

    assert event.reasons == ["extreme time-to-click"]
    assert event.heuristic_score == 0.08
    assert [item.rule_id for item in event.rule_contributions] == ["extreme_ttc"]


def test_regular_interarrival_rule_triggers_for_regular_pseudo_session() -> None:
    start = datetime(2019, 12, 2, 8, 0, 0)
    events = [_event(idx, start.replace(minute=idx * 2)) for idx in range(8)]
    _, counters = build_features(events)

    apply_heuristics(events, counters)

    contribution = events[0].rule_contributions[-1]
    assert contribution.rule_id == "regular_interarrival"
    assert contribution.label == "Regular inter-arrival timing"
    assert (
        contribution.reason
        == "regular inter-arrival timing (8 clicks, mean 120.0s, cv 0.000)"
    )
    assert contribution.weight == 0.10
    assert contribution.observed == 0.0
    assert contribution.threshold == 0.50
    assert (
        contribution.condition
        == "events >= 8 and mean_delta_seconds <= 300 and cv <= 0.50"
    )
    assert all("regular inter-arrival timing" in event.reasons[-1] for event in events)
    assert len({id(event.rule_contributions[-1]) for event in events}) == len(events)


def test_regular_interarrival_rule_ignores_irregular_timing() -> None:
    start = datetime(2019, 12, 2, 8, 0, 0)
    offsets = [0, 30, 360, 390, 900, 930, 1500, 1530]
    events = [
        _event(idx, start.replace(second=0) + timedelta(seconds=offset))
        for idx, offset in enumerate(offsets)
    ]
    _, counters = build_features(events)

    apply_heuristics(events, counters)

    assert "regular_interarrival" not in {
        contribution.rule_id
        for event in events
        for contribution in event.rule_contributions
    }


def test_regular_interarrival_rule_requires_at_least_eight_events() -> None:
    start = datetime(2019, 12, 2, 8, 0, 0)
    events = [_event(idx, start.replace(minute=idx * 2)) for idx in range(7)]
    _, counters = build_features(events)

    apply_heuristics(events, counters)

    assert "regular_interarrival" not in {
        contribution.rule_id
        for event in events
        for contribution in event.rule_contributions
    }


def test_regular_interarrival_rule_does_not_cross_split_groups() -> None:
    start = datetime(2019, 12, 2, 8, 0, 0)
    events = [
        *[
            _event(idx, start.replace(minute=idx * 2), query="human search")
            for idx in range(4)
        ],
        *[
            _event(idx + 4, start.replace(minute=idx * 2), query="other search")
            for idx in range(4)
        ],
    ]
    _, counters = build_features(events)

    apply_heuristics(events, counters)

    assert "regular_interarrival" not in {
        contribution.rule_id
        for event in events
        for contribution in event.rule_contributions
    }

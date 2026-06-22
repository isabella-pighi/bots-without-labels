"""Tests for advisory threshold sensitivity calculations."""

# pylint: disable=duplicate-code

from datetime import datetime

from bots_without_labels.data import ClickEvent
from bots_without_labels.pipeline import (
    SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD,
    _threshold_sensitivity,
)


def _event(
    event_id: str,
    *,
    heuristic_score: float,
    ml_score: float,
    combined_score: float,
) -> ClickEvent:
    return ClickEvent(
        event_id=event_id,
        event_time=datetime(2019, 12, 2, 0, 0, 0),
        region="Mars",
        browser="Chrome",
        os="iOS",
        url="/ad_click?d=a.com&ttc=3000&q=human%20search",
        params={"d": "a.com", "ttc": "3000", "q": "human search"},
        heuristic_score=heuristic_score,
        ml_score=ml_score,
        combined_score=combined_score,
        is_bot=0,
        operational_tier="monitor",
    )


def test_threshold_sensitivity_separates_ml_tail_from_final_or() -> None:
    # A spread of ML scores so the ML tail varies across thresholds, plus a
    # rules-only override that the rules path keeps regardless of the ML cutoff.
    events = [
        _event(
            f"evt_{index}",
            heuristic_score=0.10,
            ml_score=index / 200,
            combined_score=index / 200,
        )
        for index in range(201)
    ]
    events.append(
        _event(
            "evt_override",
            heuristic_score=0.80,
            ml_score=0.20,
            combined_score=0.80,
        )
    )

    rows = _threshold_sensitivity(events)
    total = len(events)
    rules_cutoff = SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
    expected_rules_path = sum(
        1 for event in events if event.heuristic_score >= rules_cutoff
    )

    assert [row["label"] for row in rows] == [
        "Kneedle dynamic cutoff",
        "95th percentile",
        "97.5th percentile",
        "99th percentile",
        "99.5th percentile",
    ]
    assert [row["current"] for row in rows] == [True, False, False, False, False]

    # Every row is computed the same way: ML tail at that threshold, the fixed
    # rules path, and their OR. Expectations are recomputed from the events, so
    # there are no magic numbers and the rule logic is verified directly.
    for row in rows:
        threshold = row["threshold"]
        ml_tail = sum(1 for event in events if event.ml_score > threshold)
        final_or = sum(
            1
            for event in events
            if event.heuristic_score >= rules_cutoff or event.ml_score > threshold
        )
        assert row["ml_tail_events"] == ml_tail
        assert row["rules_path_events"] == expected_rules_path
        assert row["final_or_events"] == final_or
        assert row["selected_events"] == final_or
        assert row["selected_rate"] == final_or / total
        assert row["suppress"] + row["quarantine"] + row["monitor"] == total

    # The rules path is fixed: it never changes with the ML threshold.
    assert len({row["rules_path_events"] for row in rows}) == 1
    # The final OR is always at least as large as either path alone.
    for row in rows:
        assert row["final_or_events"] >= row["ml_tail_events"]
        assert row["final_or_events"] >= row["rules_path_events"]

    assert rows[0]["estimated_human_false_positive_risk"] == "Run-specific"
    assert rows[1]["estimated_human_false_positive_risk"] == "High"
    assert rows[2]["estimated_human_false_positive_risk"] == "Moderate"
    assert rows[3]["estimated_human_false_positive_risk"] == "Low"
    assert rows[4]["estimated_human_false_positive_risk"] == "Very low"
    assert all(event.is_bot == 0 for event in events)
    assert all(event.operational_tier == "monitor" for event in events)

"""Tests for pipeline orchestration, output artifacts, and classifications."""

# pylint: disable=too-many-lines

import json
import sys
from collections import Counter
from datetime import datetime
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType

import pytest

from bots_without_labels import atomic, pipeline
from bots_without_labels.data import (
    EXCLUDED_ML_FEATURE_NAMES,
    ClickEvent,
    RuleContribution,
    _pseudo_session_burst_counts,
)
from bots_without_labels.ml import _assign_rank_scores, _standardize
from bots_without_labels.pipeline import (
    HEURISTIC_ML_AGREEMENT_FLOOR,
    _anomaly_classes,
    _assign_operational_tier,
    _event_method_bucket,
    _method_disagreement,
    _normalize_reason,
    _selected_event_dicts,
    _selected_method_counts,
    optimize_threshold,
    run_pipeline,
)


class FakeEIF:  # pylint: disable=too-many-instance-attributes
    """Small stand-in for isotree.IsolationForest used by pipeline tests."""

    last_instance: "FakeEIF | None" = None

    def __init__(
        self,
        sample_size: int,
        ntrees: int,
        ndim: int,
        missing_action: str,
        standardize_data: bool,
        random_seed: int,
        nthreads: int,
    ) -> None:
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        self.sample_size = sample_size
        self.ntrees = ntrees
        self.ndim = ndim
        self.missing_action = missing_action
        self.standardize_data = standardize_data
        self.random_seed = random_seed
        self.nthreads = nthreads
        self.fit_column_count = 0
        FakeEIF.last_instance = self

    def fit(self, rows) -> "FakeEIF":
        self.fit_column_count = rows.shape[1] if len(rows) else 0
        return self

    def decision_function(self, rows) -> list[float]:
        return [0.1, 0.5, 1.0][: len(rows)]


def install_fake_isotree(monkeypatch) -> None:
    FakeEIF.last_instance = None
    isotree = ModuleType("isotree")
    isotree.__spec__ = ModuleSpec("isotree", loader=None)
    isotree.IsolationForest = FakeEIF
    monkeypatch.setitem(sys.modules, "isotree", isotree)


def hide_isotree(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "isotree", None)


def _record_atomic_replace(source, destination, replaced: list[Path]) -> None:
    source_path = Path(source)
    destination_path = Path(destination)
    assert source_path.exists()
    assert source_path.parent == destination_path.parent
    assert source_path.name.startswith(f".{destination_path.name}.")
    replaced.append(destination_path)


def _classified_event(
    event_id: str,
    *,
    heuristic_score: float,
    ml_score: float,
    combined_score: float,
    is_bot: int,
    tier: str,
    rule_ids: list[str],
) -> ClickEvent:
    # pylint: disable=too-many-arguments
    event = ClickEvent(
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
        is_bot=is_bot,
        operational_tier=tier,
    )
    event.rule_contributions = [
        RuleContribution(
            rule_id=rule_id,
            label=rule_id.replace("_", " ").title(),
            reason=rule_id,
            weight=0.10,
            applied_weight=0.10,
            observed=1,
        )
        for rule_id in rule_ids
    ]
    return event


def test_pipeline_writes_predictions(monkeypatch, tmp_path: Path) -> None:
    # pylint: disable=too-many-statements
    install_fake_isotree(monkeypatch)
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
                "/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&"
                "kp=-1&sld=1&st=mobile_search_intl",
                "evt_2\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
                "/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&"
                "kp=-1&sld=1&st=mobile_search_intl",
                "evt_3\t2019-12-02 00:00:01\tVenus\tSafari\tAndroid\t"
                "/ad_click?d=b.com&ttc=3000&q=human%20search&ct=GB&"
                "kl=uk&kp=-1&sld=0&st=mobile_search_intl",
            ]
        ),
        encoding="utf-8",
    )
    summary = run_pipeline(raw, tmp_path)
    assert summary["total_events"] == 3
    assert summary["ml_backend"] == "eif"
    assert summary["feature_artifact"] == "artifacts/features.tsv"
    assert summary["selected_events_artifact"] == "artifacts/selected_events.json"
    assert summary["score_blending"]["method"] == "no_blending_two_classifier_rule"
    assert summary["score_blending"]["formula"] == (
        "is_bot = heuristic_score >= 0.70 OR ml_score > dynamic_ml_threshold"
    )
    assert "two classifiers directly" in summary["score_blending"]["note"]
    assert 0.0 <= summary["score_diagnostics"]["ml_score"]["min"] <= 1.0
    assert 0.0 <= summary["score_diagnostics"]["ml_score"]["max"] <= 1.0
    assert 0.0 <= summary["score_diagnostics"]["combined_score"]["min"] <= 1.0
    assert 0.0 <= summary["score_diagnostics"]["combined_score"]["max"] <= 1.0
    assert summary["threshold_plot_artifact"] == "artifacts/risk_score_threshold.png"
    assert 0.0 <= summary["ml_dynamic_elbow_threshold"] <= 1.0
    assert summary["ml_threshold_method"]
    assert summary["ml_threshold_plot_artifact"] == "artifacts/ml_score_threshold.png"
    assert (tmp_path / "artifacts" / "risk_score_threshold.png").is_file()
    assert (tmp_path / "artifacts" / "ml_score_threshold.png").is_file()
    assert summary["tier_counts"] == {"suppress": 0, "quarantine": 0, "monitor": 3}
    assert summary["evidence_tiers"]["counts"]["tier_3_low"] == 0
    submission = (tmp_path / "predictions.tsv").read_text(encoding="utf-8")
    assert submission.startswith("event_id\tis_bot\n")
    assert all(len(line.split("\t")) == 2 for line in submission.splitlines())
    assert "evt_1" in submission
    extended = (tmp_path / "predictions-extended.tsv").read_text(encoding="utf-8")
    assert extended.startswith(
        "event_id\tis_bot\tevidence_tier\tconfidence_proxy\t"
        "heuristic_score\tml_score\tmethod_bucket\tstd_dev_ttc\tquery_entropy\n"
    )
    assert all(len(line.split("\t")) == 9 for line in extended.splitlines())
    sample_events = (tmp_path / "artifacts" / "sample_events.json").read_text(
        encoding="utf-8"
    )
    assert '"operational_tier"' in sample_events
    assert '"rule_contributions"' in sample_events
    assert '"threshold_mode": "absolute"' in sample_events
    assert '"rule_id": "fast_click"' in sample_events
    assert '"strength": "strong"' in sample_events
    assert '"family": "timing"' in sample_events
    assert '"applied_weight":' in sample_events
    assert '"capped":' in sample_events
    assert "method_disagreement" in summary
    assert sum(count for _, count in summary["method_disagreement"]) == 3
    assert summary["selected_method_counts"] == {}
    assert [row["bin"] for row in summary["query_entropy_distribution"]] == [
        "0.0-1.0",
        "1.0-2.0",
        "2.0-3.0",
        "3.0-4.0",
        "4.0+",
    ]
    assert [row["label"] for row in summary["threshold_sensitivity"]] == [
        "Kneedle dynamic cutoff",
        "95th percentile",
        "97.5th percentile",
        "99th percentile",
        "99.5th percentile",
    ]
    assert sum(row["current"] for row in summary["threshold_sensitivity"]) == 1
    assert summary["cost_sensitive_thresholds"]["equal_cost_baseline"]["label"] == (
        "Equal-cost baseline"
    )
    assert (
        summary["cost_sensitive_thresholds"]["equal_cost_baseline"]["fp_weight"] == 1.0
    )
    assert (
        summary["cost_sensitive_thresholds"]["equal_cost_baseline"]["fn_weight"] == 1.0
    )
    assert (
        summary["cost_sensitive_thresholds"]["equal_cost_baseline"]["scenario_role"]
        == "equal_cost_baseline"
    )
    assert summary["cost_sensitive_thresholds"]["fp_avoidant_sensitivity"][
        "label"
    ].startswith("Optional FP-avoidant sensitivity")
    assert (
        summary["cost_sensitive_thresholds"]["fp_avoidant_sensitivity"]["scenario_role"]
        == "optional_sensitivity"
    )
    assert "_".join(["method", "disagreement", "extreme"]) not in summary
    assert "_".join(["method", "disagreement", "support"]) not in summary
    assert (
        summary["tier_thresholds"]["ml_agreement_score"]
        == summary["ml_dynamic_elbow_threshold"]
    )
    assert (
        summary["tier_thresholds"]["ml_score_cutoff"]
        == summary["ml_dynamic_elbow_threshold"]
    )
    assert summary["tier_thresholds"]["heuristic_ml_agreement_floor"] == 0.70
    assert summary["heuristic_thresholds"]["repeat_query_domain"]["threshold"] == 4
    assert (
        summary["heuristic_thresholds"]["repeat_query_domain"]["threshold_mode"]
        == "adaptive_percentile"
    )
    assert summary["heuristic_thresholds"]["repeat_query_domain"]["absolute_floor"] == 4
    assert "rule_strengths" in summary
    assert summary["rule_strengths"]["supporting_cap"] == 0.24
    assert "anomaly_classes" in summary
    assert summary["anomaly_classes"]["selected_event_count"] == 0
    assert summary["anomaly_classes"]["classified_selected_event_count"] == 0
    assert summary["anomaly_classes"]["ml_only_population_count"] == 0
    assert summary["anomaly_classes"]["classes"][0]["count"] == 0
    assert summary["anomaly_classes"]["filtering_options"][0]["name"] == (
        "Tier 1 suppression review"
    )
    selected_events = json.loads(
        (tmp_path / "artifacts" / "selected_events.json").read_text(encoding="utf-8")
    )
    assert len(selected_events) == 0
    assert "_".join(["ml", "support", "score"]) not in summary["tier_thresholds"]
    assert (
        "_".join(["suppress", "agreement", "ml", "score"])
        not in summary["tier_thresholds"]
    )
    features = (
        (tmp_path / "artifacts" / "features.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert features[0].split("\t") == ["event_id", *summary["feature_names"]]
    assert "is_mobile_search" not in summary["feature_names"]
    assert "log_ttc_seconds" in summary["feature_names"]
    assert "is_sub_200ms_click" in summary["feature_names"]
    assert "log_pseudo_session_10s_click_count" in summary["feature_names"]
    assert "log_apex_domain_count" in summary["feature_names"]
    assert "log_query_apex_domain_count" in summary["feature_names"]
    assert "query_entropy" in summary["feature_names"]
    assert "log_country_count" in summary["feature_names"]
    assert "log_landing_count" in summary["feature_names"]
    assert "log_kp_count" in summary["feature_names"]
    assert "log_sld_count" in summary["feature_names"]
    assert "pld_click_count" in summary["feature_names"]
    assert "pld_click_count" not in summary["ml_feature_names"]
    assert "kp" not in summary["feature_names"]
    assert "sld" not in summary["feature_names"]
    assert "query_terms" not in summary["feature_names"]
    assert "query_chars" not in summary["feature_names"]
    assert "has_bkl" not in summary["feature_names"]
    assert "has_om" not in summary["feature_names"]
    assert "log_device_count" in summary["ml_feature_names"]
    assert "log_landing_count" in summary["ml_feature_names"]
    assert "log_kp_count" in summary["ml_feature_names"]
    assert "log_sld_count" in summary["ml_feature_names"]
    assert "kp" not in summary["ml_feature_names"]
    assert "sld" not in summary["ml_feature_names"]
    assert set(summary["ml_feature_weights"].values()) == {1.0}
    assert summary["ml_feature_weights"]["log_device_count"] == 1.0
    assert len(summary["feature_names"]) == 22
    assert len(summary["ml_feature_names"]) == 21
    assert len(features) == 4
    first_feature_row = features[1].split("\t")
    first_feature_values = dict(zip(features[0].split("\t"), first_feature_row))
    assert first_feature_values["event_id"] == "evt_1"
    assert first_feature_values["log_domain_count"] == "1.098612"
    assert first_feature_values["pld_click_count"] == "2.000000"
    assert first_feature_values["log_apex_domain_count"] == "1.098612"
    assert first_feature_values["log_query_count"] == "1.098612"
    assert first_feature_values["log_query_domain_count"] == "1.098612"
    assert first_feature_values["log_query_apex_domain_count"] == "1.098612"
    assert first_feature_values["log_landing_count"] == "1.098612"
    assert first_feature_values["log_kp_count"] == "1.386294"
    assert first_feature_values["log_sld_count"] == "1.098612"
    assert first_feature_values["hour"] == "0.000000"
    assert first_feature_values["is_sub_200ms_click"] == "1.000000"
    assert first_feature_values["query_entropy"] == "2.521641"
    assert first_feature_values["unique_chars_ratio"] == "0.857143"
    assert first_feature_values["std_dev_ttc"] == "6.907755"
def test_anomaly_classes_use_selected_counts_and_ml_only_population() -> None:
    events = [
        _classified_event(
            "evt_replay_context",
            heuristic_score=0.86,
            ml_score=0.99,
            combined_score=0.91,
            is_bot=1,
            tier="suppress",
            rule_ids=[
                "repeat_query_domain",
                "repeat_query",
                "confirmed_query_repetition",
                "high_volume_domain",
            ],
        ),
        _classified_event(
            "evt_ml_selected",
            heuristic_score=0.40,
            ml_score=0.99,
            combined_score=0.65,
            is_bot=1,
            tier="quarantine",
            rule_ids=["fast_click"],
        ),
        _classified_event(
            "evt_neither_strong_selected",
            heuristic_score=0.20,
            ml_score=0.20,
            combined_score=0.88,
            is_bot=1,
            tier="quarantine",
            rule_ids=[],
        ),
        _classified_event(
            "evt_ml_monitor",
            heuristic_score=0.10,
            ml_score=0.98,
            combined_score=0.47,
            is_bot=0,
            tier="monitor",
            rule_ids=[],
        ),
    ]

    events[2].flags_assigned = True
    events[2].heuristic_flag = False
    events[2].ml_flag = False
    classes = _anomaly_classes(events)
    by_id = {item["class_id"]: item for item in classes["classes"]}

    assert classes["selected_event_count"] == 3
    assert classes["classified_selected_event_count"] == 2
    assert classes["ml_only_population_count"] == 1
    assert by_id["tier_1_high_confidence"]["count"] == 1
    assert by_id["tier_1_high_confidence"]["tier_counts"] == {
        "suppress": 1,
    }
    assert by_id["tier_1_high_confidence"]["method_counts"] == {
        "Heuristic + ML": 1,
    }
    assert (
        by_id["tier_1_high_confidence"]["examples"][0]["event_id"]
        == "evt_replay_context"
    )
    assert by_id["tier_3_low_confidence_quarantine"]["count"] == 1
    assert by_id["tier_3_low_confidence_quarantine"]["population_count"] == 1
    assert by_id["tier_3_low_confidence_quarantine"]["method_counts"] == {"ML only": 1}
    assert by_id["tier_3_low_confidence_quarantine"]["dominant_rules"] == []
    assert "rule_ids" not in by_id["tier_3_low_confidence_quarantine"]["examples"][0]
    assert "not proven fraud labels" in classes["scope"]


def test_selected_event_dicts_include_review_filter_fields() -> None:
    events = [
        _classified_event(
            "evt_replay_context",
            heuristic_score=0.86,
            ml_score=0.99,
            combined_score=0.91,
            is_bot=1,
            tier="suppress",
            rule_ids=["repeat_query_domain", "high_volume_domain"],
        ),
        _classified_event(
            "evt_ml_selected",
            heuristic_score=0.40,
            ml_score=0.99,
            combined_score=0.65,
            is_bot=1,
            tier="quarantine",
            rule_ids=[],
        ),
        _classified_event(
            "evt_neither_strong_selected",
            heuristic_score=0.40,
            ml_score=0.20,
            combined_score=0.65,
            is_bot=1,
            tier="quarantine",
            rule_ids=[],
        ),
    ]
    events[2].flags_assigned = True
    events[2].heuristic_flag = False
    events[2].ml_flag = False

    rows = _selected_event_dicts(events)

    assert rows[0]["event_id"] == "evt_replay_context"
    assert rows[0]["method_bucket"] == "Heuristic + ML"
    assert rows[0]["evidence_tier"] == 1
    assert rows[0]["confidence_proxy"] == "HIGH"
    assert rows[0]["operational_tier"] == "suppress"
    assert rows[0]["rule_contributions"][0]["rule_id"] == "repeat_query_domain"
    assert rows[1]["method_bucket"] == "ML only"
    assert rows[1]["evidence_tier"] == 3
    assert rows[2]["method_bucket"] == "Neither strong"

    assert _selected_method_counts(events) == {
        "Heuristic + ML": 1,
        "ML only": 1,
        "Neither strong": 1,
    }


def test_selected_is_bot_without_method_flags_is_neither_strong() -> None:
    event = _classified_event(
        "evt_neither_strong_selected",
        heuristic_score=0.40,
        ml_score=0.20,
        combined_score=0.80,
        is_bot=1,
        tier="quarantine",
        rule_ids=[],
    )
    event.flags_assigned = True
    event.heuristic_flag = False
    event.ml_flag = False

    assert _event_method_bucket(event) == "Neither strong"
    assert _selected_method_counts([event]) == {"Neither strong": 1}
    assert _method_disagreement([event]) == [
        ("Heuristic + ML", 0),
        ("Heuristic only", 0),
        ("ML only", 0),
        ("Neither strong", 1),
    ]


def test_unselected_without_method_flags_is_neither_strong() -> None:
    event = _classified_event(
        "evt_monitor",
        heuristic_score=0.40,
        ml_score=0.20,
        combined_score=0.20,
        is_bot=0,
        tier="monitor",
        rule_ids=[],
    )
    event.flags_assigned = True
    event.heuristic_flag = False
    event.ml_flag = False

    assert _event_method_bucket(event) == "Neither strong"


def test_single_event_pipeline_is_not_selected_by_percentile_gate(
    monkeypatch, tmp_path: Path
) -> None:
    install_fake_isotree(monkeypatch)
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
        "/ad_click?d=a.com&ttc=3000&q=human%20search&ct=US&kl=en&kp=-1&sld=1",
        encoding="utf-8",
    )

    summary = run_pipeline(raw, tmp_path)
    submission = (tmp_path / "predictions.tsv").read_text(encoding="utf-8")

    assert summary["bot_events"] == 0
    assert summary["tier_counts"] == {"suppress": 0, "quarantine": 0, "monitor": 1}
    assert submission == "event_id\tis_bot\nevt_1\t0\n"


def test_pipeline_has_no_linear_combined_score_formula() -> None:
    source = Path(pipeline.__file__).read_text(encoding="utf-8")

    forbidden_terms = (
        "_assign_dynamic_combined_scores",
        "_dynamic_blend_weights",
        "_tail_separation",
        "dynamic_heuristic_weight",
        "dynamic_ml_weight",
        "0.58",
        "0.42",
        "heuristic_weight * event.heuristic_score",
        "ml_weight * event.ml_score",
    )
    for term in forbidden_terms:
        assert term not in source
    assert '"is_bot = heuristic_score >= 0.70 OR "' in source
    assert "event.is_bot = 1 if event.heuristic_flag or event.ml_flag else 0" in source
    assert "event.combined_score = max(event.heuristic_score, event.ml_score)" in source


def test_decision_contract_rejects_disconnected_is_bot() -> None:
    # pylint: disable=protected-access
    events = [
        ClickEvent("evt_1", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_2", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
    ]
    events[0].combined_score = 0.80
    events[0].heuristic_score = 0.10
    events[0].is_bot = 1
    events[1].combined_score = 0.20
    events[1].heuristic_score = 0.70
    events[1].is_bot = 1

    with pytest.raises(AssertionError, match="heuristic/ML classifier rule"):
        pipeline._assert_decision_contract(events, 0.50)


def test_decision_contract_rejects_heuristic_override() -> None:
    # pylint: disable=protected-access
    event = ClickEvent("evt_1", datetime(2019, 12, 2), "Mars", "Chrome", "Android", "")
    event.combined_score = 0.20
    event.heuristic_score = 0.95
    event.is_bot = 0

    with pytest.raises(AssertionError, match="heuristic/ML classifier rule"):
        pipeline._assert_decision_contract([event], 0.50)


def test_all_tied_combined_scores_do_not_flag_all_events(
    monkeypatch, tmp_path: Path
) -> None:
    def score_tied_anomalies(events: list[ClickEvent]) -> str:
        for event in events:
            event.ml_score = 0.5
        return "test"

    monkeypatch.setattr("bots_without_labels.pipeline.score_anomalies", score_tied_anomalies)
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                f"evt_{idx}\t2019-12-02 00:00:0{idx}\tMars\tChrome\tiOS\t"
                f"/ad_click?d=a-{idx}.com&ttc=3000&q=human%20search%20{idx}"
                for idx in range(3)
            ]
        ),
        encoding="utf-8",
    )

    summary = run_pipeline(raw, tmp_path)

    assert summary["bot_events"] == 0
    assert summary["tier_counts"] == {"suppress": 0, "quarantine": 0, "monitor": 3}


def test_all_tied_anomaly_scores_use_non_inflated_midrank() -> None:
    events = [
        ClickEvent(f"evt_{idx}", datetime(2019, 12, 2), "Mars", "Chrome", "Android", "")
        for idx in range(4)
    ]

    _assign_rank_scores(events, [0.5, 0.5, 0.5, 0.5])

    assert [event.ml_score for event in events] == [0.5, 0.5, 0.5, 0.5]


def test_assign_rank_scores_accepts_typed_sequence_input() -> None:
    events = tuple(
        ClickEvent(
            f"evt_{idx}",
            datetime(2019, 12, 2),
            "Mars",
            "Chrome",
            "Android",
            "",
        )
        for idx in range(3)
    )

    _assign_rank_scores(events, (0.1, 0.3, 0.2))

    assert [event.ml_score for event in events] == [0.0, 1.0, 0.5]


def test_standardize_constant_feature_uses_unit_std() -> None:
    scaled, means, stds = _standardize([[2.0, 5.0], [4.0, 5.0]])

    assert means == [3.0, 5.0]
    assert stds == [1.0, 1.0]
    assert scaled == [[-1.0, 0.0], [1.0, 0.0]]


def test_excluded_ml_feature_names_is_immutable() -> None:
    assert EXCLUDED_ML_FEATURE_NAMES == frozenset({"pld_click_count"})
    assert not hasattr(EXCLUDED_ML_FEATURE_NAMES, "add")


def test_pseudo_session_burst_counts_handle_empty_and_single_events() -> None:
    event = ClickEvent(
        "evt_1",
        datetime(2019, 12, 2, 0, 0, 0),
        "Mars",
        "Chrome",
        "Android",
        "",
        params={"q": "human search", "d": "example.com"},
    )

    assert not _pseudo_session_burst_counts([])
    assert _pseudo_session_burst_counts([event]) == {id(event): 1}


def test_pseudo_session_burst_counts_include_half_window_edges() -> None:
    start = datetime(2019, 12, 2, 0, 0, 0)
    events = [
        ClickEvent(
            f"evt_{idx}",
            start.replace(second=second),
            "Mars",
            "Chrome",
            "Android",
            "",
            params={"q": "human search", "d": "example.com"},
        )
        for idx, second in enumerate((0, 5, 10, 11))
    ]

    counts = _pseudo_session_burst_counts(events)

    assert [counts[id(event)] for event in events] == [2, 3, 3, 2]


def test_pipeline_handles_empty_input(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text("", encoding="utf-8")

    summary = run_pipeline(raw, tmp_path)

    assert summary["total_events"] == 0
    assert summary["bot_events"] == 0
    assert summary["threshold"] == 0.0
    assert summary["tier_counts"] == {"suppress": 0, "quarantine": 0, "monitor": 0}
    assert (tmp_path / "predictions.tsv").read_text(
        encoding="utf-8"
    ) == "event_id\tis_bot\n"
    assert (tmp_path / "artifacts" / "features.tsv").read_text(encoding="utf-8") == (
        "event_id\t" + "\t".join(summary["feature_names"]) + "\n"
    )
    assert (
        json.loads(
            (tmp_path / "artifacts" / "selected_events.json").read_text(
                encoding="utf-8"
            )
        )
        == []
    )


def test_heuristic_flag_rate_uses_agreement_threshold_constant(
    monkeypatch, tmp_path: Path
) -> None:
    events = [
        ClickEvent("evt_1", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_2", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_3", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
    ]
    for event, score in zip(events, (0.61, 0.70, 0.80)):
        event.heuristic_score = score
        event.features = [score]

    monkeypatch.setattr(pipeline, "SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD", 0.75)
    monkeypatch.setattr(pipeline, "parse_clicks", lambda input_path: events)
    monkeypatch.setattr(
        pipeline,
        "build_features",
        lambda parsed_events: (
            ["heuristic_score"],
            {"domain": Counter(), "query": Counter()},
        ),
    )
    monkeypatch.setattr(
        pipeline, "apply_heuristics", lambda parsed_events, counters: {}
    )
    monkeypatch.setattr(pipeline, "score_anomalies", lambda parsed_events: "fallback")

    summary = run_pipeline(tmp_path / "raw.tsv", tmp_path)

    assert summary["heuristic_flag_rate"] == pytest.approx(1 / 3)
    assert summary["tier_thresholds"]["suppress_agreement_heuristic_score"] == 0.75


def test_summary_exposes_heuristic_ml_agreement_floor_constant(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(pipeline, "parse_clicks", lambda input_path: [])
    monkeypatch.setattr(
        pipeline,
        "build_features",
        lambda parsed_events: ([], {"domain": Counter(), "query": Counter()}),
    )
    monkeypatch.setattr(
        pipeline, "apply_heuristics", lambda parsed_events, counters: {}
    )
    monkeypatch.setattr(pipeline, "score_anomalies", lambda parsed_events: "fallback")

    summary = run_pipeline(tmp_path / "raw.tsv", tmp_path)

    assert summary["tier_thresholds"]["heuristic_ml_agreement_floor"] == (
        HEURISTIC_ML_AGREEMENT_FLOOR
    )


def test_pipeline_preserves_display_input_path_for_temporary_processing(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(pipeline, "parse_clicks", lambda input_path: [])
    monkeypatch.setattr(
        pipeline,
        "build_features",
        lambda parsed_events: ([], {"domain": Counter(), "query": Counter()}),
    )
    monkeypatch.setattr(
        pipeline, "apply_heuristics", lambda parsed_events, counters: {}
    )
    monkeypatch.setattr(pipeline, "score_anomalies", lambda parsed_events: "fallback")

    summary = run_pipeline(
        tmp_path / "tmp-upload.tsv",
        tmp_path,
        display_input_path="original-upload.tsv",
    )

    assert summary["input_path"] == "original-upload.tsv"


def test_pipeline_replaces_outputs_atomically(monkeypatch, tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text("", encoding="utf-8")
    replaced: list[Path] = []
    original_replace = atomic.os.replace

    def record_replace(source, destination) -> None:
        _record_atomic_replace(source, destination, replaced)
        original_replace(source, destination)

    monkeypatch.setattr(atomic.os, "replace", record_replace)

    run_pipeline(raw, tmp_path)

    replaced_names = {path.name for path in replaced}
    assert {
        "predictions.tsv",
        "summary.json",
        "features.tsv",
        "selected_events.json",
        "sample_events.json",
    }.issubset(replaced_names)
    assert not list(tmp_path.glob(".predictions.tsv.*"))
    assert not list((tmp_path / "artifacts").glob(".*"))


def test_write_features_rejects_feature_name_mismatch(tmp_path: Path) -> None:
    event = ClickEvent("evt_1", datetime(2019, 12, 2), "Mars", "Chrome", "Android", "")
    event.features = [1.0]
    path = tmp_path / "features.tsv"

    with pytest.raises(ValueError, match="evt_1 has 1 features; expected 2"):
        # Accessing the private writer keeps the validation failure hermetic.
        # pylint: disable=protected-access
        pipeline._write_features(path, ["feature_a", "feature_b"], [event])

    assert not path.exists()


def test_pipeline_uses_eif_backend(monkeypatch, tmp_path: Path) -> None:
    install_fake_isotree(monkeypatch)
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
                "/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&"
                "kp=-1&sld=1&st=mobile_search_intl",
                "evt_2\t2019-12-02 00:00:01\tMars\tChrome\tiOS\t"
                "/ad_click?d=a.com&ttc=20&q=foo%20bar&ct=US&kl=en&"
                "kp=-1&sld=1&st=mobile_search_intl",
                "evt_3\t2019-12-02 00:00:02\tVenus\tSafari\tAndroid\t"
                "/ad_click?d=b.com&ttc=3000&q=human%20search&ct=GB&"
                "kl=uk&kp=-1&sld=0&st=mobile_search_intl",
            ]
        ),
        encoding="utf-8",
    )

    summary = run_pipeline(raw, tmp_path)

    assert summary["ml_backend"] == "eif"
    assert FakeEIF.last_instance is not None
    assert FakeEIF.last_instance.sample_size == 3
    assert FakeEIF.last_instance.ndim == 2
    assert FakeEIF.last_instance.standardize_data is False
    assert FakeEIF.last_instance.fit_column_count == 21


def test_pipeline_eif_backend_reports_missing_dependency(
    monkeypatch, tmp_path: Path
) -> None:
    hide_isotree(monkeypatch)
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
        "/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&kp=-1&"
        "sld=1&st=mobile_search_intl",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Extended Isolation Forest requires isotree"):
        run_pipeline(raw, tmp_path)


def test_normalize_reason_handles_regular_interarrival() -> None:
    assert (
        _normalize_reason(
            "regular inter-arrival timing (8 clicks, mean 214.7s, cv 0.224)"
        )
        == "regular inter-arrival timing"
    )


def test_normalize_reason_handles_dense_burst_repetition_cluster() -> None:
    assert (
        _normalize_reason(
            "dense burst repetition cluster (device 43674, same-second 5, query 1226)"
        )
        == "dense burst repetition cluster"
    )


def test_normalize_reason_handles_confirmed_query_repetition() -> None:
    assert (
        _normalize_reason("confirmed query repetition (query/domain 184, query 1226)")
        == "confirmed query repetition"
    )


def test_normalize_reason_handles_concentrated_ct_context() -> None:
    assert (
        _normalize_reason("concentrated ct context (US 1000, device 600, query 12)")
        == "concentrated ct context"
    )


def test_method_disagreement_buckets_partition_events_by_agreement_thresholds() -> None:
    events = [
        ClickEvent("evt_1", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_2", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_3", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_4", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
    ]
    events[0].heuristic_score = 0.70
    events[0].ml_score = 0.976
    events[1].heuristic_score = 0.70
    events[1].ml_score = 0.10
    events[2].heuristic_score = 0.10
    events[2].ml_score = 1.0
    events[3].heuristic_score = 0.10
    events[3].ml_score = 0.10

    assert _method_disagreement(events) == [
        ("Heuristic + ML", 1),
        ("Heuristic only", 1),
        ("ML only", 1),
        ("Neither strong", 1),
    ]
    assert _method_disagreement(events, ml_threshold=0.975) == [
        ("Heuristic + ML", 1),
        ("Heuristic only", 1),
        ("ML only", 1),
        ("Neither strong", 1),
    ]


def test_method_disagreement_uses_single_ml_agreement_threshold() -> None:
    events = [
        ClickEvent("evt_1", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_2", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_3", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_4", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
    ]
    events[0].heuristic_score = 0.70
    events[0].ml_score = 0.980
    events[1].heuristic_score = 0.70
    events[1].ml_score = 0.994
    events[2].heuristic_score = 0.10
    events[2].ml_score = 0.980
    events[3].heuristic_score = 0.10
    events[3].ml_score = 0.10

    assert _method_disagreement(events) == [
        ("Heuristic + ML", 2),
        ("Heuristic only", 0),
        ("ML only", 1),
        ("Neither strong", 1),
    ]


def test_operational_tier_boundaries() -> None:
    event = ClickEvent("evt", datetime(2019, 12, 2), "Mars", "Chrome", "Android", "")

    event.is_bot = 0
    event.combined_score = 0.99
    event.heuristic_score = 1.0
    event.ml_score = 1.0
    assert _assign_operational_tier(event) == "monitor"

    event.is_bot = 1
    event.evidence_tier = 3
    event.combined_score = 0.7999
    event.heuristic_score = 0.6199
    event.ml_score = 0.8999
    assert _assign_operational_tier(event) == "quarantine"

    event.evidence_tier = 2
    event.combined_score = 0.80
    assert _assign_operational_tier(event) == "quarantine"

    event.evidence_tier = 2
    event.combined_score = 0.50
    event.heuristic_score = 0.80
    event.ml_score = 0.20
    assert _assign_operational_tier(event) == "quarantine"

    event.evidence_tier = 1
    event.heuristic_score = 0.70
    event.ml_score = 0.975
    assert _assign_operational_tier(event) == "suppress"

"""Run-history persistence and drift awareness (roadmap item 7).

Covers the task contract: first run with no history succeeds and records;
an identical repeat is stable with no warning; a sharp shift versus the
previous record warns; corrupt history is a non-fatal warning, never a
failure; and the drift path is decision-neutral (predictions byte-identical
whatever the history says).
"""

from __future__ import annotations

import json
from pathlib import Path

from bots_without_labels import history
from bots_without_labels.pipeline import run_pipeline
from bots_without_labels.synthetic import generate, write_log


def _synthetic_tsv(path: Path) -> Path:
    write_log(path, generate(n_legit=500, n_bots=60, seed=2).frame)
    return path


def _history_records(out: Path) -> list[dict]:
    lines = (out / "artifacts" / history.HISTORY_FILENAME).read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


# --- unit level: assess_drift / read_history ---------------------------------


def _record(**overrides) -> dict:
    base = {
        "run_index": 0,
        "flag_rate": 0.10,
        "heuristic_flag_rate": 0.08,
        "ml_flag_rate": 0.02,
        "ml_score_quantiles": {"q50": 0.30, "q90": 0.50, "q99": 0.70},
        "heuristic_score_quantiles": {"q50": 0.00, "q90": 0.40, "q99": 0.70},
        "top_rules": [["entity_monotony", 40], ["repeat_value", 25]],
    }
    base.update(overrides)
    return base


def test_assess_drift_no_history() -> None:
    drift = history.assess_drift(None, _record())
    assert drift == {"status": "no_history", "warnings": [], "previous_run_index": None}


def test_assess_drift_stable_on_identical_record() -> None:
    drift = history.assess_drift(_record(), _record(run_index=1))
    assert drift["status"] == "stable"
    assert drift["warnings"] == []
    assert drift["previous_run_index"] == 0


def test_assess_drift_flag_rate_shift_warns() -> None:
    drift = history.assess_drift(_record(), _record(flag_rate=0.30))
    assert drift["status"] == "drift"
    assert any("overall flag rate" in warning for warning in drift["warnings"])


def test_assess_drift_quantile_shift_warns() -> None:
    shifted = _record(ml_score_quantiles={"q50": 0.30, "q90": 0.80, "q99": 0.90})
    drift = history.assess_drift(_record(), shifted)
    assert drift["status"] == "drift"
    assert any("ML score q90" in warning for warning in drift["warnings"])


def test_assess_drift_disjoint_top_rules_warns() -> None:
    shifted = _record(top_rules=[["asymmetric_degree", 90]])
    drift = history.assess_drift(_record(), shifted)
    assert drift["status"] == "drift"
    assert any("top firing rules" in warning for warning in drift["warnings"])


def test_read_history_tolerates_corruption(tmp_path: Path) -> None:
    path = tmp_path / history.HISTORY_FILENAME
    path.write_text('{"run_index": 0, "flag_rate": 0.1}\nnot json at all\n[1,2]\n')
    records, warning = history.read_history(path)
    assert len(records) == 1
    assert warning is not None and "ignored" in warning


def test_append_record_caps_length(tmp_path: Path) -> None:
    path = tmp_path / history.HISTORY_FILENAME
    records: list[dict] = []
    for _ in range(history.HISTORY_MAX_RECORDS + 7):
        record = _record()
        history.append_record(path, record, records)
        records, warning = history.read_history(path)
        assert warning is None
    assert len(records) == history.HISTORY_MAX_RECORDS
    # run_index keeps increasing even after the oldest records are dropped.
    assert records[-1]["run_index"] == history.HISTORY_MAX_RECORDS + 6


# --- end to end through run_pipeline ------------------------------------------


def test_first_run_records_history_without_warning(tmp_path: Path) -> None:
    log = _synthetic_tsv(tmp_path / "syn.tsv")
    out = tmp_path / "out"
    summary = run_pipeline(log, out)

    assert summary["drift"]["status"] == "no_history"
    assert summary["drift"]["warnings"] == []
    records = _history_records(out)
    assert len(records) == 1
    assert records[0]["run_index"] == 0
    assert records[0]["flag_rate"] == summary["bot_rate"]
    assert records[0]["top_rules"]


def test_identical_repeat_is_stable(tmp_path: Path) -> None:
    log = _synthetic_tsv(tmp_path / "syn.tsv")
    out = tmp_path / "out"
    first = run_pipeline(log, out)
    second = run_pipeline(log, out)

    assert second["drift"]["status"] == "stable"
    assert second["drift"]["warnings"] == []
    assert second["drift"]["previous_run_index"] == 0
    assert second["bot_rate"] == first["bot_rate"]
    assert len(_history_records(out)) == 2


def test_sharp_drift_warns_and_leaves_decisions_unchanged(
    capsys, tmp_path: Path
) -> None:
    log = _synthetic_tsv(tmp_path / "syn.tsv")
    out = tmp_path / "out"
    baseline = run_pipeline(log, out)
    baseline_predictions = (out / "predictions.tsv").read_bytes()

    # Fabricate a wildly different "previous run" as the last history record.
    records = _history_records(out)
    fabricated = dict(records[-1])
    fabricated["run_index"] = 1
    fabricated["flag_rate"] = 0.95
    fabricated["ml_score_quantiles"] = {"q50": 0.95, "q90": 0.99, "q99": 1.0}
    path = out / "artifacts" / history.HISTORY_FILENAME
    path.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in [*records, fabricated]) + "\n"
    )

    summary = run_pipeline(log, out)
    assert summary["drift"]["status"] == "drift"
    assert summary["drift"]["previous_run_index"] == 1
    assert any("flag rate" in warning for warning in summary["drift"]["warnings"])
    assert "Drift warning:" in capsys.readouterr().out

    # Decision-neutral: identical predictions and identical decisions,
    # whatever the history claimed.
    assert (out / "predictions.tsv").read_bytes() == baseline_predictions
    assert summary["bot_events"] == baseline["bot_events"]
    assert summary["bot_rate"] == baseline["bot_rate"]


def test_corrupt_history_is_nonfatal(tmp_path: Path) -> None:
    log = _synthetic_tsv(tmp_path / "syn.tsv")
    out = tmp_path / "out"
    (out / "artifacts").mkdir(parents=True)
    (out / "artifacts" / history.HISTORY_FILENAME).write_text("{{{ garbage\n")

    summary = run_pipeline(log, out)
    assert summary["drift"]["status"] == "no_history"
    assert any("ignored" in warning for warning in summary["drift"]["warnings"])
    records = _history_records(out)
    assert len(records) == 1  # fresh record written, garbage dropped

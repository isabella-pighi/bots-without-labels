"""Tests for the end-to-end detection pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from bots_without_labels.evaluate import evaluate_injection
from bots_without_labels.ingest import load
from bots_without_labels.pipeline import HEURISTIC_CUTOFF, detect, run_pipeline
from bots_without_labels.synthetic import (
    DETECTABLE_ARCHETYPES,
    generate,
    write_log,
)


def _synthetic_tsv(path: Path, **kwargs) -> object:
    log = generate(**kwargs)
    write_log(path, log.frame)
    return log


def test_decision_contract_holds(tmp_path: Path) -> None:
    _synthetic_tsv(tmp_path / "syn.tsv", n_legit=400, n_bots=50, seed=2)
    loaded = load(tmp_path / "syn.tsv")
    result = detect(loaded.frame, loaded.schema)
    expected = (
        (result.heuristic >= HEURISTIC_CUTOFF)
        | (result.ml_scores > result.ml_threshold)
    ).astype(int)
    assert np.array_equal(result.is_bot, expected)
    assert result.combined.max() <= 1.0 and result.combined.min() >= 0.0


def test_run_pipeline_writes_artifacts(tmp_path: Path) -> None:
    _synthetic_tsv(tmp_path / "syn.tsv", n_legit=500, n_bots=60, seed=2)
    out = tmp_path / "out"
    summary = run_pipeline(tmp_path / "syn.tsv", out)

    assert summary["total_events"] == 560
    assert summary["bot_events"] > 0
    assert summary["id_column"] == "event_id"
    for artefact in (
        "summary.json",
        "features.tsv",
        "selected_events.json",
        "ml_score_threshold.png",
    ):
        assert (out / "artifacts" / artefact).exists()

    predictions = (out / "predictions.tsv").read_text(encoding="utf-8").splitlines()
    assert predictions[0] == "event_id\tis_bot"
    assert all(len(line.split("\t")) == 2 for line in predictions[1:])

    written = json.loads((out / "artifacts" / "summary.json").read_text())
    assert written["decision_rule"].startswith("is_bot =")

    # Every selected event carries its top feature deviations, so an ML-only
    # flag (tier 3, no rule reasons) is still reviewable.
    selected = json.loads((out / "artifacts" / "selected_events.json").read_text())
    assert selected
    for record in selected:
        devs = record["feature_deviations"]
        assert 0 < len(devs) <= 5
        for entry in devs:
            assert set(entry) == {"feature", "value", "robust_z", "batch_percentile"}
            assert 0.0 <= entry["batch_percentile"] <= 1.0
        zs = [abs(entry["robust_z"]) for entry in devs]
        assert zs == sorted(zs, reverse=True)


def test_feature_deviations_align_with_feature_names(tmp_path: Path) -> None:
    _synthetic_tsv(tmp_path / "syn.tsv", n_legit=400, n_bots=50, seed=2)
    loaded = load(tmp_path / "syn.tsv")
    result = detect(loaded.frame, loaded.schema)
    flagged = [int(row) for row in np.flatnonzero(result.is_bot)[:3]]
    deviations = result.feature_deviations(flagged)
    assert len(deviations) == len(flagged)
    for devs in deviations:
        assert devs
        assert all(entry["feature"] in result.feature_set.names for entry in devs)


def test_pipeline_recovers_planted_bots(tmp_path: Path) -> None:
    log = _synthetic_tsv(tmp_path / "syn.tsv", n_legit=900, n_bots=80, seed=2)
    loaded = load(tmp_path / "syn.tsv")
    result = detect(loaded.frame, loaded.schema)
    report = evaluate_injection(result.is_bot, log.is_bot, log.archetype)
    per = report["per_archetype"]
    # The timing archetypes are recovered reliably and what we flag is a planted
    # bot. The evasive archetypes (diffuse_replay, stealth) are not recovered, by
    # design, so overall recall sits well below 1.0 -- assert that gap honestly
    # rather than pretending every plant is detectable.
    for name in DETECTABLE_ARCHETYPES:
        assert per[name]["recall"] >= 0.85, f"{name} recall {per[name]['recall']:.2f}"
    assert report["planted_precision"] >= 0.9
    # Every evasive archetype stays clearly below the worst detectable one --
    # self-calibrating, so it documents the gap without a brittle magic number.
    floor = min(per[name]["recall"] for name in DETECTABLE_ARCHETYPES)
    hard = [a for a in per if a not in DETECTABLE_ARCHETYPES]
    assert all(per[name]["recall"] < floor for name in hard)


def test_run_is_deterministic(tmp_path: Path) -> None:
    _synthetic_tsv(tmp_path / "syn.tsv", n_legit=400, n_bots=40, seed=2)
    first = run_pipeline(tmp_path / "syn.tsv", tmp_path / "a")
    second = run_pipeline(tmp_path / "syn.tsv", tmp_path / "b")
    assert first["bot_events"] == second["bot_events"]
    assert first["ml_threshold"] == second["ml_threshold"]

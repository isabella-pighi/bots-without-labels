"""Tests for the explainable rule detector."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from bots_without_labels.features import build_features
from bots_without_labels.ingest import load
from bots_without_labels.rules import apply_rules
from bots_without_labels.synthetic import ARCHETYPES, generate, write_log


def _scored(tmp_path: Path):
    log = generate(n_legit=600, n_bots=80, seed=4)
    path = tmp_path / "syn.tsv"
    write_log(path, log.frame)
    loaded = load(path)
    feature_set = build_features(loaded.frame, loaded.schema)
    result = apply_rules(loaded.frame, loaded.schema, feature_set)
    return log, result


def test_scores_are_bounded(tmp_path: Path) -> None:
    _, result = _scored(tmp_path)
    assert result.scores.min() >= 0.0
    assert result.scores.max() <= 1.0


def test_every_bot_archetype_clears_the_cutoff(tmp_path: Path) -> None:
    log, result = _scored(tmp_path)
    archetypes = np.array([str(a) for a in log.archetype], dtype=object)
    for name in ARCHETYPES:
        rows = np.where(archetypes == name)[0]
        median = float(np.median(result.scores[rows]))
        assert median >= 0.70, f"{name} median heuristic {median:.2f} below cutoff"


def test_legitimate_traffic_scores_low(tmp_path: Path) -> None:
    log, result = _scored(tmp_path)
    legit = np.where(np.array([a is None for a in log.archetype]))[0]
    assert float(np.median(result.scores[legit])) < 0.70
    assert float((result.scores[legit] >= 0.70).mean()) < 0.05


def test_flagged_rows_carry_reasons(tmp_path: Path) -> None:
    _, result = _scored(tmp_path)
    reasons = result.reasons()
    for row in range(len(result.scores)):
        if result.scores[row] >= 0.70:
            assert reasons[row], "a flagged row must have at least one reason"

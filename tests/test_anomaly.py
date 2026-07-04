"""Tests for matrix-based anomaly scoring."""

from __future__ import annotations

import numpy as np

from bots_without_labels.anomaly import feature_deviations, score_matrix


def test_scores_are_bounded_and_aligned() -> None:
    rng = np.random.default_rng(0)
    matrix = rng.normal(size=(200, 5))
    scores, backend = score_matrix(matrix)
    assert scores.shape == (200,)
    assert scores.min() >= 0.0 and scores.max() <= 1.0
    assert backend in {"eif", "fallback"}


def test_clear_outlier_scores_high() -> None:
    rng = np.random.default_rng(1)
    matrix = rng.normal(scale=0.1, size=(200, 4))
    matrix[0] = [20.0, 20.0, 20.0, 20.0]  # a blatant outlier
    scores, _ = score_matrix(matrix)
    assert scores[0] >= np.quantile(scores, 0.95)


def test_degenerate_inputs() -> None:
    scores, backend = score_matrix(np.zeros((0, 3)))
    assert scores.shape == (0,) and backend == "degenerate"
    scores, backend = score_matrix(np.zeros((5, 0)))
    assert np.allclose(scores, 0.5) and backend == "degenerate"


def test_deterministic() -> None:
    rng = np.random.default_rng(2)
    matrix = rng.normal(size=(150, 6))
    first, _ = score_matrix(matrix)
    second, _ = score_matrix(matrix)
    assert np.array_equal(first, second)


def test_feature_deviations_explain_an_outlier() -> None:
    rng = np.random.default_rng(3)
    matrix = rng.normal(scale=0.1, size=(200, 4))
    # Row 0 is extreme in exactly two features; the others stay ordinary.
    matrix[0, 1] = 50.0
    matrix[0, 3] = -50.0
    names = ["a__val", "b__val", "c__val", "d__val"]

    (devs,) = feature_deviations(matrix, names, [0], top_k=3)

    assert len(devs) == 3
    # The two planted extremes rank first, sorted by |robust_z| descending.
    assert {devs[0]["feature"], devs[1]["feature"]} == {"b__val", "d__val"}
    zs = [abs(entry["robust_z"]) for entry in devs]
    assert zs == sorted(zs, reverse=True)
    assert zs[0] > 10.0  # far out in MAD units
    # The percentile carries the "top/bottom 1% of the batch" reading, signed.
    by_name = {entry["feature"]: entry for entry in devs}
    assert by_name["b__val"]["batch_percentile"] >= 0.99
    assert by_name["b__val"]["robust_z"] > 0
    assert by_name["d__val"]["batch_percentile"] <= 0.01
    assert by_name["d__val"]["robust_z"] < 0
    assert by_name["b__val"]["value"] == 50.0


def test_feature_deviations_degenerate_inputs() -> None:
    assert feature_deviations(np.zeros((5, 0)), [], [0, 2]) == [[], []]
    assert not feature_deviations(np.zeros((0, 3)), ["a", "b", "c"], [])

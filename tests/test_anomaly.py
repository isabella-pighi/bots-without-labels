"""Tests for matrix-based anomaly scoring."""

from __future__ import annotations

import numpy as np

from bots_without_labels.anomaly import score_matrix


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

"""Tests for self-tuning threshold selection."""

from __future__ import annotations

from bots_without_labels.threshold import dynamic_knee_threshold


def test_empty_input() -> None:
    assert dynamic_knee_threshold([]) == (0.0, "empty_input")


def test_small_input_returns_max() -> None:
    threshold, method = dynamic_knee_threshold([0.1, 0.9, 0.3])
    assert method == "small_input_fallback"
    assert threshold == 0.9


def test_tied_scores_fallback() -> None:
    threshold, method = dynamic_knee_threshold([0.5] * 20)
    assert method == "tied_score_fallback"
    assert threshold == 0.5


def test_elbow_sits_between_tail_and_body() -> None:
    # A short anomalous tail near 1.0 over a long flat body near 0.0.
    scores = [0.98, 0.97, 0.95, 0.93] + [0.05 + i * 1e-4 for i in range(200)]
    threshold, method = dynamic_knee_threshold(scores)
    assert method in {"kneedle_descending", "max_distance_descending_fallback"}
    assert 0.05 < threshold <= 0.98
    # The tail stays above the threshold; the body stays below it.
    flagged = sum(1 for score in scores if score > threshold)
    assert 1 <= flagged <= 20

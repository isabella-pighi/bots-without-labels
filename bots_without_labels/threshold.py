"""Self-tuning anomaly threshold selection.

The detector has no labels, so it cannot pick an operating threshold by
optimising accuracy. Instead it finds the "elbow" of the sorted anomaly-score
curve — the point where the steep anomaly tail gives way to the flat body of
ordinary traffic — using the Kneedle method, with a geometric fallback.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

SMALL_INPUT_SIZE = 10
"""Below this many finite scores there is no curve to find an elbow on; the
maximum score is returned instead (nothing is flagged)."""

TIED_SCORE_MIN_DISTINCT = 3
"""Fewer distinct score values than this means the "curve" is a step function;
Kneedle would be meaningless, so the maximum score is returned instead."""


def dynamic_knee_threshold(scores: Sequence[float]) -> tuple[float, str]:
    """Return a self-tuned anomaly threshold and the method used.

    Scores are sorted from most to least anomalous (non-finite values dropped),
    then Kneedle locates the elbow of the convex, decreasing curve.

    Args:
        scores: Anomaly scores in any order.

    Returns:
        A pair ``(threshold, method)``, where ``method`` is one of
        ``"empty_input"``, ``"small_input_fallback"``, ``"tied_score_fallback"``,
        ``"kneedle_descending"`` (the normal path), or
        ``"max_distance_descending_fallback"`` (geometric fallback when Kneedle
        is unavailable or finds no interior knee).
    """

    ordered = sorted(
        (float(score) for score in scores if math.isfinite(float(score))),
        reverse=True,
    )
    if not ordered:
        return 0.0, "empty_input"
    if len(ordered) < SMALL_INPUT_SIZE:
        return max(ordered), "small_input_fallback"
    if len(set(ordered)) < TIED_SCORE_MIN_DISTINCT:
        return max(ordered), "tied_score_fallback"
    kneedle = _kneedle_threshold(ordered)
    if kneedle is not None:
        return kneedle, "kneedle_descending"
    return _max_distance_threshold(ordered), "max_distance_descending_fallback"


def _kneedle_threshold(ordered_scores: Sequence[float]) -> float | None:
    # pylint: disable=import-outside-toplevel
    try:
        from kneed import KneeLocator
    except ImportError:
        return None
    positions = _normalised_positions(len(ordered_scores))
    locator = KneeLocator(
        positions,
        list(ordered_scores),
        curve="convex",
        direction="decreasing",
        online=False,
    )
    if locator.knee is None:
        return None
    index = _nearest_index(positions, float(locator.knee))
    if index <= 0 or index >= len(ordered_scores) - 1:
        return None
    return float(ordered_scores[index])


def _max_distance_threshold(ordered_scores: Sequence[float]) -> float:
    positions = _normalised_positions(len(ordered_scores))
    values = _normalise(ordered_scores)
    distances = [abs(value - (1.0 - pos)) for pos, value in zip(positions, values)]
    index = max(range(len(distances)), key=distances.__getitem__)
    return float(ordered_scores[index])


def _normalised_positions(length: int) -> list[float]:
    if length <= 1:
        return [0.0]
    return [index / (length - 1) for index in range(length)]


def _normalise(values: Sequence[float]) -> list[float]:
    minimum, maximum = min(values), max(values)
    spread = maximum - minimum
    if spread <= 0.0:
        return [0.0 for _ in values]
    return [(value - minimum) / spread for value in values]


def _nearest_index(values: Sequence[float], needle: float) -> int:
    return min(range(len(values)), key=lambda index: abs(values[index] - needle))

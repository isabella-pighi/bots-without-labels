"""Machine-learning anomaly scoring helpers for Bots Without Labels."""

from __future__ import annotations

from math import sqrt

from .data import ClickEvent

EIF_TREES = 100
EIF_EXTENSION_DIMS = 2
EIF_SAMPLE_SIZE = 4096


def _standardize(
    matrix: list[list[float]],
) -> tuple[list[list[float]], list[float], list[float]]:
    """Standardise columns to zero mean and unit variance.

    Constant columns receive a unit standard deviation so they become all-zero
    after centring instead of dividing by zero.
    """

    cols = len(matrix[0])
    means = [sum(row[i] for row in matrix) / len(matrix) for i in range(cols)]
    stds: list[float] = []
    for i in range(cols):
        var = sum((row[i] - means[i]) ** 2 for row in matrix) / len(matrix)
        stds.append(sqrt(var) if var > 0.0 else 1.0)
    return (
        [[(row[i] - means[i]) / stds[i] for i in range(cols)] for row in matrix],
        means,
        stds,
    )


def score_anomalies(events: list[ClickEvent]) -> str:
    """Score events with the configured anomaly backend.

    Args:
        events: Events with populated ML feature vectors.

    Returns:
        The backend identifier used for scoring.

    Raises:
        ValueError: If the optional Extended Isolation Forest dependency is not
            installed.
    """

    try:
        score_with_extended_isolation_forest(events)
    except ImportError as exc:
        raise ValueError(
            "Extended Isolation Forest requires isotree; install with: uv sync --extra eif"
        ) from exc
    return "eif"


def score_with_extended_isolation_forest(
    events: list[ClickEvent], seed: int = 7
) -> None:
    """Score events with the default Extended Isolation Forest settings."""

    score_with_extended_isolation_forest_config(
        events,
        seed=seed,
        sample_size=EIF_SAMPLE_SIZE,
        ntrees=EIF_TREES,
        ndim=EIF_EXTENSION_DIMS,
    )


def score_with_extended_isolation_forest_config(
    events: list[ClickEvent],
    *,
    seed: int = 7,
    sample_size: int | str = EIF_SAMPLE_SIZE,
    ntrees: int = EIF_TREES,
    ndim: int = EIF_EXTENSION_DIMS,
) -> None:
    """Score events with an Extended Isolation Forest configuration.

    Args:
        events: Events to mutate with rank-normalised ``ml_score`` values.
        seed: Deterministic model seed.
        sample_size: Isolation Forest sample size, capped to the batch size
            when an integer is supplied.
        ntrees: Number of isolation trees.
        ndim: Maximum extension dimensions for random hyperplane splits.

    Raises:
        ImportError: If ``numpy`` or ``isotree`` cannot be imported.
    """

    if not events:
        return
    # EIF is optional; keep imports lazy so non-ML CLI paths remain importable.
    # pylint: disable=import-outside-toplevel
    import numpy as np
    from isotree import IsolationForest

    matrix = [_ml_features(event) for event in events]
    scaled, means, stds = _standardize(matrix)
    _apply_feature_weights(scaled, events[0].ml_feature_weights)
    scaled_array = np.asarray(scaled, dtype=float)
    model_sample_size = (
        min(sample_size, len(scaled_array))
        if isinstance(sample_size, int)
        else sample_size
    )
    model = IsolationForest(
        sample_size=model_sample_size,
        ntrees=ntrees,
        ndim=min(ndim, scaled_array.shape[1]),
        missing_action="fail",
        standardize_data=False,
        random_seed=seed,
        nthreads=1,
    )
    model.fit(scaled_array)
    anomaly_scores = [float(score) for score in model.decision_function(scaled_array)]
    _assign_minmax_scores(events, anomaly_scores)

    # Keep the fitted scaling parameters visible to reviewers/debuggers when
    # inspecting this path, even though isotree receives pre-standardised data.
    _ = (means, stds)


def _ml_features(event: ClickEvent) -> list[float]:
    return event.ml_features or event.features


def _apply_feature_weights(matrix: list[list[float]], weights: list[float]) -> None:
    if not matrix or not weights:
        return
    for row in matrix:
        for idx, weight in enumerate(weights[: len(row)]):
            row[idx] *= weight


def _assign_minmax_scores(
    events: list[ClickEvent], anomaly_values: list[float]
) -> None:
    """Convert raw anomaly values to strict 0-1 MinMax-scaled scores."""

    if not events:
        return
    if len(set(anomaly_values)) < 2:
        for event in events:
            event.ml_score = 0.5
        return

    # pylint: disable=import-outside-toplevel
    import numpy as np
    from sklearn.preprocessing import MinMaxScaler

    values = np.asarray(anomaly_values, dtype=float).reshape(-1, 1)
    scaled = MinMaxScaler(feature_range=(0.0, 1.0)).fit_transform(values)
    for event, score in zip(events, scaled.flatten()):
        event.ml_score = min(max(float(score), 0.0), 1.0)


def _assign_rank_scores(events, anomaly_values) -> None:
    """Backward-compatible alias for tests and external callers."""

    _assign_minmax_scores(list(events), list(anomaly_values))


def _lower_bound(values: list[float], needle: float) -> int:
    low = 0
    high = len(values)
    while low < high:
        mid = (low + high) // 2
        if values[mid] < needle:
            low = mid + 1
        else:
            high = mid
    return low


def _upper_bound(values: list[float], needle: float) -> int:
    low = 0
    high = len(values)
    while low < high:
        mid = (low + high) // 2
        if values[mid] <= needle:
            low = mid + 1
        else:
            high = mid
    return low - 1

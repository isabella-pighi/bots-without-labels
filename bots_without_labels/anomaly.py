"""Unsupervised multivariate anomaly scoring over a feature matrix.

Scores a numeric feature matrix with an Extended Isolation Forest when the
optional ``isotree`` backend is installed, and otherwise falls back to a
dependency-free standardised-deviation score. Either way the output is a 0-1
array where higher means more anomalous, so the rest of the pipeline does not
care which backend ran.
"""

from __future__ import annotations

import numpy as np

EIF_TREES = 100
EIF_EXTENSION_DIMS = 2
EIF_SAMPLE_SIZE = 4096


def score_matrix(matrix: np.ndarray, *, seed: int = 7) -> tuple[np.ndarray, str]:
    """Return per-row anomaly scores in ``[0, 1]`` and the backend used.

    Args:
        matrix: ``(n_rows, n_features)`` float matrix.
        seed: Deterministic model seed.

    Returns:
        A pair ``(scores, backend)`` where ``backend`` is ``"eif"``,
        ``"fallback"``, or ``"degenerate"`` (too few rows/features to score).
    """

    matrix = np.asarray(matrix, dtype=float)
    n_rows = matrix.shape[0]
    if n_rows == 0:
        return np.zeros(0), "degenerate"
    if matrix.shape[1] == 0 or n_rows < 3:
        return np.full(n_rows, 0.5), "degenerate"

    scaled = _standardize(matrix)
    raw = _extended_isolation_forest(scaled, seed=seed)
    if raw is not None:
        return _minmax(raw), "eif"
    return _minmax(_deviation_score(scaled)), "fallback"


def _standardize(matrix: np.ndarray) -> np.ndarray:
    means = matrix.mean(axis=0)
    stds = matrix.std(axis=0)
    stds[stds == 0.0] = 1.0
    scaled = (matrix - means) / stds
    # Defensive: never pass NaN/inf to the forest (missing_action="fail").
    return np.nan_to_num(scaled, nan=0.0, posinf=0.0, neginf=0.0)


def _extended_isolation_forest(scaled: np.ndarray, *, seed: int) -> np.ndarray | None:
    # pylint: disable=import-outside-toplevel
    try:
        from isotree import IsolationForest
    except ImportError:
        return None
    model = IsolationForest(
        sample_size=min(EIF_SAMPLE_SIZE, scaled.shape[0]),
        ntrees=EIF_TREES,
        ndim=min(EIF_EXTENSION_DIMS, scaled.shape[1]),
        missing_action="fail",
        standardize_data=False,
        random_seed=seed,
        nthreads=1,
    )
    model.fit(scaled)
    return np.asarray(model.decision_function(scaled), dtype=float)


def _deviation_score(scaled: np.ndarray) -> np.ndarray:
    """Mean absolute standardised deviation across features.

    A transparent stand-in for the isolation forest: rows whose features sit far
    from the batch norm on average score higher.
    """

    return np.abs(scaled).mean(axis=1)


def _minmax(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    minimum, maximum = float(values.min()), float(values.max())
    if maximum - minimum <= 0.0:
        return np.full(values.shape[0], 0.5)
    scaled = (values - minimum) / (maximum - minimum)
    return np.clip(scaled, 0.0, 1.0)

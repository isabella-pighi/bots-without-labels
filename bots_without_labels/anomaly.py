"""Unsupervised multivariate anomaly scoring over a feature matrix.

Scores a numeric feature matrix with an Extended Isolation Forest when the
optional ``isotree`` backend is installed, and otherwise falls back to a
dependency-free marginal-deviation score.

Two deliberate choices, following the isolation-forest literature (Liu, Ting &
Zhou 2008/2012; Hariri, Carrasco Kind & Brunner 2019):

* Features are standardised with **median / MAD** (robust z-scores), not
  mean / standard deviation. Log-count and concentration features in real logs
  are heavy-tailed, where a few automated mega-clusters inflate the standard
  deviation and *mask* the anomalies; the median and MAD are not distorted by
  that tail.
* The Extended Isolation Forest's own ``decision_function`` is already a bounded
  ``[0, 1]`` anomaly score with the standard sample-size normalisation, so it is
  used **as-is** rather than re-min-maxed per batch (which would throw away that
  calibration and make the score depend on the single most- and least-anomalous
  rows in the batch). The dependency-free fallback has no natural scale, so it is
  min-max mapped to ``[0, 1]`` and is, honestly, a weaker marginal detector.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import rankdata

EIF_TREES = 100
"""Forest size. The literature's default; scores stabilise well before this."""
EIF_EXTENSION_DIMS = 2
"""Extension level: split hyperplanes combine up to 2 features, enough to catch
pairwise interactions (same-context *and* same-instant) without the noise of
fully oblique splits."""
EIF_SAMPLE_SIZE = 4096
"""Per-tree subsample. Isolation forests deliberately subsample -- small trees
isolate anomalies faster and mask less -- so this does not grow with the log."""

DEGENERATE_ANOMALY_SCORE = 0.5
"""Uninformative midpoint score used when there is nothing to rank: too few
rows/features to model, or a constant fallback score vector."""

TOP_DEVIATION_FEATURES = 5
"""Feature deviations reported per explained row: enough to read why a row is
anomalous, short enough to scan in a review queue."""

_MAD_TO_STD = 1.4826  # makes MAD a consistent estimator of the std for normal data


def score_matrix(matrix: np.ndarray, *, seed: int = 7) -> tuple[np.ndarray, str]:
    """Return per-row anomaly scores in ``[0, 1]`` and the backend used.

    Args:
        matrix: ``(n_rows, n_features)`` float matrix.
        seed: Deterministic model seed.

    Returns:
        A pair ``(scores, backend)`` where ``backend`` is ``"eif"``,
        ``"fallback"``, or ``"degenerate"`` (too few rows/features to score).
        EIF scores are the model's native anomaly score; fallback scores are
        batch-relative.
    """

    matrix = np.asarray(matrix, dtype=float)
    n_rows = matrix.shape[0]
    if n_rows == 0:
        return np.zeros(0), "degenerate"
    if matrix.shape[1] == 0 or n_rows < 3:
        return np.full(n_rows, DEGENERATE_ANOMALY_SCORE), "degenerate"

    scaled = _robust_standardize(matrix)
    raw = _extended_isolation_forest(scaled, seed=seed)
    if raw is not None:
        return np.clip(raw, 0.0, 1.0), "eif"
    return _minmax(_deviation_score(scaled)), "fallback"


def feature_deviations(
    matrix: np.ndarray,
    feature_names: list[str],
    rows: list[int],
    *,
    top_k: int = TOP_DEVIATION_FEATURES,
) -> list[list[dict[str, object]]]:
    """Explain rows by their strongest feature deviations from the batch baseline.

    An anomaly score alone tells a reviewer nothing actionable. This turns a
    high-scoring row into readable evidence: for each requested row, the
    ``top_k`` features whose values sit furthest from the batch baseline, in the
    **same robust (median / MAD) space the anomaly model scores in** — so the
    explanation describes exactly the deviations that drove the score.

    Args:
        matrix: ``(n_rows, n_features)`` float matrix, as scored by
            :func:`score_matrix` (e.g. ``FeatureSet.matrix``).
        feature_names: Column names aligned to the matrix.
        rows: Row indices to explain.
        top_k: Deviations to report per row.

    Returns:
        One list per requested row (same order), each holding up to ``top_k``
        dicts sorted by descending ``abs(robust_z)``:

        * ``feature`` — the feature name;
        * ``value`` — the row's raw feature value;
        * ``robust_z`` — signed distance from the batch median in MAD units;
        * ``batch_percentile`` — the value's rank within the batch in ``[0, 1]``
          (ties averaged), so ``>= 0.99`` reads as "in the top 1% of the batch"
          and ``<= 0.01`` as the bottom 1%.

        Rows explain to empty lists when the matrix has no features.
    """

    matrix = np.asarray(matrix, dtype=float)
    if not rows or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        return [[] for _ in rows]

    scaled = _robust_standardize(matrix)
    # Per-column percentile rank of every value (ties averaged), computed once.
    percentiles = rankdata(matrix, method="average", axis=0) / matrix.shape[0]

    out: list[list[dict[str, object]]] = []
    for row in rows:
        order = np.argsort(-np.abs(scaled[row]))[:top_k]
        out.append(
            [
                {
                    "feature": feature_names[col],
                    "value": float(matrix[row, col]),
                    "robust_z": float(scaled[row, col]),
                    "batch_percentile": float(percentiles[row, col]),
                }
                for col in order
            ]
        )
    return out


def _robust_standardize(matrix: np.ndarray) -> np.ndarray:
    """Standardise columns with median / MAD, robust to heavy tails.

    Falls back to the standard deviation, then to 1.0, for columns whose MAD is
    zero (constant or near-constant), so the result is always finite.
    """

    median = np.median(matrix, axis=0)
    mad = np.median(np.abs(matrix - median), axis=0)
    scale = _MAD_TO_STD * mad
    std = matrix.std(axis=0)
    scale = np.where(scale > 0.0, scale, std)
    scale = np.where(scale > 0.0, scale, 1.0)
    scaled = (matrix - median) / scale
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
        # Inputs are sanitised in _robust_standardize; failing loudly on a
        # NaN/inf that slips through beats silently imputing it.
        missing_action="fail",
        standardize_data=False,
        random_seed=seed,
        # Single-threaded keeps scoring bit-reproducible across runs and hosts.
        nthreads=1,
    )
    model.fit(scaled)
    return np.asarray(model.decision_function(scaled), dtype=float)


def _deviation_score(scaled: np.ndarray) -> np.ndarray:
    """Mean absolute robust-z deviation across features.

    A transparent but weaker stand-in for the isolation forest: it scores each
    row by how far its features sit from the batch norm on average. Unlike the
    forest it ignores feature interactions (e.g. same-context *and* same-instant),
    so it is a marginal detector, not an equivalent.
    """

    return np.abs(scaled).mean(axis=1)


def _minmax(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    minimum, maximum = float(values.min()), float(values.max())
    if maximum - minimum <= 0.0:
        return np.full(values.shape[0], DEGENERATE_ANOMALY_SCORE)
    scaled = (values - minimum) / (maximum - minimum)
    return np.clip(scaled, 0.0, 1.0)

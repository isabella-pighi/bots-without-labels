"""Measure detection against planted ground truth.

When bots are planted on purpose (by :mod:`synthetic` or :mod:`inject`), the
detector's output can be scored honestly: recall is the share of planted bots it
recovered, overall and per archetype. Precision here is measured only against the
*planted* set, so it is a lower bound — real traffic may contain genuine bots the
detector also (correctly) flags.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def evaluate_injection(
    predictions: Sequence[int] | np.ndarray,
    planted: Sequence[int] | np.ndarray,
    archetypes: Sequence[str | None] | None = None,
) -> dict[str, object]:
    """Score predictions against a planted-bot ground truth.

    Args:
        predictions: Per-row ``is_bot`` decisions (0/1), aligned to ``planted``.
        planted: Per-row ground truth (1 for a planted bot).
        archetypes: Optional per-row archetype names for a per-archetype
            breakdown (``None`` for legitimate rows).

    Returns:
        A dictionary with ``planted``, ``flagged``, ``recovered``, ``recall``,
        and ``planted_precision`` — the share of flagged rows that were planted
        bots. Note this is a *lower bound* on true precision: unplanted rows the
        detector flags count against it even when they are genuine bots in the
        background traffic. When ``archetypes`` is given, a ``per_archetype``
        map of ``planted``/``recovered``/``recall`` per archetype is added.
    """

    predicted = np.asarray(predictions).astype(bool)
    truth = np.asarray(planted).astype(bool)
    n_planted = int(truth.sum())
    flagged = int(predicted.sum())
    recovered = int((predicted & truth).sum())

    result: dict[str, object] = {
        "planted": n_planted,
        "flagged": flagged,
        "recovered": recovered,
        "recall": recovered / n_planted if n_planted else 0.0,
        "planted_precision": recovered / flagged if flagged else 0.0,
    }

    if archetypes is not None:
        names = [name for name in dict.fromkeys(archetypes) if name]
        per: dict[str, dict[str, object]] = {}
        archetype_array = np.array([str(name) for name in archetypes], dtype=object)
        for name in names:
            mask = archetype_array == name
            total = int(mask.sum())
            found = int((predicted & mask).sum())
            per[name] = {
                "planted": total,
                "recovered": found,
                "recall": found / total if total else 0.0,
            }
        result["per_archetype"] = per
    return result

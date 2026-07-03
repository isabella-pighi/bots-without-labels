"""Tests for label-injection evaluation."""

from __future__ import annotations

import pytest

from bots_without_labels.evaluate import evaluate_injection


@pytest.mark.parametrize(
    ("predictions", "planted", "archetypes", "expected"),
    [
        pytest.param(
            [1, 1, 1, 0, 1, 0, 0, 0],  # 3 of 4 planted found, 1 false positive
            [1, 1, 1, 1, 0, 0, 0, 0],
            None,
            {
                "planted": 4,
                "recovered": 3,
                "flagged": 4,
                "recall": 0.75,
                "planted_precision": 0.75,
            },
            id="overall-metrics",
        ),
        pytest.param(
            [1, 0, 1, 1],
            [1, 1, 1, 1],
            ["burst", "burst", "drip", "drip"],
            {
                "per_archetype": {
                    "burst": {"planted": 2, "recovered": 1, "recall": 0.5},
                    "drip": {"planted": 2, "recovered": 2, "recall": 1.0},
                }
            },
            id="per-archetype-breakdown",
        ),
        pytest.param(
            [0, 1, 0],
            [0, 0, 0],
            None,
            {"planted": 0, "recall": 0.0},
            id="no-planted-bots",
        ),
    ],
)
def test_evaluate_injection_reports(predictions, planted, archetypes, expected) -> None:
    report = evaluate_injection(predictions, planted, archetypes)
    for key, value in expected.items():
        assert report[key] == value, f"{key}: {report}"

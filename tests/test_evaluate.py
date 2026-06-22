"""Tests for label-injection evaluation."""

from __future__ import annotations

from bots_without_labels.evaluate import evaluate_injection


def test_overall_metrics() -> None:
    planted = [1, 1, 1, 1, 0, 0, 0, 0]
    predictions = [1, 1, 1, 0, 1, 0, 0, 0]  # 3 of 4 planted found, 1 false positive
    report = evaluate_injection(predictions, planted)
    assert report["planted"] == 4
    assert report["recovered"] == 3
    assert report["flagged"] == 4
    assert report["recall"] == 0.75
    assert report["planted_precision"] == 0.75


def test_per_archetype_breakdown() -> None:
    planted = [1, 1, 1, 1]
    predictions = [1, 0, 1, 1]
    archetypes = ["burst", "burst", "drip", "drip"]
    report = evaluate_injection(predictions, planted, archetypes)
    per = report["per_archetype"]
    assert per["burst"] == {"planted": 2, "recovered": 1, "recall": 0.5}
    assert per["drip"] == {"planted": 2, "recovered": 2, "recall": 1.0}


def test_no_planted_bots() -> None:
    report = evaluate_injection([0, 1, 0], [0, 0, 0])
    assert report["planted"] == 0
    assert report["recall"] == 0.0

"""Tests for synthetic log generation."""

from __future__ import annotations

import numpy as np

from bots_without_labels.synthetic import ARCHETYPES, generate


def test_shape_and_labels() -> None:
    log = generate(n_legit=300, n_bots=40, seed=0)
    assert list(log.frame.columns) == [
        "event_id",
        "event_time",
        "region",
        "browser",
        "os",
        "url",
    ]
    assert log.frame.shape[0] == 340
    assert int(log.is_bot.sum()) == 40
    assert len(log.archetype) == 340
    assert {a for a in log.archetype if a} == set(ARCHETYPES)


def test_event_ids_unique() -> None:
    log = generate(n_legit=200, n_bots=40, seed=1)
    assert log.frame["event_id"].is_unique


def test_deterministic() -> None:
    first = generate(n_legit=200, n_bots=40, seed=7)
    second = generate(n_legit=200, n_bots=40, seed=7)
    assert first.frame.equals(second.frame)
    assert np.array_equal(first.is_bot, second.is_bot)


def test_seeds_differ() -> None:
    first = generate(n_legit=200, n_bots=40, seed=1)
    second = generate(n_legit=200, n_bots=40, seed=2)
    assert not first.frame.equals(second.frame)

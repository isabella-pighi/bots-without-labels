"""Tests for generic label injection into an arbitrary log."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from bots_without_labels.evaluate import evaluate_injection
from bots_without_labels.ingest import load
from bots_without_labels.inject import inject_bots
from bots_without_labels.pipeline import detect
from bots_without_labels.synthetic import ARCHETYPES, DETECTABLE_ARCHETYPES


def _generic_log(path: Path) -> Path:
    """A non-click log (different schema) to prove genericity."""

    rng = np.random.default_rng(0)
    rows = ["uid,ts,channel,amount,note"]
    for i in range(600):
        rows.append(
            f"u{i},2022-02-0{1 + i % 9} {i % 24:02d}:{i % 60:02d}:00,"
            f"ch{rng.integers(0, 40)},{rng.integers(1, 500)},note text {i}"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_injection_appends_labelled_rows(tmp_path: Path) -> None:
    loaded = load(_generic_log(tmp_path / "g.csv"))
    base = loaded.frame.shape[0]
    result = inject_bots(loaded.frame, loaded.schema, n_bots=80, seed=1)
    assert result.frame.shape[0] == base + 80
    assert int(result.is_injected.sum()) == 80
    assert {a for a in result.archetype if a} == set(ARCHETYPES)
    # Original rows keep their place and are unlabelled.
    assert result.is_injected[:base].sum() == 0


def test_injected_bots_are_detected(tmp_path: Path) -> None:
    loaded = load(_generic_log(tmp_path / "g.csv"))
    result = inject_bots(loaded.frame, loaded.schema, n_bots=80, seed=1)
    detection = detect(result.frame, loaded.schema)
    report = evaluate_injection(detection.is_bot, result.is_injected, result.archetype)
    # The timing archetypes survive injection into an arbitrary schema: the burst
    # via its same-instant cluster, the mechanical cadence via per-run regularity
    # (which isolates the regular sub-sequence even when the bot's categorical
    # value collides with many scattered legitimate rows). The evasive archetypes
    # leave no such signature, so they stay low; whatever we flag is a planted bot.
    per = report["per_archetype"]
    for name in DETECTABLE_ARCHETYPES:
        assert per[name]["recall"] >= 0.85, f"{name} recall {per[name]['recall']:.2f}"
    assert report["planted_precision"] >= 0.9


def test_injection_is_deterministic(tmp_path: Path) -> None:
    loaded = load(_generic_log(tmp_path / "g.csv"))
    first = inject_bots(loaded.frame, loaded.schema, n_bots=40, seed=3)
    second = inject_bots(loaded.frame, loaded.schema, n_bots=40, seed=3)
    assert first.frame.equals(second.frame)

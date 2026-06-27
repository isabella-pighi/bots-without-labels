"""Unit guards for the single benchmark runner (no real data required).

These pin the runner's *contract* -- skip-if-absent, one table, no data
writes -- without downloading the gitignored captures. The measured numbers
themselves are guarded by ``tests/test_real_benchmark.py`` and
``tests/test_ctu13_benchmark.py``, which run the same ``run()`` entry points
this runner calls.

Every test here is hermetic: it owns the ``present``/``run`` behaviour via
temp paths or monkeypatching, so it never depends on what happens to sit in
the real ``data/`` directory (a developer or CI box may legitimately have the
raw shards present).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation import run_benchmarks, unsw_benchmark
from evaluation.run_benchmarks import _format_table, run_all


def _absent_shards(tmp_path: Path) -> tuple[Path, ...]:
    return tuple(tmp_path / f"UNSW-NB15_{i}.csv" for i in range(1, 5))


def test_unsw_present_shards_empty_for_absent_paths(tmp_path: Path) -> None:
    # Hermetic: point at a temp dir with no shards rather than asserting the
    # real workspace is clean.
    assert unsw_benchmark.present_shards(_absent_shards(tmp_path)) == []


def test_unsw_build_mix_raises_when_shards_absent(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        unsw_benchmark.build_mix(_absent_shards(tmp_path))


def test_unsw_main_skips_cleanly(monkeypatch) -> None:
    # Force the absent case regardless of what is in data/.
    monkeypatch.setattr(unsw_benchmark, "present_shards", lambda *a, **k: [])
    assert unsw_benchmark.main([]) == 0


def test_runner_skips_absent_benchmark_without_running(monkeypatch) -> None:
    # The runner's UNSW entry reports "present" via present_shards(); force it
    # absent so we exercise the skip path with no heavy run and no data file.
    monkeypatch.setattr(unsw_benchmark, "present_shards", lambda *a, **k: [])
    rows = run_all(keys=["unsw"])
    assert len(rows) == 1
    assert rows[0]["status"] == "skipped"
    assert "absent" in rows[0]["reason"]


def test_runner_runs_present_benchmark(monkeypatch) -> None:
    # Hermetic "ran" path: a fake benchmark that is present and returns canned
    # metrics, so run_all's ran branch is exercised with no real data.
    fake = run_benchmarks.Benchmark(
        key="fake",
        title="Fake benchmark",
        tier="tracked",
        present=lambda: True,
        absent_reason="n/a",
        run=lambda: {
            "n_rows": 10,
            "base_rate": 0.1,
            "flag_rate": 0.2,
            "recall": 1.0,
            "planted_precision": 0.5,
        },
        caveat="test only",
    )
    monkeypatch.setattr(run_benchmarks, "BENCHMARKS", (fake,))
    rows = run_all()
    assert len(rows) == 1
    assert rows[0]["status"] == "ran"
    assert rows[0]["report"]["recall"] == 1.0


def test_main_rejects_unknown_only_key(monkeypatch) -> None:
    # Unknown --only keys must fail loudly, not print an empty table at exit 0.
    monkeypatch.setattr(unsw_benchmark, "present_shards", lambda *a, **k: [])
    with pytest.raises(SystemExit) as exc:
        run_benchmarks.main(["--only", "typo"])
    assert exc.value.code != 0


def test_format_table_renders_ran_and_skipped_rows() -> None:
    ran = {
        "key": "demo",
        "title": "Demo benchmark",
        "tier": "tracked",
        "status": "ran",
        "report": {
            "n_rows": 1000,
            "base_rate": 0.03,
            "flag_rate": 0.04,
            "recall": 0.99,
            "planted_precision": 0.85,
        },
    }
    skipped = {
        "key": "gone",
        "title": "Absent benchmark",
        "tier": "secondary",
        "status": "skipped",
        "reason": "dataset absent",
    }
    table = _format_table([ran, skipped])
    assert "Demo benchmark" in table
    assert "0.990" in table  # recall rendered
    assert "0.850" in table  # precision rendered
    assert "skipped" in table  # absent row marked, not crashed


def test_every_benchmark_declares_tier_and_caveat() -> None:
    # Honest-framing guard: each benchmark must carry a tier and a caveat so
    # the table can never present an unframed number.
    for bench in run_benchmarks.BENCHMARKS:
        assert bench.tier in {"tracked", "secondary"}
        assert bench.caveat.strip()

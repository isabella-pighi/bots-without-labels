"""Fine-resolution real-data benchmark guard (CTU-13 scenario 1, Neris).

The CTU-13 binetflow is gitignored and large, so this test is *skipped* unless
the flow file is present locally (download instructions in
:mod:`evaluation.ctu13_bot_benchmark`).

What it guards is the benchmark's *premise and plumbing*, not a detection target.
Unlike the CICIDS guard -- which pins recall/precision wins -- the documented,
honest finding here is that sub-second timestamp resolution *alone* does not make
the method recover on this different traffic population: on the Neris mix the
detector over-flags the diverse NetFlow background and misses the bot (observed
at the pinned config: flag rate ~0.76, recall ~0.11, precision ~0.005). We
therefore do NOT assert detection quality (that would lock in a known method
limit as if it were a goal). We DO assert the things the benchmark exists to
establish and rely on:

* the mix is the intended rare-attack shape (~3% base rate), and
* the timestamps are genuinely sub-second, so the dense-timing rules stay ACTIVE
  (``dense_timing_gated`` is False) -- the exact opposite of the minute-quantised
  CICIDS case. This is the data-limit-vs-method-limit contrast the benchmark was
  built to make.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.ctu13_bot_benchmark import DEFAULT_BINETFLOW, run

pytestmark = pytest.mark.skipif(
    not Path(DEFAULT_BINETFLOW).exists(),
    reason=(
        f"CTU-13 binetflow {DEFAULT_BINETFLOW} not present "
        "(download locally to run; see evaluation.ctu13_bot_benchmark)"
    ),
)


def test_ctu13_mix_is_fine_resolution_rare_attack() -> None:
    report = run()

    # The intended rare-attack mix shape.
    assert report["n_rows"] == 62_000, report
    assert 0.02 <= report["base_rate"] <= 0.05, report

    # The premise: CTU-13 timestamps are sub-second, so the dense-timing rules are
    # NOT gated off as a coarse-grid artifact (contrast CICIDS, grid 60s, gated).
    grid = report["timestamp_grid_seconds"]
    assert grid is not None, report
    assert grid < 1.0, report  # sub-second; CICIDS is 60.0
    assert report["dense_timing_gated"] is False, report

    # Metrics are well-formed (no assertion on their level -- see module docstring).
    for key in ("recall", "planted_precision", "flag_rate"):
        assert 0.0 <= report[key] <= 1.0, report

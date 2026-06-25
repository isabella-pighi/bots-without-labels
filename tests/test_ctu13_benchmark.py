"""Fine-resolution real-data benchmark guard (CTU-13 scenario 1, Neris).

The CTU-13 binetflow is gitignored and large, so this test is *skipped* unless
the flow file is present locally (download instructions in
:mod:`evaluation.ctu13_bot_benchmark`).

What it guards now has two parts.

The original finding stands: sub-second timestamp resolution *alone* did not make
the method recover -- the diverse Neris bot (spam + C2 + click fraud) connects to
many destinations, so it reads as *high* diversity and the monotony/concentration
rules missed it (recall ~0.11). The actor-graph rule (``asymmetric_degree``)
closes that gap: a value that connects to an unusually large number of distinct
counterparts in one role while few connect to it in the other, on a monotone
service, is the one-sided star this bot draws. With it the bot is fully recovered,
so we now pin the **recall** win.

We still do NOT assert overall precision. On this capture it stays low because a
*separate*, pre-existing rule (``entity_monotony`` firing on the degenerate
``Proto``/``State`` "entities") over-flags the NetFlow background. A per-rule
diagnostic (measured on this constructed split) shows ``asymmetric_degree`` fires
on all recovered positives with zero false fires (1.0 fire-precision) and uniquely
carries 1,774 of the 2,000 positives -- the other 226 also have other evidence.
Fixing that other rule is tracked separately, so pinning overall precision here
would lock in an unrelated limit.

So this guards:

* the mix is the intended rare-attack shape (~3% base rate);
* the timestamps are genuinely sub-second, so the dense-timing rules stay ACTIVE
  (``dense_timing_gated`` is False) -- the opposite of the minute-quantised CICIDS
  case; and
* the actor-graph rule recovers the diverse directional bot (recall >= 0.95).
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

    # The actor-graph rule recovers the diverse directional bot. We pin recall
    # (the win) but not overall precision -- a separate rule's over-flagging caps
    # it on this capture; see the module docstring.
    assert report["recall"] >= 0.95, report
    for key in ("recall", "planted_precision", "flag_rate"):
        assert 0.0 <= report[key] <= 1.0, report

"""Real-data benchmark regression guard (CICIDS2017 botnet).

The bulk dataset is gitignored and large, so this test is *skipped* unless the
archive is present locally. When it is, it pins two stacked real-data wins:

* per-entity baselining recovered the botnet at all (recall 0.022 -> 0.998);
* the relational fan-in / hub discriminator then lifted precision from 0.144 to
  ~0.44 (and roughly halved the flag rate) by escalating a monotonous entity
  only when it is a hub -- a destination/source converging with many distinct
  counterparts -- not a single point-to-point channel.

A future change that silently reintroduces the real-data blind spot fails here
even though the synthetic suite stays green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.cicids_bot_benchmark import DEFAULT_ZIP, run

pytestmark = pytest.mark.skipif(
    not Path(DEFAULT_ZIP).exists(),
    reason=f"benchmark archive {DEFAULT_ZIP} not present (download locally to run)",
)


def test_cicids_botnet_recovered() -> None:
    report = run(n_benign=60_000)
    # Pre-baselining: recall 0.022 / precision 0.018. Post-baselining: recall
    # 0.998 / precision 0.144. With the hub discriminator: recall 0.998 /
    # precision ~0.44 / flag rate ~0.07. The bounds below sit comfortably under
    # the observed values so normal sampling jitter does not flake the guard.
    assert report["recall"] >= 0.95, report
    assert report["planted_precision"] >= 0.35, report
    assert report["planted_precision"] > report["base_rate"], report
    assert report["flag_rate"] <= 0.12, report

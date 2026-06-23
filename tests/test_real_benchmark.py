"""Real-data benchmark regression guard (CICIDS2017 botnet).

The bulk dataset is gitignored and large, so this test is *skipped* unless the
archive is present locally. When it is, it pins the per-entity-baselining win:
the detector must recover almost all of an independent, externally-labelled
botnet at a precision far above the pre-fix baseline (recall 0.022, precision
0.018), so a future change that silently reintroduces the real-data blind spot
fails here even though the synthetic suite stays green.
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
    # The pre-fix detector scored recall 0.022 / precision 0.018 here.
    assert report["recall"] >= 0.90, report
    assert report["planted_precision"] >= 0.08, report
    assert report["planted_precision"] > report["base_rate"], report

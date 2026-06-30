"""Guards for the Bournemouth web-log domain-transfer benchmark.

The 32 MB dataset zip is gitignored and an opt-in local fetch, so the run guard
skips unless it is present. The parse/mapping guard needs no data and always runs:
it pins the honest label/entity/timestamp mapping the benchmark depends on.

This is a NEGATIVE domain-transfer result (the NetFlow-tuned detector transfers
poorly to web logs), so the run guard pins the rare-attack *shape* and valid metric
ranges -- NOT a recall/precision floor.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.bournemouth_benchmark import DEFAULT_ZIP, main, parse_line, run

_BOT_LINE = (
    '- - [01/Nov/2019:10:47:35 +0000] "GET /js/x.js HTTP/1.1" 200 826 '
    '"http://160.40.52.164/" 97hf7ciplt2k54f5j6109nekn0 '
    '"Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:70.0) Firefox/70.0"'
)
_LANDING_LINE = '- - [01/Nov/2019:10:43:18 +0000] "GET / HTTP/1.0" 200 2045 "-" - "-"'


def test_parse_line_maps_label_entity_timestamp_fields() -> None:
    rec = parse_line(_BOT_LINE)
    assert rec is not None
    # Actor entity, timestamp, and behavioural fields are mapped from the log line.
    assert rec["session_id"] == "97hf7ciplt2k54f5j6109nekn0"
    assert rec["timestamp"] == "01/Nov/2019:10:47:35 +0000"
    assert rec["method"] == "GET"
    assert rec["path"] == "/js/x.js"
    assert rec["status"] == "200"
    assert rec["user_agent"].startswith("Mozilla/5.0")


def test_parse_line_drops_unsessioned_and_malformed() -> None:
    # The unsessioned landing request (session '-') is dropped, not collapsed into
    # one degenerate '-' entity.
    assert parse_line(_LANDING_LINE) is None
    assert parse_line("not a valid access log line") is None
    assert parse_line("") is None


def test_main_skips_when_zip_absent(tmp_path: Path) -> None:
    # Skip-if-absent: a missing zip exits 0 with a skip message, never raises.
    assert main(["--zip", str(tmp_path / "missing.zip")]) == 0


@pytest.mark.skipif(
    not Path(DEFAULT_ZIP).exists(),
    reason=f"Bournemouth zip {DEFAULT_ZIP} not present (opt-in local fetch)",
)
def test_bournemouth_rare_attack_shape() -> None:
    report = run()
    # The intended rare-attack mix shape (all humans + a small bot-session sample).
    assert report["n_rows"] > 10_000, report
    assert 0.02 <= report["base_rate"] <= 0.05, report
    # Honest negative transfer: pin valid ranges only, not a quality floor.
    for key in ("recall", "planted_precision", "flag_rate"):
        assert 0.0 <= report[key] <= 1.0, report

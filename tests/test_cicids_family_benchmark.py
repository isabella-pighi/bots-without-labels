"""Guards for the CICIDS2017 attack-family benchmark wrappers.

Everything except the last test is hermetic: registration in the unified
runner, skip-if-absent behaviour, and the mix-construction policy (label
held out, unlabelled trailer rows dropped, slice cap respected) are pinned
against a tiny fake archive, so no gitignored data is required. The one
data-backed smoke test builds a real mix (no detection run) and skips when
the archive is absent — like every real-data guard in this suite, it proves
nothing on machines without the zip.

No quality floor is pinned here: these families are secondary
attack-coverage probes (attacks, not bots), same policy as UNSW.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from evaluation import cicids_family_benchmark, run_benchmarks
from evaluation.cicids_family_benchmark import (
    DEFAULT_ZIP,
    FAMILIES,
    LABEL_COLUMN,
    build_mix,
    family,
)

FAMILY_KEYS = tuple(spec.key for spec in FAMILIES)


def _fake_zip(tmp_path: Path, member: str, csv_text: str) -> Path:
    path = tmp_path / "fake_flows.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, csv_text)
    return path


def test_family_lookup_rejects_unknown_key() -> None:
    with pytest.raises(KeyError, match="valid:"):
        family("typo")


def test_build_mix_raises_when_zip_absent(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_mix("cicids_portscan", tmp_path / "missing.zip")


def test_main_skips_cleanly_when_zip_absent(tmp_path: Path) -> None:
    # Force the absent case regardless of what is in data/.
    assert cicids_family_benchmark.main(["--zip", str(tmp_path / "missing.zip")]) == 0


def test_all_family_keys_registered_as_secondary() -> None:
    registered = {b.key: b for b in run_benchmarks.BENCHMARKS}
    for spec in FAMILIES:
        assert spec.key in registered, spec.key
        bench = registered[spec.key]
        assert bench.tier == "secondary"
        # Honest-framing guard: the caveat must carry the not-a-bot-result
        # framing, or the unified table would print an unframed number.
        assert "NOT a botnet" in bench.caveat


def test_runner_skips_family_rows_when_zip_absent(monkeypatch, tmp_path) -> None:
    # The registry's present() defers to the module attribute at call time,
    # so patching DEFAULT_ZIP is enough to force the skip path hermetically.
    monkeypatch.setattr(
        cicids_family_benchmark, "DEFAULT_ZIP", tmp_path / "missing.zip"
    )
    rows = run_benchmarks.run_all(keys=list(FAMILY_KEYS))
    assert len(rows) == len(FAMILY_KEYS)
    assert all(row["status"] == "skipped" for row in rows)
    assert all("absent" in row["reason"] for row in rows)


def test_build_mix_holds_out_label_and_drops_non_labels(tmp_path: Path) -> None:
    # Mimics the upstream quirks: space-padded header, an unlabelled trailer
    # row ("nan" after astype(str)) and a header-echo row, neither of which
    # may be counted as an attack (they are not BENIGN either).
    spec = family("cicids_portscan")
    rows = ["Flow ID, Source IP, Timestamp, Flow Duration, Label"]
    for i in range(8):
        rows.append(f"f{i},10.0.0.{i},7/7/2017 1:{i:02d},100,BENIGN")
    for i in range(3):
        rows.append(f"a{i},10.9.9.9,7/7/2017 2:{i:02d},5,PortScan")
    rows.append("t0,10.0.0.99,7/7/2017 3:00,100,")  # unlabelled trailer
    rows.append("Flow ID, Source IP, Timestamp, Flow Duration, Label")  # echo
    path = _fake_zip(tmp_path, spec.member, "\n".join(rows))

    frame, truth = build_mix("cicids_portscan", path, n_benign=8, seed=7)

    assert LABEL_COLUMN not in frame.columns
    assert len(frame) == len(truth) == 11  # 8 benign + 3 attacks, junk dropped
    assert truth.sum() == 3
    assert truth.min() >= 0 and truth.max() == 1


def test_build_mix_respects_contiguous_slice_cap(tmp_path: Path) -> None:
    spec = family("cicids_portscan")
    rows = ["Flow ID, Source IP, Timestamp, Flow Duration, Label"]
    for i in range(5):
        rows.append(f"f{i},10.0.0.{i},7/7/2017 1:{i:02d},100,BENIGN")
    for i in range(6):
        rows.append(f"a{i},10.9.9.9,7/7/2017 2:{i:02d},5,PortScan")
    path = _fake_zip(tmp_path, spec.member, "\n".join(rows))

    _, truth = build_mix("cicids_portscan", path, n_attack=2, n_benign=5, seed=7)
    assert truth.sum() == 2


@pytest.mark.skipif(
    not DEFAULT_ZIP.exists(),
    reason=f"benchmark archive {DEFAULT_ZIP} not present (download locally to run)",
)
def test_webattacks_real_mix_follows_convention() -> None:
    # The ugliest source file (0x96 label bytes + ~289k unlabelled trailer
    # rows): build the real mix — no detection run — and pin the conventions.
    frame, truth = build_mix("cicids_webattacks")
    assert LABEL_COLUMN not in frame.columns
    assert truth.sum() == 2_180  # all three web-attack sub-families kept
    assert len(truth) == 62_180  # 60k benign + the intact attack set
    base_rate = truth.mean()
    assert 0.02 <= base_rate <= 0.05, base_rate

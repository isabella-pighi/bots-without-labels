"""Real-data benchmark: CICIDS2017 botnet detection.

The synthetic suite proves the detector recovers what it plants, but it shares
the detector's own assumptions, so a green synthetic run does not mean the method
works on real traffic. This benchmark measures detection against an *independent*
labelled dataset: the CICIDS2017 Friday-morning capture, whose ~1% botnet (Ares)
flows are real, externally labelled, and structurally typical (a host beaconing
to one C2).

It builds a realistic *rare-attack* mix (mostly benign + the intact, temporally
dense bot flows), runs the full pipeline, and reports recall/precision against
the held-out ``Label`` column. The bulk archive is gitignored, so this is a
local/manual benchmark; :mod:`tests.test_real_benchmark` skips when it is absent.

Run:
    uv run --extra eif python -m evaluation.cicids_bot_benchmark \
        --zip data/GeneratedLabelledFlows.zip
"""

from __future__ import annotations

import argparse
import io
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from bots_without_labels.evaluate import evaluate_injection
from bots_without_labels.ingest import load
from bots_without_labels.pipeline import detect

BOT_FILE = "TrafficLabelling /Friday-WorkingHours-Morning.pcap_ISCX.csv"
DEFAULT_ZIP = Path("data/GeneratedLabelledFlows.zip")
N_BENIGN = 60_000
SEED = 7


def build_mix(zip_path: Path, *, n_benign: int = N_BENIGN, seed: int = SEED):
    """Return a (frame-without-label, truth-array) rare-attack mix from the zip.

    All bot rows are kept (preserving the beacon cadence); benign rows are
    sampled down so the attack is a realistic small minority.
    """

    with zipfile.ZipFile(zip_path) as archive:
        raw = archive.read(BOT_FILE)
    df = pd.read_csv(
        io.BytesIO(raw), encoding="latin-1", low_memory=False, skipinitialspace=True
    )
    df.columns = [c.strip() for c in df.columns]
    df["Label"] = df["Label"].astype(str).str.strip()

    bot = df[df["Label"] == "Bot"]
    benign = df[df["Label"] == "BENIGN"].sample(n=n_benign, random_state=seed)
    mix = pd.concat([benign, bot])
    mix["_ts"] = pd.to_datetime(mix["Timestamp"], errors="coerce")
    mix = mix.sort_values("_ts").drop(columns=["_ts"]).reset_index(drop=True)

    truth = (mix["Label"] != "BENIGN").to_numpy().astype(int)
    frame = mix.drop(columns=["Label"])
    return frame, truth


def run(zip_path: Path = DEFAULT_ZIP, *, n_benign: int = N_BENIGN, seed: int = SEED):
    """Build the mix, run detection through the real loader, return metrics."""

    frame, truth = build_mix(zip_path, n_benign=n_benign, seed=seed)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cicids_bot_mix.csv"
        frame.to_csv(path, index=False)
        loaded = load(path)
    result = detect(loaded.frame, loaded.schema)
    report = evaluate_injection(result.is_bot, truth)
    report["flag_rate"] = float(np.mean(result.is_bot))
    report["base_rate"] = float(np.mean(truth))
    report["n_rows"] = int(len(truth))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cicids_bot_benchmark")
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--benign", type=int, default=N_BENIGN)
    args = parser.parse_args(argv)

    report = run(args.zip, n_benign=args.benign)
    print("CICIDS2017 botnet benchmark")
    print(f"  rows         {report['n_rows']:>8d}")
    print(f"  base rate    {report['base_rate']:>8.3f}")
    print(f"  flag rate    {report['flag_rate']:>8.3f}")
    print(f"  recall       {report['recall']:>8.3f}")
    print(f"  precision    {report['planted_precision']:>8.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

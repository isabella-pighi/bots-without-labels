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
import zipfile
from pathlib import Path

import pandas as pd

from evaluation.harness import (
    DEFAULT_SEED,
    add_mix_size_arguments,
    format_report,
    score_mix,
)

# Path of the labelled Friday-morning capture inside the archive. The leading
# space in "TrafficLabelling " is IN the upstream zip, not a typo here.
BOT_FILE = "TrafficLabelling /Friday-WorkingHours-Morning.pcap_ISCX.csv"
DEFAULT_ZIP = Path("data/GeneratedLabelledFlows.zip")
LABEL_COLUMN = "Label"
TIME_COLUMN = "Timestamp"
POSITIVE_LABEL = "Bot"
NEGATIVE_LABEL = "BENIGN"
# Benign sample sized for a ~3% rare-attack base rate against the ~2k bot flows.
N_BENIGN = 60_000
SEED = DEFAULT_SEED


def build_mix(zip_path: Path, *, n_benign: int = N_BENIGN, seed: int = SEED):
    """Return a (frame-without-label, truth-array) rare-attack mix from the zip.

    All bot rows are kept (preserving the beacon cadence); benign rows are
    sampled down so the attack is a realistic small minority.
    """

    with zipfile.ZipFile(zip_path) as archive:
        raw = archive.read(BOT_FILE)
    # latin-1 + skipinitialspace: the upstream export carries stray high bytes
    # and space-padded headers.
    df = pd.read_csv(
        io.BytesIO(raw), encoding="latin-1", low_memory=False, skipinitialspace=True
    )
    df.columns = [c.strip() for c in df.columns]
    df[LABEL_COLUMN] = df[LABEL_COLUMN].astype(str).str.strip()

    bot = df[df[LABEL_COLUMN] == POSITIVE_LABEL]
    benign = df[df[LABEL_COLUMN] == NEGATIVE_LABEL].sample(
        n=n_benign, random_state=seed
    )
    mix = pd.concat([benign, bot])
    mix["_ts"] = pd.to_datetime(mix[TIME_COLUMN], errors="coerce")
    mix = mix.sort_values("_ts").drop(columns=["_ts"]).reset_index(drop=True)

    truth = (mix[LABEL_COLUMN] != NEGATIVE_LABEL).to_numpy().astype(int)
    frame = mix.drop(columns=[LABEL_COLUMN])
    return frame, truth


def run(zip_path: Path = DEFAULT_ZIP, *, n_benign: int = N_BENIGN, seed: int = SEED):
    """Build the mix, run detection through the real loader, return metrics."""

    frame, truth = build_mix(zip_path, n_benign=n_benign, seed=seed)
    _, report = score_mix(frame, truth, mix_name="cicids_bot_mix")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cicids_bot_benchmark")
    parser.add_argument(
        "--zip",
        type=Path,
        default=DEFAULT_ZIP,
        help="path to the GeneratedLabelledFlows.zip archive",
    )
    add_mix_size_arguments(parser, benign_default=N_BENIGN, seed_default=SEED)
    args = parser.parse_args(argv)

    report = run(args.zip, n_benign=args.benign, seed=args.seed)
    print(format_report("CICIDS2017 botnet benchmark", report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

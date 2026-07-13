"""Secondary real-data benchmarks: CICIDS2017 attack-family coverage probes.

The tracked CICIDS2017 benchmark (:mod:`evaluation.cicids_bot_benchmark`)
measures the Friday-morning botnet (Ares) — the one CICIDS family that is
actually a bot. This module covers the REMAINING labelled attack families in
the same archive (port scanning, DDoS, web attacks, infiltration, brute force,
DoS). Read every number here as a **secondary attack-coverage probe**: these
are attacks, not botnets, and most are not the automated who-talks-to-whom
traffic the detector is built for. A low recall on a family is a measurement
of coverage, not a bot-detection regression; none of these rows is a
bot-detection result.

Mix convention (shared with the sibling benchmarks): a rare-attack mix of
~60k sampled benign flows plus a small intact attack minority (~3% base
rate, ~62k rows, fixed seed). Large families are cut to a contiguous,
time-ordered ``N_ATTACK`` slice so the attack's cadence is preserved;
families smaller than the slice are kept whole. One documented deviation:
**Infiltration has only 36 labelled flows in the archive**, so the ~3%
convention is impossible — the probe keeps all 36 over the standard benign
background (base rate ~0.0006) and its numbers are qualitative signal only.

Source quirks handled here (all in the upstream export, not introduced):
column names are space-padded; the Thursday-morning WebAttacks file carries
~289k trailing rows with empty labels (dropped — they are not labelled
flows); the "Web Attack" labels contain a raw ``0x96`` en-dash byte (why
positives are selected as *not BENIGN* rather than by exact label string);
timestamps are minute-quantised and written without an AM/PM marker, so
afternoon hours parse as early morning — consistent within a file, but it
affects which window a contiguous slice lands on (see each family's note).

The bulk archive is gitignored, so these are local/manual benchmarks;
:mod:`tests.test_cicids_family_benchmark` skips its data-backed guard when
the archive is absent.

Run one family (or all present families via the unified runner):
    uv run --extra eif python -m evaluation.cicids_family_benchmark \
        --family cicids_portscan
    uv run --extra eif python -m evaluation.run_benchmarks --only cicids_portscan
"""

from __future__ import annotations

import argparse
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from evaluation.harness import (
    DEFAULT_SEED,
    add_mix_size_arguments,
    format_report,
    score_mix,
)

DEFAULT_ZIP = Path("data/GeneratedLabelledFlows.zip")
LABEL_COLUMN = "Label"
TIME_COLUMN = "Timestamp"
NEGATIVE_LABEL = "BENIGN"
# String values that are not real flow labels: a header echo reads as the
# column name itself, and (on pandas versions whose astype(str) stringifies
# missing values) an empty label reads as "nan". Genuinely-missing labels are
# dropped separately with notna() -- current pandas keeps them NaN.
NON_LABELS = ("nan", "", LABEL_COLUMN)
# Contiguous attack slice size and benign background, sized for the shared
# ~3% rare-attack convention (2_000 / 62_000 ≈ 0.032).
N_ATTACK = 2_000
N_BENIGN = 60_000
SEED = DEFAULT_SEED


@dataclass(frozen=True)
class FamilySpec:
    """One CICIDS attack family: where its flows live and how to frame them."""

    key: str
    member: str  # CSV path inside the archive (upstream dir name has a space)
    title: str
    positive_labels: str  # provenance note: the labels counted as positive
    n_attack: int | None  # contiguous slice size; None keeps every positive row
    note: str  # honest-framing caveat carried into every report


FAMILIES: tuple[FamilySpec, ...] = (
    FamilySpec(
        key="cicids_portscan",
        member="TrafficLabelling /Friday-WorkingHours-Afternoon-PortScan.pcap_ISCX.csv",
        title="CICIDS2017 PortScan (probe)",
        positive_labels="PortScan (158,930 in file)",
        n_attack=N_ATTACK,
        note=(
            "secondary CICIDS attack-coverage probe, NOT a botnet or "
            "bot-detection result: one scanner sweeping one victim's ports "
            "(point-to-point on IPs, fan-out only in ports); contiguous 2k "
            "slice; minute-quantised timestamps."
        ),
    ),
    FamilySpec(
        key="cicids_ddos",
        member="TrafficLabelling /Friday-WorkingHours-Afternoon-DDos.pcap_ISCX.csv",
        title="CICIDS2017 DDoS (probe)",
        positive_labels="DDoS (128,027 in file)",
        n_attack=N_ATTACK,
        note=(
            "secondary CICIDS attack-coverage probe, NOT a botnet or "
            "bot-detection result: LOIC flood converging on one victim "
            "(fan-in shaped); contiguous 2k slice; minute-quantised "
            "timestamps."
        ),
    ),
    FamilySpec(
        key="cicids_webattacks",
        member=(
            "TrafficLabelling /Thursday-WorkingHours-Morning-WebAttacks"
            ".pcap_ISCX.csv"
        ),
        title="CICIDS2017 WebAttacks (probe)",
        positive_labels=(
            "Web Attack brute force / XSS / SQL injection "
            "(1,507 / 652 / 21 in file; raw 0x96 en-dash in the labels)"
        ),
        n_attack=None,  # 2,180 total: kept whole so all three sub-attacks stay in
        note=(
            "secondary CICIDS attack-coverage probe, NOT a botnet or "
            "bot-detection result: low-volume human-paced web attacks "
            "(brute force + XSS + SQLi, all 2,180 rows kept); ~289k "
            "unlabelled trailer rows in the source file are dropped."
        ),
    ),
    FamilySpec(
        key="cicids_infiltration",
        member=(
            "TrafficLabelling /Thursday-WorkingHours-Afternoon-Infilteration"
            ".pcap_ISCX.csv"
        ),
        title="CICIDS2017 Infiltration (probe)",
        positive_labels="Infiltration (36 in file)",
        n_attack=None,  # far below the slice size: keep every labelled flow
        note=(
            "secondary CICIDS attack-coverage probe, NOT a botnet or "
            "bot-detection result: only 36 labelled flows exist, so the ~3% "
            "mix convention is impossible — base rate ~0.0006 over the "
            "standard 60k benign background; qualitative signal only, the "
            "digits are not statistically robust."
        ),
    ),
    FamilySpec(
        key="cicids_bruteforce",
        member="TrafficLabelling /Tuesday-WorkingHours.pcap_ISCX.csv",
        title="CICIDS2017 BruteForce (probe)",
        positive_labels="FTP-Patator / SSH-Patator (7,938 / 5,897 in file)",
        n_attack=N_ATTACK,
        note=(
            "secondary CICIDS attack-coverage probe, NOT a botnet or "
            "bot-detection result: credential brute force onto one victim; "
            "the AM/PM-less timestamps parse the afternoon burst first, so "
            "the contiguous 2k slice is entirely SSH-Patator (a ~21-minute "
            "single-channel burst), with FTP-Patator uncovered."
        ),
    ),
    FamilySpec(
        key="cicids_dos",
        member="TrafficLabelling /Wednesday-workingHours.pcap_ISCX.csv",
        title="CICIDS2017 DoS (probe)",
        positive_labels=(
            "DoS Hulk / GoldenEye / slowloris / Slowhttptest / Heartbleed "
            "(231,073 / 10,293 / 5,796 / 5,499 / 11 in file)"
        ),
        n_attack=N_ATTACK,
        note=(
            "secondary CICIDS attack-coverage probe, NOT a botnet or "
            "bot-detection result: single-source DoS onto one victim; the "
            "AM/PM-less timestamps parse afternoon-first, so the contiguous "
            "2k slice is DoS slowloris (1,989) plus Heartbleed (11), not a "
            "proportional sample of the five sub-attacks (Hulk/GoldenEye/"
            "Slowhttptest uncovered)."
        ),
    ),
)


def family(key: str) -> FamilySpec:
    """Return the :class:`FamilySpec` for ``key`` (raising on unknown keys)."""

    for spec in FAMILIES:
        if spec.key == key:
            return spec
    valid = ", ".join(spec.key for spec in FAMILIES)
    raise KeyError(f"unknown CICIDS family key {key!r}; valid: {valid}")


def build_mix(
    key: str,
    zip_path: Path = DEFAULT_ZIP,
    *,
    n_attack: int | None = None,
    n_benign: int = N_BENIGN,
    seed: int = SEED,
):
    """Return a (frame-without-label, truth-array) rare-attack mix for a family.

    Positives are every labelled non-benign flow in the family's source file
    (robust to the raw ``0x96`` bytes in the web-attack labels); unlabelled
    trailer rows are dropped. Large families are cut to a contiguous,
    time-ordered slice so the attack cadence is preserved; benign rows are
    sampled down so the attack is a small minority.

    Args:
        key: A :data:`FAMILIES` key.
        zip_path: The GeneratedLabelledFlows.zip archive.
        n_attack: Contiguous attack-slice size; ``None`` uses the family's
            spec default (which may itself be ``None`` = keep every positive).
        n_benign: Benign sample size (capped at what the file holds).
        seed: Sampling seed.
    """

    spec = family(key)
    if n_attack is None:
        n_attack = spec.n_attack

    with zipfile.ZipFile(zip_path) as archive:
        raw = archive.read(spec.member)
    # latin-1 + skipinitialspace: the upstream export carries stray high bytes
    # and space-padded headers (same handling as cicids_bot_benchmark).
    df = pd.read_csv(
        io.BytesIO(raw), encoding="latin-1", low_memory=False, skipinitialspace=True
    )
    df.columns = [c.strip() for c in df.columns]
    df[LABEL_COLUMN] = df[LABEL_COLUMN].astype(str).str.strip()
    df = df[df[LABEL_COLUMN].notna() & ~df[LABEL_COLUMN].isin(NON_LABELS)]

    attack = df[df[LABEL_COLUMN] != NEGATIVE_LABEL].copy()
    benign_pool = df[df[LABEL_COLUMN] == NEGATIVE_LABEL]

    attack["_ts"] = pd.to_datetime(attack[TIME_COLUMN], errors="coerce")
    attack = attack.sort_values("_ts").drop(columns=["_ts"])
    if n_attack is not None:
        attack = attack.head(n_attack)

    take = min(n_benign, len(benign_pool))
    benign = benign_pool.sample(n=take, random_state=seed)

    mix = pd.concat([benign, attack])
    mix["_ts"] = pd.to_datetime(mix[TIME_COLUMN], errors="coerce")
    mix = mix.sort_values("_ts").drop(columns=["_ts"]).reset_index(drop=True)

    truth = (mix[LABEL_COLUMN] != NEGATIVE_LABEL).to_numpy().astype(int)
    frame = mix.drop(columns=[LABEL_COLUMN])
    return frame, truth


def run(
    key: str,
    zip_path: Path = DEFAULT_ZIP,
    *,
    n_attack: int | None = None,
    n_benign: int = N_BENIGN,
    seed: int = SEED,
):
    """Build one family's mix, run detection through the real loader, return metrics."""

    frame, truth = build_mix(
        key, zip_path, n_attack=n_attack, n_benign=n_benign, seed=seed
    )
    _, report = score_mix(frame, truth, mix_name=f"{key}_mix")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cicids_family_benchmark")
    parser.add_argument(
        "--zip",
        type=Path,
        default=DEFAULT_ZIP,
        help="path to the GeneratedLabelledFlows.zip archive",
    )
    parser.add_argument(
        "--family",
        type=str,
        default=None,
        choices=[spec.key for spec in FAMILIES],
        help="family key to run (default: every family)",
    )
    parser.add_argument(
        "--attack",
        type=int,
        default=None,
        help="attack flows to slice (contiguous, cadence-preserving); "
        "default: the family's own slice policy (large families cut to "
        f"{N_ATTACK}, small ones kept whole)",
    )
    add_mix_size_arguments(parser, benign_default=N_BENIGN, seed_default=SEED)
    args = parser.parse_args(argv)

    if not args.zip.exists():
        print(f"CICIDS family benchmarks: skipped (archive {args.zip} absent)")
        print("  download GeneratedLabelledFlows.zip locally to run")
        return 0

    selected = [family(args.family)] if args.family else list(FAMILIES)
    for spec in selected:
        report = run(
            spec.key,
            args.zip,
            n_attack=args.attack,
            n_benign=args.benign,
            seed=args.seed,
        )
        print(format_report(spec.title, report, notes=(spec.note,)))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

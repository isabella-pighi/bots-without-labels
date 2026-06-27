"""Secondary real-data benchmark wrapper: UNSW-NB15 (skip-if-absent).

This is a *best-effort secondary* benchmark, deliberately weaker than the two
tracked botnet captures (:mod:`evaluation.cicids_bot_benchmark`,
:mod:`evaluation.ctu13_bot_benchmark`). Read its numbers, if you run it, as a
breadth check -- **not** as a tracked bot-detection result. Two honest caveats:

* **UNSW-NB15 is a broad IDS dataset, not a botnet capture.** Its positive
  class (``Label == 1``) mixes nine attack families -- fuzzers, exploits, DoS,
  recon, shellcode, worms, backdoors, analysis, generic -- most of which are
  *not* the automated who-talks-to-whom traffic the actor-graph / monotony
  rules are built for. A low recall here is expected and is not evidence the
  method regressed on bots; a high flag rate is expected because the attack
  share is large.
* **Only the raw flow CSVs carry the fields we need.** The detector keys on
  stable actor endpoints and real timestamps, so this wrapper requires the
  *raw* exports ``UNSW-NB15_1.csv`` .. ``UNSW-NB15_4.csv`` (headerless, 49
  columns) which carry ``srcip`` / ``dstip`` / ``Stime`` / ``Label``. The
  stripped HuggingFace / "UNSW_NB15_training-set" feature mirrors **cannot**
  be used: they drop the IP endpoint columns and the absolute timestamp,
  leaving nothing for the actor graph or the timing rules to read.

Sourcing (public, no-auth attempt only):
    The raw four-CSV export lives behind the UNSW research data portal, which
    in practice gates the direct links behind a registration/agreement step.
    There is no reliable public no-auth direct download, so this wrapper ships
    dormant and *skips cleanly* when the files are absent. If you have
    legitimate access, drop the raw shards here and re-run:

        # one or more of the raw shards (headerless, 49 cols):
        data/UNSW-NB15_1.csv  data/UNSW-NB15_2.csv
        data/UNSW-NB15_3.csv  data/UNSW-NB15_4.csv

        uv run --extra eif python -m evaluation.unsw_benchmark

    Provenance / licence: N. Moustafa, J. Slay, "UNSW-NB15: a comprehensive
    data set for network intrusion detection systems (UNSW-NB15 network data
    set)," Military Communications and Information Systems Conference
    (MilCIS), 2015. Dataset (c) UNSW Canberra; research-use terms apply.

Like the other two benchmarks the bulk CSVs are gitignored and never
committed; this wrapper only ever writes a temporary mix file.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from bots_without_labels.evaluate import evaluate_injection
from bots_without_labels.ingest import load
from bots_without_labels.pipeline import detect

# The raw shards are headerless; these are the canonical 49 column names from
# the dataset's NUSW-NB15_features.csv, in order. We apply them only when a
# shard arrives without its own header (the usual raw form).
RAW_COLUMNS = (
    "srcip",
    "sport",
    "dstip",
    "dsport",
    "proto",
    "state",
    "dur",
    "sbytes",
    "dbytes",
    "sttl",
    "dttl",
    "sloss",
    "dloss",
    "service",
    "Sload",
    "Dload",
    "Spkts",
    "Dpkts",
    "swin",
    "dwin",
    "stcpb",
    "dtcpb",
    "smeansz",
    "dmeansz",
    "trans_depth",
    "res_bdy_len",
    "Sjit",
    "Djit",
    "Stime",
    "Ltime",
    "Sintpkt",
    "Dintpkt",
    "tcprtt",
    "synack",
    "ackdat",
    "is_sm_ips_ports",
    "ct_state_ttl",
    "ct_flw_http_mthd",
    "is_ftp_login",
    "ct_ftp_cmd",
    "ct_srv_src",
    "ct_srv_dst",
    "ct_dst_ltm",
    "ct_src_ltm",
    "ct_src_dport_ltm",
    "ct_dst_sport_ltm",
    "ct_dst_src_ltm",
    "attack_cat",
    "Label",
)

DEFAULT_SHARDS = tuple(Path(f"data/UNSW-NB15_{i}.csv") for i in range(1, 5))
LABEL_COLUMN = "Label"
TIME_COLUMN = "Stime"
# A rare-attack mix comparable in shape to the botnet benchmarks: a
# contiguous, time-ordered slice of attack flows (cadence preserved) over a
# sampled benign background. UNSW's attack share is large, so we down-sample
# attacks too.
N_ATTACK = 2_000
N_BENIGN = 60_000
SEED = 7


def present_shards(shards: tuple[Path, ...] = DEFAULT_SHARDS) -> list[Path]:
    """Return the raw shards that exist locally (possibly empty)."""

    return [p for p in shards if p.exists()]


def _read_shard(path: Path) -> pd.DataFrame:
    """Read one raw shard, applying the canonical header if headerless."""

    head = pd.read_csv(path, nrows=1, header=None, low_memory=False)
    if head.shape[1] != len(RAW_COLUMNS):
        raise ValueError(
            f"{path} has {head.shape[1]} columns, expected "
            f"{len(RAW_COLUMNS)} (is this a raw UNSW-NB15 flow shard?)"
        )
    first_cell = str(head.iloc[0, 0]).strip().lower()
    has_header = first_cell == "srcip"
    frame = pd.read_csv(
        path,
        header=0 if has_header else None,
        names=None if has_header else list(RAW_COLUMNS),
        low_memory=False,
    )
    frame.columns = [c.strip() for c in frame.columns]
    return frame


def build_mix(
    shards: tuple[Path, ...] = DEFAULT_SHARDS,
    *,
    n_attack: int = N_ATTACK,
    n_benign: int = N_BENIGN,
    seed: int = SEED,
):
    """Return a (frame-without-label, truth-array) rare-attack mix.

    A contiguous time-ordered slice of attack flows (cadence preserved) is
    mixed with a sampled benign background drawn from the present shards.
    """

    available = present_shards(shards)
    if not available:
        raise FileNotFoundError(
            "no raw UNSW-NB15 shards found (expected one of "
            f"{', '.join(str(p) for p in shards)})"
        )
    df = pd.concat([_read_shard(p) for p in available], ignore_index=True)
    df[LABEL_COLUMN] = pd.to_numeric(
        df[LABEL_COLUMN],
        errors="coerce",
    ).fillna(0)
    df["_ts"] = pd.to_numeric(df[TIME_COLUMN], errors="coerce")

    attack = df[df[LABEL_COLUMN] == 1].sort_values("_ts")
    benign_pool = df[df[LABEL_COLUMN] == 0]

    attack_slice = attack.head(n_attack)
    take = min(n_benign, len(benign_pool))
    benign = benign_pool.sample(n=take, random_state=seed)

    mixed = pd.concat([benign, attack_slice])
    mix = mixed.sort_values("_ts").reset_index(drop=True)
    truth = (mix[LABEL_COLUMN] == 1).to_numpy().astype(int)
    # Drop the labels (and attack family) so detection never sees truth.
    frame = mix.drop(columns=[LABEL_COLUMN, "attack_cat", "_ts"])
    return frame, truth


def run(
    shards: tuple[Path, ...] = DEFAULT_SHARDS,
    *,
    n_attack: int = N_ATTACK,
    n_benign: int = N_BENIGN,
    seed: int = SEED,
):
    """Build the mix, run detection through the real loader, return metrics."""

    frame, truth = build_mix(
        shards,
        n_attack=n_attack,
        n_benign=n_benign,
        seed=seed,
    )
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "unsw_mix.csv"
        frame.to_csv(csv_path, index=False)
        loaded = load(csv_path)
    result = detect(loaded.frame, loaded.schema)

    report = evaluate_injection(result.is_bot, truth)
    report["flag_rate"] = float(np.mean(result.is_bot))
    report["base_rate"] = float(np.mean(truth))
    report["n_rows"] = int(len(truth))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="unsw_benchmark")
    parser.add_argument("--attack", type=int, default=N_ATTACK)
    parser.add_argument("--benign", type=int, default=N_BENIGN)
    args = parser.parse_args(argv)

    if not present_shards():
        print("UNSW-NB15 benchmark: skipped (raw shards absent)")
        print("  expected raw shards data/UNSW-NB15_1.csv .. _4.csv")
        print("  see docstring for sourcing; HF mirrors are unusable")
        return 0

    report = run(n_attack=args.attack, n_benign=args.benign)
    print("UNSW-NB15 (broad IDS, secondary breadth check)")
    print(f"  rows         {report['n_rows']:>8d}")
    print(f"  base rate    {report['base_rate']:>8.3f}")
    print(f"  flag rate    {report['flag_rate']:>8.3f}")
    print(f"  recall       {report['recall']:>8.3f}")
    print(f"  precision    {report['planted_precision']:>8.3f}")
    print("  note: broad IDS, not bot-specific -- not a tracked bot result")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

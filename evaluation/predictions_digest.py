"""Digest the registry mixes' prediction artefacts for byte-identity proofs.

The benchmark suite (`evaluation.run_benchmarks`) proves *metric* equality but
does not retain ``predictions.tsv``. This diagnostic closes that gap: for every
registry mix whose data is present (skip-if-absent), it writes the mix to a
temporary CSV, runs the full :func:`~bots_without_labels.pipeline.run_pipeline`
into a temporary output directory, and prints the SHA-256 of the produced
``predictions.tsv`` and ``predictions-extended.tsv``.

Run it on two revisions and diff the output: identical digests are a
reproducible proof that every row's prediction output is byte-identical.
Deterministic (fixed seeds throughout, single-threaded scoring) and read-only
with respect to the repository — everything it writes goes to a temporary
directory.

Run:
    uv run --extra eif python -m evaluation.predictions_digest
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pandas as pd

from bots_without_labels.pipeline import run_pipeline


def _digest_mix(key: str, frame: pd.DataFrame) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / f"{key}.csv"
        frame.to_csv(csv_path, index=False)
        out = Path(tmp) / "out"
        run_pipeline(csv_path, out)
        digests = []
        for name in ("predictions.tsv", "predictions-extended.tsv"):
            digest = hashlib.sha256((out / name).read_bytes()).hexdigest()
            digests.append(f"{name}={digest}")
    print(f"{key}: " + "  ".join(digests), flush=True)


def main() -> int:
    ran = 0

    zip_path = Path("data/GeneratedLabelledFlows.zip")
    if zip_path.exists():
        from evaluation.cicids_bot_benchmark import build_mix as cicids_mix
        from evaluation.cicids_family_benchmark import FAMILIES
        from evaluation.cicids_family_benchmark import build_mix as family_mix

        _digest_mix("cicids2017", cicids_mix(zip_path)[0])
        ran += 1
        for spec in FAMILIES:
            _digest_mix(f"cicids_{spec.key}", family_mix(spec.key)[0])
            ran += 1
    else:
        print(f"skipped: cicids2017 + families ({zip_path} absent)")

    for key, binetflow in (
        ("ctu13_sc1", Path("data/capture20110810.binetflow")),
        ("ctu13_sc3", Path("data/capture20110812.binetflow")),
    ):
        if binetflow.exists():
            from evaluation.ctu13_bot_benchmark import build_mix as ctu_mix

            _digest_mix(key, ctu_mix(binetflow)[0])
            ran += 1
        else:
            print(f"skipped: {key} ({binetflow} absent)")

    unsw = Path("data/UNSW-NB15_1.csv")
    if unsw.exists():
        from evaluation.unsw_benchmark import build_mix as unsw_mix

        _digest_mix("unsw", unsw_mix((unsw,))[0])
        ran += 1
    else:
        print(f"skipped: unsw ({unsw} absent)")

    bournemouth = Path("data/web_bot_detection_dataset.zip")
    if bournemouth.exists():
        from evaluation.bournemouth_benchmark import build_mix as bmx

        _digest_mix("bournemouth", bmx(bournemouth)[0])
        ran += 1
    else:
        print(f"skipped: bournemouth ({bournemouth} absent)")

    print(f"{ran} mixes digested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Shared machinery for the real-data benchmark wrappers.

Every benchmark in this package has the same shape: a dataset-specific
``build_mix()`` produces a ``(frame-without-label, truth-array)`` rare-attack
mix, which is then scored the same way — written to a temporary CSV, loaded
through the *real* loader (so schema inference is part of what is measured),
detected, and evaluated against the held-out truth. This module owns that
shared tail plus the report formatting and the common CLI arguments, so each
benchmark module contains only what is genuinely dataset-specific: parsing,
label policy, and provenance.

Kept deliberately behaviour-identical to the per-module code it replaced: same
temp-CSV path shape, same report keys, same default sample sizes and seed.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from bots_without_labels.evaluate import evaluate_injection
from bots_without_labels.ingest import load
from bots_without_labels.pipeline import DetectionResult, detect

DEFAULT_SEED = 7
"""Sampling seed shared by every benchmark. Fixed (not varied per run) so
measured numbers are reproducible and comparable across benchmarks."""


def score_mix(
    frame: pd.DataFrame, truth: np.ndarray, *, mix_name: str
) -> tuple[DetectionResult, dict]:
    """Score a labelled mix through the full pipeline; return result and report.

    The mix is round-tripped through a temporary CSV and :func:`load` so that
    format detection and schema inference are exercised exactly as they would
    be on a user's log — scoring the in-memory frame directly would skip the
    part of the pipeline most likely to differ across datasets.

    Args:
        frame: The mix WITHOUT any label column (detection never sees truth).
        truth: Row-aligned 0/1 ground truth.
        mix_name: Basename for the temporary CSV (``<mix_name>.csv``).

    Returns:
        ``(result, report)``: the :class:`DetectionResult` (for benchmark-
        specific extra metrics) and the metrics report from
        :func:`evaluate_injection` extended with ``flag_rate``, ``base_rate``,
        and ``n_rows``.
    """

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / f"{mix_name}.csv"
        frame.to_csv(csv_path, index=False)
        loaded = load(csv_path)
    result = detect(loaded.frame, loaded.schema)

    report = evaluate_injection(result.is_bot, truth)
    report["flag_rate"] = float(np.mean(result.is_bot))
    report["base_rate"] = float(np.mean(truth))
    report["n_rows"] = int(len(truth))
    return result, report


def format_report(title: str, report: dict, *, notes: tuple[str, ...] = ()) -> str:
    """Render one benchmark report in the shared line format.

    Always prints rows / base rate / flag rate / recall / precision; the
    extended timing keys (``timestamp_grid_seconds``, ``dense_timing_gated``,
    ``heuristic_flag_rate``, ``ml_flag_rate``) are printed only when the
    benchmark put them in its report.

    Args:
        title: Heading line for the benchmark.
        report: A report dict from :func:`score_mix` (plus any extras).
        notes: Caveat lines appended verbatim under a ``note:`` prefix.

    Returns:
        The formatted multi-line report.
    """

    lines = [title]
    lines.append(f"  rows                {report['n_rows']:>10d}")
    lines.append(f"  base rate           {report['base_rate']:>10.4f}")
    if "timestamp_grid_seconds" in report:
        grid = report["timestamp_grid_seconds"]
        lines.append(
            f"  timestamp grid (s)  {grid:>10.6f}"
            if grid is not None
            else "  timestamp grid (s)        none"
        )
    if "dense_timing_gated" in report:
        lines.append(f"  dense-timing gated  {str(report['dense_timing_gated']):>10}")
    lines.append(f"  flag rate           {report['flag_rate']:>10.4f}")
    if "heuristic_flag_rate" in report:
        lines.append(f"    heuristic         {report['heuristic_flag_rate']:>10.4f}")
    if "ml_flag_rate" in report:
        lines.append(f"    ml                {report['ml_flag_rate']:>10.4f}")
    lines.append(f"  recall              {report['recall']:>10.4f}")
    lines.append(f"  precision           {report['planted_precision']:>10.4f}")
    for note in notes:
        lines.append(f"  note: {note}")
    return "\n".join(lines)


def add_mix_size_arguments(
    parser: argparse.ArgumentParser,
    *,
    bot_flag: str = "--bot",
    bot_default: int | None = None,
    bot_help: str = "bot/attack rows to include in the mix",
    benign_default: int | None = None,
    seed_default: int = DEFAULT_SEED,
) -> None:
    """Add the shared mix-sizing CLI arguments with consistent help text.

    Args:
        parser: The benchmark's parser (data-path arguments stay per-module).
        bot_flag: Flag name for the positive-class size (``--attack`` on UNSW).
        bot_default: Default positive-class size; ``None`` omits the argument
            (a benchmark that keeps every positive row, like CICIDS).
        bot_help: Help text for the positive-class size argument.
        benign_default: Default benign sample size; ``None`` omits the argument
            (a benchmark that keeps every benign row, like Bournemouth).
        seed_default: Default sampling seed (see :data:`DEFAULT_SEED`).
    """

    if bot_default is not None:
        parser.add_argument(bot_flag, type=int, default=bot_default, help=bot_help)
    if benign_default is not None:
        parser.add_argument(
            "--benign",
            type=int,
            default=benign_default,
            help="benign rows to sample as the background",
        )
    parser.add_argument(
        "--seed",
        type=int,
        default=seed_default,
        help="sampling seed (fixed default keeps measured numbers reproducible)",
    )

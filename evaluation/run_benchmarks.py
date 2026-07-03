"""Single repeatable real-data benchmark runner.

One entry point that runs every real-data benchmark whose dataset is
present locally, skips the rest cleanly, and prints **one** results table:

    uv run --extra eif python -m evaluation.run_benchmarks

Honest framing, carried straight from ``evaluation/FINDINGS.md``:

* The **tracked** numbers come from *real, externally labelled* botnet
  captures (CICIDS2017 Friday / Ares, CTU-13 scenario 1 / Neris). They are
  the benchmarks that mean something.
* The **synthetic** suite is a *stress test only* -- it plants exactly the
  signatures the detector looks for, so a green synthetic run measures
  agreement with ourselves, not detection. It is run via ``pytest``, not
  here, and never appears in this table as a tracked accuracy number.
* UNSW-NB15 is a **secondary, best-effort breadth check** (broad IDS, not a
  botnet capture); it skips unless the raw flow shards are present.

The bulk datasets are gitignored and large, so absent benchmarks skip rather
than fail -- this runner mirrors ``tests/test_real_benchmark.py`` and
``tests/test_ctu13_benchmark.py``, which skip on the same missing files. It
never writes or commits a data file: each benchmark builds its mix into a
temporary CSV that is discarded when the run ends.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from evaluation import (
    bournemouth_benchmark,
    cicids_bot_benchmark,
    ctu13_bot_benchmark,
    unsw_benchmark,
)

# CTU-13 sc3 (Rbot) capture path, via the wrapper's scenario registry.
_SC3_BINETFLOW = ctu13_bot_benchmark.SCENARIOS["sc3"]["binetflow"]


@dataclass(frozen=True)
class Benchmark:
    """One real-data benchmark: how to find its data, run it, and frame it."""

    key: str
    title: str
    tier: str  # "tracked" | "secondary"
    present: Callable[[], bool]
    absent_reason: str
    run: Callable[[], dict]
    caveat: str


# The ``lambda: module.attr...`` wrappers are deliberate, not redundant: they
# defer the attribute lookup to call time, so tests can monkeypatch the
# benchmark modules (e.g. ``present_shards``) and the registry sees the patch.
# pylint: disable=unnecessary-lambda
BENCHMARKS: tuple[Benchmark, ...] = (
    Benchmark(
        key="cicids2017",
        title="CICIDS2017 Friday botnet (Ares)",
        tier="tracked",
        present=lambda: cicids_bot_benchmark.DEFAULT_ZIP.exists(),
        absent_reason=f"{cicids_bot_benchmark.DEFAULT_ZIP} absent",
        run=cicids_bot_benchmark.run,
        caveat=(
            "minute-quantised at source (timing rules have no sub-second "
            "data); precision is the whole detector, ~15% residual is mostly "
            "the ML path."
        ),
    ),
    Benchmark(
        key="ctu13",
        title="CTU-13 scenario 1 (Neris)",
        tier="tracked",
        present=lambda: ctu13_bot_benchmark.DEFAULT_BINETFLOW.exists(),
        absent_reason=f"{ctu13_bot_benchmark.DEFAULT_BINETFLOW} absent",
        run=ctu13_bot_benchmark.run,
        caveat=(
            "asymmetric_degree carries recall cleanly (2000/2000, zero false "
            "fires); actor-band entity gating fixed the prior entity_monotony "
            "over-flagging on the degenerate Proto/State columns. Verified "
            "precision 0.978 / recall 1.000 / flag 0.033 on this one Neris "
            "scenario -- a measured result here, not a general precision."
        ),
    ),
    Benchmark(
        key="ctu13_sc3",
        title="CTU-13 scenario 3 (Rbot)",
        tier="tracked",
        present=lambda: _SC3_BINETFLOW.exists(),
        absent_reason=f"binetflow {_SC3_BINETFLOW} absent",
        run=lambda: ctu13_bot_benchmark.run(_SC3_BINETFLOW),
        caveat=(
            "generality probe (2nd family): recall 0.985 generalises the "
            "diverse-bot catch. asymmetric_degree is now SOURCE fan-out only, so "
            "it is clean here (1970 TP / 0 FP); precision 0.929 (the ~151 "
            "residual FPs are ML-only). The earlier 0.056 came from the "
            "direction-agnostic form firing on benign fan-in hubs; no thresholds "
            "tuned. Fan-in C2 coverage lives in entity_monotony, not here."
        ),
    ),
    Benchmark(
        key="unsw",
        title="UNSW-NB15 (broad IDS)",
        tier="secondary",
        present=lambda: bool(unsw_benchmark.present_shards()),
        absent_reason="raw shards data/UNSW-NB15_1..4.csv absent",
        run=unsw_benchmark.run,
        caveat=(
            "broad IDS, NOT a botnet capture -- secondary breadth check only, "
            "not a tracked bot result. Actor-band entity gating reduced the "
            "prior degenerate-column over-flagging, so flag rate and "
            "incidental coverage dropped; current recall 0.122 is not a bot "
            "regression and precision 0.198 is above prevalence on shard 1 "
            "but not a bot-detection win."
        ),
    ),
    Benchmark(
        key="bournemouth",
        title="Bournemouth Web Bot (web logs)",
        tier="secondary",
        present=lambda: bournemouth_benchmark.DEFAULT_ZIP.exists(),
        absent_reason=f"{bournemouth_benchmark.DEFAULT_ZIP} absent",
        run=bournemouth_benchmark.run,
        caveat=(
            "web-log DOMAIN-TRANSFER check (HTTP access logs, not NetFlow), "
            "clean folder labels. NEGATIVE transfer: precision ~0.02 is BELOW "
            "the ~0.03 base rate. Session entity + actor graph are DORMANT "
            "(web session-id ratio ~0.005 falls below the actor band), so only "
            "timing+ML run and timing over-fires on dense page-load bursts. A "
            "real domain limit, not tuned. Licence: research-use, not formally "
            "specified -- numbers internal pending confirmation."
        ),
    ),
)
# pylint: enable=unnecessary-lambda


def _format_table(rows: list[dict]) -> str:
    """Render the unified results table (one line per benchmark)."""

    header = (
        f"{'benchmark':<34}{'tier':<11}{'status':<10}"
        f"{'rows':>9}{'base':>8}{'flag':>8}{'recall':>8}{'prec':>8}"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        if row["status"] == "ran":
            r = row["report"]
            lines.append(
                f"{row['title']:<34}{row['tier']:<11}{'ran':<10}"
                f"{r['n_rows']:>9d}{r['base_rate']:>8.3f}"
                f"{r['flag_rate']:>8.3f}{r['recall']:>8.3f}"
                f"{r['planted_precision']:>8.3f}"
            )
        else:
            lines.append(
                f"{row['title']:<34}{row['tier']:<11}{'skipped':<10}"
                f"{'-':>9}{'-':>8}{'-':>8}{'-':>8}{'-':>8}"
            )
    return "\n".join(lines)


def valid_keys() -> set[str]:
    """The set of selectable benchmark keys."""

    return {b.key for b in BENCHMARKS}


def run_all(keys: list[str] | None = None) -> list[dict]:
    """Run each selected benchmark if present; return per-row outcomes."""

    selected = BENCHMARKS
    if keys:
        selected = tuple(b for b in BENCHMARKS if b.key in keys)
    rows: list[dict] = []
    for bench in selected:
        row = {"key": bench.key, "title": bench.title, "tier": bench.tier}
        if not bench.present():
            row["status"] = "skipped"
            row["reason"] = bench.absent_reason
        else:
            row["status"] = "ran"
            row["report"] = bench.run()
        row["caveat"] = bench.caveat
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_benchmarks",
        description="Run every present real-data benchmark; print one table.",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="comma-separated benchmark keys to run "
        f"(default all: {', '.join(b.key for b in BENCHMARKS)})",
    )
    args = parser.parse_args(argv)

    keys = None
    if args.only:
        keys = [k.strip() for k in args.only.split(",") if k.strip()]
        unknown = [k for k in keys if k not in valid_keys()]
        if unknown:
            # Non-zero exit (argparse uses code 2) rather than a silent
            # empty table that could read as a successful run.
            parser.error(
                f"unknown benchmark key(s): {', '.join(unknown)}; "
                f"valid: {', '.join(sorted(valid_keys()))}"
            )

    print("Bots Without Labels -- real-data benchmark suite")
    print(
        "Tracked numbers come from real, externally labelled botnet "
        "captures. The\nsynthetic suite is a stress test only (run via "
        "pytest) and is not a tracked\naccuracy number."
    )
    print()

    rows = run_all(keys)
    print(_format_table(rows))
    print()

    ran = [r for r in rows if r["status"] == "ran"]
    skipped = [r for r in rows if r["status"] == "skipped"]
    print(f"{len(ran)} ran, {len(skipped)} skipped (dataset absent).")
    for r in rows:
        if r["status"] == "ran":
            print(f"  [{r['key']}] {r['caveat']}")
        else:
            print(f"  [{r['key']}] skipped: {r['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

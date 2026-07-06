"""Web-log domain-transfer benchmark: Bournemouth/CERTH Web Bot Detection.

Companion to the NetFlow botnet benchmarks (CICIDS2017, CTU-13). Those are
network-flow captures; this is the opposite domain -- raw HTTP **server access
logs** -- so it tests whether the detector's per-entity + timing signals transfer
from flows to web logs. The bot here is an automated web client (crawler / form
bot) rather than a network botnet host.

Source / provenance:
    M. Iliou et al., "Web Bot Detection" dataset, Information Technologies
    Institute (CERTH) and Bournemouth University. Catalogue: BORDaR record 272
    (https://bordar.bournemouth.ac.uk/272/); data:
    https://m4d.iti.gr/web-bot-detection-dataset/ (single 32 MB zip, public,
    no-auth). LICENCE: copyright is held by CERTH + Bournemouth University and the
    catalogue marks rights reserved; the README invites research use but states no
    formal/open (e.g. CC) licence. Treat measured numbers as *internal* until the
    licence is confirmed for publication. This wrapper never redistributes the
    data -- it reads only the locally-supplied zip, which stays gitignored.

Label / entity / timestamp mapping (confirmed before trusting numbers):
    * LABEL is the dataset's own folder split -- ``web_logs/bots/*`` (automated)
      vs ``web_logs/humans/*`` (human); the bot tier (advanced/moderate) is in the
      filename. Dataset-provided ground truth, not derived or circular.
    * Each access-log line is the custom-combined format
      ``%h %l [%t] "%r" %>s %b "%{Referer}" SESSIONID "%{User-Agent}"``. The host
      (``%h``) is anonymised to ``-`` in every line, so there is NO IP. The ACTOR
      ENTITY is the per-session id (8th field), which recurs across a session's
      requests and cross-checks the ``annotations`` files; ``user_agent`` is a
      second entity. TIMESTAMP is per-second.
    * Consequence (as MEASURED on this data, reported not tuned): the actor
      selectors are now scale-invariant (they key on recurrence + value shape, not
      the old cardinality ratio), so the recurring ``session_id`` IS admitted as a
      per-entity actor here -- which *directly* demonstrates the method limit
      rather than hiding it. A session's per-entity monotony does NOT separate an
      evasive web bot from a human: both a bot session and a monotone human session
      look self-similar, so ``entity_monotony`` fires on human sessions too and the
      detector over-flags (~92% of rows, precision 0.028 -- still *below* the ~0.029
      base rate, i.e. worse than guessing). ``user_agent`` is near-constant (the
      advanced/moderate bots spoof real browser UAs -- only ~4 distinct UAs), and
      the timing rules over-fire on dense page-load bursts. This is a real
      domain-transfer limit -- the NetFlow-shaped signals (repetition, monotony,
      timing) do not transfer to human-mimicking web bots; closing it needs
      web-specific signals (interaction biometrics), tracked in TODO item 12. It is
      NOT tuned around. (A raw request-``path`` column is also still admitted as a
      pseudo-actor -- content, not an identity; generic content-column detection
      for non-URL-typed path fields is a known residual, TODO follow-up H/12.)

Native balance is near-even (phase1: ~38.9k bot / ~57.5k human requests). For
comparability with the ~3% rare-attack NetFlow mixes we keep all human requests as
the benign background and subsample whole bot *sessions* down to a small minority;
the measured base rate is reported. Note: at a rare-attack base only a handful of
bot sessions are included, so per-session recall is noisy -- read this as a
qualitative transfer check, not a precise score.

Run:
    uv run --extra eif python -m evaluation.bournemouth_benchmark
"""

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path

import pandas as pd

from evaluation.harness import (
    DEFAULT_SEED,
    add_mix_size_arguments,
    format_report,
    score_mix,
)

DEFAULT_ZIP = Path("data/web_bot_detection_dataset.zip")
BOT_PREFIX = "phase1/data/web_logs/bots/"
HUMAN_PREFIX = "phase1/data/web_logs/humans/"
# %h %l [%t] "%r" %>s %b "%{Referer}" SESSIONID "%{User-Agent}"
LOG_RE = re.compile(
    r'^(\S+) (\S+) \[([^\]]+)\] "([^"]*)" (\S+) (\S+) "([^"]*)" (\S+) "([^"]*)"$'
)
TIME_FMT = "%d/%b/%Y:%H:%M:%S %z"
# Bot requests sampled (as whole sessions) for a rare-attack base rate against
# the full ~57.5k-request human background.
N_BOT = 1_800
SEED = DEFAULT_SEED


def parse_line(line: str) -> dict | None:
    """Parse one access-log line to an event dict, or ``None`` if unusable.

    Unsessioned landing requests (session id ``-``, ~1.8% of lines, the initial
    ``GET /`` before a session cookie is set) return ``None``: they cannot be
    attributed to a session and would otherwise collapse into one degenerate
    ``-`` mega-entity.
    """

    match = LOG_RE.match(line.strip())
    if match is None:
        return None
    _host, _ident, ts, request, status, nbytes, referer, session, ua = match.groups()
    if session == "-":
        return None
    parts = request.split()
    return {
        "timestamp": ts,
        "method": parts[0] if parts else "",
        "path": parts[1] if len(parts) > 1 else "",
        "status": status,
        "bytes": "" if nbytes == "-" else nbytes,
        "referer": referer,
        "session_id": session,
        "user_agent": ua,
    }


def _read_events(archive: zipfile.ZipFile, prefix: str, label: int) -> list[dict]:
    """Parse every ``.log`` member under ``prefix`` into labelled event dicts."""

    rows: list[dict] = []
    for name in archive.namelist():
        if not (name.startswith(prefix) and name.endswith(".log")):
            continue
        for line in archive.read(name).decode("utf-8", "ignore").splitlines():
            record = parse_line(line)
            if record is not None:
                record["_label"] = label
                rows.append(record)
    return rows


def build_mix(zip_path: Path = DEFAULT_ZIP, *, n_bot: int = N_BOT, seed: int = SEED):
    """Return a (frame-without-label, truth-array) rare-attack web-log mix.

    All human requests form the benign background; whole bot *sessions* are
    sampled (kept intact, so per-session baselining is honest) until about
    ``n_bot`` bot requests are included.
    """

    with zipfile.ZipFile(zip_path) as archive:
        bots = _read_events(archive, BOT_PREFIX, 1)
        humans = _read_events(archive, HUMAN_PREFIX, 0)

    bot_df = pd.DataFrame(bots)
    human_df = pd.DataFrame(humans)

    # Sample whole bot sessions (shuffled) until ~n_bot bot requests are reached.
    sizes = bot_df["session_id"].value_counts().sample(frac=1, random_state=seed)
    keep = sizes.cumsum() <= n_bot
    if not keep.any():  # n_bot smaller than the first session: keep that one
        keep.iloc[0] = True
    kept_sessions = set(sizes.index[keep])
    bot_keep = bot_df[bot_df["session_id"].isin(kept_sessions)]

    mix = pd.concat([human_df, bot_keep], ignore_index=True)
    parsed = pd.to_datetime(mix["timestamp"], format=TIME_FMT, errors="coerce")
    mix = mix.assign(_ts=parsed).sort_values("_ts").reset_index(drop=True)
    # Replace the raw Apache timestamp string (which the loader's sniffer does not
    # recognise) with the parsed datetime, so the timestamp role -- and the timing
    # rules -- are actually active.
    mix["timestamp"] = mix["_ts"]

    truth = mix["_label"].to_numpy().astype(int)
    frame = mix.drop(columns=["_label", "_ts"])
    return frame, truth


def run(zip_path: Path = DEFAULT_ZIP, *, n_bot: int = N_BOT, seed: int = SEED):
    """Build the mix, run detection through the real loader, return metrics."""

    frame, truth = build_mix(zip_path, n_bot=n_bot, seed=seed)
    _, report = score_mix(frame, truth, mix_name="bournemouth_mix")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bournemouth_benchmark")
    parser.add_argument(
        "--zip",
        type=Path,
        default=DEFAULT_ZIP,
        help="path to the web_bot_detection_dataset.zip archive",
    )
    add_mix_size_arguments(
        parser,
        bot_default=N_BOT,
        bot_help="approximate bot requests to include (whole sessions)",
        seed_default=SEED,
    )
    args = parser.parse_args(argv)

    if not args.zip.exists():
        print(f"Bournemouth benchmark: skipped ({args.zip} absent)")
        print(
            "  fetch the 32 MB zip from https://m4d.iti.gr/web-bot-detection-dataset/"
        )
        return 0

    report = run(args.zip, n_bot=args.bot, seed=args.seed)
    print(
        format_report(
            "Bournemouth Web Bot Detection (web-log domain-transfer)",
            report,
            notes=(
                "web-log domain-transfer; session entity + actor graph DORMANT "
                "(session ratio below the actor band), timing+ML only; licence "
                "research-use (not formally specified)",
            ),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase-1 offline evidence probe for TODO follow-ups H and I (actor residuals).

Read-only diagnostic: it makes NO engine edits and changes NO detector
behaviour. It measures, on minimal fixtures and (skip-if-absent) on the real
captures, three known residuals of the scale-invariant actor selection:

* **H  — integer-coded identifiers.** A numeric session id or integer-coded IP
  is typed ``numeric`` at ingest, so ``_entity_columns`` and
  ``_actor_endpoint_columns`` never see it and the actor rules go dormant.
* **Ia — short unstructured actor ids.** A closed pool of bare integers,
  usernames, or mnemonic hostnames is shape-ambiguous versus a bounded enum
  vocabulary (``_is_vocabulary``), so it is excluded even when it is a genuine
  actor population.
* **Ib — raw path / content columns.** A non-URL-typed request ``path`` column
  passes the recurrence + shape tests and is admitted as a pseudo-actor
  (content in an identity seat), the mechanism behind the Bournemouth
  over-flagging.

For each residual it also measures the *candidate separating signals* the
Phase-1 brief names — recurrence structure, cross-column co-occurrence /
counterpart structure, and token grammar — so the Phase-1 decision ("separable
by observable signal" vs "genuinely ambiguous, fall back to an explicit schema
override such as ``--entity-column``") rests on printed numbers, not intuition.

Nothing here uses ``distinct / n_rows`` (the removed scale-dependent ratio).
Real-capture output is mechanism evidence only — column admission and signal
values, never precision/recall claims. Bournemouth output stays
internal/provisional (licence pending).

Run:
    uv run --extra eif python -m evaluation.actor_residual_probe
    uv run --extra eif python -m evaluation.actor_residual_probe --real
"""

from __future__ import annotations

import argparse
import random
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from bots_without_labels.features import (
    ACTOR_MIN_EVENTS,
    _actor_endpoint_columns,
    _entity_columns,
    _is_vocabulary,
    _repeat_mass,
    _structured_fraction,
)
from bots_without_labels.features import (
    ACTOR_MIN_DISTINCT,
    ACTOR_MIN_RECURRING,
    REPEAT_MASS_MIN,
)
from bots_without_labels.ingest import LoadedLog, Role, load
from bots_without_labels.pipeline import detect

SEED = 7
"""Fixed seed, matching ``evaluation.harness.DEFAULT_SEED`` for reproducibility."""

_SEPARATOR_CHARS = set(".:_-/")


# ---------------------------------------------------------------------------
# Shared probe machinery
# ---------------------------------------------------------------------------


def _load_frame(frame: pd.DataFrame, name: str) -> LoadedLog:
    """Round-trip a frame through CSV + :func:`load`, like the harness does,
    so format detection and schema inference run exactly as on a user's log."""

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / f"{name}.csv"
        frame.to_csv(csv_path, index=False)
        return load(csv_path)


def _selection_report(loaded: LoadedLog, *, run_detect: bool = True) -> None:
    """Print inferred roles, selected entity/actor columns, and rule fires."""

    schema, frame = loaded.schema, loaded.frame
    roles = {col.name: col.role for col in schema.columns}
    print(f"  roles: {roles}")
    categoricals = schema.columns_with_role(Role.CATEGORICAL)
    entity = _entity_columns(frame, schema, categoricals)
    endpoints = _actor_endpoint_columns(frame, schema)
    print(f"  _entity_columns:         {entity}")
    print(f"  _actor_endpoint_columns: {endpoints}")
    if endpoints:
        print(f"  directional source endpoint (schema order): {endpoints[0]}")
    if run_detect:
        result = detect(frame, schema)
        fires = Counter(hit.rule_id for row in result.rules_result.hits for hit in row)
        print(f"  rule fires (rows per rule): {dict(sorted(fires.items()))}")
        examples: dict[str, str] = {}
        for row in result.rules_result.hits:
            for hit in row:
                examples.setdefault(hit.rule_id, hit.reason)
        for rule_id, reason in sorted(examples.items()):
            print(f"    e.g. {rule_id}: {reason}")
        print(f"  flagged rows: {int(result.is_bot.sum())} of {len(frame)}")


def _stringify_column(series: pd.Series) -> pd.Series:
    """Non-missing values as strings, formatting integral floats without
    the trailing ``.0`` a CSV round-trip introduces on numeric columns."""

    values = series.dropna()
    if pd.api.types.is_float_dtype(values) and (values % 1 == 0).all():
        return values.astype("int64").astype(str)
    return values.astype(str)


# ---------------------------------------------------------------------------
# Candidate separating signals (offline; deliberately independent of engine)
# ---------------------------------------------------------------------------


def grammar_signals(values: list[str]) -> dict[str, float]:
    """Token-grammar profile of a column's *distinct* values."""

    if not values:
        return {}
    leading_sep = sum(1 for v in values if v and v[0] in _SEPARATOR_CHARS)
    sep_counts = [sum(1 for ch in v if ch in _SEPARATOR_CHARS) for v in values]
    all_digits = [v for v in values if v.isdigit()]
    digit_share = len(all_digits) / len(values)
    if all_digits:
        lengths = Counter(len(v) for v in all_digits)
        dominant_len_share = max(lengths.values()) / len(all_digits)
    else:
        dominant_len_share = float("nan")
    return {
        "structured_fraction": round(_structured_fraction(values), 3),
        "leading_separator_fraction": round(leading_sep / len(values), 3),
        "mean_separator_count": round(float(np.mean(sep_counts)), 2),
        "pure_digit_fraction": round(digit_share, 3),
        "dominant_digit_length_share": round(dominant_len_share, 3),
    }


def counterpart_selectivity(
    frame: pd.DataFrame, col: str, other: str
) -> dict[str, float]:
    """Cross-column co-occurrence signal: how selective are ``col``'s recurring
    values in which ``other`` values they co-occur with?

    For each value of ``col`` recurring >= ACTOR_MIN_EVENTS, observed coverage
    is the fraction of ``other``'s distinct values it co-occurs with. Expected
    coverage is what independent draws from ``other``'s marginal would give the
    same row count. The ratio (selectivity) is ~1 for a vocabulary/content
    value (mixes freely) and « 1 for an identity (talks to its own
    counterparts). Scale-invariant: both sides saturate for fixed populations.
    """

    pair = frame[[col, other]].dropna()
    col_values = _stringify_column(pair[col])
    other_values = _stringify_column(pair[other])
    marginal = other_values.value_counts(normalize=True)
    n_distinct_other = len(marginal)
    if n_distinct_other == 0:
        return {}
    counts = col_values.value_counts()
    recurring = counts[counts >= ACTOR_MIN_EVENTS]
    if recurring.empty:
        return {}
    total_weight = 0.0
    weighted_ratio = 0.0
    for value, n in recurring.items():
        rows = other_values[col_values == value]
        observed = rows.nunique() / n_distinct_other
        expected = float((1.0 - (1.0 - marginal) ** int(n)).sum()) / n_distinct_other
        if expected <= 0:
            continue
        weighted_ratio += n * (observed / expected)
        total_weight += n
    if total_weight == 0:
        return {}
    return {
        "recurring_values": int(len(recurring)),
        "weighted_selectivity": round(weighted_ratio / total_weight, 3),
    }


def actor_test_audit(loaded: LoadedLog, column: str) -> dict[str, object]:
    """Apply the existing scale-invariant actor tests to ONE column as if its
    values were strings — the 'what would happen if this column were routed
    through the selector' audit, without touching the selector."""

    frame = loaded.frame
    values = _stringify_column(frame[column])
    counts = values.value_counts()
    distinct = int(len(counts))
    recurring = int((counts >= ACTOR_MIN_EVENTS).sum())
    mass = _repeat_mass(counts, len(values))
    vocabulary = _is_vocabulary([str(v) for v in counts.index], distinct)
    qualifies = (
        distinct > ACTOR_MIN_DISTINCT
        and recurring >= ACTOR_MIN_RECURRING
        and mass >= REPEAT_MASS_MIN
        and not vocabulary
    )
    return {
        "distinct": distinct,
        f"recurring>={ACTOR_MIN_EVENTS}": recurring,
        "repeat_mass": round(mass, 3),
        "is_vocabulary": vocabulary,
        "WOULD_QUALIFY_AS_ENDPOINT": qualifies,
    }


def numeric_audit(loaded: LoadedLog, *, endpoint_for_coverage: str | None) -> None:
    """For every numeric-typed column: would it qualify as an actor endpoint if
    integer columns were routed through the existing tests (candidate H fix)?"""

    numerics = loaded.schema.columns_with_role(Role.NUMERIC)
    if not numerics:
        print("  (no numeric columns)")
        return
    for name in numerics:
        audit = actor_test_audit(loaded, name)
        line = f"  {name}: {audit}"
        if audit["WOULD_QUALIFY_AS_ENDPOINT"] and endpoint_for_coverage:
            sel = counterpart_selectivity(loaded.frame, name, endpoint_for_coverage)
            line += f"  selectivity vs {endpoint_for_coverage}: {sel}"
        distinct_values = _stringify_column(loaded.frame[name]).unique().tolist()
        line += f"  grammar: {grammar_signals([str(v) for v in distinct_values])}"
        print(line)


# ---------------------------------------------------------------------------
# Fixtures (deterministic; volumes clear the ENTITY/ACTOR floors on purpose)
# ---------------------------------------------------------------------------


def _ip_to_int(ip: str) -> int:
    a, b, c, d = (int(part) for part in ip.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def broadcaster_fixture(coding: str) -> pd.DataFrame:
    """The toolkit Recipe-5 broadcaster: one fan-out source (90 distinct
    destinations, one service) over 60 benign clients x 12 flows to 2 servers.
    ``coding='dotted'`` keeps IP strings; ``coding='integer'`` inet-codes them.
    """

    rows: list[dict] = []
    for i in range(90):
        rows.append(
            {"src": "10.0.0.1", "dst": f"10.9.{i // 256}.{i % 256}", "svc": "smtp"}
        )
    for c in range(60):
        server = "10.0.0.250" if c % 2 == 0 else "10.0.0.251"
        rows.extend([{"src": f"10.0.1.{c}", "dst": server, "svc": "https"}] * 12)
    frame = pd.DataFrame(rows)
    if coding == "integer":
        frame["src"] = frame["src"].map(_ip_to_int)
        frame["dst"] = frame["dst"].map(_ip_to_int)
    return frame


def session_fixture(id_form: str) -> pd.DataFrame:
    """40 sessions x 30 events with diverse behaviour columns. ``id_form='token'``
    gives structured ids ('sess1001'); ``id_form='integer'`` bare ints (1001)."""

    rng = random.Random(SEED)
    actions = ["view", "click", "add", "remove", "search", "pay", "rate", "share"]
    rows: list[dict] = []
    for s in range(40):
        session = 1001 + s
        for _ in range(30):
            rows.append(
                {
                    "session_id": f"sess{session}" if id_form == "token" else session,
                    "action": rng.choice(actions),
                    "item": rng.randint(1, 500),
                }
            )
    return pd.DataFrame(rows)


def pool_fixture(id_form: str) -> pd.DataFrame:
    """The Ia ambiguity pair: a closed pool of 60 actor ids (each exactly 12
    rows, talking to 3 of 12 servers — selective) alongside a ``cmd`` column of
    60 short tokens with the IDENTICAL frequency profile but assigned
    independently of the actor (a true vocabulary). ``id_form='username'``
    makes the actor pool short/unstructured; ``id_form='structured'`` makes it
    token-shaped ('usr-1001')."""

    rng = random.Random(SEED)
    first = ["ana", "bob", "cai", "dee", "eli", "fay", "gus", "hal", "ivy", "jo"]
    last = ["m", "r", "s", "t", "v", "w"]
    users = [f"{first[i % 10]}{last[i // 10]}" for i in range(60)]
    if id_form == "structured":
        users = [f"usr-{1001 + i}" for i in range(60)]
    servers = [f"10.2.0.{k}" for k in range(12)]
    consonants = "bcdfghklmnprstvz"
    vowels = "aeiou"
    cmds = []
    while len(cmds) < 60:
        word = "".join(rng.choice(consonants) + rng.choice(vowels) for _ in range(2))
        if word not in cmds:
            cmds.append(word)
    cmd_stream = [cmd for cmd in cmds for _ in range(12)]
    rng.shuffle(cmd_stream)
    rows: list[dict] = []
    for i, user in enumerate(users):
        own_servers = rng.sample(servers, 3)
        for _ in range(12):
            rows.append(
                {
                    "user": user,
                    "server": rng.choice(own_servers),
                    "cmd": cmd_stream[len(rows)],
                    "bytes": rng.randint(40, 4000),
                }
            )
    return pd.DataFrame(rows)


def weblog_fixture() -> pd.DataFrame:
    """The Ib pseudo-actor case: 80 structured sessions requesting 70 raw
    paths (40 product pages, 20 API items, 10 short static pages). The path
    column is content, not identity, but is recurrence- and shape-eligible.

    Columns follow Apache access-log order (path BEFORE session_id), and
    ``bytes`` is a deterministic function of the path — a static page returns
    the same size on every request — so a hot path is behaviourally monotone,
    as on a real web server, not diversified by per-row noise."""

    rng = random.Random(SEED)
    static = [
        "/",
        "/cart",
        "/login",
        "/checkout",
        "/search",
        "/about",
        "/faq",
        "/home",
        "/terms",
        "/contact",
    ]
    products = [f"/products/{1000 + i}" for i in range(40)]
    api = [f"/api/v1/items/{i}" for i in range(20)]
    catalogue = static + products + api
    weights = [30] * len(static) + [12] * len(products) + [12] * len(api)
    page_bytes = {path: 200 + 137 * i for i, path in enumerate(catalogue)}
    rows: list[dict] = []
    for s in range(80):
        for _ in range(rng.randint(12, 16)):
            path = rng.choices(catalogue, weights=weights, k=1)[0]
            rows.append(
                {
                    "method": "GET",
                    "path": path,
                    "status": (
                        "200"
                        if path in static
                        else rng.choice(["200", "200", "200", "304", "404"])
                    ),
                    "bytes": page_bytes[path],
                    "session_id": f"sess_{1000 + s}",
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Probe sections
# ---------------------------------------------------------------------------


def probe_h() -> None:
    print("=" * 72)
    print("Residual H — integer-coded identifiers")
    print("=" * 72)
    print("PREDICTED: dotted -> endpoints [src, dst], asymmetric_degree fires 90;")
    print(
        "PREDICTED: integer -> roles numeric, no entity/actor columns, 0 "
        "actor-rule fires (entity_monotony/asymmetric_degree; supporting "
        "numeric_reuse and ML-tail flags may still appear)."
    )
    for coding in ("dotted", "integer"):
        print(f"\n[H1 broadcaster / {coding} addresses]")
        _selection_report(_load_frame(broadcaster_fixture(coding), f"h1_{coding}"))
    print("\nPREDICTED: token ids -> _entity_columns [session_id]; integer ids -> [].")
    for id_form in ("token", "integer"):
        print(f"\n[H2 sessions / {id_form} ids]")
        _selection_report(_load_frame(session_fixture(id_form), f"h2_{id_form}"))
    print("\n[H candidate-signal audit: integer variants routed through actor tests]")
    for name, frame in (
        ("h1_integer", broadcaster_fixture("integer")),
        ("h2_integer", session_fixture("integer")),
    ):
        loaded = _load_frame(frame, name)
        print(f"  -- {name} --")
        numeric_audit(loaded, endpoint_for_coverage=None)


def probe_ia() -> None:
    print("=" * 72)
    print("Residual Ia — short unstructured actor ids vs bounded vocabulary")
    print("=" * 72)
    print("PREDICTED: username pool excluded as vocabulary (grammar cannot separate")
    print("PREDICTED: it from the frequency-identical cmd column); counterpart")
    print("PREDICTED: selectivity separates them (user << 1, cmd ~ 1).")
    for id_form in ("username", "structured"):
        print(f"\n[Ia pool / {id_form} ids]")
        loaded = _load_frame(pool_fixture(id_form), f"ia_{id_form}")
        _selection_report(loaded)
    loaded = _load_frame(pool_fixture("username"), "ia_signals")
    frame = loaded.frame
    for col in ("user", "cmd"):
        distinct = _stringify_column(frame[col]).unique().tolist()
        print(f"\n  {col}: grammar {grammar_signals([str(v) for v in distinct])}")
        print(
            f"  {col}: selectivity vs server "
            f"{counterpart_selectivity(frame, col, 'server')}"
        )
        print(f"  {col}: actor-test audit {actor_test_audit(loaded, col)}")


def probe_ib() -> None:
    print("=" * 72)
    print("Residual Ib — raw path/content column admitted as pseudo-actor")
    print("=" * 72)
    print("PREDICTED: path admitted to BOTH entity columns and actor endpoints,")
    print("PREDICTED: and (Apache column order) path takes the directional SOURCE")
    print("PREDICTED: seat; entity_monotony fires >0 rows via monotone hot paths")
    print("PREDICTED: (moderate confidence); selectivity ~1 for BOTH columns")
    print("PREDICTED: (negative); leading-separator 1.0 vs 0.0 separates.")
    loaded = _load_frame(weblog_fixture(), "ib_weblog")
    _selection_report(loaded)
    frame = loaded.frame
    for col in ("session_id", "path"):
        distinct = _stringify_column(frame[col]).unique().tolist()
        print(f"\n  {col}: grammar {grammar_signals([str(v) for v in distinct])}")
        print(
            f"  {col}: selectivity vs "
            f"{'path' if col == 'session_id' else 'session_id'} "
            f"{counterpart_selectivity(frame, col, 'path' if col == 'session_id' else 'session_id')}"
        )


def probe_real() -> None:
    """Skip-if-absent measurements on the real captures (mechanism only)."""

    print("=" * 72)
    print("Real captures (skip-if-absent; mechanism evidence only —")
    print("Bournemouth values are internal/provisional, licence pending)")
    print("=" * 72)

    bournemouth_zip = Path("data/web_bot_detection_dataset.zip")
    if bournemouth_zip.exists():
        from evaluation.bournemouth_benchmark import build_mix as bmx

        print("\n[Bournemouth web-log mix, seed 7]")
        frame, _truth = bmx(bournemouth_zip)
        loaded = _load_frame(frame, "bournemouth")
        _selection_report(loaded)
        for col in ("path", "session_id", "user_agent", "referer", "method"):
            if col not in loaded.frame.columns:
                continue
            distinct = _stringify_column(loaded.frame[col]).unique().tolist()
            print(f"  {col}: grammar {grammar_signals([str(v) for v in distinct])}")
            if col != "session_id":
                sel = counterpart_selectivity(loaded.frame, col, "session_id")
                if sel:
                    print(f"  {col}: selectivity vs session_id {sel}")
        sel = counterpart_selectivity(loaded.frame, "session_id", "path")
        print(f"  session_id: selectivity vs path {sel}")
        print("  numeric-column audit (candidate H routing on the web log):")
        numeric_audit(loaded, endpoint_for_coverage="session_id")
    else:
        print("\n[Bournemouth] SKIPPED — data/web_bot_detection_dataset.zip absent")

    flow_captures: list[tuple[str, object]] = []
    ctu = Path("data/capture20110810.binetflow")
    if ctu.exists():
        from evaluation.ctu13_bot_benchmark import build_mix as ctu_mix

        flow_captures.append(("CTU-13 sc1 (Neris) mix", lambda: ctu_mix(ctu)[0]))
    else:
        print("\n[CTU-13 sc1] SKIPPED — binetflow absent")
    cicids = Path("data/GeneratedLabelledFlows.zip")
    if cicids.exists():
        from evaluation.cicids_bot_benchmark import build_mix as cic_mix

        flow_captures.append(("CICIDS2017 Ares mix", lambda: cic_mix(cicids)[0]))
    else:
        print("\n[CICIDS2017] SKIPPED — GeneratedLabelledFlows.zip absent")
    unsw = Path("data/UNSW-NB15_1.csv")
    if unsw.exists():
        from evaluation.unsw_benchmark import build_mix as unsw_mix

        flow_captures.append(("UNSW-NB15 mix", lambda: unsw_mix((unsw,))[0]))
    else:
        print("\n[UNSW-NB15] SKIPPED — UNSW-NB15_1.csv absent")

    for title, make in flow_captures:
        print(f"\n[{title}]")
        loaded = _load_frame(make(), title.split()[0].lower())
        _selection_report(loaded, run_detect=False)
        entity = _entity_columns(
            loaded.frame,
            loaded.schema,
            loaded.schema.columns_with_role(Role.CATEGORICAL),
        )
        endpoints = _actor_endpoint_columns(loaded.frame, loaded.schema)
        for col in entity:
            if col in endpoints:
                continue
            distinct = _stringify_column(loaded.frame[col]).unique().tolist()
            print(
                f"  {col} (entity column): "
                f"grammar {grammar_signals([str(v) for v in distinct])}"
            )
        anchor = endpoints[0] if endpoints else None
        print("  numeric-column audit (candidate H routing — a column that")
        print("  WOULD_QUALIFY here means naive integer routing changes this")
        print("  capture's selection, i.e. NOT bit-identical):")
        numeric_audit(loaded, endpoint_for_coverage=anchor)
        for col in endpoints:
            sel = {}
            others = [c for c in endpoints if c != col]
            if others:
                sel = counterpart_selectivity(loaded.frame, col, others[0])
            distinct = _stringify_column(loaded.frame[col]).unique().tolist()
            print(f"  {col} (admitted endpoint): selectivity {sel}")
            print(f"    grammar: {grammar_signals([str(v) for v in distinct])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="actor_residual_probe")
    parser.add_argument(
        "--real",
        action="store_true",
        help="also probe the real captures (skip-if-absent; slower)",
    )
    args = parser.parse_args(argv)
    probe_h()
    probe_ia()
    probe_ib()
    if args.real:
        probe_real()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

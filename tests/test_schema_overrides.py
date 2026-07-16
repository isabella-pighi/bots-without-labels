"""Explicit schema overrides and raw-content grammar demotion (follow-ups H/I).

Covers the Phase-2 contract: overrides are default-off (no flag, no behaviour
change), ``--entity-column`` makes an otherwise invisible identity eligible for
the SAME actor/entity machinery as inferred actors (identity-shape tests
bypassed, volume/recurrence floors kept), ``--content-column`` forces
exclusion, and raw path-like content is demoted by value grammar
(:func:`_is_path_shaped`) unless the user overrides.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from bots_without_labels import cli
from bots_without_labels.features import (
    _actor_endpoint_columns,
    _entity_columns,
    _is_path_shaped,
)
from bots_without_labels.ingest import Role, load
from bots_without_labels.pipeline import detect


def _write_csv(path: Path, header: str, rows: list[str]) -> Path:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def _integer_broadcaster_log(path: Path) -> Path:
    """The H1 minimal pair's integer side: one fan-out source (90 distinct
    destinations, one service) over 60 benign clients x 12 flows to 2 servers,
    with every address integer-coded so ingest types the columns numeric."""

    def ip_to_int(ip: str) -> int:
        a, b, c, d = (int(part) for part in ip.split("."))
        return (a << 24) | (b << 16) | (c << 8) | d

    rows = []
    for i in range(90):
        rows.append(
            f"{ip_to_int('10.0.0.1')},{ip_to_int(f'10.9.{i // 256}.{i % 256}')},smtp"
        )
    for c in range(60):
        server = "10.0.0.250" if c % 2 == 0 else "10.0.0.251"
        rows.extend([f"{ip_to_int(f'10.0.1.{c}')},{ip_to_int(server)},https"] * 12)
    return _write_csv(path, "src,dst,svc", rows)


def _weblog(path: Path) -> Path:
    """A benign web log whose raw ``path`` column is content, not identity:
    80 structured sessions requesting 70 paths, bytes deterministic per path."""

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
    catalogue = (
        static
        + [f"/products/{1000 + i}" for i in range(40)]
        + [f"/api/v1/items/{i}" for i in range(20)]
    )
    page_bytes = {p: 200 + 137 * i for i, p in enumerate(catalogue)}
    rows = []
    for s in range(80):
        for k in range(14):
            page = catalogue[(s * 7 + k * 3) % len(catalogue) if k % 3 else k % 10]
            rows.append(f"GET,{page},200,{page_bytes[page]},sess_{1000 + s}")
    return _write_csv(path, "method,path,status,bytes,session_id", rows)


def _selection(loaded):
    entity = _entity_columns(
        loaded.frame, loaded.schema, loaded.schema.columns_with_role(Role.CATEGORICAL)
    )
    endpoints = _actor_endpoint_columns(loaded.frame, loaded.schema)
    return entity, endpoints


def test_default_off_marks_no_overrides(tmp_path: Path) -> None:
    loaded = load(_integer_broadcaster_log(tmp_path / "flows.csv"))
    assert not any(col.entity_override for col in loaded.schema.columns)
    assert not any(col.content_override for col in loaded.schema.columns)
    payload = loaded.schema.to_dict()
    assert all(not col["entity_override"] for col in payload["columns"])


def test_integer_ids_invisible_by_default(tmp_path: Path) -> None:
    loaded = load(_integer_broadcaster_log(tmp_path / "flows.csv"))
    assert loaded.schema.role_of("src") == Role.NUMERIC
    assert _selection(loaded) == ([], [])


def test_entity_override_recovers_integer_coded_actors(tmp_path: Path) -> None:
    """The override makes the integer-coded broadcaster behave exactly like its
    dotted-address twin: same selection, same 90-row asymmetric_degree fire."""

    loaded = load(
        _integer_broadcaster_log(tmp_path / "flows.csv"),
        entity_columns=("src", "dst"),
    )
    assert loaded.schema.role_of("src") == Role.CATEGORICAL
    entity, endpoints = _selection(loaded)
    assert entity == ["src"]
    assert endpoints == ["src", "dst"]

    result = detect(loaded.frame, loaded.schema)
    fires = Counter(hit.rule_id for row in result.rules_result.hits for hit in row)
    assert fires["asymmetric_degree"] == 90


def test_entity_override_keeps_volume_floors(tmp_path: Path) -> None:
    """The override answers identity, not statistics: a column below the
    entity volume floors stays out even when forced."""

    rows = [f"{i % 3},act{i % 7},{i}" for i in range(120)]  # svc: 3 distinct
    loaded = load(
        _write_csv(tmp_path / "tiny.csv", "svc,act,val", rows),
        entity_columns=("svc",),
    )
    entity, endpoints = _selection(loaded)
    assert "svc" not in entity  # distinct 3 < ENTITY_MIN_DISTINCT
    assert "svc" not in endpoints  # distinct 3 <= ACTOR_MIN_DISTINCT


def test_raw_path_demoted_by_grammar_by_default(tmp_path: Path) -> None:
    loaded = load(_weblog(tmp_path / "web.csv"))
    entity, endpoints = _selection(loaded)
    assert "path" not in entity
    assert "path" not in endpoints
    assert entity == ["session_id"]
    assert endpoints == ["session_id"]


def test_is_path_shaped_examples() -> None:
    assert _is_path_shaped(["/", "/cart", "/products/42"])
    assert not _is_path_shaped(["10.0.0.1", "10.0.0.2"])
    assert not _is_path_shaped(["sess_1000", "sess_1001"])
    assert not _is_path_shaped([])


def test_content_override_excludes_column(tmp_path: Path) -> None:
    """Forcing content excludes a column that inference would admit."""

    loaded = load(_weblog(tmp_path / "web.csv"), content_columns=("session_id",))
    entity, endpoints = _selection(loaded)
    assert entity == []
    assert endpoints == []


def test_entity_override_outranks_grammar_demotion(tmp_path: Path) -> None:
    loaded = load(_weblog(tmp_path / "web.csv"), entity_columns=("path",))
    entity, endpoints = _selection(loaded)
    assert "path" in entity
    assert "path" in endpoints


def test_unknown_override_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown entity-column"):
        load(_weblog(tmp_path / "web.csv"), entity_columns=("nope",))


def test_conflicting_overrides_raise(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="both entity and content"):
        load(
            _weblog(tmp_path / "web.csv"),
            entity_columns=("path",),
            content_columns=("path",),
        )


def test_cli_flags_reach_pipeline_and_summary(capsys, tmp_path: Path) -> None:
    log = _weblog(tmp_path / "web.csv")
    out = tmp_path / "out"
    exit_code = cli.main(
        [
            "run",
            "--input",
            str(log),
            "--output-dir",
            str(out),
            "--entity-column",
            "session_id",
            "--content-column",
            "path",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    summary = json.loads(out[out.index("{") :])  # skip the human summary line
    assert summary["entity_column_overrides"] == ["session_id"]
    assert summary["content_column_overrides"] == ["path"]


def test_cli_reports_bad_override_as_user_error(capsys, tmp_path: Path) -> None:
    log = _weblog(tmp_path / "web.csv")
    exit_code = cli.main(
        [
            "run",
            "--input",
            str(log),
            "--entity-column",
            "nope",
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 2
    assert "Unknown entity-column" in capsys.readouterr().err

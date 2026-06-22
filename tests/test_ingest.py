"""Tests for the autodetecting log loader and schema inference."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from pandas.api import types as ptypes

from bots_without_labels.ingest import Role, Schema, infer_schema, load, read_table

CLICK_ROWS = [
    "event_id\tevent_time\tregion\tbrowser\tos\turl",
    "evt_1\t2019-12-02 00:00:00\tmars\tchrome\tios\t/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=us",
    "evt_2\t2019-12-02 00:00:00\tvenus\tchrome\tios\t/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=us",
    "evt_3\t2019-12-02 00:00:01\tvenus\tsafari\tandroid\t/ad_click?d=b.com&ttc=3000&q=human%20search&ct=gb",
    "evt_4\t2019-12-02 00:00:02\tmars\tsafari\tandroid\t/ad_click?d=b.com&ttc=2500&q=real%20person&ct=gb",
]


def _write(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_load_click_tsv_detects_roles(tmp_path: Path) -> None:
    log = load(_write(tmp_path / "clicks.tsv", CLICK_ROWS))

    assert log.schema.source_format == "tsv"
    assert log.schema.n_rows == 4
    assert log.schema.primary_timestamp == "event_time"
    assert log.schema.row_id == "event_id"
    assert log.schema.role_of("event_id") == Role.IDENTIFIER
    assert log.schema.role_of("event_time") == Role.TIMESTAMP
    assert log.schema.role_of("region") == Role.CATEGORICAL
    assert log.schema.role_of("url") == Role.URL
    assert "url" in log.schema.url_columns


def test_url_expansion_creates_typed_param_columns(tmp_path: Path) -> None:
    log = load(_write(tmp_path / "clicks.tsv", CLICK_ROWS))
    frame, schema = log.frame, log.schema

    # Query params became columns, and the path became its own column.
    assert "url__ttc" in frame.columns
    assert "url__q" in frame.columns
    assert "url__d" in frame.columns
    assert "url__path" in frame.columns

    assert schema.column("url__ttc").derived_from == "url"
    assert schema.role_of("url__ttc") == Role.NUMERIC
    assert schema.column("url__ttc").numeric_subtype == "int"
    assert ptypes.is_numeric_dtype(frame["url__ttc"])
    assert frame["url__ttc"].tolist() == [10, 10, 3000, 2500]

    # URL-encoded query values are decoded on the way in.
    assert frame["url__q"].tolist() == ["foo bar", "foo bar", "human search", "real person"]


def test_typed_frame_dtypes(tmp_path: Path) -> None:
    log = load(_write(tmp_path / "clicks.tsv", CLICK_ROWS))
    frame = log.frame
    assert ptypes.is_datetime64_any_dtype(frame["event_time"])
    assert frame["event_time"].iloc[0] == pd.Timestamp("2019-12-02 00:00:00")
    assert frame["region"].dtype == "string"


def test_csv_with_numeric_boolean_and_missing(tmp_path: Path) -> None:
    rows = [
        "user,age,active,country",
        "u1,34,true,us",
        "u2,28,false,gb",
        "u3,,true,us",
        "u4,41,false,",
    ]
    log = load(_write(tmp_path / "users.csv", rows))
    schema, frame = log.schema, log.frame

    assert schema.source_format == "csv"
    assert schema.role_of("age") == Role.NUMERIC
    assert schema.role_of("active") == Role.BOOLEAN
    assert schema.role_of("country") == Role.CATEGORICAL
    assert frame["active"].dtype == "boolean"
    assert frame["active"].tolist() == [True, False, True, False]
    # Missing cells are recorded and represented as NA in the typed frame.
    assert schema.column("age").n_missing == 1
    assert pd.isna(frame["age"].iloc[2])
    assert pd.isna(frame["country"].iloc[3])


def test_csv_without_header_gets_positional_names(tmp_path: Path) -> None:
    rows = ["1,2,3", "4,5,6", "7,8,9", "10,11,12"]
    frame, source_format = read_table(_write(tmp_path / "nohdr.csv", rows))
    assert source_format == "csv"
    assert list(frame.columns) == ["col0", "col1", "col2"]
    assert frame.shape == (4, 3)


def test_jsonl_flattens_nested_keys(tmp_path: Path) -> None:
    records = [
        {"ts": "2020-01-01 00:00:00", "actor": {"id": "a1"}, "n": 5},
        {"ts": "2020-01-01 00:00:01", "actor": {"id": "a2"}, "n": 9},
        {"ts": "2020-01-01 00:00:02", "actor": {"id": "a1"}, "n": 2},
    ]
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    log = load(path)
    assert log.schema.source_format == "jsonl"
    assert "actor.id" in log.frame.columns
    assert log.schema.role_of("ts") == Role.TIMESTAMP
    assert log.schema.role_of("n") == Role.NUMERIC


def test_json_array_and_wrapper_object(tmp_path: Path) -> None:
    records = [{"a": "x", "v": 1}, {"a": "y", "v": 2}, {"a": "x", "v": 3}]

    array_path = tmp_path / "arr.json"
    array_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    array_log = load(array_path)
    assert array_log.schema.source_format == "json"
    assert array_log.schema.n_rows == 3

    wrapper_path = tmp_path / "wrap.json"
    wrapper_path.write_text(json.dumps({"events": records}), encoding="utf-8")
    wrapper_log = load(wrapper_path)
    assert wrapper_log.schema.n_rows == 3
    assert "v" in wrapper_log.frame.columns


def test_expand_urls_can_be_disabled(tmp_path: Path) -> None:
    log = load(_write(tmp_path / "clicks.tsv", CLICK_ROWS), expand_urls=False)
    assert not any(col.startswith("url__") for col in log.frame.columns)
    assert log.schema.role_of("url") == Role.URL


def test_schema_serialisation_roundtrips(tmp_path: Path) -> None:
    log = load(_write(tmp_path / "clicks.tsv", CLICK_ROWS))
    payload = log.schema.to_dict()
    assert json.loads(json.dumps(payload))  # JSON-serialisable
    assert isinstance(log.schema.describe(), str)
    assert "event_time" in log.schema.describe()

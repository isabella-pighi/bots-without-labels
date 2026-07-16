"""Input-parsing breadth (roadmap item 4): gzip inputs, broader timestamp
formats, and the default-off ``--timestamp-column`` override.

All fixtures are hermetic (written under ``tmp_path``); nothing here touches
real captures or changes default behaviour for uncompressed inputs.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from bots_without_labels import cli
from bots_without_labels.ingest import Role, load

CSV_TEXT = (
    "ts,user,val\n"
    "2026-07-16 10:00:00,alice,1\n"
    "2026-07-16 10:00:05,bob,2\n"
    "2026-07-16 10:00:09,cara,3\n"
)


def _write_gz(path: Path, text: str) -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(text)
    return path


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# --- gzip-compressed inputs ---------------------------------------------------


def test_gzip_csv_loads_like_plain_csv(tmp_path: Path) -> None:
    plain = load(_write(tmp_path / "log.csv", CSV_TEXT))
    packed = load(_write_gz(tmp_path / "log.csv.gz", CSV_TEXT))
    assert packed.schema.source_format == "csv"
    assert packed.schema.to_dict()["columns"] == plain.schema.to_dict()["columns"]
    assert packed.frame.equals(plain.frame)


def test_gzip_tsv_json_jsonl_load(tmp_path: Path) -> None:
    tsv = _write_gz(tmp_path / "log.tsv.gz", CSV_TEXT.replace(",", "\t"))
    assert load(tsv).schema.source_format == "tsv"

    records = [
        {"ts": f"2026-07-16 10:00:0{i}", "user": "u", "val": i} for i in range(3)
    ]
    jsonl = _write_gz(
        tmp_path / "log.jsonl.gz", "\n".join(json.dumps(r) for r in records)
    )
    assert load(jsonl).schema.source_format == "jsonl"
    assert load(jsonl).schema.n_rows == 3

    array = _write_gz(tmp_path / "log.json.gz", json.dumps(records))
    assert load(array).schema.source_format == "json"
    assert load(array).schema.n_rows == 3


def test_gzip_detected_by_content_not_name(tmp_path: Path) -> None:
    """A gzipped file without a .gz suffix still loads (magic-byte check)."""

    log = load(_write_gz(tmp_path / "log.csv", CSV_TEXT))
    assert log.schema.source_format == "csv"
    assert log.schema.role_of("ts") == Role.TIMESTAMP


def test_empty_gzip_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        load(_write_gz(tmp_path / "empty.csv.gz", ""))


# --- broadened timestamp formats ---------------------------------------------


@pytest.mark.parametrize(
    ("values", "expected_format"),
    [
        (
            [
                "10/Oct/2000:13:55:36 -0700",
                "11/Oct/2000:14:55:36 -0700",
                "12/Oct/2000:15:55:36 -0700",
            ],
            "%d/%b/%Y:%H:%M:%S %z",
        ),
        (
            ["10/Oct/2000:13:55:36", "11/Oct/2000:14:55:36", "12/Oct/2000:15:55:36"],
            "%d/%b/%Y:%H:%M:%S",
        ),
        (
            [
                "2011/08/10 09:46:53.047277",
                "2011/08/10 09:46:54.147277",
                "2011/08/10 09:46:55.247277",
            ],
            "%Y/%m/%d %H:%M:%S.%f",
        ),
        (
            [
                "2026-07-16T10:00:00.123",
                "2026-07-16T10:00:01.456",
                "2026-07-16T10:00:02.789",
            ],
            "%Y-%m-%dT%H:%M:%S.%f",
        ),
        (
            ["10.07.2026 12:00:00", "11.07.2026 12:00:01", "12.07.2026 12:00:02"],
            "%d.%m.%Y %H:%M:%S",
        ),
    ],
)
def test_broadened_formats_detected(
    tmp_path: Path, values: list[str], expected_format: str
) -> None:
    path = _write(
        tmp_path / "t.csv",
        "t,x\n" + "\n".join(f"{v},{i}" for i, v in enumerate(values)) + "\n",
    )
    col = load(path).schema.column("t")
    assert col.role == Role.TIMESTAMP
    assert col.datetime_format == expected_format


def test_pure_number_column_stays_non_timestamp(tmp_path: Path) -> None:
    """Epoch-like pure digits must never autodetect as a timestamp."""

    path = _write(
        tmp_path / "epoch.csv",
        "t,x\n1300123456,1\n1300123457,2\n1300123458,3\n",
    )
    schema = load(path).schema
    assert schema.role_of("t") == Role.NUMERIC
    assert schema.primary_timestamp is None


# --- the --timestamp-column override -------------------------------------------


TWO_TS_TEXT = (
    "created,event_time,x\n"
    "2026-01-01 00:00:00,2026-07-16 10:00:00,1\n"
    "2026-01-02 00:00:00,2026-07-16 10:00:05,2\n"
)


def test_timestamp_override_wins_primary_post(tmp_path: Path) -> None:
    path = _write(tmp_path / "two.csv", TWO_TS_TEXT)
    assert load(path).schema.primary_timestamp == "created"

    forced = load(path, timestamp_column="event_time")
    col = forced.schema.column("event_time")
    assert forced.schema.primary_timestamp == "event_time"
    assert col.role == Role.TIMESTAMP
    assert col.timestamp_override is True
    assert forced.schema.row_id != "event_time"


def test_timestamp_override_requires_parseable_values(tmp_path: Path) -> None:
    path = _write(tmp_path / "two.csv", TWO_TS_TEXT)
    with pytest.raises(ValueError, match="does not parse as datetimes"):
        load(path, timestamp_column="x")


def test_timestamp_override_unknown_and_conflict_raise(tmp_path: Path) -> None:
    path = _write(tmp_path / "two.csv", TWO_TS_TEXT)
    with pytest.raises(ValueError, match="Unknown timestamp-column"):
        load(path, timestamp_column="nope")
    with pytest.raises(ValueError, match="both entity and timestamp"):
        load(path, timestamp_column="event_time", entity_columns=("event_time",))
    with pytest.raises(ValueError, match="both content and timestamp"):
        load(path, timestamp_column="event_time", content_columns=("event_time",))


def test_cli_timestamp_column_reaches_summary(capsys, tmp_path: Path) -> None:
    rows = "\n".join(
        f"2026-01-01 00:00:0{i},2026-07-16 10:00:0{i},{i}" for i in range(6)
    )
    log = _write(tmp_path / "two.csv", "created,event_time,x\n" + rows + "\n")
    exit_code = cli.main(
        [
            "run",
            "--input",
            str(log),
            "--output-dir",
            str(tmp_path / "out"),
            "--timestamp-column",
            "event_time",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    summary = json.loads(out[out.index("{") :])
    assert summary["timestamp_column_override"] == "event_time"
    assert summary["schema"]["primary_timestamp"] == "event_time"


def test_cli_bad_timestamp_column_is_user_error(capsys, tmp_path: Path) -> None:
    log = _write(tmp_path / "two.csv", TWO_TS_TEXT)
    exit_code = cli.main(
        [
            "run",
            "--input",
            str(log),
            "--output-dir",
            str(tmp_path / "out"),
            "--timestamp-column",
            "nope",
        ]
    )
    assert exit_code == 2
    assert "Unknown timestamp-column" in capsys.readouterr().err

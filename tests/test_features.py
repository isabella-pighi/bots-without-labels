"""Tests for schema-driven feature engineering."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from bots_without_labels.features import build_features
from bots_without_labels.ingest import load


def _write_click_log(path: Path) -> Path:
    """A click-like CSV: a 6-event same-second burst, then scattered traffic."""

    header = "id,ts,region,browser,query,ttc"
    rows = [header]
    # Rows 0..5: identical context (us/chrome) and identical second -> a burst.
    for i in range(6):
        rows.append(f"e{i},2020-01-01 00:00:00,us,chrome,search phrase {i},10")
    # Rows 6..79: scattered over later seconds, varied context, mixed ttc.
    regions = ["us", "gb", "de"]
    browsers = ["chrome", "safari"]
    for i in range(6, 80):
        ttc = 10 if i % 2 == 0 else 100 + i
        ts = f"2020-01-01 00:{i // 60:02d}:{i % 60:02d}"
        rows.append(
            f"e{i},{ts},{regions[i % 3]},{browsers[i % 2]},search phrase {i},{ttc}"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_feature_families_present_for_each_role(tmp_path: Path) -> None:
    log = load(_write_click_log(tmp_path / "clicks.csv"))
    fs = build_features(log.frame, log.schema)

    expected = {
        "region__conc",
        "browser__conc",
        "context__conc",
        "query__entropy",
        "query__uniqchar",
        "query__rep",
        "ttc__val",
        "ttc__rep",
        "hour",
        "same_time__conc",
        "burst10s__conc",
        "dt__std",
        "dt__cv",
    }
    assert expected <= set(fs.names)
    # query is high-cardinality free text, so it produced text features.
    assert log.schema.role_of("query") == "text"
    assert fs.families["region__conc"] == "concentration"
    assert fs.families["query__entropy"] == "text"


def test_matrix_shape_and_finiteness(tmp_path: Path) -> None:
    log = load(_write_click_log(tmp_path / "clicks.csv"))
    fs = build_features(log.frame, log.schema)
    assert fs.matrix.shape == (log.schema.n_rows, len(fs.names))
    assert np.isfinite(fs.matrix).all()
    assert list(fs.frame().columns) == fs.names


def test_concentration_equals_log1p_of_count(tmp_path: Path) -> None:
    log = load(_write_click_log(tmp_path / "clicks.csv"))
    fs = build_features(log.frame, log.schema)
    frame = fs.frame()

    region = log.frame["region"].astype(str)
    us_count = int((region == "us").sum())
    us_rows = np.where(region.to_numpy() == "us")[0]
    assert np.allclose(frame["region__conc"].to_numpy()[us_rows], np.log1p(us_count))


def test_burst_and_same_time_detect_the_cluster(tmp_path: Path) -> None:
    log = load(_write_click_log(tmp_path / "clicks.csv"))
    fs = build_features(log.frame, log.schema)
    frame = fs.frame()

    # The first six rows share one second and one categorical context.
    burst = np.expm1(frame["burst10s__conc"].to_numpy()[:6])
    assert np.allclose(burst, 6.0)
    same_time = np.expm1(frame["same_time__conc"].to_numpy()[:6])
    assert np.allclose(same_time, 6.0)


def test_repetition_for_reused_numeric_value(tmp_path: Path) -> None:
    log = load(_write_click_log(tmp_path / "clicks.csv"))
    fs = build_features(log.frame, log.schema)
    frame = fs.frame()

    ttc = log.frame["ttc"].astype(str)
    count_10 = int((ttc == "10").sum())
    ten_rows = np.where(ttc.to_numpy() == "10")[0]
    assert np.allclose(frame["ttc__rep"].to_numpy()[ten_rows], np.log1p(count_10))


def test_build_is_deterministic(tmp_path: Path) -> None:
    log = load(_write_click_log(tmp_path / "clicks.csv"))
    first = build_features(log.frame, log.schema)
    second = build_features(log.frame, log.schema)
    assert first.names == second.names
    assert np.array_equal(first.matrix, second.matrix)


def test_minimal_log_without_timestamp_or_categoricals(tmp_path: Path) -> None:
    path = tmp_path / "amounts.csv"
    path.write_text(
        "amount\n" + "\n".join(str(i % 7) for i in range(40)) + "\n", "utf-8"
    )
    log = load(path)
    fs = build_features(log.frame, log.schema)

    assert "amount__val" in fs.names
    assert "amount__rep" in fs.names
    assert "hour" not in fs.names  # no timestamp
    assert "context__conc" not in fs.names  # fewer than two categoricals
    assert fs.context.timestamp_column is None
    assert fs.matrix.shape == (40, len(fs.names))

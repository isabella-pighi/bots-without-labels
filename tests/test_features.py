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


def test_entity_degree_distinguishes_hub_from_point_to_point(
    tmp_path: Path, network_log_factory
) -> None:
    # The hub / point-to-point / filler structure comes from the shared
    # ``network_log_factory`` fixture (tests/conftest.py).
    log = load(network_log_factory(tmp_path / "net.csv"))
    fs = build_features(log.frame, log.schema)

    assert fs.context.entity_columns == ["src", "dst"]
    assert set(fs.context.entity_degree_by_col) == {"src", "dst"}

    dst = log.frame["dst"].astype(str).to_numpy()
    src = log.frame["src"].astype(str).to_numpy()
    dst_degree = fs.context.entity_degree_by_col["dst"]
    src_degree = fs.context.entity_degree_by_col["src"]

    # The hub destination is reached by four distinct sources (a star).
    hub_rows = np.where(dst == "c2hub")[0]
    assert float(dst_degree[hub_rows][0]) == 4.0
    # The backup->store channel is point-to-point: degree 1 on both ends.
    backup_rows = np.where(src == "backup")[0]
    assert float(src_degree[backup_rows][0]) == 1.0
    store_rows = np.where(dst == "store")[0]
    assert float(dst_degree[store_rows][0]) == 1.0


def _degenerate_vocab_log(path: Path) -> Path:
    """A flow-like CSV with actor IP columns plus a degenerate ``proto`` column.

    ``src``/``dst`` are recurring high-cardinality actors (cardinality ratio
    inside the actor band); ``proto`` is a bounded categorical vocabulary -- 12
    values that recur heavily, so it clears the distinct floor and the
    median-recurrence test, but its cardinality ratio (~12/700) sits *below*
    ``ACTOR_MIN_RATIO``. It stands in for CTU-13 ``Proto``/``State``.
    """

    protos = [f"proto{i}" for i in range(12)]
    header = "src,dst,proto,payload"
    rows = [header]
    for s in range(50):
        for r in range(14):  # 700 rows: 50 src actors x 14 events
            d = (s + r) % 50
            proto = protos[(s + r) % 12]
            payload = (s * 13 + r * 7) % 97
            rows.append(f"s{s},d{d},{proto},{payload}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_entity_columns_exclude_degenerate_low_cardinality_categorical(
    tmp_path: Path,
) -> None:
    # The cardinality-ratio band keeps a bounded vocabulary (``proto``) out of the
    # per-entity baseline while retaining the actor-like IP columns -- the fix that
    # stops entity_monotony over-flagging on CTU-13 Proto/State. ``proto`` is
    # excluded *only* by the band: it clears the distinct floor (12 >= 10) and the
    # median-recurrence test, so a vacuous pass is ruled out.
    log = load(_degenerate_vocab_log(tmp_path / "flows.csv"))
    fs = build_features(log.frame, log.schema)

    assert "proto" not in fs.context.entity_columns
    assert "src" in fs.context.entity_columns
    assert "dst" in fs.context.entity_columns


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


def test_actor_endpoints_detected_excluding_context(
    tmp_path: Path, broadcaster_log_factory
) -> None:
    log = load(broadcaster_log_factory(tmp_path / "bcast.csv"))
    fs = build_features(log.frame, log.schema)

    # The two address columns are actor endpoints; the bounded service vocabulary
    # is context, never an actor node.
    assert fs.context.actor_columns == ["src", "dst"]
    assert "svc" not in fs.context.actor_columns


def test_actor_graph_role_degrees(tmp_path: Path, broadcaster_log_factory) -> None:
    log = load(broadcaster_log_factory(tmp_path / "bcast.csv"))
    fs = build_features(log.frame, log.schema)
    ctx = fs.context
    src = log.frame["src"].astype(str).to_numpy()

    bot_rows = np.where(src == "10.0.0.1")[0]
    client_rows = np.where(src == "10.0.1.0")[0]

    # Source star: degree 90 in its role, reached by none in the reverse role,
    # monotone service.
    assert float(ctx.actor_degree_by_col["src"][bot_rows][0]) == 90.0
    assert float(ctx.actor_reverse_degree_by_col["src"][bot_rows][0]) == 0.0
    assert float(ctx.actor_ctx_diversity_by_col["src"][bot_rows][0]) == 0.0
    # Benign client: talks to a single server (point-to-point degree of 1).
    assert float(ctx.actor_degree_by_col["src"][client_rows][0]) == 1.0


def test_actor_graph_dormant_on_click_log(tmp_path: Path) -> None:
    # A click log has no two recurring high-cardinality endpoint columns, so the
    # actor graph stays dormant (region/browser are bounded context; query is
    # near-unique free text).
    log = load(_write_click_log(tmp_path / "clicks.csv"))
    fs = build_features(log.frame, log.schema)
    assert len(fs.context.actor_columns) < 2
    assert not fs.context.actor_degree_by_col

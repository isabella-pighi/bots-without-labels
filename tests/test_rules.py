"""Tests for the explainable rule detector."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from bots_without_labels.features import build_features
from bots_without_labels.ingest import load
from bots_without_labels.rules import apply_rules
from bots_without_labels.synthetic import (
    ARCHETYPES,
    DETECTABLE_ARCHETYPES,
    generate,
    write_log,
)


def _scored(tmp_path: Path):
    log = generate(n_legit=600, n_bots=80, seed=4)
    path = tmp_path / "syn.tsv"
    write_log(path, log.frame)
    loaded = load(path)
    feature_set = build_features(loaded.frame, loaded.schema)
    result = apply_rules(loaded.frame, loaded.schema, feature_set)
    return log, result


def test_scores_are_bounded(tmp_path: Path) -> None:
    _, result = _scored(tmp_path)
    assert result.scores.min() >= 0.0
    assert result.scores.max() <= 1.0


def test_detectable_archetypes_clear_the_cutoff(tmp_path: Path) -> None:
    """The timing archetypes clear the heuristic cutoff; the deliberately hard
    ones stay below it.

    ``diffuse_replay`` and ``stealth`` are designed to be indistinguishable from
    popular or human traffic without labels, so their staying below the cutoff is
    the honest, expected result -- not a regression.
    """
    log, result = _scored(tmp_path)
    archetypes = np.array([str(a) for a in log.archetype], dtype=object)
    for name in DETECTABLE_ARCHETYPES:
        rows = np.where(archetypes == name)[0]
        median = float(np.median(result.scores[rows]))
        assert median >= 0.70, f"{name} median heuristic {median:.2f} below cutoff"
    for name in (a for a in ARCHETYPES if a not in DETECTABLE_ARCHETYPES):
        rows = np.where(archetypes == name)[0]
        median = float(np.median(result.scores[rows]))
        assert (
            median < 0.70
        ), f"{name} median heuristic {median:.2f} should stay below cutoff"


def test_legitimate_traffic_scores_low(tmp_path: Path) -> None:
    log, result = _scored(tmp_path)
    legit = np.where(np.array([a is None for a in log.archetype]))[0]
    assert float(np.median(result.scores[legit])) < 0.70
    assert float((result.scores[legit] >= 0.70).mean()) < 0.05


def test_flagged_rows_carry_reasons(tmp_path: Path) -> None:
    _, result = _scored(tmp_path)
    reasons = result.reasons()
    for row in range(len(result.scores)):
        if result.scores[row] >= 0.70:
            assert reasons[row], "a flagged row must have at least one reason"


def _network_log(path: Path, *, n_fill: int = 40) -> Path:
    """A flow-like CSV with a hub, a point-to-point channel, and filler traffic.

    See ``tests.test_features._network_log`` for the structure; both behaviours
    are exercised here through the rule detector.
    """

    n_pay = 12
    header = "src,dst," + ",".join(f"p{i}" for i in range(n_pay))
    rows = [header]
    zero = ",".join(["0"] * n_pay)
    for source in range(4):
        for _ in range(8):
            rows.append(f"s{source},c2hub,{zero}")
        for j in range(10):
            payload = ",".join(str(j * n_fill * 13 + source + k * 101) for k in range(n_pay))
            rows.append(f"s{source},benign{j % 5},{payload}")
    for _ in range(20):
        rows.append(f"backup,store,{zero}")
    for host in range(n_fill):
        for j in range(12):
            payload = ",".join(str(j * n_fill * 13 + host + k * 101) for k in range(n_pay))
            rows.append(f"f{host},fd{host},{payload}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _fired(result, rule_id, rows):
    return np.array(
        [any(hit.rule_id == rule_id for hit in result.hits[row]) for row in rows]
    )


def test_entity_monotony_escalates_only_for_a_hub(tmp_path: Path) -> None:
    """With a source/destination structure, a monotonous entity escalates only
    when it is a relational hub. A monotonous *point-to-point* channel -- equally
    low-diversity but with a single counterpart -- must stay below the cutoff."""

    log = load(_network_log(tmp_path / "net.csv"))
    feature_set = build_features(log.frame, log.schema)
    result = apply_rules(log.frame, log.schema, feature_set)

    assert result.thresholds["entity_graph_active"] is True
    assert result.thresholds["min_hub_degree"] == 3

    dst = log.frame["dst"].astype(str).to_numpy()
    src = log.frame["src"].astype(str).to_numpy()

    hub_rows = np.where(dst == "c2hub")[0]
    assert _fired(result, "entity_monotony", hub_rows).all()
    assert (result.scores[hub_rows] >= 0.70).all()
    hub_reason = next(
        hit.reason
        for hit in result.hits[hub_rows[0]]
        if hit.rule_id == "entity_monotony"
    )
    assert "counterpart" in hub_reason  # the explanation cites the fan-in

    channel_rows = np.where((src == "backup") & (dst == "store"))[0]
    assert not _fired(result, "entity_monotony", channel_rows).any()
    assert (result.scores[channel_rows] < 0.70).all()


def test_entity_monotony_falls_back_without_relational_structure(
    tmp_path: Path,
) -> None:
    """With a single entity column there is no source/hub structure to read, so
    the hub gate is dormant and the rule fires on monotony alone."""

    rows = ["actor,action,size"]
    for _ in range(30):
        rows.append("botactor,beacon,1")
    actions = ["get", "post", "put", "del"]
    for i in range(12):
        for j in range(6):
            rows.append(f"user{i},{actions[(i + j) % 4]},{(i * 7 + j * 13) % 50}")
    path = tmp_path / "single.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    log = load(path)
    feature_set = build_features(log.frame, log.schema)
    result = apply_rules(log.frame, log.schema, feature_set)

    assert result.thresholds["entity_graph_active"] is False
    assert result.thresholds["min_hub_degree"] is None

    actor = log.frame["actor"].astype(str).to_numpy()
    bot_rows = np.where(actor == "botactor")[0]
    assert _fired(result, "entity_monotony", bot_rows).all()
    assert (result.scores[bot_rows] >= 0.70).all()


def _timing_result(tmp_path: Path, timestamps: list[str], name: str):
    """Score a busy single-context burst at a chosen timestamp granularity.

    Every row shares one categorical context so the burst/same-instant rules see
    a dense pile; only the timestamp spacing differs between callers, which is
    exactly what the dense-timing resolution gate keys on.
    """

    header = "ts,channel,amount"
    rows = [header]
    for stamp in timestamps:
        rows.append(f"{stamp},A,1.0")
    path = tmp_path / f"{name}.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    loaded = load(path)
    feature_set = build_features(loaded.frame, loaded.schema)
    return apply_rules(loaded.frame, loaded.schema, feature_set)


def _rule_ids(result) -> set[str]:
    return {hit.rule_id for row in result.hits for hit in row}


def test_dense_timing_fires_at_fine_resolution(tmp_path: Path) -> None:
    """At sub-second resolution a same-instant pile and a local burst are genuine
    simultaneity, so both dense-timing rules fire."""

    instants = [
        "2020-01-01 00:00:00.000",
        "2020-01-01 00:00:00.500",
        "2020-01-01 00:00:01.000",
        "2020-01-01 00:00:01.500",
        "2020-01-01 00:00:02.000",
        "2020-01-01 00:00:02.500",
    ]
    timestamps = [stamp for stamp in instants for _ in range(8)]
    result = _timing_result(tmp_path, timestamps, "fine")

    assert result.thresholds["dense_timing_active"] is True
    assert result.thresholds["timestamp_resolution"] < 10.0
    fired = _rule_ids(result)
    assert "same_instant_burst" in fired
    assert "local_burst" in fired


def test_dense_timing_suppressed_at_coarse_resolution(tmp_path: Path) -> None:
    """The identical pile snapped to a minute grid -- a 60s clock, coarser than
    the 10s burst window -- is binning, not simultaneity, so both dense-timing
    rules are gated off and carry no evidence."""

    minutes = [
        "2020-01-01 00:00:00",
        "2020-01-01 00:01:00",
        "2020-01-01 00:02:00",
        "2020-01-01 00:03:00",
        "2020-01-01 00:04:00",
        "2020-01-01 00:05:00",
    ]
    timestamps = [stamp for stamp in minutes for _ in range(8)]
    result = _timing_result(tmp_path, timestamps, "coarse")

    assert result.thresholds["dense_timing_active"] is False
    assert result.thresholds["timestamp_resolution"] >= 10.0
    fired = _rule_ids(result)
    assert "same_instant_burst" not in fired
    assert "local_burst" not in fired


def test_dense_timing_resolution_is_robust_to_one_small_gap(tmp_path: Path) -> None:
    """A single jittered, off-grid timestamp on an otherwise minute-binned clock
    must not flip the source to fine-resolution: the median positive gap stays at
    60s, so the gate still suppresses the dense-timing rules."""

    minutes = [f"2020-01-01 00:{m:02d}:00" for m in range(20)]
    timestamps = [stamp for stamp in minutes for _ in range(8)]
    # One stray row a half-second after the first minute -- the only sub-10s gap,
    # a lone clock glitch among 19 clean 60s gaps. A low percentile ignores this
    # sparse tail of jitter, so the clock still reads ~60s and the gate holds.
    timestamps.append("2020-01-01 00:00:00.500")
    result = _timing_result(tmp_path, timestamps, "jittered")

    assert result.thresholds["dense_timing_active"] is False
    assert result.thresholds["timestamp_resolution"] >= 10.0
    fired = _rule_ids(result)
    assert "same_instant_burst" not in fired
    assert "local_burst" not in fired

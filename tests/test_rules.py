"""Tests for the explainable rule detector."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from bots_without_labels.features import build_features
from bots_without_labels.ingest import load
from bots_without_labels.pipeline import HEURISTIC_CUTOFF

# The private imports are deliberate: the symmetric-peer case is a unit test of
# the rule internals on a hand-built context.
from bots_without_labels.rules import _asymmetric_endpoint, _degree_floor, apply_rules
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
        assert (
            median >= HEURISTIC_CUTOFF
        ), f"{name} median heuristic {median:.2f} below cutoff"
    for name in (a for a in ARCHETYPES if a not in DETECTABLE_ARCHETYPES):
        rows = np.where(archetypes == name)[0]
        median = float(np.median(result.scores[rows]))
        assert (
            median < HEURISTIC_CUTOFF
        ), f"{name} median heuristic {median:.2f} should stay below cutoff"


def test_legitimate_traffic_scores_low(tmp_path: Path) -> None:
    log, result = _scored(tmp_path)
    legit = np.where(np.array([a is None for a in log.archetype]))[0]
    assert float(np.median(result.scores[legit])) < HEURISTIC_CUTOFF
    assert float((result.scores[legit] >= HEURISTIC_CUTOFF).mean()) < 0.05


def test_flagged_rows_carry_reasons(tmp_path: Path) -> None:
    _, result = _scored(tmp_path)
    reasons = result.reasons()
    for row, score in enumerate(result.scores):
        if score >= HEURISTIC_CUTOFF:
            assert reasons[row], "a flagged row must have at least one reason"


def _fired(result, rule_id, rows):
    """Per-row boolean array: did ``rule_id`` fire on each of ``rows``?"""
    return np.array(
        [any(hit.rule_id == rule_id for hit in result.hits[row]) for row in rows]
    )


def test_entity_monotony_escalates_only_for_a_hub(
    tmp_path: Path, network_log_factory
) -> None:
    """With a source/destination structure, a monotonous entity escalates only
    when it is a relational hub. A monotonous *point-to-point* channel -- equally
    low-diversity but with a single counterpart -- must stay below the cutoff."""

    log = load(network_log_factory(tmp_path / "net.csv"))
    feature_set = build_features(log.frame, log.schema)
    result = apply_rules(log.frame, log.schema, feature_set)

    assert result.thresholds["entity_graph_active"] is True
    assert result.thresholds["min_hub_degree"] == 3

    dst = log.frame["dst"].astype(str).to_numpy()
    src = log.frame["src"].astype(str).to_numpy()

    hub_rows = np.where(dst == "10.0.0.9")[0]
    assert _fired(result, "entity_monotony", hub_rows).all()
    assert (result.scores[hub_rows] >= HEURISTIC_CUTOFF).all()
    hub_reason = next(
        hit.reason
        for hit in result.hits[hub_rows[0]]
        if hit.rule_id == "entity_monotony"
    )
    assert "counterpart" in hub_reason  # the explanation cites the fan-in

    channel_rows = np.where((src == "10.0.1.1") & (dst == "10.0.1.2"))[0]
    assert not _fired(result, "entity_monotony", channel_rows).any()
    assert (result.scores[channel_rows] < HEURISTIC_CUTOFF).all()


def test_entity_monotony_falls_back_without_relational_structure(
    tmp_path: Path,
) -> None:
    """With a single entity column there is no source/hub structure to read, so
    the hub gate is dormant and the rule fires on monotony alone."""

    # IP-shaped actor tokens so the scale-invariant shape test admits the column
    # as an actor pool (a single entity column, so no relational hub structure).
    bot = "192.168.0.99"
    rows = ["actor,action,size"]
    for _ in range(30):
        rows.append(f"{bot},beacon,1")
    actions = ["get", "post", "put", "del"]
    for i in range(12):
        for j in range(6):
            rows.append(f"192.168.1.{i},{actions[(i + j) % 4]},{(i * 7 + j * 13) % 50}")
    path = tmp_path / "single.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    log = load(path)
    feature_set = build_features(log.frame, log.schema)
    result = apply_rules(log.frame, log.schema, feature_set)

    assert result.thresholds["entity_graph_active"] is False
    assert result.thresholds["min_hub_degree"] is None
    # No actor graph covers the single entity column, so the fallback stays
    # bare (no counterpart structure is derivable from this log).
    assert result.thresholds["entity_fallback_hub_gated"] is False

    actor = log.frame["actor"].astype(str).to_numpy()
    bot_rows = np.where(actor == bot)[0]
    assert _fired(result, "entity_monotony", bot_rows).all()
    assert (result.scores[bot_rows] >= HEURISTIC_CUTOFF).all()


def test_fallback_hub_gate_uses_actor_degrees_when_derivable(
    tmp_path: Path,
) -> None:
    """With ONE entity column but an active actor graph covering it, the
    monotony fallback re-applies the structural hub gate through actor
    counterpart degrees: a monotone point-to-point channel (degree below
    MIN_HUB_DEGREE) no longer fires, while an equally monotone hub entity
    (converging from several distinct sources) still does."""

    rows = ["src,dst,action,size"]
    # Monotone point-to-point channel: one src <-> one dst (counterpart degree 1).
    for _ in range(15):
        rows.append("10.0.1.1,10.0.1.2,sync,7")
    # Monotone hub: one dst converging from 4 distinct sources (degree 4),
    # dominated by one source so its behaviour stays low-diversity.
    for _ in range(17):
        rows.append("172.16.0.1,10.9.9.9,beacon,1")
    for k in (2, 3, 4):
        rows.append(f"172.16.0.{k},10.9.9.9,beacon,1")
    # Busy diverse destinations: qualified volume, varied behaviour. Sources
    # are drawn from a small busy pool so `src` passes the actor repeat-mass
    # test while its median value stays a one-off -- `src` must be an actor
    # endpoint but NOT an entity column, or the entity graph itself activates.
    actions = ["get", "post", "put", "del"]
    for i in range(20):
        for j in range(12):
            rows.append(
                f"10.5.0.{j % 8},10.0.2.{i},{actions[(i + j) % 4]},{(i * 7 + j) % 9}"
            )
    for i in range(10):
        for j in range(13):
            rows.append(f"10.6.{i}.{j},10.0.3.{i},{actions[j % 2]},{j % 3}")
    # Low-volume tail so the dst distinct count clears the actor minimum.
    for i in range(25):
        rows.append(f"10.7.{i}.1,10.0.4.{i},{actions[i % 4]},{i % 9}")
        rows.append(f"10.7.{i}.2,10.0.4.{i},{actions[(i + 1) % 4]},{(i + 3) % 9}")
    path = tmp_path / "fallback_hub.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    log = load(path)
    feature_set = build_features(log.frame, log.schema)
    result = apply_rules(log.frame, log.schema, feature_set)

    # Regime under test: exactly one entity column, actor graph active over it.
    assert result.thresholds["entity_columns"] == ["dst"]
    assert result.thresholds["entity_graph_active"] is False
    assert result.thresholds["entity_fallback_hub_gated"] is True
    assert result.thresholds["min_hub_degree"] == 3
    assert "dst" in result.thresholds["actor_columns"]

    dst = log.frame["dst"].astype(str).to_numpy()
    hub_rows = np.where(dst == "10.9.9.9")[0]
    assert _fired(result, "entity_monotony", hub_rows).all()
    assert (result.scores[hub_rows] >= HEURISTIC_CUTOFF).all()
    hub_reason = next(
        hit.reason
        for hit in result.hits[hub_rows[0]]
        if hit.rule_id == "entity_monotony"
    )
    assert "counterpart" in hub_reason  # the explanation cites the convergence

    channel_rows = np.where(dst == "10.0.1.2")[0]
    assert not _fired(result, "entity_monotony", channel_rows).any()
    assert (result.scores[channel_rows] < HEURISTIC_CUTOFF).all()


def _timing_result(tmp_path: Path, timestamps: list[str], name: str):
    """Score a busy single-context pile at a chosen timestamp granularity.

    Every row shares one categorical context so the burst/same-instant rules see
    a dense pile; only the timestamp spacing differs between callers, which is
    exactly what the per-collision grid gate keys on: a same-instant pile fires
    when its timestamp is off the coarse grid and is suppressed when it sits on
    the grid (a binning artifact).
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
    """All rule IDs that fired on any row of the result."""
    return {hit.rule_id for row in result.hits for hit in row}


def test_dense_timing_fires_at_fine_resolution(tmp_path: Path) -> None:
    """At sub-second resolution the grid is finer than the burst window, so no
    collision is treated as binning: a same-instant pile and a local burst are
    genuine simultaneity and both dense-timing rules fire."""

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

    assert result.thresholds["dense_timing_gated"] is False
    assert result.thresholds["timestamp_grid"] < 10.0
    fired = _rule_ids(result)
    assert "same_instant_burst" in fired
    assert "local_burst" in fired


def test_dense_timing_suppressed_for_on_grid_coarse_bins(tmp_path: Path) -> None:
    """Identical piles snapped to a minute grid -- a 60s clock coarser than the
    10s burst window, every pile on-grid -- are binning, not simultaneity, so
    both dense-timing rules are suppressed on every row and carry no evidence."""

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

    assert result.thresholds["dense_timing_gated"] is True
    assert result.thresholds["timestamp_grid"] >= 10.0
    fired = _rule_ids(result)
    assert "same_instant_burst" not in fired
    assert "local_burst" not in fired


def test_dense_timing_fires_for_off_grid_pile_on_coarse_clock(tmp_path: Path) -> None:
    """A genuine same-instant pile at an *off-grid* instant on an otherwise
    minute-binned clock is simultaneity the clock recorded precisely, not a bin,
    so both dense-timing rules still fire on it -- while the on-grid minute piles
    around it stay suppressed. This is the case the old global gate wrongly hid."""

    minutes = [f"2020-01-01 00:{m:02d}:00" for m in range(20)]
    timestamps = [stamp for stamp in minutes for _ in range(8)]
    on_grid_count = len(timestamps)
    # Eight events at one sub-minute instant (:17), well clear of any minute mark.
    off_grid_pile = ["2020-01-01 00:30:17"] * 8
    timestamps.extend(off_grid_pile)
    result = _timing_result(tmp_path, timestamps, "offgrid")

    assert result.thresholds["dense_timing_gated"] is True
    assert result.thresholds["timestamp_grid"] == 60.0

    pile_rows = range(on_grid_count, on_grid_count + len(off_grid_pile))
    assert _fired(result, "same_instant_burst", pile_rows).all()
    assert _fired(result, "local_burst", pile_rows).all()

    on_grid_rows = range(on_grid_count)
    assert not _fired(result, "same_instant_burst", on_grid_rows).any()
    assert not _fired(result, "local_burst", on_grid_rows).any()


def test_dense_timing_suppressed_for_phase_offset_coarse_bins(tmp_path: Path) -> None:
    """Minute bins at a fixed ``:30`` phase offset are just as much a 60s coarse
    grid as bins at ``:00`` -- the clock is simply not epoch-aligned. Every pile
    sits on the grid's dominant phase, so both dense-timing rules are suppressed;
    epoch-anchored alignment would have wrongly fired on all of them."""

    minutes = [f"2020-01-01 00:{m:02d}:30" for m in range(8)]
    timestamps = [stamp for stamp in minutes for _ in range(8)]
    result = _timing_result(tmp_path, timestamps, "offset")

    assert result.thresholds["dense_timing_gated"] is True
    assert result.thresholds["timestamp_grid"] == 60.0
    fired = _rule_ids(result)
    assert "same_instant_burst" not in fired
    assert "local_burst" not in fired


def test_dense_timing_grid_is_robust_to_one_small_gap(tmp_path: Path) -> None:
    """A single jittered, off-grid timestamp on an otherwise minute-binned clock
    must not move the detected grid: the *mode* positive gap stays at 60s, so the
    on-grid minute piles are still recognised as bins and suppressed."""

    minutes = [f"2020-01-01 00:{m:02d}:00" for m in range(20)]
    timestamps = [stamp for stamp in minutes for _ in range(8)]
    on_grid_count = len(timestamps)
    # One stray row a half-second after the first minute -- a lone clock glitch
    # among 19 clean 60s gaps. The mode gap ignores this rare value, so the grid
    # still reads 60s and the on-grid bins stay suppressed.
    timestamps.append("2020-01-01 00:00:00.500")
    result = _timing_result(tmp_path, timestamps, "jittered")

    assert result.thresholds["dense_timing_gated"] is True
    assert result.thresholds["timestamp_grid"] == 60.0
    on_grid_rows = range(on_grid_count)
    assert not _fired(result, "same_instant_burst", on_grid_rows).any()
    assert not _fired(result, "local_burst", on_grid_rows).any()


def _passive_fanin_log(path: Path) -> Path:
    """A passive fan-IN hub: many distinct clients reach one server on a monotone
    service, and the server never appears as a source. The asymmetry is identical
    in shape to the source-broadcaster (one role high-degree, the other near-zero),
    only the direction differs -- which the undirected graph cannot tell apart.

    Point-to-point background gives both address columns enough distinct, recurring
    values to qualify as endpoints (the hub alone would be a single dst value)."""

    rows = ["src,dst,svc"]
    # Fan-in hub: 60 distinct clients each send 12 flows to one server, one service.
    for c in range(60):
        for _ in range(12):
            rows.append(f"10.0.2.{c},10.0.0.9,smtp")
    # Background point-to-point: 60 source->dest pairs, 12 flows each, so dst has
    # >50 distinct recurring values and src is a valid endpoint too.
    for k in range(60):
        for _ in range(12):
            rows.append(f"10.0.3.{k},10.0.4.{k},https")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_asymmetric_degree_fires_on_star_only(
    tmp_path: Path, broadcaster_log_factory
) -> None:
    path = tmp_path / "bcast.csv"
    loaded = load(broadcaster_log_factory(path))
    fs = build_features(loaded.frame, loaded.schema)
    result = apply_rules(loaded.frame, loaded.schema, fs)

    src = loaded.frame["src"].astype(str).to_numpy()
    star_rows = np.where(src == "10.0.0.1")[0]
    client_rows = np.where(src == "10.0.1.0")[0]

    assert result.thresholds["actor_graph_active"] is True
    # The high-degree source star carries the rule and clears the cutoff.
    assert _fired(result, "asymmetric_degree", star_rows).all()
    assert all(result.scores[row] >= HEURISTIC_CUTOFF for row in star_rows)
    # Benign point-to-point clients never trigger it.
    assert not _fired(result, "asymmetric_degree", client_rows).any()


def test_asymmetric_degree_does_not_fire_on_passive_fanin_hub(tmp_path: Path) -> None:
    # Directional semantics (Phase 2): the rule fires only on a SOURCE fan-out
    # broadcaster, not on a passive fan-IN hub. A server reached by many distinct
    # clients on a monotone service (high in-degree, never a source) is the shape of
    # a benign DNS/NTP/load-balancer -- and the dominant false positive on real
    # captures (CTU-13 Rbot). It must NOT fire here; fan-in C2 coverage is owned by
    # the direction-agnostic hub escalation in entity_monotony.
    loaded = load(_passive_fanin_log(tmp_path / "fanin.csv"))
    fs = build_features(loaded.frame, loaded.schema)
    result = apply_rules(loaded.frame, loaded.schema, fs)

    dst = loaded.frame["dst"].astype(str).to_numpy()
    hub_rows = np.where(dst == "10.0.0.9")[0]
    # The actor graph still builds (the hub is a real high-degree endpoint) ...
    assert result.thresholds["actor_graph_active"] is True
    # ... but asymmetric_degree, now source-only, does not fire on the fan-in hub.
    assert not _fired(result, "asymmetric_degree", hub_rows).any()


def test_asymmetric_degree_dormant_without_endpoints(tmp_path: Path) -> None:
    # Synthetic click log: no two recurring endpoint columns -> rule dormant.
    log = generate(n_legit=300, n_bots=40, seed=4)
    path = tmp_path / "syn.tsv"
    write_log(path, log.frame)
    loaded = load(path)
    fs = build_features(loaded.frame, loaded.schema)
    result = apply_rules(loaded.frame, loaded.schema, fs)

    assert result.thresholds["actor_graph_active"] is False
    assert result.thresholds["degree_floor"] is None
    fired_any = any(
        hit.rule_id == "asymmetric_degree" for row in result.hits for hit in row
    )
    assert not fired_any


def test_asymmetric_degree_skips_symmetric_peer() -> None:
    # A node high in BOTH roles (a server/peer reached as much as it reaches) is
    # not asymmetric: the order-of-magnitude test must exclude it past the floor.
    # Two nodes at degree 100: a one-sided star (reverse 0) and a peer (reverse 100).
    ctx = SimpleNamespace(
        actor_columns=["src"],
        actor_degree_by_col={"src": np.array([100.0, 100.0])},
        actor_reverse_degree_by_col={"src": np.array([0.0, 100.0])},
        actor_volume_by_col={"src": np.array([100.0, 100.0])},
        actor_ctx_diversity_by_col={"src": np.array([0.0, 0.0])},
        actor_node_degrees=[100.0, 100.0],
    )
    floor = _degree_floor(ctx)
    assert floor is not None and floor <= 100.0
    assert _asymmetric_endpoint(0, ctx, floor) is not None  # one-sided star
    assert _asymmetric_endpoint(1, ctx, floor) is None  # symmetric peer

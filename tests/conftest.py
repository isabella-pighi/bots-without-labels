"""Shared test fixtures and assertion helpers.

The flow-log factories are exercised by both the feature tests (does the
structure get *detected*?) and the rule tests (does the detector *behave*
correctly on that structure?), so they live here rather than being duplicated
per module. The CTU-13 assertion helper pins the mix shape and recall guard
shared by every CTU-13 scenario benchmark.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _network_log(path: Path, *, n_fill: int = 40) -> Path:
    """A flow-like CSV with two entity columns (``src``/``dst``).

    Contains a *hub*: one destination (``10.0.0.9``) fanned to by four distinct
    sources with a constant payload; a *point-to-point* monotone channel
    (``10.0.1.1`` -> ``10.0.1.2``); and diverse filler traffic that spreads the
    per-entity diversity distribution so the adaptive cut is well defined. The
    numeric payloads of the filler/benign rows step across the whole global range
    so each entity occupies many quantile bins (genuinely diverse), rather than
    clustering into one. Actor tokens are IP-shaped so the scale-invariant shape
    discriminator (:func:`bots_without_labels.features._is_vocabulary`) admits
    them as actors rather than reading them as a bounded vocabulary.
    """

    n_pay = 12
    header = "src,dst," + ",".join(f"p{i}" for i in range(n_pay))
    rows = [header]
    zero = ",".join(["0"] * n_pay)
    hub = "10.0.0.9"
    for source in range(4):
        src = f"10.0.2.{source}"
        for _ in range(8):
            rows.append(f"{src},{hub},{zero}")
        for j in range(10):
            payload = ",".join(
                str(j * n_fill * 13 + source + k * 101) for k in range(n_pay)
            )
            rows.append(f"{src},10.0.3.{j % 5},{payload}")
    for _ in range(20):
        rows.append(f"10.0.1.1,10.0.1.2,{zero}")
    for host in range(n_fill):  # n_fill < 256 keeps each octet valid
        src, dst = f"10.0.4.{host}", f"10.0.5.{host}"
        for j in range(12):
            payload = ",".join(
                str(j * n_fill * 13 + host + k * 101) for k in range(n_pay)
            )
            rows.append(f"{src},{dst},{payload}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _broadcaster_log(path: Path) -> Path:
    """A flow-like CSV with an asymmetric high-degree source endpoint.

    ``10.0.0.1`` connects to 90 distinct destinations on one service (a spam/scan
    shape) while never appearing as a destination; benign clients each talk only
    to one of two busy servers. The two address columns are recurring
    high-cardinality endpoints; ``svc`` is a bounded categorical context (not an
    actor node).
    """

    rows = ["src,dst,svc"]
    # Broadcaster: one source -> 90 distinct destinations, one service.
    for i in range(90):
        rows.append(f"10.0.0.1,10.9.{i // 256}.{i % 256},smtp")
    # Benign clients: 60 clients, each 12 flows to one of two servers. Enough
    # distinct sources/destinations that the address columns clear the actor
    # endpoint distinct floor.
    for c in range(60):
        server = "10.0.0.250" if c % 2 == 0 else "10.0.0.251"
        for _ in range(12):
            rows.append(f"10.0.1.{c},{server},https")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture(name="network_log_factory")
def network_log_factory_fixture():
    """Factory writing the hub / point-to-point / filler flow log to a path."""
    return _network_log


@pytest.fixture(name="broadcaster_log_factory")
def broadcaster_log_factory_fixture():
    """Factory writing the asymmetric source-broadcaster flow log to a path."""
    return _broadcaster_log


def assert_ctu13_rare_attack_recall(report: dict) -> None:
    """Assertions shared by every CTU-13 scenario benchmark guard.

    Pins the intended rare-attack mix shape, the sub-second-timestamp premise
    (dense-timing rules stay active, unlike the minute-quantised CICIDS case),
    the recall win, and metric sanity bounds. Overall precision is deliberately
    NOT pinned by any CTU-13 guard — see the scenario test modules for why.
    """

    # The intended rare-attack mix shape.
    assert report["n_rows"] == 62_000, report
    assert 0.02 <= report["base_rate"] <= 0.05, report

    # Sub-second timestamps, so the dense-timing rules stay active.
    grid = report["timestamp_grid_seconds"]
    assert grid is not None and grid < 1.0, report
    assert report["dense_timing_gated"] is False, report

    # The recall win (the thing each scenario guard exists to pin).
    assert report["recall"] >= 0.95, report
    for key in ("recall", "planted_precision", "flag_rate"):
        assert 0.0 <= report[key] <= 1.0, report

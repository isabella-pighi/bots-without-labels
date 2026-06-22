"""Synthetic log generation with planted ground truth.

Detecting bots in unlabelled data has no scorecard. This module manufactures one:
it generates realistic legitimate traffic mixed with bot traffic of known
*archetypes*, and returns the ground-truth labels alongside the log. Run the
detector over the generated log and you can finally measure recall — overall and
per archetype — because you planted the bots yourself.

The generated schema is a click log (``event_id, event_time, region, browser,
os, url``) so it exercises URL-parameter expansion, but the detector treats it
like any other log.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

ARCHETYPES = ("burst", "repeated_query", "mechanical_timing", "nonsense_query")

_REGIONS = ("us", "gb", "de", "fr", "jp", "br", "in", "ca", "au", "it")
_BROWSERS = ("chrome", "safari", "firefox", "edge")
_OS = ("ios", "android", "windows", "macos", "linux")
_DOMAINS = ("news.example", "shop.example", "videos.example", "blog.example", "maps.example")
_WORDS = (
    "best", "cheap", "fast", "local", "weather", "recipes", "flights", "shoes",
    "laptop", "insurance", "near", "me", "today", "review", "price", "guide",
    "how", "to", "buy", "online", "store", "deals", "phone", "car", "house",
    "movie", "music", "news", "sport", "travel", "hotel", "food", "coffee",
)
_EPOCH = datetime(2021, 6, 1, 0, 0, 0)
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class SyntheticLog:
    """A generated log with planted labels.

    Attributes:
        frame: The log columns (``event_id, event_time, region, browser, os,
            url``).
        is_bot: ``(n_rows,)`` int array; 1 for planted bot rows.
        archetype: Per-row archetype name, or ``None`` for legitimate rows.
    """

    frame: pd.DataFrame
    is_bot: np.ndarray
    archetype: list[str | None]


def generate(
    n_legit: int = 900, n_bots: int = 100, *, seed: int = 0
) -> SyntheticLog:
    """Generate a synthetic click log with planted bot archetypes.

    Args:
        n_legit: Number of legitimate events.
        n_bots: Number of bot events, split across :data:`ARCHETYPES`.
        seed: Deterministic seed.

    Returns:
        A :class:`SyntheticLog`.
    """

    rng = random.Random(seed)
    rows: list[dict[str, str]] = []
    archetypes: list[str | None] = []
    counter = _Counter()

    for _ in range(n_legit):
        rows.append(_legit_row(rng, counter))
        archetypes.append(None)

    per = max(n_bots // len(ARCHETYPES), 0)
    remainder = n_bots - per * len(ARCHETYPES)
    for index, archetype in enumerate(ARCHETYPES):
        count = per + (1 if index < remainder else 0)
        builder = _BOT_BUILDERS[archetype]
        for row in builder(rng, counter, count):
            rows.append(row)
            archetypes.append(archetype)

    order = list(range(len(rows)))
    rng.shuffle(order)
    shuffled_rows = [rows[i] for i in order]
    shuffled_arch = [archetypes[i] for i in order]
    frame = pd.DataFrame(shuffled_rows, columns=["event_id", "event_time", "region", "browser", "os", "url"])
    is_bot = np.array([0 if arch is None else 1 for arch in shuffled_arch], dtype=int)
    return SyntheticLog(frame=frame, is_bot=is_bot, archetype=shuffled_arch)


def write_log(path, frame: pd.DataFrame) -> None:
    """Write a generated log frame to a TSV file (no label columns)."""

    frame.to_csv(path, sep="\t", index=False)


class _Counter:
    def __init__(self) -> None:
        self.value = 0

    def next(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}{self.value}"


def _time(offset_seconds: float) -> str:
    return (_EPOCH + timedelta(seconds=offset_seconds)).strftime(_TIME_FORMAT)


def _url(domain: str, query: str, ttc: int, country: str) -> str:
    return f"/click?d={domain}&q={query.replace(' ', '%20')}&ttc={ttc}&ct={country}"


def _phrase(rng: random.Random) -> str:
    return " ".join(rng.choice(_WORDS) for _ in range(rng.randint(2, 4)))


def _legit_row(rng: random.Random, counter: _Counter) -> dict[str, str]:
    region = rng.choice(_REGIONS)
    return {
        "event_id": counter.next("e"),
        "event_time": _time(rng.randint(0, 86_400)),
        "region": region,
        "browser": rng.choice(_BROWSERS),
        "os": rng.choice(_OS),
        "url": _url(rng.choice(_DOMAINS), _phrase(rng), rng.randint(600, 9000), region),
    }


def _burst_bots(rng: random.Random, counter: _Counter, count: int) -> list[dict[str, str]]:
    """Many clicks in the same second, same context, fast and identical."""

    rows = []
    region, browser, os_name = rng.choice(_REGIONS), rng.choice(_BROWSERS), rng.choice(_OS)
    domain, query = "botnet.example", "buy now"
    second = rng.randint(0, 86_400)
    for _ in range(count):
        rows.append(
            {
                "event_id": counter.next("b"),
                "event_time": _time(second),
                "region": region,
                "browser": browser,
                "os": os_name,
                "url": _url(domain, query, 5, region),
            }
        )
    return rows


def _repeated_query_bots(rng: random.Random, counter: _Counter, count: int) -> list[dict[str, str]]:
    """The same query/domain hammered across the day with a reused time-to-click."""

    rows = []
    domain, query = "spam.example", "free gift card winner"
    for _ in range(count):
        rows.append(
            {
                "event_id": counter.next("r"),
                "event_time": _time(rng.randint(0, 86_400)),
                "region": rng.choice(_REGIONS),
                "browser": rng.choice(_BROWSERS),
                "os": rng.choice(_OS),
                "url": _url(domain, query, 42, "us"),
            }
        )
    return rows


def _mechanical_timing_bots(rng: random.Random, counter: _Counter, count: int) -> list[dict[str, str]]:
    """Regular inter-arrival timing within one context, reused fast click."""

    rows = []
    region, browser, os_name = rng.choice(_REGIONS), rng.choice(_BROWSERS), rng.choice(_OS)
    domain, query = "scriptfarm.example", "auto refresh page"
    start = rng.randint(0, 80_000)
    for step in range(count):
        rows.append(
            {
                "event_id": counter.next("m"),
                "event_time": _time(start + step * 2),
                "region": region,
                "browser": browser,
                "os": os_name,
                "url": _url(domain, query, 7, region),
            }
        )
    return rows


def _nonsense_query_bots(rng: random.Random, counter: _Counter, count: int) -> list[dict[str, str]]:
    """A scripted low-entropy gibberish seed reused with a fixed click delay."""

    rows = []
    domain, query = "gibberish.example", "xxxxxxxx"
    for _ in range(count):
        rows.append(
            {
                "event_id": counter.next("n"),
                "event_time": _time(rng.randint(0, 86_400)),
                "region": rng.choice(_REGIONS),
                "browser": rng.choice(_BROWSERS),
                "os": rng.choice(_OS),
                "url": _url(domain, query, 9, "us"),
            }
        )
    return rows


_BOT_BUILDERS = {
    "burst": _burst_bots,
    "repeated_query": _repeated_query_bots,
    "mechanical_timing": _mechanical_timing_bots,
    "nonsense_query": _nonsense_query_bots,
}

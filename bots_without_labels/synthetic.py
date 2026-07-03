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

ARCHETYPES = ("burst", "mechanical_timing", "diffuse_replay", "stealth")
DETECTABLE_ARCHETYPES = ("burst", "mechanical_timing")
"""The timing-based archetypes the detector is designed to catch. The other two
(``diffuse_replay``, ``stealth``) are deliberately hard: without labels or a
stable per-entity identifier they cannot be separated from popular or human
traffic, so low recall on them is the honest, expected result."""

_REGIONS = ("us", "gb", "de", "fr", "jp", "br", "in", "ca", "au", "it")
_BROWSERS = ("chrome", "safari", "firefox", "edge")
_OS = ("ios", "android", "windows", "macos", "linux")
_DOMAINS = (
    "news.example",
    "shop.example",
    "videos.example",
    "blog.example",
    "maps.example",
)
_WORDS = (
    "best",
    "cheap",
    "fast",
    "local",
    "weather",
    "recipes",
    "flights",
    "shoes",
    "laptop",
    "insurance",
    "near",
    "me",
    "today",
    "review",
    "price",
    "guide",
    "how",
    "to",
    "buy",
    "online",
    "store",
    "deals",
    "phone",
    "car",
    "house",
    "movie",
    "music",
    "news",
    "sport",
    "travel",
    "hotel",
    "food",
    "coffee",
)
_EPOCH = datetime(2021, 6, 1, 0, 0, 0)
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_SECONDS_PER_DAY = 86_400
"""Generated events are spread across one synthetic day starting at ``_EPOCH``."""

MECHANICAL_TIMING_INTERVAL_SECONDS = 2.0
"""Fixed inter-arrival cadence of the ``mechanical_timing`` archetype.

:mod:`bots_without_labels.inject` reuses this value so injected bots present the
same regularity to the detector as generated ones.
"""

_MECHANICAL_START_MAX_SECOND = 80_000
"""Latest start second for a mechanical-timing run; the headroom below
``_SECONDS_PER_DAY`` keeps the paced sequence inside the synthetic day."""

_HUMAN_TTC_RANGE = (600, 9000)
"""Time-to-click range (seconds) for human-like rows (legitimate and stealth)."""


@dataclass(frozen=True)
class BotSignature:
    """The fixed context a bot archetype reuses across its rows.

    Attributes:
        domain: Click-target domain shared by every row of the archetype.
        query: Query text shared by every row of the archetype.
        time_to_click: Constant, implausibly fast (or suspiciously identical)
            time-to-click in seconds.
    """

    domain: str
    query: str
    time_to_click: int


_BOT_SIGNATURES: dict[str, BotSignature] = {
    "burst": BotSignature("botnet.example", "buy now", 5),
    "mechanical_timing": BotSignature("scriptfarm.example", "auto refresh page", 7),
    "diffuse_replay": BotSignature("spam.example", "free gift card winner", 42),
}
"""Default per-archetype signatures. ``stealth`` has no entry on purpose: it
reuses nothing, which is what makes it undetectable without labels. The
signature *text* map in :mod:`bots_without_labels.inject` is intentionally
similar but kept separate — injection composes signatures from the target log's
own columns rather than from this click-log schema."""


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
    n_legit: int = 900,
    n_bots: int = 100,
    *,
    seed: int = 0,
    signatures: dict[str, BotSignature] | None = None,
) -> SyntheticLog:
    """Generate a synthetic click log with planted bot archetypes.

    Args:
        n_legit: Number of legitimate events.
        n_bots: Number of bot events, split across :data:`ARCHETYPES`.
        seed: Deterministic seed.
        signatures: Per-archetype :class:`BotSignature` overrides; defaults to
            :data:`_BOT_SIGNATURES`. Archetypes without an entry (``stealth``)
            carry no signature.

    Returns:
        A :class:`SyntheticLog` whose ``frame`` holds the shuffled log columns
        (``event_id, event_time, region, browser, os, url``), ``is_bot`` the
        aligned 0/1 ground-truth array, and ``archetype`` the aligned per-row
        archetype name (``None`` for legitimate rows).
    """

    rng = random.Random(seed)
    signatures = _BOT_SIGNATURES if signatures is None else signatures
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
        for row in builder(rng, counter, count, signatures.get(archetype)):
            rows.append(row)
            archetypes.append(archetype)

    order = list(range(len(rows)))
    rng.shuffle(order)
    shuffled_rows = [rows[i] for i in order]
    shuffled_arch = [archetypes[i] for i in order]
    frame = pd.DataFrame(
        shuffled_rows,
        columns=["event_id", "event_time", "region", "browser", "os", "url"],
    )
    is_bot = np.array([0 if arch is None else 1 for arch in shuffled_arch], dtype=int)
    return SyntheticLog(frame=frame, is_bot=is_bot, archetype=shuffled_arch)


def write_log(path, frame: pd.DataFrame) -> None:
    """Write a generated log frame to a TSV file (no label columns).

    Args:
        path: Destination file path (``str`` or ``Path``).
        frame: The log columns to write, e.g. :attr:`SyntheticLog.frame`.
    """

    frame.to_csv(path, sep="\t", index=False)


class _Counter:
    """Monotonic counter for unique, prefix-tagged event IDs."""

    def __init__(self) -> None:
        """Start the counter at zero."""
        self.value = 0

    def next(self, prefix: str) -> str:
        """Return the next ID as ``prefix`` + running integer."""
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
        "event_time": _time(rng.randint(0, _SECONDS_PER_DAY)),
        "region": region,
        "browser": rng.choice(_BROWSERS),
        "os": rng.choice(_OS),
        "url": _url(
            rng.choice(_DOMAINS), _phrase(rng), rng.randint(*_HUMAN_TTC_RANGE), region
        ),
    }


def _burst_bots(
    rng: random.Random, counter: _Counter, count: int, signature: BotSignature
) -> list[dict[str, str]]:
    """Many clicks in the same second, same context, fast and identical."""

    rows = []
    region, browser, os_name = (
        rng.choice(_REGIONS),
        rng.choice(_BROWSERS),
        rng.choice(_OS),
    )
    second = rng.randint(0, _SECONDS_PER_DAY)
    for _ in range(count):
        rows.append(
            {
                "event_id": counter.next("b"),
                "event_time": _time(second),
                "region": region,
                "browser": browser,
                "os": os_name,
                "url": _url(
                    signature.domain, signature.query, signature.time_to_click, region
                ),
            }
        )
    return rows


def _diffuse_replay_bots(
    rng: random.Random, counter: _Counter, count: int, signature: BotSignature
) -> list[dict[str, str]]:
    """An evasive bot: the same query/value, but spread across diverse contexts
    and times with no burst or regular pacing.

    This is deliberately one of the *hard* archetypes. Repetition from diverse
    contexts is indistinguishable from a popular legitimate query, so a detector
    that has no labels and no stable per-user identifier cannot honestly flag it
    without also flagging viral searches. Recall on this archetype is expected to
    be low -- that is the point.
    """

    rows = []
    for _ in range(count):
        rows.append(
            {
                "event_id": counter.next("r"),
                "event_time": _time(rng.randint(0, _SECONDS_PER_DAY)),
                "region": rng.choice(_REGIONS),
                "browser": rng.choice(_BROWSERS),
                "os": rng.choice(_OS),
                # The replayed click always reports the same origin country,
                # regardless of the (diverse) region column.
                "url": _url(
                    signature.domain, signature.query, signature.time_to_click, "us"
                ),
            }
        )
    return rows


def _mechanical_timing_bots(
    rng: random.Random, counter: _Counter, count: int, signature: BotSignature
) -> list[dict[str, str]]:
    """Regular inter-arrival timing within one context, reused fast click."""

    rows = []
    region, browser, os_name = (
        rng.choice(_REGIONS),
        rng.choice(_BROWSERS),
        rng.choice(_OS),
    )
    start = rng.randint(0, _MECHANICAL_START_MAX_SECOND)
    for step in range(count):
        rows.append(
            {
                "event_id": counter.next("m"),
                "event_time": _time(start + step * MECHANICAL_TIMING_INTERVAL_SECONDS),
                "region": region,
                "browser": browser,
                "os": os_name,
                "url": _url(
                    signature.domain, signature.query, signature.time_to_click, region
                ),
            }
        )
    return rows


def _stealth_bots(
    rng: random.Random, counter: _Counter, count: int, _signature: None
) -> list[dict[str, str]]:
    """A bot that mimics human variance: a fresh query each time, a varied click
    delay, a diverse context, and no temporal pattern.

    It leaves no signature at all, so it is the floor of what unlabelled
    detection can do -- recall here should be near the background rate. Held out
    on purpose so the measured numbers are not just "we detect what we planted".
    """

    rows = []
    for _ in range(count):
        domain = rng.choice(_DOMAINS)
        query = _phrase(rng)
        rows.append(
            {
                "event_id": counter.next("s"),
                "event_time": _time(rng.randint(0, _SECONDS_PER_DAY)),
                "region": rng.choice(_REGIONS),
                "browser": rng.choice(_BROWSERS),
                "os": rng.choice(_OS),
                "url": _url(
                    domain,
                    query,
                    rng.randint(*_HUMAN_TTC_RANGE),
                    rng.choice(_REGIONS),
                ),
            }
        )
    return rows


_BOT_BUILDERS = {
    "burst": _burst_bots,
    "mechanical_timing": _mechanical_timing_bots,
    "diffuse_replay": _diffuse_replay_bots,
    "stealth": _stealth_bots,
}

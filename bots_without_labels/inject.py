"""Inject synthetic bots with known signatures into any loaded log.

Where :mod:`synthetic` builds a whole labelled log from scratch, this module
plants bots into an *existing* log you already loaded — whatever its schema.
Injected rows are synthesised from the detected column roles so they carry a
recognisable signature (a same-instant burst, a reused exact value, a repeated or
low-entropy string, mechanically regular timing), and the returned mask is the
ground truth for measuring recall with :func:`~bots_without_labels.evaluate`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .ingest import Role, Schema
from .synthetic import ARCHETYPES


@dataclass
class InjectionResult:
    """A log with planted bot rows appended.

    Attributes:
        frame: The augmented table (original rows followed by injected rows).
        is_injected: ``(n_rows,)`` int array; 1 for an injected row.
        archetype: Per-row archetype name, or ``None`` for original rows.
    """

    frame: pd.DataFrame
    is_injected: np.ndarray
    archetype: list[str | None]


def inject_bots(
    frame: pd.DataFrame,
    schema: Schema,
    *,
    n_bots: int = 100,
    seed: int = 0,
    archetypes: tuple[str, ...] = ARCHETYPES,
) -> InjectionResult:
    """Append synthetic bot rows to a loaded log and return the ground truth.

    Args:
        frame: A typed table from :func:`~bots_without_labels.ingest.load`.
        schema: Its inferred schema.
        n_bots: Total bot rows to inject, split across ``archetypes``.
        seed: Deterministic seed.
        archetypes: Which archetypes to plant.

    Returns:
        An :class:`InjectionResult`.
    """

    rng = random.Random(seed)
    tmin, tmax = _time_bounds(frame, schema)
    samples = _column_samples(frame, schema, rng)

    new_rows: list[dict[str, object]] = []
    row_archetypes: list[str] = []
    per = max(n_bots // len(archetypes), 0)
    remainder = n_bots - per * len(archetypes)

    uid = 0
    for index, archetype in enumerate(archetypes):
        count = per + (1 if index < remainder else 0)
        cluster = _cluster_values(schema, samples, archetype, rng)
        base_time = rng.uniform(tmin, tmax)
        for step in range(count):
            uid += 1
            new_rows.append(
                _bot_row(
                    schema,
                    samples,
                    cluster,
                    archetype,
                    base_time,
                    step,
                    tmin,
                    tmax,
                    uid,
                    rng,
                )
            )
            row_archetypes.append(archetype)

    if not new_rows:
        return InjectionResult(
            frame=frame.copy(),
            is_injected=np.zeros(frame.shape[0], dtype=int),
            archetype=[None] * frame.shape[0],
        )

    injected = pd.DataFrame(new_rows, columns=list(frame.columns))
    injected = injected.astype(frame.dtypes.to_dict(), errors="ignore")
    augmented = pd.concat([frame, injected], ignore_index=True)
    is_injected = np.array([0] * frame.shape[0] + [1] * len(new_rows), dtype=int)
    archetype_col = [None] * frame.shape[0] + row_archetypes
    return InjectionResult(
        frame=augmented, is_injected=is_injected, archetype=archetype_col
    )


def _time_bounds(frame: pd.DataFrame, schema: Schema) -> tuple[float, float]:
    column = schema.primary_timestamp
    if column is None:
        return 0.0, 0.0
    times = pd.to_datetime(frame[column], errors="coerce").dropna()
    if times.empty:
        return 0.0, 0.0
    nanos = times.to_numpy(dtype="datetime64[ns]").astype("int64")
    return float(nanos.min()) / 1e9, float(nanos.max()) / 1e9


def _column_samples(
    frame: pd.DataFrame, schema: Schema, rng: random.Random
) -> dict[str, list]:
    samples: dict[str, list] = {}
    for column in frame.columns:
        values = frame[column].dropna().tolist()
        samples[column] = values
    return samples


def _cluster_values(
    schema: Schema, samples: dict[str, list], archetype: str, rng: random.Random
) -> dict[str, object]:
    """Fix the shared values that give an archetype cluster its signature."""

    cluster: dict[str, object] = {}
    for column in samples:
        role = schema.role_of(column)
        pool = samples[column]
        if role == Role.NUMERIC:
            cluster[column] = float(rng.choice(pool)) if pool else 5.0
        elif role == Role.CATEGORICAL:
            cluster[column] = rng.choice(pool) if pool else "bot"
        elif role == Role.BOOLEAN:
            cluster[column] = rng.choice(pool) if pool else True
        elif role in (Role.TEXT, Role.URL):
            cluster[column] = _signature_text(archetype, rng)
    return cluster


def _signature_text(archetype: str, rng: random.Random) -> str:
    if archetype == "nonsense_query":
        return rng.choice("abcdefghijk") * 8
    return {
        "burst": "buy now now now",
        "repeated_query": "free gift card winner",
        "mechanical_timing": "auto refresh page",
    }.get(archetype, "automated click")


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _bot_row(
    schema: Schema,
    samples: dict[str, list],
    cluster: dict[str, object],
    archetype: str,
    base_time: float,
    step: int,
    tmin: float,
    tmax: float,
    uid: int,
    rng: random.Random,
) -> dict[str, object]:
    row: dict[str, object] = {}
    for column in samples:
        role = schema.role_of(column)
        if role == Role.IDENTIFIER:
            row[column] = f"inj_{archetype}_{uid}"
        elif role == Role.TIMESTAMP:
            row[column] = _bot_time(archetype, base_time, step, tmin, tmax, rng)
        elif column in cluster:
            row[column] = cluster[column]
        else:
            pool = samples[column]
            row[column] = rng.choice(pool) if pool else ""
    return row


def _bot_time(
    archetype: str,
    base_time: float,
    step: int,
    tmin: float,
    tmax: float,
    rng: random.Random,
) -> object:
    if archetype == "burst":
        seconds = base_time
    elif archetype == "mechanical_timing":
        seconds = base_time + step * 2.0
    else:
        seconds = rng.uniform(tmin, tmax) if tmax > tmin else base_time
    return pd.to_datetime(int(seconds * 1e9))

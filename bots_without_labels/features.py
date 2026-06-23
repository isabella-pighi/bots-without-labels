"""Schema-driven feature engineering.

Given a typed table and its :class:`~bots_without_labels.ingest.Schema`, this
module derives a purely numeric feature matrix suitable for unsupervised anomaly
scoring, plus a :class:`FeatureContext` of the per-row counts and timing
statistics that the rule-based detector (Phase 3) reuses.

Features are produced *from column roles*, not from any fixed schema, so the
click-specific signals are a special case that lights up when the relevant
columns are present:

* **categorical** columns -> value concentration (``<col>__conc``), and a joint
  concentration over all categoricals together (``context__conc``) — the generic
  analogue of a region/browser/OS device cluster;
* **numeric** columns -> the value itself (``<col>__val``) and how often the
  exact value recurs (``<col>__rep``) — e.g. a reused exact time-to-click;
* **text** columns -> string entropy, unique-character ratio, and exact-string
  repetition (``<col>__entropy`` / ``__uniqchar`` / ``__rep``) — e.g. a repeated
  or nonsense search query;
* **boolean** columns -> a 0/1 flag (``<col>__bool``);
* the primary **timestamp** -> hour of day, same-instant concentration, a local
  burst count within the categorical context, and inter-arrival regularity
  (``hour`` / ``same_time__conc`` / ``burst{W}s__conc`` / ``dt__std`` /
  ``dt__cv``).

Identifier columns, URL source columns, and non-primary timestamps contribute no
features.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import log1p

import numpy as np
import pandas as pd
from scipy.stats import entropy as shannon_entropy

from .ingest import Role, Schema

BURST_WINDOW_SECONDS = 10
SPARSE_TIMING_SENTINEL = 999.0
"""Inter-arrival std/cv for groups too small to be considered regular. The high
value keeps sparse groups from looking mechanically regular."""

ENTITY_MIN_DISTINCT = 10
"""An actor-like column needs at least this many distinct values to baseline."""
ENTITY_DIVERSITY_BINS = 8
"""Quantile bins applied to numeric columns before per-entity entropy."""

RESOLUTION_GAP_PERCENTILE = 5
"""Percentile of positive inter-timestamp gaps taken as the clock's resolution.
A *low* percentile (the finest typical spacing) -- not the median -- so a sparse
log whose events are far apart is not mistaken for a coarse clock; not the strict
minimum, so a sparse tail of off-grid jitter (a few stray fine gaps) cannot lower
it. See :func:`_timestamp_resolution`."""

_MISSING = "\x00NA"


@dataclass
class FeatureContext:
    """Per-row counts and timing statistics reused by the rule-based detector.

    Attributes:
        n_rows: Row count.
        row_counts: Per-column array of how many rows share each row's value.
        count_values: Per-column list of distinct-value group sizes (for
            computing adaptive percentile thresholds).
        context_count: Per-row joint count over all categorical columns.
        timestamp_count: Per-row count of rows sharing the exact timestamp.
        burst_count: Per-row local click count within the burst window and the
            row's categorical context.
        timestamp_resolution: Typical granularity of the primary timestamp, in
            seconds -- the *median* positive gap between consecutive distinct
            timestamps, i.e. the grid the clock is effectively quantised to. The
            median (not the minimum) is used so a single off-grid pair cannot make
            an otherwise minute-binned source look fine-resolution. ``None`` when
            there is no timestamp or fewer than two distinct values. Dense-timing
            rules use it to ignore within-window co-occurrence on coarse clocks.
        dt_std: Per-row inter-arrival standard deviation within the burst-run.
        dt_cv: Per-row inter-arrival coefficient of variation within the burst-run.
        run_size: Per-row size of the row's burst-run (the contiguous, densely
            spaced sub-sequence of its categorical context, not the whole group).
        entity_columns: Actor-like columns used for per-entity baselining.
        entity_diversity: Per-row minimum, across entity columns, of the entity's
            behavioural diversity (mean normalised entropy of its events over the
            other columns). Low means the entity does the same thing repeatedly.
        entity_volume: Per-row event count of the entity that gave the minimum
            diversity, so a rule can require enough volume to baseline.
        entity_diversity_by_col / entity_volume_by_col: Per-entity-column,
            per-row diversity and event count (the un-reduced inputs to the
            ``entity_diversity``/``entity_volume`` minima above), so a rule can
            reason about each entity role separately.
        entity_degree_by_col: Per-entity-column, per-row relational degree -- the
            number of *distinct counterpart values* (across the other entity
            columns) the row's entity communicates with. A monotonous entity with
            a high degree is a hub/star (e.g. a C2 fanned to by many hosts); a
            monotonous entity with degree 1 is a single point-to-point channel. It
            is 0 when there is only one entity column (no counterpart to count).
        categorical_columns / numeric_columns / text_columns / boolean_columns:
            The columns used, by role.
        timestamp_column: The primary timestamp column, or ``None``.
    """

    n_rows: int
    row_counts: dict[str, np.ndarray] = field(default_factory=dict)
    count_values: dict[str, list[int]] = field(default_factory=dict)
    context_count: np.ndarray | None = None
    timestamp_count: np.ndarray | None = None
    timestamp_resolution: float | None = None
    burst_count: np.ndarray | None = None
    dt_std: np.ndarray | None = None
    dt_cv: np.ndarray | None = None
    run_size: np.ndarray | None = None
    entity_columns: list[str] = field(default_factory=list)
    entity_diversity: np.ndarray | None = None
    entity_volume: np.ndarray | None = None
    entity_diversity_by_col: dict[str, np.ndarray] = field(default_factory=dict)
    entity_volume_by_col: dict[str, np.ndarray] = field(default_factory=dict)
    entity_degree_by_col: dict[str, np.ndarray] = field(default_factory=dict)
    categorical_columns: list[str] = field(default_factory=list)
    numeric_columns: list[str] = field(default_factory=list)
    text_columns: list[str] = field(default_factory=list)
    boolean_columns: list[str] = field(default_factory=list)
    timestamp_column: str | None = None


@dataclass
class FeatureSet:
    """A numeric feature matrix with aligned names and families.

    Attributes:
        names: Feature names, aligned to ``matrix`` columns.
        matrix: ``(n_rows, n_features)`` float array.
        families: Maps each feature name to a family
            (concentration/value/repetition/text/timing/burst/flag/time).
        context: The :class:`FeatureContext` for the rule-based detector.
    """

    names: list[str]
    matrix: np.ndarray
    families: dict[str, str]
    context: FeatureContext

    def frame(self) -> pd.DataFrame:
        """Return the feature matrix as a named :class:`pandas.DataFrame`."""

        return pd.DataFrame(self.matrix, columns=self.names)


def build_features(frame: pd.DataFrame, schema: Schema) -> FeatureSet:
    """Build the numeric feature matrix and rule context for a loaded log.

    Args:
        frame: The typed table from :func:`~bots_without_labels.ingest.load`.
        schema: Its inferred schema.

    Returns:
        A :class:`FeatureSet`.
    """

    n_rows = int(frame.shape[0])
    categoricals = schema.columns_with_role(Role.CATEGORICAL)
    numerics = schema.columns_with_role(Role.NUMERIC)
    texts = schema.columns_with_role(Role.TEXT)
    booleans = schema.columns_with_role(Role.BOOLEAN)
    timestamp = schema.primary_timestamp

    context = FeatureContext(
        n_rows=n_rows,
        categorical_columns=categoricals,
        numeric_columns=numerics,
        text_columns=texts,
        boolean_columns=booleans,
        timestamp_column=timestamp,
    )
    columns: dict[str, np.ndarray] = {}
    families: dict[str, str] = {}

    def add(name: str, values: np.ndarray, family: str) -> None:
        columns[name] = np.asarray(values, dtype=float)
        families[name] = family

    # Categorical concentration.
    for name in categoricals:
        counts, distinct = _value_counts(frame[name])
        context.row_counts[name] = counts
        context.count_values[name] = distinct
        add(f"{name}__conc", np.log1p(counts), "concentration")

    # Joint categorical context concentration (device-cluster analogue).
    if len(categoricals) >= 2:
        context_counts, context_distinct = _joint_counts(frame, categoricals)
        context.context_count = context_counts
        context.count_values["__context__"] = context_distinct
        add("context__conc", np.log1p(context_counts), "concentration")

    # Numeric value and exact-value repetition.
    for name in numerics:
        numeric = pd.to_numeric(frame[name], errors="coerce")
        # Treat non-finite values as missing: real captures (e.g. CICIDS flow
        # throughput) carry literal "Infinity"/"NaN" cells from divide-by-zero
        # rates, which ``to_numeric`` parses to +/-inf. Left in, they poison the
        # downstream median/std standardisation (an inf column makes every
        # deviation NaN) and would otherwise need scrubbing at scoring time.
        numeric = numeric.replace([np.inf, -np.inf], np.nan)
        # Median-fill missing values; fall back to 0 when the whole column is
        # missing (median is NaN) so the matrix never carries NaN into scoring.
        median = numeric.median()
        filled = numeric.fillna(0.0 if pd.isna(median) else median)
        add(f"{name}__val", filled.to_numpy(dtype=float), "value")
        counts, distinct = _value_counts(frame[name])
        context.row_counts[name] = counts
        context.count_values[name] = distinct
        add(f"{name}__rep", np.log1p(counts), "repetition")

    # Text entropy, character diversity, and repetition. Entropy/diversity depend
    # only on the string value, so compute them once per distinct value and map
    # back -- O(distinct) instead of O(rows), which matters on large logs.
    for name in texts:
        as_text = frame[name].astype("string").fillna("").astype(str)
        unique_values = as_text.unique()
        entropy_by_value = {value: _string_entropy(value) for value in unique_values}
        uniqchar_by_value = {
            value: _unique_char_ratio(value) for value in unique_values
        }
        add(f"{name}__entropy", as_text.map(entropy_by_value).to_numpy(float), "text")
        add(
            f"{name}__uniqchar",
            as_text.map(uniqchar_by_value).to_numpy(float),
            "text",
        )
        counts, distinct = _value_counts(frame[name])
        context.row_counts[name] = counts
        context.count_values[name] = distinct
        add(f"{name}__rep", np.log1p(counts), "repetition")

    # Boolean flags.
    for name in booleans:
        flag = frame[name].map({True: 1.0, False: 0.0}).fillna(0.0)
        add(f"{name}__bool", flag.to_numpy(dtype=float), "flag")

    # Timestamp-derived timing and burst features.
    if timestamp is not None:
        times = pd.to_datetime(frame[timestamp], errors="coerce")
        add("hour", times.dt.hour.fillna(0).to_numpy(dtype=float), "time")
        ts_counts, ts_distinct = _value_counts(frame[timestamp])
        context.timestamp_count = ts_counts
        context.timestamp_resolution = _timestamp_resolution(times)
        context.count_values["__timestamp__"] = ts_distinct
        add("same_time__conc", np.log1p(ts_counts), "burst")

        keys = _joint_keys(frame, categoricals) if categoricals else np.zeros(n_rows)
        burst, dt_std, dt_cv, run_size = _temporal_context(times, keys)
        context.burst_count = burst
        context.dt_std = dt_std
        context.dt_cv = dt_cv
        context.run_size = run_size
        add(f"burst{BURST_WINDOW_SECONDS}s__conc", np.log1p(burst), "burst")
        add("dt__std", np.log1p(dt_std), "timing")
        add("dt__cv", np.log1p(dt_cv), "timing")

    # Per-entity behavioural diversity. An automated actor (botnet host, scraper,
    # click farm) emits internally self-similar events; a popular *legitimate*
    # actor fans out. Scoring each entity by how repetitive its own events are
    # catches repetition-based bots that the globally-capped concentration rules
    # miss -- without firing on every popular value.
    entity_cols = _entity_columns(frame, schema, categoricals)
    if entity_cols:
        diversity, volume, by_col = _entity_baseline(
            frame, schema, entity_cols, categoricals
        )
        context.entity_columns = entity_cols
        context.entity_diversity = diversity
        context.entity_volume = volume
        context.entity_diversity_by_col = {c: by_col[c][0] for c in entity_cols}
        context.entity_volume_by_col = {c: by_col[c][1] for c in entity_cols}
        context.entity_degree_by_col = {c: by_col[c][2] for c in entity_cols}
        add("entity__diversity", diversity, "entity")

    names = list(columns.keys())
    matrix = (
        np.column_stack([columns[name] for name in names])
        if names
        else np.zeros((n_rows, 0))
    )
    return FeatureSet(names=names, matrix=matrix, families=families, context=context)


# --- Helpers -----------------------------------------------------------------


def _stringify(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna(_MISSING).astype(str)


def _value_counts(series: pd.Series) -> tuple[np.ndarray, list[int]]:
    """Return per-row occurrence counts and the distinct-value group sizes.

    Missing values are excluded: a missing cell gets a count of 0 (so it never
    counts as concentration, repetition, or a same-instant burst), and the
    missing bucket is dropped from the distinct group sizes.
    """

    text = _stringify(series)
    counts = text.value_counts()
    per_row = text.map(counts).to_numpy(dtype=float)
    missing = (text == _MISSING).to_numpy()
    per_row[missing] = 0.0
    distinct = [int(value) for key, value in counts.items() if key != _MISSING]
    return per_row, distinct


def _joint_counts(
    frame: pd.DataFrame, columns: list[str]
) -> tuple[np.ndarray, list[int]]:
    keys = _joint_keys(frame, columns)
    counts = Counter(keys.tolist())
    per_row = np.array([counts[key] for key in keys], dtype=float)
    return per_row, [int(value) for value in counts.values()]


def _joint_keys(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    joined = _stringify(frame[columns[0]])
    for name in columns[1:]:
        joined = joined.str.cat(_stringify(frame[name]), sep="\x1f")
    return joined.to_numpy()


def _string_entropy(value: str) -> float:
    if not value:
        return 0.0
    total = len(value)
    probabilities = [count / total for count in Counter(value).values()]
    return float(shannon_entropy(probabilities, base=2))


def _unique_char_ratio(value: str) -> float:
    if not value:
        return 0.0
    return len(set(value)) / len(value)


def _entity_columns(
    frame: pd.DataFrame, schema: Schema, categoricals: list[str]
) -> list[str]:
    """Pick actor-like columns to baseline: categoricals whose values recur.

    An entity column has many distinct values (so it identifies actors, not a
    handful of categories) but each value recurs (so an actor has several events
    to baseline), and is not essentially unique (that is an identifier).
    """

    n_rows = int(frame.shape[0])
    out: list[str] = []
    for name in categoricals:
        counts = frame[name].value_counts()
        distinct = len(counts)
        if distinct < ENTITY_MIN_DISTINCT or distinct >= 0.95 * n_rows:
            continue
        if float(counts.median()) < 2:
            continue
        out.append(name)
    return out


def _behaviour_frame(
    frame: pd.DataFrame, schema: Schema, entity_col: str, categoricals: list[str]
) -> list[np.ndarray]:
    """Coarse behavioural columns for one entity's events (ids/text excluded)."""

    out: list[np.ndarray] = []
    for name in categoricals + schema.columns_with_role(Role.NUMERIC):
        if name == entity_col:
            continue
        if schema.role_of(name) == Role.NUMERIC:
            num = pd.to_numeric(frame[name], errors="coerce")
            binned = pd.qcut(
                num.rank(method="first"),
                q=ENTITY_DIVERSITY_BINS,
                labels=False,
                duplicates="drop",
            )
            out.append(binned.fillna(-1).to_numpy())
        else:
            out.append(_stringify(frame[name]).to_numpy())
    return out


def _entity_baseline(
    frame: pd.DataFrame,
    schema: Schema,
    entity_cols: list[str],
    categoricals: list[str],
) -> tuple[np.ndarray, np.ndarray, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]]:
    """Per-row entity baselining: diversity, volume, and relational degree.

    For each entity column, every value is scored by its behavioural *diversity*
    (the mean over behavioural columns of its events' normalised Shannon entropy:
    0 = always identical, 1 = maximally varied), its *volume* (event count), and
    its *degree* (the number of distinct counterpart values it communicates with
    across the other entity columns).

    Returns the per-row minimum diversity across entity columns (the most
    automation-like view of the row) and the volume of that same entity, plus a
    ``by_col`` mapping ``entity_col -> (diversity, volume, degree)`` of per-row
    arrays so a rule can reason about each entity role and its relational
    structure separately.
    """

    n_rows = int(frame.shape[0])
    diversity = np.ones(n_rows, dtype=float)
    volume = np.ones(n_rows, dtype=float)
    by_col: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    entity_values = {col: _stringify(frame[col]).to_numpy() for col in entity_cols}

    for entity_col in entity_cols:
        behaviour = _behaviour_frame(frame, schema, entity_col, categoricals)
        entities = entity_values[entity_col]
        counterpart_cols = [c for c in entity_cols if c != entity_col]
        members: dict[object, list[int]] = defaultdict(list)
        for index in range(n_rows):
            members[entities[index]].append(index)

        per_entity_div: dict[object, float] = {}
        per_entity_vol: dict[object, int] = {}
        per_entity_deg: dict[object, int] = {}
        for key, idx in members.items():
            per_entity_vol[key] = len(idx)
            if len(idx) < 2 or not behaviour:
                per_entity_div[key] = 1.0
            else:
                ents = [_norm_entropy(column[idx]) for column in behaviour]
                per_entity_div[key] = float(np.mean(ents)) if ents else 1.0
            # Relational degree: distinct counterparts across the other entity
            # columns. A hub (many counterparts) is structurally unlike a single
            # point-to-point channel even when both look equally monotonous.
            counterparts: set[object] = set()
            for col in counterpart_cols:
                counterparts.update(entity_values[col][idx].tolist())
            counterparts.discard(key)
            per_entity_deg[key] = len(counterparts)

        col_div = np.array([per_entity_div[e] for e in entities], dtype=float)
        col_vol = np.array([per_entity_vol[e] for e in entities], dtype=float)
        col_deg = np.array([per_entity_deg[e] for e in entities], dtype=float)
        by_col[entity_col] = (col_div, col_vol, col_deg)

        update = col_div < diversity
        diversity = np.where(update, col_div, diversity)
        volume = np.where(update, col_vol, volume)
    return diversity, volume, by_col


def _norm_entropy(values: np.ndarray) -> float:
    """Shannon entropy of a value array, normalised to ``[0, 1]`` by ``log(n)``."""

    _, counts = np.unique(values, return_counts=True)
    total = counts.sum()
    if total <= 1:
        return 0.0
    probabilities = counts / total
    h = float(-(probabilities * np.log(probabilities)).sum())
    return h / np.log(total)


def _timestamp_resolution(times: pd.Series) -> float | None:
    """Return the timestamp's effective clock resolution in seconds, or ``None``.

    A low percentile (:data:`RESOLUTION_GAP_PERCENTILE`) of the positive gaps
    between consecutive *distinct* timestamps -- the grid the clock is effectively
    quantised to. Two design choices keep it honest on real and synthetic logs:

    * **Distinct, deduped first** -- repeated (same-instant) timestamps would
      otherwise drive the estimate to zero.
    * **A low percentile, not the median** -- the median is the *typical spacing*,
      which on a sparse log (events minutes apart but a one-second clock) is large
      even though the clock is fine; it would wrongly read as coarse and suppress
      the timing rules that catch a sub-second burst inside that sparse log. The
      finest-typical spacing (a low percentile) reflects the clock, not the load.
    * **Not the strict minimum** -- a sparse tail of off-grid jitter (a handful of
      stray fine gaps on an otherwise minute-binned clock) cannot pull a low
      percentile below the grid, so the estimate stays robust to clock glitches.

    Returns ``None`` when there is no valid timestamp or fewer than two distinct
    values (no spacing to measure), in which case dense-timing rules stay active.
    """

    valid = times.dropna()
    if valid.empty:
        return None
    distinct = np.unique(valid.to_numpy(dtype="datetime64[ns]").astype("int64"))
    if distinct.size < 2:
        return None
    gaps = np.diff(distinct)
    gaps = gaps[gaps > 0]
    if gaps.size == 0:
        return None
    return float(np.percentile(gaps, RESOLUTION_GAP_PERCENTILE)) / 1e9


def _temporal_context(
    times: pd.Series, keys: np.ndarray, window_seconds: int = BURST_WINDOW_SECONDS
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return per-row burst counts, inter-arrival regularity, and run sizes.

    Rows are grouped by their categorical context. Within each group, sorted by
    time, every row receives the number of peers inside a centred time window
    (the burst count).

    Inter-arrival regularity is measured per **burst-run** -- a maximal
    sub-sequence whose consecutive gaps stay within the burst window -- rather
    than over the whole group. A bot that injects a mechanically regular cadence
    into a *popular* context (one whose categorical value many legitimate rows
    also share) would otherwise be masked: the legitimate rows, scattered across
    hours or days, inflate the group's inter-arrival variance so the regular
    sub-sequence never stands out. Segmenting into runs isolates the cadence.

    A run whose events are all at the *same instant* (mean gap of zero) is left at
    the sparse sentinel rather than scored as perfectly regular: a same-instant
    pile is the ``same_instant_burst`` rule's job, and treating coarse or repeated
    timestamps as "mechanically regular" would invent false positives. Runs and
    groups too small to be considered regular keep the high sentinel.
    """

    n_rows = len(times)
    burst = np.ones(n_rows, dtype=float)
    dt_std = np.full(n_rows, SPARSE_TIMING_SENTINEL, dtype=float)
    dt_cv = np.full(n_rows, SPARSE_TIMING_SENTINEL, dtype=float)
    run_size = np.ones(n_rows, dtype=float)

    # Normalise to nanoseconds: pandas may parse timestamps at second/us/ns
    # resolution, so the raw int64 view is not a fixed unit.
    nanos = times.to_numpy(dtype="datetime64[ns]").astype("int64")
    valid = times.notna().to_numpy()
    half_window = window_seconds / 2.0

    groups: dict[object, list[int]] = defaultdict(list)
    for index in range(n_rows):
        if valid[index]:
            groups[keys[index]].append(index)

    for members in groups.values():
        order = sorted(members, key=lambda index: nanos[index])
        seconds = [nanos[index] / 1e9 for index in order]
        left = 0
        right = 0
        for position, index in enumerate(order):
            moment = seconds[position]
            while seconds[left] < moment - half_window:
                left += 1
            while right + 1 < len(order) and seconds[right + 1] <= moment + half_window:
                right += 1
            burst[index] = right - left + 1

        # Segment the group into burst-runs and score regularity within each.
        start = 0
        for position in range(1, len(order) + 1):
            ends_run = position == len(order) or (
                seconds[position] - seconds[position - 1] > window_seconds
            )
            if not ends_run:
                continue
            run = order[start:position]
            run_seconds = seconds[start:position]
            for index in run:
                run_size[index] = len(run)
            if len(run) >= 3:
                deltas = [
                    run_seconds[i] - run_seconds[i - 1] for i in range(1, len(run))
                ]
                mean_delta = sum(deltas) / len(deltas)
                if mean_delta > 0:
                    variance = sum((d - mean_delta) ** 2 for d in deltas) / len(deltas)
                    std = variance**0.5
                    for index in run:
                        dt_std[index] = std
                        dt_cv[index] = std / mean_delta
            start = position
    return burst, dt_std, dt_cv, run_size

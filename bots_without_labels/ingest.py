"""Autodetecting log loader and schema inference.

This module turns an arbitrary log file into a typed table plus a description of
what each column *is*. It is deliberately format- and schema-agnostic: the goal
is that you can point it at a CSV, a TSV, or newline-delimited JSON without
telling it anything about the columns, and downstream feature engineering can ask
the resulting :class:`Schema` which columns are timestamps, categories, numbers,
URLs, and so on.

The original ad-click format (``event_id, event_time, region, browser, os, url``)
is just one schema this loader recognises: the ``url`` column is detected and its
query string is expanded into ordinary columns (``url__d``, ``url__q``,
``url__ttc`` ...), which recovers the click-specific signals automatically.

Loading is a three-step pipeline:

1. :func:`read_table` detects the file format and reads every cell as a string.
2. URL columns are detected and their query parameters expanded into new columns.
3. :func:`infer_schema` classifies each column into a :class:`Role`, and a typed
   :class:`pandas.DataFrame` is built from those roles.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pandas as pd

# --- Tuning constants --------------------------------------------------------

SAMPLE_SIZE = 1000
"""Rows sampled (from the top) when classifying a column. Keeps inference fast
on large logs while staying deterministic."""

MAX_SAMPLE_BYTES = 65_536
"""Bytes read from the head of a file for format/dialect detection. Enough to
see many lines of any realistic log without reading a large file twice."""

PARSE_RATE = 0.95
"""Fraction of sampled non-missing values that must parse as a type for the
column to be assigned that type."""

URL_RATE = 0.70
"""Fraction of non-missing values that must look like a URL for a column to be
treated as a URL (and have its query string expanded)."""

CATEGORICAL_ABS_MAX = 50
"""A column with at most this many distinct values is categorical regardless of
row count (captures small fixed sets like region or browser)."""

CATEGORICAL_RATIO_MAX = 0.20
"""A column whose distinct/non-missing ratio is at or below this is categorical
(captures larger-but-bounded sets like country in a big log)."""

IDENTIFIER_RATIO_MIN = 0.95
"""A near-unique, token-like column at or above this ratio is an identifier."""

NA_TOKENS = frozenset({"", "na", "n/a", "null", "none", "nan", "-"})
TRUE_TOKENS = frozenset({"true", "t", "yes", "y"})
FALSE_TOKENS = frozenset({"false", "f", "no", "n"})

KNOWN_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%d-%m-%Y %H:%M:%S",
    "%d %b %Y %H:%M:%S",
)

_URL_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://\S+|\?\S*=", re.IGNORECASE)
_TOKEN_RE = re.compile(r"^\S{1,64}$")
_SEPARATOR_RE = re.compile(r"[^0-9.]")


class Role:
    """String constants for the role a column plays in a log."""

    TIMESTAMP = "timestamp"
    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    CATEGORICAL = "categorical"
    TEXT = "text"
    URL = "url"
    IDENTIFIER = "identifier"


# --- Schema dataclasses ------------------------------------------------------


@dataclass
class ColumnSchema:
    """The inferred description of a single column.

    Attributes:
        name: Column name.
        role: One of the :class:`Role` constants.
        n_unique: Distinct non-missing value count.
        n_missing: Missing value count.
        cardinality_ratio: ``n_unique`` divided by the non-missing count.
        examples: Up to five example values, as strings.
        derived_from: For URL-expanded columns, the source URL column name.
        datetime_format: The matched strptime format for timestamp columns, if a
            known one applied.
        numeric_subtype: ``"int"`` or ``"float"`` for numeric columns.
        entity_override: True when the user explicitly declared this column an
            actor/entity column (``--entity-column``). The column is treated as
            categorical and the *identity-shape* actor tests (vocabulary shape,
            content grammar) are bypassed for it; the volume/recurrence floors
            still apply, because they guard the statistical validity of the
            adaptive thresholds rather than guessing identity.
        content_override: True when the user explicitly declared this column
            content (``--content-column``); it is excluded from actor/entity
            selection like a URL column.
    """

    name: str
    role: str
    n_unique: int
    n_missing: int
    cardinality_ratio: float
    examples: list[str] = field(default_factory=list)
    derived_from: str | None = None
    datetime_format: str | None = None
    numeric_subtype: str | None = None
    entity_override: bool = False
    content_override: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation of the column schema."""

        return {
            "name": self.name,
            "role": self.role,
            "n_unique": self.n_unique,
            "n_missing": self.n_missing,
            "cardinality_ratio": round(self.cardinality_ratio, 4),
            "examples": self.examples,
            "derived_from": self.derived_from,
            "datetime_format": self.datetime_format,
            "numeric_subtype": self.numeric_subtype,
            "entity_override": self.entity_override,
            "content_override": self.content_override,
        }


@dataclass
class Schema:
    """The inferred schema for a whole log.

    Attributes:
        columns: Per-column schemas, in column order.
        n_rows: Total row count.
        source_format: ``"csv"``, ``"tsv"``, ``"json"``, or ``"jsonl"``.
        primary_timestamp: The chosen timestamp column, or ``None``.
        row_id: A column that uniquely identifies rows, or ``None``.
        url_columns: Names of columns detected as URLs.
    """

    columns: list[ColumnSchema]
    n_rows: int
    source_format: str
    primary_timestamp: str | None = None
    row_id: str | None = None
    url_columns: list[str] = field(default_factory=list)

    def column(self, name: str) -> ColumnSchema | None:
        """Return the schema for ``name`` if present."""

        return next((col for col in self.columns if col.name == name), None)

    def role_of(self, name: str) -> str | None:
        """Return the role assigned to ``name`` if present."""

        col = self.column(name)
        return col.role if col else None

    def columns_with_role(self, role: str) -> list[str]:
        """Return the names of all columns assigned ``role``, in order."""

        return [col.name for col in self.columns if col.role == role]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation of the schema."""

        return {
            "n_rows": self.n_rows,
            "source_format": self.source_format,
            "primary_timestamp": self.primary_timestamp,
            "row_id": self.row_id,
            "url_columns": self.url_columns,
            "columns": [col.to_dict() for col in self.columns],
        }

    def describe(self) -> str:
        """Return a compact human-readable table of column roles."""

        header = f"{self.n_rows} rows, format={self.source_format}"
        marks = []
        if self.primary_timestamp:
            marks.append(f"timestamp={self.primary_timestamp}")
        if self.row_id:
            marks.append(f"row_id={self.row_id}")
        if self.url_columns:
            marks.append(f"urls={','.join(self.url_columns)}")
        lines = [header + ("  (" + "; ".join(marks) + ")" if marks else "")]
        width = max((len(col.name) for col in self.columns), default=0)
        for col in self.columns:
            extra = f" <- {col.derived_from}" if col.derived_from else ""
            lines.append(
                f"  {col.name:<{width}}  {col.role:<11}"
                f"  unique={col.n_unique} missing={col.n_missing}{extra}"
            )
        return "\n".join(lines)


@dataclass
class LoadedLog:
    """A loaded log: a typed table plus its inferred schema.

    Attributes:
        frame: The typed table. Timestamp columns are ``datetime64``, numeric
            columns are numeric, boolean columns are nullable booleans, and the
            rest are nullable strings (missing values are ``<NA>``/``NaT``).
        schema: The inferred :class:`Schema`.
        path: The source file path.
    """

    frame: pd.DataFrame
    schema: Schema
    path: str


# --- Public API --------------------------------------------------------------


def load(
    path: str | Path,
    *,
    expand_urls: bool = True,
    entity_columns: Sequence[str] = (),
    content_columns: Sequence[str] = (),
) -> LoadedLog:
    """Load any supported log into a typed table with an inferred schema.

    Args:
        path: Path to a CSV, TSV, JSON array, or JSON-lines log. Files are
            decoded as UTF-8 with undecodable bytes replaced, so a stray
            non-UTF-8 byte never aborts a load.
        expand_urls: When true, detected URL columns have their query string
            expanded into new ``<column>__<param>`` columns (plus
            ``<column>__path``) before schema inference.
        entity_columns: Explicit, default-off schema override: column names the
            user declares to be actor/entity columns (an integer-coded session
            id, a short-username pool). Each named column is coerced to the
            categorical role and marked ``entity_override`` so the actor/entity
            machinery considers it without the identity-shape inference tests.
        content_columns: Explicit, default-off schema override: column names
            the user declares to be content (a raw request path); each is
            marked ``content_override`` and excluded from actor/entity
            selection.

    Returns:
        A :class:`LoadedLog`.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file is empty or cannot be parsed, if an override
            names a column that does not exist, or if the same column is named
            in both overrides.
    """

    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise FileNotFoundError(f"Log file '{file_path}' does not exist")

    raw, source_format = read_table(file_path)
    if raw.shape[1] == 0:
        raise ValueError(f"Log file '{file_path}' produced no columns")

    derived: dict[str, str] = {}
    if expand_urls:
        derived = _expand_url_columns(raw)

    schema = infer_schema(
        raw,
        source_format=source_format,
        derived=derived,
        entity_columns=entity_columns,
        content_columns=content_columns,
    )
    typed = _typed_frame(raw, schema)
    return LoadedLog(frame=typed, schema=schema, path=str(file_path))


def read_table(path: str | Path) -> tuple[pd.DataFrame, str]:
    """Detect a log's format and read every cell as a string.

    Missing values are represented as empty strings so that schema inference can
    apply a single, explicit notion of "missing".

    Args:
        path: Path to the log file.

    Returns:
        A pair ``(frame, source_format)`` where ``frame`` is an all-string
        DataFrame and ``source_format`` is one of ``csv``/``tsv``/``json``/
        ``jsonl``.

    Raises:
        ValueError: If the file is empty or cannot be parsed into a table.
        OSError: If the file cannot be read (e.g. it does not exist; callers
            like :func:`load` check existence first).
    """

    file_path = Path(path).expanduser()
    sample = file_path.read_bytes()[:MAX_SAMPLE_BYTES].decode("utf-8", errors="replace")
    if not sample.strip():
        raise ValueError(f"Log file '{file_path}' is empty")

    source_format = _detect_format(file_path, sample)
    if source_format in ("json", "jsonl"):
        frame = _read_json(file_path, source_format)
    else:
        frame = _read_delimited(file_path, source_format, sample)
    return _stringify(frame), source_format


def infer_schema(
    raw: pd.DataFrame,
    *,
    source_format: str = "csv",
    derived: dict[str, str] | None = None,
    entity_columns: Sequence[str] = (),
    content_columns: Sequence[str] = (),
) -> Schema:
    """Classify each column of an all-string frame into a :class:`Role`.

    Args:
        raw: An all-string DataFrame as produced by :func:`read_table` (with
            missing values as empty strings).
        source_format: The detected source format, recorded on the schema.
        derived: Optional mapping of ``derived_column -> source_url_column`` for
            URL-expanded columns.
        entity_columns: Explicit user override — see :func:`load`. Applied
            before the primary timestamp / row id are picked, so a coerced
            column can never simultaneously hold those posts.
        content_columns: Explicit user override — see :func:`load`.

    Returns:
        The inferred :class:`Schema`.

    Raises:
        ValueError: If an override names an unknown column or the same column
            appears in both overrides.
    """

    derived = derived or {}
    columns = [
        _classify_column(name, raw[name], derived_from=derived.get(name))
        for name in raw.columns
    ]
    _apply_overrides(columns, entity_columns, content_columns)
    schema = Schema(
        columns=columns,
        n_rows=int(raw.shape[0]),
        source_format=source_format,
    )
    schema.url_columns = schema.columns_with_role(Role.URL)
    schema.primary_timestamp = _pick_primary_timestamp(columns)
    schema.row_id = _pick_row_id(columns)
    return schema


def _apply_overrides(
    columns: list[ColumnSchema],
    entity_columns: Sequence[str],
    content_columns: Sequence[str],
) -> None:
    """Mark explicit user schema overrides on ``columns``, in place.

    Default-off: with both sequences empty (the default everywhere) this is a
    no-op and behaviour is identical to inference alone. An entity override
    coerces the column to the categorical role so the typed frame keeps its raw
    string values and the standard categorical/entity/actor machinery sees it;
    identity-shape tests are bypassed downstream via the ``entity_override``
    mark (see ``features._entity_columns`` / ``_actor_endpoint_columns``).
    A content override only marks the column; exclusion happens in
    ``features._is_content_column``.
    """

    overlap = set(entity_columns) & set(content_columns)
    if overlap:
        raise ValueError(
            "Columns named as both entity and content overrides: "
            + ", ".join(sorted(overlap))
        )
    by_name = {col.name: col for col in columns}
    for kind, names in (("entity", entity_columns), ("content", content_columns)):
        unknown = [name for name in names if name not in by_name]
        if unknown:
            raise ValueError(
                f"Unknown {kind}-column override(s): "
                + ", ".join(sorted(unknown))
                + f" (available: {', '.join(sorted(by_name))})"
            )
    for name in entity_columns:
        col = by_name[name]
        col.entity_override = True
        if col.role != Role.CATEGORICAL:
            col.role = Role.CATEGORICAL
            col.datetime_format = None
            col.numeric_subtype = None
    for name in content_columns:
        by_name[name].content_override = True


# --- Format detection & reading ---------------------------------------------


def _detect_format(path: Path, sample: str) -> str:
    ext = path.suffix.lower()
    if ext in (".jsonl", ".ndjson"):
        return "jsonl"
    if ext == ".json":
        return "jsonl" if _looks_like_jsonl(sample) else "json"
    if ext in (".tsv", ".tab"):
        return "tsv"
    if ext == ".csv":
        return "csv"

    stripped = sample.lstrip()
    if stripped[:1] == "[":
        return "json"
    if stripped[:1] == "{":
        return "jsonl" if _looks_like_jsonl(sample) else "json"
    return "tsv" if _sniff_delimiter(sample) == "\t" else "csv"


def _looks_like_jsonl(sample: str) -> bool:
    lines = [line for line in sample.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    parsed = 0
    for line in lines[:20]:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return False
        if isinstance(obj, dict):
            parsed += 1
    return parsed >= 2


def _sniff_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        return "\t" if sample.count("\t") > sample.count(",") else ","


def _read_delimited(path: Path, source_format: str, sample: str) -> pd.DataFrame:
    sep = "\t" if source_format == "tsv" else _sniff_delimiter(sample)
    try:
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        has_header = True
    frame = pd.read_csv(
        path,
        sep=sep,
        dtype=str,
        header=0 if has_header else None,
        na_filter=False,
        skip_blank_lines=True,
        engine="python",
        encoding="utf-8",
        encoding_errors="replace",
    )
    if not has_header:
        frame.columns = [f"col{i}" for i in range(frame.shape[1])]
    else:
        frame.columns = [str(name) for name in frame.columns]
    return frame


def _read_json(path: Path, source_format: str) -> pd.DataFrame:
    if source_format == "jsonl":
        records = []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Line {line_number} is not valid JSON: {exc}"
                    ) from exc
    else:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            data = json.load(handle)
        records = _records_from_json(data)
    return pd.json_normalize(records)


def _records_from_json(data: object) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # A wrapper object: use the first list-of-objects value if present,
        # otherwise treat the object itself as a single row.
        for value in data.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
        return [data]
    raise ValueError("Unsupported JSON structure; expected an array or object")


def _stringify(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy where every cell is a string and missing values are ``""``."""

    out = pd.DataFrame(index=range(frame.shape[0]))
    for name in frame.columns:
        column = frame[name]
        missing = column.isna()
        text = column.astype(str)
        text = text.mask(missing, "")
        out[str(name)] = text.to_numpy()
    return out


# --- Column classification ---------------------------------------------------


def _classify_column(
    name: str, series: pd.Series, *, derived_from: str | None
) -> ColumnSchema:
    nonmissing = series[~_missing_mask(series)]
    n_missing = int(series.shape[0] - nonmissing.shape[0])
    n_unique = int(nonmissing.nunique())
    denom = max(nonmissing.shape[0], 1)
    ratio = n_unique / denom
    examples = [str(value) for value in nonmissing.head(5).tolist()]
    sample = nonmissing.head(SAMPLE_SIZE)

    role, datetime_format, numeric_subtype = _role_for(sample, n_unique, ratio)
    return ColumnSchema(
        name=name,
        role=role,
        n_unique=n_unique,
        n_missing=n_missing,
        cardinality_ratio=ratio,
        examples=examples,
        derived_from=derived_from,
        datetime_format=datetime_format,
        numeric_subtype=numeric_subtype,
    )


def _role_for(
    sample: pd.Series, n_unique: int, ratio: float
) -> tuple[str, str | None, str | None]:
    if sample.empty:
        return Role.TEXT, None, None
    if _is_boolean(sample, n_unique):
        return Role.BOOLEAN, None, None
    if _is_url(sample):
        return Role.URL, None, None
    datetime_format, is_ts = _timestamp_format(sample)
    if is_ts:
        return Role.TIMESTAMP, datetime_format, None
    numeric_subtype = _numeric_subtype(sample)
    if numeric_subtype is not None:
        return Role.NUMERIC, None, numeric_subtype
    return _string_role(sample, n_unique, ratio), None, None


def _string_role(sample: pd.Series, n_unique: int, ratio: float) -> str:
    # A near-unique, token-like column is an identifier even when the distinct
    # count is small (e.g. a per-row id in a tiny sample). This must precede the
    # categorical check, which would otherwise claim any low-count column.
    if ratio >= IDENTIFIER_RATIO_MIN and _token_like(sample):
        return Role.IDENTIFIER
    if n_unique <= CATEGORICAL_ABS_MAX or ratio <= CATEGORICAL_RATIO_MAX:
        return Role.CATEGORICAL
    return Role.TEXT


def _is_boolean(sample: pd.Series, n_unique: int) -> bool:
    if n_unique > 2:
        return False
    tokens = {value.strip().lower() for value in sample}
    return bool(tokens) and tokens <= (TRUE_TOKENS | FALSE_TOKENS)


def _is_url(sample: pd.Series) -> bool:
    matches = sum(1 for value in sample if _looks_url(value))
    return matches / max(sample.shape[0], 1) >= URL_RATE


def _looks_url(value: str) -> bool:
    return bool(_URL_RE.search(value.strip()))


def _timestamp_format(sample: pd.Series) -> tuple[str | None, bool]:
    # Pure-number columns (e.g. integer IDs) are never timestamps.
    has_separators = sum(1 for value in sample if _SEPARATOR_RE.search(value))
    if has_separators / max(sample.shape[0], 1) < 0.5:
        return None, False
    for fmt in KNOWN_DATETIME_FORMATS:
        parsed = pd.to_datetime(sample, format=fmt, errors="coerce")
        if parsed.notna().mean() >= PARSE_RATE:
            return fmt, True
    parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    if parsed.notna().mean() >= PARSE_RATE:
        return None, True
    return None, False


def _numeric_subtype(sample: pd.Series) -> str | None:
    parsed = pd.to_numeric(sample, errors="coerce")
    if parsed.notna().mean() < PARSE_RATE:
        return None
    finite = parsed.dropna()
    if not finite.empty and (finite % 1 == 0).all():
        return "int"
    return "float"


def _token_like(sample: pd.Series) -> bool:
    matches = sum(1 for value in sample if _TOKEN_RE.match(value.strip()))
    return matches / max(sample.shape[0], 1) >= 0.90


def _missing_mask(series: pd.Series) -> pd.Series:
    return series.str.strip().str.lower().isin(NA_TOKENS)


def _pick_primary_timestamp(columns: list[ColumnSchema]) -> str | None:
    candidates = [col for col in columns if col.role == Role.TIMESTAMP]
    if not candidates:
        return None
    return min(candidates, key=lambda col: col.n_missing).name


def _pick_row_id(columns: list[ColumnSchema]) -> str | None:
    candidates = [col for col in columns if col.role == Role.IDENTIFIER]
    if not candidates:
        return None
    named = [col for col in candidates if "id" in col.name.lower()]
    pool = named or candidates
    return max(pool, key=lambda col: col.cardinality_ratio).name


# --- URL expansion -----------------------------------------------------------


def _expand_url_columns(raw: pd.DataFrame) -> dict[str, str]:
    """Expand detected URL columns into ``<column>__<field>`` columns in place.

    Returns:
        A mapping of new column name to the source URL column it came from.
    """

    derived: dict[str, str] = {}
    for name in list(raw.columns):
        sample = raw[name][~_missing_mask(raw[name])].head(SAMPLE_SIZE)
        if sample.empty or not _is_url(sample):
            continue
        parsed = [_parse_url_fields(value) for value in raw[name]]
        keys: list[str] = []
        for fields in parsed:
            for key in fields:
                if key not in keys:
                    keys.append(key)
        for key in keys:
            new_name = _unique_column_name(f"{name}__{key}", raw.columns)
            raw[new_name] = [fields.get(key, "") for fields in parsed]
            derived[new_name] = name
    return derived


def _unique_column_name(name: str, existing) -> str:
    """Return ``name`` or a numbered variant that does not collide."""

    if name not in existing:
        return name
    suffix = 1
    while f"{name}_{suffix}" in existing:
        suffix += 1
    return f"{name}_{suffix}"


def _parse_url_fields(value: str) -> dict[str, str]:
    if not value:
        return {}
    parts = urlsplit(value)
    fields: dict[str, str] = {}
    if parts.path:
        fields["path"] = parts.path
    for key, values in parse_qs(parts.query, keep_blank_values=True).items():
        fields[key] = values[-1] if values else ""
    return fields


# --- Typed frame construction ------------------------------------------------


def _typed_frame(raw: pd.DataFrame, schema: Schema) -> pd.DataFrame:
    typed = pd.DataFrame(index=range(raw.shape[0]))
    for col in schema.columns:
        series = raw[col.name]
        typed[col.name] = _typed_column(series, col)
    return typed


def _typed_column(series: pd.Series, col: ColumnSchema) -> pd.Series:
    blanked = series.mask(_missing_mask(series), other=pd.NA)
    if col.role == Role.TIMESTAMP:
        fmt = col.datetime_format
        if fmt:
            return pd.to_datetime(series, format=fmt, errors="coerce")
        return pd.to_datetime(series, errors="coerce", format="mixed")
    if col.role == Role.NUMERIC:
        return pd.to_numeric(blanked, errors="coerce")
    if col.role == Role.BOOLEAN:
        return blanked.str.strip().str.lower().map(_to_bool).astype("boolean")
    return blanked.astype("string")


def _to_bool(value: object) -> object:
    if value in TRUE_TOKENS:
        return True
    if value in FALSE_TOKENS:
        return False
    return pd.NA

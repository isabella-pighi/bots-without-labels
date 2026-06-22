"""Data parsing and feature engineering for Bots Without Labels click events."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite, log1p
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlsplit

import tldextract
from scipy.stats import entropy

EXPECTED_FIELD_COUNT = 6
EVENT_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
EPOCH = datetime(1970, 1, 1)
EXCLUDED_ML_FEATURE_NAMES: frozenset[str] = frozenset({"pld_click_count"})
LOWERCASE_PARAM_NAMES: frozenset[str] = frozenset({"ct", "d", "kl"})
DOMAIN_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=())


@dataclass
class RuleContribution:  # pylint: disable=too-many-instance-attributes
    """Explains one heuristic rule's contribution to an event score.

    Attributes:
        rule_id: Stable machine-readable rule identifier used by reports.
        label: Human-readable rule name.
        reason: Event-specific reason text.
        weight: Nominal rule weight before any supporting-evidence cap.
        observed: Observed value that triggered the rule.
        threshold: Threshold or threshold description used by the rule.
        threshold_mode: Whether the threshold is absolute or adaptive.
        condition: Boolean condition represented as readable text.
        strength: ``strong`` or ``supporting`` evidence family.
        family: Broader rule family such as repetition, timing, or context.
        applied_weight: Weight after caps have been applied.
        capped: Whether the supporting-evidence cap changed this rule's weight.
    """

    rule_id: str
    label: str
    reason: str
    weight: float
    observed: int | float | str
    threshold: int | float | str | None = None
    threshold_mode: str = "absolute"
    condition: str = ""
    strength: str = "strong"
    family: str = "general"
    applied_weight: float = 0.0
    capped: bool = False


@dataclass
class ClickEvent:  # pylint: disable=too-many-instance-attributes
    """Parsed click event and all derived scoring state.

    The parser fills the immutable source fields and URL parameters first.
    Feature engineering, heuristics, ML scoring, and pipeline selection then
    mutate the derived fields in place so later artifact writers can emit a
    complete event record without joining separate structures.
    """

    event_id: str
    event_time: datetime
    region: str
    browser: str
    os: str
    url: str
    params: dict[str, str] = field(default_factory=dict)
    features: list[float] = field(default_factory=list)
    ml_features: list[float] = field(default_factory=list)
    ml_feature_weights: list[float] = field(default_factory=list)
    heuristic_score: float = 0.0
    ml_score: float = 0.0
    combined_score: float = 0.0
    is_bot: int = 0
    evidence_tier: int = 0
    confidence_proxy: str = "NONE"
    operational_tier: str = "monitor"
    heuristic_flag: bool = False
    ml_flag: bool = False
    flags_assigned: bool = False
    std_dev_ttc: float = 999.0
    coefficient_variation_ttc: float = 999.0
    query_entropy: float = 0.0
    unique_chars_ratio: float = 0.0
    query_is_nonsense: int = 0
    apex_domain: str = ""
    pld_click_count: int = 0
    reasons: list[str] = field(default_factory=list)
    rule_contributions: list[RuleContribution] = field(default_factory=list)

    @property
    def domain(self) -> str:
        """Clicked domain from the URL query string, or empty when absent."""

        return self.params.get("d", "")

    @property
    def query(self) -> str:
        """Search query text from the URL query string, or empty when absent."""

        return self.params.get("q", "")

    @property
    def ttc(self) -> int:
        """Time-to-click in milliseconds, or ``-1`` when missing or invalid."""

        return _parse_int_param(self.params.get("ttc"), default=-1)


def parse_clicks(path: str | Path) -> list[ClickEvent]:
    """Parse raw click TSV into click events.

    Args:
        path: Raw input TSV path. The file may include a header row and blank
            lines.

    Returns:
        Parsed click events with decoded query-string parameters.

    Raises:
        ValueError: If a non-header row has the wrong field count or an invalid
            timestamp.
    """

    events: list[ClickEvent] = []
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.rstrip("\r\n")
            if not line:
                continue
            parts = line.split("\t")
            if line_number == 1 and parts[0].lower() == "event_id":
                continue
            if len(parts) != EXPECTED_FIELD_COUNT:
                raise ValueError(
                    f"Line {line_number} has {len(parts)} fields; expected {EXPECTED_FIELD_COUNT}"
                )
            event_id, event_time, region, browser, os_name, url = parts
            parsed_url = urlsplit(url)
            raw_params = parse_qs(parsed_url.query, keep_blank_values=True)
            params = {
                key: _canonical_param_value(key, values[-1] if values else "")
                for key, values in raw_params.items()
            }
            events.append(
                ClickEvent(
                    event_id=event_id,
                    event_time=_parse_event_time(event_time, line_number),
                    region=region.lower(),
                    browser=browser.lower(),
                    os=os_name.lower(),
                    url=url,
                    params=params,
                )
            )
    return events


def _canonical_param_value(key: str, value: str) -> str:
    if key in LOWERCASE_PARAM_NAMES:
        return value.lower()
    return value


def _parse_event_time(value: str, line_number: int) -> datetime:
    try:
        return datetime.strptime(value, EVENT_TIME_FORMAT)
    except ValueError as exc:
        raise ValueError(
            f"Line {line_number} has invalid event_time {value!r}; expected YYYY-MM-DD HH:MM:SS"
        ) from exc


def build_features(events: list[ClickEvent]) -> tuple[list[str], dict[str, Counter]]:
    """Populate feature vectors and return feature metadata for a batch.

    Count features are computed from the whole batch before event-level feature
    vectors are assigned. The model intentionally excludes raw ``kp`` and
    ``sld`` categorical values because their numeric meaning is unknown, but it
    keeps their aggregate counts as context features.

    Args:
        events: Parsed click events to enrich in place.

    Returns:
        A pair of ``(feature_names, counters)`` where ``counters`` contains the
        batch-level counts reused by heuristic rules.
    """

    counters = {
        "domain": Counter(event.domain for event in events),
        "apex_domain": Counter(apex_domain(event.domain) for event in events),
        "query": Counter(event.query for event in events),
        "query_domain": Counter((event.query, event.domain) for event in events),
        "query_apex_domain": Counter(
            (event.query, apex_domain(event.domain)) for event in events
        ),
        "device": Counter((event.region, event.browser, event.os) for event in events),
        "second": Counter(event.event_time for event in events),
        "ttc": Counter(event.ttc for event in events),
        "country": Counter(event.params.get("ct", "") for event in events),
        "landing": Counter(event.params.get("kl", "") for event in events),
        "kp": Counter(event.params.get("kp", "") for event in events),
        "sld": Counter(event.params.get("sld", "") for event in events),
    }
    names = [
        "log_domain_count",
        "pld_click_count",
        "log_apex_domain_count",
        "log_query_count",
        "log_query_domain_count",
        "log_query_apex_domain_count",
        "log_device_count",
        "log_country_count",
        "log_landing_count",
        "log_kp_count",
        "log_sld_count",
        "log_same_second_count",
        "log_ttc_count",
        "hour",
        "log_ttc_seconds",
        "is_sub_200ms_click",
        "log_pseudo_session_10s_click_count",
        "query_entropy",
        "unique_chars_ratio",
        "query_is_nonsense",
        "std_dev_ttc",
        "coefficient_variation_ttc",
    ]
    ml_feature_weights = select_ml_feature_weights(names)
    burst_counts = _pseudo_session_burst_counts(events)
    temporal_stats = _temporal_ttc_stats(events)
    for event in events:
        event_apex_domain = apex_domain(event.domain)
        click_delay_seconds = max(event.ttc, 0) / 1000.0
        query_entropy = _query_entropy(event.query)
        unique_chars_ratio = _unique_chars_ratio(event.query)
        std_dev_ttc, coefficient_variation_ttc = temporal_stats.get(
            id(event), (999.0, 999.0)
        )
        event.query_entropy = query_entropy
        event.unique_chars_ratio = unique_chars_ratio
        event.query_is_nonsense = _query_is_nonsense(
            event.query, counters["query"][event.query]
        )
        event.apex_domain = event_apex_domain
        event.pld_click_count = counters["apex_domain"][event_apex_domain]
        event.std_dev_ttc = std_dev_ttc
        event.coefficient_variation_ttc = coefficient_variation_ttc
        event.features = [
            log1p(counters["domain"][event.domain]),
            float(event.pld_click_count),
            log1p(counters["apex_domain"][event_apex_domain]),
            log1p(counters["query"][event.query]),
            log1p(counters["query_domain"][(event.query, event.domain)]),
            log1p(counters["query_apex_domain"][(event.query, event_apex_domain)]),
            log1p(counters["device"][(event.region, event.browser, event.os)]),
            log1p(counters["country"][event.params.get("ct", "")]),
            log1p(counters["landing"][event.params.get("kl", "")]),
            log1p(counters["kp"][event.params.get("kp", "")]),
            log1p(counters["sld"][event.params.get("sld", "")]),
            log1p(counters["second"][event.event_time]),
            log1p(counters["ttc"][event.ttc]),
            float(event.event_time.hour),
            log1p(click_delay_seconds),
            1.0 if 0 <= event.ttc < 200 else 0.0,
            log1p(burst_counts[id(event)]),
            query_entropy,
            unique_chars_ratio,
            float(event.query_is_nonsense),
            log1p(std_dev_ttc),
            log1p(coefficient_variation_ttc),
        ]
        event.ml_features = _select_ml_features(names, event.features)
        event.ml_feature_weights = ml_feature_weights
    return names, counters


def apex_domain(domain: str) -> str:
    """Return the registrable domain used for subdomain-resistant features."""

    clean = domain.strip().lower().split(":", 1)[0].strip(".")
    if not clean:
        return ""
    extracted = DOMAIN_EXTRACTOR(clean)
    apex = extracted.top_domain_under_public_suffix
    return apex or clean


def select_ml_feature_names(feature_names: list[str]) -> list[str]:
    """Return the subset of feature names used by the anomaly model."""

    return [name for name in feature_names if name not in EXCLUDED_ML_FEATURE_NAMES]


def select_ml_feature_weights(feature_names: list[str]) -> list[float]:
    """Return model feature weights aligned to ``select_ml_feature_names``."""

    return [1.0 for _ in select_ml_feature_names(feature_names)]


def _select_ml_features(feature_names: list[str], values: list[float]) -> list[float]:
    return [
        value
        for name, value in zip(feature_names, values)
        if name not in EXCLUDED_ML_FEATURE_NAMES
    ]


def pseudo_session_groups(
    events: list[ClickEvent],
) -> dict[tuple[str, str, str, str, str], list[ClickEvent]]:
    """Group events by the device/query/domain context used as a pseudo-session."""

    groups: dict[tuple[str, str, str, str, str], list[ClickEvent]] = defaultdict(list)
    for event in events:
        groups[
            (event.region, event.browser, event.os, event.query, event.domain)
        ].append(event)
    return groups


def _pseudo_session_burst_counts(
    events: list[ClickEvent], window_seconds: int = 10
) -> dict[int, int]:
    """Count local click density inside pseudo-session groups.

    Events are grouped by device/query/domain context, then each event receives
    the number of peer clicks within a centred time window. Object IDs are used
    as keys because repeated or missing event IDs should not merge events.
    """

    counts: dict[int, int] = {}
    half_window = window_seconds / 2.0
    for group_events in pseudo_session_groups(events).values():
        ordered = sorted(group_events, key=lambda event: event.event_time)
        timestamps = [(event.event_time - EPOCH).total_seconds() for event in ordered]
        left = 0
        right = 0
        for idx, timestamp in enumerate(timestamps):
            while timestamps[left] < timestamp - half_window:
                left += 1
            while (
                right + 1 < len(timestamps)
                and timestamps[right + 1] <= timestamp + half_window
            ):
                right += 1
            counts[id(ordered[idx])] = right - left + 1
    return counts


def _temporal_ttc_stats(  # pylint: disable=too-many-locals
    events: list[ClickEvent],
) -> dict[int, tuple[float, float]]:
    """Return per-event regularity features from grouped time-to-click deltas.

    Improvement 2: bots can avoid exact same-second bursts while still using
    mechanically regular click delays. Events are grouped by ``(domain, query)``
    so the timing signal is anchored to observable click behaviour without
    relying on ``kp`` or ``sld``. Within each group we sort by event time and
    calculate the standard deviation and coefficient of variation of
    consecutive ``ttc`` differences. Sparse groups receive a high sentinel value
    so they are not treated as mechanically regular.
    """

    grouped: dict[tuple[str, str], list[ClickEvent]] = defaultdict(list)
    for event in events:
        grouped[(event.domain, event.query)].append(event)

    stats: dict[int, tuple[float, float]] = {}
    for group_events in grouped.values():
        ordered = sorted(group_events, key=lambda event: event.event_time)
        ttc_seconds = [event.ttc / 1000.0 for event in ordered if event.ttc >= 0]
        if len(ttc_seconds) < 3:
            value = (999.0, 999.0)
        else:
            deltas = [
                abs(ttc_seconds[idx] - ttc_seconds[idx - 1])
                for idx in range(1, len(ttc_seconds))
            ]
            mean_delta = sum(deltas) / len(deltas)
            variance = sum((delta - mean_delta) ** 2 for delta in deltas) / len(deltas)
            std_dev = variance**0.5
            coefficient_variation = std_dev / mean_delta if mean_delta > 0.0 else 0.0
            value = (std_dev, coefficient_variation)
        for event in group_events:
            stats[id(event)] = value
    return stats


def _query_entropy(query: str) -> float:
    """Return Shannon entropy for a query string.

    Improvement 3: entropy is exposed as a first-class feature so the model can
    distinguish more natural text from unusually repetitive or random-looking
    strings without treating every popular query as suspicious by count alone.
    """

    if not query:
        return 0.0
    total = len(query)
    probabilities = [count / total for count in Counter(query).values()]
    return float(entropy(probabilities, base=2))


def _unique_chars_ratio(query: str) -> float:
    if not query:
        return 0.0
    return len(set(query)) / len(query)


def _query_is_nonsense(query: str, query_count: int) -> int:
    clean = query.strip()
    if not clean:
        return 0
    return int(
        clean.islower() and clean.isalpha() and len(clean) > 4 and query_count < 5
    )


def _parse_int_param(value: str | None, default: int) -> int:
    try:
        parsed = float(value if value is not None else str(default))
        if not isfinite(parsed):
            return default
        return int(parsed)
    except (OverflowError, ValueError):
        return default


def iter_event_dicts(events: Iterable[ClickEvent]) -> Iterable[dict[str, object]]:
    """Yield JSON-serialisable event dictionaries for reports and dashboards."""

    for event in events:
        yield {
            "event_id": event.event_id,
            "event_time": event.event_time.isoformat(sep=" "),
            "region": event.region,
            "browser": event.browser,
            "os": event.os,
            "domain": event.domain,
            "apex_domain": event.apex_domain,
            "pld_click_count": event.pld_click_count,
            "query": event.query,
            "ttc": event.ttc,
            "heuristic_score": round(event.heuristic_score, 4),
            "ml_score": round(event.ml_score, 4),
            "combined_score": round(event.combined_score, 4),
            "is_bot": event.is_bot,
            "evidence_tier": event.evidence_tier,
            "confidence_proxy": event.confidence_proxy,
            "operational_tier": event.operational_tier,
            "std_dev_ttc": round(event.std_dev_ttc, 6),
            "coefficient_variation_ttc": round(event.coefficient_variation_ttc, 6),
            "query_entropy": round(event.query_entropy, 6),
            "unique_chars_ratio": round(event.unique_chars_ratio, 6),
            "query_is_nonsense": event.query_is_nonsense,
            "reasons": event.reasons,
            "rule_contributions": [
                {
                    "rule_id": contribution.rule_id,
                    "label": contribution.label,
                    "reason": contribution.reason,
                    "weight": contribution.weight,
                    "applied_weight": round(contribution.applied_weight, 4),
                    "strength": contribution.strength,
                    "family": contribution.family,
                    "capped": contribution.capped,
                    "observed": contribution.observed,
                    "threshold": contribution.threshold,
                    "threshold_mode": contribution.threshold_mode,
                    "condition": contribution.condition,
                }
                for contribution in event.rule_contributions
            ],
        }

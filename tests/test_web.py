"""Tests for the local dashboard server and static dashboard documents."""

# Pytest test names describe intent; private access is deliberate for narrow
# helper coverage in this local module.
# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access
# pylint: disable=too-many-lines,too-many-locals,too-many-statements,too-few-public-methods

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bots_without_labels import web

SIDEBAR_LABELS = [
    "Overview",
    "Decision Logic",
    "Traffic Explorer",
    "Patterns",
    "Help",
]

OVERVIEW_HEADINGS = [
    "<h2>Executive View</h2>",
    "<h2>Run Scorecard</h2>",
    "<h2>Recommended actions</h2>",
]


def _sidebar_nav_markup(dashboard: str) -> str:
    """Return the sidebar navigation fragment from dashboard HTML."""
    nav_start = dashboard.index('<nav class="sidebar-nav">')
    nav_end = dashboard.index("</nav>", nav_start)
    return dashboard[nav_start:nav_end]


def _overview_markup(dashboard: str) -> str:
    """Return the overview page fragment from dashboard HTML."""
    overview_start = dashboard.index('<section class="page active" id="page-overview">')
    overview_end = dashboard.index('<section class="page" id="page-decision">')
    return dashboard[overview_start:overview_end]


def _page_markup(dashboard: str, page_id: str, next_page_id: str) -> str:
    """Return one dashboard page fragment bounded by the next page."""
    page_start = dashboard.index(f'<section class="page" id="{page_id}">')
    page_end = dashboard.index(f'<section class="page" id="{next_page_id}">')
    return dashboard[page_start:page_end]


def _help_markup(dashboard: str) -> str:
    """Return the inline Help page fragment from dashboard HTML."""
    help_start = dashboard.index('<section class="page" id="page-help">')
    help_end = dashboard.index('<div class="modal-backdrop"', help_start)
    return dashboard[help_start:help_end]


def _help_modal_markup(dashboard: str) -> str:
    """Return the Help modal fragment from dashboard HTML."""
    modal_start = dashboard.index('<div class="modal-backdrop" id="helpModal"')
    modal_end = dashboard.index('<div class="modal-backdrop" id="evidenceModal"')
    return dashboard[modal_start:modal_end]


def _definitions_markup(dashboard: str) -> str:
    """Return the JavaScript definition dictionary fragment."""
    definitions_start = dashboard.index("const definitions = {")
    definitions_end = dashboard.index("    attachNavigation();", definitions_start)
    return dashboard[definitions_start:definitions_end]


def _labels_are_ordered(markup: str, labels: list[str]) -> bool:
    """Check that labels appear in the same order as the expected list."""
    positions = [markup.index(label) for label in labels]
    return positions == sorted(positions)


def _read_text(url: str) -> str:
    """Read a URL as UTF-8 text and close the response."""
    with urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def _read_json(url: str) -> object:
    """Read a URL as JSON and close the response."""
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read())


def _read_request_json(request: Request) -> object:
    """Read a request response as JSON and close the response."""
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def _error_json(request_or_url: Request | str) -> tuple[int, object]:
    """Return an HTTP error response code and JSON body."""
    try:
        with urlopen(request_or_url, timeout=5):
            pass
    except HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        finally:
            exc.close()
    raise AssertionError("request should return an HTTP error")


def test_web_serves_feature_page_and_api(monkeypatch, tmp_path: Path) -> None:
    artifacts = tmp_path / "run-output" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "summary.json").write_text('{"total_events": 1}', encoding="utf-8")
    (artifacts / "selected_events.json").write_text(
        (
            '[{"event_id":"evt_selected","method_bucket":"Heuristic + ML",'
            '"anomaly_class":"compound_burst_replay",'
            '"operational_tier":"suppress"}]'
        ),
        encoding="utf-8",
    )
    (artifacts / "sample_events.json").write_text("[]", encoding="utf-8")
    (artifacts / "features.tsv").write_text(
        "event_id\tlog_domain_count\tlog_ttc_seconds\n"
        "evt_<script>\t1.386294\t0.010000\n"
        "evt_2\t0.693147\t3.000000\n",
        encoding="utf-8",
    )
    (tmp_path / "run-output" / "predictions.tsv").write_text(
        "event_id\tis_bot\nevt_selected\t1\n", encoding="utf-8"
    )
    (tmp_path / "run-output" / "predictions-extended.tsv").write_text(
        "event_id\tis_bot\tevidence_tier\nevt_selected\t1\t1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web, "ROOT", tmp_path)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        dashboard = _read_text(base_url + "/")
        assert 'href="/features"' in dashboard
        assert 'id="uploadModeButton"' not in dashboard
        assert "setInputMode" not in dashboard
        assert 'id="pathModeButton"' not in dashboard
        assert "Server path" not in dashboard
        assert "Upload TSV" not in dashboard
        assert 'class="topbar"' in dashboard
        assert 'class="brand-block"' in dashboard
        assert '<nav class="utility-nav" aria-label="Dashboard tools">' in dashboard
        assert 'class="dataset-runner" aria-label="Dataset source"' in dashboard
        assert 'class="run-actions"' in dashboard
        assert 'id="inputFile"' in dashboard
        assert 'class="file-label" for="inputFile">Choose TSV</label>' in dashboard
        assert 'id="selectedFileName" aria-live="polite">No file selected' in dashboard
        assert "function updateSelectedFile()" in dashboard
        assert "file ? file.name : 'No file selected'" in dashboard
        assert 'id="lastRunPath"' not in dashboard
        assert "function renderLastAnalysedInput(summary)" in dashboard
        assert "!looksLikeTemporaryUploadPath(inputPath)" in dashboard
        assert "function looksLikeTemporaryUploadPath(value)" in dashboard
        assert "path.includes('/var/folders/')" in dashboard
        assert (
            '<button id="runButton" onclick="runPipeline()">Run analysis</button>'
            in dashboard
        )
        assert 'id="uploadInputPanel" class="input-panel"' in dashboard
        assert 'id="pathInputPanel"' not in dashboard
        assert ".input-panel.is-hidden { display:none; }" in dashboard
        assert 'id="inputPath"' not in dashboard
        assert "Choose a local .tsv file to upload and analyse." in dashboard
        assert "Use only when the TSV already exists" not in dashboard
        assert "Only the active mode is submitted" not in dashboard
        assert "await uploadAndRun(file)" in dashboard
        assert "runPath" not in dashboard
        assert "return fetch('/run?input='" not in dashboard
        assert "Choose a TSV file before running the pipeline." in dashboard
        assert "Enter a file path before running the pipeline." not in dashboard
        assert 'id="mlBackend"' not in dashboard
        assert "Bots Without Labels Business Dashboard" in dashboard
        assert "Submission outputs" not in dashboard
        assert "Download final TSV" not in dashboard
        assert "Download extended diagnostics" not in dashboard
        assert "use for review evidence, not evaluator submission" not in dashboard
        # Filters are single-select drop-down menus plus a single-event-ID lookup.
        assert "Pick a value from each drop-down menu" in dashboard
        assert "enter a single event ID to single out one anomaly" in dashboard
        assert "Filters allow multiple values" not in dashboard
        assert "Ctrl-click or Command-click" not in dashboard
        assert 'multiple size="${visibleRows}"' not in dashboard
        assert 'Choose a value, or “All”.' in dashboard
        assert '<option value="">All</option>' in dashboard
        assert 'id="eventIdFilter"' in dashboard
        assert "function applyEventIdFilter(value)" in dashboard
        assert "font-family:Arial, Helvetica, sans-serif;" in dashboard
        assert "--ink:#172026; --muted:#52616d; --line:#cfd7df;" in dashboard
        assert "html { scroll-behavior:smooth; }" in dashboard
        assert "overflow-x:hidden" not in dashboard
        assert ".table-wrap { overflow:auto; contain:inline-size; }" in dashboard
        assert 'href="#dashboardMain" class="skip-link"' in dashboard
        assert 'id="dashboardMain" tabindex="-1"' in dashboard
        assert 'id="pageStatus" aria-live="polite"' in dashboard
        assert "Executive View" in dashboard
        assert "What this run says" not in dashboard
        assert "Business problem" not in dashboard
        assert "What was analysed" not in dashboard
        assert "How to act" not in dashboard
        assert 'id="storyAnalysed"' not in dashboard
        assert 'class="panel analysis-brief-panel"' in dashboard
        assert 'class="analysis-brief-copy"' in dashboard
        assert '<p id="storyLead">Loading current run...</p>' in dashboard
        assert 'id="confidenceExplainer"' in dashboard
        assert '<p id="confidenceExplainer"></p>' in dashboard
        assert (
            ".analysis-brief-panel { width:100%; min-width:0; overflow:visible; }"
            in dashboard
        )
        assert (
            ".analysis-brief-copy { display:grid; gap:10px; width:100%; "
            "max-width:none; min-width:0; }" in dashboard
        )
        assert "max-width:clamp(72ch,78%,104ch)" not in dashboard
        assert (
            ".analysis-brief-copy p { margin:0; color:var(--ink); "
            "font-size:15px; line-height:1.55; overflow-wrap:anywhere; }" in dashboard
        )
        assert (
            "The dashboard explains each decision through evidence tiers" in dashboard
        )
        assert "ML only" in dashboard
        assert "combinedThresholdDescription(s)" in dashboard
        assert "max_distance_descending_fallback" in dashboard
        assert "max-distance fallback" in dashboard
        assert (
            "ML threshold (${thresholdMethodLabel(s.ml_threshold_method)})" in dashboard
        )
        assert "method === 'Kneedle elbow' ? 'EIF Kneedle threshold'" in dashboard
        assert "Kneedle cutoff of" not in dashboard
        # The Threshold Sensitivity panel was removed from Decision Logic.
        assert "Threshold Sensitivity" not in dashboard
        assert "function renderThresholdSensitivity(s)" not in dashboard
        assert 'id="thresholdSensitivity"' not in dashboard
        assert "Advisory threshold sensitivity scenarios" not in dashboard
        assert "Estimated human false-positive risk" not in dashboard
        assert "thresholdRisk(row)" not in dashboard
        assert "thresholdCharacteristics(row)" not in dashboard
        assert "Run Scorecard" in dashboard
        assert "Run at a glance" not in dashboard
        overview_markup = _overview_markup(dashboard)
        assert _labels_are_ordered(overview_markup, OVERVIEW_HEADINGS)
        assert "Explore detected anomalies" not in overview_markup
        assert (
            'class="panel global-filters" aria-labelledby="filterTitle" hidden'
            in dashboard
        )
        assert 'aria-label="Current result proportions"' not in overview_markup
        assert 'id="tierChart"' not in overview_markup
        assert 'id="methodChart"' not in overview_markup
        assert 'id="classChart"' not in overview_markup
        assert "Traffic Explorer" in dashboard
        assert "Patterns" in dashboard
        assert "Decision Logic" in dashboard
        # The Blend Iteration page was removed from the web tool.
        assert "Blend Iteration" not in dashboard
        assert 'id="page-blend"' not in dashboard
        assert "This is a separate executable review step" not in dashboard
        assert "Download optional blend TSV" not in dashboard
        assert "function renderWeakSupervisionBlend" not in dashboard
        assert "LabelModel.predict_proba(L=label_matrix)[:, 1]" not in dashboard
        assert "Max Score" in dashboard
        assert "Decision rule" in dashboard
        assert "Decision method" not in dashboard
        assert "Decision formula" not in dashboard
        assert "Method/Tier Breakdown" not in dashboard
        assert "Technical Evidence" not in dashboard
        assert "Help" in dashboard
        nav_markup = _sidebar_nav_markup(dashboard)
        assert _labels_are_ordered(
            nav_markup, [f">{label}</button>" for label in SIDEBAR_LABELS]
        )
        assert 'data-page="classes"' not in nav_markup
        assert (
            '<button type="button" class="nav" data-page="overview" '
            'aria-current="page" onclick="showPage(\'overview\')">Overview' in dashboard
        )
        assert 'data-page="breakdown"' not in nav_markup
        assert "showPage('breakdown')" not in dashboard
        assert 'data-page="technical"' not in nav_markup
        assert "showPage('technical')" not in dashboard
        assert (
            '<button type="button" class="nav" data-page="explorer" '
            "onclick=\"showPage('explorer')\">Traffic Explorer" in dashboard
        )
        assert "let navigationAttached = false;" in dashboard
        assert "if (navigationAttached) return;" in dashboard
        assert "navigationAttached = true;" in dashboard
        assert dashboard.index("attachNavigation();") < dashboard.index(
            "async function load()"
        )
        assert "button.onclick = () => showPage(button.dataset.page);" in dashboard
        assert 'class="app-shell"' in dashboard
        assert '<aside class="sidebar" aria-label="Dashboard sections">' in dashboard
        assert '<nav class="sidebar-nav">' in dashboard
        assert (
            '<nav class="sidebar-nav" aria-label="Dashboard sections">' not in dashboard
        )
        assert "header { position:sticky; top:0; z-index:20;" in dashboard
        assert ".dataset-runner { display:grid;" in dashboard
        assert ".file-picker { display:flex;" in dashboard
        assert ".visually-hidden-input:focus + .file-label" in dashboard
        assert (
            ".app-shell { display:grid; grid-template-columns:240px minmax(0,1fr);"
            in dashboard
        )
        assert ".sidebar { position:sticky; top:0;" in dashboard
        assert ".workspace { min-width:0; width:100%;" in dashboard
        assert (
            ".global-filters { position:relative; z-index:1; padding:12px; }"
            in dashboard
        )
        assert "top:122px" not in dashboard
        assert ".control-head { display:flex;" in dashboard
        assert (
            ".filter-grid { grid-template-columns:repeat(4,minmax(160px,1fr)); gap:8px; }"
            in dashboard
        )
        assert (
            ".filter-grid select[multiple] { min-height:116px; width:100%; }"
            in dashboard
        )
        assert (
            ".sidebar-nav { grid-template-columns:repeat(2,minmax(0,1fr)); }"
            in dashboard
        )
        assert (
            ".sidebar-nav button.nav { text-align:center; min-width:0; }" in dashboard
        )
        assert "table { table-layout:fixed; font-size:11px; }" in dashboard
        assert "header { align-items:start; }" in dashboard
        assert "Evidence tiers" not in dashboard
        assert "Method buckets" in dashboard
        assert "How The Classifier Decides" in dashboard
        # Decision Logic page carries a section-5 probability summary.
        assert "<h2>Probability Perspective</h2>" in dashboard
        assert "reasoned operational estimates, not measured probabilities" in dashboard
        assert "Operational likelihood by evidence tier" in dashboard
        assert 'id="probabilityTiers"' in dashboard
        assert 'id="blendedPrecision"' in dashboard
        assert "function renderProbabilitySummary(s)" in dashboard
        assert "renderProbabilitySummary(summary);" in dashboard
        assert "Anomaly classes and handling" not in dashboard
        assert "Recommended actions" in dashboard
        assert "Technical evidence" not in dashboard
        assert "Adaptive rule thresholds" not in dashboard
        assert 'id="ruleStrengths"' not in dashboard
        assert 'id="heuristicThresholds"' not in dashboard
        assert 'id="regionsChart"' in dashboard
        assert 'id="familiesChart"' in dashboard
        assert 'id="contributionsChart"' in dashboard
        assert (
            'id="evidenceModal" role="dialog" aria-modal="true" '
            'aria-labelledby="evidenceTitle" aria-describedby="evidenceSummary"'
            in dashboard
        )
        assert 'id="tierChart"' not in dashboard
        assert 'id="methodChart"' not in dashboard
        assert 'id="classChart"' not in dashboard
        assert 'id="tierChartBreakdown"' not in dashboard
        assert 'id="methodChartBreakdown"' not in dashboard
        assert 'id="classChartBreakdown"' not in dashboard
        assert 'id="classCards"' not in dashboard
        assert 'id="filteringOptions"' not in dashboard
        assert 'id="definitionButtons"' in dashboard
        assert (
            'id="helpModal" role="dialog" aria-modal="true" '
            'aria-labelledby="modalTitle" aria-describedby="modalBody modalExample"'
            in dashboard
        )
        assert 'onclick="if(event.target===this)closeDefinition()"' in dashboard
        assert "openDefinition" in dashboard
        assert "closeDefinition" in dashboard
        assert "openEvidence(eventId)" in dashboard
        assert "closeEvidence" in dashboard
        assert "renderRuleEvidenceCards(event)" in dashboard
        assert 'class="score-button"' in dashboard
        assert (
            'onclick="${handlerAttr(`openEvidence(${jsString(e.event_id)})`)}"'
            in dashboard
        )
        assert "<strong>Observed:</strong>" in dashboard
        assert "<strong>Threshold:</strong>" in dashboard
        assert "<strong>Why it fired:</strong>" in dashboard
        assert "Escape" in dashboard
        assert "event.key === 'Tab'" in dashboard
        assert "event.preventDefault()" in dashboard
        assert "function setBackgroundModalState(open)" in dashboard
        assert "element.inert = open;" in dashboard
        assert "Country / ct" not in dashboard
        assert "Not available in sample_events.json" not in dashboard
        assert "Raw country/ct is not available in the row sample." not in dashboard
        assert "Country/ct: unavailable in row sample" not in dashboard
        assert "Detected anomaly sample" not in dashboard
        assert "All traffic rows unavailable" not in dashboard
        assert "Device cluster (region/browser/OS sample)" not in dashboard
        help_markup = _help_markup(dashboard)
        help_modal_markup = _help_modal_markup(dashboard)
        definitions_markup = _definitions_markup(dashboard)
        assert "Explore detected anomalies" not in help_markup
        assert "Explore detected anomalies" not in help_modal_markup
        assert "Explore detected anomalies" not in definitions_markup
        assert "Open a term for a short business definition and example." in help_markup
        assert 'id="definitionButtons"' in help_markup
        assert "const definitions = {" in definitions_markup
        assert "'Combined tail': [" not in definitions_markup
        # Help definitions mirror the report glossary terms.
        assert "'Extended Isolation Forest (EIF)': [" in definitions_markup
        assert "'rules-based classifier': [" in definitions_markup
        assert "'method bucket': [" in definitions_markup
        assert "'pseudo-session': [" in definitions_markup
        assert "'query_entropy': [" in definitions_markup
        assert "Shannon entropy of the query characters" in definitions_markup
        # The removed weak-supervision feature is not defined in Help.
        assert "Snorkel" not in definitions_markup
        assert "Weak supervision" not in definitions_markup
        assert "Explore detected anomalies" in dashboard
        assert '<h2 id="filterTitle">Explore detected anomalies</h2>' in dashboard
        assert (
            "globalFilters.hidden = !['explorer', 'patterns'].includes(page)"
            in dashboard
        )
        assert "Clear filters" in dashboard
        assert (
            "Compact row-level controls for the full selected anomaly set." in dashboard
        )
        assert "View data" not in dashboard
        assert "Export CSV" in dashboard
        assert 'id="sampleKpis"' not in dashboard
        assert "renderSampleKpis" not in dashboard
        assert "Filtered anomalies" not in dashboard
        assert "Suppress rows" not in dashboard
        assert "Unique domains" not in dashboard
        assert 'id="sampleTierChart"' not in dashboard
        assert 'class="chart-body" id="sampleMethodChart"' in dashboard
        assert 'id="sampleDomainChart"' in dashboard
        explorer_markup = _page_markup(dashboard, "page-explorer", "page-patterns")
        assert _labels_are_ordered(
            explorer_markup,
            [
                "<h3>Method buckets (selected events only)</h3>",
                "<h3>Flagged regions</h3>",
                "<h3>Rule families</h3>",
                "<h3>Rule contributions</h3>",
                "<h3>Apex domains</h3>",
            ],
        )
        assert "<h3>Evidence tiers</h3>" not in explorer_markup
        assert "<h3>Top bot signals</h3>" not in explorer_markup
        assert "<h3>Reasons</h3>" not in explorer_markup
        assert 'class="chart-grid explorer-chart-grid"' in explorer_markup
        assert 'class="card explorer-card-tiers"' not in explorer_markup
        assert 'class="card explorer-card-regions"' in explorer_markup
        assert 'class="card explorer-card-methods"' in explorer_markup
        assert 'class="card explorer-card-classes"' not in explorer_markup
        assert 'class="card explorer-card-families"' in explorer_markup
        assert 'class="card explorer-card-reasons"' not in explorer_markup
        assert 'class="card explorer-card-contributions"' in explorer_markup
        assert 'class="card explorer-card-domains"' in explorer_markup
        assert 'class="card explorer-card-signals"' not in explorer_markup
        assert 'id="tierChartBreakdown"' not in explorer_markup
        assert 'id="regionsChart"' in explorer_markup
        assert 'id="classChartBreakdown"' not in explorer_markup
        assert explorer_markup.index('id="sampleMethodChart"') < explorer_markup.index(
            'id="regionsChart"'
        )
        assert explorer_markup.index('id="regionsChart"') < explorer_markup.index(
            'id="familiesChart"'
        )
        assert explorer_markup.index('id="familiesChart"') < explorer_markup.index(
            'id="contributionsChart"'
        )
        assert explorer_markup.index('id="contributionsChart"') < explorer_markup.index(
            'id="sampleDomainChart"'
        )
        assert "Filtered anomaly tiers" not in dashboard
        assert (
            ".explorer-chart-grid { grid-template-columns:repeat(2,minmax(0,1fr)); "
            'grid-template-areas:"methods regions" "families contributions" '
            '"domains domains"; }'
            in dashboard
        )
        assert (
            '.explorer-chart-grid { grid-template-areas:"methods" '
            '"regions" "families" "contributions" "domains"; }' in dashboard
        )
        assert (
            ".evidence-row { display:grid; gap:5px; width:100%; padding:8px; "
            "border:1px solid var(--line); border-radius:6px; "
            "background:#fbfcfc; color:var(--ink); text-align:left; font-size:12px; }"
            in dashboard
        )
        assert "button.evidence-row { cursor:pointer; }" in dashboard
        assert ".score-button { border:1px solid var(--line);" in dashboard
        assert "const interactive = Boolean(filterName);" in dashboard
        assert "const legendTag = interactive ? 'button' : 'div';" in dashboard
        assert (
            "const legendClass = interactive ? 'legend-row clickable' : 'legend-row';"
            in dashboard
        )
        assert "renderDonut('tierChartBreakdown', 'Evidence tiers', " not in dashboard
        assert "renderDonut('classChartBreakdown', 'Anomaly classes', " not in dashboard
        assert (
            "renderDonut('sampleMethodChart', 'Method buckets (selected events only)', "
            "countBy(rows, methodBucket), 'events', '', "
            "'filtered selected-event set')" in dashboard
        )
        assert (
            "renderDonut('regionsChart', 'Flagged regions', s.bot_regions || [], "
            not in dashboard
        )
        assert (
            "renderDonut('regionsChart', 'Flagged regions', "
            "countBy(rows, e => e.region), 'events', '', "
            "'filtered detected anomaly set')" in dashboard
        )
        assert (
            "renderDonut('familiesChart', 'Rule families', "
            "countFamilies(rows), 'tags', '', "
            "'filtered selected-event set')" in dashboard
        )
        assert (
            "renderDonut('contributionsChart', 'Rule contributions', "
            "countContributions(rows), 'tags', '', "
            "'filtered selected-event set')" in dashboard
        )
        assert "renderEvidenceBars('reasons'," not in dashboard
        assert "function countReasons(rows)" not in dashboard
        assert "function normalizeReason(reason)" not in dashboard
        assert "function countFamilies(rows)" in dashboard
        assert "function countContributions(rows)" in dashboard
        assert (
            "renderEvidenceBars('sampleDomainChart', countBy(rows, e => "
            "e.apex_domain || e.domain), "
            "rows.length, 'domain')" in dashboard
        )
        assert 'select id="filter-${name}"' in dashboard
        assert 'select id="filter-${name}" multiple' not in dashboard
        assert 'id="classSelectionNote"' not in dashboard
        assert "row-level filtering is not available for this class" not in dashboard
        assert "class-card clickable selected" not in dashboard
        assert (
            "Use the legend buttons below to apply filters with a keyboard."
            in dashboard
        )
        assert "clearFilters()" in dashboard
        assert "exportSelection()" in dashboard
        assert "export_scope" in dashboard
        assert "))).join('\\n');" in dashboard
        assert "))).join('\n');" not in dashboard
        assert "Filtered top-250 highest-risk suppress sample" not in dashboard
        assert "Filtered selected-event diagnostic export" in dashboard
        assert "full-run aggregate; not affected by explorer filters" not in dashboard
        assert "filtered detected anomaly set" in dashboard
        assert (
            "Full-run aggregate. Explorer filters do not change these KPI cards."
            not in dashboard
        )
        assert "sample filters do not change them" not in dashboard
        assert "Overview charts use full-run aggregates" not in dashboard
        assert "Apex domains" in dashboard
        assert "Rows below are the selected candidate-bot events" in dashboard
        assert "<code>run-output/artifacts/selected_events.json</code>" in dashboard
        assert "why a row was selected" in dashboard
        assert "Top query terms in detected anomalies" in dashboard
        assert "Top query/domain combinations" in dashboard
        assert "Summary top queries" in dashboard
        assert 'id="activeFilters"' in dashboard
        assert 'id="filteredEvents"' in dashboard
        assert 'id="explorerPagination"' in dashboard
        assert "const EXPLORER_PAGE_SIZE = 100;" in dashboard
        assert "function changeExplorerPage(direction)" in dashboard
        assert (
            "const pageRows = rows.slice(start, start + EXPLORER_PAGE_SIZE);"
            in dashboard
        )
        assert 'id="sampleQueries"' in dashboard
        assert 'id="queryDomainPairs"' in dashboard
        assert 'id="summaryQueries"' in dashboard
        assert 'role="img"' in dashboard
        assert 'aria-label="${escapeHtml(label)} donut chart"' in dashboard
        assert "tierChart donut chart" not in dashboard
        assert "classChart donut chart" not in dashboard
        assert "The binary prediction" in dashboard
        assert "The suggested handling action for an event" in dashboard
        assert "A high-confidence candidate" in dashboard
        assert "Traffic to hold, delay, sample" in dashboard
        assert "Traffic not selected for action" in dashboard
        assert "Bounded rules-based score from deterministic bot indicators" in dashboard
        assert "Bounded EIF anomaly score" in dashboard
        assert "Display and sorting aid: max(heuristic_score, ml_score)" in dashboard
        assert "'Combined tail': [" not in dashboard
        assert "blended combined score passed the run threshold" not in dashboard
        assert "open the most suspicious rows first" in dashboard
        assert "run-specific Kneedle cutoff" not in dashboard
        assert "dynamic_snorkel_elbow_threshold" not in dashboard
        assert "based on which classifiers fired" in dashboard
        assert "not measured precision" in dashboard
        assert "accuracy can be estimated but not measured" in dashboard
        assert "Review-priority signal" not in dashboard
        assert "Click events in the current run." not in dashboard
        assert "`is_bot = 1` events." not in dashboard
        assert "Share of traffic selected." not in dashboard
        assert "Run-specific combined-score cutoff." not in dashboard
        assert "Policy approval required." not in dashboard
        assert "Keep for trend tracking." not in dashboard
        assert '<div class="label">${escapeHtml(note)}</div>' not in dashboard
        assert "The run-specific cutoff used by the ML classifier" in dashboard
        assert "fixed high-evidence cutoff" in dashboard
        assert 'carries no trusted "bot or not" answer' in dashboard
        assert "Anomaly classes are operational review groups" not in dashboard
        assert "not proven fraud labels" not in dashboard
        assert "ML-only traffic should be sampled or quarantined" not in dashboard
        assert "not a confirmed fraud label" in dashboard
        assert '<p class="label">${escapeHtml(definitions[tier])}</p>' not in dashboard
        assert '<section class="panel">' in dashboard
        assert 'style="margin-bottom' not in dashboard
        assert "renderRuleStrengths(s.rule_strengths || {})" not in dashboard
        assert (
            "renderHeuristicThresholds(s.heuristic_thresholds || {})" not in dashboard
        )
        assert "Supporting rule score is capped at" not in dashboard
        assert "strong rule evidence is not capped" not in dashboard
        assert "97.5th-percentile combined score" not in dashboard
        assert "threshold, floor" not in dashboard
        assert "% percentile" not in dashboard
        assert "Rule evidence" in dashboard
        assert "item.family || item.rule_family || 'general'" in dashboard
        assert "+${applied} applied of +${raw} raw" in dashboard
        assert "method_disagreement || []" not in dashboard
        assert "function renderMethodChart" not in dashboard
        assert (
            "renderMethodChart(s.method_disagreement || [], 'methodChart', "
            not in dashboard
        )
        assert (
            "renderMethodChart(s.method_disagreement || [], 'methodChartBreakdown', "
            not in dashboard
        )
        assert "function renderExplorer(rows)" in dashboard
        assert "arguments.length" not in dashboard
        assert "renderQueries(sampleEvents, summary)" not in dashboard
        assert "fetch('/api/anomalies')" in dashboard
        assert "fetch('/api/events')" not in dashboard
        assert "updateFilteredViews()" in dashboard
        assert "updateFilteredViews(true)" in dashboard
        assert "methodBucket(event)" in dashboard
        assert "deviceLabel(event)" in dashboard
        assert "renderEvidenceBars('sampleDomainChart'" in dashboard
        assert "rows.length, 'domain')" in dashboard
        assert "applyBarFilter" in dashboard
        assert "toggleFilterValue(name, value)" in dashboard
        assert "Anomaly class aggregate only:" not in dashboard
        assert "filter-query" not in dashboard
        assert "filter-device" not in dashboard
        assert "filter-focus" not in dashboard
        assert 'class="method-bars" role="img"' not in dashboard
        assert "Method buckets bar chart for review-relevant events" not in dashboard
        assert "label !== 'Neither strong'" not in dashboard
        assert "excluded from this review-bucket chart" not in dashboard
        assert "renderDonut('tierChart', 'Operational tiers', " not in dashboard
        assert "renderDonut('classChart', 'Anomaly classes', " not in dashboard
        assert "(s.anomaly_classes || {}).classes || []" not in dashboard
        assert "const classes = anomaly.classes || [];" not in dashboard
        assert "0.90 ML agreement" not in dashboard

        features_page = _read_text(base_url + "/features")
        assert "Bots Without Labels Features" in features_page
        assert "font-family:Arial, Helvetica, sans-serif;" in features_page
        assert "--ink:#172026; --muted:#52616d; --line:#cfd7df;" in features_page
        assert "escapeHtml" in features_page
        assert 'id="nextButton"' in features_page
        assert "No rows found at offset" in features_page

        with urlopen(base_url + "/predictions.tsv", timeout=5) as response:
            assert response.headers["Content-Type"] == (
                "text/tab-separated-values; charset=utf-8"
            )
            assert response.headers["Content-Disposition"] == (
                'attachment; filename="predictions.tsv"'
            )
            assert response.read().decode("utf-8") == (
                "event_id\tis_bot\nevt_selected\t1\n"
            )

        with urlopen(base_url + "/predictions-extended.tsv", timeout=5) as response:
            assert response.headers["Content-Type"] == (
                "text/tab-separated-values; charset=utf-8"
            )
            assert response.headers["Content-Disposition"] == (
                'attachment; filename="predictions-extended.tsv"'
            )
            assert response.read().decode("utf-8") == (
                "event_id\tis_bot\tevidence_tier\nevt_selected\t1\t1\n"
            )

        payload = _read_json(base_url + "/api/features?limit=1")
        assert payload["feature_names"] == ["log_domain_count", "log_ttc_seconds"]
        assert payload["rows"] == [
            {"event_id": "evt_<script>", "features": [1.386294, 0.01]}
        ]
        assert payload["next_offset"] == 1

        anomalies = _read_json(base_url + "/api/anomalies")
        assert anomalies == [
            {
                "event_id": "evt_selected",
                "method_bucket": "Heuristic + ML",
                "anomaly_class": "compound_burst_replay",
                "operational_tier": "suppress",
            }
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_reports_malformed_dashboard_artifacts(monkeypatch, tmp_path: Path) -> None:
    artifacts = tmp_path / "run-output" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "summary.json").write_text("{", encoding="utf-8")
    (artifacts / "features.tsv").write_text(
        "event_id\tlog_domain_count\nrow_1\tnot-a-number\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web, "ROOT", tmp_path)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        summary = _read_json(base_url + "/api/summary")
        assert summary == {"error": "summary.json is malformed; run the pipeline again"}

        features = _read_json(base_url + "/api/features")
        assert features == {
            "error": "features.tsv is malformed; run the pipeline again"
        }

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_dashboard_family_and_contribution_pies_use_filtered_rows() -> None:
    """Check the rule-family and rule-contribution pies render from the filtered set."""
    dashboard = web._dashboard_html()

    assert (
        "renderDonut('familiesChart', 'Rule families', "
        "countFamilies(rows), 'tags', '', "
        "'filtered selected-event set')" in dashboard
    )
    assert (
        "renderDonut('contributionsChart', 'Rule contributions', "
        "countContributions(rows), 'tags', '', "
        "'filtered selected-event set')" in dashboard
    )
    assert "renderEvidenceBars('reasons'," not in dashboard
    # The family pie is a coarse rollup over rule_contributions[].family, deduped per
    # event, so it shows different granularity from the per-contribution pie. Both pies
    # dedupe per event (Set) and report a "tags" total, since one event spans several
    # slices; method/region pies report an "events" total (one slice per event).
    assert "function countFamilies(rows)" in dashboard
    assert "item.family || 'unspecified'" in dashboard
    assert "const labels = new Set(" in dashboard
    assert "function countReasons(rows)" not in dashboard
    assert "function normalizeReason(reason)" not in dashboard


def test_dashboard_bar_filter_click_keeps_visible_nav_state() -> None:
    """Check chart filters keep users in a visible nav section."""
    dashboard = web._dashboard_html()
    filter_branch = dashboard[
        dashboard.index("function toggleFilterValue(name, value)") : dashboard.index(
            "function clearFilters()"
        )
    ]

    assert "showPage('explorer');" in filter_branch
    assert "showPage('decision');" not in filter_branch


def test_dashboard_modals_trap_tab_and_restore_focus() -> None:
    """Check modal keyboard handling wraps focus and restores the opener."""
    dashboard = web._dashboard_html()

    assert "let activeModalReturnFocus = null;" in dashboard
    assert "function modalFocusableElements(modal)" in dashboard
    assert "function trapModalFocus(event, modal)" in dashboard
    assert "if (event.shiftKey && document.activeElement === first)" in dashboard
    assert "else if (!event.shiftKey && document.activeElement === last)" in dashboard
    assert "trapModalFocus(event, modal);" in dashboard
    assert "const returnTarget = activeModalReturnFocus;" in dashboard
    assert "activeModalReturnFocus = null;" in dashboard


def test_web_upload_runs_pipeline_and_cleans_temp_file(
    monkeypatch, tmp_path: Path
) -> None:
    calls = []
    original_send_json = web.Handler._send_json

    def fake_run_pipeline(input_path, output_dir, display_input_path=None):
        path = Path(input_path)
        assert path.exists()
        assert (
            path.read_text(encoding="utf-8")
            == "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com\n"
        )
        calls.append((path, output_dir, display_input_path))
        return {"total_events": 1, "ml_backend": "eif"}

    def fake_send_json(handler, payload, status=200):
        if calls:
            assert not calls[0][0].exists()
            assert calls[0][2] == "clicks.tsv"
        original_send_json(handler, payload, status=status)

    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(web.Handler, "_send_json", fake_send_json)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        body, content_type = _multipart(
            {},
            {
                "file": (
                    "clicks.tsv",
                    b"evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com\n",
                )
            },
        )
        request = Request(
            base_url + "/upload",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        payload = _read_request_json(request)
        assert payload == {"total_events": 1, "ml_backend": "eif"}
        assert len(calls) == 1
        assert calls[0][1] == tmp_path / "run-output"
        assert calls[0][2] == "clicks.tsv"
        assert not calls[0][0].exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_upload_reports_missing_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web, "ROOT", tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        body, content_type = _multipart({}, {})
        request = Request(
            base_url + "/upload",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        status, payload = _error_json(request)
        assert status == 400
        assert payload["error"] == "Upload a TSV file before running the pipeline"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_upload_rejects_oversized_body(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "MAX_UPLOAD_BYTES", 1)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        body, content_type = _multipart({}, {"file": ("clicks.tsv", b"too large")})
        request = Request(
            base_url + "/upload",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        status, payload = _error_json(request)
        assert status == 413
        assert "Upload exceeds" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_upload_reports_invalid_upload_and_cleans_temp_file(
    monkeypatch, tmp_path: Path
) -> None:
    temp_paths = []

    def fake_run_pipeline(input_path, _output_dir, display_input_path=None):
        path = Path(input_path)
        assert path.exists()
        assert display_input_path == "bad.tsv"
        temp_paths.append(path)
        raise ValueError("Line 1 has 1 fields; expected 6")

    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "run_pipeline", fake_run_pipeline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        body, content_type = _multipart({}, {"file": ("bad.tsv", b"bad row\n")})
        request = Request(
            base_url + "/upload",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        status, payload = _error_json(request)
        assert status == 400
        assert payload["error"] == "Line 1 has 1 fields; expected 6"
        assert len(temp_paths) == 1
        assert not temp_paths[0].exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_get_run_returns_method_not_allowed(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_run_pipeline(input_path, output_dir):
        calls.append((input_path, output_dir))
        return {"total_events": 0}

    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "run_pipeline", fake_run_pipeline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, payload = _error_json(base_url + "/run?input=clicks.tsv")
        assert status == 405
        assert "Use POST /run" in payload["error"]
        assert not calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_post_run_uses_production_pipeline(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_run_pipeline(input_path, output_dir):
        calls.append((str(input_path), output_dir))
        return {"total_events": 0, "ml_backend": "eif"}

    raw = tmp_path / "clicks.tsv"
    raw.write_text("", encoding="utf-8")
    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "run_pipeline", fake_run_pipeline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        request = Request(
            base_url + "/run",
            data=json.dumps({"input": str(raw)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        payload = _read_request_json(request)
        assert payload == {"total_events": 0, "ml_backend": "eif"}
        assert calls == [(str(raw), tmp_path / "run-output")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_run_rejects_server_path_outside_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web, "ROOT", tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        request = Request(
            base_url + "/run",
            data=json.dumps({"input": "/etc/passwd"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        status, payload = _error_json(request)
        assert status == 400
        assert "Server-side input path must be under" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_run_reports_missing_input_without_errno(
    monkeypatch, tmp_path: Path
) -> None:
    calls = []

    def fake_run_pipeline(input_path, output_dir):
        calls.append((input_path, output_dir))
        return {"total_events": 0}

    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "run_pipeline", fake_run_pipeline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        request = Request(
            base_url + "/run",
            data=json.dumps({"input": "missing.tsv"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        status, payload = _error_json(request)
        assert status == 400
        assert "does not exist" in payload["error"]
        assert "Errno" not in payload["error"]
        assert not calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_validate_server_input_path_normalises_and_rejects_symlinks(
    monkeypatch, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    data_dir = root / "data"
    data_dir.mkdir(parents=True)
    raw = data_dir / "clicks.tsv"
    raw.write_text("", encoding="utf-8")
    linked = root / "linked.tsv"
    linked.symlink_to(raw)

    monkeypatch.setattr(web, "ROOT", root)

    assert web._validate_server_input_path("data/../data/clicks.tsv") == raw
    try:
        web._validate_server_input_path(str(linked))
    except ValueError as exc:
        assert "must not use symlinks" in str(exc)
    else:
        raise AssertionError("server path using a symlink should be rejected")


def test_parse_content_disposition_handles_quotes_and_malformed_values() -> None:
    parsed = web._parse_content_disposition(
        'Content-Disposition: form-data; name="file"; filename="a;b.tsv"'
    )

    assert parsed["name"] == "file"
    assert parsed["filename"] == "a;b.tsv"
    assert web._parse_content_disposition("Content-Disposition: form-data; bad") == {
        "": "form-data"
    }


def test_parse_multipart_form_accepts_quoted_boundary_and_rejects_missing() -> None:
    body, _content_type = _multipart({"note": "review"}, {"file": ("a.tsv", b"row\n")})
    fields, files = web._parse_multipart_form(
        'multipart/form-data; charset=utf-8; boundary="----bots-without-labels-test-boundary"',
        body,
    )

    assert fields == {"note": "review"}
    assert files["file"] == {"filename": "a.tsv", "content": b"row\n"}
    try:
        web._parse_multipart_form("multipart/form-data; boundary=", body)
    except ValueError as exc:
        assert "missing a multipart boundary" in str(exc)
    else:
        raise AssertionError("missing multipart boundary should be rejected")


def test_web_main_accepts_argv_and_starts_monkeypatched_server(monkeypatch) -> None:
    calls = []

    class FakeServer:
        def __init__(self, address, handler) -> None:
            calls.append((address, handler))

        def serve_forever(self) -> None:
            calls.append("served")

    monkeypatch.setattr(web, "ThreadingHTTPServer", FakeServer)

    web.main(["--host", "0.0.0.0", "--port", "0"])

    assert calls == [(("0.0.0.0", 0), web.Handler), "served"]


def _multipart(
    fields: dict[str, str], files: dict[str, tuple[str, bytes]]
) -> tuple[bytes, str]:
    """Build a multipart/form-data body for upload route tests."""
    boundary = "----bots-without-labels-test-boundary"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    for name, (filename, content) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    "Content-Disposition: form-data; "
                    f'name="{name}"; filename="{filename}"\r\n'
                ).encode(),
                b"Content-Type: text/tab-separated-values\r\n\r\n",
                content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

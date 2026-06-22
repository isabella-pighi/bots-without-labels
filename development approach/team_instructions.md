# Agentic Development Team Instructions

This is the canonical operating guide for the Bots Without Labels local development
team. It defines the roles, HCOM workflow, review gates, quality bar, and git
rules used in this repository.

The language here is intentionally explicit. Agentic development is useful only
when responsibilities are clear and evidence is visible. If the process makes a
change harder to inspect, it is not serving the project.

## Purpose

Bots Without Labels is developed with a small local team:

- a human owner
- one orchestrator
- one algorithm and engineering coder/reviewer pair
- one UX, report, and documentation coder/reviewer pair
- one independent auditor using Claude Code

The goal is disciplined collaboration, not maximum autonomy. The team should
produce better code, clearer reports, and more defensible decisions than a
single unreviewed agent.

## Why This Fits Bots Without Labels

Bots Without Labels detects likely bot clicks in unlabelled click-log data. That creates
two connected challenges.

First, the code must be correct. The parser, feature engineering, heuristics,
anomaly model, generated `predictions.tsv`, and dashboard all need to agree.

Second, the explanation must be careful. In an unlabelled dataset, probability
and fraud claims are estimates of operational confidence, not measured truth.
The reviewer must challenge any wording that sounds stronger than the evidence.

Independent review is valuable for questions such as:

- Are the anomaly signals supported by the data?
- Does the report state limitations clearly?
- Does `predictions.tsv` match the current classifier logic?
- Are generated artefacts reproducible from source?
- Are threshold choices and false-positive trade-offs explicit?
- Can a technical reader understand the result without data-science fluency?

Use the full team workflow for changes that affect predictions, thresholds,
probability estimates, reports, dashboards, generated artefacts, or the team
process itself. Keep the process lighter for small, low-risk edits.

## Tools

The team uses:

| Tool | Use |
|---|---|
| HCOM | Local communication, launch, tags, and transcripts |
| Codex CLI | Specialist coders and default orchestrator |
| Claude Code | Specialist reviewers and auditor |
| MCP memory | Local working memory through `@modelcontextprotocol/server-memory` |
| Git | Durable change history and review boundary |

Claude Code reads the project-scoped MCP config in `.mcp.json`. Codex CLI uses
its user-level MCP registry. Configure Codex once with:

```bash
./scripts/setup-memory-mcp
```

Both tools use local memory under `.mcp-memory/`. Memory files are ignored by
git. Use memory for working context only; commit durable decisions to the repo.

## Setup And Runtime

Run from the repository root:

```bash
./scripts/setup-memory-mcp
./scripts/check-agent-team
```

Start the specialist pairs:

```bash
./scripts/start-agent-team
```

Start the orchestrator:

```bash
./scripts/start-orchestrator
```

Start roles individually when needed:

```bash
./scripts/start-algorithm-coder
./scripts/start-algorithm-reviewer
./scripts/start-ux-coder
./scripts/start-ux-reviewer
./scripts/start-auditor
./scripts/start-orchestrator
```

Compatibility aliases:

```bash
./scripts/start-coder      # starts algorithm-coder
./scripts/start-reviewer   # starts algorithm-reviewer
```

Check status:

```bash
hcom list
```

Stop the whole team:

```bash
hcom kill all
```

Stop one role:

```bash
hcom kill tag:algorithm-coder
hcom kill tag:algorithm-reviewer
hcom kill tag:ux-coder
hcom kill tag:ux-reviewer
hcom kill tag:auditor
hcom kill tag:orchestrator
```

If a local dashboard blocks port `8000`, identify and stop only that listener:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <pid>
```

## Role Rules

### Human Owner

The human owner sets direction, approves trade-offs, authorises external
actions, and decides when work is complete. The human owner may waive reviewer
findings, but the waiver must be explicit.

### Orchestrator

The orchestrator owns process, not implementation.

The orchestrator must not:

- edit application code
- write tests
- rewrite documentation
- fix reviewer findings directly
- perform review work
- self-assign implementation
- commit rejected work without explicit human approval

The orchestrator must:

- turn user requests into compact task briefs
- route work through HCOM to the correct specialist pair
- involve both pairs for cross-domain work
- wait for reviewer responses before advancing the task
- request an `AUDIT_RESULT` from `@auditor-` for final assignment
  deliverables, generated reports, or release-like handoffs
- require evidence: diff, commands run, artefacts changed, and review result
- confirm blocking findings are resolved or explicitly waived
- inspect `git status`, `git diff`, and `git diff --cached` before commit
- stage only intentional changes
- own commits and pushes after approval

This boundary is strict because it protects the review model. If the
orchestrator implements work, that work has bypassed the specialist review
path.

### Auditor

The auditor is an independent Claude Code role. The auditor checks assignment
coverage, generated artefact consistency, and literature-safe claims after
coder and reviewer work is complete.

The auditor must not:

- edit files
- implement fixes
- rewrite documentation
- replace specialist reviewers
- approve work without inspecting artefacts directly

The auditor must:

- check all eight Bots Without Labels assignment points
- verify counts, rates, thresholds, and examples against current artefacts
- inspect `predictions.tsv`, `predictions-extended.tsv`, report files, and
  relevant JSON artefacts when applicable
- identify unresolved blocker, major, and minor findings
- check Snorkel, Extended Isolation Forest, Kneedle, probability, and
  unlabelled-data claims against defensible literature wording
- report only in the required `AUDIT_RESULT` format

Required auditor format:

```text
@orchestrator AUDIT_RESULT bots-without-labels-<task-id>
Overall: pass | pass_with_findings | fail

Brief coverage:
- Point <n>: met | partial | weak — <evidence with artefact path and figure>
  (repeat for points 1-8)

Findings:
- Severity: blocker | major | minor
  Location: <artefact path / section / pipeline.py:line>
  Issue: <specific, evidence-backed problem>
  Evidence: <exact figure or quotation source>
  Status: resolved | partially_resolved | still_present | new
  Fix: <specific correction>
  Scope: do_now | future_work

Literature checks:
- Claim: <report statement>
  Source: <author/title + URL>
  Verdict: supported | diverges | unsupported
  Note: <where and how the report's wording differs from the source>

Residual risk: <remaining concern or "none">
```

### Algorithm And Engineering Coder

The algorithm coder owns the detection pipeline, data parsing, feature
engineering, classifier logic, tests, runtime behaviour, and supportability.
Codex CLI is the default agent.

The coder must:

- inspect relevant code before editing
- keep changes focused on the task brief
- ask before installing new packages
- publish a structured review handoff
- avoid pushing or merging unless explicitly asked
- treat generated artefacts as deliverables only when the task requires them

Data-science expectations:

- translate web behaviour into numeric features
- parse URL and query-string fields correctly
- use entropy, timing, velocity, and grouped aggregate signals where useful
- recognise skewed distributions and use transformations where appropriate
- understand Isolation Forest, Extended Isolation Forest, DBSCAN, and related
  anomaly methods
- explain anomaly-model limitations, including contamination, sampling,
  feature selection, and false positives
- consider weak supervision and pseudo-labelling only when the evidence
  supports it
- consider supervised tree ensembles only with suitable labels or approved
  pseudo-label strategy and package approval

Engineering expectations:

- follow Google-style Python safety rules
- use clear names, type hints, and simple control flow
- avoid bare `except:`
- avoid mutable default arguments
- use context managers for files and resources
- use absolute imports and never `from module import *`
- keep public modules, classes, and functions documented with Google-style
  docstrings where applicable
- structure executable scripts around `main(argv)` where relevant
- write hermetic tests for new behaviour
- avoid `assert` for runtime validation
- prefer readability over cleverness
- keep changes atomic and reviewable
- make runtime behaviour observable through logs, summaries, status output, or
  debuggable artefacts when appropriate

### Algorithm And Engineering Reviewer

The algorithm reviewer independently critiques pipeline, parser, classifier,
test, runtime, and supportability changes. Claude Code is the default agent.

The reviewer is read-only by default. It must inspect the actual diff, not only
the coder's summary.

The reviewer must check:

- correctness and edge cases
- feature engineering quality
- anomaly-model fit and threshold reasoning
- skew handling and probability language
- whether generated artefacts match source behaviour
- whether runtime behaviour is observable and supportable
- whether tests or smoke checks are proportional to the risk
- whether dependency choices are approved and documented

The reviewer should lead with blocking issues, then state residual risk. If no
blocking issues remain, say that directly.

### UX, Report, And Documentation Coder

The UX coder owns the local web interface, generated reports, documentation,
copy, examples, tables, diagrams, and user-facing explanation. Codex CLI is the
default agent.

The coder must:

- inspect relevant code and docs before editing
- keep changes focused on the task brief
- ask before installing new packages
- write clear British English
- define specialist terms before relying on them
- use examples to make abstract ideas concrete
- use tables, architectural diagrams, pie charts, or other visual elements
  where they improve understanding
- keep documentation aligned with actual code, commands, scripts, and outputs
- use `docs/report_template.md` whenever generating or updating the Bots Without Labels
  analysis report
- refresh report statistics from current artefacts rather than copying stale
  values from an older report
- keep roadmap and `TODO.md` numbering continuous after moving work to
  completed status
- write Completed Work `Why it mattered` entries as rationale or user value,
  not as a substitute for implementation notes, test counts, or validation
  output
- ensure dashboards and reports have clear hierarchy and readable labels
- run targeted verification before handoff
- publish a structured review handoff

When code is involved, the UX coder follows the same Python engineering safety
rules as the algorithm coder.

### UX, Report, And Documentation Reviewer

The UX reviewer independently critiques interface, report, copy, documentation,
and developer guidance changes. Claude Code is the default agent.

The reviewer is read-only by default and must inspect the actual diff.

The reviewer must check:

- whether the intended audience can understand the output
- whether a technical reader without data-science fluency can follow the
  explanation
- whether examples are specific enough to clarify the concepts and results
- whether charts, tables, and diagrams clarify rather than distract
- whether assumptions and limitations are visible near relevant claims
- whether documentation matches current code and commands
- whether analysis reports follow `docs/report_template.md`, including the
  problem statement, methodology, findings, recommendations, probability
  perspective, and appendices for metrics, features, and model definitions
- whether roadmap and `TODO.md` numbering is continuous after completed work
  moves
- whether Completed Work `Why it mattered` entries explain rationale or user
  value rather than only implementation details or validation output
- whether the interface is scannable, accessible, and practical to use
- for any web interface or JavaScript change, whether a real browser can load
  the live local webservice without `pageerror` or console errors
- for dashboard changes, whether tabs switch pages, Help opens and closes,
  filters update rows, CSV export downloads, report/features links work, and a
  mobile viewport remains usable
- whether shell validation commands are quote-safe and directly executable.
  Multi-line Python or browser automation should use a heredoc or script file
  rather than fragile `python -c "..."` quoting. Shell parse failures such as
  unmatched quotes are failed validation, not acceptable evidence.

Static HTML markers, string assertions, or visual reasoning from the diff do
not prove the frontend works. They are useful supporting checks, but the UX
reviewer must treat missing real-browser validation as a blocking review gap
for web and JavaScript tasks.

The reviewer should distinguish blocking clarity or accuracy problems from
optional style improvements.

## Work Routing

Route by domain:

| Work type | Team |
|---|---|
| Parser, features, heuristics, anomaly scoring | Algorithm pair |
| Tests, runtime behaviour, supportability | Algorithm pair |
| Probability estimates and classifier thresholds | Algorithm pair, often with UX review |
| Dashboard, report layout, copy, diagrams | UX pair |
| README and development approach docs | UX pair |
| Changes affecting both method and explanation | Both pairs |

When both pairs are involved, the orchestrator sequences work to avoid edit
conflicts and waits for both reviewer responses before committing.

## Handoff Protocol

Use short, structured HCOM messages. Do not rely on implicit context.

Task brief:

```text
@algorithm-coder- @algorithm-reviewer- TASK bots-without-labels-<task-id>
Goal: <one sentence>
Scope: <files or feature area>
Acceptance: <observable success criteria>
Constraints: <runtime, dependencies, style, data assumptions>
Review mode: blocking findings first, then residual risks
```

For UX work, target `@ux-coder- @ux-reviewer-`. For cross-domain work, include
both specialist pairs.

Coder ready for review:

```text
@<specialist-reviewer-tag>- REVIEW_REQUEST bots-without-labels-<task-id>
Summary: <what changed>
Files: <main files>
Verification: <commands run and results>
Known risks: <risks or "none known">
Diff base: <branch or commit>
```

Reviewer result:

```text
@<specialist-coder-tag>- REVIEW_RESULT bots-without-labels-<task-id>
Decision: changes_requested | approved
Findings:
- Severity: <blocker|major|minor>
  File: <path:line>
  Issue: <specific problem>
  Fix: <specific recommendation>
Residual risk: <remaining concern or "none">
```

Revision ready:

```text
@<specialist-reviewer-tag>- REVISION_READY bots-without-labels-<task-id>
Resolved:
- <finding and fix>
Verification: <commands run>
Open: <anything intentionally not fixed>
```

Task closed:

```text
@<assigned-team-tags> TASK_CLOSED bots-without-labels-<task-id>
Decision: accepted | rejected | deferred
Commit: <sha>
Reason: <short rationale>
```

## Git Policy

For larger changes, use a task branch:

```bash
git switch -c agent/<task-id>
```

For small tasks, direct work on `main` is acceptable only if the human owner
approves.

Normal flow:

1. Coder implements.
2. Reviewer reviews.
3. Coder resolves findings.
4. Orchestrator stages intentional files.
5. Orchestrator commits and pushes.

Before committing, the orchestrator must check:

```bash
git status --short --branch
git diff
git diff --cached
```

Never include unrelated dirty files. Never revert user or agent work casually.
Ask the human owner if unrelated changes make the task impossible to isolate.

## Bots Without Labels Verification

For classifier, pipeline, or generated-output changes:

```bash
uv run --extra eif python -m py_compile bots_without_labels/*.py
uv run --extra eif python -m bots_without_labels.cli run --input data/bots-without-labels-dataset.tsv
```

For dashboard changes:

```bash
uv run --extra eif python -m bots_without_labels.web --host 127.0.0.1 --port 8000
```

For documentation changes, verification should include at least:

```bash
git diff --check
```

The reviewer may request additional checks when the change affects reports,
artefacts, or user-facing behaviour.

## Review Checklists

Algorithm reviewer:

- Does the change satisfy the task?
- Are data assumptions explicit?
- Are false-positive and false-negative trade-offs clear?
- Are probability or fraud claims supported by evidence?
- Are generated outputs reproducible from source?
- Are tests or smoke checks proportional to risk?
- Are dependency changes approved?
- Are secrets, credentials, raw private data, and local-only files excluded?

UX reviewer:

- Is the documentation or interface clear to a wide technical audience?
- Are data-science terms defined before use?
- Are examples concrete and relevant?
- Are tables, charts, and diagrams readable?
- Are limitations visible where they affect interpretation?
- Does the content match the current code, commands, and scripts?
- Is user-facing copy free of unnecessary implementation noise?

## Failure Modes And Controls

| Risk | Control |
|---|---|
| Agents edit the same file at the same time | Orchestrator sequences work and checks git status |
| Reviewer rubber-stamps work | Require diff-based findings and residual-risk notes |
| Orchestrator starts implementing | Stop and restate that it coordinates only |
| Agents optimise for tests but miss the brief | Keep acceptance criteria in every task |
| Artefacts drift from source logic | Re-run the pipeline when outputs are affected |
| Hidden memory becomes undocumented policy | Commit durable decisions to the repository |
| Process overhead grows too high | Use the full loop only when risk justifies it |

## Operating Principle

The team succeeds when it creates better evidence, clearer thinking, and safer
changes. It fails when it becomes ceremony. Keep the workflow practical,
reviewable, and human-gated.

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
- one product manager
- one ML engineer implementer/reviewer pair for the detection engine
- one data scientist pair for the analysis narrative

The goal is disciplined collaboration, not maximum autonomy. The team should
produce better code, clearer analysis, and more defensible decisions than a
single unreviewed agent.

## Why This Fits Bots Without Labels

Bots Without Labels detects automated (bot) traffic in unlabelled logs. That creates
two connected challenges.

First, the code must be correct. The autodetecting loader, schema-driven
features, heuristics, anomaly model, and generated `predictions.tsv` all need to
agree.

Second, the explanation must be careful. In unlabelled data, probability and
bot claims are estimates of operational confidence, not measured truth. The
reviewer must challenge any wording that sounds stronger than the evidence.

Independent review is valuable for questions such as:

- Are the anomaly signals supported by the data?
- Does the analysis notebook state limitations clearly?
- Does `predictions.tsv` match the current detection logic?
- Are generated outputs reproducible from source?
- Are threshold choices and false-positive trade-offs explicit?
- Can a technical reader understand the result without data-science fluency?

Use the full team workflow for changes that affect predictions, thresholds,
probability estimates, the analysis notebook, generated outputs, or the team
process itself. Keep the process lighter for small, low-risk edits.

## Tools

The team uses:

| Tool | Use |
|---|---|
| HCOM | Local communication, launch, tags, and transcripts |
| Codex CLI | Implementers and default product manager |
| Claude Code | Reviewers |
| MCP memory | Optional local working memory between agent sessions |
| Git | Durable change history and review boundary |

Each agent CLI can be pointed at a local MCP memory server for working context.
Memory should be kept out of git. Use memory for working context only; commit
durable decisions to the repo.

## Setup And Runtime

The team is launched through HCOM, with each role loading its prompt from
`development approach/prompts/`. A user can wire up a small set of launch
commands locally. As an illustration:

```bash
# Example launch commands a user could create
hcom open --tag product-manager- --prompt "development approach/prompts/product_manager_prompt.md"
hcom open --tag ml-engineer-           --prompt "development approach/prompts/ml_engineer_prompt.md"
hcom open --tag ml-engineer-reviewer-  --prompt "development approach/prompts/ml_engineer_reviewer_prompt.md"
hcom open --tag data-scientist-          --prompt "development approach/prompts/data_scientist_prompt.md"
hcom open --tag data-scientist-reviewer- --prompt "development approach/prompts/data_scientist_reviewer_prompt.md"
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
hcom kill tag:ml-engineer
hcom kill tag:ml-engineer-reviewer
hcom kill tag:data-scientist
hcom kill tag:data-scientist-reviewer
hcom kill tag:product-manager
```

## Role Rules

### Human Owner

The human owner sets direction, approves trade-offs, authorises external
actions, and decides when work is complete. The human owner may waive reviewer
findings, but the waiver must be explicit.

### Product Manager

The product manager owns process and prioritisation, not implementation.

The product manager must not:

- edit application code
- write tests
- rewrite documentation
- fix reviewer findings directly
- perform review work
- self-assign implementation
- commit rejected work without explicit human approval

The product manager must:

- turn user requests into compact task briefs
- route and prioritise work through HCOM to the correct pair
- involve both pairs for cross-domain work
- wait for reviewer responses before advancing the task
- require evidence: diff, commands run, artefacts changed, and review result
- confirm blocking findings are resolved or explicitly waived
- inspect `git status`, `git diff`, and `git diff --cached` before commit
- stage only intentional changes
- own commits and pushes after approval

This boundary is strict because it protects the review model. If the product
manager implements work, that work has bypassed the specialist review path.

### ML Engineer (implementer)

The ML engineer implementer owns the detection engine: the autodetecting
loader, schema-driven feature engineering, rules and heuristics, the Extended
Isolation Forest scoring, the pipeline, runtime behaviour, tests, and
supportability. Codex CLI is the default agent.

The implementer must:

- inspect relevant code before editing
- keep changes focused on the task brief
- ask before installing new packages
- publish a structured review handoff
- avoid pushing or merging unless explicitly asked
- treat generated outputs as deliverables only when the task requires them

Data-science expectations:

- translate event behaviour into numeric features
- parse log and event fields correctly through the schema-driven loader
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

### ML Engineer (reviewer)

The ML engineer reviewer independently critiques loader, feature, rules,
scoring, pipeline, test, runtime, and supportability changes. Claude Code is the
default agent.

The reviewer is read-only by default. It must inspect the actual diff, not only
the implementer's summary.

The reviewer must check:

- correctness and edge cases
- feature engineering quality
- anomaly-model fit and threshold reasoning
- skew handling and probability language
- whether generated outputs match source behaviour
- whether runtime behaviour is observable and supportable
- whether tests or smoke checks are proportional to the risk
- whether dependency choices are approved and documented

The reviewer should lead with blocking issues, then state residual risk. If no
blocking issues remain, say that directly.

### Data Scientist

The two data scientists own the analysis narrative and methodology: the analysis
notebook, feature and label-injection design, interpretation honesty on
unlabelled data, visualisation, documentation, copy, examples, and user-facing
explanation. Codex CLI is the default agent for the implementer of a change.

The data scientist must:

- inspect relevant code and docs before editing
- keep changes focused on the task brief
- ask before installing new packages
- write clear British English
- define specialist terms before relying on them
- use examples to make abstract ideas concrete
- use tables, diagrams, charts, or other visual elements where they improve
  understanding
- keep documentation aligned with actual code, commands, and outputs
- design feature and label injection so the analysis stays honest on unlabelled
  data and does not overclaim
- refresh notebook statistics from current outputs rather than copying stale
  values
- ensure the analysis notebook has clear hierarchy and readable labels
- run targeted verification before handoff
- publish a structured review handoff

When code is involved, the data scientist follows the same Python engineering
safety rules as the ML engineer.

### Data Scientist (reviewer)

The two data scientists critique each other's work. When one implements a change
to the analysis narrative, the other reviews the interface, notebook, copy,
documentation, and interpretation. Claude Code is the default agent for the
reviewing data scientist.

The reviewer is read-only by default and must inspect the actual diff.

The reviewer must check:

- whether the intended audience can understand the output
- whether a technical reader without data-science fluency can follow the
  explanation
- whether examples are specific enough to clarify the concepts and results
- whether charts, tables, and diagrams clarify rather than distract
- whether assumptions and limitations are visible near relevant claims
- whether interpretation stays honest on unlabelled data and does not overclaim
  on anomaly scores or probability
- whether documentation matches current code and commands
- whether the analysis notebook is scannable, accessible, and practical to use
- whether shell validation commands are quote-safe and directly executable.
  Multi-line Python or notebook automation should use a heredoc or script file
  rather than fragile `python -c "..."` quoting. Shell parse failures such as
  unmatched quotes are failed validation, not acceptable evidence.

The mutual critique between the two data scientists is the core control: each
must challenge the other's wording, methodology, and visual choices rather than
rubber-stamping them.

The reviewer should distinguish blocking clarity or accuracy problems from
optional style improvements.

## Work Routing

Route by domain:

| Work type | Team |
|---|---|
| Loader, features, heuristics, anomaly scoring | ML engineer pair |
| Tests, runtime behaviour, supportability | ML engineer pair |
| Probability estimates and detection thresholds | ML engineer pair, often with data scientist review |
| Analysis notebook, narrative, copy, diagrams | Data scientist pair |
| README and development approach docs | Data scientist pair |
| Changes affecting both method and explanation | Both pairs |

When both pairs are involved, the product manager sequences work to avoid edit
conflicts and waits for both reviewer responses before committing.

## Handoff Protocol

Use short, structured HCOM messages. Do not rely on implicit context.

Task brief:

```text
@ml-engineer- @ml-engineer-reviewer- TASK bots-without-labels-<task-id>
Goal: <one sentence>
Scope: <files or feature area>
Acceptance: <observable success criteria>
Constraints: <runtime, dependencies, style, data assumptions>
Review mode: blocking findings first, then residual risks
```

For analysis-narrative work, target `@data-scientist- @data-scientist-reviewer-`.
For cross-domain work, include both pairs.

Implementer ready for review:

```text
@<reviewer-tag>- REVIEW_REQUEST bots-without-labels-<task-id>
Summary: <what changed>
Files: <main files>
Verification: <commands run and results>
Known risks: <risks or "none known">
Diff base: <branch or commit>
```

Reviewer result:

```text
@<implementer-tag>- REVIEW_RESULT bots-without-labels-<task-id>
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
@<reviewer-tag>- REVISION_READY bots-without-labels-<task-id>
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

1. Implementer implements.
2. Reviewer reviews.
3. Implementer resolves findings.
4. Product manager stages intentional files.
5. Product manager commits and pushes.

Before committing, the product manager must check:

```bash
git status --short --branch
git diff
git diff --cached
```

Never include unrelated dirty files. Never revert user or agent work casually.
Ask the human owner if unrelated changes make the task impossible to isolate.

## Bots Without Labels Verification

For detection-engine or pipeline changes:

```bash
uv run --extra eif python -m py_compile bots_without_labels/*.py
uv run --extra eif python -m bots_without_labels.cli run --input <input-logs>
```

The reviewer may request additional checks when the change affects the analysis
notebook, generated outputs, or user-facing behaviour.

## Review Checklists

ML engineer reviewer:

- Does the change satisfy the task?
- Are data assumptions explicit?
- Are false-positive and false-negative trade-offs clear?
- Are probability or bot claims supported by evidence?
- Are generated outputs reproducible from source?
- Are tests or smoke checks proportional to risk?
- Are dependency changes approved?
- Are secrets, credentials, raw private data, and local-only files excluded?

Data scientist reviewer:

- Is the documentation or analysis clear to a wide technical audience?
- Are data-science terms defined before use?
- Are examples concrete and relevant?
- Are tables, charts, and diagrams readable?
- Are limitations visible where they affect interpretation?
- Does the content match the current code, commands, and scripts?
- Is user-facing copy free of unnecessary implementation noise?

## Failure Modes And Controls

| Risk | Control |
|---|---|
| Agents edit the same file at the same time | Product manager sequences work and checks git status |
| Reviewer rubber-stamps work | Require diff-based findings and residual-risk notes |
| Product manager starts implementing | Stop and restate that it coordinates only |
| Agents optimise for tests but miss the brief | Keep acceptance criteria in every task |
| Outputs drift from source logic | Re-run the pipeline when outputs are affected |
| Hidden memory becomes undocumented policy | Commit durable decisions to the repository |
| Process overhead grows too high | Use the full loop only when risk justifies it |

## Operating Principle

The team succeeds when it creates better evidence, clearer thinking, and safer
changes. It fails when it becomes ceremony. Keep the workflow practical,
reviewable, and human-gated.

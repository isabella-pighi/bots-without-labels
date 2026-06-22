# Community Cheat Sheet: Local Agentic Development Team

This is the short version of the Bots Without Labels development approach. It describes
how to run a small local team of CLI agents with HCOM, Codex, Claude, and MCP
memory.

The central idea is simple: one agent writes, another reviews, and an
orchestrator manages the handoff and git history. The human owner remains in
control of scope and final decisions.

## Team Shape

| Role | Tool | Owns |
|---|---|---|
| Orchestrator | Codex CLI | Task routing, review gates, commits, pushes |
| Algorithm coder | Codex CLI | Data parsing, features, classifiers, tests |
| Algorithm reviewer | Claude Code | Correctness, method, engineering quality |
| UX coder | Codex CLI | Dashboard, reports, README, documentation |
| UX reviewer | Claude Code | Clarity, accessibility, report quality |

The orchestrator does not code. It coordinates and integrates reviewed work.

## Setup

From the repository root:

```bash
./scripts/setup-memory-mcp
./scripts/check-agent-team
```

Expected checks:

```text
ok: hcom
ok: codex
ok: claude
ok: bunx
ok: .mcp.json present
ok: Claude memory MCP connected
ok: Codex memory MCP configured
```

## Start And Stop

Start both specialist pairs:

```bash
./scripts/start-agent-team
```

Start the orchestrator:

```bash
./scripts/start-orchestrator
```

Check status:

```bash
hcom list
```

Stop everything:

```bash
hcom kill all
```

Stop one role:

```bash
hcom kill tag:algorithm-coder
hcom kill tag:algorithm-reviewer
hcom kill tag:ux-coder
hcom kill tag:ux-reviewer
hcom kill tag:orchestrator
```

## Route Work

Algorithm and engineering task:

```text
@algorithm-coder- @algorithm-reviewer- TASK bots-without-labels-<id>
Goal: <one sentence>
Scope: parser/features/classifier/tests/runtime
Acceptance: <observable success criteria>
Review mode: blocking findings first, then residual risks
```

UX, report, or documentation task:

```text
@ux-coder- @ux-reviewer- TASK bots-without-labels-<id>
Goal: <one sentence>
Scope: dashboard/report/copy/docs
Acceptance: <observable success criteria>
Review mode: blocking findings first, then residual risks
```

Use both pairs for cross-domain changes, such as changing classifier behaviour
and updating the report that explains it.

## Handoff Template

Coder to reviewer:

```text
@<reviewer-tag>- REVIEW_REQUEST bots-without-labels-<id>
Summary: <what changed>
Files: <main files>
Verification: <commands run and results>
Known risks: <risks or "none known">
Diff base: <branch or commit>
```

Reviewer to coder:

```text
@<coder-tag>- REVIEW_RESULT bots-without-labels-<id>
Decision: changes_requested | approved
Findings:
- Severity: <blocker|major|minor>
  File: <path:line>
  Issue: <specific problem>
  Fix: <specific recommendation>
Residual risk: <remaining concern or "none">
```

Orchestrator closeout:

```text
@<assigned-team-tags> TASK_CLOSED bots-without-labels-<id>
Decision: accepted | rejected | deferred
Commit: <sha>
Reason: <short rationale>
```

## Quality Bars

Algorithm and engineering:

- readable, typed Python
- Google-style safety rules
- tests proportional to risk
- observable runtime behaviour
- explicit data assumptions
- careful probability language for unlabelled data

UX, report, and documentation:

- clear British English
- definitions for specialist terms
- examples that make the result concrete
- tables, diagrams, charts, or visual elements where helpful
- documentation that matches the code and commands
- accessible, scannable dashboard and report surfaces

## Git Rules

- Normal flow: only the orchestrator commits and pushes.
- Coder implements.
- Reviewer reviews.
- Orchestrator stages only intentional files.
- Rejected work is not committed unless the human owner explicitly waives the
  finding.

Before committing, the orchestrator checks:

```bash
git status --short --branch
git diff
git diff --cached
```

## Bots Without Labels Verification

For classifier or pipeline changes:

```bash
uv run --extra eif python -m py_compile bots_without_labels/*.py
uv run --extra eif python -m bots_without_labels.cli run --input data/bots-without-labels-dataset.tsv
```

For web or report changes:

```bash
uv run --extra eif python -m bots_without_labels.web --host 127.0.0.1 --port 8000
```

If port `8000` is blocked:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <pid>
```

## What To Share

The pattern is worth sharing when the work benefits from independent review:
data science, generated artefacts, dashboards, documentation, and user-facing
claims. It is less useful for tiny edits where the process costs more than the
risk reduction.

The practical lesson is that multi-agent development works best when the roles
are narrow, the handoffs are explicit, and the human owner keeps final
judgement.

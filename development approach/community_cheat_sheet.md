# Community Cheat Sheet: Local Agentic Development Team

This is the short version of the Bots Without Labels development approach. It describes
how to run a small local team of CLI agents with HCOM, Codex, Claude, and MCP
memory.

The central idea is simple: one agent writes, another reviews, and a product
manager handles routing, prioritisation, and git history. The human owner
remains in control of scope and final decisions.

## Team Shape

| Role | Tool | Owns |
|---|---|---|
| Product Manager | Codex CLI | Task routing, prioritisation, review gates, commits, pushes |
| ML Engineer (implementer) | Codex CLI | Loader, features, rules, scoring, pipeline, tests |
| ML Engineer (reviewer) | Claude Code | Correctness, method, engineering quality |
| Data Scientist | Codex CLI | Analysis notebook, narrative, README, documentation |
| Data Scientist (reviewer) | Claude Code | Clarity, interpretation honesty, mutual critique |

The product manager does not code. It routes, prioritises, and integrates
reviewed work.

## Setup

Install HCOM and the agent CLIs you want to use, then launch each role with its
prompt from `development approach/prompts/`. As an illustration, a user could
create launch commands like:

```bash
# Example launch commands a user could create
hcom open --tag product-manager- --prompt "development approach/prompts/product_manager_prompt.md"
hcom open --tag ml-engineer-           --prompt "development approach/prompts/ml_engineer_prompt.md"
hcom open --tag ml-engineer-reviewer-  --prompt "development approach/prompts/ml_engineer_reviewer_prompt.md"
hcom open --tag data-scientist-          --prompt "development approach/prompts/data_scientist_prompt.md"
hcom open --tag data-scientist-reviewer- --prompt "development approach/prompts/data_scientist_reviewer_prompt.md"
```

## Start And Stop

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
hcom kill tag:ml-engineer
hcom kill tag:ml-engineer-reviewer
hcom kill tag:data-scientist
hcom kill tag:data-scientist-reviewer
hcom kill tag:product-manager
```

## Route Work

Detection-engine task:

```text
@ml-engineer- @ml-engineer-reviewer- TASK bots-without-labels-<id>
Goal: <one sentence>
Scope: loader/features/rules/scoring/pipeline/tests
Acceptance: <observable success criteria>
Review mode: blocking findings first, then residual risks
```

Analysis-narrative task:

```text
@data-scientist- @data-scientist-reviewer- TASK bots-without-labels-<id>
Goal: <one sentence>
Scope: analysis notebook/narrative/copy/docs
Acceptance: <observable success criteria>
Review mode: blocking findings first, then residual risks
```

Use both pairs for cross-domain changes, such as changing detection behaviour
and updating the analysis notebook that explains it.

## Handoff Template

Implementer to reviewer:

```text
@<reviewer-tag>- REVIEW_REQUEST bots-without-labels-<id>
Summary: <what changed>
Files: <main files>
Verification: <commands run and results>
Known risks: <risks or "none known">
Diff base: <branch or commit>
```

Reviewer to implementer:

```text
@<implementer-tag>- REVIEW_RESULT bots-without-labels-<id>
Decision: changes_requested | approved
Findings:
- Severity: <blocker|major|minor>
  File: <path:line>
  Issue: <specific problem>
  Fix: <specific recommendation>
Residual risk: <remaining concern or "none">
```

Product manager closeout:

```text
@<assigned-team-tags> TASK_CLOSED bots-without-labels-<id>
Decision: accepted | rejected | deferred
Commit: <sha>
Reason: <short rationale>
```

## Quality Bars

ML engineering:

- readable, typed Python
- Google-style safety rules
- tests proportional to risk
- observable runtime behaviour
- explicit data assumptions
- careful probability language for unlabelled data

Analysis and documentation:

- clear British English
- definitions for specialist terms
- examples that make the result concrete
- tables, diagrams, charts, or visual elements where helpful
- documentation that matches the code and commands
- interpretation that stays honest on unlabelled data

## Git Rules

- Normal flow: only the product manager commits and pushes.
- Implementer implements.
- Reviewer reviews.
- Product manager stages only intentional files.
- Rejected work is not committed unless the human owner explicitly waives the
  finding.

Before committing, the product manager checks:

```bash
git status --short --branch
git diff
git diff --cached
```

## Bots Without Labels Verification

For detection-engine or pipeline changes:

```bash
uv run --extra eif python -m py_compile bots_without_labels/*.py
uv run --extra eif python -m bots_without_labels.cli run --input <input-logs>
```

## What To Share

The pattern is worth sharing when the work benefits from independent review:
data science, generated artefacts, analysis narratives, documentation, and
user-facing claims. It is less useful for tiny edits where the process costs
more than the risk reduction.

The practical lesson is that multi-agent development works best when the roles
are narrow, the handoffs are explicit, and the human owner keeps final
judgement.

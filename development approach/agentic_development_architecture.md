# Agentic Development Architecture

This document explains the architecture behind the Bots Without Labels development team.
It is written for technical readers who want to understand why the team is
structured this way, how HCOM is used, and where the review gates sit.

## Architectural Intent

The architecture is a local, CLI-based agent team. It is not a fully autonomous
software factory. The human owner remains accountable for product direction and
final judgement. The agents provide implementation, review, coordination, and
evidence gathering.

The model is deliberately conservative:

- implementation and review are separate
- the orchestrator coordinates but does not code
- commits and pushes happen only after review approval or explicit human waiver
- durable decisions are written to the repository, not left only in memory

This matters for Bots Without Labels because the project blends code and interpretation.
The classifier can run successfully while the explanation is still misleading,
or the report can read well while the underlying artefacts are stale. The team
structure creates checkpoints for both risks.

## System Overview

```text
Human owner
    |
    v
Orchestrator (Codex CLI)
    |
    +--> Algorithm coder (Codex CLI)
    |        |
    |        v
    |    Algorithm reviewer (Claude Code)
    |
    +--> UX coder (Codex CLI)
             |
             v
         UX reviewer (Claude Code)
```

HCOM provides the message bus and agent tags. The repository provides the shared
working state. Git provides the durable change history.

## Role Boundaries

| Role | Does | Does not do |
|---|---|---|
| Human owner | Sets priorities and approves trade-offs | Delegate final accountability |
| Orchestrator | Routes tasks, waits for review, commits, pushes | Implement, test, edit, or self-review |
| Algorithm coder | Changes pipeline, features, classifiers, tests | Push directly in normal flow |
| Algorithm reviewer | Reviews correctness, method, probability claims | Edit files by default |
| UX coder | Changes dashboard, report, docs, and copy | Push directly in normal flow |
| UX reviewer | Reviews clarity, accessibility, and documentation truth | Edit files by default |

The orchestrator boundary is the most important control. If the orchestrator
starts making code or documentation changes, it becomes an unreviewed
implementer. That breaks the review model.

## Why Two Specialist Pairs

Bots Without Labels has two natural domains.

The algorithm and engineering domain covers parsing, feature engineering,
heuristics, anomaly scoring, output generation, tests, runtime behaviour, and
supportability. This pair asks questions such as:

- Does the feature mean what the report says it means?
- Does the model choice match the evidence available?
- Are unlabelled probability claims carefully framed?
- Can the run be reproduced from source?
- Are tests and logs sufficient for a future maintainer?

The UX, report, and documentation domain covers the local dashboard, generated
reports, README content, diagrams, examples, accessibility, and business-facing
explanation. This pair asks questions such as:

- Can a technical reader understand the result without being a data scientist?
- Are assumptions and limitations visible near the claims they affect?
- Do tables, charts, and examples clarify rather than decorate?
- Does the documentation match the current commands and scripts?
- Is the dashboard useful for repeated review rather than just a demo?

Cross-domain changes should go through both pairs. For example, a change to the
bot threshold affects classifier behaviour and also how the result must be
explained to the reader.

## HCOM Runtime Pattern

Run the team from the repository root.

```bash
./scripts/check-agent-team
./scripts/start-agent-team
./scripts/start-orchestrator
```

The expected active tags are:

```text
orchestrator-<name>
algorithm-coder-<name>
algorithm-reviewer-<name>
ux-coder-<name>
ux-reviewer-<name>
```

Messages are routed by tag prefix:

```bash
hcom send @algorithm-coder- "TASK bots-without-labels-001 ..."
hcom send @ux-reviewer- "Please review ..."
```

Use the helper scripts for normal launches because they load the role prompts
from `development approach/prompts/` and set the working directory correctly.

## MCP Memory

The team uses `@modelcontextprotocol/server-memory` as local working memory.
Claude Code reads `.mcp.json`. Codex CLI uses its own registry, configured by:

```bash
./scripts/setup-memory-mcp
```

Memory is useful for continuity across local agent sessions. It is not the
source of truth. Any decision that another contributor should rely on must be
committed in the repository.

## Workflow

1. The human owner states the goal.
2. The orchestrator writes a compact task brief.
3. The orchestrator routes the task to the relevant coder and reviewer tags.
4. The coder inspects the repo, makes focused changes, and runs verification.
5. The coder sends a structured review request.
6. The reviewer inspects the diff and evidence directly.
7. The reviewer approves or requests changes.
8. The coder revises until blocking findings are resolved.
9. The orchestrator checks status, stages only intentional changes, commits,
   and pushes.
10. The orchestrator announces the closeout with the commit SHA.

The work should stay lightweight for low-risk changes. Full review gates are
most valuable when work affects predictions, generated artefacts, probability
claims, reports, dashboard behaviour, or the team process itself.

## Handoff Messages

Task brief:

```text
@<coder-tag>- @<reviewer-tag>- TASK bots-without-labels-<id>
Goal: <one sentence>
Scope: <files or feature area>
Acceptance: <observable success criteria>
Constraints: <dependencies, runtime, style, data assumptions>
Review mode: blocking findings first, then residual risks
```

Coder handoff:

```text
@<reviewer-tag>- REVIEW_REQUEST bots-without-labels-<id>
Summary: <what changed>
Files: <main files>
Verification: <commands run and results>
Known risks: <risks or "none known">
Diff base: <branch or commit>
```

Reviewer response:

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

Task closeout:

```text
@<assigned-team-tags> TASK_CLOSED bots-without-labels-<id>
Decision: accepted | rejected | deferred
Commit: <sha>
Reason: <short rationale>
```

## Review Gates

The reviewer should inspect the actual repository diff, not only the coder's
summary. A good review leads with blocking issues and then states residual risk.

Algorithm review should cover:

- parser and feature correctness
- data assumptions and edge cases
- anomaly model fit and threshold reasoning
- reproducibility of `predictions.tsv` and reports
- test coverage and runtime supportability
- unsupported fraud or probability claims

UX review should cover:

- clarity for a wide technical audience
- British English, plain definitions, and concrete examples
- use of tables, diagrams, charts, or visual aids where helpful
- accessibility and readable hierarchy
- consistency between documentation, scripts, and generated output
- avoidance of unnecessary implementation detail in user-facing copy

## Failure Modes And Controls

| Risk | Control |
|---|---|
| Agents edit the same file concurrently | Orchestrator sequences work and checks git status |
| Reviewer rubber-stamps work | Require diff-based findings and residual-risk notes |
| Orchestrator becomes an implementer | Restate boundary: orchestrator coordinates only |
| Artefacts drift from code | Re-run the pipeline when outputs are affected |
| Agent agreement creates false confidence | Require evidence and human judgement |
| Hidden memory becomes undocumented policy | Commit durable decisions to the repo |
| Process becomes too heavy | Use the full loop only when risk justifies it |

## Design Principle

The team is useful when it improves evidence, review quality, and decision
clarity. It is not useful when it adds ceremony without reducing risk.

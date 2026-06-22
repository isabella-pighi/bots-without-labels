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
- the product manager routes and prioritises but does not code
- commits and pushes happen only after review approval or explicit human waiver
- durable decisions are written to the repository, not left only in memory

This matters for Bots Without Labels because the project blends code and interpretation.
The detection engine can run successfully while the explanation is still
misleading, or the analysis notebook can read well while the underlying outputs
are stale. The team structure creates checkpoints for both risks.

## System Overview

```text
Human owner
    |
    v
Product Manager (Codex CLI, OpenAI)
    |
    +--> ML Engineer (implementer, Claude Code, Claude)
    |        |
    |        v
    |    ML Engineer (reviewer, Codex CLI, OpenAI)
    |
    +--> Data Scientist (Claude Code, Claude)
             |
             v
         Data Scientist (reviewer, Codex CLI, OpenAI)
```

HCOM provides the message bus and agent tags. The repository provides the shared
working state. Git provides the durable change history.

## Role Boundaries

| Role | Does | Does not do |
|---|---|---|
| Human owner | Sets priorities and approves trade-offs | Delegate final accountability |
| Product Manager | Routes and prioritises tasks, waits for review, commits, pushes | Implement, test, edit, or self-review |
| ML Engineer (implementer) | Changes loader, features, rules, scoring, pipeline, tests | Push directly in normal flow |
| ML Engineer (reviewer) | Reviews correctness, method, probability claims | Edit files by default |
| Data Scientist | Tracks the literature, grounds the methodology, and changes the analysis notebook, narrative, docs, and copy | Push directly in normal flow |
| Data Scientist (reviewer) | Critiques theoretical grounding and literature fit, clarity, interpretation honesty, and documentation truth | Edit files by default |

The product manager boundary is the most important control. If the product
manager starts making code or documentation changes, it becomes an unreviewed
implementer. That breaks the review model.

## Why Two Pairs

Bots Without Labels has two natural domains.

The ML engineer pair owns the detection engine: the autodetecting loader,
schema-driven feature engineering, rules and heuristics, the Extended Isolation
Forest scoring, the pipeline, output generation, tests, runtime behaviour, and
supportability. This pair asks questions such as:

- Does the feature mean what the analysis says it means?
- Does the model choice match the evidence available?
- Are unlabelled probability claims carefully framed?
- Can the run be reproduced from source?
- Are tests and logs sufficient for a future maintainer?

The data scientist pair owns the theoretical approach and the analysis
narrative: the relevant academic and industry literature (for example isolation
forests and the Extended Isolation Forest, unsupervised anomaly detection, weak
supervision and label injection, score calibration, and bot and fraud-detection
practice), the grounding of the detection methodology in that literature, the
analysis notebook, feature and label-injection design, interpretation honesty on
unlabelled data, visualisation, README content, diagrams, examples, and
accessibility. They ground feature design, the rule families, the anomaly-model
choice, threshold selection, and the label-injection evaluation in the
literature, and flag where the approach diverges from or is unsupported by it.
The two data scientists critique each other's work, asking questions such as:

- Is the methodology grounded in the cited literature, and are divergences flagged?
- Are the theoretical claims consistent with the cited evidence?
- Can a technical reader understand the result without being a data scientist?
- Are assumptions and limitations visible near the claims they affect?
- Does the analysis avoid overclaiming on unlabelled data?
- Do tables, charts, and examples clarify rather than decorate?
- Does the documentation match the current commands and scripts?

Cross-domain changes should go through both pairs. For example, a change to the
bot threshold affects detection behaviour and also how the result must be
explained to the reader.

## HCOM Runtime Pattern

Each role runs as an HCOM agent and loads its prompt from
`development approach/prompts/`. The expected active tags are:

```text
product-manager-<name>
ml-engineer-<name>
ml-engineer-reviewer-<name>
data-scientist-<name>
data-scientist-reviewer-<name>
```

Messages are routed by tag prefix:

```bash
hcom send @ml-engineer- "TASK bots-without-labels-001 ..."
hcom send @data-scientist-reviewer- "Please review ..."
```

When launching agents, point each one at the matching prompt file in
`development approach/prompts/` and set the working directory to the repository
root.

## MCP Memory

Each agent CLI can be pointed at a local MCP memory server for working context.
Memory is useful for continuity across local agent sessions. It is not the
source of truth. Any decision that another contributor should rely on must be
committed in the repository.

## Workflow

1. The human owner states the goal.
2. The product manager writes a compact task brief.
3. The product manager routes the task to the relevant implementer and reviewer tags.
4. The implementer inspects the repo, makes focused changes, and runs verification.
5. The implementer sends a structured review request.
6. The reviewer inspects the diff and evidence directly.
7. The reviewer approves or requests changes.
8. The implementer revises until blocking findings are resolved.
9. The product manager checks status, stages only intentional changes, commits,
   and pushes.
10. The product manager announces the closeout with the commit SHA.

The work should stay lightweight for low-risk changes. Full review gates are
most valuable when work affects predictions, generated outputs, probability
claims, the analysis notebook, or the team process itself.

## Handoff Messages

Task brief:

```text
@<implementer-tag>- @<reviewer-tag>- TASK bots-without-labels-<id>
Goal: <one sentence>
Scope: <files or feature area>
Acceptance: <observable success criteria>
Constraints: <dependencies, runtime, style, data assumptions>
Review mode: blocking findings first, then residual risks
```

Implementer handoff:

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
@<implementer-tag>- REVIEW_RESULT bots-without-labels-<id>
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

The reviewer should inspect the actual repository diff, not only the
implementer's summary. A good review leads with blocking issues and then states
residual risk.

ML engineer review should cover:

- loader and feature correctness
- data assumptions and edge cases
- anomaly model fit and threshold reasoning
- reproducibility of `predictions.tsv` and generated outputs
- test coverage and runtime supportability
- unsupported bot or probability claims

Data scientist review should cover:

- theoretical grounding in the cited academic and industry literature, and
  whether claims match that evidence
- clarity for a wide technical audience
- British English, plain definitions, and concrete examples
- interpretation honesty on unlabelled data
- use of tables, diagrams, charts, or visual aids where helpful
- accessibility and readable hierarchy
- consistency between documentation, scripts, and generated output

## Failure Modes And Controls

| Risk | Control |
|---|---|
| Agents edit the same file concurrently | Product manager sequences work and checks git status |
| Reviewer rubber-stamps work | Require diff-based findings and residual-risk notes |
| Product manager becomes an implementer | Restate boundary: product manager coordinates only |
| Outputs drift from code | Re-run the pipeline when outputs are affected |
| Agent agreement creates false confidence | Require evidence and human judgement |
| Hidden memory becomes undocumented policy | Commit durable decisions to the repo |
| Process becomes too heavy | Use the full loop only when risk justifies it |

## Design Principle

The team is useful when it improves evidence, review quality, and decision
clarity. It is not useful when it adds ceremony without reducing risk.

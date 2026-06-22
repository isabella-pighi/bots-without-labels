# Development Approach

This folder documents the local agentic development team used for Bots Without Labels.
The team is intentionally small: one human owner, one orchestrator, two
specialist coder/reviewer pairs, and one independent auditor. The purpose is
not to automate judgement away. The purpose is to make work traceable,
reviewed, audited, and easy to challenge.

Bots Without Labels is a good use case for this pattern because it combines software
engineering, data-science judgement, user-facing explanation, and generated
deliverables. A change to a threshold, for example, is not just a code change.
It may alter `predictions.tsv`, the dashboard, the report, and the probability
story told to the reader. The team structure is designed to keep those concerns
visible.

## Folder Map

| File | Purpose |
|---|---|
| `README.md` | Narrative entry point for the development approach |
| `team_instructions.md` | Canonical operating instructions for the team |
| `shared_agent_principles.md` | Common rules and quality principles for all agents |
| `agentic_development_architecture.md` | Architecture, rationale, and workflow design |
| `community_cheat_sheet.md` | Short shareable summary of the pattern |
| `prompts/` | Role prompts loaded by the HCOM launch scripts |

The executable helper scripts remain in `../scripts/` because they are project
tooling rather than documentation. They load the prompts from this folder when
starting HCOM agents.

## Team Model

The team has seven responsibilities across six active roles:

| Role | Default tool | Responsibility |
|---|---|---|
| Human owner | Human | Sets goals, approves trade-offs, and owns final decisions |
| Orchestrator | Codex CLI | Routes work, enforces review gates, commits, and pushes |
| Algorithm coder | Codex CLI | Pipeline, features, classifiers, tests, and supportability |
| Algorithm reviewer | Claude Code | Engineering quality, methodology, and probability critique |
| UX coder | Codex CLI | Dashboard, reports, documentation, and user-facing language |
| UX reviewer | Claude Code | UX clarity, accessibility, report quality, and documentation accuracy |
| Auditor | Claude Code | Assignment coverage, artefact consistency, and literature-safe claims |

The orchestrator is deliberately not a coder. It must not edit application
files, write tests, rewrite documentation, or resolve reviewer findings itself.
It delegates task work through HCOM, waits for reviewer responses, checks the
evidence, requests an auditor result for final assignment deliverables, and
then owns the git commit and push once the work is accepted.

## Why This Structure Exists

Bots Without Labels has two different kinds of risk.

The first is technical risk. The parser, feature engineering, anomaly scoring,
and generated artefacts must remain reproducible. A small implementation error
can produce a plausible-looking `predictions.tsv` that is still wrong.

The second is interpretation risk. The dataset is unlabelled, so the project
cannot honestly claim measured precision or recall. Probability statements are
operational confidence estimates unless future labels are added. A reviewer
must therefore challenge wording that sounds more certain than the evidence
allows.

The two specialist pairs reflect those risks:

- The algorithm pair focuses on correctness, data-science method, runtime
  behaviour, and engineering standards.
- The UX pair focuses on whether the dashboard, report, and documentation are
  clear to a wide technical audience, including readers who are not fluent in
  data science.
- The auditor checks final assignment coverage, generated artefacts, and
  literature-safe wording. The auditor uses Claude Code and does not edit
  files.

This split keeps implementation and review independent while avoiding a large
or heavy process.

## HCOM In This Repo

HCOM is the local communication and launch layer. Each agent runs as a CLI
session, and HCOM provides:

- role tags such as `@algorithm-coder-` and `@ux-reviewer-`
- direct messages between agents
- event awareness for agent activity
- transcript access for handoffs and review history
- a practical way to separate coding, review, and orchestration

Claude Code uses the project-scoped MCP config in `.mcp.json`. Codex CLI uses
its user-level MCP registry, which can be configured with
`./scripts/setup-memory-mcp`. Both point at local storage under `.mcp-memory/`.
The memory files are ignored by git so private working notes do not leak into
the repository. Durable decisions belong in committed documentation.

## Setup

The agent-team workflow is optional and separate from the Bots Without Labels runtime.
It expects HCOM plus the local agent CLIs used by the team:

```bash
uv tool install hcom
```

Codex CLI, Claude Code, and `bunx` must be installed separately if you want to
run the multi-agent development team. They are not required for the Bots Without Labels
classifier or dashboard itself.

Run these commands from the repository root:

```bash
./scripts/setup-memory-mcp
./scripts/check-agent-team
```

The check should confirm that HCOM, Codex CLI, Claude Code, `bunx`, git, and
MCP memory are available.

Start the specialist pairs and auditor:

```bash
./scripts/start-agent-team
```

Start only the auditor:

```bash
./scripts/start-auditor
```

Start the orchestrator:

```bash
./scripts/start-orchestrator
```

Check the active agents:

```bash
hcom list
```

Stop the team:

```bash
hcom kill all
```

Any machine-specific Terminal window layout automation should remain local and
ignored by Git. It is not required for a clean install or for running Bot
Hunter.

## Working Pattern

The orchestrator converts the human request into a compact task brief and sends
it to the relevant pair.

For algorithm or engineering work:

```text
@algorithm-coder- @algorithm-reviewer- TASK bots-without-labels-<id>
Goal: <one sentence>
Scope: <files or feature area>
Acceptance: <observable success criteria>
Constraints: <runtime, dependencies, style, data assumptions>
Review mode: blocking findings first, then residual risks
```

For dashboard, report, or documentation work:

```text
@ux-coder- @ux-reviewer- TASK bots-without-labels-<id>
Goal: <one sentence>
Scope: <dashboard, report, copy, docs, or user journey>
Acceptance: <observable success criteria>
Constraints: <audience, accessibility, evidence, style>
Review mode: blocking findings first, then residual risks
```

For cross-domain work, both pairs are involved. For example, changing a bot
threshold and explaining it in the report needs algorithm review for classifier
impact and UX review for clarity.

For final assignment deliverables, the orchestrator also sends an audit request
to `@auditor-` and waits for an `AUDIT_RESULT`. The auditor checks the eight
assignment points, generated artefacts, unresolved findings, and literature
claims. It reports findings; it does not implement fixes.

Auditor result format:

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

## Quality Bar

The engineering quality bar is intentionally high. Python changes should follow
Google-style expectations: clear names, type hints, focused functions, explicit
resource management, no bare `except:`, no mutable default arguments, readable
control flow, hermetic tests, and executable logic behind a `main(argv)` entry
point where relevant.

The UX and documentation quality bar is equally explicit. Outputs should use
plain British English, define specialist terms, include concrete examples, and
use tables, diagrams, charts, or other visual elements where they make the work
easier to understand.

New packages must not be installed without approval from the human owner or
orchestrator. This keeps the dependency surface intentional.

## Source Of Truth

The role prompts in `prompts/` are operational inputs for agents.
`shared_agent_principles.md` contains the common quality bar that applies to
every role. The canonical human-readable operating model is
`team_instructions.md`. The architecture guide explains why the model exists.
The cheat sheet is the compact version to share with others.

# Development Approach

This folder documents the local agentic development team used for Bots Without Labels.
The team is intentionally small: one human owner, one product manager, one
machine-learning engineer pair, and one data-scientist pair. The purpose is
not to automate judgement away. The purpose is to make work traceable,
reviewed, and easy to challenge.

Bots Without Labels is a good use case for this pattern because it combines software
engineering, data-science judgement, and user-facing explanation. A change to a
threshold, for example, is not just a code change. It may alter `predictions.tsv`,
the analysis notebook, and the probability story told to the reader. The team
structure is designed to keep those concerns visible.

## Folder Map

| File | Purpose |
|---|---|
| `README.md` | Narrative entry point for the development approach |
| `team_instructions.md` | Canonical operating instructions for the team |
| `shared_agent_principles.md` | Common rules and quality principles for all agents |
| `agentic_development_architecture.md` | Architecture, rationale, and workflow design |
| `community_cheat_sheet.md` | Short shareable summary of the pattern |
| `prompts/` | Role prompts loaded when launching HCOM agents |

The `prompts/` folder contains:

| Prompt | Role |
|---|---|
| `product_manager_prompt.md` | Product Manager |
| `ml_engineer_prompt.md` | ML Engineer (implementer) |
| `ml_engineer_reviewer_prompt.md` | ML Engineer (reviewer) |
| `data_scientist_prompt.md` | Data Scientist |
| `data_scientist_reviewer_prompt.md` | Data Scientist (reviewer) |

## Team Model

The team has six roles:

| Role | Default tool | Responsibility |
|---|---|---|
| Human owner | Human | Sets goals, approves trade-offs, and owns final decisions |
| Product Manager | Codex CLI | Routes and prioritises work, enforces review gates, commits, and pushes |
| ML Engineer (implementer) | Codex CLI | Detection engine: loader, features, rules, scoring, pipeline, and tests |
| ML Engineer (reviewer) | Claude Code | Engineering quality, methodology, and probability critique of the engine |
| Data Scientist | Codex CLI | Analysis narrative, methodology, label-injection design, and visualisation |
| Data Scientist (reviewer) | Claude Code | Critiques the analysis narrative, interpretation honesty, and visualisation |

The product manager is deliberately not a coder. It must not edit application
files, write tests, rewrite documentation, or resolve reviewer findings itself.
It routes and prioritises work through HCOM, enforces review gates, waits for
reviewer responses, checks the evidence, and then owns the git commit and push
once the work is accepted.

## Why This Structure Exists

Bots Without Labels has two different kinds of risk.

The first is technical risk. The autodetecting loader, feature engineering,
anomaly scoring, and generated outputs must remain reproducible. A small
implementation error can produce a plausible-looking `predictions.tsv` that is
still wrong.

The second is interpretation risk. The data is unlabelled, so the project
cannot honestly claim measured precision or recall. Probability statements are
operational confidence estimates unless trusted labels are added. A reviewer
must therefore challenge wording that sounds more certain than the evidence
allows.

The two pairs reflect those risks:

- The ML engineer pair owns the detection engine: the autodetecting loader,
  schema-driven features, rules and heuristics, the Extended Isolation Forest
  scoring, the pipeline, and tests. It focuses on correctness, data-science
  method, runtime behaviour, and engineering standards.
- The data scientist pair owns the analysis narrative and methodology: the
  analysis notebook, feature and label-injection design, interpretation honesty
  on unlabelled data, and visualisation. The two data scientists critique each
  other's work so the narrative stays clear and defensible.

This split keeps implementation and review independent while avoiding a large
or heavy process.

## HCOM In This Repo

HCOM is the local communication and launch layer. Each agent runs as a CLI
session, and HCOM provides:

- role tags such as `@ml-engineer-` and `@data-scientist-reviewer-`
- direct messages between agents
- event awareness for agent activity
- transcript access for handoffs and review history
- a practical way to separate implementation, review, and coordination

Each agent CLI can be pointed at a local MCP memory server so agents keep
working notes between sessions. Memory files should be kept out of git so
private working notes do not leak into the repository. Durable decisions belong
in committed documentation.

## Setup

The agent-team workflow is optional and separate from the Bots Without Labels runtime.
It expects HCOM plus the local agent CLIs used by the team:

```bash
uv tool install hcom
```

Codex CLI and Claude Code must be installed separately if you want to run the
multi-agent development team. They are not required for the Bots Without Labels
detection engine or analysis notebook itself.

A typical launch is a short set of commands a user can wire up locally, for
example:

```bash
# Example launch a user could create
hcom open --tag product-manager- --prompt "development approach/prompts/product_manager_prompt.md"
hcom open --tag ml-engineer-           --prompt "development approach/prompts/ml_engineer_prompt.md"
hcom open --tag ml-engineer-reviewer-  --prompt "development approach/prompts/ml_engineer_reviewer_prompt.md"
hcom open --tag data-scientist-          --prompt "development approach/prompts/data_scientist_prompt.md"
hcom open --tag data-scientist-reviewer- --prompt "development approach/prompts/data_scientist_reviewer_prompt.md"
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
ignored by git. It is not required for a clean install or for running Bots
Without Labels.

## Working Pattern

The product manager converts the human request into a compact task brief and
sends it to the relevant pair.

For detection-engine work:

```text
@ml-engineer- @ml-engineer-reviewer- TASK bots-without-labels-<id>
Goal: <one sentence>
Scope: <files or feature area>
Acceptance: <observable success criteria>
Constraints: <runtime, dependencies, style, data assumptions>
Review mode: blocking findings first, then residual risks
```

For analysis-narrative work:

```text
@data-scientist- @data-scientist-reviewer- TASK bots-without-labels-<id>
Goal: <one sentence>
Scope: <analysis notebook, features, label injection, copy, or user journey>
Acceptance: <observable success criteria>
Constraints: <audience, accessibility, evidence, style>
Review mode: blocking findings first, then residual risks
```

For cross-domain work, both pairs are involved. For example, changing a bot
threshold and explaining it in the analysis notebook needs ML engineer review
for engine impact and data scientist review for clarity.

## Quality Bar

The engineering quality bar is intentionally high. Python changes should follow
Google-style expectations: clear names, type hints, focused functions, explicit
resource management, no bare `except:`, no mutable default arguments, readable
control flow, hermetic tests, and executable logic behind a `main(argv)` entry
point where relevant.

The analysis and documentation quality bar is equally explicit. Outputs should
use plain British English, define specialist terms, include concrete examples,
and use tables, diagrams, charts, or other visual elements where they make the
work easier to understand.

New packages must not be installed without approval from the human owner or
product manager. This keeps the dependency surface intentional.

## Source Of Truth

The role prompts in `prompts/` are operational inputs for agents.
`shared_agent_principles.md` contains the common quality bar that applies to
every role. The canonical human-readable operating model is
`team_instructions.md`. The architecture guide explains why the model exists.
The cheat sheet is the compact version to share with others.

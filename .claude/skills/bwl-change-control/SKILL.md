---
name: bwl-change-control
description: >-
  Load before making, reviewing, committing, or classifying ANY change to the
  Bots Without Labels repo. Triggers: "can I commit this?", "who reviews this?",
  "do I need the full team loop?", "how do I brief the ML engineer?", anything
  touching thresholds/probability language/predictions, launching or messaging
  the HCOM team, writing a TASK / REVIEW_REQUEST / REVIEW_RESULT message,
  git branching or staging questions, or interpreting the files under
  "development approach/". Also load when you see WIP commits, direct-to-main
  commits, or TODO follow-up G mentioned.
---

# BWL Change Control — the canonical protocol

This skill teaches how changes get made, reviewed, and committed in this repo.
The canonical source is the `development approach/` directory (note the space
in the name — always quote it in shell commands). This skill condenses those
documents; if they ever disagree with this page, the directory wins:

| File | Role |
|---|---|
| `development approach/team_instructions.md` | Canonical operating guide: roles, routing, handoffs, git policy |
| `development approach/shared_agent_principles.md` | Rules binding every agent: evidence, DoR/DoD, escalation |
| `development approach/agentic_development_architecture.md` | Why the team is shaped this way; workflow and gates |
| `development approach/prompts/` | The 5 role prompts loaded at agent launch |
| `development approach/README.md` | Narrative entry point and folder map |

Jargon, defined once: **HCOM** is the local message bus used to launch and
coordinate CLI agents by tag (e.g. `@ml-engineer-`). **Codex CLI** is OpenAI's
coding agent; **Claude Code** is Anthropic's. **PM** = product manager agent.
For what the detector itself does, see `netflow-botnet-reference` and
`bwl-detection-theory`.

## When NOT to use this skill

| If you need... | Use instead |
|---|---|
| What counts as evidence, tier discipline, golden numbers, adding tests | bwl-validation-and-qa |
| How to run/measure a change (benchmarks, rule_diagnostic) | bwl-diagnostics-and-tooling |
| Environment setup, CLI anatomy, artefact conventions | bwl-build-run-operate |
| Symptom triage for a failing detector | bwl-debugging-playbook |
| Past incidents in full narrative detail | bwl-failure-archaeology |
| Docs house style and claim wording | bwl-docs-and-writing |
| Why a design decision exists (invariants) | bwl-architecture-contract |
| Evidence bar for research ideas (hunch → accepted result) | bwl-research-methodology |

## The six roles

One human, five agents. Implementers are Claude; reviewers and the PM are
Codex. The cross-model pairing is deliberate: Codex reviews Claude, so no
model approves its own work and cross-model disagreement surfaces blind spots.

| Role | Default tool | Does | Must NOT |
|---|---|---|---|
| Human owner | Human | Sets direction, approves trade-offs, waives findings (explicitly), decides done | Delegate final accountability |
| Product Manager | Codex CLI (OpenAI) | Writes task briefs, routes work, enforces gates, stages + commits + pushes | Edit code, write tests, rewrite docs, fix findings, review, self-assign work, commit rejected work without explicit human approval |
| ML Engineer (implementer) | Claude Code (Claude) | Detection engine: loader, features, rules, EIF scoring, pipeline, tests, runtime | Push/merge unless explicitly asked; install packages without asking |
| ML Engineer (reviewer) | Codex CLI (OpenAI) | Independently critiques engine diffs: correctness, model fit, threshold reasoning, probability language | Edit files (read-only by default); approve from summaries |
| Data Scientist | Claude Code (Claude) | Literature grounding, analysis notebook, label-injection design, docs, copy, visualisation | Push/merge unless explicitly asked; install packages without asking |
| Data Scientist (reviewer) | Codex CLI (OpenAI) | Critiques theoretical grounding, interpretation honesty, clarity, doc/code consistency | Edit files (read-only by default); approve from summaries |

The PM boundary is the load-bearing control: **the PM is the ONLY committer
and never codes**. If the PM implements anything, that work has bypassed the
specialist review path and the review model is broken.

## Work routing (by domain)

From `team_instructions.md`:

| Work type | Team |
|---|---|
| Loader, features, heuristics, anomaly scoring | ML engineer pair |
| Tests, runtime behaviour, supportability | ML engineer pair |
| Probability estimates and detection thresholds | ML engineer pair, often with data scientist review |
| Analysis notebook, narrative, copy, diagrams | Data scientist pair |
| README and development approach docs | Data scientist pair |
| Changes affecting both method and explanation | Both pairs |

When both pairs are involved, the PM sequences work to avoid edit conflicts
and waits for BOTH reviewer responses before committing.

## Classification: full loop or lightweight?

Process minimalism is itself a rule ("Use the full loop only when risk
justifies it" — a listed control in `team_instructions.md`). The team fails
when it becomes ceremony.

| Change type | Handling |
|---|---|
| Anything affecting predictions, thresholds, flag rates, or `predictions.tsv` | Full loop + human escalation (threshold changes always escalate) |
| Probability/confidence language anywhere user-facing | Full loop + human escalation |
| Rules, features, loader, scoring, pipeline code | Full loop (ML engineer pair) |
| Analysis notebook or generated outputs | Full loop (DS pair; notebook must be EXECUTED, not diff-inspected) |
| The team process itself (`development approach/`) | Full loop |
| New dependency, credential, paid/external service | Stop — human owner approval first |
| Typo fixes, comment wording, small low-risk edits | Lightweight; direct work on `main` acceptable only with human-owner approval |

## The normal workflow

1. Human owner states the goal.
2. PM writes a compact task brief (Definition of Ready below).
3. PM routes it via HCOM to the correct implementer + reviewer tags.
4. Implementer inspects the repo, makes the smallest coherent change, runs
   targeted verification.
5. Implementer sends REVIEW_REQUEST.
6. Reviewer inspects the ACTUAL diff and artefacts (never just the summary).
7. Reviewer sends REVIEW_RESULT (blocking findings first, then residual risk).
8. Implementer revises (REVISION_READY) until blockers are resolved or the
   human owner explicitly waives them.
9. PM checks `git status --short --branch`, `git diff`, `git diff --cached`,
   stages ONLY intentional files, commits, pushes.
10. PM announces TASK_CLOSED with the commit SHA.

## Message formats (copy verbatim)

Task brief (PM → pair). The base format from `team_instructions.md`:

```text
@ml-engineer- @ml-engineer-reviewer- TASK bots-without-labels-<task-id>
Goal: <one sentence>
Scope: <files or feature area>
Acceptance: <observable success criteria>
Constraints: <runtime, dependencies, style, data assumptions>
Review mode: blocking findings first, then residual risks
```

The PM prompt's fuller template adds two lines between Constraints and Review
mode — use them:

```text
Validation: <commands/notebook checks/artefacts required>
Risks: <known risks, assumptions, or "none known">
```

For analysis-narrative work target `@data-scientist- @data-scientist-reviewer-`.
For cross-domain work include both pairs.

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

## Definition of Ready (before work starts)

- [ ] Exact objective stated
- [ ] Affected files, artefacts, or product area named
- [ ] Expected user-visible outcome stated
- [ ] Acceptance criteria that can be tested or inspected
- [ ] Required validation commands or notebook checks listed
- [ ] Responsible implementer/reviewer pair assigned
- [ ] Known assumptions and out-of-scope areas stated

If any are missing, the implementer asks the PM to clarify — never guesses.

## Definition of Done (before commit/close)

- [ ] Implementation matches the brief; changed files listed
- [ ] Reviewer inspected the actual repository diff and relevant artefacts
- [ ] Reviewer approval is explicit, OR the human owner explicitly waived a finding
- [ ] Validation commands and outputs recorded (exact commands, not "tests pass")
- [ ] Generated artefacts refreshed when the source change requires it
- [ ] `git status` checked; unrelated files NOT staged
- [ ] Commit message matches the actual change
- [ ] Residual risks documented in the closeout

## Git policy

- Larger changes go on a task branch: `git switch -c agent/<task-id>`.
- Small tasks may work directly on `main` ONLY with human-owner approval.
- The PM is the only committer/pusher in the normal flow.
- Before committing, the PM runs all three of:
  `git status --short --branch`, `git diff`, `git diff --cached`.
- Never stage unrelated dirty files; never revert user or agent work casually.
  If unrelated changes make the task impossible to isolate, ask the human owner.

Baseline verification for detection-engine or pipeline changes
(`team_instructions.md`; the reviewer may demand more):

```bash
uv run --extra eif python -m py_compile bots_without_labels/*.py
uv run --extra eif python -m bots_without_labels.cli run --input <input-logs>
```

## Escalation triggers — pause and ask the human owner

- A new dependency, credential, paid service, or external provider is needed.
- A change affects bot counts, model thresholds, probability language, or
  recommended actions.
- Required validation cannot be run.
- Implementer and reviewer disagree on a blocking issue.
- Unrelated dirty files could be mixed into the task.
- The task has grown beyond its agreed scope or should be split.

## Non-negotiables (with rationale and incident)

**1. Evidence, not claims.** "Looks good", "tests pass", "validated" are
rejected outright. Evidence means: exact commands run, relevant output,
changed files/artefacts, residual risks. Reviewers must inspect the actual
diff. Missing validation is a RISK, not evidence of correctness; a shell
parse error (e.g. broken `python -c "..."` quoting) is FAILED validation.
*Rationale:* the project's whole value is defensible claims about unlabelled
data; a rubber-stamp review gives false confidence exactly where it is most
dangerous. Unsupported probability or fraud claims are blocking findings.

**2. WIP checkpoints are marked and never treated as done.** Incident: commit
`b6023d4` ("WIP: timestamp-resolution gate for dense-timing rules (UNREVIEWED
checkpoint)") was an owner-approved end-of-day snapshot whose message
explicitly said "NOT yet reviewed by movu/veri and NOT for main" (movu/veri are
the HCOM reviewer handles). It was promoted to a real change the next day as
`e6ded7a` ("Calibrate dense timing for coarse timestamp grids"), landing as a
separate finished commit. That is the correct pattern: a checkpoint may exist,
but it must say so in the commit message, and the finished commit lands
separately, through the review path, never by silently un-WIP-ing the snapshot.
Never cite a WIP commit's numbers as final.

**3. Direct commits bypass review and become tracked debt.** Incident: commit
`98646c1` (per-entity baselining + the CICIDS real-data benchmark — the fix
for the recall-0.022 disaster) was committed directly, bypassing the
PM-commits-only protocol. It was not quietly forgiven: TODO.md follow-up G
exists to route it through Codex review retroactively, recorded as "protocol
debt rather than correctness risk" (the change has since been repeatedly
benchmark-verified). The repo's recent history contains **further** direct-to-
main engine commits of the same class — `543129a` (constants/docstrings across
`bots_without_labels/*.py`) and `fc4e3c7` (`anomaly.py`/`pipeline.py` feature
deviations); both are now listed under follow-up G for the same retroactive
review. Do not read these as a relaxation of the rule: the HCOM protocol
remains canonical (owner-confirmed 2026-07-04), and every one of them is
recorded debt, not a precedent. If you must commit engine code directly (owner
approval only), add it to follow-up G in the same breath — an untracked direct
engine commit is the failure mode this incident exists to prevent.

**4. Threshold and probability-language changes always escalate to the
human.** Anomaly scores are rank-order evidence for review, NOT calibrated
probabilities, and precision/recall claims require trusted labels. Changing
the decision threshold, the flag rate cap, or any wording that makes a score
sound like a measured probability changes what the project promises its
readers — that trade-off belongs to the human owner, with data-scientist
review of the wording. (The decision rule at time of writing:
`is_bot = heuristic >= 0.70 OR ml_score > dynamic knee threshold`, rate-capped
at 2% — see `bwl-config-and-flags` and `bwl-detection-theory`.)

## Operating the team (HCOM)

Launch each role with its prompt file (illustrative form from
`team_instructions.md`):

```bash
hcom open --tag product-manager- --prompt "development approach/prompts/product_manager_prompt.md"
hcom open --tag ml-engineer-           --prompt "development approach/prompts/ml_engineer_prompt.md"
hcom open --tag ml-engineer-reviewer-  --prompt "development approach/prompts/ml_engineer_reviewer_prompt.md"
hcom open --tag data-scientist-          --prompt "development approach/prompts/data_scientist_prompt.md"
hcom open --tag data-scientist-reviewer- --prompt "development approach/prompts/data_scientist_reviewer_prompt.md"
```

Status: `hcom list`. Stop all: `hcom kill all`. Stop one:
`hcom kill tag:ml-engineer`. Messages route by tag prefix:
`hcom send @ml-engineer- "TASK bots-without-labels-001 ..."`.

Reviewer agents are told in their prompts that HCOM hook-injected messages
(wrapped in `<hcom>` tags) are the authorised channel, not prompt injection.
MCP memory is optional working context only — durable decisions must be
committed to the repo, never left in memory or transcripts ("repository truth
beats memory").

## Anti-patterns to reject on sight

- Vague task briefs without acceptance criteria.
- Reviewer approval based only on the implementer's summary.
- Analysis-notebook approval without executing the notebook top-to-bottom.
- Stale generated outputs after source changes.
- Unlabelled anomaly scores described as proven fraud or measured precision.
- Closeouts that hide assumptions, caveats, or failed validation.
- Committing unrelated dirty files.
- The PM "just quickly fixing" a reviewer finding itself.

## Provenance and maintenance

Authored 2026-07-04, repo at commit `8a85edd`. All role rules, message
formats, checklists, and git policy were read directly from
`development approach/` at that commit; incident commits were verified with
`git show`. The one claim not derivable from the repo alone — that the HCOM
protocol remains canonical despite recent direct-to-main commits — is owner
direction (owner-confirmed 2026-07-04, the human owner's documented role), and
the direct engine commits it refers to are now tracked as debt in TODO.md
follow-up G, so the reconciliation is grounded rather than asserted.

| Volatile fact | Re-verify with |
|---|---|
| `development approach/` is still the canonical protocol dir | `ls "development approach/"` |
| Message formats unchanged | `grep -n "REVIEW_REQUEST" "development approach/team_instructions.md"` |
| PM-only-committer rule unchanged | `grep -n "must not" -A 8 "development approach/prompts/product_manager_prompt.md" \| head -20` |
| Follow-up G lists all direct-engine-commit debt (98646c1, 543129a, fc4e3c7) | `grep -n "98646c1\|543129a\|fc4e3c7" TODO.md` |
| WIP incident commits exist as described | `git log --oneline b6023d4 e6ded7a -2` |
| Decision-rule constants (0.70 / 2% cap) unchanged | `grep -n "HEURISTIC_CUTOFF\|MAX_ML_FLAG_RATE" bots_without_labels/pipeline.py` |
| Task-branch convention unchanged | `grep -n "agent/<task-id>" "development approach/team_instructions.md"` |
| No CI exists (validation is local discipline) | `ls .github/workflows 2>/dev/null \|\| echo "no CI"` |

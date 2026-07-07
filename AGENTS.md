# AGENTS.md — Bots Without Labels

Operating contract for every agent (Claude Code, Codex CLI, or otherwise) working
in this repository. It is the guaranteed-loaded distilment of
[`development approach/`](development%20approach/), which remains the canonical,
longer-form source. When this file and a role prompt disagree, the role prompt
adds detail but must not weaken the non-negotiables below.

**What this project is.** An unsupervised detector for automated traffic in
*unlabelled* logs, with synthetic label injection to *measure* recall. Because the
data is unlabelled, the hardest risk is not a broken run — it is a run that
succeeds while the *explanation* is wrong. The rules below exist to keep that from
happening silently.

## Non-negotiables

1. **Evidence over assertion.** Never claim "looks good", "tests pass", or
   "validated" without the concrete proof: exact commands, real output, changed
   files, residual risks. Missing validation is a *risk to state*, not a pass to
   assume.

2. **Predict before you run.** Write the expected number/outcome down *before*
   measuring. A match is understanding; a surprise is the finding. Do not
   rationalise a number after the fact.

3. **Data-science integrity — the blocking rules.** Anomaly scores are *evidence
   for review*, not proof of fraud. Operational confidence is not measured
   precision. Precision/recall/calibration claims require trusted labels. Describe
   a feature by *how the code actually uses it*. Say "measured" vs "projected"
   honestly. Unsupported probability/fraud language is a **blocking issue**.

4. **Repository truth beats memory.** Memory and chat transcripts are working
   context, not the source of truth. Before acting, check `git status`, recent
   commits, the relevant source, and `development approach/`. Durable decisions
   must land in committed code, tests, docs, or `evaluation/FINDINGS.md`.

5. **Protect the working tree.** Stage only intentional files. Never revert,
   delete, or stage someone else's dirty changes without approval. Commit messages
   must match the actual change. One coherent purpose per commit; record negative
   results too.

6. **No direct-to-main; separate implement from review.** Engine changes are made
   on a branch and reviewed (cross-model where possible — Codex reviews Claude's
   work and vice versa) before the product manager commits. A reviewer inspects
   the *actual diff and artefacts*, never approves from a summary alone.

7. **Refactor = bit-identical.** A change billed as a refactor must not move any
   output. Prove it with a fixed seed and a diff of the benchmark report, not by
   "tests still pass". If the number moves at all, it is a behaviour change and
   takes the review + benchmark-no-regression path.

8. **Escalate to the human owner** when: a change touches bot counts, thresholds,
   probability language, or recommended actions; a new dependency / paid service /
   credential is needed; validation cannot be run; implementer and reviewer
   disagree on a blocker; scope has grown; or unrelated dirty files would be mixed
   in.

## Definition of ready / done

**Ready:** objective, affected files/artefacts, expected user-visible outcome,
acceptance criteria, the validation commands to run, and what is out of scope. If
these are missing, ask — do not guess.

**Done:** implementation matches the brief; artefacts refreshed if source changed;
validation evidence present; reviewer approval explicit (or a human waiver);
no unrelated files staged; residual risks documented; the summary says what
changed, what was checked, and what remains.

## Build, run, validate

```bash
uv sync                                   # deps + dev tools
uv run pytest -q                          # hermetic suite (data-dependent tests skip)
uv run black --check .                    # formatting gate
uv run --extra eif pytest -q              # + Extended Isolation Forest backend (needs isotree)
uv run --extra eif python -m evaluation.run_benchmarks   # real-data gates (needs local datasets)
```

Real-data benchmarks (CTU-13, CICIDS, UNSW, Bournemouth) need large, licence-bound,
gitignored datasets, so they are a **local/manual gate** and skip when the data is
absent — CI runs the hermetic suite only. How to obtain each dataset (source,
size, licence, fetch command) is documented in [`data/README.md`](data/README.md);
see also [`.claude/skills/bwl-build-run-operate`](.claude/skills/bwl-build-run-operate)
and [`bwl-validation-and-qa`](.claude/skills/bwl-validation-and-qa).

## Where the detail lives

- `development approach/shared_agent_principles.md` — the full 15 principles.
- `development approach/agentic_development_architecture.md` — roles, review gates,
  HCOM runtime.
- `.claude/skills/bwl-*` — deep, trigger-loaded playbooks (architecture contract,
  change control, proof toolkit, detection theory, failure archaeology, …).
- `evaluation/FINDINGS.md` — the chronicle of what was tried, shipped, and rejected
  (read it before re-attempting a rule/threshold/feature idea).
- `TODO.md` — the roadmap and parked follow-ups with their re-entry triggers.

Engineering baseline: Google-style Python, type hints, focused functions, absolute
imports, no `import *`, no bare `except`, no mutable defaults, hermetic tests for
new behaviour, British English in prose. Readability over cleverness.

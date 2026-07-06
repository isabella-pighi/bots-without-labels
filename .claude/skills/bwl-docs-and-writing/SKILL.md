---
name: bwl-docs-and-writing
description: >
  Load when writing or updating any document of record in this repo — README.md,
  evaluation/BENCHMARKS.md, evaluation/FINDINGS.md, TODO.md, docs/EXEC_MEMO.md,
  INSTALL.md, or "development approach/". Triggers: "where do I write this up",
  "add a benchmark row", "record this finding", "update the roadmap", "write the
  commit message", "which doc gets this change", questions about house style,
  honest-framing vocabulary (measured vs projected, ranking vs verdict), the
  claim-discipline rules, or how to keep numbers consistent across docs after a
  change. Not for deciding whether evidence is strong enough (that is
  bwl-validation-and-qa) or for external-publication claims (bwl-external-positioning).
---

# Maintaining the documents of record

This repo's credibility lives in its prose. The detector runs on **unlabelled**
data (logs with no ground-truth `is_bot` column), so its scores are *rankings under
uncertainty*, never verdicts — and the docs are the only place that discipline is
enforced. A number written into the wrong doc, rounded "for effect", or dressed up
as a probability is a correctness bug in the product, not a typo. Treat writing here
the way you would treat a code change: sourced, reviewed, consistent.

> Term note: **recall** = fraction of true bots caught; **precision** = fraction of
> flags that are real bots; **flag rate** = fraction of all rows flagged; **base
> rate** = fraction of rows that are actually bots. First-use definitions of NetFlow,
> C2, botnet families etc. live in `netflow-botnet-reference`; the detector's maths
> (robust z / MAD, isolation forest, Kneedle knee, adaptive percentiles) in
> `bwl-detection-theory`.

## When NOT to use this skill

| Situation | Use instead |
|---|---|
| Deciding whether a result is *strong enough* to write down (tier discipline, golden numbers, adding a test/benchmark) | `bwl-validation-and-qa` |
| Deciding what may be claimed as *novel* / publishable, or licence gating on numbers | `bwl-external-positioning` |
| Classifying a change, routing it through HCOM review, who may commit | `bwl-change-control` |
| Chronicling *why* a past investigation went the way it did (root-cause archaeology) | `bwl-failure-archaeology` |
| How to *measure* the numbers you are about to write (diagnostics, benchmark runner) | `bwl-diagnostics-and-tooling` |
| Writing the executable web-bot campaign plan | `bwl-webbot-campaign` |

This skill is only about **where** a change is recorded and **how** it is worded once
you already have sourced numbers and change-control clearance.

## 1. The document hierarchy and division of labour

Each doc has one job. Do not blur them: the split is what lets a reader trust the
registry as fact and read the narrative for judgement without cross-contamination.

| Doc | Role | Voice | What it is NOT |
|---|---|---|---|
| `evaluation/BENCHMARKS.md` | **Factual registry** — one row per externally-labelled dataset, the current measured numbers, and the stage-by-stage history of how they moved. The durable scoreboard. | Terse, tabular, every figure source-cited. | Not a place for reasoning or synthetic numbers. |
| `evaluation/FINDINGS.md` | **Narrative of why** — the investigation record: symptom → hypothesis → attribution evidence → fix → verified numbers → honest ceiling. | Explanatory, ordered, honest about limits. | Not a registry; numbers here are quoted *from* the same runs BENCHMARKS registers. |
| `TODO.md` | **Roadmap** — P1/P2/P3 open items with a `*Status:*` note, a "Shipped" section of one-liners + commit refs, and lettered open follow-ups (F, G, H…). | Motivation-first: why a change matters before what it is. | Not a changelog of everything; closed arcs collapse to one line. |
| `README.md` | **Positioning that leads with failure** — the honest-evaluation story ("our synthetic tests lied to us first"), how it works, what the evidence supports, **what not to claim**, quick start. | Public-facing, narrative-before-data. | Not exhaustive; points to FINDINGS/BENCHMARKS for detail. |
| `docs/EXEC_MEMO.md` | **Executive summary** — bottom line, what changed plainly, what to fund next, for a non-implementer. | Plain-English, decision-oriented. | Not technical; no reproduction commands. |
| `development approach/` | **Team protocol** (canonical) — roles, HCOM workflow, Definition of Ready/Done, review pairs. | Process. | Not detector docs; edit only via change control. |
| `INSTALL.md` | **Environment setup** — Python ≥ 3.11, `uv`, the `eif` extra, pip-only fallback. | Runbook. | Not usage/positioning. |

**The load-bearing separation:** BENCHMARKS is *what*, FINDINGS is *why*. A number
appears in BENCHMARKS as a registered fact and in FINDINGS inside its story — they
must agree to the digit. If you change one you almost always touch the other.

### Routing table — which doc(s) to update for which change

| Change type | BENCHMARKS | FINDINGS | TODO | README | EXEC_MEMO |
|---|---|---|---|---|---|
| New real-data benchmark measured | **new row** | **new section** | Shipped one-liner if it closes an item | if it shifts positioning | if it shifts the funding story |
| Existing benchmark number moved by a fix | **update row + history stage** | **update section + honest ceiling** | Shipped line + commit ref | only if headline numbers | only if bottom-line |
| Roadmap item shipped | numbers only | the story | **move item → Shipped one-liner + commit** | maybe | maybe |
| New open problem / follow-up found | — | note it | **new P-item or lettered follow-up** | — | maybe "fund next" |
| Rule/threshold/flag added or changed | if it moves a benchmark | if it moves a benchmark | Status note | if it changes the decision rule | — |
| Synthetic-suite change | — (never registered) | if it changes the stress story | Status note | — | — |
| Wording / claim-discipline fix | if a caveat is wrong | if a caveat is wrong | — | likely | likely |

Golden rule: **refresh every doc a change touches in the same task.** A benchmark
that moves and is updated in BENCHMARKS but stale in FINDINGS is a defect — the two
now disagree and a reader cannot tell which is right.

## 2. House style (verified from the docs themselves)

- **British English in the documents of record.** BENCHMARKS, FINDINGS and TODO use
  *labelled, behaviour, standardisation, prioritise*. Match that when editing them.
  - *Known inconsistency (do not "fix" silently):* `README.md` and `docs/EXEC_MEMO.md`
    currently use American spelling (`labeled`, `behavior`). They are internally
    consistent; a spelling sweep of a public doc is a deliberate edit, not a drive-by.
    Verify before assuming British in those two files.
- **Narrative before data.** Lead a section with why it matters, then the table.
  README's evaluation section and every TODO item open with motivation, not a metric.
- **Define terms at first use**, or point to `netflow-botnet-reference` /
  `bwl-detection-theory`. The audience may know neither security nor anomaly theory.
- **Tables and checklists over prose** for anything a reader will scan or copy.

### Honest-framing vocabulary (non-negotiable)

| Say this | Never this | Why |
|---|---|---|
| **measured** / **verified** (on externally-labelled data) | *measured* for synthetic numbers | Synthetic recall only measures agreement with our own generator. |
| **projected** / **estimated** / **counterfactual** | presenting a projection as the result | e.g. CTU-13 fix: projection said 0.956, verified re-run said **0.978** — cite the verified figure. |
| **ranking under uncertainty** / "this actor is unusual relative to this batch" | *fraud verdict*, *is a bot*, *guilty* | The system has no labels and cannot know. |
| **operational confidence** / rank-order **signal** | *precision* / *accuracy* of the live system | Only a labelled benchmark can measure precision; production cannot. |
| **anomaly score** / rank-order signal | *probability* | Scores are not calibrated; never feed them to a cost-based threshold as if they were. |
| **flag** / escalate / "where to look first" | *catch a criminal* / detect fraud | It is triage, not judgement. |

### The claim-discipline list (from README "What not to claim")

Every one of these has burned the project once. Enforce them in any doc:

1. **Never report synthetic recall/precision as field accuracy.** Synthetic injection
   is a stress test for *known* failure modes — necessary, insufficient. Only
   externally-labelled real data earns a precision/recall claim.
2. **Never call a score a probability.** Rank-order anomaly signals, not calibrated
   fraud probabilities.
3. **Never claim generality from one attack family.** The graph-signal win is
   same-family evidence (CTU-13 Neris + Rbot are *two scenarios of one dataset*); it
   supports a hypothesis, it is not proof of transfer to unseen families.
4. **Never over-read a single capture's precision.** CTU-13 precision 0.978 is real
   *on this capture* — not a general precision, not proof the method transfers.
5. **Never trust timing signals on coarse timestamps.** Minute/second-resolution logs
   cannot carry sub-second cadence; the engine gates those rules off and so must the
   prose. (CICIDS timestamps are minute-quantised at source — the burst rules are off.)
6. **Never present a fix as done without the review path** — see `bwl-change-control`.

## 3. Templates (extracted from real entries)

### A. FINDINGS investigation entry

Follow the arc the existing sections use (e.g. "The precision fix", FINDINGS
§245–279). Six beats, in order:

```markdown
## <Discriminator / fix name>

<Symptom, with the numbers.> On <dataset> the detector scored:

    recall 0.113   precision 0.005   flag rate 0.757   (base rate 0.032)

<Hypothesis — the mechanism you think is at fault, in plain terms.>
<why the obvious other explanation is wrong.>

### The fix: <one line>

<What changed and — crucially — that no constant was tuned to the dataset if true.>
The effect, verified end-to-end: <metric> rises **X → Y**, flag rate **A → B**,
recall held at **Z**. An earlier per-rule *counterfactual projection* estimated
**Wp**; the actual verified figure on the re-run pipeline is **Y** — the number to
cite. <what stayed unchanged and why, e.g. CICIDS unregressed>.

*Verification: <who> (review #NNNNN) against <who>'s measured table (#NNNNN).*

### The honest ceiling (<dataset>)

Read this as <hypothesis-supporting evidence within one family>, not a solved problem:
- **<residual risk 1>** — <why it is still open>.
- **<scope limit>** — one family / one hub / limited-evidence guardrail constants.
```

Rules for this template: symptom carries *numbers* not adjectives; the fix states
whether any constant was tuned (bragging right is "no thresholds tuned"); the honest
ceiling is mandatory — a finding without stated limits is not finished.

### B. BENCHMARKS registry row + required caveat

The registry table columns (verified in BENCHMARKS §43) are fixed:

```
| Benchmark | Source / licence | Data shape | Labelled? | Base rate |
  Timestamp resolution | Entity columns (by detector) | Recall | Precision | Flag rate |
```

Every row must also carry, below the table or in its own `##` section:

- **Source citation** — dataset, provider, licence (CC-BY, academic terms, or
  *licence unclear → numbers provisional, not for publication*).
- **The primary/secondary/probe framing.** Only rare-single-botnet captures are
  *primary*. Broad-IDS mixes (UNSW-NB15) are *secondary* and "not comparable
  like-for-like". Web-log runs are *domain-transfer*. Label them so nobody reads a
  secondary number as a bot-detection win.
- **A reproduce command**, e.g. `uv run --extra eif python -m evaluation.run_benchmarks --only <name>`.
- **The stage history table** when a number moved, so a regression can't hide.

Required caveats by dataset kind:

| Kind | Mandatory caveat |
|---|---|
| Negative / worse-than-chance (Bournemouth precision 0.020 < base 0.029) | State it is *below base rate* and *why* (domain transfer, not regression); mark provisional if licence-pending. |
| Tiny positive set (Bournemouth: 11 bot sessions) | "Qualitative signal, not a statistically robust precision/recall estimate." |
| Secondary broad-IDS (UNSW-NB15) | "Not a bot capture; numbers not comparable like-for-like." |
| Any real number | "Read as ranking under uncertainty, never a fraud verdict." |

### C. TODO item + status convention

Open item:

```markdown
### <n>. <Imperative title> (Pn)

<Why it matters — motivation first, one short paragraph.>

- <concrete sub-goal>
- <concrete sub-goal>

*Status: <not started | in progress | shipped[ (YYYY-MM-DD)]>.* <one-line evidence
of shipped-ness: which function/test, or what remains>.
```

Shipped arc (collapse to a one-liner so open items stay readable):

```markdown
- **<Arc name>** (`<commit>`) — <what it did, with the measured before→after>.
```

Real example (TODO Shipped section): `**Generality beyond Neris proven** (`13e9436`)
— CTU-13 sc3 / Rbot: recall 0.985 generalised immediately; the fan-in false-positive
risk … was fixed by narrowing the rule to source fan-out (precision 0.056 → 0.929, no
thresholds tuned).` Lettered follow-ups (F/G/H) track debt and deferred work; G
tracks *unreviewed-change* debt explicitly — keep such honesty in.

### D. Commit-message style

Subject: **imperative mood, no full stop**, describes the change not the outcome —
e.g. `Add actor endpoint asymmetric-degree signal`, `Calibrate dense timing for
coarse timestamp grids`, `Make asymmetric degree source fan-out`.

Body (why-first, then measured numbers, then honest scope). The exemplar is
**`2a3f362`** — quote its shape:

```
Add a schema-driven, optional actor-graph rule (asymmetric_degree) that
fires on a high-volume endpoint whose graph degree exceeds an adaptive
floor ... Dormant otherwise, so the synthetic suite ... is unaffected.

Recovers a diverse directional bot that concentration/monotony rules miss.

Validation (independently re-run):
- Full suite: 64 passed.
- CICIDS botnet: recall 0.998 / precision 0.846 / flag 0.037 — unchanged;
  asymmetric_degree does not fire on CICIDS (no regression).
- CTU-13 Neris: overall recall 0.113 -> 1.000. ...

Honest scope: same-family (Neris) evidence only ...

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

Note the four moves: **what + why it is safe** (dormant otherwise) → **the win in one
line** → **validation as measured numbers with no-regression stated** → **honest
scope**. Trailer: `Co-Authored-By:` as your environment's commit rules specify.

> Standard vs practice: some shipped commits (`56f305d`, `13e9436`, `6c66306`) landed
> with **subject-only bodies** — the measured story lives in FINDINGS/BENCHMARKS
> instead. That is a recorded shortfall against the `2a3f362` standard, not a pattern
> to copy: prefer the full body. (Committing itself is gated — see `bwl-change-control`.)

## 4. Update discipline

- **Numbers are copied from script output, with the source cited.** Every figure in
  BENCHMARKS/FINDINGS is "copied from a script output or from `FINDINGS.md`, with the
  source cited" — cite the run (`evaluation/run_benchmarks.py`, a `rule_diagnostic`
  line range, or a review #). See `bwl-diagnostics-and-tooling` for producing them.
- **Nothing is rounded for effect.** Report 0.846, 0.998, 0.033 as measured; a
  measured count is given as a count (2,000 of 2,000; 358 false positives).
- **Projection ≠ result.** If a number is a counterfactual projection, label it and
  give the verified figure beside it (0.956 projected vs **0.978** verified).
- **Refresh every doc the change touches in the same task** (routing table above).
  BENCHMARKS and FINDINGS must never disagree; the "protected gates" line that recites
  all current numbers (CICIDS 0.998/0.846/0.037, CTU-13 sc1 1.000/0.978/0.033, sc3
  0.985/0.929/0.034, UNSW 0.122/0.198/0.020) appears in several places — update all.
- **Run the drift checker after any benchmark-number or commit-stamp change.** These
  numbers are echoed across ~10 skills for self-containedness, so a re-run that updates
  the registry can leave a stale copy behind. The checker treats the docs of record as
  ground truth and flags any skill that cites a metric triple not in
  BENCHMARKS.md/FINDINGS.md, plus any Provenance stamp behind current `HEAD`:

  ```bash
  # exit 0 = clean, 1 = drift; scans every .claude/skills/*/SKILL.md
  uv run python .claude/skills/bwl-docs-and-writing/scripts/check_golden_numbers.py
  ```

  It also reads every module-level numeric constant from `bots_without_labels/` and
  `evaluation/` and flags any skill citing `NAME = value` that disagrees with source
  (the high-harm class — a stale `HEURISTIC_CUTOFF` or `DEGREE_ASYMMETRY` misleads an
  engineer); constants defined with different values in different modules (e.g. per-
  benchmark `N_BOT`) are ambiguous and skipped. It catches typos and
  registry/source-updated-but-skill-stale drift; it does *not* judge whether the
  registry or source value is itself right (that is `bwl-validation-and-qa`). Re-verify
  each flag against the docs/source before editing — ground truth wins, never the skill.
- **Roadmap hygiene:** when an item ships, move it *out* of the open list into a
  Shipped one-liner with its commit ref; keep the full story in FINDINGS, not TODO.
- **Provisional stays provisional.** Licence-pending numbers (Bournemouth) carry the
  "local/internal, not cleared for publication" banner every time they appear.

## Provenance and maintenance

Authored 2026-07-04 (repo at commit `8a85edd`). Verify volatile facts before relying
on them — the numbers and doc structure drift as the project advances.

| Volatile fact | One-line re-verification |
|---|---|
| Current headline benchmark numbers | `sed -n '43,49p' evaluation/BENCHMARKS.md` |
| No golden-number drift across the skill library | `uv run python .claude/skills/bwl-docs-and-writing/scripts/check_golden_numbers.py` (exit 0 = clean) |
| Docs of record still exist at these paths | `ls README.md INSTALL.md TODO.md docs/EXEC_MEMO.md evaluation/BENCHMARKS.md evaluation/FINDINGS.md "development approach/README.md"` |
| FINDINGS section structure (the arc order) | `grep -n '^#' evaluation/FINDINGS.md` |
| BENCHMARKS registry column order | `sed -n '43p' evaluation/BENCHMARKS.md` |
| TODO Shipped / open-follow-up conventions | `grep -n '^## \|^### \|^\*Status' TODO.md | head -40` |
| Commit-message exemplar body still `2a3f362` | `git show -s --format='%s%n%n%b' 2a3f362` |
| README/EXEC_MEMO still American-spelled | `grep -rlw 'behavior\|labeled' README.md docs/EXEC_MEMO.md` (registry docs stay British: `grep -rlw 'behaviour\|labelled' evaluation/FINDINGS.md TODO.md`) |
| Co-author trailer convention | check the active commit-message rules in your environment |
| HCOM team protocol still canonical (who may commit) | `sed -n '1,40p' "development approach/team_instructions.md"` |

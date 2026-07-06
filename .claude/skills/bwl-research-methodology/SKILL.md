---
name: bwl-research-methodology
description: >
  Load when turning a hunch or idea into an accepted result in this repo: deciding whether a finding
  is real, setting expected numbers before running, promoting a fix from experiment to shipped, or
  judging whether evidence is strong enough to commit or claim. Triggers include "is this result
  real?", "should we ship this?", "what's the evidence bar?", "predict the numbers first", "one
  mechanism should explain all of it", "record the negative result", "no-tuning oath", "guardrail vs
  production constant", handling counterfactual projections, WIP/UNREVIEWED checkpoints, cross-model
  (Codex-reviews-Claude) refutation, and the idea lifecycle from diagnostic to PM commit to docs.
---

# BWL research methodology — hunch → accepted result

This is the *discipline*: how a guess becomes a number you are allowed to write down and defend. It is
extracted from how this project actually worked (git history + `evaluation/FINDINGS.md`). It tells you
what counts as proof, what order to do things in, and where to stop. It does **not** re-teach the
detector's maths (see `bwl-detection-theory`) or the mechanics of measuring (`bwl-diagnostics-and-tooling`).

First-use jargon, one line each:
- **Rule / heuristic** — a hand-written explainable signal (e.g. `entity_monotony`, `asymmetric_degree`) that adds to a per-row heuristic score. See `bwl-config-and-flags`.
- **The decision** — `is_bot = heuristic_score >= 0.70 OR ml_score > dynamic-knee threshold` (the ML side is rate-capped at ~2%). Precision/recall are properties of this *whole* decision, never of one rule.
- **Precision / recall / flag rate** — of flagged rows, how many are bots (precision); of bots, how many are flagged (recall); what fraction of all rows got flagged (flag rate).
- **Counterfactual** — recompute the whole decision with one rule's evidence removed; what changes is what that rule *carries*. Produced by `evaluation/rule_diagnostic.py`.
- **Synthetic (label-injection) vs real (externally-labelled)** — recall on planted bots is honest because ground truth is planted; precision on synthetic is *not* field precision. See `bwl-validation-and-qa` for tier discipline.

## When NOT to use this skill

| Your actual question | Go to |
|---|---|
| What counts as evidence / tier discipline / golden-number inventory / how to add a test | `bwl-validation-and-qa` |
| How to *run* the diagnostic, benchmark runner, feature deviations | `bwl-diagnostics-and-tooling` |
| The maths of entropy / robust-z / isolation forest / Kneedle | `bwl-detection-theory` |
| How a change is classified/gated, the HCOM team protocol as policy | `bwl-change-control` (canonical) |
| Symptom → triage for a live failure | `bwl-debugging-playbook` |
| The chronicle of past investigations and dead ends | `bwl-failure-archaeology` |
| First-principles analysis recipes with worked examples | `bwl-proof-and-analysis-toolkit` |
| Open problems / falsifiable milestones vs published baselines | `bwl-research-frontier` |

This skill is the *method*; those are the *material*. If you are asking "how do I decide if I believe
this", stay here.

---

## 1. The evidence bar

A result is accepted here only when **all** of the following hold. Treat it as a gate, not a wish-list.

| # | Gate | Why it exists |
|---|---|---|
| 1 | **One mechanism explains every observation, including the negatives** | A fix that explains the win but not the collateral movement is unattributed luck. |
| 2 | **No regression on any tracked benchmark** — CICIDS/Ares, CTU-13 sc1/Neris, CTU-13 sc3/Rbot, and the protected synthetic recall all still stand | Prevents trading one capture's precision for another's recall. |
| 3 | **The fix was designed against the mechanism, not the benchmark** | Tuning to a benchmark overfits; see the no-tuning oath (§5). |
| 4 | **Survived assigned adversarial review** — implementer (Claude) authored it, a *different model* (Codex) tried to refute it | Cross-model review is the built-in refutation step (§1.2). |
| 5 | **Claims are worded honestly** — synthetic ≠ field, scores are not probabilities, one-capture ≠ general | No-oversell rule; enforced by the Data Scientist reviewer. |

### 1.1 Worked example — one mechanism, three numbers (commit `56f305d`)

The CTU-13 precision fix is the canonical "one mechanism explains all" result. The **single mechanism**:
`entity_monotony` was doing per-entity baselining over the *degenerate* categorical columns `Proto` /
`State` (a handful of repeated tokens across the whole batch), reading them as if they were high-
cardinality actor identities. The fix (as it stood at commit `543129a`): gate per-entity baselining to
columns whose cardinality ratio sat in an **actor band** `[0.02, 0.5]`, which excludes the degenerate
columns. *(That ratio band was later found scale-dependent and replaced with scale-invariant
recurrence/shape tests; the methodology point is unchanged.)* That *one* change had to explain three
separate movements simultaneously:

| Observation | Number | Why the same mechanism predicts it |
|---|---|---|
| CTU-13 sc1/Neris **over-flagging fixed** | precision **0.041 → 0.978**, flag **0.785 → 0.033**, recall held **1.000** | Removing degenerate-column fires stops the over-flag; `asymmetric_degree` still carries recall (2000/2000, zero false fires). |
| CICIDS/Ares **non-regression** | **unchanged 0.998 / 0.846 / 0.037** | There `Source IP` / `Dest IP` are genuine high-cardinality actor columns — *in-band*, so the gate removes nothing. |
| UNSW-NB15 (secondary) **recall drop, then restored** | band fix: recall **0.561 → 0.122**, precision **0.090 → 0.198**; later scale-invariant fix re-admits IPs: **→ 1.000 / 0.519** | The band fix lowered recall (partly the same degenerate-column artefact); the later scale-invariant selection removed the band and re-admitted the IP actors. |

The UNSW drop is the tell: a mechanism you trust must also predict where you *lose*. Recording the loss
(rather than quietly keeping the higher number) is what made the attribution credible. If your proposed
mechanism cannot account for the collateral movements, you have not found the mechanism yet.

### 1.2 Adversarial review is a step, not a courtesy

The team runs **cross-model** review pairs: the implementer is Claude (see the `Co-Authored-By: Claude`
trailer on the commits), and review is done by a *different* model — Codex/OpenAI — in two roles:

| Reviewer role (model) | Refutes | Trace in the record |
|---|---|---|
| **ML Engineer reviewer** (Codex) | correctness, method, engineering, that scores are not called probabilities | code-review approvals |
| **Data Scientist reviewer** (Codex) | theoretical grounding, literature fit, interpretation honesty, doc truth | e.g. FINDINGS "rina-approved (review #37205) against mono's measured benchmark table" |

Different-model review exists because the author is the worst auditor of their own reasoning. In the
record you will see agent-instance tags (`mono` measured tables #37143/#37642, `rina` approved review
#37205, `movu`/`veri` cited as the pending code/claims reviewers in `b6023d4`). Do not route around
this: `bwl-change-control` is canonical — the **Product Manager (Codex) is the only committer**, and a
result that has not survived a reviewer of a different model has not cleared gate 4.

---

## 2. Predict the numbers before you run

Write the expected outcome — and the expected *risk* — **before** measuring. This converts a run from
"let's see" into a falsifiable test, and it makes overfitting visible: if you did not predict a number,
you cannot claim you understood the mechanism that produced it.

### 2.1 Worked example — the fan-in risk was predicted, then it materialised

When `asymmetric_degree` shipped (commit `2a3f362`, same-family Neris evidence only), the commit message
**predicted the failure mode in writing**: *"asymmetric_degree can also fire on passive fan-in hubs
(benign FP risk)."* That prediction was logged as an open follow-up (`771c9cb`).

It then **materialised exactly** on the second family. On CTU-13 sc3/Rbot the direction-agnostic rule
fired on benign fan-in infrastructure and precision **collapsed to 0.056** at a **0.567** flag rate
(recall generalised fine at 0.985). Because the risk was predicted, the fix was already scoped: narrow
the rule to the **source / fan-out side only**. Result (commit `13e9436`): precision **0.056 → 0.929**,
flag **0.567 → 0.034**, recall held **0.985**. A predicted-then-confirmed failure is *stronger* evidence
of understanding than a clean pass — it shows the mechanism model had teeth.

### 2.2 Projections are labelled and superseded by measurement

Predictions are allowed to be *quantitative*, but a projection is never the number of record. Worked
example (FINDINGS): the per-rule counterfactual *projected* CTU-13 precision at **0.956** after removing
the degenerate-column fires; the **verified precision on the re-run pipeline was 0.978** — and 0.978 is
the number cited everywhere. The rule:

- A projection must be **labelled** ("counterfactual projection", "estimate") wherever it appears.
- Measurement **supersedes** it; once you have the end-to-end number, the projection is retired from claims.
- Never present a projection where a reader would assume a measured field number.

### 2.3 The prediction checklist (do this before the run)

- [ ] Written expected direction **and magnitude** for the target benchmark.
- [ ] Written the expected movement on **every other** tracked benchmark (including "unchanged").
- [ ] Named the **predicted failure mode / FP risk** and where it would show up.
- [ ] Chosen the **discriminating** measurement (the one that separates your hypothesis from the rival) — see `bwl-diagnostics-and-tooling`.
- [ ] Decided in advance what result would make you **abandon** the idea.

---

## 3. The idea lifecycle (stage gates)

Every accepted change in this repo walked this path. Each arrow is a gate; do not skip forward.

```
hunch
  → diagnostic measurement (rule_diagnostic / benchmark)   [what actually causes it?]
  → root-cause attribution (one mechanism, §1)             [name it, in words]
  → fix designed against the MECHANISM, not the benchmark  [§5 no-tuning oath]
  → [optional] WIP checkpoint, marked NOT-for-main         [§3.1]
  → full validation: no-regression on ALL tracked benchmarks [gate 2]
  → cross-model review (Codex refutes Claude)              [gate 4]
  → PM (Codex) commit                                      [only committer]
  → docs of record updated (BENCHMARKS.md + FINDINGS.md)   [§4]
  → roadmap status (TODO.md: Shipped / follow-up)
```

Per-stage exit checklist:

| Stage | You may leave it only when… |
|---|---|
| Diagnostic | you have a *counterfactual* (fp_eliminated / tp_lost per rule), not an eyeball. |
| Root cause | you can state the mechanism in one sentence and it explains the negatives too. |
| Fix design | the change references the mechanism; no constant was picked to hit a benchmark target. |
| Validation | every tracked benchmark re-run; regressions either absent or *recorded and explained*. |
| Review | a different-model reviewer has approved the code AND the claim wording. |
| Commit | done by the PM, with a message stating validation + honest scope (see `2a3f362`, `b6023d4`). |
| Docs | BENCHMARKS.md registry row + FINDINGS.md narrative both updated; projections relabelled. |
| Roadmap | TODO.md moved to Shipped or a numbered open follow-up (F/G/H). |

### 3.1 The WIP checkpoint pattern (`b6023d4`)

Long work can be snapshotted to a commit **before** review, but only under an explicit contract. The
model is `b6023d4`, "WIP: timestamp-resolution gate … (UNREVIEWED checkpoint)":

- Subject line contains **`WIP`** and **`UNREVIEWED`**.
- Body states it is **owner-approved** and **NOT for main**, and names who still has to review (`movu` code, `veri` claims).
- Body lists *measured-so-far* numbers **and** the honest caveats to disclose (e.g. "disclose ml-only FP 245→253 from inf-hygiene (0 TP)"; "no 'proven safe' wording").
- Body has a **Resume** plan: finish tests → full suite + benchmark → review → PM commit.

A WIP checkpoint is a save-point, not a result. It has **not** cleared gates 2–4 and must never be cited
as evidence or merged as final.

### 3.2 Retirement path — negatives are recorded, never deleted

A result that fails is data. It is written down so the project does not re-run the same dead end.

- **Negative transfer, recorded:** the Bournemouth web-log benchmark is an honest **negative** — recall **0.873**, precision **0.028** (*below* the base rate, i.e. worse than chance), flag rate **0.918**. It flagged monotone *human* sessions and caught 0 of 11 bot sessions. It ships as a tracked, skip-if-absent benchmark with the numbers marked provisional/licence-pending. It is kept precisely because "the netflow-tuned method does not transfer to web logs out of the box" is a finding.
- **Rejected candidates, tabled:** dataset candidates that were assessed and dropped are recorded with the reason (e.g. files that turn out to be bot-vs-bot with no accessible real-human labels are marked SKIP), so the assessment is not repeated.

Retirement checklist: [ ] number recorded in BENCHMARKS.md/FINDINGS.md · [ ] reason stated · [ ] wording honest (no spin on a bad number) · [ ] roadmap note if it opens a future capability.

---

## 4. Where good ideas came from (provenance, so you can mine the same seams)

Ideas here did not come from brainstorming; they came from four repeatable sources. When you need a new
idea, go dig in these seams in this order:

| Source | Worked example | Where to look |
|---|---|---|
| **Failure attribution** — a measured ceiling names the missing signal | The **hub gate** came from the "busy-benign" precision ceiling: busy benign minutes over-flagged, so a relational-hub discriminator was added. | `bwl-failure-archaeology`, FINDINGS "honest ceiling" |
| **Literature** — a published anomaly shape maps to a rule | **OddBall** (Akoglu, McGlohon, Faloutsos, *PAKDD 2010*) on near-star / degree-outlier egonets → the `asymmetric_degree` rule. | FINDINGS references; `netflow-botnet-reference` |
| **Predicted risk** — a written-down FP risk becomes the next work item | The **fan-in** FP risk (§2.1) predicted in `2a3f362`, later fixed by source-fan-out narrowing. | commit `2a3f362` → `771c9cb` → `13e9436` |
| **Diagnostics** — a tier/attribution view reveals an unexplained bucket | The **ML-tail** explanation work came from tier analysis: high-anomaly rows had no human-readable reason, so `feature_deviations()` was added. | TODO item 3; `bwl-diagnostics-and-tooling` |

The pattern: every idea traces to a *measurement* or a *citation*, never to intuition alone. If you
cannot name which seam your idea came from, treat it as unvalidated and put it through §2 before §3.

---

## 5. The no-tuning oath

The single rule that protects the whole method from overfitting. Recite it before touching a constant.

> **Thresholds derive from distributions. Constants earn their value from a robustness sweep. Any
> constant that only works on one capture is labelled a guardrail, not a production default.**

Operationally:

| Kind | Rule | Examples in-repo |
|---|---|---|
| **Distribution-derived threshold** | Must be computed from the batch's own distribution (percentile, knee, MAD), never a hand-set magic number. | ML side uses a **dynamic knee** threshold rate-capped at ~2%; `asymmetric_degree` uses an **adaptive floor** = 99th-percentile of the batch's own hub-subset degrees (`DEGREE_FLOOR_PERCENTILE`). |
| **Sweep-earned constant** | A fixed constant is allowed only if it holds across a range; state the range. | `DEGREE_ASYMMETRY` = 10 and the 99th-pctile floor are documented as holding across a band of asymmetry factors. |
| **Guardrail (capture-specific)** | If it only demonstrably works on one capture, it is a *limited-evidence guardrail*, explicitly labelled, not sold as universal. | FINDINGS: "The constants are limited-evidence guardrails, not universal constants." A fixed **10th-percentile diversity cut** is flagged as needing an *adaptive* (gap/knee) replacement — a known guardrail, not a default. |

Anti-patterns that fail the oath (and gate 3):

- [ ] Picking a number because it makes a specific benchmark's precision cross a target — **overfitting**.
- [ ] A constant tuned on CTU-13 and silently applied everywhere — **must be labelled a guardrail** or made adaptive.
- [ ] A threshold hard-coded rather than derived from the batch distribution — **replace with a percentile/knee**.
- [ ] Calling a robustness "unproven" fix "proven safe" — **wording violation** (`b6023d4` explicitly forbids it).

The distinction between a **production** constant and a **guardrail** is documented per-flag in
`bwl-config-and-flags`; when in doubt, downgrade to guardrail and say so.

---

## 6. One-screen summary — the acceptance checklist

Before you claim a result is real / ready to commit:

- [ ] **Mechanism** stated in one sentence; explains the win **and** every collateral movement (the negatives).
- [ ] **Predicted** numbers (and the FP risk) were written **before** the run; projections are labelled and now superseded by measurement.
- [ ] **No regression** on CICIDS/Ares (0.998/0.846/0.037), CTU-13 sc1/Neris (1.000/0.978/0.033), CTU-13 sc3/Rbot (0.985/0.929/0.034), and protected synthetic recall — or any change is **recorded and explained** (e.g. UNSW honest drop).
- [ ] **No-tuning oath** held: thresholds distribution-derived; capture-specific constants labelled guardrails.
- [ ] **Cross-model review** passed: a Codex reviewer refuted the code and the claim wording.
- [ ] **Honest scope**: synthetic ≠ field, one-capture ≠ general, scores ≠ probabilities.
- [ ] **Docs of record** updated (BENCHMARKS.md registry + FINDINGS.md narrative), roadmap status moved.
- [ ] **Committed by the PM** (Codex), not direct-to-main. (Recorded exceptions like `98646c1` carry a tracked review-debt follow-up, item G — do not create new ones.)

If any box is empty, the result is a **candidate**, not an accepted result. Label it as such.

---

## Provenance and maintenance

Authored 2026-07-06 (repo at commit `8a85edd`). British English. All numbers below are cited from the
docs of record or git history at that commit; re-verify before quoting in a later session.

| Volatile fact | Stated value | One-line re-verify |
|---|---|---|
| Tracked benchmark numbers | CICIDS 0.998/0.846/0.037; CTU sc1 1.000/0.978/0.033; CTU sc3 0.985/0.929/0.034; UNSW 1.000/0.519/0.062; Bournemouth 0.873/0.028/0.918 | `grep -nE "0.998\|0.978\|0.929\|1.000\|0.873" evaluation/BENCHMARKS.md evaluation/FINDINGS.md` |
| Scale-invariant actor tests | `REPEAT_MASS_MIN`=0.3, `VOCAB_MAX_DISTINCT`=200, `STRUCTURED_TOKEN_MIN`=0.5 | `grep -nE "REPEAT_MASS_MIN\|VOCAB_MAX_DISTINCT\|STRUCTURED_TOKEN_MIN" bots_without_labels/features.py` |
| Fan-in prediction → materialised 0.056 → fixed 0.929 | predicted in `2a3f362`, fixed in `13e9436` | `git log --oneline 2a3f362 771c9cb 13e9436` and `grep -n "0.056" evaluation/FINDINGS.md` |
| 0.956 projection vs 0.978 verified | projection superseded by measurement | `grep -n "0.956\|0.978" evaluation/FINDINGS.md` |
| WIP-checkpoint contract | `b6023d4` marked WIP/UNREVIEWED, NOT for main | `git show -s --format=%B b6023d4` |
| Cross-model review roles / only-committer | PM+reviewers = Codex; implementer = Claude | `grep -niE "reviewer\|Codex\|commit" "development approach/agentic_development_architecture.md"` |
| Guardrail constants | `DEGREE_ASYMMETRY`=10, `DEGREE_FLOOR_PERCENTILE`, 10th-pctile diversity cut | `grep -nE "DEGREE_ASYMMETRY\|DEGREE_FLOOR_PERCENTILE" bots_without_labels/rules.py` and `grep -n "guardrail" evaluation/FINDINGS.md` |
| Decision rule | `heuristic >= 0.70 OR ml_score > dynamic knee (2% cap)` | `grep -rnE "0.70\|knee\|0.02" bots_without_labels/` |
| OddBall citation | Akoglu/McGlohon/Faloutsos, PAKDD 2010 | `grep -n "OddBall" evaluation/FINDINGS.md` |
| Roadmap open follow-ups | F (CICIDS families), G (unreviewed-change debt, `98646c1`), H (integer-id inference) | `grep -nE "^### [FGH]\." TODO.md` |
| Change-control canonical source | HCOM protocol in `development approach/` | `ls "development approach/"` |

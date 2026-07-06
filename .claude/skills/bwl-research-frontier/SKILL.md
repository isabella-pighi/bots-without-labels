---
name: bwl-research-frontier
description: Load when picking or scoping a RESEARCH bet for Bots Without Labels — "where can we beat published unsupervised baselines?", "what's a novel result we could publish?", "which open problem is worth the effort?", turning a benchmark win into a matched-protocol comparison against literature, planning the ML-tail (EIF-only false-positive) calibration attack, constructing a fan-in-bot benchmark, or scoping the cross-domain generality question. Use it to choose a frontier problem, know why current SOTA fails, what asset this repo has, the first three concrete repo steps, and the falsifiable "you have a result when …" milestone. NOT for how to run a benchmark (bwl-diagnostics-and-tooling), what counts as evidence (bwl-validation-and-qa / bwl-research-methodology), or the web-bot capability build (bwl-webbot-campaign).
---

# BWL research frontier

Open problems where this project can **beat published unsupervised baselines on
public captures**, expressed as runbook bets. The owner's SOTA definition
(2026-07-04) is narrow and load-bearing: *beat published **label-free** numbers,
on **public** captures, under a **pre-registered, matched** protocol.* A win
against a supervised or semi-supervised method is not the target; a win on a
private split is not publishable. Every bet below is scoped to that bar.

This skill tells you, for each problem: **why current SOTA fails**, **the
specific asset this repo already has**, **the first three concrete steps in this
repo**, and a **falsifiable milestone**. It does not re-teach the detector (see
`bwl-detection-theory`), the domain (`netflow-botnet-reference`), or the
evidence bar (`bwl-research-methodology`). It picks the fight.

## When NOT to use this skill

| Your actual question | Go to |
|---|---|
| How do I run a benchmark / diagnostic / measure a change? | `bwl-diagnostics-and-tooling` |
| What counts as evidence; how do I add a test/benchmark; tier discipline | `bwl-validation-and-qa` |
| How do I take a hunch to an accepted result (predict-before-run, idea lifecycle) | `bwl-research-methodology` |
| What must be *proven* before I claim novelty/licence/reproducibility publicly | `bwl-external-positioning` |
| Build the web-bot capability (mouse dynamics, TODO item 12) | `bwl-webbot-campaign` |
| First-principles analysis recipe with worked examples | `bwl-proof-and-analysis-toolkit` |
| Set up environment, CLI anatomy, artifact conventions | `bwl-build-run-operate` |
| The math behind entropy / MAD / isolation forest / knee | `bwl-detection-theory` |
| Security terms (NetFlow, C2, fan-in, botnet families) | `netflow-botnet-reference` |

A **frontier problem** is an open bet against the outside world. If you are
executing already-scoped work, or just measuring, you are in the wrong skill.

## Vocabulary (one line each, first use)

- **Label-free / unsupervised**: the detector never sees ground-truth labels at
  train or decision time. Labels exist only in the *benchmark* to score it.
- **Fan-in star**: many distinct hosts → one shared counterpart (classic C2
  beaconing; the shared node has high in-degree). See `netflow-botnet-reference`.
- **Fan-out / broadcasting source**: one host → many distinct counterparts
  (spam / scan / click-fraud; high out-degree). The opposite shape.
- **EIF / ML path / tier-3**: Extended Isolation Forest, the anomaly-scorer half
  of the decision rule. A "tier-3" or "ML-only" flag is one no heuristic rule
  fired on — it came from `ml_score > knee threshold` alone.
- **Matched protocol**: same capture, same split, same base rate, same
  train/test discipline as the paper you compare to — so the comparison is
  like-for-like, not our-numbers-vs-their-numbers.
- **Pre-registered**: the protocol and success threshold are written down and
  frozen *before* the run, so a good number can't be back-rationalised.

## The decision rule you are trying to beat with (context)

```
is_bot = heuristic_score >= 0.70  OR  ml_score > dynamic_knee_threshold  (rate-capped ~2%)
```
(`bots_without_labels/pipeline.py`: `HEURISTIC_CUTOFF = 0.70`, `dynamic_knee_threshold`.)
Every problem below is about moving one term of this rule against a public
baseline, or building the capture that lets you measure it.

## The four bets at a glance

| # | Bet | Repo asset | Milestone (falsifiable) | Honest odds |
|---|---|---|---|---|
| 1 | Label-free botnet detection on CTU-13 at rare base rates | 1.000/0.978 (sc1 Neris), 0.985/0.929 (sc3 Rbot) **label-free** | Beat published **label-free** numbers on **≥5** CTU-13 scenarios under a pre-registered protocol | **Strongest** — asset already measured on 2 scenarios |
| 2 | The ML-tail calibration frontier | `feature_deviations()` + per-rule attribution; ~70% of residual error is EIF-only | ML-only FP **halved**, recall held on **ALL** tracked benchmarks | **Tractable** — instrumentation exists; mechanism unknown |
| 3 | Build a public fan-in-bot benchmark | Injection harness plants calibrated signatures into real backgrounds | A published, reproducible fan-in benchmark **+ measured coverage** | **Fills a real gap** — no such public capture found |
| 4 | Cross-domain schema-agnostic generality (value-shape residual) | Scale-invariant shape-based actor typing (band adaptation partly delivered); skip-if-absent runner | An adaptation that types short-unstructured-id / content-column actors **with netflow gates held** | **Hard / honest** — Bournemouth is a negative; heavy proof burden |

Pick 1 first: it is the only bet whose asset is *already measured* and whose only
missing piece is disciplined comparison. Pick 2 if you want a self-contained
engineering win. Pick 3 to remove a standing blind-spot excuse. Treat 4 as
long-horizon and claim nothing until the proof obligations in
`bwl-external-positioning` are met.

---

## Problem 1 — Label-free botnet detection on CTU-13 at rare base rates

**The claim in waiting.** This detector reaches recall/precision on CTU-13 that
is competitive with the *supervised* comparison in the canonical CTU-13 paper —
**without labels**. If that holds across ≥5 scenarios under a matched protocol,
it is a publishable label-free result.

**Why current SOTA fails / is beatable.** The reference is Garcia, Grill,
Stiborek, Zunino, "An empirical comparison of botnet detection methods,"
*Computers & Security* 45 (2014) 100–123 (cited in
`evaluation/ctu13_bot_benchmark.py`; dataset CC-BY). It compares BClus, CAMNEP,
and the BotHunter lineage — methods that are **supervised or semi-supervised**,
or need per-network training / signature priors. The gap in the literature is a
**purely unsupervised, schema-agnostic, per-batch** method that still separates
the rare bot. That is exactly this detector's shape.

**This repo's specific asset (measured, on this branch).**

| Scenario | Bot family | Recall | Precision | Flag rate | Source |
|---|---|---|---|---|---|
| CTU-13 sc1 | Neris (outbound spam/C2/click-fraud) | **1.000** | **0.978** | 0.033 | `BENCHMARKS.md` L46 |
| CTU-13 sc3 | Rbot (IRC DDoS/scan) | **0.985** | **0.929** | 0.034 | `BENCHMARKS.md` L47 |

Both are label-free, at a ~3% base rate, on microsecond-resolution Argus
NetFlow. The `asymmetric_degree` rule carries the recall (2,000/2,000 zero-FP on
Neris; 1,970 TP / 0 FP on Rbot) — see `evaluation/FINDINGS.md` "asymmetric
endpoint degree" and "second-family test".

**The first three concrete steps in this repo.**

1. **Build the literature baseline table — label-free rows only.** Extract, from
   Garcia et al. 2014 and its citing successors, the per-scenario recall /
   precision (or FPR / detection-rate as the paper reports them) for **every
   method that is genuinely label-free or that you can fairly re-run
   label-free**. Discard supervised rows or mark them explicitly out-of-scope —
   comparing our unsupervised numbers to a supervised BClus row would be the
   dishonest kind of win. Record the paper's exact metric definitions and base
   rates; ours must be recomputed to match, not the reverse. Draft this as a
   pre-registered protocol doc (house style: `bwl-docs-and-writing`) and freeze
   the ≥5-scenario success threshold *before* running.

2. **Run the remaining CTU-13 scenarios through the existing wrapper.** The
   benchmark already generalises across scenarios by capture path — no new code
   needed for the run itself. The scenario registry lives in
   `evaluation/ctu13_bot_benchmark.py` (`SCENARIOS`), and a capture is selected
   by either `--scenario` or an explicit `--binetflow`:
   ```bash
   # fetch a new scenario capture (example: sc3/Rbot, Botnet-44)
   curl -o data/capture20110812.binetflow \
     https://mcfp.felk.cvut.cz/publicDatasets/CTU-Malware-Capture-Botnet-44/detailed-bidirectional-flow-labels/capture20110812.binetflow
   # run any capture through the same pipeline
   uv run --extra eif python -m evaluation.ctu13_bot_benchmark --binetflow data/capture20110812.binetflow
   ```
   `_scenario_label()` labels an explicit `--binetflow` by its matching registry
   scenario, so results can't be mis-filed under the sc1 heading. To add a
   scenario to the registered set (so `--scenario scN` and the combined runner's
   `--only ctu13_scN` work), add an entry to `SCENARIOS` with its capture path
   and CTU-Malware-Capture fetch URL — mirror the existing sc1/sc3 entries.
   **Predict each scenario's recall before you run it** (`bwl-research-methodology`):
   sc1 (single outbound bot) and sc3 (IRC) both favour `asymmetric_degree`;
   scenarios with a *fan-in* C2 shape will lean on `entity_monotony` / the hub
   gate instead, and are the ones most likely to surprise you.

3. **Write the matched-protocol comparison.** One table: our label-free
   recall/precision per scenario beside the paper's label-free rows, same metric,
   same base rate, with every methodological difference called out (they train
   per-network; we score per-batch; their base rate vs our constructed ~3%). Ship
   it through the review path in `bwl-change-control`, and register each new
   scenario row in `evaluation/BENCHMARKS.md` with a `tests/test_ctu13_benchmark.py`
   guard so a regression can't hide.

**You have a result when …** you beat the published **label-free** numbers on
**≥5 CTU-13 scenarios** under the **pre-registered, matched** protocol, with each
scenario measured through the committed wrapper and pinned by a test. Fewer than
5, or a protocol adjusted after seeing the numbers, is not the result — it is a
promising lead.

**Proof obligations (per `bwl-external-positioning`).** Confirm CTU-13's CC-BY
covers your redistribution of *numbers* (data itself stays gitignored). State
plainly that ours is unsupervised vs their supervised/semi-supervised baselines —
that framing is the whole novelty and must not be blurred. Two-scenarios-of-one-
corpus is *not* independent-corpus evidence; ≥5 CTU-13 scenarios is still
one-dataset generality, so scope the claim to CTU-13.

---

## Problem 2 — The ML-tail calibration frontier

**The claim in waiting.** After rule calibration, the residual false positives
are **mostly the ML/EIF path, not the heuristics**. If you can halve the ML-only
false positives while holding recall on every tracked benchmark, you close the
last-standing precision leak with a single, attributable mechanism.

**Why this is the live frontier.** Per-rule diagnostics show the heuristics are
now clean and the residual error concentrated in tier-3:

| Capture | Residual FP | ML-only (EIF) share | Heuristic share | Source |
|---|---|---|---|---|
| CICIDS (Ares) | 358 of 2,320 flags | ~253 | ~104 (`entity_monotony`), rest ≈ 0 | `FINDINGS.md` L146–156 / `BENCHMARKS.md` L139–154 |
| CTU-13 sc3 (Rbot) | 151 | **all 151** | 0 | `FINDINGS.md` "Closing the precision gap" |

So on Rbot the ML path owns **100%** of the residual error, and on CICIDS the
majority. Squeezing precision further is now an **ML-calibration** question, not
a rule question. This is the ~70% figure in the brief: the dominant residual
error is EIF-only.

**This repo's specific asset.** Every ML-tail flag already carries *why*:
`bots_without_labels/anomaly.py::feature_deviations()` (shipped, TODO item 3)
reports each flagged event's top robust-z deviations **with batch percentiles**,
in the same median/MAD space the model scores in. It is surfaced per event in
`selected_events.json` and via `DetectionResult.feature_deviations()`
(`pipeline.py`). Combined with `evaluation/rule_diagnostic.py` per-rule
attribution, you can isolate the exact ML-only false positives *and* read their
deviation signatures — you are not staring at an opaque tree path.

**The first three concrete steps in this repo.**

1. **Cluster the tier-3 FPs' deviation signatures on CICIDS + sc3.** Run
   `rule_diagnostic` to get the ML-only false positives (flags with no heuristic
   rule) on both captures, pull `feature_deviations()` for each, and cluster the
   deviation vectors. The question this answers: *is there one recurring
   structural reason the EIF over-fires* (e.g. a single heavy-tailed feature
   dominating the score, or one benign traffic shape) — or is it diffuse?
   ```bash
   uv run --extra eif python -m evaluation.rule_diagnostic --zip data/GeneratedLabelledFlows.zip
   ```
   (CTU-13 has an equivalent diagnostic path via its benchmark module; see
   `bwl-diagnostics-and-tooling` for the exact invocation.)

2. **Test one mechanism hypothesis — predict before you run.** State a single
   falsifiable cause ("the EIF FPs are dominated by feature *X* sitting in the
   batch's extreme tail because it is not robustly scaled" — note TODO item 5,
   robust/quantile scaling for heavy-tailed features, is the natural lever).
   Write down what the deviation clusters *must* look like if the hypothesis is
   true, then check. A hypothesis that survives a predicted-in-advance test is
   worth building on; one rationalised afterwards is not (`bwl-research-methodology`).

3. **Evaluate a deviation-aware gate.** Prototype one mechanism — e.g. a
   deviation-consistency requirement on ML-only flags, or robust scaling of the
   implicated feature before EIF — behind a flag (`bwl-config-and-flags` for how
   to add a guardrail flag without disturbing production defaults). Measure on
   **all** tracked benchmarks, not just the two you tuned on.

**You have a result when …** ML-only false positives are **halved** on the
captures you targeted **and** recall is held (within its pinned guard) on **every
tracked benchmark**: CICIDS 0.998, CTU-13 sc1 1.000, CTU-13 sc3 0.985, UNSW-NB15
1.000, Bournemouth unchanged. A precision gain on one capture that dents recall
or precision anywhere else is not the result — the guards in
`tests/test_real_benchmark.py` and `tests/test_ctu13_benchmark.py` exist to make
that failure loud.

**Proof obligations.** The gate must be a *mechanism*, not a fit to the two
captures' false positives — an EIF threshold tuned to CICIDS's 253 FPs would
overfit exactly as the original global-concentration cap did (see
`bwl-failure-archaeology`). Never describe the ML score as a probability
(`bwl-change-control` non-negotiable): it is a rank-order signal until TODO item
10's calibration lands on a labelled holdout.

---

## Problem 3 — Build a public fan-in-bot benchmark

**The claim in waiting.** No public, natively-labelled **fan-in-bot** capture
exists to test whether a source-fan-out detector misses a bot that is *itself* a
fan-in C2. This repo can *construct* one — a reproducible benchmark that plants
calibrated fan-in stars into a real background — and publish it, filling a
documented gap in the evaluation literature.

**Why this matters (the standing blind spot).** The absence is verified in
`evaluation/FINDINGS.md`: "There is no real external fan-in-bot benchmark, so
fan-in generality is *guarded, not proved*." Today the only real labelled fan-in
C2 in the data is CICIDS (many hosts → `205.174.165.73`), where the catch is
carried by `entity_monotony`, and `asymmetric_degree` fires **0**. CICIDS is
therefore used only as **no-regression** evidence, not positive proof that fan-in
detection generalises. A single real fan-in capture cannot settle it; a
*constructed, calibrated* one can at least measure coverage across a controlled
range.

**This repo's specific asset.** The injection harness
(`bots_without_labels/inject.py::inject_bots`, driven by
`synthetic.py::generate` signatures) plants synthetic bot rows with **known
ground truth** into any real loaded log, returning an `is_injected` mask — the
same mechanism the synthetic recall suite trusts, because the labels are planted
on purpose. `inject_bots` synthesises rows from the target log's detected column
roles, so a planted signature composes from *real* background values.

**Honest gap you must close first.** The four shipped archetypes are `burst`,
`mechanical_timing`, `diffuse_replay`, `stealth` (`synthetic.py::ARCHETYPES`).
**None is a fan-in star.** `inject.py::_cluster_values` picks *one* shared value
per column for a cluster, so a planted cluster shares the *same* source **and**
destination — that is a point-to-point monotone channel, not a fan-in star
(**many distinct** sources → **one shared** destination). So step 1 is not "use
the harness"; it is "extend the harness with a fan-in archetype".

**The first three concrete steps in this repo.**

1. **Add a `fan_in` archetype that varies the source but fixes the counterpart.**
   In `inject.py`, the planted rows must draw a *distinct* source-endpoint value
   per row (sample many from the background) while pinning **one shared**
   destination-endpoint value across the whole cluster — the fan-in star. This is
   a new builder/cluster policy, not a signature-text change; keep it dormant
   unless the schema exposes ≥2 actor-endpoint columns (mirror the actor-band
   gating in `features.py`). Make the fan-out ratio (distinct sources per shared
   destination) a parameter so it is *calibrated*, not a single fixed shape.

2. **Plant calibrated fan-in stars into a real netflow background and measure
   coverage vs the fan-out ratio.** Use a real gitignored capture (e.g. a benign
   CTU-13 or UNSW background) as the host log, inject fan-in stars at a swept
   ratio, and record recall as a function of that ratio — the honest analogue of
   the `DEGREE_ASYMMETRY ≈ 10` / floor bounds already documented for the
   fan-out side (`FINDINGS.md` "honest ceiling (CTU-13)"). This is the
   controlled test that CICIDS-as-no-regression cannot give you.

3. **Package it as a skip-if-absent benchmark + registry row.** Wire it into
   `evaluation/run_benchmarks.py` (a `key=` entry, per the existing
   cicids2017 / ctu13 / unsw / bournemouth pattern) and add its measured coverage
   curve to `evaluation/BENCHMARKS.md`, clearly labelled **constructed /
   injection-based** so it is never mistaken for a natively-labelled real
   capture. A test guard pins the coverage floor.

**You have a result when …** there is a **published, reproducible** fan-in
benchmark (data-construction script + registry row + test) **and** a measured
coverage curve of the detector against calibrated fan-in stars. "The harness
*could* do it" is not the result; a committed, reproducible benchmark with a
number is.

**Proof obligations.** An injection benchmark measures **recall against planted
ground truth honestly, but never field precision** — a synthetic fan-in star is
not proof of real-world separability (`bwl-validation-and-qa` tier discipline; the
synthetic-numbers-are-a-stress-test rule at the top of `BENCHMARKS.md`). Present
it as *coverage of a controlled blind spot*, explicitly weaker than a
natively-labelled real capture, and keep hunting for a real one (absence of a
benchmark is not proof the blind spot is empty — `FINDINGS.md`).

---

## Problem 4 — Cross-domain schema-agnostic generality (band adaptation)

**Honestly labelled HARD.** This is the "does the method transfer beyond
netflow?" question, and the one live data point is a **negative**: Bournemouth
web logs scored recall 0.873 / precision **0.028** — *below* the 0.029 base rate,
worse than chance (`BENCHMARKS.md` L49; `FINDINGS.md` "Domain transfer"). State
that up front in any pitch of this bet; do not sell it as a near-win.

**Why SOTA "fails" here is subtle — it is a method limit, not a bug.** Under the
scale-invariant actor selection `session_id` **is** admitted as a per-entity
actor, and `entity_monotony` over it **over-flags** (~92% of rows): a monotone
human session is as self-similar as a bot session, so the rule fires on humans
too. This is the method limit shown *directly* — the Phase-1 diagnosis predicted
it (forced active under the old band, `entity_monotony` caught **0 of 11** bot
sessions and flagged monotone *humans*), because bot and human diversity, timing
CV, request entropy and volume all **overlap** (`FINDINGS.md`; `TODO.md` item 12).
So entity selection is *not* the lever for the human-mimicking web-bot case.

**Where the real frontier is (and isn't).** The earlier *band-adaptation*
question — can actor typing adapt to a new schema's cardinality without breaking
the netflow gates? — was **partly delivered** by the scale-invariance work: the
cardinality-ratio band is gone, replaced by scale-invariant recurrence/repeat-mass/
value-shape tests that type entities by *shape relative to the batch* rather than by
absolute ratio constants. What remains open is the **value-shape residual**: a
closed pool of *short unstructured* ids (bare integers, usernames) and *content*
columns (a raw request-`path`) are still shape-ambiguous — see TODO follow-ups H/I.
Cross-domain generality on that residual is the live frontier.

**But note the hard boundary:** even perfect actor typing does **not** fix
Bournemouth, because the features do not separate the classes there at all — that
is `bwl-webbot-campaign` / TODO item 12, a separate biometric capability, not an
actor-selection problem.

**This repo's specific asset.** The whole detector is already **schema-by-shape,
never by name** (`_actor_endpoint_columns`, `_entity_columns` in `features.py`),
and the runner is skip-if-absent, so a new domain capture drops in without
bespoke code. The band is the single localised knob that decides transfer.

**The first three concrete steps (scoped narrowly).**

1. **Instrument the band decision on ≥2 non-netflow captures.** For each
   candidate domain log, dump every candidate column's cardinality ratio and
   whether it lands in/below/above the band, and *by hand* identify the true
   actor. Map the gap between "what the band picks" and "the real actor". This
   tells you whether an adaptive band is even the right lever for that capture
   (for Bournemouth the answer was *no* — do not repeat that mistake blindly).
2. **Prototype an adaptive band (gap/knee on the ratio distribution) behind a
   flag** and re-measure on the instrumented captures **and** the netflow gates.
   The bar is non-negotiable: netflow gates held *exactly* (CICIDS 0.998/0.846,
   CTU-13 sc1 1.000/0.978, sc3 0.985/0.929) or the change is dead on arrival.
3. **Predict, then measure, on one honestly-labelled out-of-domain capture where
   a real signal plausibly exists** (a scarce find — see the dataset-pool sweep
   in `BENCHMARKS.md`: Zenodo/IDS2018/ISIT all skipped on honesty grounds).
   Absent one, this bet stays **open**, and the band work is filed as robustness
   (TODO item 4/5), not a frontier win.

**You have a result when …** an adaptive-band change lifts detection on a
**genuinely out-of-domain, honestly-labelled** capture **with every netflow gate
held** — measured, reviewed, pinned. Until such a capture exists and that holds,
every claim here stays labelled **open / candidate**.

**Proof obligations (heaviest of the four).** Per `bwl-external-positioning`: no
cross-domain generality claim until it is *measured* on real out-of-domain
labels — the Bournemouth negative is the standing counter-evidence and must be
cited alongside any positive. Never present the schema-agnostic *design* as
proven cross-domain *capability*; those are different claims. Do not conflate
this with the web-bot campaign — mixing them re-imports the exact "force the
band" error the Phase-1 diagnosis already refuted.

---

## Cross-cutting discipline for every bet

- **Pre-register or it doesn't count.** Write the protocol and the success
  threshold before the run. A number that only became "the milestone" after you
  saw it is not evidence (`bwl-research-methodology`).
- **Predict before you run.** Each new scenario/capture/mechanism gets a written
  prediction first; surprises are where the learning is.
- **Guards, not vibes.** A frontier win must land as a registry row +
  benchmark test, so it cannot silently regress (`bwl-validation-and-qa`).
- **The four non-negotiables never bend:** unsupervised means no labels at
  decision time; scores are rank-order, not probabilities; synthetic/injection
  recall is honest but is not field precision; route every shipped change through
  the review path in `bwl-change-control`.

## Provenance and maintenance

Authored 2026-07-04 (revised against repo state on this session). Repo at commit
**8a85edd** (`git rev-parse --short HEAD` at authoring). All numbers below are
recorded benchmark figures cited from `evaluation/FINDINGS.md` /
`evaluation/BENCHMARKS.md` — **not** re-run here (the full suite is slow and the
captures are gitignored).

| Volatile fact | One-line re-verification |
|---|---|
| HEAD commit is 8a85edd | `git -C /Users/isabella/bots-without-labels rev-parse --short HEAD` |
| CTU-13 sc1 1.000/0.978, sc3 0.985/0.929; CICIDS 0.998/0.846 | `grep -nE '0\.978\|0\.929\|0\.846' /Users/isabella/bots-without-labels/evaluation/BENCHMARKS.md` |
| Residual FP is mostly ML-only (Rbot 151/151; CICIDS ~253/358) | `grep -n "ML-only" /Users/isabella/bots-without-labels/evaluation/FINDINGS.md` |
| Decision rule + heuristic cutoff 0.70 | `grep -n "HEURISTIC_CUTOFF\|is_bot =" /Users/isabella/bots-without-labels/bots_without_labels/pipeline.py` |
| Shipped archetypes (no fan-in among them) | `grep -n "^ARCHETYPES" /Users/isabella/bots-without-labels/bots_without_labels/synthetic.py` |
| Injection clusters one value per column (no fan-in star yet) | `sed -n '152,181p' /Users/isabella/bots-without-labels/bots_without_labels/inject.py` |
| Scale-invariant actor tests 0.3 / 200 / 0.5 | `grep -n "REPEAT_MASS_MIN\|VOCAB_MAX_DISTINCT\|STRUCTURED_TOKEN_MIN" bots_without_labels/features.py` |
| feature_deviations() shipped (TODO item 3) | `grep -n "def feature_deviations" /Users/isabella/bots-without-labels/bots_without_labels/anomaly.py` |
| CTU-13 scenario wrapper (`--scenario` / `--binetflow`) | `grep -n "SCENARIOS\|--binetflow" /Users/isabella/bots-without-labels/evaluation/ctu13_bot_benchmark.py` |
| run_benchmarks --only keys | `grep -n 'key=' /Users/isabella/bots-without-labels/evaluation/run_benchmarks.py` |
| No public fan-in-bot benchmark (verified absence) | `grep -n "no real external fan-in" /Users/isabella/bots-without-labels/evaluation/FINDINGS.md` |
| Bournemouth negative 0.873/0.028, method-limit not bug | `grep -n "0.873\|Phase-1 diagnosis" /Users/isabella/bots-without-labels/evaluation/FINDINGS.md` |
| Garcia et al. 2014 is the CTU-13 baseline citation | `grep -n "Garcia\|empirical comparison" /Users/isabella/bots-without-labels/evaluation/ctu13_bot_benchmark.py` |
| Full suite collects and passes | `uv run pytest --collect-only -q \| tail -1` |

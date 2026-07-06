---
name: bwl-failure-archaeology
description: The chronicle of every investigation, dead end, and rejected fix in Bots Without Labels — load this BEFORE re-attempting a rule/threshold change, adding or forcing an actor column, chasing a "why is precision below the base rate?" mystery, proposing undirected degree signals, forcing session_id on web logs, or picking a new external dataset. Answers "have we tried this before, and what happened?" and "why is the rule shaped this way?" Triggers on: entity_monotony, asymmetric_degree, hub gate, Proto/State over-flagging, CTU-13/CICIDS/Rbot/Bournemouth precision surprises, per-entity baselining, source fan-out, dataset selection.
---

# BWL Failure Archaeology

The record of settled battles, so nobody re-fights one. Every arc below is
`symptom → root cause → evidence → fix → verified numbers → status`. If your idea
matches an entry marked **SETTLED**, the burden is on you to show what is *different
now* — the last person who tried it has already paid the cost.

**Jargon note:** unfamiliar terms (NetFlow, C2, fan-in/fan-out, botnet families) are
defined in `netflow-botnet-reference`; the detector maths (robust z/MAD, entropy,
isolation forest, adaptive percentiles) in `bwl-detection-theory`. This skill assumes
those and focuses on *history*.

## When NOT to use this skill

| Your situation | Use instead |
|---|---|
| A **live** failure you are triaging right now (symptom → what to check) | `bwl-debugging-playbook` |
| You want the *current* design and invariants, not the history that produced them | `bwl-architecture-contract` |
| You want to know what a flag/constant *does*, not why it exists | `bwl-config-and-flags` |
| You need to *measure* something (run a diagnostic, benchmark) | `bwl-diagnostics-and-tooling` |
| You need the evidence bar for a *new* result | `bwl-research-methodology`, `bwl-validation-and-qa` |
| You are planning the web-bot capability (TODO item 12) | `bwl-webbot-campaign` |

This skill is the *past*. When a past decision is still binding as a rule you must not
break, that rule also lives in `bwl-change-control` (non-negotiables) — this skill
supplies the story behind it.

## How to read the timeline

39 linear commits, 2026-06-22 → 2026-07-04 (repo at `6fd33ac`). The `git log` order is
topological, **not** date order — verify a hash's real date with
`git show -s --format='%ci %s' <hash>`. Narrative order of the work (not log order):

| # | Arc | Key commit(s) | Date |
|---|---|---|---|
| 1 | Foundation: rebrand + genericisation | `751a67d`..`f8fbbad` | 06-22 |
| 2 | Robustness audits A / B | `1be2385`, `17b6bc5` | 06-22 |
| 3 | Mechanical-timing blind spot | `53251dc` | 06-22 |
| 4 | **The synthetic-lied-to-us crisis** → per-entity → hub → timing | `98646c1`, `41d8162`, `b6023d4`, `e6ded7a` | 06-23 → 06-24 |
| 5 | Actor graph (`asymmetric_degree`) + precision root-cause | `2a3f362`, `56f305d` | 06-25 → 06-29 |
| 6 | Rbot generality + fan-in FP materialises → source fan-out | `2fe88f7`, `13e9436` | 06-29 → 06-30 |
| 7 | Bournemouth honest negative (domain transfer) | `5f20e40`, `6c66306` | 06-30 |
| 8 | Formalisation & engineering audits | `8dd5519`, `43b5e86`, `1f69f4b`, `529aee3`, `1a4abeb` | 06-27, 07-03/04 |

The full measured narrative of arcs 4–7 is `evaluation/FINDINGS.md`; the registry with
per-benchmark caveats is `evaluation/BENCHMARKS.md`. Cite those as the docs of record.

---

## Arc 1 — Foundation: rebrand and genericisation (751a67d..f8fbbad, 06-22)

- **Symptom / motivation:** the project began as "Bot Hunter", a click-fraud-specific
  tool. The goal became a *schema-generic* detector for any unlabelled log.
- **What changed:** rebrand (`751a67d`); the web dashboard was **removed**, visual
  analysis moved to the notebook (`4ffa32b`); autodetecting loader + schema inference
  (`321facb`); schema-driven feature engineering (`d2f299e`); generic detection engine
  + synthetic data + label injection (`ff4d8f0`); test suite (`3fd0de1`); narrative
  notebook (`f8fbbad`).
- **Load-bearing consequence:** click-specific behaviour appears **only** when the
  relevant columns are detected — never as a hardcoded branch. This is why later actor
  rules must pick columns *by shape, never by name* (arcs 5–6). Any change that parses a
  column *name* to decide behaviour violates the founding contract.
- **Status:** SHIPPED foundation (TODO items 1 & 2). Not a battle — the baseline.

## Arc 2 — Robustness audits A / B (1be2385, 17b6bc5, 06-22)

- **Symptom:** missing / blank cells were being counted as real behaviour. A blank
  timestamp produced a **false STRONG "same-instant burst"** — many rows with an empty
  time all landed in one zero-gap pile and read as a perfectly synchronised burst.
- **Root cause:** the feature layer counted a missing cell as a value. Concentration,
  repetition, and same-instant bursts all inflated on absence.
- **Fix (`17b6bc5`):** a missing cell gets **count 0** and is dropped from distinct
  group sizes; numeric median-fill is guarded so an all-missing numeric column cannot
  put NaN into the feature matrix; `anomaly.py` defensively replaces NaN/inf before
  scoring (isotree fails on NaN); the adaptive count threshold became the **99th
  percentile of distinct group sizes bounded by a floor** — robust to the bot fraction
  because bots are few distinct values and don't inflate their own threshold.
- **Verified:** recall stayed 100% across archetypes, planted-precision 1.00, ~0.8%
  pure-legit FP.
- **SETTLED:** *missing values are absence, not evidence.* Do not "fill" a blank and let
  it score. Do not reintroduce whole-batch concentration as STRONG (arc 4 explains why
  global concentration was capped).

## Arc 3 — Mechanical-timing blind spot (53251dc, 06-22)

- **Symptom:** a bot injecting a regular cadence into a *popular* context value was
  invisible. In the generic-injection path `mechanical_timing` recall sat at **0.0–0.2**
  while the synthetic path (where bots get unique contexts) scored ~1.0 — a classic
  "synthetic looks fine, realistic case fails" split.
- **Root cause:** inter-arrival regularity was measured over the **whole categorical
  context group**. Scattered legitimate rows sharing that popular value inflated the
  group's inter-arrival variance, so the bot's regular sub-sequence never stood out.
- **Fix:** measure regularity **per burst-run** — a maximal sub-sequence whose
  consecutive gaps stay within the burst window — isolating the cadence from surrounding
  traffic. Same-instant piles (zero mean gap) are left to `same_instant_burst`, not
  scored as "perfectly regular" (avoids inventing FPs on coarse/repeated timestamps).
  The context field `group_size` was renamed `run_size`.
- **Verified:** generic-path `mechanical_timing` recall **0.0–0.2 → 1.0**, zero new
  legitimate FPs across both paths.
- **Lesson (recurring):** granularity of the aggregation window *is* the signal. A
  pattern buried in a coarse group needs a finer sub-group to surface. The same shape of
  bug returns in arc 4 (global vs per-entity) and arc 5 (whole-batch vs per-actor).
- **Status:** SHIPPED.

---

## Arc 4 — THE synthetic-lied-to-us crisis (98646c1 → e6ded7a, 06-23 → 06-24)

The pivotal arc. Read `evaluation/FINDINGS.md` §"The failure" through §"The honest
ceiling" in full before touching `entity_monotony`, the hub gate, or timing gating.

### 4a. The crisis (98646c1, 06-23)

- **Symptom:** on the first *fair, externally-labelled* botnet benchmark (CICIDS2017
  Friday-morning, Ares), the detector scored **recall 0.022, precision 0.018** against a
  **base rate 0.032**. Precision *below the base rate* means a flagged row was **less**
  likely to be a bot than a randomly chosen one. The synthetic suite was simultaneously
  ~1.0. The measurement tool and the detector shared one blind assumption.
- **Root cause (a design tension, not a bug):**
  1. The bot signal is concentration/repetition (infected hosts beacon one C2,
     `205.174.165.73`, with near-identical flows).
  2. The earlier "honest archetype" audit had **downgraded repetition/concentration to
     supporting-only (capped 0.24)** to avoid flagging popular *legitimate* values —
     leaving only sub-second **timing** as strong evidence.
  3. CICIDS is **minute-quantised at source**, so adaptive timing thresholds are set by
     busy benign minutes and never fire on the bot.
  Net: heuristics flagged busy-but-benign entities and missed obvious bots.
- **Process note:** committed **directly to main**, bypassing the PM-commits-only HCOM
  protocol. Tracked as unresolved review debt — **TODO follow-up G** (commit `98646c1`).
  It has since been repeatedly benchmark-verified, so it is *protocol debt, not
  correctness risk* — but do not cite it as precedent for skipping review.

### 4b. First fix — per-entity behavioural diversity (98646c1)

- **Fix:** instead of *global* concentration, score each **entity** (actor-like column,
  e.g. Source/Destination IP) by how self-similar *its own* events are — the mean
  normalised entropy of its behaviour across the other columns
  (`features.py::_entity_baseline`, the `entity_monotony` rule in `rules.py`). A botnet
  host does one thing repeatedly (low diversity); a popular legit host fans out (high
  diversity).
- **Verified:** recall **0.022 → 0.998**, but **precision only 0.144** at a **21.9% flag
  rate**. Per-entity diversity is a strong *ranking* signal, not a clean separator: a
  busy *legitimate* channel (backup job, keepalive, one client hammering one server) is
  just as monotonous as a beacon and dominates the monotonous tail.

### 4c. Second discriminator — relational hub gate (41d8162, 06-23)

- **Insight:** genuine bots and the residual FPs differ not in *how repetitive* but in
  *how connected*. A C2 is a **hub** (a fan-in star: many distinct hosts → one
  destination); a benign monotone channel is **point-to-point** (one source ↔ one
  destination). Identical to diversity; obviously different the moment you count
  *distinct counterparts* (**degree**).
- **Fix:** `entity_monotony` no longer escalates to a strong on-its-own flag on monotony
  alone. When the log exposes ≥2 stable entity columns (edges exist), a monotone
  high-volume entity is escalated **only if it is also a hub** — ≥ `MIN_HUB_DEGREE = 3`
  distinct counterparts. `K = 3` is a deliberately small *structural* minimum (a star
  needs more than a pair of spokes); it is **not tuned to this botnet's fan-out**. With
  0–1 entity columns the rule falls back to monotony alone (low-dim logs unaffected).
- **Verified:** precision **0.144 → 0.441**, flag rate **0.219 → 0.072**, recall held.

### 4d. Third fix — timing calibration on coarse clocks (b6023d4 → e6ded7a, 06-24)

- **Symptom:** whole-minute timestamp bins were still firing the dense-timing rules as
  noise on coarse-clock logs.
- **Fix:** gate the dense (sub-second) timing rules **off adaptively by detected
  timestamp resolution**, so minute-quantised logs stop generating timing noise.
- **Verified (current CICIDS):** **recall 0.998, precision 0.846, flag rate 0.037**
  (`evaluation/BENCHMARKS.md`; reproduce with
  `uv run --extra eif python -m evaluation.cicids_bot_benchmark --zip data/GeneratedLabelledFlows.zip`).
- **Watch the WIP checkpoint:** `b6023d4` is an explicitly **UNREVIEWED WIP checkpoint**
  ("timestamp-resolution gate for dense-timing rules"). It is *not* a clean reference
  point — the reviewed, calibrated version is `e6ded7a`. When bisecting, do not treat
  `b6023d4` as a stable state.
- **Residual (honest ceiling):** 0.846 is one attack family, one hub. Of 358 FPs in the
  per-rule diagnostic (2,320 flags), **~253 are ML/EIF-only** and **~104 are
  `entity_monotony`** — so residual error is *not* dominated by benign monotone hubs;
  most is the ML path, a separate calibration question that motivated TODO item 3
  (ML-tail explanations, arc 8).
- **Status:** SHIPPED. The CICIDS win is pinned by `tests/test_real_benchmark.py`
  (recall ≥ 0.95, precision ≥ 0.35, flag ≤ 0.12).

---

## Arc 5 — Actor graph and the precision root-cause (2a3f362, 56f305d, 06-25 → 06-29)

### 5a. The diverse outbound bot the CICIDS rules miss (2a3f362)

- **Symptom:** CTU-13 scenario 1 (Neris) is the *opposite* shape to CICIDS: one infected
  host (`147.32.84.165`) reaches out to *many* destinations (spam + C2 + click fraud).
  Reaching many counterparts reads as **high** diversity, so both `entity_monotony` and
  the diversity-gated hub gate walk past it. With microsecond timestamps and dense-timing
  rules *active*, the pre-fix detector scored **recall 0.113, precision 0.005, flag rate
  0.757**. This was the documented **method limit** — resolution alone did not recover
  the bot; the missing signal is **directional asymmetry of connectivity**.
- **Fix:** the `asymmetric_degree` rule (strong, weight 0.70) on an actor-endpoint graph.
  It **first shipped deliberately direction-agnostic** — a schema-generic detector cannot
  reliably tell a source column from a destination column by name, and name-parsing is
  the coupling arc 1 forbids. Endpoints are chosen **by shape**: a recurring,
  high-cardinality token column whose **cardinality ratio** sits in the band
  `ACTOR_MIN_RATIO = 0.02` to `ACTOR_MAX_RATIO = 0.5` (`_actor_endpoint_columns` in
  `features.py`). The band separates a genuine actor from a *bounded categorical* below
  it (protocol, TCP state, region) and a *per-row edge id* above it (flow id, 5-tuple).
  The rule fired on a high-volume endpoint whose degree exceeds an adaptive floor
  (`DEGREE_FLOOR_PERCENTILE`, 99th pct of the hub subset), **and** exceeds its
  reverse-role degree by ≥ `DEGREE_ASYMMETRY = 10`, **and** is monotone in service.
- **Verified:** recall **0.113 → 1.000** (2,000/2,000 positives, **zero** false fires,
  uniquely carrying 1,774), but **overall precision only 0.041** at flag rate 0.785.

### 5b. The precision root-cause was NOT the new rule (56f305d, 06-29)

- **Symptom:** the middle-row 0.041 precision looked like `asymmetric_degree` was noisy.
  It was not.
- **Root cause:** `entity_monotony` was treating the **degenerate `Proto` / `State`
  columns** as if they were actors and over-flagging the diverse NetFlow background.
  `Proto`/`State` are *bounded categoricals* (a handful of values across the batch).
- **Fix (reuses existing machinery):** apply the **same actor cardinality-ratio band**
  that `_actor_endpoint_columns` uses to the columns `entity_monotony` baselines over
  (`_entity_columns`). `Proto`/`State` fall **below** the band → excluded. Real actor
  columns (Source/Destination address) sit **in** the band → kept. **No constant was
  tuned to CTU-13.**
- **Verified:** CTU-13 precision **0.041 → 0.978**, flag rate **0.785 → 0.033**, recall
  held **1.000**. CICIDS **unchanged** (there Source IP/Destination IP stay in-band, so
  `entity_monotony` keeps its recall-carrying role). The same band change made UNSW-NB15
  more conservative: recall 0.561 → 0.122, precision 0.090 → 0.198, flag 0.201 → 0.020
  (broad IDS, not a bot capture — lower recall is no bot regression).
- **CITE THE VERIFIED NUMBER:** an earlier per-rule *counterfactual projection* (removing
  degenerate-column fires from the diagnostic) estimated **0.956**. That was a
  **projection**. The **actual verified precision on the re-run pipeline is 0.978** — cite
  0.978, never 0.956. Verified rina review #37205 against mono's table #37143.
- **Status:** SHIPPED. CTU-13 recall win pinned by `tests/test_ctu13_benchmark.py`
  (recall ≥ 0.95).

---

## Arc 6 — Rbot generality: the predicted fan-in FP materialises (2fe88f7, 13e9436, 06-29 → 06-30)

The honest ceiling of arc 5 explicitly demanded a *second labelled family* before reading
the `asymmetric_degree` win as more than same-family evidence. This arc supplied it — and
the predicted failure happened exactly on schedule.

- **Symptom:** running the identical pipeline on CTU-13 scenario 3 (**Rbot**, an
  IRC-controlled DDoS/scan botnet, same Argus NetFlow / CC-BY capture) gave **recall
  0.985** (the connectivity-asymmetry signal generalised straight away) but **precision
  collapsed to 0.056 at a 0.567 flag rate** (`2fe88f7`).
- **Attribution (unambiguous, and NOT the arc-5 story):** `asymmetric_degree` itself fired
  on **34,995 rows** — 1,970 TP, **33,025 FP**, stand-alone fire-precision 0.056. The rule
  that was a clean 2,000/2,000-zero-FP catch on Neris was the *direct* source. The arc-5
  culprit was ruled out: `entity_monotony`'s entity columns were **empty** here (no
  Proto/State over-flagging).
- **Root cause (structural):** an **undirected** asymmetry rule cannot tell a bot's
  **fan-out** (one source → many counterparts) from benign **fan-in** infrastructure (DNS
  resolver, NTP source, load balancer: many clients → one server). Both are high-degree,
  monotone, role-asymmetric stars. On Rbot the benign fan-in hubs vastly outnumber the bot.
- **Fix (`13e9436`):** narrow the rule to the **source / fan-out side only** — it fires
  only where a value's **out-degree ≥ 10 × in-degree** (broadcasting-source shape). The
  source endpoint is taken by **schema column order** (source precedes destination in flow
  logs, `SrcAddr` before `DstAddr`) — a positional convention, **not** name-parsing, with
  the honest caveat that it assumes that ordering. Passive fan-in hubs are now owned by
  `entity_monotony` / the hub gate instead.
- **Verified (no detector thresholds tuned):** Rbot precision **0.056 → 0.929**, flag rate
  **0.567 → 0.034**, recall held **0.985**. `asymmetric_degree` now fires **1,970 TP / 0
  FP** on Rbot (as clean as Neris); the 151 residual FPs are **ML-only**. Verified rina
  review #38226; original split by mono #37642.
- **Guarded residual:** there is **no real external fan-in-bot benchmark**. A source-only
  rule could in principle miss a bot that is *itself* a fan-in C2. The only real labelled
  fan-in C2 in the data is CICIDS (many hosts → `205.174.165.73`), where the catch is
  carried by `entity_monotony` (`asymmetric_degree` fires 0). CICIDS is used as
  **no-regression evidence** that the fan-in case stays covered — **not** positive proof
  that fan-in detection generalises. Still two scenarios of one dataset (CTU-13).
- **Status:** SHIPPED (TODO closed; item 9 largely delivered). This arc is the model case
  for `bwl-research-methodology`'s predict-before-run: the fan-in FP was *predicted* in
  arc 5's ceiling, then observed.

---

## Arc 7 — Bournemouth: the honest negative (5f20e40, 6c66306, 06-30)

Everything above is *network-flow* data. The first **different-domain** test — raw Apache
access logs (Bournemouth Web Bot Detection) — is an honest **negative**, and recording it
matters as much as the wins.

- **Symptom:** on 58,279 rows (base rate 0.029, real folder labels `bots/` vs `humans/`),
  the detector scored **recall 0.474, precision 0.020** — *below* the base rate, worse than
  chance, flagging 68% of rows.
- **Root cause (two domain-transfer effects, neither a detector regression):**
  1. **Actor rules went dormant.** `session_id` is a real recurring entity, but its
     cardinality ratio falls **below** the actor band, so it is read as a bounded
     categorical, not an actor endpoint. With no in-band actor column, both
     `entity_monotony` and `asymmetric_degree` never engaged.
  2. **Timing over-fired on page-load bursts.** Left with only timing + ML, the sub-second
     timing rules misread near-simultaneous requests from a single page-load as automated
     cadence.
- **Phase-1 diagnosis — it is a METHOD limit, not an entity-selection bug (`6c66306`):**
  forcing `session_id` active anyway **does not help**. With `session_id` baselined as the
  entity, `entity_monotony` caught **0 of 11** bot sessions and instead flagged *monotone
  human* sessions. Bot and human **diversity, timing coefficient-of-variation, request
  entropy, and volume all overlap** — the human-mimicking web bots are, on the axes the
  detector measures, indistinguishable from people.
- **Two honest caveats on the number:** the positive set is **tiny — 11 bot sessions** (263
  human), so this is *qualitative* domain-transfer evidence, not a robust estimate; and the
  numbers are **provisional / local-internal** pending a licence decision (research-use
  invited, copyright reserved). Measured mono, verified rina #38700.
- **Status:** SETTLED as a method limit. Closing it needs **web-specific signals**
  (interaction biometrics / mouse dynamics, which Bournemouth ships) — a separate future
  capability tracked as **TODO P3 item 12**, planned in `bwl-webbot-campaign`. It is **not**
  calibration and **not** a tweak to the existing rules. The netflow gates are unchanged.

---

## Arc 8 — Formalisation and engineering audits (8dd5519, 43b5e86, 1f69f4b, 529aee3, 1a4abeb)

- **`8dd5519` (06-27)** — the ad-hoc scripts became a tracked, skip-if-absent benchmark
  suite behind one runner (`evaluation/run_benchmarks.py`).
- **`43b5e86`, `1f69f4b`, `529aee3` (07-03)** — engineering hygiene, not behaviour: extract
  constants + expose tuning params + complete docstrings; deduplicate test fixtures via a
  shared `conftest`; consolidate benchmark boilerplate into `evaluation/harness.py`. No
  measured numbers changed.
- **`1a4abeb` (07-04)** — ML-tail flags now carry their top feature deviations (robust z +
  batch percentile) in `selected_events.json` and via `DetectionResult.feature_deviations()`
  (TODO item 3). Motivated directly by arc 4's residual: after rule calibration, *all*
  remaining FPs were tier-3 ML-only flags, which were previously opaque.
- **Status:** SHIPPED. These are the reason `bwl-diagnostics-and-tooling` and
  `bwl-config-and-flags` have a clean surface to document.

---

## SETTLED BATTLES — do NOT retry without new evidence

| Idea / temptation | Why it was rejected | Evidence anchor |
|---|---|---|
| **Undirected / direction-agnostic `asymmetric_degree`** | Fires on benign fan-in infrastructure (DNS/NTP/LB). On Rbot it fired 34,995 rows, 33,025 FP, precision 0.056. Fixed by narrowing to **source fan-out** (out ≥ 10× in). | Arc 6; `13e9436`; FINDINGS §"The second-family test" |
| **Global / whole-batch concentration as STRONG evidence** | Fires on popular *legitimate* values; capped to supporting-only (0.24). This cap is *why* CICIDS needed per-entity diversity. Reinstating it re-breaks precision. | Arcs 2 & 4; `98646c1`; FINDINGS §"The failure" |
| **Forcing `session_id` (or any below-band column) to be an actor entity on web logs** | `entity_monotony` then catches 0/11 bots and flags monotone humans. Trades a clean "dormant by data" state for active FPs with no recall. It is a **method limit**, not a config lever. | Arc 7; `6c66306`; FINDINGS §"Phase-1 diagnosis" |
| **Parsing column *names* to decide source/destination or actor-ness** | Violates the founding schema-generic contract (arc 1). Direction is taken by *positional* column order; actor-ness by *cardinality shape*. | Arcs 1, 5, 6 |
| **Counting missing/blank cells as behaviour** | Produced false STRONG "same-instant burst" on blank timestamps. Missing = count 0, dropped from distinct sizes. | Arc 2; `17b6bc5` |
| **Tuning `MIN_HUB_DEGREE`, `DEGREE_ASYMMETRY`, or the floor percentile to a capture** | `K=3` and `DEGREE_ASYMMETRY=10` are deliberately *structural minima*, not fitted to Neris/Rbot fan-out. Fitting them overfits one capture and voids the generality claim. | Arcs 4c, 5a; FINDINGS honest-ceiling bullets |
| **Citing 0.956 as the CTU-13 precision** | 0.956 was a per-rule *counterfactual projection*; the verified re-run pipeline number is **0.978**. | Arc 5b; FINDINGS §"The precision fix" |

## OPEN / DEFERRED (not settled — genuinely unfinished)

| Item | State | Where tracked |
|---|---|---|
| **Fixed 10th-percentile diversity quantile** | Brittle: on real flow data many entities share identical diversity, so the quantile lands on a **tie at a bin edge** and the cut is sensitive to tie-breaking. Needs an *adaptive* gap/knee cut — a redesign, **deferred** to threshold-calibration work. | FINDINGS §"The honest ceiling"; `bwl-research-frontier` |
| **ML/EIF-only false positives** | ~253 of CICIDS's 358 FPs are ML-path, a separate calibration question. Partly addressed by explanations (`1a4abeb`), not by score calibration. | Arcs 4d, 8; TODO item 10 |
| **Fan-in-bot generality** | *Guarded* by CICIDS no-regression, **not** positively proved — no natively-labelled fan-in-bot benchmark exists. | Arc 6; FINDINGS takeaway |
| **Per-entity change review debt** | `98646c1` bypassed PM-commits-only protocol; benchmark-verified but not Codex-reviewed. | TODO follow-up G; `bwl-change-control` |

## Rejected external datasets — with reasons (don't re-propose without new access)

| Source | Dataset | Why rejected |
|---|---|---|
| Hugging Face | `mindweave/web-server-logs` | Flagged rows' bot-UA rate ≈ base rate — **no lift** to measure. |
| Kaggle | `tunguz/clickstream-data-for-online-shopping` | **No labels**; surfaced over-long sessions only. |
| Local zip | CICIDS2017 **PortScan** flows | Attacks were **55%** of the sample — the majority, so **not anomalous**. |
| Zenodo 3477932 (CC-BY-4.0) | Web Robot Detection server logs | Labelled files are aggregated per-session features (no raw entities/timestamps); raw events have entities but **no joinable label**. Deriving a label from IP/UA/time is **circular leakage** (the detector keys on those). |
| AWS open-data | CSE-CIC-IDS2018 botnet day | Official processed CSVs are **IP-stripped** (only bounded `Dst Port`) → actor/graph/monotony rules stay **dormant**. Recovering IPs needs CICFlowMeter reprocessing, out of scope. |
| Kaggle | ISIT-2024 "Bits and Bots" | Accessible files are **two bot classes** (`gremlins/`, `hlisa_traces/` — HLISA *generates* human-**like** bot traces, not real users). No accessible human label → a run would be **bot-vs-bot**. **HLISA must never be labelled "human."** Skipped per boss decision. |

Kept (measured) benchmarks and their current numbers live in `evaluation/BENCHMARKS.md`;
this table is the *graveyard* so each rejection is a documented decision, not a silent gap.
Clean web-bot benchmarks pairing real entities, real timestamps, and a real human-vs-bot
label are genuinely scarce — see `bwl-external-positioning` before claiming otherwise.

---

## Provenance and maintenance

Authored 2026-07-04 (last repo review 2026-07-06); repo at commit `6fd33ac`. This is a
*historical* chronicle — the commit hashes and root-cause stories are stable, but the
"current" measured numbers drift as new arcs land. Re-verify before quoting a live number.

| Volatile fact | One-line re-verification |
|---|---|
| Commit count / range / head | `git log --oneline \| wc -l && git log --oneline -1` |
| Arc hashes still present & dated | `git show -s --format='%ci %s' 98646c1 56f305d 13e9436 6c66306` |
| CICIDS current numbers (0.998 / 0.846 / 0.037) | `grep -n 'CICIDS2017 Friday' evaluation/BENCHMARKS.md` |
| CTU-13 sc1 numbers (1.000 / 0.978 / 0.033) | `grep -n 'scenario 1 (Neris)' evaluation/BENCHMARKS.md` |
| Rbot sc3 numbers (0.985 / 0.929 / 0.034) | `grep -n 'scenario 3 (Rbot)' evaluation/BENCHMARKS.md` |
| Bournemouth numbers (0.474 / 0.020) provisional | `grep -n 'Bournemouth' evaluation/BENCHMARKS.md` |
| Verified-not-projected CTU-13 precision is 0.978 | `grep -n '0.956\|0.978' evaluation/FINDINGS.md` |
| Rbot asymmetric_degree fired 34,995 rows | `grep -n '34,995' evaluation/FINDINGS.md` |
| Constants `MIN_HUB_DEGREE`/`ACTOR_MIN_RATIO`/`DEGREE_ASYMMETRY` | `grep -rn 'MIN_HUB_DEGREE\|ACTOR_MIN_RATIO\|ACTOR_MAX_RATIO\|DEGREE_ASYMMETRY' bots_without_labels/` |
| TODO follow-ups F/G/H still open | `grep -n '^### [FGH]\.' TODO.md` |
| Rejected-dataset table intact | `grep -n 'Bits and Bots\|Zenodo\|IP-stripped' evaluation/BENCHMARKS.md` |
| Tests that pin the wins still exist | `uv run pytest tests/test_real_benchmark.py tests/test_ctu13_benchmark.py --collect-only -q` |

When a new arc lands: add it here as `symptom → root cause → evidence → fix → verified
numbers → status`, move any newly-settled temptation into the SETTLED BATTLES table, and
promote or retire the matching OPEN/DEFERRED row. Do not delete a settled row — a future
session needs to know it was tried.

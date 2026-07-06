---
name: bwl-debugging-playbook
description: >
  Symptom-to-fix triage for the Bots Without Labels detector when it MISBEHAVES on a
  dataset. Load this when: recall collapsed on a real/labelled capture but the synthetic
  suite is green; precision is below the base rate (worse than guessing); a rule never fires
  or is "dormant"; same_instant_burst / timing rules fire everywhere; a mechanically-regular
  bot is missed in a popular context; a column got the wrong role (identifier read as
  categorical, timestamp missed); `isotree`/EIF is missing and scores look flat; a benchmark
  test is skipped. Also load when someone asks "why is the detector wrong on THIS log?",
  "which rule is costing precision?", or points at rule_diagnostic.py, features.py entity/actor
  gating, ingest role classification, or the thresholds dict.
---

# BWL debugging playbook

Imperative triage for when the detector produces the *wrong answer on a dataset* (bad
recall/precision, a rule that won't fire or won't stop firing, a mis-typed column). This is a
**runbook**, not theory. Every command below was run against the repo at commit `6fd33ac`.

New to the domain? One-line glossary you will need here:
- **flow / NetFlow** — one row = one network conversation (source IP, dest IP, protocol,
  bytes, timestamp). See `netflow-botnet-reference`.
- **botnet / C2** — many infected hosts "beacon" to one command-and-control server with
  near-identical, repetitive flows. That repetition/concentration is the signal.
- **base rate** — the fraction of rows that are actually bots. Precision *below* the base rate
  means a flagged row is *less* likely to be a bot than a row picked at random — worse than a
  coin weighted to the prior.
- **rule / heuristic** — an explainable per-row check (e.g. `entity_monotony`) that adds to a
  0–1 heuristic score. **ml_score** — the Extended Isolation Forest anomaly score (unsupervised).
- **the decision**: `is_bot = heuristic_score >= 0.70 (HEURISTIC_CUTOFF) OR ml_score >
  dynamic_knee_threshold` (the ML cut is rate-capped at `MAX_ML_FLAG_RATE = 0.02`).
  Verified in `bots_without_labels/pipeline.py:36,41`.

## When NOT to use this skill

| Your situation | Go here instead |
| --- | --- |
| The detector works; you want to *measure* it (run benchmarks, dump per-rule stats, feature deviations) | `bwl-diagnostics-and-tooling` |
| You want the *chronicle* of a past bug (full narrative, evidence, who fixed it, commit) | `bwl-failure-archaeology` |
| A crash / stack trace / import error / env breakage, not a *wrong answer* | `bwl-build-run-operate` |
| You want to understand WHY a rule or gate exists (design intent, invariants) | `bwl-architecture-contract` |
| You want the maths (entropy, robust z/MAD, isolation forest, Kneedle knee) | `bwl-detection-theory` |
| You want to change a constant/flag and know which are production vs guardrail | `bwl-config-and-flags` |
| The web-bot domain-transfer problem specifically (that is a known method limit, not a bug) | `bwl-webbot-campaign` |
| You proved a fix and need to land it (review pairs, DoR/DoD, who commits) | `bwl-change-control` |

**Golden rule of this playbook: reproduce before you theorise, and discriminate before you
fix.** The single most expensive class of mistake in this repo's history was "the synthetic
suite is green, ship it" — the synthetic suite shares the detector's own assumptions and
cannot see a real-data blind spot (this is the `98646c1` crisis, row 1).

---

## Master triage table

Read the symptom, run the first command, read the discriminator, jump to the deep section.

| # | Symptom | First command | Discriminator | Deep section |
| --- | --- | --- | --- | --- |
| 1 | Recall collapsed on a real/labelled capture, but the synthetic suite is green | `uv run --extra eif python -m evaluation.rule_diagnostic --zip data/GeneratedLabelledFlows.zip` | `n_tp`/`recall` near 0 while synthetic ~1.0 → real-data blind spot, NOT a regression the suite can see | [§1](#1) |
| 2 | Precision below the base rate (flagged row worse than a guess) | same `rule_diagnostic` run; read the **fire** and **fp_share** columns | one rule with high `n_fired`, low `fire_precision`, high `fp_share` = the precision drag | [§2](#2) |
| 3 | A rule never fires / is "dormant" | dump `result.rules_result.thresholds` (recipe in §0) | `*_graph_active == False`, or `entity_columns == []`, or `degree_floor == None` | [§3](#3) |
| 4 | `same_instant_burst` fires everywhere / precision tanks on a coarse-clock log | dump thresholds; read `timestamp_grid`, `dense_timing_gated` | `dense_timing_gated == True` should be *suppressing* on-grid rows; if grid is `None` it isn't | [§4](#4) |
| 5 | A mechanically-regular bot is missed when it hides in a *popular* context value | per-archetype recall (§1) on `mechanical_timing` | `mechanical_timing` recall low on generic injection but ~1.0 on synthetic | [§5](#5) |
| 6 | A column was classified into the wrong role (id read as categorical, timestamp missed) | inspect `loaded.schema` roles (recipe in §0) | walk the role chain against `PARSE_RATE`/`URL_RATE`/ratio thresholds | [§6](#6) |
| 7 | ML scores look flat / all-equal; `eif` behaviour absent | read `summary["ml_backend"]` (recipe in §0) | `"fallback"` (isotree not installed) or `"degenerate"` (too few rows/features) | [§7](#7) |
| 8 | A benchmark test is "skipped" and you expected it to run | `uv run pytest tests/test_real_benchmark.py -q -rs` | `skipped` = the gitignored dataset zip/binetflow is absent | [§8](#8) |

---

## §0 — Three inspection recipes you will reuse

These are the load-bearing "look at the state" moves. Build a tiny log once and reuse it.

**Dump the adaptive thresholds dict** (the single most useful artefact — it records what the
rule engine decided about *this* dataset):

```bash
uv run python - <<'PY'
from bots_without_labels.ingest import load
from bots_without_labels.pipeline import detect
lo = load("data/your_log.csv")          # or a tiny fixture
r = detect(lo.frame, lo.schema)
import json
print(json.dumps({k: str(v) for k, v in r.rules_result.thresholds.items()}, indent=1))
PY
```

Verified keys in that dict (source `bots_without_labels/rules.py`, confirmed by running on a
5-row fixture): `timestamp_grid`, `dense_timing_gated`, `entity_diversity_cut`,
`entity_columns`, `entity_graph_active`, `min_hub_degree`, `actor_columns`,
`actor_graph_active`, `degree_floor`, plus per-column maps `text_repeat`,
`categorical_concentration`, `numeric_reuse`, and the scalars `context_cluster`,
`same_instant`, `local_burst`.

**Inspect column roles** (why a column is treated the way it is):

```bash
uv run python - <<'PY'
from bots_without_labels.ingest import load
lo = load("data/your_log.csv")
for c in lo.schema.columns:
    print(c.name, "->", c.role, "cardinality_ratio", c.cardinality_ratio)
PY
```

**Read the ML backend** (from the pipeline summary dict, key `ml_backend`; also printed by the
`run` CLI):

```bash
uv run python -c "from bots_without_labels.ingest import load; from bots_without_labels.pipeline import detect; lo=load('data/your_log.csv'); print(detect(lo.frame, lo.schema).ml_backend)"
```

---

## §1 — Recall collapsed on real data, synthetic suite green  {#1}

**This is the crisis pattern (`98646c1`).** The synthetic suite plants bots using the same
assumptions the detector checks for, so it *cannot* fail the way real data does. On the
CICIDS2017 Ares botnet the pre-fix detector scored **recall 0.022, precision 0.018** (base rate
0.032 → precision *below* base rate) while the synthetic path read ~1.0. Recorded in
`evaluation/FINDINGS.md:41-52`.

Root cause of that specific incident: the bot signal is *concentration/repetition* (hosts
beacon to one C2), but an earlier "honest-archetype audit" had capped repetition/concentration
to supporting-only, leaving sub-second **timing** as the only strong signal — and those logs
are minute-resolution, so timing thresholds were set by busy benign minutes and never fired on
the bot. The fix added a strong per-entity **diversity** signal (`entity__diversity`,
`features.py::_entity_baseline`).

**Discriminate — is it a real blind spot or a bug you introduced?**

1. Run the per-rule attribution on the labelled mix:
   ```bash
   uv run --extra eif python -m evaluation.rule_diagnostic --zip data/GeneratedLabelledFlows.zip
   ```
   The **fire view** gives each rule's stand-alone precision; the **counterfactual view**
   (`fp_eliminated` / `tp_lost`) tells you which rule *carries* recall vs *costs* precision. If
   `tp_lost` is ~0 for every heuristic rule and the `ml-only` line carries the true positives,
   the heuristics have gone dormant (jump to §3).
2. Get **per-archetype recall** on synthetic injection to prove which behaviour class is lost.
   `evaluate_injection(..., archetypes=...)` returns a `per_archetype` map of
   `planted`/`recovered`/`recall` (`bots_without_labels/evaluate.py:17-58`). The archetypes are
   `("burst", "mechanical_timing", "diffuse_replay", "stealth")`; only
   `("burst", "mechanical_timing")` are the *detectable* set
   (`synthetic.py:23-24`). A collapse localised to one archetype points at the rule that serves
   it.
3. Compare against the pinned real-data guard: `tests/test_real_benchmark.py` *skips* when the
   dataset is absent (§8) but *fails* if a change silently reintroduces the blind spot. Run it.

**Fix path:** if real recall is genuinely gone, the lever is usually a rule that was gated too
tightly for real data. Do NOT re-tune by staring at synthetic numbers. Land any change through
`bwl-change-control`. Next skill: `bwl-diagnostics-and-tooling` (to measure) then
`bwl-failure-archaeology` (to check you are not re-walking a known dead end).

---

## §2 — Precision below the base rate  {#2}

Precision below base rate = a flagged row is less likely to be a bot than a random row. Almost
always **one rule over-fires** on the background.

**Command:** the same `rule_diagnostic` run as §1. Read the printed table columns:
`fired` (n_fired), `fire_p` (fire_precision), `fp_elim` (fp_eliminated), `tp_lost`, `fp_share`.
Sort is by `fp_eliminated` descending, so the top row is your prime suspect. The rule you want
to scope down has **high `fp_elim`, low `tp_lost`** (removes many false positives, loses little
recall) — see the module docstring `evaluation/rule_diagnostic.py:24-27`.

**Two historical over-fire patterns to recognise:**

- **`entity_monotony` on degenerate columns.** On CTU-13, the low-cardinality NetFlow columns
  `Proto` and `State` (cardinality ratio ~0.0002–0.002) were being baselined as *entities*, so
  `entity_monotony` flagged the honest NetFlow background. Fixed (`56f305d`) by requiring an
  entity column to sit inside the **actor cardinality-ratio band `[0.02, 0.5]`**
  (`ACTOR_MIN_RATIO`/`ACTOR_MAX_RATIO`, `features.py:64,71`; band applied in
  `_entity_columns`, `features.py:502-509`). Result: CTU-13 sc1 precision → **0.978**
  (`evaluation/BENCHMARKS.md:189`). If `entity_monotony` is your top FP source, dump
  `thresholds["entity_columns"]` and check whether a degenerate column snuck in.
- **Timing rules on a coarse clock.** When timestamps are quantised coarsely (minute
  resolution), sub-second timing rules can misread benign co-occurrence as automation. The
  guard is the timestamp-grid gate (§4): on a detected grid, on-grid rows are *suppressed*.

Next skill: `bwl-config-and-flags` (to find the right guardrail constant to tighten) and
`bwl-change-control` (to land it with the review pair).

---

## §3 — A rule never fires / is dormant  {#3}

Dormancy is usually **intended** — the entity and actor graphs are *gated off* when the
dataset does not support them, precisely so they do not invent false positives. Confirm intent
before "fixing".

**Command:** dump the thresholds dict (§0). Check, in order:

| Key | Dormant when | Meaning |
| --- | --- | --- |
| `entity_columns` | `[]` | no column passed entity selection → `entity_monotony` cannot fire |
| `entity_graph_active` | `False` | `< 2` entity columns / graph not built (`rules.py:248`) |
| `actor_columns` | `[]` | no column passed actor-endpoint selection |
| `actor_graph_active` | `False` | `< 2` actor columns (`rules.py:261`) → `asymmetric_degree` off |
| `degree_floor` | `None` | actor graph inactive, so no degree floor computed |
| `min_hub_degree` | `None` | entity graph inactive (`MIN_HUB_DEGREE = 3` when active) |

**Why a column fails entity/actor selection — the cardinality-ratio band `[0.02, 0.5]`.** A
column must have distinct values that *scale with the data* (it identifies *who*), not a
bounded vocabulary and not a per-row identifier. Verified selection gate (`_entity_columns`,
`features.py:502-511`): distinct `>= ENTITY_MIN_DISTINCT (10)`, distinct
`< ENTITY_UNIQUE_RATIO_MAX (0.95) * n_rows`, ratio inside `[ACTOR_MIN_RATIO 0.02,
ACTOR_MAX_RATIO 0.5]`, and median value-count `>= ENTITY_MEDIAN_RECURRENCE_MIN (2)`. Actor
endpoints add `ACTOR_MIN_DISTINCT (50)` and a recurring-values floor (`features.py:57-81`).

**Two recorded dormancy causes — one a correct verdict, one a role bug:**

- **Bournemouth web logs — dormant by data (correct).** `session_id` is a real recurring
  entity but its cardinality ratio falls **below the actor band**, so it reads as a bounded
  categorical and the actor rules never engage (`evaluation/FINDINGS.md:406-410`). Forcing it
  active caught **0 of 11** bot sessions and flagged monotone *humans* instead — so the band is
  *not* the lever here; this is a documented **method limit** (`FINDINGS.md:424-440`). Do not
  force it. If your log is web/HTTP, go to `bwl-webbot-campaign`, not a threshold tweak.
- **CTU-13 `entity_columns` empty — a role/recurrence issue.** The address columns did not
  populate `entity_columns` because of how their roles/recurrence resolved (`SrcAddr` typed as
  text; `DstAddr` failing the median-recurrence floor), which is why the *actor* graph — chosen
  by **schema column order**, source before destination (`rules.py:534,548-561`;
  `FINDINGS.md:356-357`) — carries CTU-13 rather than the entity graph. If addresses are absent
  from `entity_columns`, that alone is not a bug; check that the actor graph is active instead.

Next skill: `bwl-config-and-flags` (the band constants and how to reason about them),
`bwl-architecture-contract` (why the gates exist).

---

## §4 — `same_instant_burst` fires everywhere / coarse-clock false positives  {#4}

The timing rules assume you can distinguish sub-second machine cadence from human spacing. On a
**coarse clock** (timestamps quantised to whole seconds/minutes at source) many benign rows
collide at the same instant, and `same_instant_burst` would fire indiscriminately. The guard is
the **timestamp grid**.

**Command:** dump thresholds (§0), read `timestamp_grid` and `dense_timing_gated`.

- `timestamp_grid` is the detected coarse quantisation period in seconds (e.g. `1.0` for
  whole-second data, computed as the *mode* (most common) gap between distinct timestamps, so a
  handful of off-grid jitter timestamps cannot move the detected grid; `features.py:773+`,
  docstring `features.py:113-121`).
- `dense_timing_gated == True` means a grid of `>= burst_window` (`BURST_WINDOW_SECONDS = 10`)
  was detected and **on-grid rows are suppressed** from the dense-timing evidence
  (`rules.py:221-223,355`, gated by `grid >= burst_window_seconds` at `features.py:358`). If
  `same_instant_burst` is firing on a coarse log, first check `dense_timing_gated` is actually
  `True`. If it's `False`, either no grid was detected OR the detected grid is finer than the 10s
  burst window (e.g. `timestamp_grid=2.0` leaves it `False`) — the timestamps may parse as finer
  than they are (an off-grid jitter tail), or the timestamp column was mis-typed (go to §6).
- Off-grid, genuinely sub-second instants are still admitted (tolerance
  `GRID_ALIGNMENT_TOLERANCE_SECONDS = 1e-3`, `features.py:83-87`) — that is the real automation
  signal you want to keep.

This is the calibration shipped in `e6ded7a` ("Calibrate dense timing for coarse timestamp
grids"). Note: on the CICIDS Ares row, the clock is minute-quantised, so dense-timing rules are
**gated off** and recall is carried by the diversity/actor signals — that is expected
(`evaluation/BENCHMARKS.md:45`).

Next skill: `bwl-detection-theory` (grid/mode-gap maths), `bwl-failure-archaeology` (the
coarse-clock arc).

---

## §5 — Mechanically-regular bot missed in a popular context  {#5}

**Symptom:** `mechanical_timing` recall is ~1.0 on the synthetic suite (bots planted into
*unique* contexts) but near zero on generic injection where the bot's regular cadence is
planted into a **popular** categorical value that many legitimate rows also share.

**Root cause (`53251dc`):** inter-arrival regularity used to be measured over the *whole*
categorical context group. When a bot injects a regular cadence into a popular value, the
scattered legitimate rows inflate the group's inter-arrival variance and the regular
sub-sequence never stands out. The fix measures regularity **per burst-run** — a maximal
sub-sequence whose consecutive gaps stay within the burst window — so the cadence is isolated
from surrounding traffic. Same-instant piles (zero mean gap) are left to `same_instant_burst`
rather than scored as "perfectly regular" (which would invent false positives on coarse or
repeated timestamps). The context field was renamed `group_size` → `run_size` to reflect this
(`context.run_size`, used in `rules.py:384-386`; `REGULAR_TIMING_MIN_EVENTS` guards it).

**Discriminate:** run per-archetype recall (§1 step 2) on a *generic* (non-synthetic)
injection and confirm the loss is localised to `mechanical_timing`. If `run_size` is `None` in
the context, the timing path is not engaging at all — check the timestamp role (§6).

Next skill: `bwl-detection-theory` (regularity / coefficient-of-variation), `bwl-failure-archaeology`.

---

## §6 — A column was classified into the wrong role  {#6}

Every downstream rule keys off the inferred **role**. Get the role wrong and rules fire on the
wrong columns (or not at all). Roles are assigned per column by a fixed chain
(`ingest._role_for`, `_string_role`, `ingest.py:481-507`), evaluated **in this order** — first
match wins:

| Order | Role | Test | Threshold |
| --- | --- | --- | --- |
| 0 | TEXT | sample empty | — |
| 1 | BOOLEAN | `<= 2` unique values, all in true/false token sets | `_is_boolean`, `ingest.py:510` |
| 2 | URL | fraction matching URL regex `>= URL_RATE` | `URL_RATE = 0.70` (`ingest.py:48`) |
| 3 | TIMESTAMP | `>= 50%` values carry separators AND parse `>= PARSE_RATE` | `PARSE_RATE = 0.95` (`ingest.py:44`) |
| 4 | NUMERIC | parses to number `>= PARSE_RATE`; int vs float by whole-number test | `PARSE_RATE = 0.95` |
| 5 | IDENTIFIER | ratio `>= IDENTIFIER_RATIO_MIN` **and** token-like (`>= 0.90`) | precedes categorical |
| 6 | CATEGORICAL | `n_unique <= CATEGORICAL_ABS_MAX (50)` OR ratio `<= CATEGORICAL_RATIO_MAX (0.20)` | `ingest.py:52,56,505` |
| 7 | TEXT | fallthrough | — |

**How to debug:** dump roles + `cardinality_ratio` (§0 recipe 2), then walk the chain:

- **Timestamp read as text/numeric?** It failed the `>= 50%`-separators pre-check or fell below
  `PARSE_RATE 0.95` against `KNOWN_DATETIME_FORMATS` and the `format="mixed"` fallback
  (`ingest.py:526-538`). A minority of malformed rows can tip it below 0.95. Downstream: every
  timing rule and the grid gate (§4) go silent.
- **Identifier read as categorical?** The identifier check requires *both* a high ratio and
  token-like values (`_token_like >= 0.90`, `ingest.py:551-553`); miss either and the
  categorical branch claims it (any column with `<= 50` distinct values). Downstream: it can
  leak into `entity_columns`/`actor_columns` if it also lands in the `[0.02, 0.5]` band — the
  exact `Proto`/`State` failure mode of §2/§3.
- **Categorical read as text?** It exceeded both `CATEGORICAL_ABS_MAX (50)` distinct and
  `CATEGORICAL_RATIO_MAX (0.20)` ratio. Text columns are eligible for concentration rules at
  any cardinality (`rules.py:181`), so this changes which rules apply.

Do not "fix" by editing the raw log. If a real dataset needs a different threshold, that is a
guardrail change — go to `bwl-config-and-flags`, then `bwl-change-control`.

---

## §7 — `isotree` missing / ML scores look flat  {#7}

The ML path (Extended Isolation Forest) uses the optional `isotree` backend. **Command:** read
`result.ml_backend` (§0 recipe 3). Three values (`anomaly.py:57-74`):

| `ml_backend` | Meaning | What to do |
| --- | --- | --- |
| `"eif"` | isotree installed and scoring natively | normal |
| `"fallback"` | isotree NOT installed → dependency-free deviation score (min-max normalised, no natural scale) | install the extra: `uv run --extra eif ...`, or `uv sync --extra eif` |
| `"degenerate"` | too few rows/features to model → constant score vector | expected on tiny inputs; the ML path simply can't contribute |

If scores look "flat/all-equal", you are almost certainly on `"degenerate"` (a tiny fixture) or
`"fallback"` (no isotree). The benchmarks and `rule_diagnostic` are invoked with
`--extra eif` for a reason — the recorded numbers assume the `eif` backend. If you ran without
it, your ML-side numbers are not comparable to the registry. Next skill:
`bwl-build-run-operate` (environment/extras), `bwl-detection-theory` (isolation forest, knee
threshold).

---

## §8 — A benchmark test is skipped  {#8}

The real-data benchmarks depend on **gitignored, large, licence-restricted** datasets. The
tests `skipif` when the file is absent, so a clean checkout does not fail — but you also get no
coverage. **Command:** `uv run pytest tests/test_real_benchmark.py -q -rs` (the `-rs` prints
skip *reasons*). The guard: `tests/test_real_benchmark.py:24-25` skips on
`not Path(DEFAULT_ZIP).exists()`.

To make a skipped benchmark run, fetch its dataset to the expected path under `data/`:

| Benchmark | Expected path (`data/…`) | Fetch |
| --- | --- | --- |
| CICIDS2017 Ares | `data/GeneratedLabelledFlows.zip` | CIC / UNB academic terms, registration required (`cicids_bot_benchmark.py:39`) |
| CTU-13 sc1 (Neris) | `data/capture20110810.binetflow` | `curl -o data/capture20110810.binetflow https://mcfp.felk.cvut.cz/publicDatasets/CTU-Malware-Capture-Botnet-42/detailed-bidirectional-flow-labels/capture20110810.binetflow` |
| CTU-13 sc3 (Rbot) | `data/capture20110812.binetflow` | `curl -o data/capture20110812.binetflow https://mcfp.felk.cvut.cz/publicDatasets/CTU-Malware-Capture-Botnet-44/detailed-bidirectional-flow-labels/capture20110812.binetflow` (640 MB, opt-in local fetch) then `--scenario sc3` |
| Bournemouth web logs | `data/web_bot_detection_dataset.zip` | licence-pending; provisional numbers only (`bournemouth_benchmark.py:69`) |

Then run one benchmark directly, e.g.:
`uv run --extra eif python -m evaluation.ctu13_bot_benchmark` (add `--scenario sc3` for Rbot),
or the whole runner `uv run --extra eif python -m evaluation.run_benchmarks` (use `--only` to
select). A *skip* is not a pass — do not read "all tests pass" as "the real-data guards ran".
Next skill: `bwl-validation-and-qa` (tier discipline: what counts as evidence).

---

## Recorded benchmark numbers (cite, don't re-run the full suite)

These are the tracked golden numbers as of `evaluation/BENCHMARKS.md` at commit `6fd33ac`. Use
them to judge whether a change is a regression; do not treat synthetic numbers as field
accuracy.

| Dataset | Recall | Precision | Flag rate | Note |
| --- | --- | --- | --- | --- |
| CICIDS2017 / Ares | 0.998 | 0.846 | 0.037 | minute clock → dense-timing gated off |
| CTU-13 sc1 / Neris | 1.000 | 0.978 | 0.033 | microsecond clock; actor graph carries it |
| CTU-13 sc3 / Rbot | 0.985 | 0.929 | 0.034 | second-family generality probe |
| UNSW-NB15 (secondary breadth) | 0.122 | 0.198 | 0.020 | broad IDS, not a botnet capture |
| Bournemouth web logs | 0.474 | 0.020 | 0.681 | **provisional, licence-pending**; documented method limit |

---

## Provenance and maintenance

Authored 2026-07-06, repo at commit `6fd33ac` (verified `git rev-parse HEAD`). British English.
All commands and constants below were run/read against that commit. Re-verify volatile facts:

| Fact | One-line re-verification |
| --- | --- |
| Decision cutoffs `HEURISTIC_CUTOFF 0.70`, `MAX_ML_FLAG_RATE 0.02` | `grep -n "HEURISTIC_CUTOFF\|MAX_ML_FLAG_RATE" bots_without_labels/pipeline.py` |
| Thresholds dict keys (dormancy signals) | run §0 recipe 1 on any log and read the keys |
| Actor/entity band `[0.02, 0.5]` and entity gate constants | `grep -n "ACTOR_MIN_RATIO\|ACTOR_MAX_RATIO\|ENTITY_MIN_DISTINCT\|ENTITY_MEDIAN_RECURRENCE_MIN" bots_without_labels/features.py` |
| Role-chain thresholds `PARSE_RATE 0.95`, `URL_RATE 0.70`, `CATEGORICAL_ABS_MAX 50`, `CATEGORICAL_RATIO_MAX 0.20` | `grep -n "PARSE_RATE\|URL_RATE\|CATEGORICAL_ABS_MAX\|CATEGORICAL_RATIO_MAX" bots_without_labels/ingest.py` |
| Role classification order | `sed -n '481,507p' bots_without_labels/ingest.py` |
| Archetype names and detectable subset | `uv run python -c "from bots_without_labels.synthetic import ARCHETYPES, DETECTABLE_ARCHETYPES; print(ARCHETYPES, DETECTABLE_ARCHETYPES)"` |
| ML backend values `eif`/`fallback`/`degenerate` | `sed -n '55,74p' bots_without_labels/anomaly.py` |
| Recorded benchmark numbers | read the results table in `evaluation/BENCHMARKS.md` (rows for CICIDS/CTU-13/UNSW/Bournemouth) |
| Real-benchmark skip guard + dataset paths | `grep -n "skipif\|DEFAULT_ZIP\|DEFAULT_BINETFLOW\|DEFAULT" tests/test_real_benchmark.py evaluation/*benchmark.py` |
| `98646c1` / `56f305d` / `e6ded7a` / `53251dc` fix commits still describe these arcs | `git show --stat <hash>` |

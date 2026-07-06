---
name: bwl-config-and-flags
description: >
  Load when you need the value, meaning, or tier of any tuning knob in Bots Without Labels — a rule
  weight, threshold, floor, percentile, cardinality band, EIF parameter, CLI flag, or benchmark
  argument. Triggers: "what does W_ENTITY_MONOTONY / SUPPORTING_CAP / HEURISTIC_CUTOFF / ACTOR_MIN_RATIO
  / DEGREE_ASYMMETRY do", "how do I change a threshold safely", "what's the default n_bots / seed /
  max_ml_flag_rate", "which constants are safe to touch", "add a new config knob", "where is 0.70 set",
  "why is precision moving after I changed a weight". Read this before editing any constant, kwarg, or
  argparse flag, and before hand-tuning anything to a single capture.
---

# Bots Without Labels — configuration & flags catalogue

This is the map of **every tuning axis** in the codebase: module constants, function keyword arguments,
CLI subcommand flags, and benchmark script arguments. Each entry gives the **value**, what it **means**,
and its **tier** (how dangerous it is to change). Use it to find a knob, understand what it controls, and
classify a proposed change before you make it.

Jargon note: a *flow* is one summarised network connection (see `netflow-botnet-reference`); the
*heuristic/rule score* is the explainable half, the *ml/anomaly score* is the Extended Isolation Forest
half (see `bwl-detection-theory`). "Actor/entity" = a column the detector treats as identifying *who*
communicates (an address, a session id).

## When NOT to use this skill

| Your question is really about… | Go to |
| --- | --- |
| The **maths** behind a knob (why MAD, what Kneedle does, entropy) | `bwl-detection-theory` |
| **Whether** a change is allowed / who commits / review pairs | `bwl-change-control` |
| **Measuring** the effect of a change (diagnostics, benchmark runner) | `bwl-diagnostics-and-tooling` |
| **Adding a test or benchmark** to lock a number | `bwl-validation-and-qa` |
| A number **regressed** and you need the history of why | `bwl-failure-archaeology` |
| A knob exists because of a **design invariant** you might break | `bwl-architecture-contract` |
| Security terms (flow, C2, Neris, CTU-13) you don't recognise | `netflow-botnet-reference` |

This skill tells you *what each knob is and its blast radius*. It does not re-derive the theory, does not
authorise the change, and does not run the measurement — those are the siblings above.

## Tier legend (the blast-radius column in every table)

| Tier | Meaning | Rule for touching it |
| --- | --- | --- |
| **load-bearing calibrated** | Its value was tuned against measured captures; a rule's behaviour or a recorded benchmark number depends on it. | Never touch alone. Change paired constants together, re-run affected benchmarks, route through `bwl-change-control`. |
| **structural guard** | A floor/minimum/cap that keeps a rule *dormant* in the wrong regime (too few events, low cardinality, coarse clock). Not fitted to a dataset. | Changing it widens/narrows where a rule can fire at all. Full test run + a benchmark diff still required. |
| **guardrail — limited evidence** | Holds only across the narrow band actually tested; generality is explicitly unproven and tracked as a follow-up. | Treat as fragile. Do not present as a general constant. See the callout under Table 1. |
| **cosmetic** | Affects output size / reporting only, never a decision. | Safe to change; still run tests. |

**The cardinal rule (read before any edit): never hand-tune a threshold to make one capture look good.**
Every calibrated constant here was set against a *distribution* (a percentile of the batch, a synthetic
stress test, or ≥1 externally-labelled capture with a no-regression guard on the others). Fitting a
number to a single log is how you get a detector that scores ~1.0 on its fixture and fails on real data.

---

## Table 1 — Module constants

### `bots_without_labels/rules.py` — the explainable rule detector

The rule score is a weighted sum of *hits*. Timing hits are `strong` (full weight); repetition /
concentration / entropy hits are `supporting` (their combined weight is capped at `SUPPORTING_CAP`). The
whole weight system is calibrated so **no single strong rule reaches `HEURISTIC_CUTOFF` (0.70) alone** —
except the two hub rules, which are deliberately allowed to.

| Constant | Value | Meaning | Tier |
| --- | --- | --- | --- |
| `SUPPORTING_CAP` | `0.24` | Ceiling on the summed weight of all *supporting* hits on a row. Keeps "popular value repeats" from ever adding up to a flag. | load-bearing calibrated |
| `W_SAME_INSTANT_BURST` | `0.40` | Weight: many events at the exact same timestamp. Strong. | load-bearing calibrated |
| `W_LOCAL_BURST` | `0.35` | Weight: dense pile-up within the burst window in one context. Strong. | load-bearing calibrated |
| `W_REGULAR_TIMING` | `0.40` | Weight: mechanically regular inter-arrival cadence. Strong. | load-bearing calibrated |
| `W_TEXT_REPEAT` | `0.12` | Weight: a text value repeats. Supporting. | load-bearing calibrated |
| `W_NUMERIC_REUSE` | `0.12` | Weight: an exact numeric value recurs. Supporting. | load-bearing calibrated |
| `W_CATEGORICAL_CONCENTRATION` | `0.08` | Weight: a high-volume categorical value. Supporting. | load-bearing calibrated |
| `W_CONTEXT_CLUSTER` | `0.10` | Weight: heavy joint-categorical cluster. Supporting. | load-bearing calibrated |
| `W_LOW_ENTROPY` | `0.06` | Weight: low-entropy text string. Supporting. | load-bearing calibrated |
| `W_ENTITY_MONOTONY` | `0.70` | Weight: a high-volume, low-diversity *hub* entity (a beacon/scraper). Strong, and **= cutoff on purpose** — this rule can flag alone. | load-bearing calibrated |
| `ENTITY_MIN_EVENTS` | `12` | An entity needs this many events before its diversity is trusted (can't baseline a stranger). | structural guard |
| `ENTITY_DIVERSITY_CEILING` | `0.20` | Absolute cap on the adaptive diversity cut: only an entity doing essentially *one* thing qualifies. Also keeps the rule dormant on low-dimensional logs. | load-bearing calibrated |
| `ENTITY_DIVERSITY_PERCENTILE` | `0.10` | The adaptive cut is the 10th-percentile diversity among high-volume entities (min'd with the ceiling). | load-bearing calibrated |
| `MIN_HUB_DEGREE` | `3` | A "hub/star" must reach at least this many distinct counterparts. Deliberately a tiny structural minimum, **not** tuned to any botnet's fan-out. | structural guard |
| `W_ASYMMETRIC_DEGREE` | `0.70` | Weight: an asymmetric high-out-degree *source* endpoint (fan-out broadcaster: spam/scan/click-fraud). Strong, flags alone. | load-bearing calibrated |
| `DEGREE_FLOOR_PERCENTILE` | `0.99` | Degree floor = 99th-percentile degree among endpoints already ≥ `MIN_HUB_DEGREE` (batch-relative, not a fixed count). | **guardrail — limited evidence** |
| `DEGREE_ASYMMETRY` | `10` | Out-degree must exceed in-degree by this factor (`degree ≥ 10·(reverse+1)`) to count as one-sided. | **guardrail — limited evidence** |
| `COUNT_PERCENTILE` | `0.99` | Adaptive count rules fire above the 99th percentile of *distinct group sizes* (robust to bot fraction). | load-bearing calibrated |
| `TEXT_REPEAT_FLOOR` | `10` | Lower bound for the adaptive text-repeat threshold. | structural guard |
| `NUMERIC_REUSE_FLOOR` | `10` | Lower bound for numeric-reuse. | structural guard |
| `CONCENTRATION_FLOOR` | `50` | Lower bound for categorical-concentration and context-cluster. | structural guard |
| `SAME_INSTANT_FLOOR` | `4` | Minimum same-timestamp collisions before the rule can fire. | structural guard |
| `LOCAL_BURST_FLOOR` | `5` | Minimum events in the burst window (fixed, not adaptive). | structural guard |
| `MIN_CARDINALITY_FOR_CONCENTRATION` | `20` | A column needs this many distinct values before concentration/reuse is meaningful. | structural guard |
| `REGULAR_TIMING_MIN_EVENTS` | `8` | A burst-run needs this many events before its cadence regularity is trusted. | structural guard |
| `REGULAR_TIMING_MAX_CV` | `0.50` | Inter-arrival coefficient-of-variation at or below this = "mechanically regular". | load-bearing calibrated |
| `LOW_ENTROPY_MAX` | `1.5` | Shannon-entropy (bits) at or below this = low-entropy string. | structural guard |
| `LOW_ENTROPY_MIN_LENGTH` | `5` | String must be at least this long for the entropy rule to apply. | structural guard |

> **Limited-evidence callout — `DEGREE_FLOOR_PERCENTILE` and `DEGREE_ASYMMETRY`.** These two are GUARDRAILS
> calibrated against limited evidence, **not** established general constants. On the one labelled split
> tested (CTU-13 / Neris) plus a synthetic broadcaster, the result is unchanged for asymmetry factors
> ~10–100, **over-fires below ~10, and the rule vanishes at ≥200** (it exceeds Neris's own ratio). This is
> **not scale-free.** Generality to other families is a tracked follow-up. Do not quote these as universal.

### `bots_without_labels/features.py` — feature engineering & actor/entity detection

| Constant | Value | Meaning | Tier |
| --- | --- | --- | --- |
| `BURST_WINDOW_SECONDS` | `10` | Sliding window for the burst-concentration feature and burst-run segmentation; also names the feature (`burst10s__conc`). | load-bearing calibrated |
| `SPARSE_TIMING_SENTINEL` | `999.0` | Inter-arrival std/cv value for groups too small to score, so sparse groups never look "regular". | structural guard |
| `ENTITY_MIN_DISTINCT` | `10` | A categorical needs ≥ this many distinct values to be an *entity* column (baselined actor). | structural guard |
| `ENTITY_UNIQUE_RATIO_MAX` | `0.95` | An entity column with distinct/rows ≥ this is a per-row identifier and is excluded. | structural guard |
| `ENTITY_MEDIAN_RECURRENCE_MIN` | `2` | The median entity value must recur at least this often, else "actors" are one-offs. | structural guard |
| `ENTITY_DIVERSITY_BINS` | `8` | Quantile bins applied to numeric columns before per-entity/per-actor entropy. | structural guard |
| `ACTOR_MIN_DISTINCT` | `50` | An actor *endpoint* (relational graph node) needs more than this many distinct values (above the loader's bounded-set cutoff). | structural guard |
| `ACTOR_MIN_RATIO` | `0.02` | **Lower** cardinality-ratio band for an actor endpoint. Below it = a bounded vocabulary (protocol/TCP-state) = context, not an actor. | load-bearing calibrated |
| `ACTOR_MAX_RATIO` | `0.5` | **Upper** cardinality-ratio band. Above it = a near-unique edge/flow id, not a recurring endpoint. | load-bearing calibrated |
| `ACTOR_MIN_RECURRING` | `2` | Needs ≥ this many values that recur (≥ `ACTOR_MIN_EVENTS`) so real hubs exist. | structural guard |
| `ACTOR_MIN_EVENTS` | `12` | Events a value needs to count as a recurring actor / qualify for the asymmetric rule (mirrors `ENTITY_MIN_EVENTS`). | structural guard |
| `GRID_ALIGNMENT_TOLERANCE_SECONDS` | `1e-3` | How close to a grid multiple a timestamp must fall to count as *on-grid* (absorbs float round-trip). | structural guard |
| `_MISSING`, `_FIELD_SEPARATOR` | `"\x00NA"`, `"\x1f"` | Internal sentinels that cannot occur in log text (missing cell; multi-column key join). | cosmetic |

> The `ACTOR_MIN_RATIO`/`ACTOR_MAX_RATIO` band is the fix for the CTU-13 over-flagging root cause:
> degenerate low-cardinality `Proto`/`State` columns (ratio ~0.0002–0.002) were being baselined as
> entities. Real address columns (ratio ~0.04–0.06) sit inside the band. See `bwl-failure-archaeology`.

### `bots_without_labels/ingest.py` — loader & schema inference

| Constant | Value | Meaning | Tier |
| --- | --- | --- | --- |
| `SAMPLE_SIZE` | `1000` | Rows sampled from the top when classifying a column's role. | structural guard |
| `MAX_SAMPLE_BYTES` | `65_536` | Bytes read from the head for format/dialect detection. | structural guard |
| `PARSE_RATE` | `0.95` | Fraction of sampled values that must parse as a type for the column to get it. | structural guard |
| `URL_RATE` | `0.70` | Fraction that must look like a URL for the column to be URL-expanded. | structural guard |
| `CATEGORICAL_ABS_MAX` | `50` | ≤ this many distinct values ⇒ categorical regardless of row count. | structural guard |
| `CATEGORICAL_RATIO_MAX` | `0.20` | distinct/non-missing ≤ this ⇒ categorical (larger bounded sets). | structural guard |
| `IDENTIFIER_RATIO_MIN` | `0.95` | Near-unique, token-like column ≥ this ratio ⇒ identifier. | structural guard |

### `bots_without_labels/pipeline.py` — the decision

| Constant | Value | Meaning | Tier |
| --- | --- | --- | --- |
| `HEURISTIC_CUTOFF` | `0.70` | Rule-score decision cutoff. **The paired partner of every rule weight** — no single non-hub rule reaches it; the two hub rules equal it. | load-bearing calibrated |
| `MAX_ML_FLAG_RATE` | `0.02` | Cap on the share of rows the anomaly model may flag *on its own* (rate-cap on the knee threshold), so a loose elbow can't flood output. | load-bearing calibrated |
| `MAX_SELECTED_EVENTS` | `500` | Cap on rows written to `selected_events.json` (a triage sample; full set is in `predictions.tsv`). | cosmetic |
| `CANONICAL_RUN_OUTPUT_DIR` | `Path("run-output")` | Default artefact directory constant (the CLI passes `.`). | cosmetic |

> **The 0.70 pairing is the single most important coupling in the codebase.** `HEURISTIC_CUTOFF` and the
> `rules.py` weights are one calibrated system. Change a weight without re-checking the cutoff (or vice
> versa) and you silently change which corroboration counts as a flag.

### `bots_without_labels/anomaly.py` — Extended Isolation Forest scorer

| Constant | Value | Meaning | Tier |
| --- | --- | --- | --- |
| `EIF_TREES` | `100` | Forest size (isolation-forest literature default). | structural guard |
| `EIF_EXTENSION_DIMS` | `2` | Extension level: hyperplanes combine up to 2 features (pairwise interactions). | structural guard |
| `EIF_SAMPLE_SIZE` | `4096` | Per-tree subsample (deliberately does not grow with the log). | structural guard |
| `DEGENERATE_ANOMALY_SCORE` | `0.5` | Uninformative midpoint returned when there is nothing to rank (< 3 rows, 0 features, constant scores). | structural guard |
| `TOP_DEVIATION_FEATURES` | `5` | Feature deviations reported per explained row. | cosmetic |
| `_MAD_TO_STD` | `1.4826` | Makes MAD a consistent estimator of the std for normal data (a statistical constant, not a tunable). | structural guard |

### `bots_without_labels/threshold.py` — self-tuning knee threshold

| Constant | Value | Meaning | Tier |
| --- | --- | --- | --- |
| `SMALL_INPUT_SIZE` | `10` | Below this many finite scores there is no curve; return max score (flag nothing). | structural guard |
| `TIED_SCORE_MIN_DISTINCT` | `3` | Fewer distinct score values than this ⇒ step function, Kneedle meaningless; return max score. | structural guard |

---

## Table 2 — Function keyword arguments (per-call overrides)

Every kwarg **defaults to the module constant above**, so a plain call reproduces production behaviour;
overrides are for ablation/tuning studies and tests only.

| Function (module) | Kwarg = default | Overrides | Notes |
| --- | --- | --- | --- |
| `detect` (`pipeline.py`) | `max_ml_flag_rate=MAX_ML_FLAG_RATE` (0.02) | ML self-flag rate cap | — |
| `detect` | `heuristic_cutoff=HEURISTIC_CUTOFF` (0.70) | Rule-score cutoff | **Override for studies only** — the default is calibrated to the weights. |
| `build_features` (`features.py`) | `burst_window_seconds=BURST_WINDOW_SECONDS` (10) | Burst window; also part of the feature name | — |
| `build_features` | `entity_diversity_bins=ENTITY_DIVERSITY_BINS` (8) | Numeric quantile bins before per-entity entropy | — |
| `generate` (`synthetic.py`) | `n_legit=900`, `n_bots=100`, `seed=0`, `signatures=None` | Synthetic click-log size, seed, per-archetype signature overrides | Bots split across `ARCHETYPES`. |
| `inject_bots` (`inject.py`) | `n_bots=100`, `seed=0`, `archetypes=ARCHETYPES` | Bots injected into an existing loaded log | — |
| `run_pipeline` (`pipeline.py`) | `output_dir=CANONICAL_RUN_OUTPUT_DIR`, `display_input_path=None`, `max_output_events=MAX_SELECTED_EVENTS` (500) | Artefact dir; path label in summary; selected-events cap | CLI passes `output_dir="."`. |
| `score_matrix` (`anomaly.py`) | `seed=7` | EIF model seed | Fixed for bit-reproducibility. |
| `feature_deviations` (`anomaly.py`) | `top_k=TOP_DEVIATION_FEATURES` (5) | Deviations per explained row | — |

`ARCHETYPES` (identical in `synthetic.py` and `inject.py`) = `('burst', 'mechanical_timing',
'diffuse_replay', 'stealth')`. The two timing archetypes are the ones the rules are designed to catch;
`stealth` is a deliberately hard near-legit control (see `bwl-validation-and-qa`).

---

## Table 3 — CLI arguments (`bots-without-labels <command>`)

Entry point `bots_without_labels.cli:main`. Three subcommands.

| Command | Flag | Default | Meaning |
| --- | --- | --- | --- |
| `run` | `--input` (required) | — | Path to a CSV/TSV/JSON log to score. |
| `run` | `--output-dir` | `.` | Directory for `predictions.tsv` + `artifacts/`. |
| `generate` | `--output` (required) | — | Path to write the synthetic TSV log. |
| `generate` | `--legit` | `900` | Legitimate events (→ `n_legit`). |
| `generate` | `--bots` | `100` | Bot events (→ `n_bots`). |
| `generate` | `--seed` | `0` | Deterministic seed. |
| `doctor` | `--input` | none | Optional input path to validate. |
| `doctor` | `--output-dir` | `.` | Directory to test for writability. |

`doctor` checks Python ≥ 3.11, `numpy`/`pandas`/`scipy` importable, package importable, `isotree`
(optional — absence is **not** a failure; the fallback scorer is used), and output-dir writability.
See `bwl-build-run-operate` for the full CLI anatomy and artefact conventions.

---

## Table 4 — Benchmark script arguments

Real-data benchmarks live in `evaluation/` and share mix-sizing arguments via
`evaluation.harness.add_mix_size_arguments`. **`DEFAULT_SEED = 7` is fixed for every benchmark** (not
varied per run) so measured numbers are reproducible and comparable. Do **not** cite synthetic numbers as
field accuracy; only externally-labelled captures earn a tracked row (see `bwl-validation-and-qa`).

| Script (`python -m evaluation.…`) | Data-path flag | Mix-size flags (default) | Seed |
| --- | --- | --- | --- |
| `cicids_bot_benchmark` | `--zip` (`data/GeneratedLabelledFlows.zip`) | `--benign` (60_000); keeps all bot rows | `--seed 7` |
| `ctu13_bot_benchmark` | `--scenario` (e.g. `sc3`) / `--binetflow` (explicit path, overrides scenario) | `--bot` (2_000), `--benign` (60_000) | `--seed 7` |
| `unsw_benchmark` | (module-specific data path) | `--attack` (2_000), `--benign` (60_000) | `--seed 7` |
| `bournemouth_benchmark` | `--zip` | `--bot` (1_800); keeps all benign rows | `--seed 7` |
| `run_benchmarks` (whole suite) | — | `--only key1,key2` (default: all present) | fixed |

Recorded numbers (from `evaluation/BENCHMARKS.md`, this repo — **not** production guarantees):

| Capture | Recall | Precision | Flag rate |
| --- | --- | --- | --- |
| CICIDS2017 / Ares (minute-quantised ⇒ dense-timing gated off) | 0.998 | 0.846 | 0.037 |
| CTU-13 sc1 / Neris (µs clock) | 1.000 | 0.978 | 0.033 |
| CTU-13 sc3 / Rbot (generality probe) | 0.985 | 0.929 | 0.034 |
| UNSW-NB15 shard 1/4 (secondary; not a bot capture) | 0.122 | 0.198 | 0.020 |
| Bournemouth web logs (**provisional, licence-pending; negative** — precision below base rate) | 0.474 | 0.020 | 0.681 |

---

## How to add or change a knob — checklist

Follow in order. Do not skip the pairing or the diff step.

1. **Classify the tier** (Table 1 legend). Cosmetic → light touch. Anything else → the full loop below.
2. **Find the paired constant.** Weights ↔ `HEURISTIC_CUTOFF`; a supporting weight ↔ `SUPPORTING_CAP`;
   `DEGREE_FLOOR_PERCENTILE` ↔ `DEGREE_ASYMMETRY`; `ACTOR_MIN_RATIO` ↔ `ACTOR_MAX_RATIO`. **Change the
   pair together** — an isolated weight change silently redefines what counts as a flag.
3. **If you are adding a knob:** add the module constant *and* a default-preserving kwarg so existing
   callers are byte-identical, and document its tier in this table. Never introduce a magic literal in
   the middle of a function.
4. **Run the full test suite** (see re-verify commands below). All must pass; the suite pins several
   golden numbers and rule behaviours.
5. **Re-run the affected benchmarks and diff against `evaluation/BENCHMARKS.md`.**
   - For a **pure refactor** (no intended behaviour change), the numbers must be **bit-identical**. Any
     drift is a finding — stop and investigate, don't update the number.
   - For an **intended** calibration change, record the before/after and the reason.
6. **Route through `bwl-change-control`** — cross-model review (Codex reviews Claude), Definition of
   Ready/Done, evidence-not-claims. The product manager is the only committer.
7. **Update the docs of record** — `evaluation/BENCHMARKS.md` (registry), `evaluation/FINDINGS.md`
   (narrative), and this table.

**Never** set a constant so that one specific capture's precision/recall jumps while you're staring at
that capture. Calibrate against a *distribution* (a batch percentile), a synthetic stress test, and at
least one held-out labelled capture with a no-regression guard on the others.

---

## Provenance and maintenance

Authored 2026-07-06. Repo at commit `6fd33ac` ("Refresh roadmap: fold shipped arcs into a Shipped
section"). All constant values were verified by import (`uv run python -c "import …"`) and by reading
source, not from memory. The author brief referenced commit `6fd33ac`; note the brief's frontmatter date
stamp (2026-07-04) predates this authoring session — trust the re-verify commands over any date.

| Volatile fact | One-line re-verify command |
| --- | --- |
| `rules.py` weights / floors / bands | `uv run python -c "import bots_without_labels.rules as r; print(r.W_ENTITY_MONOTONY, r.W_ASYMMETRIC_DEGREE, r.SUPPORTING_CAP, r.DEGREE_ASYMMETRY, r.DEGREE_FLOOR_PERCENTILE)"` |
| `features.py` actor/entity constants | `uv run python -c "import bots_without_labels.features as f; print(f.BURST_WINDOW_SECONDS, f.ACTOR_MIN_RATIO, f.ACTOR_MAX_RATIO, f.ACTOR_MIN_EVENTS)"` |
| `ingest.py` inference constants | `uv run python -c "import bots_without_labels.ingest as i; print(i.PARSE_RATE, i.URL_RATE, i.CATEGORICAL_ABS_MAX, i.CATEGORICAL_RATIO_MAX, i.IDENTIFIER_RATIO_MIN, i.SAMPLE_SIZE)"` |
| `pipeline.py` decision constants | `uv run python -c "import bots_without_labels.pipeline as p; print(p.HEURISTIC_CUTOFF, p.MAX_ML_FLAG_RATE, p.MAX_SELECTED_EVENTS)"` |
| `anomaly.py` / `threshold.py` | `uv run python -c "import bots_without_labels.anomaly as a, bots_without_labels.threshold as t; print(a.EIF_TREES, a.EIF_EXTENSION_DIMS, a.EIF_SAMPLE_SIZE, t.SMALL_INPUT_SIZE, t.TIED_SCORE_MIN_DISTINCT)"` |
| CLI flags & defaults | `uv run bots-without-labels generate --help && uv run bots-without-labels run --help` |
| Benchmark seed / mix-size args | `grep -n "DEFAULT_SEED\|N_BENIGN\|N_BOT\|N_ATTACK" evaluation/harness.py evaluation/*_benchmark.py` |
| Archetype tuples | `uv run python -c "import bots_without_labels.synthetic as s, bots_without_labels.inject as j; print(s.ARCHETYPES, j.ARCHETYPES)"` |
| Recorded benchmark numbers | `grep -nE "0\.998\|0\.978\|0\.929\|Bournemouth" evaluation/BENCHMARKS.md` |
| Test suite still green | `uv run pytest -q` |

---
name: bwl-detection-theory
description: >
  Load when you need to understand or explain the DETECTOR'S MATHS in Bots Without Labels:
  normalised Shannon entropy, median/MAD robust z-scores (why not mean/std, the 1.4826 constant),
  the Extended Isolation Forest and its dependency-free fallback, Kneedle knee-detection and its
  fallback ladder, adaptive count/degree thresholds (99th percentile over distinct-group sizes),
  the supporting-evidence cap arithmetic (why 0.40 + support = 0.64 < 0.70), timestamp-grid
  estimation, percentile ranks and quantile binning. Triggers on questions like "why does the score
  not change / why is this a probability", "what does robust_z mean", "why isn't a repeated value
  flagged", "what is method='max_distance_descending_fallback'", "how is the ML threshold chosen",
  "what does normalised entropy 0 vs 1 mean", or when reading anomaly.py / threshold.py / features.py
  / rules.py and needing the theory behind a function.
---

# BWL detection theory: the maths, tied to the code

This is the **why and the formula** behind every number the detector computes, each pinned to the
exact function that implements it. It does not tell you how to run the pipeline (that is
`bwl-build-run-operate`) or how to tune the constants (that is `bwl-config-and-flags`). Read it when a
line of `anomaly.py`, `threshold.py`, `features.py` or `rules.py` needs justifying, or when you must
explain to a reviewer why a score behaves as it does.

**Jargon note.** *Flow / NetFlow / botnet / C2* are security-domain terms — see
`netflow-botnet-reference`. Everything else is defined at first use below. One term you need
immediately: a **row** is one log record (one network flow, one HTTP request); the detector scores
each row 0–1 for "how bot-like".

## When NOT to use this skill

| If you need… | Go to |
|---|---|
| To run the pipeline, CLI anatomy, artifact/data layout | `bwl-build-run-operate` |
| To change a constant / add a flag / production-vs-guardrail split | `bwl-config-and-flags` |
| The security domain (what a botnet/C2/NetFlow actually is) | `netflow-botnet-reference` |
| Load-bearing design decisions & invariants (not the maths) | `bwl-architecture-contract` |
| To MEASURE the detector (diagnostics, feature-deviation dumps) | `bwl-diagnostics-and-tooling` |
| A symptom→fix table for a live failure | `bwl-debugging-playbook` |
| Worked first-principles analysis recipes | `bwl-proof-and-analysis-toolkit` |

## The two-headed decision (context for everything below)

The detector is **unsupervised**: no labels, so it cannot pick a threshold by optimising accuracy. It
runs two independent scorers over the same feature matrix and OR-s them
(`bots_without_labels/pipeline.py`, `_run` around line 143):

```
is_bot = heuristic_score >= 0.70            # explainable rules (rules.py)
         OR ml_score > dynamic_knee_threshold   # Extended Isolation Forest (anomaly.py, threshold.py)
```

Constants: `HEURISTIC_CUTOFF = 0.70`, `MAX_ML_FLAG_RATE = 0.02` (pipeline.py:36,41). The ML side is
additionally **rate-capped**: if the knee would flag more than 2% of rows, the threshold is raised to
the 98th-percentile score instead (pipeline.py:150-152, method string gains `+rate_capped`).

Everything in this skill is the maths inside one of those two heads, plus the shared standardisation
and the explanation layer.

---

## 1. Normalised Shannon entropy — "how diverse is this actor's behaviour?"

**Idea.** Entropy measures how spread-out a set of values is. All-identical → 0 (a bot replaying one
request shape). All-distinct-and-balanced → 1 (a human browsing variedly). We normalise so the number
is comparable across actors with different event counts.

**Formula.** `_norm_entropy` in `bots_without_labels/features.py:761`:

```
H = -Σ p_i · ln(p_i)          # p_i = count of value i / total
return H / ln(total)          # divide by ln(n) → range [0, 1]
```

**Why `/ ln(total)`.** Raw Shannon entropy grows with the number of distinct values, so a busy actor
looks "more diverse" purely for being busy. `ln(n)` is the entropy of the *maximally* diverse set of
that size (n equally-likely values), so `H / ln(n)` asks "how close to maximally diverse is this,
*for its size*" — a size-independent [0,1] diversity. `total <= 1` returns 0.0 (a single event has no
diversity to measure).

**Verified example** (`uv run python -c`):

| Input | Normalised entropy | Reading |
|---|---|---|
| `['a','a','a','a']` | `0.0` | one behaviour repeated — bot-like |
| `['a','a','b','b']` | `0.5` | two behaviours, balanced |
| `['a','b','c','d']` | `1.0` | maximally diverse — human-like |

**Where it feeds.** Per-context entropy over categorical columns; numeric columns are quantile-binned
first (§8). Low entropy is a *supporting* rule (`W_LOW_ENTROPY = 0.06`, rules.py:46) with
`LOW_ENTROPY_MAX` on the raw entropy scale — deliberately weak, because popular legitimate content is
also low-entropy.

---

## 2. Median / MAD robust z-score — the shared standardisation

**Idea.** Before either scorer sees the feature matrix, each column is put on a common scale so a
"big" value in one feature is comparable to a "big" value in another. The classic way is the z-score
`(x − mean) / std`. This project uses **median / MAD** instead.

**Formula.** `_robust_standardize` in `bots_without_labels/anomaly.py:138`:

```
median = median(column)
MAD    = median(|column − median|)      # Median Absolute Deviation
scale  = 1.4826 · MAD
robust_z = (column − median) / scale
```

Fallback ladder for `scale`: if `1.4826·MAD == 0` (constant/near-constant column) use the plain std;
if that is also 0 use `1.0`; then `nan_to_num` scrubs any NaN/inf to 0 so the forest
(`missing_action="fail"`) never sees a bad value (anomaly.py:148-153).

**Why the `1.4826` constant** (`_MAD_TO_STD`, anomaly.py:46). For normally-distributed data,
`1.4826 · MAD` equals the standard deviation. Multiplying by it makes MAD a *consistent estimator of
σ*, so a robust z-score reads on the same "number of standard deviations" scale everyone expects —
but computed from the median, which the tail cannot move.

**Why not mean/std** (the load-bearing reason, documented in the anomaly.py module docstring).
Real log features (log-counts, concentration ratios) are **heavy-tailed**: a few automated
mega-clusters. The mean and std are dragged toward that tail, so the very anomalies you want to catch
*inflate the scale that is supposed to make them stand out* — they **mask** themselves. The median and
MAD are computed from the middle of the distribution and barely move, so anomalies keep a large
robust-z.

**Verified example.** Column `[10, 11, 12, 13, 100]`: median = 12, MAD = 1, scale = 1.4826.

| Value | robust_z |
|---|---|
| 10 | −1.349 |
| 12 | 0.000 |
| 100 | **59.355** |

The outlier scores ~59 MAD-units out. With mean/std the same 100 would sit at only ~1.6 σ (the std is
~35, inflated by the 100 itself) — masked. That contrast is the whole argument.

---

## 3. Extended Isolation Forest — the multivariate ML head

**Idea (twenty questions).** An isolation forest builds many random binary trees. At each node it
picks a random split; a point that gets *isolated* (alone in a leaf) after only a few questions is
anomalous, because random cuts separate outliers quickly and dense normal points slowly. The
anomaly score is derived from the **average path length** to isolate a row across the forest.
The **Extended** variant (Hariri et al. 2019) splits on random *oblique* hyperplanes combining
several features instead of one axis at a time, removing the axis-aligned artefacts of the original.

**Config** (`_extended_isolation_forest`, anomaly.py:156, backed by module constants):

| Setting | Value | Constant / line | Why |
|---|---|---|---|
| trees | 100 | `EIF_TREES` (28) | literature default; scores stabilise well before this |
| extension dims | 2 | `EIF_EXTENSION_DIMS` (30) | hyperplanes combine ≤2 features — catches pairwise interactions (same-context *and* same-instant) without fully-oblique noise |
| subsample | 4096 | `EIF_SAMPLE_SIZE` (34) | `min(4096, n_rows)`; forests deliberately subsample — small trees isolate faster and mask less; does **not** grow with the log |
| `nthreads` | 1 | anomaly.py:172 | single-threaded ⇒ bit-reproducible scores across runs and hosts |
| `standardize_data` | False | anomaly.py:169 | we already did median/MAD (§2); don't let isotree re-standardise with mean/std |
| `missing_action` | `"fail"` | anomaly.py:168 | fail loudly on a stray NaN rather than silently impute |

Backend is optional: the `uv`/`pip` extra `eif` installs `isotree`. If absent,
`_extended_isolation_forest` returns `None` and the fallback (§4) runs.

**Use the native score as-is — do NOT re-min-max.** `isotree.decision_function` already returns a
bounded, sample-size-normalised anomaly score in `[0, 1]`; `score_matrix` only `np.clip`s it
(anomaly.py:73). Re-min-maxing per batch would throw away that calibration and make every score depend
on the single most- and least-anomalous rows *in this particular batch* — the same row would score
differently depending on what else happened to be in the file (module docstring, anomaly.py:15-20).

**This is NOT a probability.** The [0,1] score is a calibrated *anomaly rank*, not P(bot). Never
describe it, or the heuristic score, as a probability in docs or output (a `bwl-docs-and-writing`
non-negotiable).

**Degenerate guard.** `score_matrix` returns a constant `0.5` (`DEGENERATE_ANOMALY_SCORE`, backend
`"degenerate"`) when there is nothing to rank: 0 features, or `< 3` rows (anomaly.py:65-68).

---

## 4. The dependency-free fallback — honest but weaker

When `isotree` is not installed, `score_matrix` uses `_deviation_score` (anomaly.py:178):

```
row_score = mean( |robust_z of each feature| )     # then min-max mapped to [0,1]
```

**Idea.** Score each row by how far its features sit from the batch norm *on average*. It is a
**marginal** detector: it treats features independently and **ignores interactions** — it cannot see
"same-context AND same-instant", only "unusual on some axes". That is strictly weaker than the forest,
and the code and docstring say so plainly (backend string `"fallback"`).

Because a mean-abs-deviation has no natural scale, the fallback (and only the fallback) is `_minmax`-ed
to [0,1] (anomaly.py:74,190) — so fallback scores *are* batch-relative, unlike EIF's. If the batch is
constant, `_minmax` returns `0.5` everywhere.

**Verified example.** Matrix `[[10,1],[11,1],[12,1],[13,1],[100,9]]` → raw mean|robust_z|
`[0.674, 0.337, 0, 0.337, 30.928]` → min-max `[0.022, 0.011, 0, 0.011, 1.0]`. The outlier pins to 1.0;
everything else collapses near 0. Serviceable, but it only fired on the marginal `100`/`9`, not on any
joint structure.

---

## 5. Kneedle knee detection — self-tuning the ML threshold

**Idea.** Sort the ML scores from most to least anomalous. The curve drops steeply through the
anomaly tail, then flattens into the body of ordinary traffic. The **elbow** ("knee") of that curve is
the natural cut. Kneedle (Satopää et al. 2011) finds the point of maximum curvature.

**Function.** `dynamic_knee_threshold` in `bots_without_labels/threshold.py:23` returns
`(threshold, method)`. It sorts descending, drops non-finite scores, then walks a **fallback ladder**:

| Method string | Fires when | Returns |
|---|---|---|
| `empty_input` | no finite scores | `0.0` |
| `small_input_fallback` | `< 10` scores (`SMALL_INPUT_SIZE`) | `max(scores)` → flags nothing |
| `tied_score_fallback` | `< 3` distinct values (`TIED_SCORE_MIN_DISTINCT`) | `max(scores)` → the "curve" is a step function, Kneedle is meaningless |
| `kneedle_descending` | **normal path** — `kneed` installed and finds an interior knee | score at the knee index |
| `max_distance_descending_fallback` | `kneed` missing, or knee is `None`, or knee lands on an endpoint | geometric fallback |

**The geometric fallback** (`_max_distance_threshold`, threshold.py:78). Normalise positions and
values to [0,1]; the chosen index is the point whose value is **furthest above the anti-diagonal**
`(1 − position)` — a dependency-free "elbow" that needs no `kneed`. `kneed` itself is optional; when
absent every call lands here.

Kneedle rejects a knee on the first or last point (`index <= 0 or index >= len-1`, threshold.py:73) —
an endpoint "knee" means "flag everything" or "flag nothing", never a real elbow.

**Verified examples.** `[]` → `(0.0,'empty_input')`; three scores → `('small_input_fallback')`; twenty
identical → `('tied_score_fallback')`; a 3-point steep head + 30-point flat tail →
`(0.129, 'max_distance_descending_fallback')` in an env without `kneed`.

---

## 6. Adaptive count thresholds — "how many repeats is suspicious HERE?"

**Idea.** A fixed "flag anything seen > 50 times" is wrong on both a tiny log (never fires) and a huge
one (fires on everything popular). Instead the count threshold is the **99th percentile of the
distinct-group sizes**, floored by a constant.

**Function.** `_adaptive` in `bots_without_labels/rules.py:588`, with `COUNT_PERCENTILE = 0.99`
(rules.py:110). "Distinct-group sizes" = for each distinct value, how many rows have it. It takes the
99th percentile *of that list*, then `max(floor, …)`.

```
ordered = sorted(group_size for each distinct value, if size > 0)
index   = ceil(len(ordered) * 0.99) - 1
threshold = max(floor, ordered[index])
```

Floors per rule family (rules.py:111-114): `TEXT_REPEAT_FLOOR=10`, `NUMERIC_REUSE_FLOOR=10`,
`CONCENTRATION_FLOOR=50`, `SAME_INSTANT_FLOOR=4`.

**Two properties** (docstring, rules.py:594-604):

- **Flat/uniform log** → almost every value unique → the 99th percentile is ~1 → the **floor
  governs**. Verified: `_adaptive([1]*100, 10)` → `10`.
- **Heavy-tailed real log** → the percentile rises above the floor → a rule fires only on the
  genuinely over-represented tail, so the false-positive rate stays bounded as the batch grows.
  Verified: `_adaptive([1]*90 + [50,60,80,200,500,1000,...], 10)` → `500`.

**Why it is robust to the bot fraction** (the subtle, important bit). Bots that repeat are a *few
distinct values each seen many times* — they add only a handful of entries to the distinct-size list,
so they **barely move the 99th percentile they are being measured against**. The threshold meant to
catch them is not inflated by them.

**The degree floor is the same trick on connectivity.** `_degree_floor` (rules.py:503) takes
`DEGREE_FLOOR_PERCENTILE = 0.99` (rules.py:106) of the *hub-subset* node degrees (endpoints already
reaching ≥ `MIN_HUB_DEGREE = 3` counterparts). Data-relative, not a magic count. **Caveat:** the
degree-floor / asymmetry constants (`DEGREE_ASYMMETRY = 10`) are explicitly labelled **guardrails
calibrated on limited evidence, not scale-free general constants** (rules.py:100-105) — do not present
them as established. See `bwl-config-and-flags` for the production-vs-guardrail split.

---

## 7. The supporting-evidence cap — why repetition alone never flags

**Idea.** Rules are split into **strong** (direct timing/replay evidence, full weight) and
**supporting** (weaker context — repetition, concentration, low entropy). The *combined* weight of all
supporting rules on a row is capped, so no pile of weak signals can flag a row on its own. Only strong
timing evidence — and it takes *two* corroborating timing signals — reaches the 0.70 cutoff.

**Function.** `_cap_and_sum` in `bots_without_labels/rules.py:639`, cap `SUPPORTING_CAP = 0.24`
(rules.py:28). Sum the strong weights at full value; sum the supporting weights and, if that sum
exceeds 0.24, scale every supporting hit down by `0.24 / supporting_total`; total is `min(…, 1.0)`.

Weights (rules.py:39-46): strong — `W_SAME_INSTANT_BURST=0.40`, `W_REGULAR_TIMING=0.40`,
`W_LOCAL_BURST=0.35`. Supporting — `W_TEXT_REPEAT=0.12`, `W_NUMERIC_REUSE=0.12`,
`W_CATEGORICAL_CONCENTRATION=0.08`, `W_CONTEXT_CLUSTER=0.10`, `W_LOW_ENTROPY=0.06`.

**Verified arithmetic.**

| Row's hits | Raw sum | After cap | ≥ 0.70? |
|---|---|---|---|
| one strong `0.40` + all four supporting (`0.12+0.12+0.08+0.06 = 0.38`) | 0.78 | `0.40 + 0.24` = **0.64** | **No** |
| same-instant `0.40` + local-burst `0.35` (two strong timing) | — | **0.75** | **Yes** |
| regular-timing `0.40` + local-burst `0.35` | — | **0.75** | **Yes** |

So a viral query or a common latency that trips *every* count/concentration/entropy rule still lands
at 0.64 and is **not** flagged by the heuristic head — exactly the design intent (rules.py:30-38). The
big weights (`W_ENTITY_MONOTONY = 0.70`, `W_ASYMMETRIC_DEGREE = 0.70`, rules.py:63,93) are the two
`strong` rules that *can* reach the cutoff alone; they carry heavy structural guards (hub degree,
directional asymmetry) precisely because they are single-signal flags.

---

## 8. Supporting maths (the smaller pieces)

**Timestamp-grid estimation** (`_timestamp_grid`, features.py:773). Many logs are quantised — a
minute-binned flow export snaps every timestamp to `:00`. Firing "same-instant" rules on that is a
binning artefact. The grid is the **mode of the positive gaps between distinct, deduped timestamps**
— the spacing the clock is actually snapped to (60s → a minute grid). The mode, *not* the
min/median/percentile: a handful of off-grid jitter timestamps change rare gap values but not the
*most common* one, so the estimate is robust to clock glitches. Returns `None` (rules stay active)
when there are `< 2` distinct timestamps.

**Phase-aware on-grid membership** (`_on_grid`, features.py:811). A coarse clock need not be
epoch-aligned — minute bins at `:30` are still a 60s grid with non-zero phase. The phase is recovered
as the **modal remainder** of distinct timestamps modulo the grid; a row is on-grid when its circular
distance to that phase is within `GRID_ALIGNMENT_TOLERANCE_SECONDS`. On-grid rows are suppressed
(artefact); a sub-grid burst (e.g. an injected cluster at `…:53` on a minute grid) stays off-grid and
observable. Computed in integer nanoseconds so the modular arithmetic is exact. Crucially the timing
rules gate **per collision**, so an off-grid burst inside an otherwise-coarse log is still caught.

**Percentile rank / batch percentile** (`feature_deviations`, anomaly.py:77). Turns a high score into
readable evidence: for each explained row it reports the top-k features by `|robust_z|`, each with its
`batch_percentile` = `scipy.stats.rankdata(method="average") / n_rows` — the value's rank in the batch
in [0,1], ties averaged. `>= 0.99` reads "top 1% of the batch". `TOP_DEVIATION_FEATURES = 5`
(anomaly.py:42). This is the explanation layer, not a scorer.

**Quantile binning for entropy over numerics** (`_context_arrays`, features.py:743). Entropy needs
discrete labels, but numeric columns are continuous. Each numeric context column is binned with
`pd.qcut(num.rank(method="first"), q=ENTITY_DIVERSITY_BINS, labels=False, duplicates="drop")` —
`ENTITY_DIVERSITY_BINS = 8` (features.py:54). Ranking **first** before `qcut` forces roughly-equal-count
bins even with heavy ties (raw `qcut` on tied values would collapse bins); NaNs go to a `-1` bucket.
Verified: `qcut(rank([5,5,5,1,2,3,4,100,200,300]), q=8)` → `[3,4,5,0,0,1,2,6,7,7]` — eight
rank-ordered buckets, ties spread by first-appearance order.

---

## Cross-checks (fast facts to re-derive)

- **A repeated value is not enough.** Repetition rules are all `SUPPORTING`, capped at 0.24 < 0.70 (§7).
- **The ML score never re-min-maxes** (EIF path); only the fallback does (§3–4).
- **"method" strings** on the threshold tell you which rung of the ladder fired (§5) — read them in
  `run-output` / benchmark JSON when a flag rate looks wrong.
- **Score ≠ probability.** Both heads produce ranks; do not call them probabilities.

---

## Provenance and maintenance

Authored 2026-07-06. Repo at commit `8a85edd` ("Refresh roadmap: fold shipped arcs into a Shipped
section"). All numeric examples were verified with `uv run python -c` against the working tree on this
commit; benchmark figures are cited from `evaluation/BENCHMARKS.md`, not re-run here.

| Volatile fact | One-line re-verification |
|---|---|
| MAD→σ constant `1.4826` | `grep -n "_MAD_TO_STD" bots_without_labels/anomaly.py` |
| EIF config (100 trees, ndim 2, 4096, nthreads 1) | `grep -n "EIF_TREES\|EIF_EXTENSION_DIMS\|EIF_SAMPLE_SIZE\|nthreads" bots_without_labels/anomaly.py` |
| Kneedle fallback method strings | `grep -n "fallback\|kneedle_descending\|SMALL_INPUT_SIZE\|TIED_SCORE_MIN_DISTINCT" bots_without_labels/threshold.py` |
| `COUNT_PERCENTILE=0.99`, floors | `grep -n "COUNT_PERCENTILE\|_FLOOR =" bots_without_labels/rules.py` |
| `SUPPORTING_CAP=0.24` and rule weights | `grep -n "SUPPORTING_CAP\|^W_" bots_without_labels/rules.py` |
| Heuristic cutoff 0.70 / ML rate cap 0.02 | `grep -n "HEURISTIC_CUTOFF\|MAX_ML_FLAG_RATE" bots_without_labels/pipeline.py` |
| `ENTITY_DIVERSITY_BINS=8` | `grep -n "ENTITY_DIVERSITY_BINS" bots_without_labels/features.py` |
| Cap arithmetic reproduces (0.64 / 0.75) | run the `_cap_and_sum` snippet in §7 via `uv run python -c` |
| Benchmark numbers (CICIDS 0.998/0.846, CTU-13 sc3 0.985/0.929) | `grep -n "0.998\|0.985" evaluation/BENCHMARKS.md` |
| Degree/asymmetry guardrail caveat still stands | `grep -n "GUARDRAILS\|not scale-free\|DEGREE_ASYMMETRY" bots_without_labels/rules.py` |

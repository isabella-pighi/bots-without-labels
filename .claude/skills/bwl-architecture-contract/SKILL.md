---
name: bwl-architecture-contract
description: Load when you need the WHY behind a design choice before changing it — why rules key on inferred roles not column names, why the two detectors are joined by OR, why only timing/graph evidence is "strong" and repetition is capped, why every threshold is batch-relative, why the actor graph is undirected with source by schema order, why timestamps are grid-gated, why everything is deterministic. Load before touching rule weights, the 0.70 cutoff, the cardinality band, the degree/asymmetry guardrails, or the evidence-tier logic; before proposing a new hardcoded branch (e.g. "special-case clicks/DNS/this dataset"); or when asked "is this safe to change / what invariant would this break / why is it built this way". Names: rules.py, anomaly.py, pipeline.py, features.py, DEGREE_ASYMMETRY, SUPPORTING_CAP, entity_monotony, asymmetric_degree.
---

# BWL Architecture Contract

The load-bearing design decisions of the detector, each with its rationale and the incident that
proved it. This is the "why you must not just change this" reference. It does not tell you the mechanics
of running the tool (see `bwl-build-run-operate`) or the maths (see `bwl-detection-theory`); it tells you
which decisions are structural and what breaks if you undo them.

**Orientation for a zero-context reader.** This project finds *bots* (automated clients: botnet hosts
talking to a command-and-control server, scrapers, click-fraud farms) in *logs that carry no labels* —
nobody has marked which rows are bots. It scores every row two ways and flags a row if **either** says
"anomalous". A *flow*/NetFlow row = one network conversation (source address, destination address, ports,
byte counts, timestamp). *C2* = command-and-control, the server a botnet phones home to. Jargon is defined
at first use; deeper background is in `netflow-botnet-reference` and `bwl-detection-theory`.

## When NOT to use this skill

| Your question is about… | Go to |
|---|---|
| How to run the pipeline / CLI / set up the env | `bwl-build-run-operate` |
| What a constant does and how to add a new flag | `bwl-config-and-flags` |
| The maths (entropy, robust z/MAD, isolation forest, Kneedle) | `bwl-detection-theory` |
| How to classify/gate/review a change; HCOM protocol | `bwl-change-control` |
| A concrete failure and its root cause / evidence | `bwl-failure-archaeology` |
| Symptom → triage for a live bug | `bwl-debugging-playbook` |
| How to measure a change (diagnostics, benchmarks) | `bwl-diagnostics-and-tooling` |
| Security-domain theory (flows, families, datasets) | `netflow-botnet-reference` |

This skill is the *contract*: the decisions and their WHY. When a change would touch one, read the
relevant row here first, then hand off to the skill above for the mechanics.

---

## The pipeline in one line

`load` (infer schema) → `build_features` (numeric matrix + `FeatureContext`) → `apply_rules`
(explainable score) **and** `score_matrix` (anomaly score) → `dynamic_knee_threshold` → **decide**.
Source of truth: `bots_without_labels/pipeline.py:detect`.

```
is_bot = heuristic_score >= 0.70  OR  ml_score > dynamic_ml_threshold
```

Everything below is a decision that this line, or a stage feeding it, depends on.

---

## The ten load-bearing decisions

### 1. Roles, not names — behaviour is emergent, never a hardcoded branch

Every rule and feature keys off an **inferred column role** (`timestamp`, `numeric`, `categorical`,
`text`, `url`, `identifier`), never off a column *name* or a dataset-specific `if`. The loader
(`ingest.py:infer_schema`) classifies each column; features and rules then react to roles.

- The original ad-click behaviour (repeated query/domain, reused time-to-click, same-second bursts) is
  **not** a click module. A `url` column is detected and its query string expanded into ordinary columns
  (`url__d`, `url__q`, `url__ttc` …) by `ingest.py:_expand_url_columns`, and the generic role-driven rules
  then light up on those columns. `synthetic.py` header and `rules.py` header both state this explicitly.
- **WHY:** the promise is *"any CSV/TSV/JSON log without bespoke parsing"* (TODO item 1, shipped). A
  hardcoded `if column == "url"` branch would make the tool a click detector wearing a general-purpose
  costume. The same generality is what lets a NetFlow capture and a web access log run through the *same*
  `detect()`.
- **Invariant:** no rule may branch on a literal column name or a dataset identity. New signal must be
  expressed as "for columns of role X, when property Y holds". TODO item 1's own acceptance bullet:
  *"Click-specific behaviour appears only when the relevant columns are detected, never as a hardcoded
  branch."*

### 2. Two detectors joined by OR — explainability carries precision, EIF catches the unnamed

Two independent scorers, combined with a logical OR, never averaged:

| Detector | File | Score | Role |
|---|---|---|---|
| Explainable rules | `rules.py` | heuristic ∈ [0,1], each point has a human reason | Precision + the *why* a reviewer needs |
| Extended Isolation Forest (EIF) | `anomaly.py` | anomaly ∈ [0,1] | Catches anomalies no rule names |

*EIF = Extended Isolation Forest, an unsupervised outlier model that scores how easily a row is isolated
from the rest; see `bwl-detection-theory`.*

- **WHY OR, not average:** averaging would let the transparent half dilute the black-box half and vice
  versa, and would destroy the *evidence tier* — the record of **which** detector fired. `pipeline.py`
  computes `evidence_tier`: 1 = both agree, 2 = rules only, 3 = ML only, 0 = not selected. A reviewer
  triages tier-2 by reading `reasons`, tier-3 by reading `feature_deviations` (top robust-z deviations,
  added because a bare anomaly score is unactionable — TODO item 3, shipped).
- **Invariant:** the two scores stay separable end-to-end; the decision is a disjunction; every selected
  row must be explainable via *either* a rule reason *or* a feature-deviation list.

### 3. Evidence weighting contract — only timing/graph evidence is STRONG; popularity alone must never flag

Rules are `STRONG` or `SUPPORTING`. Supporting hits are summed and **capped** so they can never on their
own reach the 0.70 cutoff. Source: `rules.py` weights block and `_cap_and_sum`.

| Rule (`rule_id`) | Weight | Strength | Fires on |
|---|---|---|---|
| `same_instant_burst` | **0.40** | STRONG | many events at the exact same timestamp |
| `local_burst` | **0.35** | STRONG | dense pile-up in a short window within a context |
| `regular_timing` | **0.40** | STRONG | mechanically regular inter-arrival (low CV) |
| `entity_monotony` | **0.70** | STRONG | high-volume actor doing essentially one thing (+ hub, see §6) |
| `asymmetric_degree` | **0.70** | STRONG | source fan-out broadcaster (see §6) |
| `repeat_value` / `numeric_reuse` | 0.12 | SUPPORTING | a value recurs a lot |
| `concentration` / `context_cluster` | 0.08 / 0.10 | SUPPORTING | a value / context is over-represented |
| `low_entropy` | 0.06 | SUPPORTING | a low-entropy text string |
| **SUPPORTING_CAP** | **0.24** | — | ceiling on the *sum* of all supporting hits |

Verify: `uv run python -c "import bots_without_labels.rules as r; print(r.SUPPORTING_CAP, r.W_SAME_INSTANT_BURST, r.W_LOCAL_BURST, r.W_REGULAR_TIMING, r.W_ENTITY_MONOTONY, r.W_ASYMMETRIC_DEGREE)"`
→ `0.24 0.4 0.35 0.4 0.7 0.7`.

- **WHY:** *"popularity alone must never flag."* A viral search query, a common latency, a busy-but-benign
  channel all repeat values and concentrate on popular contexts — to a count-based rule they look exactly
  like a low-volume replay. So repetition/concentration/low-entropy are *supporting only*, capped at 0.24,
  well under 0.70. The two lone-timing rules (0.40) also cannot reach 0.70 alone: a flag needs **two
  corroborating** timing signals (same-instant *and* a burst, or regular pacing *and* a burst). Only the
  two graph-aware rules reach 0.70 on their own — and each has extra structural gates (§6).
- **THE COUPLING — the single most important maintenance fact:** the weights, the `SUPPORTING_CAP`, and
  the `HEURISTIC_CUTOFF = 0.70` were calibrated **together**. `pipeline.py:HEURISTIC_CUTOFF` docstring:
  *"Change the weights and this cutoff together."* Nudging any one in isolation silently re-decides what
  "needs corroboration" means. If you touch a weight, re-derive the cutoff and re-run the benchmark suite;
  never ship one without the other.
- **Invariant:** no `SUPPORTING` rule, alone or summed, may cross 0.70. No single lone-timing STRONG rule
  may cross 0.70 alone.

### 4. Every threshold is batch-relative — never tuned to one capture

No rule uses a fixed "flag if count > N" magic number as its primary cut. Each derives its threshold from
the current batch:

| Mechanism | Where | What it adapts to |
|---|---|---|
| Adaptive count threshold = 99th pct of **distinct-group sizes**, floored | `rules.py:_adaptive`, `COUNT_PERCENTILE=0.99` | value-popularity distribution of this batch |
| Entity diversity cut = low-tail quantile of qualified entities' diversity, ceilinged | `rules.py` entity_cut, `ENTITY_DIVERSITY_PERCENTILE/CEILING` | how monotone this batch's actors are |
| Degree floor = 99th pct of the **hub-subset** degrees | `rules.py:_degree_floor`, `DEGREE_FLOOR_PERCENTILE=0.99` | this batch's connectivity |
| ML threshold = Kneedle elbow of sorted anomaly scores | `threshold.py:dynamic_knee_threshold` | this batch's score curve |
| ML rate cap = flag at most 2% on ML alone | `pipeline.py:MAX_ML_FLAG_RATE=0.02` | bounds ML tail regardless of elbow |

- **WHY the 99th percentile is over *distinct group sizes*, not per-row counts** (`_adaptive` docstring):
  on a flat log almost every value is unique, so the percentile ≈ 1 and the *floor* governs; on a
  heavy-tailed log the percentile rises so only the over-represented tail fires and the false-positive
  rate stays bounded as the batch grows. Crucially it is **robust to the bot fraction**: bots are a *few
  distinct* values, so they barely move the distinct-size distribution and cannot inflate the very
  threshold meant to catch them.
- **WHY the ML rate cap:** Kneedle finds an elbow even when there is no real anomaly tail; the 2% cap
  stops a loose elbow from flooding the output. `pipeline.py` uses `max(kneedle, 98th-pct)` and tags the
  method `…+rate_capped`.
- **Invariant:** thresholds must remain functions of the batch. A constant tuned to make one dataset's
  number look good is overfitting and forbidden — see §Known-weak-points for where this rule is *already*
  strained (the degree guardrails).

### 5. The cardinality band `[0.02, 0.5]` gates who can be an "actor"

An *actor/entity column* is one whose values identify **who** is communicating (an IP address, a session
id) so the row can be baselined against that actor's own history. A column qualifies only if its
`cardinality_ratio` (distinct values ÷ rows) sits inside a band. Both the entity-baseline path
(`features.py:_entity_columns`) and the relational actor graph (`features.py:_actor_endpoint_columns`)
use the **same** band. Verify:
`uv run python -c "import bots_without_labels.features as f; print(f.ACTOR_MIN_RATIO, f.ACTOR_MAX_RATIO)"`
→ `0.02 0.5`.

| Bound | Value | Excludes | WHY |
|---|---|---|---|
| lower `ACTOR_MIN_RATIO` | 0.02 | bounded vocabularies (TCP `State`, `Proto`, region, status code) | their distinct count does **not** scale with the data — they are *context*, not actors |
| upper `ACTOR_MAX_RATIO` | 0.5 | per-row / edge identifiers (flow id, composite 5-tuple key) | mostly-unique values identify the *row*, not a recurring actor, and would corrupt degrees |

- **The incident (recorded in `_entity_columns` docstring + `evaluation/FINDINGS.md`):** without the lower
  bound, CTU-13's degenerate low-cardinality `Proto`/`State` columns (ratio ~0.0002–0.002) were baselined
  as entities, so `entity_monotony` over-flagged the NetFlow background. Real IP columns (ratio
  ~0.04–0.06) sit inside the band and are kept. The band is what fixed the CTU-13 over-flagging (see
  `bwl-failure-archaeology`, "CTU-13 precision root cause").
- **Invariant:** any new "who is the actor" logic reuses this single band; do not add a second, divergent
  cardinality gate.

### 6. Undirected actor graph, source by schema order, source-fan-out only

The relational graph is built **undirected**: generically we cannot tell source from destination without
name-matching, which is deliberately avoided (name-matching is a §1 violation). Degrees are per-role
counterpart counts. But one rule needs direction, and gets it *structurally*:

- **Source = first actor column in schema order.** `_asymmetric_endpoint` takes `actor_columns[0]` as the
  originating endpoint, because in flow logs source precedes destination by convention (`SrcAddr` before
  `DstAddr`, `Source IP` before `Destination IP`). This is a **schema-order** signal, not a name match and
  not a magic constant.
- **`asymmetric_degree` fires on source FAN-OUT only** (out-degree ≫ in-degree, on a monotone service):
  the spam/scan/click-fraud broadcaster reaching many peers. It **deliberately does not fire on fan-IN** —
  a destination reached by many. A benign DNS resolver, NTP source, or load balancer is exactly a fan-in
  hub, and on real captures (CTU-13 / Rbot) those infra hubs were the dominant false positive when the
  rule was undirected.
- **Fan-in C2 coverage is owned by `entity_monotony`'s hub gate, not here.** The two rules split the
  work: `entity_monotony` escalates a monotone entity that is *also* a hub (≥ `MIN_HUB_DEGREE = 3`
  distinct counterparts, direction-agnostic) — the C2 fanned-to by many hosts; `asymmetric_degree` owns
  the directional broadcaster. On CICIDS the fan-in C2 is carried by `entity_monotony` and
  `asymmetric_degree` fires 0 there.
- **The incident:** the original direction-agnostic `asymmetric_degree` gave CTU-13/Rbot precision 0.056.
  Restricting it to source fan-out recovered precision to **0.929** at recall 0.985 (commit `13e9436`;
  `evaluation/FINDINGS.md` Rbot row; `bwl-failure-archaeology`, "CTU-13 Rbot generality").
- **Invariant:** direction is inferred from schema order, never a name. The fan-out/fan-in split between
  the two rules is a contract — do not let one rule start covering the other's shape without re-measuring
  both precisions.

### 7. Dense-timing gating is per-collision, phase-aware, and mode-based

The dense-timing rules (`same_instant_burst`, `local_burst`) assume the clock is fine enough that
co-occurrence means genuine simultaneity. On a coarse clock (a minute-quantised flow log) an "on-grid same
instant" is really a wide bin holding many independent events, so every busy bin would trip these rules on
benign volume. Gating logic in `rules.py` (grid block) + `features.py:_timestamp_grid`/`_on_grid`:

- **Per collision, not per rule:** suppression is decided for each row's timestamp, only where the shared
  timestamp lies *on* the coarse grid. An *off-grid* pile at a sub-second instant the clock recorded
  precisely is genuine simultaneity and **still fires** — so a real burst injected into a coarse-grid log
  stays observable.
- **Phase-aware:** the grid's dominant offset (phase) is recovered as the modal remainder, so minute bins
  at `:30` count as on-grid like bins at `:00`.
- **Mode, not median or minimum, for the grid period** (`FeatureContext.timestamp_grid` docstring): the
  grid is the *most common* positive gap between consecutive distinct timestamps. WHY mode: a handful of
  off-grid jitter timestamps cannot move the detected grid — the dominant spacing wins; median or minimum
  would be dragged by outliers.
- **Measured effect:** CICIDS/Ares is minute-quantised at source → dense-timing rules gate off, and the
  detector still hits recall 0.998 because resolution-independent evidence (`entity_monotony`, the hub
  gate) carries the decision. CTU-13 is microsecond → rules active. (`evaluation/BENCHMARKS.md`.)
- **Invariant:** dense-timing evidence stays gated by clock resolution; never treat "same wide bin" as
  "same instant".

### 8. Determinism everywhere — because tests and recorded numbers are exact

Every stochastic step is seeded and single-threaded, so outputs are bit-reproducible across runs and
hosts:

| Where | How |
|---|---|
| EIF model | `anomaly.py`: `random_seed=seed` (default 7), **`nthreads=1`** |
| Anomaly score | native EIF `decision_function` used **as-is**, never re-min-maxed per batch |
| Synthetic/injection | seeded `random.Random(seed)`; loader samples the top N rows deterministically |
| Kneedle | `online=False` |

- **WHY single-threaded EIF:** multithreaded tree building is not bit-reproducible; the golden benchmark
  numbers and the tests assert exact outputs. `anomaly.py`: *"Single-threaded keeps scoring
  bit-reproducible across runs and hosts."*
- **WHY score used as-is:** the EIF `decision_function` is already a calibrated [0,1] anomaly score with
  the standard sample-size normalisation. Re-min-maxing per batch would throw that away and make the score
  depend on the single most- and least-anomalous rows in the batch (`anomaly.py` header). (The
  dependency-free *fallback* scorer has no natural scale, so it — and only it — is min-max mapped.)
- **Invariant:** never introduce an unseeded RNG, multithread the forest, or re-scale the EIF score per
  batch. Any of these silently invalidates every recorded number and breaks tests.

### 9. Atomic artefact writes

Every generated file (`predictions.tsv`, `summary.json`, `features.tsv`, `selected_events.json`, the
threshold PNG) is written to a temporary sibling and `os.replace`-d into place — `atomic.py`
(`atomic_text_writer`, `atomic_path_writer`), used throughout `pipeline.py`. **WHY:** a crashed or
concurrent run never leaves a half-written artefact that a downstream reader (a notebook, a benchmark)
would silently consume. **Invariant:** new artefact writers go through `atomic.py`, not bare `open`.

### 10. The measurement layer mirrors the detector — including deliberately-undetectable bots

Detection on unlabelled data has no scorecard, so `synthetic.py` manufactures one: legitimate traffic
mixed with bots of known **archetypes**, labels returned alongside. `inject.py` does the same into *real*
captures. Four archetypes, and this is a contract, not an accident:

| Archetype | Detectable? | WHY |
|---|---|---|
| `burst` | yes | same-second pile-up → dense-timing rules |
| `mechanical_timing` | yes | regular cadence → `regular_timing` |
| `diffuse_replay` | **no, on purpose** | same value from diverse contexts = indistinguishable from a viral query without labels or a stable per-user id |
| `stealth` | **no, on purpose** | mimics human variance, leaves no signature — the floor of what unlabelled detection can do |

`synthetic.py:DETECTABLE_ARCHETYPES = ("burst", "mechanical_timing")`. **WHY keep two undetectable ones:**
so the measured numbers are *"not just we detect what we planted"* — low recall on `diffuse_replay` /
`stealth` is the honest, expected result, and holding them out guards against overfitting the detector to
its own fixtures. **Invariant:** never "fix" recall on the evasive archetypes by adding a signal that also
flags popular legitimate traffic — that inverts the whole evidence contract (§3).

---

## INVARIANTS — what a change must never break

A one-screen checklist. If your change would flip any of these, stop and route through `bwl-change-control`.

1. **No name/dataset branch.** Rules and features key on roles and properties, never a literal column name
   or dataset identity (§1).
2. **Two separable scores, OR-combined, always explainable.** Every flag is readable via a rule reason
   (tiers 1–2) or feature deviations (tier 3) (§2).
3. **Popularity alone never flags.** Repetition/concentration/low-entropy stay SUPPORTING and summed ≤
   `SUPPORTING_CAP = 0.24`; no lone STRONG timing rule reaches 0.70 (§3).
4. **Weights, cap, and 0.70 cutoff move together** — never one in isolation (§3).
5. **Thresholds stay batch-relative** — 99th-pct distinct-group sizes with floors, Kneedle knee, 2% ML
   cap, hub-subset degree floor. No constant tuned to one capture (§4).
6. **One cardinality band `[0.02, 0.5]`** gates both entity and actor columns (§5).
7. **Actor graph undirected; direction from schema order, not names; fan-out ≠ fan-in ownership split**
   between `asymmetric_degree` and `entity_monotony` (§6).
8. **Dense timing stays clock-gated** — per-collision, phase-aware, mode-based grid (§7).
9. **Determinism** — seeds fixed, EIF single-threaded, EIF score used as-is (§8).
10. **Atomic writes** for every artefact (§9).
11. **The two evasive archetypes stay unsolved by trickery** (§10).

---

## KNOWN-WEAK-POINTS — stated plainly (do not oversell)

These are open or limited-evidence, on the record. Do not present any of them as solved.

| Weak point | Status | Evidence / where |
|---|---|---|
| **ML-only false-positive tail** | Open, dominant residual. On CICIDS/Ares, of 358 false positives ~253 (≈70%) are tier-3 ML-only flags, attributable to no heuristic rule; the heuristics are ~0.95 fire-precision. The residual error is an EIF *calibration* question, not a rule problem. | `evaluation/FINDINGS.md` (~line 152); `bwl-detection-theory` |
| **Fan-in generality guarded, not proved** | `entity_monotony`'s hub gate covers fan-in C2 on the captures tested; it is not proven to generalise across families. | §6; `evaluation/FINDINGS.md` |
| **`DEGREE_ASYMMETRY = 10` + 99th-pct degree floor are GUARDRAILS, not general constants** | On the *one* labelled split tested (CTU-13/Neris) + a synthetic broadcaster: result unchanged for asymmetry factors ~10–100, **over-fires below ~10**, and the rule **vanishes at ≥ 200** (exceeds Neris's own ratio). Generality unproven; tracked follow-up. Do **not** read these as scale-free. | `rules.py` `DEGREE_ASYMMETRY` block; verify `uv run python -c "import bots_without_labels.rules as r; print(r.DEGREE_ASYMMETRY, r.DEGREE_FLOOR_PERCENTILE, r.MIN_HUB_DEGREE)"` → `10 0.99 3` |
| **Diversity-cut tie-edge brittleness** | The entity diversity cut is a low-tail quantile capped by a ceiling; on batches where many entities tie at the cut, membership on the boundary is brittle. | `rules.py` entity_cut; `ENTITY_DIVERSITY_CEILING`/`PERCENTILE` |
| **Integer-coded identifiers missed** | A numeric `session_id` or numeric IP is typed `numeric`, so per-entity baselining and id handling skip it. Open. | **TODO follow-up H**; couples with schema-override hints (item 4) |
| **Unreviewed-change debt** | The per-entity baselining fix (commit `98646c1`) was committed direct-to-main, bypassing the PM-commits-only / Codex-review protocol. Benchmark-verified since, so process debt not correctness risk — but still owed a review. | **TODO follow-up G**; `bwl-change-control` |

---

## Provenance and maintenance

Authored 2026-07-04 (repo re-verified at commit `8a85edd`; benchmark numbers as recorded in
`evaluation/BENCHMARKS.md` / `FINDINGS.md` on that branch). British English. All constants and the test
count were verified by import/collection at authoring time.

| Volatile fact | One-line re-verification |
|---|---|
| Rule weights + supporting cap | `uv run python -c "import bots_without_labels.rules as r; print(r.SUPPORTING_CAP, r.W_SAME_INSTANT_BURST, r.W_LOCAL_BURST, r.W_REGULAR_TIMING, r.W_ENTITY_MONOTONY, r.W_ASYMMETRIC_DEGREE)"` |
| Heuristic cutoff + ML rate cap | `uv run python -c "import bots_without_labels.pipeline as p; print(p.HEURISTIC_CUTOFF, p.MAX_ML_FLAG_RATE)"` |
| Cardinality band | `uv run python -c "import bots_without_labels.features as f; print(f.ACTOR_MIN_RATIO, f.ACTOR_MAX_RATIO)"` |
| Degree guardrails | `uv run python -c "import bots_without_labels.rules as r; print(r.DEGREE_ASYMMETRY, r.DEGREE_FLOOR_PERCENTILE, r.MIN_HUB_DEGREE)"` |
| EIF determinism knobs | `uv run python -c "import bots_without_labels.anomaly as a; print(a.EIF_TREES, a.EIF_EXTENSION_DIMS, a.EIF_SAMPLE_SIZE)"` then `grep -n "nthreads\|random_seed\|standardize_data" bots_without_labels/anomaly.py` |
| Decision line text | `grep -n "is_bot = heuristic" bots_without_labels/pipeline.py` |
| Detectable vs evasive archetypes | `uv run python -c "import bots_without_labels.synthetic as s; print(s.ARCHETYPES, s.DETECTABLE_ARCHETYPES)"` |
| Recorded benchmark numbers | `grep -nE "Ares|Neris|Rbot|Bournemouth" evaluation/BENCHMARKS.md` |
| ML-tail residual ratio | `sed -n '146,156p' evaluation/FINDINGS.md` |
| Open weak points G/H | `grep -n "### G\|### H" TODO.md` |
| Suite collects and passes (~80+ at authoring) | `uv run pytest --collect-only -q | tail -1` |

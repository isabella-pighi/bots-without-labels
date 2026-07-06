---
name: bwl-diagnostics-and-tooling
description: >
  How to MEASURE the Bots Without Labels detector instead of eyeballing it. Load
  when you need to answer "which rule caused these false positives?", "why was
  this row flagged?", "what did the detector decide on this log and why?", or
  "did my change move the benchmark numbers?" — i.e. when working with
  evaluation/rule_diagnostic.py, evaluation/run_benchmarks.py, the
  RulesResult.thresholds dict, DetectionResult.feature_deviations(),
  selected_events.json, evidence tiers, or the trace_detection.py script that
  ships with this skill. Symptoms that should trigger it: precision dropped and
  you don't know which rule to blame; a flag has no rule reason; a rule seems
  dormant on some log; you are about to tweak a threshold "by feel".
---

# bwl-diagnostics-and-tooling — measure, don't eyeball

The detector is unsupervised: on real jobs there are no labels, so the only way
to understand its behaviour is to instrument it. This skill catalogues every
measurement tool in the repo, how to read each one, and ships a one-command
tracer for arbitrary logs. Rule of the house: **never tune a threshold or blame
a rule without an attribution number in front of you.**

Minimal domain glossary (details in `netflow-botnet-reference` and
`bwl-detection-theory`): a **flow** is one network-connection summary row
(source/destination address, protocol, bytes); a **botnet** is a set of
compromised hosts remote-controlled via a **C2** (command-and-control) server;
**precision** = flagged rows that are truly bot, **recall** = bot rows that got
flagged, **flag rate** = share of all rows flagged.

## When NOT to use this skill

| If you actually need… | Go to |
|---|---|
| WHY the detector is built this way (invariants, design decisions) | `bwl-architecture-contract` |
| The maths behind the numbers (entropy, MAD, Kneedle, EIF) | `bwl-detection-theory` |
| What each constant/flag means and how to add one | `bwl-config-and-flags` |
| Symptom→triage for a live failure ("it flags everything") | `bwl-debugging-playbook` |
| Whether a past investigation already covered your anomaly | `bwl-failure-archaeology` |
| What counts as evidence / adding a NEW test or benchmark | `bwl-validation-and-qa` |
| Environment setup, CLI anatomy, artefact conventions | `bwl-build-run-operate` |
| First-principles analysis recipes (deriving expected values) | `bwl-proof-and-analysis-toolkit` |
| Getting a measured change committed (review path) | `bwl-change-control` |

## The measurement toolbox at a glance

| Tool | Needs labels? | Question it answers | Command |
|---|---|---|---|
| `trace_detection.py` (this skill) | No | "What did the detector do on THIS log, and why?" | `uv run python .claude/skills/bwl-diagnostics-and-tooling/scripts/trace_detection.py <log> [--top N]` |
| `evaluation/rule_diagnostic.py` | Yes | "Which rule is costing precision / carrying recall?" | `uv run --extra eif python -m evaluation.rule_diagnostic --zip data/GeneratedLabelledFlows.zip` |
| `evaluation/run_benchmarks.py` | Yes (real captures) | "Did my change move the tracked numbers?" | `uv run --extra eif python -m evaluation.run_benchmarks [--only ctu13,ctu13_sc3]` |
| `RulesResult.thresholds` dict | No | "What thresholds/gates did the rules actually apply?" | in-process; also in `artifacts/summary.json` under `rule_thresholds` |
| `DetectionResult.feature_deviations()` / `selected_events.json` | No | "Why did the ML path flag this reasonless row?" | in-process; also `run-output/artifacts/selected_events.json` after a CLI run |
| Evidence tiers | No (labels make them an FP-attribution tool) | "Which classifier carried each flag?" | `predictions-extended.tsv` column `evidence_tier`; tier counts in `summary.json` |

`--extra eif` installs `isotree` for the Extended Isolation Forest (the ML
scorer's preferred backend); without it the detector uses a deterministic
fallback scorer and diagnostic numbers will not match the recorded ones.
All commands run from the repo root.

## 1. rule_diagnostic.py — per-rule false-positive attribution

The decision is `is_bot = heuristic >= 0.70 OR ml_score > dynamic_threshold`
(`bots_without_labels/pipeline.py`), so headline precision is a property of the
*whole* decision — but the levers you can pull are individual rules.
`evaluation/rule_diagnostic.py` splits the blame. It builds the CICIDS2017
benchmark mix (real labelled botnet capture, see `netflow-botnet-reference`),
scores it, and prints two views per rule:

| View | Columns | Meaning |
|---|---|---|
| **Fire view** | `n_fired`, `fired_tp`, `fired_fp`, `fire_precision` | Rows where the rule appears in the evidence at all, split by ground truth. The rule's *stand-alone* precision, regardless of whether the row cleared the decision threshold. |
| **Counterfactual view** | `fp_eliminated`, `tp_lost`, `fp_share` | Recompute the WHOLE decision with this rule's evidence removed (heuristic re-summed and re-capped via `_cap_and_sum`; ML unchanged). A row flagged before but not after is *carried* by the rule. `fp_eliminated` = false positives that would vanish; `tp_lost` = true positives ONLY this rule catches; `fp_share` = `fp_eliminated / total_fp`. |

**The counterfactual view is the actionable one.** A rule with large
`fp_eliminated` and small `tp_lost` is a precision drag you can calibrate or
scope down at little recall risk. A rule with `fire_precision` below the batch
base rate is firing worse than chance. **ML-only flags** (rows no heuristic
rule carries) are reported separately at the top, so heuristic calibration is
never blamed for — or credited with — the anomaly model's decisions.

### How it attributed the CICIDS residual (recorded case study — canonical home)

This is the canonical home for the CICIDS attribution numbers; other skills cite
the one-line result and point back here.

Recorded in `evaluation/FINDINGS.md` ("The headline 0.846 is the whole
detector…"): on the CICIDS2017/Ares mix the detector flags 2,320 rows with 358
false positives (precision 0.846). The diagnostic showed:

- `entity_monotony` fired on 2,067 rows with ~104 false positives
  (fire-precision 0.949) and carries 1,938 of the 1,962 true-positive catches —
  it is the recall engine of that capture, not the FP problem;
- ~253 of the 358 FPs are **ML-only** — attributable to no heuristic rule;
- the other heuristic rules contribute essentially none.

Conclusion drawn (and this is the pattern to imitate): the residual error was
NOT the feared "benign monotone hubs" failure of the heuristic — it is mostly
the ML path, a separate calibration question. Without the counterfactual split,
the obvious-but-wrong move was to tighten `entity_monotony` and lose ~1,900
true positives.

### The CTU-13 story (why attribution precedes tuning)

Same tool, same pattern, twice (`evaluation/FINDINGS.md`):

1. **sc1/Neris, precision 0.041 era**: attribution showed the new
   `asymmetric_degree` rule fired on 2,000/2,000 bot rows with ZERO false
   fires — the over-flagging came entirely from `entity_monotony` baselining
   the degenerate `Proto`/`State` columns. Fix: the actor cardinality-ratio
   band applied to entity columns. Precision 0.041 → 0.978, recall held at
   1.000. The new rule was never the problem; only attribution proved that.
2. **sc3/Rbot, precision 0.056 era**: attribution showed the direction-agnostic
   `asymmetric_degree` firing on benign fan-IN hubs (DNS/NTP/load-balancer
   shapes). Fix: narrow to source fan-OUT only. Precision 0.056 → 0.929, recall
   held at 0.985; the remaining 151 FPs are ML-only, the actor rule contributes
   none.

### When to reach for it, and how to reuse it on other data

Reach for it whenever precision or flag rate moves and you need to know *which
rule*. The CLI is CICIDS-specific, but the core is dataset-agnostic:

```python
# any DetectionResult + aligned 0/1 truth array works
from evaluation.rule_diagnostic import attribute
report = attribute(result, truth)   # dict: n_flagged/n_tp/n_fp, ml_only, per_rule
```

That is exactly how the CTU-13 attributions were produced. `--benign N`
shrinks the sampled benign background for a faster (less precise) run.

## 2. run_benchmarks.py — the tracked scoreboard

`uv run --extra eif python -m evaluation.run_benchmarks` runs every real-data
benchmark whose dataset exists under `data/` (absent ones **skip** cleanly,
never fail) and prints one table: `benchmark, tier, status, rows, base, flag,
recall, prec`, followed by a per-benchmark caveat line. Select subsets with
`--only cicids2017,ctu13,ctu13_sc3,unsw,bournemouth`.

Tier discipline (enforced in the script's registry and in
`evaluation/BENCHMARKS.md`; full policy in `bwl-validation-and-qa`):

| Tier | Members | How to read |
|---|---|---|
| `tracked` | CICIDS2017/Ares, CTU-13 sc1/Neris, CTU-13 sc3/Rbot | Real, externally labelled botnet captures. These are the numbers that mean something. |
| `secondary` | UNSW-NB15 (broad IDS, not a bot capture), Bournemouth web logs (domain-transfer, NEGATIVE result, licence-pending) | Breadth/transfer probes on a different footing; never compare like-for-like with tracked rows. |
| (never in table) | Synthetic suite | Stress test only, run via `pytest`. It plants exactly the signatures the rules look for, so a green run measures agreement with ourselves, not detection. |

Recorded numbers as of this writing (source: `evaluation/BENCHMARKS.md`,
recall/precision/flag): CICIDS 0.998/0.846/0.037; CTU-13 sc1 1.000/0.978/0.033;
CTU-13 sc3 0.985/0.929/0.034; UNSW 0.122/0.198/0.020; Bournemouth
0.474/0.020/0.681 (provisional, below base rate — an honest negative). Quote
caveats along with numbers; the caveat strings in the registry are part of the
result. Do not run the full suite casually — it is slow; use `--only` for the
benchmarks your change can plausibly touch.

## 3. RulesResult.thresholds — the detector's flight recorder

Every adaptive decision the rule layer made on a batch is written into
`result.rules_result.thresholds` (built in `bots_without_labels/rules.py
apply_rules`; persisted as `rule_thresholds` in `artifacts/summary.json`).
When a rule "mysteriously" fires or stays dormant, read this dict first.

| Key | Type | Meaning |
|---|---|---|
| `text_repeat` | `{column: int}` | Adaptive repeat-count threshold per eligible text column (99th percentile of distinct-value group sizes, floored at 10). Empty dict = no eligible text columns. |
| `categorical_concentration` | `{column: int}` | Same, for categorical concentration (floor 50); only columns with ≥ 20 distinct values are eligible. |
| `numeric_reuse` | `{column: int}` | Same, for exact numeric value reuse (floor 10). |
| `context_cluster` | int | Count threshold for the joint-context cluster rule (floor 50). |
| `same_instant` | int | Events sharing one timestamp needed for `same_instant_burst` (floor 4). |
| `local_burst` | int | Events in the 10-second window needed for `local_burst` (constant 5). |
| `timestamp_grid` | float or None | Inferred clock quantisation period in seconds (e.g. 60.0 for minute-quantised CICIDS). None = no coarse grid detected. |
| `dense_timing_gated` | bool | True when `timestamp_grid >= 10` (the burst window): same-instant/burst rules are suppressed per collision for ON-grid pile-ups (binning artefacts), while off-grid pile-ups still fire. The single most common answer to "why don't timing rules fire on this flow log". |
| `entity_columns` | list[str] | Columns `entity_monotony` baselines per-entity behaviour over, chosen by the actor cardinality-ratio band (0.02–0.5) — the fix that excluded degenerate `Proto`/`State`. Empty = rule dormant. |
| `entity_diversity_cut` | float | Adaptive low-tail diversity cut (10th percentile of qualified entities, ceiling 0.20). 0.0 = no entity qualifies; monotony cannot fire. |
| `entity_graph_active` | bool | True when ≥ 2 entity columns exist so hub degrees can be computed; then monotony escalates only on hubs. False with entity columns present = fallback: monotony fires on low diversity alone. |
| `min_hub_degree` | int or None | 3 when the entity graph is active (spokes a star needs), else None. |
| `actor_columns` | list[str] | Endpoint columns of the relational actor graph (chosen by shape, never by name; first one is the SOURCE by schema order). Empty = `asymmetric_degree` dormant. |
| `actor_graph_active` | bool | True when ≥ 2 actor columns produced a degree map. |
| `degree_floor` | float or None | Adaptive out-degree cut for `asymmetric_degree`: 99th-percentile of hub-subset degrees. None = no endpoint reaches hub degree 3; rule cannot fire. |

Reading pattern: `entity_columns == []` or `actor_graph_active == False`
explains a dormant graph rule (this is exactly the Bournemouth negative result:
the web `session_id` cardinality ratio fell below the actor band, so entity and
actor rules were dormant and only timing+ML ran). `dense_timing_gated == True`
explains missing burst fires on coarse-clock logs.

## 4. feature_deviations() and selected_events.json — reading ML-only flags

An ML-only flag has no rule reason, so `DetectionResult.feature_deviations(rows,
top_k=5)` (`bots_without_labels/anomaly.py`) turns it into readable evidence:
for each row, the features whose values sit furthest from the batch baseline,
computed in the SAME robust median/MAD space the anomaly model scores in — so
the explanation describes the deviations that actually drove the score. Each
entry:

| Field | Meaning |
|---|---|
| `feature` | Feature name (e.g. `dt__cv`, `SrcAddr__conc`, `entity__diversity`). |
| `value` | The row's raw feature value. |
| `robust_z` | Signed distance from the batch **median** in **MAD** units (MAD = median absolute deviation, a robust standard-deviation stand-in; see `bwl-detection-theory`). `-14` = far below typical; `+6` = far above. |
| `batch_percentile` | The value's rank within this batch in [0, 1], ties averaged. `>= 0.99` reads "top 1% of the batch"; `<= 0.01` bottom 1%. |

The CLI (`uv run python -m bots_without_labels run --input <log> --output-dir
run-output`) writes the same evidence to
`run-output/artifacts/selected_events.json`: the top flagged rows (max 500, by
combined score) each with `evidence_tier`, scores, up to 6 rule reasons, and
their top feature deviations. That file is the triage sample for a human
review queue; `predictions.tsv` holds the full decision set.

Never call these scores probabilities: they are batch-relative rankings.

## 5. Evidence tiers as an error-attribution tool

`DetectionResult.evidence_tier` encodes which classifier carried each flag:

| Tier | Meaning | Where to look next |
|---|---|---|
| 1 | Heuristic AND ML agree | Rule reasons (strongest flags) |
| 2 | Heuristic only | Rule reasons + `thresholds` dict |
| 3 | ML only — no rule reason | `feature_deviations()` — nothing else explains it |
| 0 | Not selected | — |

On a labelled benchmark, crossing tiers with truth is the fastest first cut of
error attribution: **tier-3 FPs are an ML-calibration problem; tier-1/2 FPs are
a rule problem.** On the tracked benchmarks the residual FPs are mostly or
entirely tier-3: on CTU-13 sc3 all 151 residual FPs are ML-only, and on CICIDS
~253 of 358 are ML-only with ~104 from `entity_monotony` (source:
`evaluation/FINDINGS.md`). So before touching any rule weight, check the tier
split — if the FPs are tier-3, no rule change can fix them.

## 6. trace_detection.py — one-command trace of any log

This skill ships a read-only tracer built ONLY on the public API
(`ingest.load`, `pipeline.detect`); it writes nothing and needs no labels.

```
uv run python .claude/skills/bwl-diagnostics-and-tooling/scripts/trace_detection.py <log> [--top N]
```

It prints, in order: the inferred schema (column roles), the decision state
(ML threshold + the `thresholds` highlights from section 3), per-rule fire
counts (all rows vs flagged rows), evidence-tier counts, and the top-N flagged
rows with rule reasons and top feature deviations.

Verified example (log from `uv run python -m bots_without_labels generate
--output /tmp/demo_log.tsv --legit 900 --bots 100 --seed 0`, then traced with
`--top 3`; output abridged to the first flagged row):

```
== Inferred schema =============================================
1000 rows, format=tsv  (timestamp=event_time; row_id=event_id; urls=url)
  event_id    identifier   unique=1000 missing=0
  event_time  timestamp    unique=971 missing=0
  ...
  url__q      text         unique=898 missing=0 <- url
  url__ttc    numeric      unique=883 missing=0 <- url

== Decision state (thresholds dict + ML threshold) =============
  decision: is_bot = heuristic >= 0.70 OR ml_score > ml_threshold
  ml_threshold=0.696541 (method=kneedle_descending, backend=eif)
  timestamp_grid = 2.0
  dense_timing_gated = False
  entity_columns = []
  entity_graph_active = False
  actor_columns = []
  actor_graph_active = False
  degree_floor = None
  ...

== Rule fire counts ============================================
  rule                      fired_rows  fired_in_flagged
  numeric_reuse                     75                48
  repeat_value                      75                48
  local_burst                       46                46
  regular_timing                    25                23
  same_instant_burst                25                25

== Evidence tiers ==============================================
  rows=1000  flagged=48  flag_rate=0.0480
  tier 1 (rules AND ml agree)                0
  tier 2 (rules only)                       46
  tier 3 (ml only — no rule reason)          2
  tier 0 (not selected)                    952

== Top 3 flagged rows (by combined score) ======================
  row 132: tier=2 heuristic=0.990 ml=0.568
    reason: url__q repeated 25 times
    reason: exact url__ttc value reused 25 times
    reason: dense local burst (5 events)
    reason: regular inter-arrival timing (cv 0.000)
    deviation: url__d__conc=3.258 robust_z=-14.25 batch_percentile=0.038
    deviation: dt__cv=0 robust_z=-6.41 batch_percentile=0.013
```

Also verified on a flow-shaped CSV (3,400 rows with `StartTime`/`SrcAddr`/
`DstAddr`/`Proto`/`TotBytes` columns and one planted source `147.32.84.165`
fanning out to 400 distinct destinations on a monotone service — same protocol
and byte count): the trace showed `actor_columns = ['SrcAddr', 'DstAddr']`,
`actor_graph_active = True`, `degree_floor = 25.02` (adaptive — it tracks *this*
batch's connectivity, so expect a different value on your data),
`entity_columns = ['SrcAddr']`, and `asymmetric_degree` firing on exactly the
400 planted rows, tier 2, with the full human-readable reason:

```
reason: SrcAddr '147.32.84.165' reaches 400 distinct counterparts as a
        source while only 0 reach it back, on a monotone service
        (context diversity 0.04 over 400 events)
```

(`dense_timing_gated` was `False` here because the microsecond timestamps give a
sub-second grid, finer than the 10-second burst window; it flips to `True` only
when a grid of ≥ 10 s is detected, e.g. minute-quantised CICIDS.)

Interpretation checklist when a trace surprises you:

- [ ] Schema roles right? A timestamp read as `categorical`, or an actor column
      read as `identifier`, silently disables whole rule families.
- [ ] `dense_timing_gated` True on a log you expected timing fires from?
      That is the coarse-clock gate, not a bug (see `bwl-architecture-contract`).
- [ ] Graph rules dormant? Check `entity_columns`/`actor_columns` emptiness and
      the cardinality-ratio band before suspecting the rules themselves.
- [ ] Many tier-3 flags? Read their deviations; consider the ML threshold
      method printed (`kneedle_descending`, possibly `+rate_capped` when the 2%
      ML-only flag-rate cap engaged).
- [ ] Remember: on an unlabelled log the trace explains decisions; it cannot
      tell you they are correct. Correctness claims need a labelled benchmark
      (sections 1–2) — see `bwl-validation-and-qa`.

## Provenance and maintenance

Authored 2026-07-06, repo at commit `8a85edd` (branch `main`). Every command
above was executed against that tree; both example traces are pasted from real
runs (the click-log one from `generate --seed 0`; the flow one from a
hand-built broadcaster fixture). Recorded benchmark/attribution numbers are
cited from `evaluation/BENCHMARKS.md` and `evaluation/FINDINGS.md`, not
re-measured here.

| Volatile fact | Re-verify with |
|---|---|
| Decision rule & cutoff 0.70, ML rate cap 2% | `grep -n "HEURISTIC_CUTOFF\|MAX_ML_FLAG_RATE" bots_without_labels/pipeline.py` |
| Tracked numbers (CICIDS 0.998/0.846/0.037 etc.) | `grep -n "0.846\|0.978\|0.929" evaluation/BENCHMARKS.md` |
| CICIDS residual split (~253 ML-only / ~104 entity_monotony of 358 FP) | `grep -n "253\|358" evaluation/FINDINGS.md` |
| Benchmark keys for `--only` | `uv run python -m evaluation.run_benchmarks --help` |
| `rule_diagnostic` CLI flags (`--zip`, `--benign`) | `uv run python -m evaluation.rule_diagnostic --help` |
| `thresholds` dict keys (section 3 table) | `grep -n 'thresholds\[' bots_without_labels/rules.py` |
| Deviation entry fields (`robust_z`, `batch_percentile`) | `grep -n "robust_z" bots_without_labels/anomaly.py` |
| Tier encoding (1/2/3/0) | `grep -n "_evidence_tiers" -A6 bots_without_labels/pipeline.py` |
| Dense-timing gate trigger (grid ≥ 10 s burst window) | `grep -n "burst_window_seconds\|timestamp_on_grid" bots_without_labels/features.py` |
| Tracer still runs end-to-end | `uv run python -m bots_without_labels generate --output /tmp/d.tsv && uv run python .claude/skills/bwl-diagnostics-and-tooling/scripts/trace_detection.py /tmp/d.tsv --top 1` |
| `selected_events.json` cap (500) and contents | `grep -n "MAX_SELECTED_EVENTS\|_write_selected" bots_without_labels/pipeline.py` |

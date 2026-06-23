# Roadmap

This roadmap captures planned work for Bots Without Labels. It is written for a
wide technical audience — engineers, data scientists, and reviewers — who need to
understand why a change matters before deciding whether to prioritise it.

The project works on **unlabelled** data. Items that involve probability,
precision, recall, or supervised learning must be treated carefully: until
trusted labels exist, the system estimates operational confidence but cannot
claim measured fraud accuracy. The synthetic label-injection workflow is the one
place where measured recall is honest, because there the ground truth is planted
on purpose.

| Priority | Meaning |
|---|---|
| P1 | Highest value. Improves correctness, explainability, or the core promise. |
| P2 | Important but less urgent. Improves robustness, stability, or coverage. |
| P3 | Future-facing. Useful when more data, labels, or external context exist. |

## Next Session (picked up 2026-06-23 PM)

Concrete follow-ups from the real-data evaluation (see `evaluation/FINDINGS.md`).
Per-entity baselining now recovers the CICIDS botnet (recall 0.022 → 0.998) but
precision is only 0.144: busy *legitimate* servers are as low-diversity as bots,
so the entity-monotony rule over-flags. These are the steps to take it further.

### A. Lift entity-monotony precision past the busy-benign ceiling (P1)

Diversity alone cannot separate a botnet host from a busy legitimate server —
only the shared C2 hub is uniquely separable. Add a *second discriminator* that
fires only when an entity is both monotonous **and** structurally bot-like:

- Sub-minute timing regularity, where timestamp resolution allows (a beacon has
  a regular cadence; a busy server does not). Couples with item 6.
- Relational structure: one external hub contacted by *many* monotonous sources.
  This is the graph view in item 9 — promote it from P3 for the entity case.
- Or a per-volume-stratified diversity baseline: compare a busy entity against
  other busy entities, not against the global tail.

### B. Calibrate the entity-monotony threshold (P1)

The cut is currently a fixed 10th-percentile with a 0.20 ceiling — recall 0.998
but a 21.9% flag rate. Try gap/knee detection on the entity-diversity
distribution, and add a heuristic flag-rate cap mirroring `MAX_ML_FLAG_RATE`.
Measure every change on the benchmark; do **not** tune to the single C2 hub.

### C. Grow the labelled real-data benchmark suite (P2)

`tests/test_real_benchmark.py` pins one attack family. Add the other CICIDS
families (PortScan, DDoS, web attacks, infiltration) and one non-network log,
each as a skip-if-absent benchmark, so recall/precision are tracked per attack
type and a regression cannot hide behind the synthetic suite. Extends item 10.

### D. Route the per-entity change through HCOM Codex review

The fix (commit 98646c1) was committed directly, bypassing the PM-commits-only
protocol. Have the ML-engineer-reviewer (Codex) review `features.py` / `rules.py`
before treating it as final.

### E. Minor robustness (P2/P3)

- Sanitise `Infinity` / `NaN` in numeric features *before* standardisation;
  results are already nan-guarded, but CICIDS flow data raises a numpy warning.
- Revisit integer-coded identifier inference: a `session ID` / numeric IP is
  typed numeric, so per-entity baselining and id handling miss it. Couples with
  the schema-override / entity-id hints in item 4.

## P1: Core Promise

### 1. Run the schema-driven engine end to end

The autodetecting loader and schema-driven features feed the rules and EIF
detector through a single generic pipeline, so any CSV/TSV/JSON log can be scored
without bespoke parsing.

- One pipeline entry point that takes a log path and returns predictions plus
  an explainable per-row score.
- Click-specific behaviour appears only when the relevant columns are detected,
  never as a hardcoded branch.

### 2. Richer label-injection archetypes

Synthetic bots planted into real traffic are how detection is measured without
labels. The injector should cover a spectrum of automation styles so recall is
reported per archetype, not just in aggregate.

- Burst, repeated query/domain, mechanically regular timing, low-entropy /
  nonsense strings, and slow-drip archetypes.
- Per-archetype recall and overall precision against the planted ground truth.

### 3. Explain ML-tail events with feature deviations

An anomaly score alone is not enough for a reviewer. For high-anomaly events,
store the top feature deviations from the batch baseline so an ML-only flag can
be read as "this value is in the top 1% of the batch", not an opaque tree path.

## P2: Robustness And Coverage

### 4. Broaden input parsing

- Gzip-compressed logs, schema overrides for ambiguous columns, and more
  timestamp formats.
- Optional user hints (which column is the timestamp / entity id) when
  autodetection is uncertain.

### 5. Robust scaling for heavy-tailed features

Log features are often heavy-tailed: a few values appear thousands of times while
most appear once. Compare standardisation with robust or quantile scaling and
keep whichever improves stability and explanation.

### 6. Rolling burst windows

The engine captures same-instant and context-local bursts. Add 1-second,
10-second, and 60-second rolling windows so automation that spreads clicks to
avoid exact same-second bursts is still visible.

### 7. Drift awareness across runs

Thresholds are batch-relative, which suits a self-contained log but benefits from
historical context in production.

- Save compact run history: flagged rate, score quantiles, top reasons.
- Warn when traffic or score distributions drift sharply between runs.

### 8. Optional domain reputation signals

When a log carries domains, an offline, versioned blocklist can add context. A
match should raise risk and be recorded in the explanation, but never decide the
outcome on its own.

## P3: Needs More Evidence Or External Context

### 9. Graph features on stable identifiers

When stable links such as IP, user, or account exist, build a graph over shared
identifiers to surface coordinated behaviour that per-event signals miss
(shared-identifier fan-out, connected-component size, repeated edges). Keep it
optional and disabled when no stable identifier is present.

### 10. Labelled validation and cost-sensitive thresholds

With trusted labels, the system can move from operational confidence to measured
precision/recall and a cost-aware operating point. Calibrate anomaly scores into
probabilities (e.g. isotonic regression or Platt scaling) on a validated holdout,
then choose a threshold from explicit error costs:

```text
tau = C_FP / (C_FP + C_FN)
```

where `C_FP` is the cost of flagging legitimate traffic and `C_FN` the cost of
missing automated traffic. This must not be applied to raw anomaly scores, which
are rank-order signals, not calibrated probabilities.

### 11. Optional live reputation providers

Live threat-intelligence providers could strengthen detection when credentials
and usage terms allow. Keep them optional and disabled by default, never require
credentials to run the project, and cache unique-entity lookups rather than
calling per event.

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

## Shipped (roadmap items closed as of 2026-07-06)

Kept as one-liners so the open items below stay readable; the full measured
story of each arc lives in `evaluation/FINDINGS.md` and `evaluation/BENCHMARKS.md`.

- **Per-entity baselining + relational hub gate** — CICIDS recall 0.022 → 0.998;
  the busy-benign precision ceiling (old items A/B) was closed by the hub gate
  plus timing calibration (`e6ded7a`): CICIDS 0.998 / 0.846 / flag 0.037.
- **Actor graph / `asymmetric_degree`** (`2a3f362`) — recovers the diverse
  directional bot (CTU-13 Neris recall 0.113 → 1.000, 2000/2000, zero false fires).
- **CTU-13 over-flagging root-caused and fixed** (`56f305d`) — the ~0.041
  precision was `entity_monotony` baselining degenerate `Proto`/`State` columns;
  the actor cardinality-ratio band now gates entity columns too. Precision
  0.041 → 0.978, flag 0.785 → 0.033, recall held at 1.000; CICIDS unregressed.
- **Generality beyond Neris proven** (`13e9436`) — CTU-13 sc3 / Rbot: recall
  0.985 generalised immediately; the fan-in false-positive risk materialised
  exactly as predicted and was fixed by narrowing the rule to source fan-out
  (precision 0.056 → 0.929, no thresholds tuned).
- **ML-tail sentinel decouple** (`ef92510`) — the sparse-timing sentinel
  (`SPARSE_TIMING_SENTINEL = 999`) no longer pollutes the EIF feature matrix
  (median-fill of the `dt` axes plus a `has_regular_timing` indicator); the
  `regular_timing` rule is byte-identical. CICIDS 0.846 → 0.879, flag 0.037 → 0.036
  (ML-only false positives ~253 → 165); CTU-13 sc1 0.978 → 0.971; sc3 0.929 → 0.9319;
  all recalls flat. The "drop `dt` entirely" variant was rejected (CTU -4.8 pts).
- **Benchmark suite grown** (old item C, now done) — CTU-13 sc1 + sc3,
  UNSW-NB15 (secondary), Bournemouth web logs (honest negative transfer), all
  skip-if-absent behind one runner (`evaluation/run_benchmarks.py`) and a shared
  harness (`evaluation/harness.py`). The remaining CICIDS attack families were
  closed by follow-up F (2026-07-12, below).
- **`Infinity`/`NaN` sanitised before standardisation** (old item E, first
  bullet) — see the non-finite handling in `features.py`.
- **Items 1 and 2 (P1 core)** — the schema-driven end-to-end pipeline and the
  per-archetype label-injection suite are the shipped foundation of the repo.
- **Item 3 (P1)** — ML-tail flags now carry their top feature deviations
  (robust z + batch percentile) in `selected_events.json` and via
  `DetectionResult.feature_deviations()`, so a tier-3 flag reads as "this value
  is in the top 1% of the batch".

## Open follow-ups

### F. Add the remaining CICIDS attack families as benchmarks (P2)

The rest of old item C: PortScan, DDoS, web attacks, infiltration are in the
same `GeneratedLabelledFlows.zip` already used by the Ares benchmark, and the
shared harness makes each family mostly a `build_mix` + spec. Tracks
recall/precision per attack type so a regression cannot hide behind the
synthetic suite. Extends item 10.

*Status: closed (2026-07-12).* Six secondary attack-coverage probes
(`cicids_portscan`, `cicids_ddos`, `cicids_webattacks`, `cicids_infiltration`,
`cicids_bruteforce`, `cicids_dos`) run skip-if-absent through
`evaluation/run_benchmarks.py`, guarded by `tests/test_cicids_family_benchmark.py`,
with predictions recorded before measurement and surprises attributed via
`rule_diagnostic` (ML change reviewed with no blockers). Measured and registered in
`evaluation/BENCHMARKS.md` (story in `evaluation/FINDINGS.md`): PortScan
1.000/0.585, DDoS 1.000/0.786, BruteForce 1.000/0.168 (recall/precision), alongside
three first-class weak results — WebAttacks recall 0.000, DoS precision 0.008
(below the 0.032 base rate), Infiltration precision 0.002 on 36 positives. These
are attack-coverage measurements, not bot-detection results. The over-firing
single-entity-column monotony fallback they exposed is follow-up L (whose fix has
since moved the fallback-row numbers — see L below for the before/after).

### G. Route direct-to-main engine commits through HCOM Codex review (process)

Several engine changes were committed directly to `main`, bypassing the
PM-commits-only protocol and the cross-model ML-engineer review it requires.
Retroactive ML-engineer (Codex) reviews have now recorded an outcome for each:

- `98646c1` — per-entity baselining + CICIDS benchmark (`features.py` /
  `rules.py`). Reviewed and closed (2026-07-12): approved with no blocking
  findings.
- `543129a` — constants extraction, tuning-param exposure, docstrings across
  `bots_without_labels/*.py`. Reviewed and closed (2026-07-12): approved with
  no blocking findings; residual risk noted that the full historical
  bit-identical benchmark set was not rerun.
- `fc4e3c7` — ML-tail feature deviations (`anomaly.py` / `pipeline.py`).
  Reviewed (2026-07-12): one attribution-wording blocker found, resolved by a
  wording-only fix in `bots_without_labels/anomaly.py` and
  `bots_without_labels/pipeline.py`, then approved with no blocking findings.

*Status: closed (2026-07-12).* All three commits retroactively reviewed as
above. The reviews clear process debt on these specific commits; benchmark
figures cited in them are measurements on labelled captures, not evidence of
production precision.

### H. Integer-coded identifier inference (P2/P3)

Old item E, second bullet: a `session ID` / numeric IP is typed numeric, so
per-entity baselining and id handling miss it. Couples with the
schema-override / entity-id hints in item 4.

### I. Actor-selection residuals from the scale-invariant fix (P2/P3)

The scale-invariant actor selection (recurrence + repeat-mass + value shape,
replacing the cardinality-ratio band) left two known residuals, both value-shape
edge cases:

- **Short unstructured actor ids.** A *closed* pool of short, non-identifier-shaped
  values — bare integers, usernames, mnemonic hostnames — is frequency- and
  shape-ambiguous vs a bounded enum vocabulary, so it is not detected as an actor.
  Overlaps item H (integer-coded identifiers).
- **Raw content columns.** URL and URL-derived columns are excluded
  (`_is_content_column`), but a *raw* request-`path` field (non-URL-typed content) is
  still admitted as a pseudo-actor and over-flags on web logs (visible in the
  Bournemouth secondary result). Generic content-column detection without value
  semantics is the open problem; couples with item 12.

### J. Drift checker: flag citations of removed constants (P3)

`.claude/skills/bwl-docs-and-writing/scripts/check_golden_numbers.py` flags a skill
that cites a constant with the *wrong value*, but not one that cites a constant which
no longer exists in source (it builds its constant set *from* source). Removing
`ACTOR_MIN_RATIO`/`ACTOR_MAX_RATIO` in the scale-invariance fix left stale skill
references the checker did not catch. Add a check that flags skill citations of an
`UPPER_SNAKE = value` constant name absent from the source modules.

*Status: closed (2026-07-13).* The checker now also flags a skill citing a
claim-shaped `UPPER_SNAKE` constant (`NAME = value`, `NAME (value)`, or a
`| NAME | value |` table row) whose name no longer exists in source — the
`ACTOR_MIN_RATIO` class. Scope is deliberately narrow: skill drift in
`.claude/skills/*/SKILL.md` only (`evaluation/FINDINGS.md` narrates dead constants
historically by design), with precision-first exclusions for env/tooling/command
lines and bare name mentions; a line carrying explicit historical wording
(*removed, replaced, superseded, deprecated, …*) is intentionally never flagged,
so recorded history stays writable. Reviewed with no blockers: `--self-test`
passes all 9 built-in fixtures, an independent negative control
(`ACTOR_MIN_RATIO = 0.02` cited as current) is flagged while the existing
historical references stay unflagged, and the full run over 16 skills ends
VERDICT clean.

### K. Feature-build vectorisation at production scale (P3, parked)

`build_features` is ~13.5s on the 62k CICIDS mix (linearly ~3.6 min at 1M rows),
of which `_entity_baseline` + `_actor_graph` are ~56%. Profiling showed the named
per-row Python loops are only 0.5% of the cost; 99% is entropy-per-group
(~97k `np.unique`/Shannon-entropy calls). A groupby-vectorised entropy is 3.0×
faster but drifts 4.4e-16 (**not bit-identical** → a behaviour change, not a
refactor); the bit-identical variant is *slower* (0.58×). So there is no
speedup that also rides the behaviour-preservation diff gate. **Re-entry
trigger:** a genuine ~1M-row / full-day workload. **Then:** ship the
groupby-vectorised entropy on the behaviour-change track (full benchmark
no-regression, not bit-identical), targeting the two entropy loops only; note the
EIF fit is subsample-bounded (`sample_size=min(4096, n)`) so scoring, not fitting,
is the co-equal cost and feature-build can only reach ~half of end-to-end. Full
measurements in `evaluation/FINDINGS.md`, "Vectorising the feature-build loops".

### L. Decide whether to gate the single-entity-column monotony fallback (P2, decision needed)

The CICIDS attack-family probes (follow-up F) showed that when a capture qualifies
only **one** entity column, `entity_monotony`'s low-diversity fallback runs without
the hub gate and fired on 7,500–9,600 benign rows per 62k mix (13–19% flag rates,
fire precision 0.000–0.175 on those mixes) — the driver of the WebAttacks and DoS
at-or-below-chance precisions. Whether to gate or calibrate the fallback is an
**engine change** with regression risk to captures where that same fallback carries
recall (it alone caught the BruteForce burst), so it needs the full
predict–attribute–verify loop and cross-model review. It was deliberately not
touched in the measurement-only follow-up F pass; evidence in
`evaluation/FINDINGS.md`, "Attack-family coverage: the rest of CICIDS2017".

*Status: implemented and reviewed (2026-07-13) — awaiting human owner merge
approval; not yet landed.* The two-phase, evidence-first arc ran to completion:
Phase 1 attributed every fallback fire (floods are point-to-point channels, the
BruteForce recall sits entirely on hub-shaped entities) and Phase 2 re-applies the
existing structural hub gate (`MIN_HUB_DEGREE = 3`) inside the fallback regime via
actor-derived counterpart degree, keeping the bare fallback where no counterpart
structure is derivable (`bots_without_labels/rules.py` + tests only, branch
`agent/followup-l-phase2-fallback-hub-gate`, ML review approved with no blockers).
Predictions recorded before implementation matched the verified re-runs at
displayed precision: BruteForce precision 0.168 → 0.600 with recall held 1.000,
WebAttacks flag 0.158 → 0.005 (recall still 0.000), Infiltration precision
0.002 → 0.053, DoS precision 0.008 → 0.046 at flag 0.160 → 0.028 (still weak); all
seven non-fallback registry rows unchanged. Because the change moves flag
decisions, landing is held for explicit human owner approval. Full story in
`evaluation/FINDINGS.md`, "The fallback hub gate"; before/after registry detail in
`evaluation/BENCHMARKS.md`.

## P1: Core Promise

### 1. Run the schema-driven engine end to end

The autodetecting loader and schema-driven features feed the rules and EIF
detector through a single generic pipeline, so any CSV/TSV/JSON log can be scored
without bespoke parsing.

- One pipeline entry point that takes a log path and returns predictions plus
  an explainable per-row score.
- Click-specific behaviour appears only when the relevant columns are detected,
  never as a hardcoded branch.

*Status: shipped.* `run_pipeline()` / `detect()` are the single entry points;
every benchmark and test runs through them.

### 2. Richer label-injection archetypes

Synthetic bots planted into real traffic are how detection is measured without
labels. The injector should cover a spectrum of automation styles so recall is
reported per archetype, not just in aggregate.

- Burst, repeated query/domain, mechanically regular timing, low-entropy /
  nonsense strings, and slow-drip archetypes.
- Per-archetype recall and overall precision against the planted ground truth.

*Status: shipped.* Four archetypes (two deliberately evasive) in
`synthetic.py` / `inject.py`, with per-archetype recall via
`evaluate_injection()`; custom signatures injectable via
`generate(signatures=...)`.

### 3. Explain ML-tail events with feature deviations

An anomaly score alone is not enough for a reviewer. For high-anomaly events,
store the top feature deviations from the batch baseline so an ML-only flag can
be read as "this value is in the top 1% of the batch", not an opaque tree path.

*Status: shipped (2026-07-04).* `anomaly.feature_deviations()` reports the top
robust-z deviations (with batch percentiles) in the same median/MAD space the
model scores in; surfaced per selected event in `selected_events.json` and via
`DetectionResult.feature_deviations()`. Motivated by the benchmarks: after rule
calibration, all residual false positives were tier-3 (ML-only) flags.

## P2: Robustness And Coverage

### 4. Broaden input parsing

- Gzip-compressed logs, schema overrides for ambiguous columns, and more
  timestamp formats.
- Optional user hints (which column is the timestamp / entity id) when
  autodetection is uncertain.

### 5. Robust scaling for heavy-tailed features — DONE (measured-negative)

Log features are often heavy-tailed: a few values appear thousands of times while
most appear once. Compare standardisation with robust or quantile scaling and
keep whichever improves stability and explanation.

Resolved. Robust (median/MAD) scaling is already applied in
`anomaly._robust_standardize`. The remaining option — a nonlinear quantile-rank of
the numeric `__val` columns — was probed on CICIDS across four seeds and is a
**measured wash**: precision Δ swings ±0.2 on the sampling seed alone (sign not
stable), swamped by the intrinsic variance of the rate-capped EIF tail. See
`evaluation/FINDINGS.md`, "Quantile-ranking the numeric value features". Not
shipped; no reliable improvement to keep.

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

*Status: largely delivered.* Two graph signals now exist — the relational hub
gate on `entity_monotony` (fan-in stars) and the source-fan-out
`asymmetric_degree` rule on the actor-endpoint graph, both dormant when no
stable endpoint columns are present. Validation on a second labelled family is
**done** (CTU-13 sc3 / Rbot — see the Shipped section). See
`evaluation/FINDINGS.md`. Still open: connected-component size and
repeated-edge weighting.

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

### 12. Web-behavioural / interaction-biometric signals for human-mimicking web bots

The current detector targets **mechanical automation and network botnets** — it
keys on repetition, concentration, behavioural monotony, and timing regularity.
The Bournemouth web-log evaluation (see `evaluation/FINDINGS.md`) showed this does
**not** transfer to *evasive, human-mimicking web bots*: their diversity, timing
coefficient-of-variation, request entropy, and volume **overlap** with real humans,
so the signals the engine measures cannot separate the two. The Phase-1 diagnosis is
concrete — even forcing `session_id` to be the actor entity, `entity_monotony` caught
**0 of 11** bot sessions and flagged monotone humans, and overall precision sat
*below* the base rate.

This is a **method limit, not a calibration**: no threshold or entity-selection
change closes it. A future capability would need **web-specific behavioural signals**
the current rules do not model — for example **mouse dynamics / interaction
biometrics**, page-sequence / navigation modelling, or keystroke cadence. Bournemouth
ships **mouse-movement data**, which gives a ready validation source. This is a
**separate research direction** — likely supervised or biometric, and probably its
own pipeline — **not** a tweak to the existing unsupervised rules. Treat it as
exploratory until trusted labels and the extra signal streams exist.

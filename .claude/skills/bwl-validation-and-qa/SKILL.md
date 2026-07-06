---
name: bwl-validation-and-qa
description: Load when deciding whether a number is citable, what tier a result belongs to, or how to add a test/benchmark that guards a win. Triggers — "is this result real?", "can I put this in the registry?", "why is precision not pinned?", "add a benchmark / regression test", synthetic vs real-data confusion, planted_precision meaning, editing evaluation/BENCHMARKS.md or FINDINGS.md, touching tests/test_real_benchmark.py / test_ctu13*_benchmark.py / test_pipeline.py / tests/conftest.py, notebook output validation, or claims like "recall 1.0" that need a tier and caveat.
---

# Validation and QA: what counts as evidence here

This project has **no CI and no ground truth in production** — the running detector
sees unlabelled logs and *cannot measure its own accuracy*. Every citable number
comes from one of two places: a **synthetic stress test** (we plant the bots) or a
**real externally-labelled capture** (someone else labelled the bots). The whole job
of this skill is keeping those two straight and keeping the numbers honest. A number
in the wrong tier, or quoted without its caveat, is a defect as real as a code bug.

Jargon is defined at first use; deeper domain/theory background lives in
`netflow-botnet-reference` and `bwl-detection-theory`.

## When NOT to use this skill

| If you are… | Use instead |
|---|---|
| Running the environment / CLI / where artefacts land | `bwl-build-run-operate` |
| Reading a *tool's* output (rule_diagnostic, benchmark runner, feature deviations) | `bwl-diagnostics-and-tooling` |
| Deciding if a change is allowed / who commits / review pairs | `bwl-change-control` |
| Chasing a live failure by symptom | `bwl-debugging-playbook` |
| Wanting the *history* of a rejected fix or dead end | `bwl-failure-archaeology` |
| Deciding what may be claimed *externally* / licence / novelty | `bwl-external-positioning` |
| Raising the evidence bar for a *new research idea* (predict-before-run) | `bwl-research-methodology` |
| Writing the prose of a docs-of-record entry | `bwl-docs-and-writing` |

This skill is the **evidence contract**: tiers, the golden-number inventory, and how
to add a guard. It stops where "how to phrase it" (docs) or "am I allowed" (change
control) begins.

---

## 1. The tier system — four footings, never mixed

Every measured result sits in exactly one tier. The tier decides where it may appear
and how it must be read.

| Tier | What it is | Registry row in BENCHMARKS.md? | Citable as bot-detection accuracy? |
|---|---|---|---|
| **synthetic** | The generator plants exactly the signatures the rules look for. `~1.0` recall by construction — detector and benchmark share one assumption. | **No — never.** | **No.** Necessary-but-not-sufficient sanity gate only. |
| **tracked** | Real, externally-labelled capture; a *rare-attack mix* (mostly benign + a small intact slice of one labelled botnet ≈ 3%). | **Yes** — this is what earns a row. | Yes, *as ranking under uncertainty on that one capture*, never as a fraud verdict. |
| **secondary** | Real & labelled but a *broad-IDS* mix (many attack families, not one botnet) — e.g. UNSW-NB15. | Yes, flagged secondary; not comparable like-for-like. | **No** — read as a generality probe, not a bot result. |
| **provisional** | Real & labelled but licence-pending / tiny positive set — e.g. Bournemouth (11 bot sessions, licence unclear). | Yes, marked provisional / local-internal. | **No** — not cleared for publication; qualitative signal only. |

Ground-truth phrasing from `evaluation/BENCHMARKS.md` lines 11–19:

> Synthetic numbers are a stress test only… A green synthetic run is necessary but
> never sufficient, and its numbers do not belong in this registry.
> Only externally-labelled real data earns a row here.

**The synthetic suite's success criterion is inverted from what you'd guess.** The
evasive archetypes (`diffuse_replay`, `stealth`) are supposed to stay *missed*. If a
change started "catching" them, `tests/test_pipeline.py::test_pipeline_recovers_planted_bots`
would **FAIL** (see the self-calibrating assertion in §3). Catching the evasive plants
means the detector is now flagging behaviour indistinguishable from legitimate — that
is the failure mode, not a win.

> **A note on the code's own `tier` field.** `evaluation/run_benchmarks.py` tags each
> benchmark with a coarse 2-value `tier` (`"tracked" | "secondary"`). It codes
> Bournemouth as `"secondary"` and CTU-13 sc3 as `"tracked"`. The **documentary**
> vocabulary in BENCHMARKS.md is finer (synthetic / tracked / secondary / provisional,
> plus "generality probe"). When they disagree, **BENCHMARKS.md is authoritative** for
> how a number may be cited; the code field is only a display grouping.

---

## 2. Evidence rules (with the quote that anchors each)

These are the recurring ways a number gets mis-stated in this repo. Each has a source.

| Rule | What it means | Anchor |
|---|---|---|
| **Measured, not tuned** | State whether detector thresholds were tuned for the result. If they were not, say so — it is stronger evidence. | Rbot fix "verified end-to-end with **no detector thresholds tuned**" (BENCHMARKS.md 277–279; FINDINGS.md 365) |
| **Verified beats projected** | A per-rule *counterfactual projection* (arithmetic on a diagnostic) is not a measurement. When a projection and a re-run pipeline number disagree, **cite the pipeline number.** | CTU-13 sc1 projection **0.956** vs verified **0.978** — "0.978 is the number to cite" (FINDINGS.md 262–265; BENCHMARKS.md 213) |
| **`planted_precision` is a lower bound** | Precision is measured only against the *planted* positives. Unplanted rows the detector flags count *against* it even if they are genuine background bots. Never present it as true precision. | `bots_without_labels/evaluate.py` 5–7, 33 |
| **No-regression ≠ positive proof** | Holding an existing gate is evidence a capability *stayed*, not that a *new* one generalises. The fan-in (many→one) case is only *guarded* by CICIDS no-regression, **not** proved. | BENCHMARKS.md 289–295 ("guarded, not proved") |
| **Second independent family before generality** | A win on the family the rule was built against is same-family evidence. Claim generality only after a *second, independently-labelled* family. sc1/Neris → sc3/Rbot supplies the second. | BENCHMARKS.md 215–220, 232–236 |
| **Qualitative-only on tiny positive sets** | With a handful of positives (Bournemouth: **11 bot sessions**) recall/precision are not statistically robust — report the *direction*, not the digits. | BENCHMARKS.md 455–459 |
| **Precision-below-base-rate = worse than chance** | If precision < base rate, a flagged row is *less* likely a bot than a random row. State it plainly; do not bury it. | Bournemouth 0.020 precision < 0.029 base rate (BENCHMARKS.md 461–462) |
| **Never a fraud verdict / never a probability** | Scores rank "unusual relative to this batch". Not a label, not a probability of fraud. | BENCHMARKS.md 19, 159–163 |

---

## 3. Golden-number inventory

The current registry numbers, how to reproduce each, and the **test that pins it** so
a silent regression fails the suite even when synthetic stays green. Numbers are from
`evaluation/BENCHMARKS.md` (2026-07-04 branch, commit 8a85edd); re-verify with the
commands in Provenance.

| Dataset (tier) | Recall / Precision / Flag | Base rate | Reproduce (needs gitignored data) | Guarding test → **pinned bound** |
|---|---|---|---|---|
| **CICIDS2017 / Ares** (tracked, fan-in C2) | 0.998 / 0.846 / 0.037 | 0.032 | `uv run --extra eif python -m evaluation.cicids_bot_benchmark --zip data/GeneratedLabelledFlows.zip` | `tests/test_real_benchmark.py` → recall ≥ 0.95, `planted_precision` ≥ 0.35 **and** > base_rate, flag_rate ≤ 0.12 |
| **CTU-13 sc1 / Neris** (tracked, fan-out) | 1.000 / 0.978 / 0.033 | 0.032 | `uv run --extra eif python -m evaluation.ctu13_bot_benchmark` | `tests/test_ctu13_benchmark.py` → `conftest.assert_ctu13_rare_attack_recall` (below) |
| **CTU-13 sc3 / Rbot** (tracked / generality probe) | 0.985 / 0.929 / 0.034 | 0.0323 | `uv run --extra eif python -m evaluation.ctu13_bot_benchmark --scenario sc3` | `tests/test_ctu13_sc3_benchmark.py` → same `assert_ctu13_rare_attack_recall`; **plus** a no-data label guard `test_scenario_label_does_not_mislabel_binetflow_override` |
| **UNSW-NB15 shard 1/4** (secondary, broad IDS) | 0.122 / 0.198 / 0.020 | 0.032 | `uv run --extra eif python -m evaluation.run_benchmarks --only unsw` | *No pinned bound* — secondary breadth check, skip-if-absent only |
| **Bournemouth web logs** (provisional, negative) | 0.474 / 0.020 / 0.681 | 0.029 | `uv run --extra eif python -m evaluation.bournemouth_benchmark` | `tests/test_bournemouth_benchmark.py` → shape + valid-range only (no quality floor); parse/mapping guard always runs |

### The CTU-13 shared guard (`tests/conftest.py::assert_ctu13_rare_attack_recall`)

Every CTU-13 scenario funnels through one helper (conftest.py 90–111). It pins:

| Assertion | Value | Why |
|---|---|---|
| `report["n_rows"] == 62_000` | 62,000 rows | the intended rare-attack mix size |
| `0.02 <= base_rate <= 0.05` | ~3% minority | a *realistic rare* attack, not a majority class |
| `timestamp_grid_seconds is not None and < 1.0` | sub-second | proves microsecond clock (contrast CICIDS 60 s) |
| `dense_timing_gated is False` | timing rules **active** | the CTU-13 premise: dense-timing rules engage here |
| `recall >= 0.95` | the recall win | the one metric each CTU-13 guard exists to pin |
| recall/planted_precision/flag_rate ∈ [0,1] | sanity | valid-range guard |

**Precision is deliberately NOT pinned on any CTU-13 guard.** Reasoning (conftest.py
95–97; test_ctu13_benchmark.py 18–25): the recall win is carried by `asymmetric_degree`
(a clean 2,000/2,000 zero-false-fire catch on Neris), but *overall* precision has at
times been capped by a **separate** rule's behaviour. Pinning overall precision here
would lock in an unrelated limit and flake when that other rule is calibrated. The
recall guard is the load-bearing one; precision is tracked in the registry, not the
test. (On sc3 the same reasoning holds — the direction-agnostic `asymmetric_degree`
over-fired; precision is a tracked generality gap, not a pinned bound.)

### The synthetic guard (`tests/test_pipeline.py::test_pipeline_recovers_planted_bots`)

Two floors plus one self-calibrating assertion (test_pipeline.py 87–104):

- **Detectable archetypes** (`DETECTABLE_ARCHETYPES = ("burst", "mechanical_timing")`):
  `per[name]["recall"] >= 0.85` each.
- **Planted precision floor**: `report["planted_precision"] >= 0.9`.
- **Evasive-below-detectable (self-calibrating)**: every evasive archetype
  (`diffuse_replay`, `stealth`) must recall *strictly below* the worst detectable one —
  `all(per[name]["recall"] < floor for name in hard)`. No magic number: it documents
  the designed gap without a brittle constant, and **fails if evasive plants start
  being caught** (the inverted success criterion from §1).

`test_decision_contract_holds` (test_pipeline.py 26–35) separately pins the decision
rule itself: `is_bot == (heuristic >= HEURISTIC_CUTOFF) | (ml_scores > ml_threshold)`
and `0 <= combined <= 1`. `test_run_is_deterministic` pins reproducibility.

---

## 4. How to add a guard

### Add a unit test

1. **Reuse the conftest factories.** `network_log_factory` (a hub + point-to-point
   monotone channel + diverse filler) and `broadcaster_log_factory` (one source → 90
   destinations, the fan-out shape) build the canonical flow structures — do not
   hand-roll new ones. For the synthetic pipeline use `synthetic.generate(...)` with an
   explicit `seed`.
2. **Be hermetic and deterministic.** No network, no reliance on a gitignored dataset
   (those belong in skip-if-absent benchmark guards, below). Write to `tmp_path`. Every
   generator/pipeline call takes a fixed `seed`; there is a dedicated determinism test
   pattern (`test_run_is_deterministic`, `test_deterministic`) — mirror it if your
   feature has a stochastic component.
3. **Assert behaviour, not a frozen internal number.** Pin the *win* (a recall floor, a
   contract, an ordering) with a bound that "sits comfortably under the observed value
   so normal sampling jitter does not flake the guard" (test_real_benchmark.py 32–35).
4. Run the narrow selection: `uv run pytest tests/test_<yourfile>.py -q`.

### Add a real-data benchmark

1. **Build the mix, score through the shared tail.** Write a module in `evaluation/`
   whose dataset-specific code returns `(frame_without_label, truth_array)` for a
   *rare-attack mix* (~3% base rate). Hand it to `evaluation.harness.score_mix(frame,
   truth, mix_name=...)` — it round-trips through a temp CSV and the **real** `load()`
   so schema inference is part of what you measure (harness.py 34–66). Use
   `harness.DEFAULT_SEED = 7` (fixed, shared — reproducible across benchmarks).
2. **The frame must never contain the label.** `score_mix` scores `frame`; `truth` is
   held out. Passing the label column in leaks ground truth.
3. **Skip-if-absent.** Guard on the data path with
   `pytest.mark.skipif(not Path(DEFAULT_ZIP).exists(), reason=...)` and make the CLI
   `main()` exit 0 with a skip message when the file is missing (see
   `test_bournemouth_benchmark.py::test_main_skips_when_zip_absent`). Data is gitignored
   and never redistributed.
4. **Assign a tier and write the caveat.** Decide tracked / secondary / provisional per
   §1 and carry a one-line caveat in the benchmark `notes=` (harness.format_report
   appends them under a `note:` prefix). A secondary/provisional result with no caveat
   is not shippable.
5. **Register it in two docs of record.** Add a **row to `evaluation/BENCHMARKS.md`**
   (source, licence, timestamp resolution, entity columns) and a **narrative entry to
   `evaluation/FINDINGS.md`** (why the number is what it is). Add it to
   `evaluation.run_benchmarks.BENCHMARKS` so `--only <key>` and the combined table pick
   it up. All doc edits and any commit go through `bwl-change-control` (the HCOM review
   path — never commit around it).
6. **Pin the win in a test** if it is tracked (recall floor at minimum; precision only
   if it is genuinely stable and load-bearing — see the CTU-13 reasoning in §3).

### What a green suite does and does NOT prove

| A passing `uv run pytest` (the full suite) proves | It does NOT prove |
|---|---|
| The decision contract, determinism, and synthetic floors hold | Any field-accuracy number (synthetic is a stress test) |
| Every *locally present* real benchmark still clears its pinned bound | Anything about benchmarks whose data is absent — they **skipped** silently |
| Evasive plants stay uncaught (the inverted criterion) | Generality to unseen bot families or domains |
| pylint 10/10, black clean (separate local gates) | That precision generalises where only recall is pinned |

Because the tracked guards **skip** when their gitignored data is absent, a green
suite on a fresh checkout can be green *with zero real-data benchmarks having run*.
Confirm they ran (not skipped) before treating a real number as re-verified —
`uv run --extra eif python -m evaluation.run_benchmarks` prints `N ran, M skipped`.

---

## 5. Notebook validation

`notebooks/bots_without_labels.ipynb` is a doc-of-record artefact, so its **rendered
outputs are claims** subject to the same discipline.

- **Execute top-to-bottom** (Restart & Run All), never cell-by-cell — stale kernel
  state produces numbers no reproduction can match.
- **Verify every rendered number against a source** (a benchmark run or BENCHMARKS.md).
  A hard-coded or drifted output cell is a mis-stated result.
- **No synthetic number presented as accuracy.** If a cell runs the synthetic suite,
  its output must be framed as a stress test, not a field metric (§1).
- **Re-run after any pipeline change** that could move an output; commit the notebook
  and the number source together, through change control.

---

## Provenance and maintenance

Authored 2026-07-06. Repo at commit `8a85edd` (`git rev-parse HEAD` to check drift).
All numbers below are from `evaluation/BENCHMARKS.md` on that branch and are **measured
on gitignored local data** — treat them as the recorded scoreboard, not a live re-run.

| Volatile fact | One-line re-verification |
|---|---|
| Suite collects and passes | `uv run pytest --collect-only -q 2>/dev/null \| tail -1` |
| Full suite / lint gates green | `uv run pytest -q && uv run pylint bots_without_labels && uv run black --check .` |
| CICIDS guard bounds (recall≥0.95, prec≥0.35, flag≤0.12) | `grep -n "planted_precision\|recall\|flag_rate" tests/test_real_benchmark.py` |
| CTU-13 shared guard (62k rows, base 0.02–0.05, grid<1, recall≥0.95, no precision pin) | `sed -n '90,112p' tests/conftest.py` |
| Synthetic floors + evasive-below-detectable assertion | `sed -n '87,104p' tests/test_pipeline.py` |
| `DETECTABLE_ARCHETYPES` = burst, mechanical_timing | `grep -n "DETECTABLE_ARCHETYPES\|^ARCHETYPES" bots_without_labels/synthetic.py` |
| `planted_precision` is a lower bound | `sed -n '1,8p' bots_without_labels/evaluate.py` |
| Registry rows & numbers (5 datasets) | `sed -n '43,49p' evaluation/BENCHMARKS.md` |
| Runner tiers & `--only` keys | `grep -n "key=\|tier=" evaluation/run_benchmarks.py` |
| 0.956 projection vs 0.978 verified | `grep -n "0.956\|0.978" evaluation/FINDINGS.md` |
| Decision rule contract | `grep -n "HEURISTIC_CUTOFF\|ml_threshold" tests/test_pipeline.py` |

Change control for any edit here or to the docs of record: `bwl-change-control`
(HCOM review path is canonical — never commit around it).

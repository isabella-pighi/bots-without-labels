---
name: bwl-proof-and-analysis-toolkit
description: >
  First-principles analysis recipes for the Bots-Without-Labels detector — "prove it, don't just install
  it". Load this when you need to ATTRIBUTE which rule causes a precision drop, decide whether a feature
  can ever separate two classes (oracle-ceiling), ablate a rule without editing code, sweep a guardrail
  constant to learn where behaviour breaks, build the smallest synthetic log that isolates one structure,
  write a predicted number down before running, or prove a refactor changed nothing. Triggers: "why did
  precision fall?", "is this feature even sufficient?", "what does DEGREE_ASYMMETRY do at other values?",
  "attribute the false positives", "counterfactual", "which rule carries recall?", "build a minimal
  fixture", "prove behaviour preserved", rule_diagnostic.py, _cap_and_sum, oracle threshold, fp_eliminated,
  tp_lost.
---

# BWL proof-and-analysis toolkit

The project's evidence bar (see `bwl-research-methodology`) is: **do not accept a change because a number
moved — prove *why* it moved, and predict where it breaks.** This skill is the how-to for that proof. Each
recipe is a numbered runbook with a worked example drawn from this repo's own history and copy-pasteable
code you can run today.

Jargon is defined at first use; deeper domain theory lives in `netflow-botnet-reference` (flows, botnets,
C2, the datasets) and `bwl-detection-theory` (entropy, isolation forests, adaptive percentiles). The
tuning axes these recipes poke at are catalogued in `bwl-config-and-flags`.

The one non-negotiable: **you may run any read-only analysis here freely, but you may not COMMIT anything
you learn without going through the review path in `bwl-change-control`.** A counterfactual is evidence for
a change, not the change itself.

## When NOT to use this skill

| If you are… | Use instead |
|---|---|
| Looking up what a constant/kwarg *is* (its default, where it lives) | `bwl-config-and-flags` |
| Trying to remember which script already measures this | `bwl-diagnostics-and-tooling` (ships `scripts/`, `rule_diagnostic`) |
| Triaging a live symptom → probable cause (fast lookup, not a study) | `bwl-debugging-playbook` |
| Reading the *conclusion* of a past investigation (what was decided and why) | `bwl-failure-archaeology` / `evaluation/FINDINGS.md` |
| Deciding whether a result is strong enough to *claim* externally | `bwl-external-positioning`, `bwl-validation-and-qa` |
| Wanting the math behind a feature (entropy, MAD-z, Kneedle) | `bwl-detection-theory` |
| Running the standard benchmark suite as a pass/fail gate | `bwl-validation-and-qa` |

This skill is the layer *below* those: it is how you generate the evidence they consume.

## Shared prerequisites

Definitions used throughout (one line each):

- **Rule / heuristic**: a transparent scorer that adds weighted "hits" to a row; final heuristic score is
  capped at 1.0. Source: `bots_without_labels/rules.py`.
- **The decision**: `is_bot = heuristic_score >= 0.70 OR ml_score > dynamic_knee_threshold` (the ML side
  rate-capped at 2%). Verify: `grep -n "is_bot =" bots_without_labels/pipeline.py`.
- **Precision / recall / flag rate**: of the rows we flag, the fraction truly bot / of the true bots, the
  fraction we catch / the fraction of *all* rows flagged. A precision *below the base rate* means flagged
  rows are less bot-likely than random — worse than chance.
- **Counterfactual**: recompute the whole decision with one rule's evidence removed; a row that stops being
  flagged is *carried* by that rule.
- **Oracle threshold**: a threshold chosen *with* the labels — impossible in production, but it tells you
  the best a feature *could* do, which is a statement about the feature, not the tuning.

Environment: `uv` drives everything (`bwl-build-run-operate`). The isolation-forest backend needs
`--extra eif`; without it the ML path falls back and benchmark numbers will not reproduce. All the
snippets below were run green against the repo at commit 8a85edd.

---

## Recipe 1 — Per-rule counterfactual attribution

**Question it answers:** *which rule is costing me precision, and would removing it cost recall?*

Headline precision is a property of the whole decision, but the only levers are individual rules. Attribute
the flagged rows to the rule responsible so you calibrate the rule that carries false positives without
carrying recall.

**Procedure**
1. Score a *labelled* mix (you need ground truth to split flagged rows into TP/FP).
2. For each rule, compute two views:
   - **Fire view** — rows where the rule appears at all, split by truth → its stand-alone `fire_precision`.
   - **Counterfactual view** — for each row the rule fired *and* that was flagged, re-sum the heuristic
     with that rule's hits dropped (re-cap!) and re-test the decision. A row that falls below the line is
     carried by the rule: if truth=bot it is `tp_lost` (unique recall), else `fp_eliminated`.
3. Report `ml_only` separately — flagged rows whose heuristic never reached 0.70, so no heuristic rule
   carries them. This keeps the anomaly model's errors from being blamed on rule calibration.

The re-cap matters: dropping a supporting hit can *raise* other supporting hits (the 0.24 supporting cap
is redistributed). Never subtract a weight by hand — always re-run `_cap_and_sum` on the kept hits. This is
exactly what `evaluation/rule_diagnostic.py::_heuristic_without` does.

**Run the ready-made tool** (CICIDS2017, the fan-in-C2 capture):

```bash
uv run --extra eif python -m evaluation.rule_diagnostic --zip data/GeneratedLabelledFlows.zip
```

It prints, per rule, `fired  fire_p  fp_elim  tp_lost  fp_share`, sorted by `fp_eliminated`.

**Worked example A — CICIDS residual error is mostly *not* heuristic.** Attribution split the CICIDS
residual to show ~253 of the 358 FPs are ML/EIF-only, so the error is the ML path, not benign monotone
hubs — the pattern this recipe exists to catch. Full number breakdown lives in its canonical home,
`bwl-diagnostics-and-tooling` §1 ("How it attributed the CICIDS residual"). (Source:
`evaluation/FINDINGS.md`, "The honest ceiling".)

**Worked example B — CTU-13 cleared `asymmetric_degree` of over-firing.** On the CTU-13/Neris split the
same attribution showed `asymmetric_degree` fires on **2,000 of 2,000** positives with **zero** false
fires and *uniquely* carries **1,774** of them. That proved the middle-stage 0.041 precision was **not**
the new rule's doing — it was `entity_monotony` treating the degenerate `Proto`/`State` columns as actors.
The fix targeted the real culprit (actor-band entity gating), lifting precision **0.041 → 0.978** with
recall held. (Source: `evaluation/FINDINGS.md`, "The third discriminator".)

**Custom counterfactual on your own scored frame** (any labelled `DetectionResult`):

```python
from bots_without_labels.rules import _cap_and_sum
from bots_without_labels.pipeline import HEURISTIC_CUTOFF

def carried_by(result, truth, rule_id):
    """(fp_eliminated, tp_lost) for one rule via the re-capped counterfactual."""
    ml_flag = result.ml_scores > result.ml_threshold
    fp_elim = tp_lost = 0
    for i, row in enumerate(result.rules_result.hits):
        if not result.is_bot[i] or not any(h.rule_id == rule_id for h in row):
            continue
        kept = [h for h in row if h.rule_id != rule_id]
        new_h = _cap_and_sum(kept) if kept else 0.0
        if not ((new_h >= HEURISTIC_CUTOFF) or bool(ml_flag[i])):
            tp_lost += bool(truth[i]); fp_elim += (not truth[i])
    return fp_elim, tp_lost
```

A rule with large `fp_elim` and small `tp_lost` is a precision drag you can scope down cheaply. A rule with
large `tp_lost` is load-bearing for recall — touch it only with a benchmark guard.

---

## Recipe 2 — Oracle-threshold ceiling: is the FEATURE even sufficient?

**Question it answers:** *before I spend a week tuning a threshold, can this feature separate the classes
at all?*

Sweep the threshold *with the labels* and read off the best precision achievable at (near-)full recall. If
that ceiling is low, no amount of threshold tuning will save you — **the feature is insufficient, stop
tuning and go find a second discriminator.** This is a diagnostic on the *feature*, not a proposal to ship
a label-tuned threshold (you cannot, in production).

**Procedure**
1. Pick the single feature/score under test (e.g. per-entity diversity).
2. Sort rows by it; sweep the cut; at each cut record precision and recall against truth.
3. Look at precision at the highest recall you require. Low ceiling ⇒ the feature does not carry the
   decision alone.

**Worked example — per-entity diversity had a low ceiling on CICIDS, which *demanded* the hub gate.**
Per-entity diversity (how self-similar an actor's own events are) recovered recall from ~0 to **0.998**,
but its best precision at that recall was **0.144** (flag rate 0.219). The reason is structural, not
tuning: a busy *legitimate* channel — a backup job, a keepalive, one client hammering one server — is just
as monotone as a beacon, so *no* diversity cut separates them. That low ceiling is what justified adding a
**second, orthogonal discriminator**: relational hub degree (does the monotone node talk to *many* distinct
counterparts?). Adding it lifted precision to **0.441** at the same recall, and later timing calibration to
**0.846**. The lesson the project banked: a low oracle ceiling is a signal to *change the feature set*, not
to keep sweeping. (Source: `evaluation/FINDINGS.md`, "The fix" and "The second discriminator".)

**Snippet — sweep any per-row score against truth:**

```python
import numpy as np
def oracle_ceiling(score, truth, recall_floor=0.95):
    score = np.asarray(score, float); truth = np.asarray(truth, bool)
    best = 0.0
    for cut in np.unique(score):
        flag = score >= cut
        if not flag.any():
            continue
        prec = (flag & truth).sum() / flag.sum()
        rec  = (flag & truth).sum() / truth.sum()
        if rec >= recall_floor:
            best = max(best, prec)
    return best   # low  ->  the feature cannot separate; add a discriminator
```

(For a score where *low* means anomalous, invert the comparison.)

---

## Recipe 3 — Ablation via public kwargs (no code edits)

**Question it answers:** *what does the detector do if I move a knob — without forking the code?*

Two entry points take keyword arguments precisely so you can ablate without editing source:

| Call | Kwarg | Default | What it ablates |
|---|---|---|---|
| `detect(frame, schema, ...)` | `heuristic_cutoff` | `0.70` | the rule-side decision line |
| `detect(frame, schema, ...)` | `max_ml_flag_rate` | `0.02` | the ML rate cap |
| `build_features(frame, schema, ...)` | `burst_window_seconds` | `10` | the sliding burst-concentration window |

Verify the signatures: `grep -n "def detect" bots_without_labels/pipeline.py` and
`grep -n "def build_features" bots_without_labels/features.py`. The docstring for `heuristic_cutoff` says
in-source: *"override for ablation/tuning studies only"* — that is this recipe's blessing, and its limit.

**Snippet — sweep the decision line on the minimal broadcaster fixture (Recipe 5 builds it):**

```python
from bots_without_labels.pipeline import detect
from bots_without_labels.ingest import load
loaded = load("bc.csv")
for cut in (0.50, 0.70, 0.90):
    r = detect(loaded.frame, loaded.schema, heuristic_cutoff=cut)
    fired = {h.rule_id for row in r.rules_result.hits for h in row}
    print(f"cut={cut:.2f} flagged={int(r.is_bot.sum())} rules={sorted(fired)}")
```

Verified output at commit 8a85edd: `cut=0.50 flagged=810`, `cut=0.70 flagged=810`, `cut=0.90 flagged=0` —
i.e. the strong rules (`asymmetric_degree`, `entity_monotony`, weight 0.70) sit exactly on the 0.70 line,
so raising the cut above 0.70 silences the whole heuristic. That is a *design fact you can see*, not a
guess: no single strong rule reaches 0.70 by more than its own weight.

Kwargs cover the *exposed* axes only. A constant that is not a kwarg (e.g. `DEGREE_ASYMMETRY`) needs
Recipe 4.

---

## Recipe 4 — Guardrail robustness sweep

**Question it answers:** *over what range of this constant is behaviour stable, and where does it break?*
The answer is *why* a constant is labelled "guardrail / limited-evidence" versus "established".

A **guardrail** is a constant calibrated against limited evidence (one or two captures), not a proven
scale-free law. You earn the right to call it that — or to distrust it — by sweeping it across *decades*
(×10 steps) and recording where behaviour changes. See `bwl-config-and-flags` for the production-vs-guardrail
taxonomy.

**Procedure**
1. Import the module and read the constant's current value.
2. Loop over a decade-spanning range, patch `module.CONST = value`, re-run `detect`, record the metric
   (fire count, precision, flag rate).
3. **Restore the original** at the end. Report the *stable band* and the *break points*.

**Worked example — `DEGREE_ASYMMETRY` is stable ×10–×100, over-fires below, vanishes at ≥200.** On the one
labelled split it was calibrated against (CTU-13/Neris) plus a synthetic broadcaster, `asymmetric_degree`'s
result is unchanged for asymmetry factors ≈ 10–100, **over-fires below ≈ 10**, and the rule **disappears at
≥ 200** (200 exceeds Neris's own out/in ratio). *That sweep is the entire reason the constant is documented
as a limited-evidence guardrail, not a scale-free law* — see the in-source comment block at
`DEGREE_ASYMMETRY` in `rules.py` (lines ~93–107). Generality to other families is explicitly unproven and
tracked as a follow-up. (Source: `rules.py` docstring + `evaluation/FINDINGS.md`, "The honest ceiling
(CTU-13)".)

**Snippet — sweep the constant on a synthetic broadcaster (patch-and-restore):**

```python
from bots_without_labels import rules
from bots_without_labels.pipeline import detect
from bots_without_labels.ingest import load
loaded = load("bc.csv")
orig = rules.DEGREE_ASYMMETRY
for factor in (1, 10, 100, 200):
    rules.DEGREE_ASYMMETRY = factor
    r = detect(loaded.frame, loaded.schema)
    fires = sum(any(h.rule_id == "asymmetric_degree" for h in row)
                for row in r.rules_result.hits)
    print(f"DEGREE_ASYMMETRY={factor:>3}  fires on {fires} rows")
rules.DEGREE_ASYMMETRY = orig
```

Verified output at 8a85edd on the fixture below (source out-degree 90, in-degree 0): fires on 90 rows at
factors 1 and 10, **0** at 100 and 200. The exact break point here (≈90) is the *fixture's* out-degree, not
CTU-13's — the point of the recipe is the *shape* (a stable band with a hard cliff), which you then confirm
on the real labelled split. Never read a synthetic break point as the field number.

---

## Recipe 5 — Minimal synthetic fixture construction

**Question it answers:** *what is the smallest log that exhibits exactly one structure, so a rule's
behaviour is unambiguous?*

The shared factories in `tests/conftest.py` are the canonical models. Study them before rolling your own —
they encode hard-won rules about making the *adaptive* thresholds well-defined.

| Factory (`tests/conftest.py`) | Structure it isolates | The bot shape |
|---|---|---|
| `_network_log` | two entity cols; a fan-**in** hub (`c2hub` reached by 4 sources) + a point-to-point monotone channel (`backup`→`store`) + diverse filler | tests `entity_monotony` hub gate |
| `_broadcaster_log` | asymmetric high-degree **source** (`10.0.0.1` → 90 distinct dsts, one service) vs benign clients on two servers | tests `asymmetric_degree` fan-out |

**Rules for a fixture that actually exercises the adaptive machinery** (learned from these factories):

- **Diverse filler is mandatory.** Adaptive cuts are quantiles of a *distribution*. A log containing only
  the bot has no distribution to sit in — the cut is undefined or degenerate. `_network_log` adds 40 filler
  hosts whose numeric payloads *step across the whole global range* so each occupies many quantile bins and
  reads as genuinely diverse. Without spread, everything looks monotone and the rule can't discriminate.
- **Give an actor column an in-band cardinality ratio.** The actor-endpoint band is
  `ACTOR_MIN_RATIO`≈0.02 to `ACTOR_MAX_RATIO`≈0.5 (distinct/rows). Too few distinct values → read as a
  bounded categorical (rule dormant); one-per-row → read as an edge id (dormant). `_broadcaster_log` uses
  60 clients × 12 flows so the address columns clear the endpoint floor. (This band is *also* why the
  Bournemouth web-log `session_id` went dormant — below the band; see `evaluation/FINDINGS.md`.)
- **Isolate one structure per fixture.** A broadcaster fixture must *not* also contain a fan-in hub, or you
  cannot attribute a fire to one rule. Keep contexts (like `svc`) low-cardinality so they are read as
  *context*, not as a second actor node.
- **Meet the volume floors.** `ENTITY_MIN_EVENTS = 12`, `MIN_HUB_DEGREE = 3`. An entity below these is
  ignored by design. Verify: `grep -n "ENTITY_MIN_EVENTS\|MIN_HUB_DEGREE" bots_without_labels/rules.py`.

**Snippet — the whole broadcaster fixture inlined (writes `bc.csv` used above):**

```python
rows = ["src,dst,svc"]
for i in range(90):                                   # fan-out source: 90 distinct dsts
    rows.append(f"10.0.0.1,10.9.{i//256}.{i%256},smtp")
for c in range(60):                                   # benign: 60 clients, 2 servers
    server = "10.0.0.250" if c % 2 == 0 else "10.0.0.251"
    rows += [f"10.0.1.{c},{server},https"] * 12
open("bc.csv", "w").write("\n".join(rows) + "\n")
```

For a fan-*in* / hub fixture instead, copy `_network_log`. For timing-rule fixtures remember the
dense-timing gate: minute-quantised timestamps *suppress* `same_instant_burst`/`local_burst` (a binning
artefact), so a timing fixture needs sub-grid timestamps — see `assert_ctu13_rare_attack_recall` in
`conftest.py` for the "grid < 1.0s, dense-timing active" premise.

---

## Recipe 6 — Predicted-vs-measured discipline

**Question it answers:** *did I understand the mechanism, or did I just curve-fit after the fact?*

**Write the expected number down before you run.** A prediction that matches is mechanism understanding; a
surprise is a bug or a gap in your model — both valuable, both invisible if you only look at the result.
This is the core of `bwl-research-methodology`; this recipe is its mechanical form.

**Procedure**
1. State the hypothesis as a number or inequality *and commit it to writing* (a comment, the PR body, a
   scratch note) before running.
2. Run.
3. Record predicted vs measured. If they diverge, that gap is the finding — investigate it, do not quietly
   overwrite the prediction.

**Worked example — the fan-in false-positive risk was predicted, then materialised, then fixed without
tuning.** When `asymmetric_degree` first shipped **direction-agnostic** (commit `2a3f362`, 2026-06-25), the
design note already stated the risk: an undirected asymmetry rule cannot tell a bot's *fan-out* from benign
*fan-in* infrastructure (a DNS resolver, NTP source, load balancer), so it would over-fire on captures
where benign fan-in hubs dominate. That prediction **materialised** on the second family, CTU-13/Rbot:
precision collapsed to **0.056** (flag rate 0.567), with `asymmetric_degree` itself firing on 34,995 rows
(1,970 TP, 33,025 FP). Because the mechanism was predicted, the fix was structural, not a tuning search:
narrow the rule to the **source / fan-out side only** (out-degree ≫ in-degree). Result on Rbot,
**no thresholds tuned**: precision **0.056 → 0.929**, recall held at 0.985, `asymmetric_degree` back to
0 false fires. (Source: `evaluation/FINDINGS.md`, "The second-family test".)

The moral the project banks: a predicted failure that arrives on schedule is a *cheap* fix, because you
already know the cause. An unpredicted number that you rationalise afterwards is how overfitting hides.

---

## Recipe 7 — Behaviour-preservation proof for refactors

**Question it answers:** *did this refactor change any output, or only the code?*

A refactor's contract is **bit-identical output**. Prove it with fixed seeds and a diff, not by eyeballing
that the tests still pass (tests allow ranges; a refactor must not move the number *at all*).

**Procedure**
1. Confirm the sampling seed is fixed and shared, so the mix is identical run-to-run. `DEFAULT_SEED = 7`
   in `evaluation/harness.py`, consumed by every benchmark (`SEED = DEFAULT_SEED`). Verify:
   `grep -n "DEFAULT_SEED" evaluation/harness.py`.
2. Capture the full benchmark report *before* the refactor (all metrics, not just the headline).
3. Apply the refactor. Re-run with the same seed.
4. **Diff.** Identical ⇒ behaviour preserved. Any delta ⇒ the refactor changed behaviour and is no longer a
   refactor — it needs the full review path in `bwl-change-control`.

**Worked example — the 2026-07-03 consolidation audit.** The commits `3e93f14` ("Deduplicate test fixtures
via shared conftest") and `3f3f770` ("Consolidate benchmark boilerplate into a shared harness") moved code
without changing logic. They were validated as behaviour-preserving because the harness fixes the seed
(`DEFAULT_SEED = 7`, documented in-source as *"fixed (not varied per run) so measured numbers reproduce"*)
and the benchmark reports diffed identically — the protected gates (CICIDS 0.998/0.846/0.037, CTU-13 sc1
1.000/0.978/0.033, UNSW 0.122/0.198/0.020) were unchanged. That identity is the proof the consolidation was
safe. (Verify the commits: `git log --oneline --since=2026-07-02 --until=2026-07-04`.)

**Snippet — capture a comparable report before/after:**

```bash
# before the refactor
uv run --extra eif python -m evaluation.run_benchmarks > /tmp/before.txt
# ... apply refactor ...
uv run --extra eif python -m evaluation.run_benchmarks > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt && echo "IDENTICAL — behaviour preserved"
```

If you cannot afford the full suite, diff a single fast benchmark (`--only unsw`) plus
`uv run pytest -q` — but a true refactor claim wants the numeric report identical, not merely green tests.

---

## Quick reference — which recipe for which question

| You are asking… | Recipe |
|---|---|
| Which rule causes these false positives? Would cutting it lose recall? | 1 — counterfactual attribution |
| Can this feature *ever* separate the classes, or am I wasting tuning effort? | 2 — oracle ceiling |
| What happens if I move an exposed knob, without forking? | 3 — public-kwarg ablation |
| Over what range is this constant safe, and where does it break? | 4 — guardrail sweep |
| What is the smallest log that isolates one structure? | 5 — minimal fixture |
| Did I understand the mechanism or curve-fit after the fact? | 6 — predict-before-run |
| Did this refactor change any output? | 7 — behaviour preservation |

**The through-line:** every recipe converts a *claim* ("this rule is the problem", "this constant is fine",
"this refactor is safe") into a *reproducible measurement*. That conversion is the price of admission to the
review path — see `bwl-change-control` and `bwl-research-methodology` for what counts as enough.

---

## Provenance and maintenance

Authored 2026-07-04; repo at commit `8a85edd`. All snippets and the two sweep outputs were executed green
against that commit. Worked-example numbers are cited from `evaluation/FINDINGS.md` /
`evaluation/BENCHMARKS.md` (docs of record) — they are *recorded* benchmark results, not fresh runs; do not
present them as production accuracy or as fraud verdicts (see `bwl-external-positioning`).

| Volatile fact | Value cited | One-line re-verify |
|---|---|---|
| Decision cutoff | `HEURISTIC_CUTOFF = 0.70` | `grep -n "HEURISTIC_CUTOFF =" bots_without_labels/pipeline.py` |
| `detect` kwargs | `max_ml_flag_rate=0.02`, `heuristic_cutoff=0.70` | `grep -n "def detect" -A6 bots_without_labels/pipeline.py` |
| `build_features` kwarg | `burst_window_seconds=10` | `grep -n "burst_window_seconds\|BURST_WINDOW_SECONDS =" bots_without_labels/features.py` |
| Guardrail constant swept | `DEGREE_ASYMMETRY = 10`, `DEGREE_FLOOR_PERCENTILE = 0.99` | `grep -n "DEGREE_ASYMMETRY\|DEGREE_FLOOR_PERCENTILE" bots_without_labels/rules.py` |
| Fixture volume floors | `ENTITY_MIN_EVENTS=12`, `MIN_HUB_DEGREE=3` | `grep -n "ENTITY_MIN_EVENTS\|MIN_HUB_DEGREE" bots_without_labels/rules.py` |
| Fixed benchmark seed | `DEFAULT_SEED = 7` | `grep -n "DEFAULT_SEED" evaluation/harness.py` |
| CICIDS attribution | 2,320 flags / 358 FP / ~104 `entity_monotony` / ~253 ML-only | `grep -n "2,320\|entity_monotony fired" evaluation/FINDINGS.md` |
| CTU-13 `asymmetric_degree` fire | 2,000/2,000, 0 FP, carries 1,774 | `grep -n "2,000 of 2,000\|1,774\|1,774" evaluation/FINDINGS.md` |
| Rbot fan-in regression → fix | 0.056 → 0.929, recall 0.985 | `grep -n "0.056\|0.929" evaluation/FINDINGS.md` |
| Predicted-FP origin commit | `2a3f362` (2026-06-25) | `git show -s --format=%ci 2a3f362` |
| Refactor-audit commits | `3e93f14`, `3f3f770` (2026-07-03) | `git log --oneline --since=2026-07-02 --until=2026-07-04` |
| Recorded gate numbers | CICIDS 0.998/0.846/0.037; CTU sc1 1.000/0.978/0.033; sc3 0.985/0.929/0.034; UNSW 0.122/0.198/0.020 | `grep -n "0.846\|0.978\|0.929\|0.198" evaluation/BENCHMARKS.md` |

Numbers marked "~" are approximate in the source docs (tie-sensitive attribution); re-run
`evaluation/rule_diagnostic.py` if you need the exact current split. The Bournemouth web-log numbers are
provisional / licence-pending and must not be cited as settled (see `bwl-external-positioning`).

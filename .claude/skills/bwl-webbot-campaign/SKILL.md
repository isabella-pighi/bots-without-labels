---
name: bwl-webbot-campaign
description: >
  Load when working on TODO item 12 — detecting evasive, HUMAN-MIMICKING WEB BOTS in web-server
  access logs, the project's hardest open capability. Triggers: any task touching the Bournemouth /
  CERTH web-bot dataset (data/web_bot_detection_dataset.zip, evaluation/bournemouth_benchmark.py,
  tests/test_bournemouth_benchmark.py); questions like "why does the detector not transfer to web
  logs?", "can we catch human-mimicking web bots?", "what about mouse dynamics / interaction
  biometrics?", "should we force session_id as the entity?"; proposals to tune timing thresholds for
  page-load bursts, reintroduce a ratio gate to re-hide web sessions, or claim web-bot detection works. This is
  a decision-gated campaign, not a fix — it tells you which experiments are allowed and which are
  fenced-off wrong paths with recorded evidence.
---

# bwl-webbot-campaign — the human-mimicking web-bot campaign

**Owner-selected 2026-07-04 as the project's hardest live problem.** The flow-domain detector
(the one that wins on NetFlow botnets) **does not transfer to web logs** — this is an *honest
recorded negative*, not a bug to patch. This skill is the executable, phase-gated plan to turn that
negative into a capability, or to prove it cannot be done with the signals we have. Every phase has
exact commands, an EXPECTED observation, and an explicit **gate** telling you where to branch.

> **One-paragraph orientation.** "Web bot" here = an automated web client (crawler, form-filler,
> scraper) that is *deliberately built to look human* — it spoofs a real browser User-Agent, paces
> its requests irregularly, and visits a diverse set of pages. That is the opposite of a NetFlow
> botnet host, which the detector catches by its *mechanical* repetition, concentration, and timing
> regularity. On the axes our rules measure (diversity, timing coefficient-of-variation, request
> entropy, volume) these web bots **overlap real humans**, so the rules cannot separate them. For the
> underlying signals see `bwl-detection-theory`; for the domain (flows, HTTP logs, botnets) see
> `netflow-botnet-reference`.

---

## When NOT to use this skill

| If your task is… | Use instead |
| --- | --- |
| A NetFlow benchmark (CICIDS/Ares, CTU-13/Neris/Rbot, UNSW-NB15) drifting or failing | `bwl-validation-and-qa`, `bwl-debugging-playbook` |
| Understanding *why* the scale-invariant actor/entity selection works the way it does | `bwl-architecture-contract`, `bwl-detection-theory` |
| A general "detector over-flags / mis-scores" symptom not specific to web logs | `bwl-debugging-playbook` |
| Reading the recorded history of *other* investigations and dead ends | `bwl-failure-archaeology` |
| Deciding whether ANY new dataset is worth wiring in | `bwl-diagnostics-and-tooling`, `bwl-validation-and-qa`; `bwl-failure-archaeology` (its rejected-datasets table) |
| Actually committing a change / routing a review | `bwl-change-control` (canonical) |
| Wording a claim in docs of record | `bwl-docs-and-writing`, `bwl-external-positioning` |

This skill owns exactly one thing: **the web-bot capability and the Bournemouth evidence base.** If
you are not touching web logs, mouse dynamics, or TODO 12, you are in the wrong skill.

---

## The current state (the negative you must not re-discover)

Recorded in `evaluation/FINDINGS.md` (§ "Domain transfer: web-server logs") and
`evaluation/BENCHMARKS.md` (row 5). Numbers are **provisional / local-internal, licence-pending**.

| Fact | Value | Meaning |
| --- | --- | --- |
| Rows scored | 58,279 | Apache access-log requests (phase1) |
| Base rate | 0.029 | fraction of rows that are bot |
| Recall | 0.873 | most bot requests flagged — but so is almost everything |
| **Precision** | **0.028** | **below base rate → worse than chance** |
| Flag rate | 0.918 | flagged ~92% of all rows (session entity + timing over-fire) |
| Positive set | **11 bot sessions** / 263 human | *qualitative only* — far too small for a robust score |
| Provenance | see BENCHMARKS.md row for caveats | provisional / licence-pending |

**Two domain-transfer effects (both diagnosed, neither a detector regression):**

1. **The session entity over-flags.** Under the scale-invariant actor selection `session_id` IS
   admitted as a per-entity actor (the old cardinality-ratio band that used to exclude it is gone),
   and `entity_monotony` then fires on human sessions too — a monotone human session is as
   self-similar as a bot session — so the detector flags ~92% of rows at precision below the base
   rate. This is the method limit shown *directly*: per-entity monotony does not separate
   human-mimicking web bots from humans. `user_agent` is near-constant (~4 spoofed browser UAs), so
   it is no help either.
2. **Timing over-fired on page-load bursts.** The sub-second timing rules also misread the burst of
   near-simultaneous requests from a *single web page-load* as automated cadence.

**A METHOD limit, not a calibration.** It is tempting to read the over-flagging as a *config*
problem — tune the selection so `session_id` behaves. **It does not help:** with `session_id`
baselined as the entity, `entity_monotony` catches **0 of 11** bot sessions and instead flags
*monotone human* sessions. The discriminating features do not separate
the classes here — bot and human diversity, timing CoV, request entropy, and volume **all overlap**.
No threshold or entity-selection change closes this. Closing it needs **web-specific signals the
current rules do not model** — interaction biometrics (mouse dynamics), page-sequence / navigation
modelling, or keystroke cadence. TODO 12 classifies this as **P3, a separate research direction,
likely supervised or biometric, probably its own pipeline — exploratory until trusted labels and the
extra signal streams exist.**

---

## PHASE 0 — Licence gate (blocking; nothing publishes without it)

The Bournemouth / CERTH dataset has **no formal open licence**: the BORDaR catalogue (record 272)
marks copyright reserved to CERTH ITI + Bournemouth University; the README invites *research use* but
specifies no CC/OSS terms. The wrapper never redistributes the data — it reads only the locally
supplied, gitignored zip.

**Rule:** every number derived from this data is **internal-only** until a licence decision is
recorded. You may compute, diagnose, and iterate internally. You may **not** publish, put numbers in
an external-facing artefact, or claim them as field results.

| Step | Action | Deliverable |
| --- | --- | --- |
| 0.1 | Confirm the zip is present and gitignored | `git -C . check-ignore data/web_bot_detection_dataset.zip` returns the path |
| 0.2 | Record dataset provenance + licence status | already in `evaluation/bournemouth_benchmark.py` module docstring and BENCHMARKS.md — do not re-derive, cite it |
| 0.3 | **Owner contact for licence** | escalate via `bwl-change-control` (HCOM); record the decision (cleared / still-pending) in FINDINGS/BENCHMARKS with a date |

**Gate:** licence still unclear → stay internal, keep the "provisional / licence-pending" label on
every number, do NOT remove it. Licence cleared for research publication → `bwl-external-positioning`
governs what may then be claimed (and a tiny 11-session positive set still bars a precision/recall
claim regardless — see Phase 4).

---

## PHASE 1 — Reproduce the negative (baseline before you touch anything)

Never build on top of a number you have not reproduced this session.

```bash
# from repo root; the --extra eif installs the isotree Extended-Isolation-Forest backend
uv run --extra eif python -m evaluation.bournemouth_benchmark
```

**EXPECTED** (rare-attack mix, default `--bot 1800`, seed = repo `DEFAULT_SEED`): a `format_report`
block for "Bournemouth Web Bot Detection (web-log domain-transfer)" with recall ≈ **0.47**,
precision ≈ **0.03**, flag rate ≈ **0.92**, base rate ≈ **0.029**, n_rows > 10,000, and the note
line "session entity + actor graph DORMANT … timing+ML only". The parse/mapping guard test runs
without the zip:

```bash
uv run pytest tests/test_bournemouth_benchmark.py -q
```

**EXPECTED:** the parse guards pass unconditionally; `test_bournemouth_rare_attack_shape` runs only
if the zip is present, and pins the *shape* (n_rows > 10,000, valid metric ranges) — **not** a
recall/precision floor (this is a negative result, so there is no floor to defend).

**Gates:**

| Observation | Branch |
| --- | --- |
| Numbers within ±0.03 of expected | ✔ baseline good, proceed to Phase 2 |
| Numbers drifted materially | **STOP.** The engine or loader changed. Do not "fix" the web benchmark — re-baseline the NetFlow suite first via `bwl-validation-and-qa`; a shift here usually means a shared-path change (loader, timing rule, actor selection). Diagnose with `bwl-debugging-playbook`. |
| `import isotree` / eif error | You omitted `--extra eif`. The ML path needs it; without it the run is not comparable. |
| Zip absent | `main` prints a skip and exits 0 by design. Fetch per the printed URL (`https://m4d.iti.gr/web-bot-detection-dataset/`); it stays gitignored. |

---

## PHASE 2 — Inventory the unused signal (read-only)

The current wrapper reads **only** `phase1/data/web_logs/{bots,humans}/*.log`. The zip carries far
more that it ignores — most importantly **mouse-movement traces** and **train/test annotations**.
Inspect read-only; do not unpack into the repo tree.

```bash
# structure overview (verified 2026-07-06 at commit 8a85edd)
unzip -l data/web_bot_detection_dataset.zip | head -40
unzip -l data/web_bot_detection_dataset.zip | grep -c mouse_movements.json   # -> 200 (phase1)
```

**Verified member map (phase1; phase2 mirrors it at larger scale):**

| Member path | Format | What it is |
| --- | --- | --- |
| `phase1/data/web_logs/bots/access_{advanced,moderate}_bots.log` | custom Apache combined log | the ONLY thing the wrapper reads today (bot side) |
| `phase1/data/web_logs/humans/access_{1..5}.log` | same | human side |
| `phase1/data/mouse_movements/humans_and_{advanced,moderate}_bots/<session_id>/mouse_movements.json` | JSON dict | **unused signal** — 200 sessions, one file each |
| `phase1/annotations/humans_and_{advanced,moderate}_bots/{train,test}` | text, `"<session_id> <label>"` per line | **per-session ground-truth labels** (`human` / `advanced_bot` / `moderate_bot`); train/test split already provided |
| `phase2/…` | same layout, larger | second collection round (bigger human background, `moderate_and_advanced` bot mix) |
| `README.docx` | Word | dataset documentation |

**Log line format** (from the wrapper, verified): `%h %l [%t] "%r" %>s %b "%{Referer}" SESSIONID
"%{User-Agent}"`. The host `%h` is anonymised to `-` in every line — **there is no IP**. The actor
entity is the **8th field, the session id**; `user_agent` is a second (near-constant) entity;
timestamp is per-second. Unsessioned landing requests (session `-`, ~1.8%, the initial `GET /`
before the cookie is set) are dropped, not collapsed into one degenerate entity (`parse_line`).

**mouse_movements.json shape** (verified sample): a dict with keys `session_id` and
`total_behaviour`. `total_behaviour` is an encoded event string of the form
`[m(x,y)][m(x,y)]…` — a time-ordered sequence of mouse coordinate samples (and, per the dataset,
click/scroll events in the same encoding). **This is the raw material for interaction-biometric
features.** Before proposing any mouse-dynamics feature you MUST re-open a real file and confirm the
exact fields/encoding you intend to compute from — do not assume velocity/curvature are pre-computed
(they are not; you derive them from the coordinate stream).

```bash
# inspect one trace read-only (extract to /tmp, never into the repo)
d='phase1/data/mouse_movements/humans_and_advanced_bots/071tbv7fsev5d64kb0f9jieor6/mouse_movements.json'
mkdir -p /tmp/wbdz && (cd /tmp/wbdz && unzip -o -q "$OLDPWD/data/web_bot_detection_dataset.zip" "$d")
uv run python -c "import json; o=json.load(open('/tmp/wbdz/$d')); print(sorted(o)); print(o['total_behaviour'][:200])"
```

**Deliverable of Phase 2:** a short note listing the exact member paths and formats *you verified
this session* (not copied from here), and which of them a candidate feature would consume.

---

## PHASE 3 — Ranked solution menu (with theory obligations)

Each option carries a **theory obligation** you must discharge *before* building — otherwise you are
guessing. Ranked by evidence-availability and doctrine fit. Nothing here is proven; all are
**candidate** until Phase 4 gates pass.

### (a) Interaction-biometric features — mouse dynamics ★ top-ranked
Session-level features from the `total_behaviour` coordinate stream: velocity distribution, curvature,
pause/dwell distributions, straightness, sample-rate regularity. Literature line: Chu et al.; Iliou
et al. (this dataset's own authors) — human-mimicking bots are separable on *motor* signals even when
their *request* patterns overlap.
- **Why top:** the discriminating signal the request-log rules lack is physically present in the zip,
  with per-session labels (Phase 2). This is the only option whose signal we can *see* today.
- **Obligation:** features must be *computable from the shipped `total_behaviour` encoding*. Verify
  the columns/encoding first (Phase 2). If a bot session has no mouse file, the feature is null — you
  must decide (and pre-register) how nulls are handled, because "bot has no mouse data at all" is
  itself a signal you must not accidentally leak as a label proxy.

### (b) Page-sequence / navigation-graph modelling
Model a session as an ordered sequence of `path`s; score its entropy/perplexity against a human
navigation model, or its graph shape against typical human browsing.
- **Why second:** computable from the log the wrapper already parses (no new file type) — but the
  recorded negative says request *entropy* already overlaps between classes, so this must beat that
  overlap, not restate it.
- **Obligation:** predict *which* sequence statistic separates the classes and why the existing
  entropy rule does not already capture it. If you cannot name that, this collapses into the failed
  entropy signal.

### (c) Session-level aggregation layer feeding the EXISTING unsupervised pipeline
Add a new *feature family* computed per session (from (a) and/or (b)), preserving the
**roles-not-names** contract (features keyed by role, not by literal column name — see
`bwl-architecture-contract`) so the existing per-entity baseline + Extended Isolation Forest consume
it unchanged.
- **Why third:** best *doctrine fit* — extends the unsupervised skeleton rather than forking it — but
  only works if (a)/(b) actually yield a separating feature. It is a *delivery mechanism*, not a
  signal; it inherits whichever of (a)/(b) you prove.
- **Obligation:** the new family must be a genuine engine change routed as such (Phase 5). The
  session entity *is* now admitted, but per-entity monotony over it does not separate bots from
  humans — so the new signal must add discriminating information at the session level (interaction
  biometrics, navigation sequence), not lean on the existing monotony/timing signals.

### (d) A separate supervised web pipeline
Train on the provided train/test annotations; keep it entirely apart from the unsupervised engine.
- **Why last for *this* project, though most likely to "work" numerically:** it contradicts the core
  doctrine (*unsupervised, explainable, unlabelled logs*). TODO 12 itself anticipates this: the web
  capability is *"likely supervised or biometric, and probably its own pipeline … exploratory until
  trusted labels and the extra signal streams exist."* So supervised is *permitted as a separate
  exploratory pipeline*, but it is **not** the main detector and its numbers are not the project's
  headline unsupervised result.
- **Obligation:** if you go supervised, it must be a clearly separate artefact with its own
  provenance, and you must not present its labelled accuracy as evidence about the unsupervised
  detector.

**Ranking rationale:** (a) has the signal + labels in hand → highest evidence-availability; (c) is
the doctrine-preferred *vehicle* for (a); (b) is cheap but fights a known overlap; (d) works but
costs doctrine. Recommended path: **prove separation with (a) at the session level (Phase 4), then
deliver via (c).** Treat (d) as the fallback that changes what the project *is*.

---

## PHASE 4 — Evaluation design BEFORE building (falsifiable, pre-registered)

The single most important discipline here, because the positive set is tiny.

- **11 bot sessions in the current rare-attack mix = qualitative only.** You may NOT quote a
  precision/recall from 11 sessions as a capability. The *full* phase1 annotations carry ~35 bots per
  split (verified: `humans_and_advanced_bots/train` = 35 `advanced_bot` + 35 `human`), and phase2 is
  larger — if you evaluate a new feature, evaluate on the **full labelled session set**, not the
  rare-attack sample built for NetFlow-comparability.
- **Define the falsifiable bar up front.** Example bar for option (a): *"On phase1 session-level
  features with leave-one-session-out, advanced_bot sessions separate from human with AUC ≥ X and the
  separation survives on the held-out phase2 sessions."* Fill X *before* you run. Anything that only
  works in-sample is not signal.
- **The floor to beat is concrete:** the current method gets **0 of 11** with `entity_monotony` on
  forced `session_id`. Any credible result must *measurably* clear that — a handful of caught
  sessions with controlled false-positives on humans, on a defined split, reported with the split.
- **Pre-register expected numbers** (predict-before-run — see `bwl-research-methodology`). Write the
  predicted metric and the decision it drives ("if AUC < X, option (a) is rejected") before executing.
- **Guard against label leakage:** the train/test split is provided — use it; do not tune on test.
  "Bot sessions that have no mouse-movement file" must not become a backdoor label.

**Gate:** you have a written, falsifiable bar and a pre-registered prediction → build. You do not →
you are about to eyeball a result on 11 points; **stop and design first.**

---

## PHASE 5 — Promotion (route through change control)

Nothing from this campaign lands on `main` outside the HCOM team protocol. `bwl-change-control` is
canonical; this is the web-specific overlay.

| Change | Classification | Route |
| --- | --- | --- |
| New session-level **feature family** feeding the engine (option c) | **engine change** | full review loop; cross-model review pair (Codex reviews Claude); Definition of Ready/Done |
| New **dependency** (e.g. a mouse-trace parser lib) | **escalation trigger** | owner sign-off before adoption; prefer stdlib/pandas |
| **Separate supervised pipeline** (option d) | new exploratory artefact | its own module + provenance; explicitly *not* the unsupervised detector |
| Registry / narrative update | docs of record | `evaluation/BENCHMARKS.md` row + `evaluation/FINDINGS.md` narrative per `bwl-docs-and-writing`; keep the "provisional / licence-pending" tag until Phase 0 clears |

Add a guard test in the spirit of `tests/test_bournemouth_benchmark.py`: pin the *shape and mapping*
(and, once a real capability exists, a defended floor) so a future silent regression fails CI-less
local validation. The product manager is the only committer — never self-commit.

---

## Fenced wrong paths (each with its recorded evidence)

These are **not open questions.** They were considered or measured and rejected. Re-proposing one
without new evidence is a process error.

| Tempting move | Why it is wrong | Evidence |
| --- | --- | --- |
| **Lean on `session_id` per-entity monotony as the web signal** | `session_id` is already admitted as a per-entity actor, and `entity_monotony` over it catches **0 of 11** bots while lighting up *monotone humans* (~92% flag rate) — the monotony signal does not separate the classes. Adding "more monotony" cannot fix a signal that is uninformative here | FINDINGS § Bournemouth method limit |
| **Reintroduce a `distinct / n_rows` gate to suppress web sessions** | The cardinality-ratio band was *removed* because it is scale-dependent (it silently disabled the actor signals on busy NetFlow logs). Do not bring back a ratio gate to re-hide `session_id`; the over-flagging is a method limit to *fix with a real signal*, not to mask | `bwl-architecture-contract` §5; features.py scale-invariant tests |
| **Tune the sub-second timing thresholds to suppress page-load bursts** | The high flag rate is a *method limit*, not calibration — the timing rules assume flow cadence, not HTTP page-loads; suppressing bursts by threshold does not add the missing behavioural signal and risks the NetFlow timing wins | FINDINGS: "No detector thresholds were tuned for this"; "a method limit, not calibration" |
| **Claim web-bot detection "works" / quote a precision-recall from the mix** | 11 bot sessions is qualitative; the recorded precision (0.028) is *below* base rate. Any capability claim needs the Phase 4 bar on the full labelled set, and Phase 0 licence clearance | BENCHMARKS.md row 5 caveats; FINDINGS "qualitative domain-transfer evidence, not a robust estimate" |
| **Eyeball separation on a plot and call it signal** | Success in this campaign is *measurable gates only* (Phase 4). A convincing-looking scatter on 11 points is not evidence | `bwl-research-methodology` evidence bar |

---

## Provenance and maintenance

*Authored 2026-07-06 (repo at commit `8a85edd`). British English. All Bournemouth numbers are
provisional / local-internal, licence-pending (Phase 0).*

| Volatile fact | Stated value | One-line re-verify |
| --- | --- | --- |
| Bournemouth benchmark numbers | recall 0.873 / precision 0.028 / flag 0.918, base 0.029 | `grep -n "Bournemouth" evaluation/BENCHMARKS.md` |
| Phase-1 "0 of 11" method-limit diagnosis | forced `session_id` → 0/11 bots caught | `grep -n "0 of 11" evaluation/FINDINGS.md` |
| Scale-invariant actor tests | `REPEAT_MASS_MIN 0.3 / VOCAB_MAX_DISTINCT 200 / STRUCTURED_TOKEN_MIN 0.5` | `grep -n "REPEAT_MASS_MIN\|VOCAB_MAX_DISTINCT\|STRUCTURED_TOKEN_MIN" bots_without_labels/features.py` |
| Run command / eif extra | `uv run --extra eif python -m evaluation.bournemouth_benchmark` | `sed -n '/^Run:/,/"""/p' evaluation/bournemouth_benchmark.py` |
| Zip member map (200 mouse files phase1; annotations format) | see Phase 2 table | `unzip -l data/web_bot_detection_dataset.zip \| grep -c mouse_movements.json` |
| mouse_movements.json shape | dict with `session_id`, `total_behaviour` (`[m(x,y)]…`) | inspect one file per the Phase 2 snippet |
| Log line format / no IP / session = 8th field | custom combined, host `-` | `grep -n "SESSIONID" evaluation/bournemouth_benchmark.py` |
| Test guards (parse always, run skip-if-absent) | `tests/test_bournemouth_benchmark.py` | `uv run pytest tests/test_bournemouth_benchmark.py -q` |
| Entity-band precision-fix commit | `56f305d` | `git log --oneline \| grep 56f305d` |
| TODO 12 classification (P3, separate/exploratory) | see § current state | `grep -n "### 12" TODO.md` |

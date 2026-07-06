# Real-data benchmark registry

This file is the **tracked registry of real-data benchmarks** for the detector:
one row per externally-labelled dataset we measure against, the numbers we
currently get, and how those numbers moved as the design changed. It is the
durable scoreboard; `FINDINGS.md` is the narrative of *why* each number is what
it is.

Two rules keep this honest, and they are the whole reason this file exists:

- **Synthetic numbers are a stress test only.** The synthetic suite reports
  ~1.0 recall because the generator plants exactly the signatures the rules look
  for — detector and benchmark sharing one assumption. A green synthetic run is
  necessary but never sufficient, and its numbers do **not** belong in this
  registry.
- **Only externally-labelled real data earns a row here.** Recall, precision and
  flag-rate are reported against a held-out ground-truth label that someone other
  than us produced. Even then, read every number as *ranking under uncertainty* —
  "this actor is unusual relative to this batch" — never as a fraud verdict.

Every figure below is copied from a script output or from `FINDINGS.md`, with the
source cited. Nothing here is invented or rounded for effect; where a number is a
measured count it is given as a count.

## How to read the registry

Each **primary, bot-specific** benchmark (the first two rows) is a **rare-attack
mix**: nearly all benign traffic plus a small, intact slice of one labelled botnet,
sized so the attack is a realistic ~3% minority. "Entity columns keyed by detector"
are the actor-like columns the engine picks out *by shape, never by name* — the
addresses it builds its per-entity and graph signals on. "Timestamp resolution"
matters because the sub-second timing rules gate themselves off when the clock is
too coarse to carry a beacon cadence; it is the axis on which the two primary
benchmarks deliberately disagree.

**Secondary rows** are on a different footing: they may be labelled *broad-IDS*
probes (multiple mixed attack families, not a single botnet) included to test the
method's generality, and must be read on their own terms — their numbers are not
comparable, like-for-like, with the bot-specific rows.

## Registry

| Benchmark | Source / licence | Data shape | Labelled? | Base rate | Timestamp resolution | Entity columns (by detector) | Recall | Precision | Flag rate |
|---|---|---|---|---|---|---|---|---|---|
| **CICIDS2017 Friday-morning botnet (Ares)** | CIC / University of New Brunswick; academic terms (registration required) | NetFlow-style flow export; 61,966 rows (60,000 sampled benign + all bot) | Yes — `Label` ∈ {`Bot`, `BENIGN`} | 0.032 | **Minute**-quantised *at source* (`6/7/2017 8:59`) → dense-timing rules **gated off** | `Source IP` / `Destination IP` (degree floor ≈ 551) | **0.998** | **0.879** | **0.036** |
| **CTU-13 scenario 1 (Neris)** | Stratosphere Lab, CTU University; **CC-BY** | Argus bidirectional NetFlow; 62,000 rows (60,000 sampled benign + 2,000 bot) | Yes — directional `Label`; `From-Botnet` = positive | 0.032 | **Microsecond** (`2011/08/10 09:46:53.047277`) → dense-timing rules **active** | actor endpoints chosen by shape (source/destination address) | **1.000** | **0.971** | **0.033** |
| *Generality probe —* **CTU-13 scenario 3 (Rbot)** *(second family; recall and precision now generalise after the source fan-out fix)* | Stratosphere Lab, CTU University; **CC-BY** | Argus bidirectional NetFlow; 62,000 rows | Yes — directional `Label`; `From-Botnet` = positive | 0.0323 | **Microsecond** → dense-timing rules **active** | actor endpoints chosen by shape | 0.985 | 0.9319 | 0.034 |
| *Secondary —* **UNSW-NB15 shard 1/4** *(broad IDS, not a bot capture)* | UNSW Canberra Cyber Range Lab; academic terms | Raw pcap-derived flow CSV (`UNSW-NB15_1.csv`, shard 1 of 4); 62,000 rows | Yes — `Label` 0/1 + `attack_cat` (9 mixed attack families) | 0.032 | Second-resolution `Stime` | `srcip` / `dstip` (now admitted at scale) | 1.000 | 0.519 | 0.062 |
| *Domain-transfer, provisional —* **Bournemouth Web Bot Detection** *(web-log domain; negative result; licence-pending)* | CERTH ITI / Bournemouth University (m4d.iti.gr); **licence unclear** — research-use invited, copyright reserved | Apache access logs; 58,279 rows | Yes — folder label (`bots/` vs `humans/`) | 0.029 | Per-second | `session_id` now **admitted** by the scale-invariant selector → over-flags (the method limit, shown directly) | 0.873 | **0.028** | 0.918 |

The first two rows are the **primary, bot-specific** benchmarks and are the current
measured output on this branch. Both now hold high precision at recall ≥ 0.998
(CICIDS 0.879, CTU-13 0.971) — the CTU-13 figure rose from an earlier 0.041 once the
broad rule that was over-flagging the diverse NetFlow background was calibrated (see
its honest note below). The two captures still contrast deliberately on timestamp
resolution and bot shape; that contrast, not the precision gap, is the point.

The third row, **CTU-13 scenario 3 (Rbot)**, is a **second-family generality probe**.
The asymmetry signal's **recall generalised** to a different bot family at once
(0.985); its precision did **not** under the original direction-agnostic rule (0.056),
which fired on benign fan-in infrastructure too — but narrowing the rule to the
**source fan-out** shape recovered precision to **0.929** (the source-fan-out step);
the **current** post-decouple registry row reads **0.9319** at the same 0.034 rounded
flag rate, recall held. So both now generalise across the two CTU-13 families seen. The honest residual
is in its section below: fan-in coverage lives in `entity_monotony` / the hub gate,
and fan-in generality is *guarded* by CICIDS no-regression, **not** positively proved.

The fourth row, **UNSW-NB15**, is a **secondary** entry on a deliberately different
footing: it is a *broad intrusion-detection* dataset of nine mixed attack families,
**not** a bot capture, so its numbers (now recall 1.000 after the scale-invariant
selector re-admits the IP actor columns) are read as a generality probe, not a
bot-detection result — see its section below.

The fifth row, **Bournemouth Web Bot Detection**, is a **web-log domain-transfer**
probe and an honest **negative** result: precision (0.028) sits *below* the base rate
(0.029), so on this dataset the detector does worse than chance. Its numbers are
**provisional / local-internal**, not cleared for publication, because the dataset's
licence is unclear (research use invited, copyright reserved). Read it as a
domain-transfer finding, not a detector benchmark — see its section below.

### Reproduce

The single repeatable entry point runs **every** benchmark, skips the ones whose
data file is absent, and prints one combined table:

```bash
uv run --extra eif python -m evaluation.run_benchmarks
```

Or run a single benchmark directly:

```bash
# CICIDS2017 (needs data/GeneratedLabelledFlows.zip)
uv run --extra eif python -m evaluation.cicids_bot_benchmark \
    --zip data/GeneratedLabelledFlows.zip

# CTU-13 scenario 1 (needs data/capture20110810.binetflow — see fetch below)
uv run --extra eif python -m evaluation.ctu13_bot_benchmark
```

Both data files are gitignored and large, so these are local/manual benchmarks.
The runner writes only temporary CSVs and **persists no artefacts** — it never
commits data, so there is no generated state to keep in sync with this file.
`tests/test_real_benchmark.py` (CICIDS) and `tests/test_ctu13_benchmark.py`
(CTU-13) **skip** when the file is absent, and otherwise pin the wins below so a
future change that silently reintroduces a real-data blind spot fails the suite
even with the synthetic tests green.

---

## CICIDS2017 Friday-morning botnet (Ares) — results history

A **passive fan-in star**: many infected hosts beacon to one command-and-control
server (`205.174.165.73`) with near-identical flows. The clock is minute-resolution
at the source, so this benchmark isolates a **data limit** — the sub-second timing
rules have nothing to work with. The story of this dataset is the design arc that
took precision from *below the base rate* to 0.879.

| Stage | Recall | Precision | Flag rate | What changed |
|---|---|---|---|---|
| Pre-fix (global concentration capped) | 0.022 | 0.018 | — | Repetition/concentration downgraded to supporting-only; only sub-second timing left as strong evidence, and the clock is too coarse for it. Precision **below** the 0.032 base rate — a flagged row was *less* likely to be a bot than a random one. |
| Per-entity diversity baseline | 0.998 | 0.144 | 0.219 | Score each actor by how self-similar *its own* events are (`entity_monotony`). Recovers recall, but a busy *legitimate* channel is just as monotonous as a beacon, so precision is low at a high flag rate. |
| + relational hub discriminator | 0.998 | 0.441 | 0.072 | Escalate a monotone actor only if it is also a **hub** (≥ `MIN_HUB_DEGREE = 3` distinct counterparts). Removes the point-to-point benign channels diversity alone could not separate. |
| + timing calibration | 0.998 | 0.846 | 0.037 | Gate the dense-timing rules off on coarse clocks (adaptively, by detected resolution), so whole-minute bins stop firing as noise. |
| **+ ML-tail sentinel decouple (current)** | **0.998** | **0.879** | **0.036** | Stop the sparse-timing sentinel (`SPARSE_TIMING_SENTINEL = 999`) leaking into the EIF feature matrix: median-fill the `dt__std` / `dt__cv` axes for rows with too few events to time, and add a `has_regular_timing` 0/1 indicator instead. The isolation-forest tail stops carving sparse-timing rows out as artificial outliers, so the ML-only false positives fall. `regular_timing` still reads `context.dt_cv`, untouched, so that cadence heuristic is byte-identical. |

*Source: `FINDINGS.md` CICIDS history and "Decoupling the sparse-timing sentinel from
the ML feature matrix". The arc is real intermediate output, kept to show the
progression; the last row is the current branch and reproduces today.*

**Note on the actor graph.** The `asymmetric_degree` rule does **not** fire on
CICIDS: the actor graph builds (`Source IP` / `Destination IP` endpoints, degree
floor ≈ 551) but no row clears the combined asymmetry/floor/monotony gate. So this
result and its no-regression are credited to the **timing calibration**, not to
the actor rule (`FINDINGS.md` lines 121–124).

### Per-rule attribution (where the residual error lives)

A checked diagnostic (`evaluation/rule_diagnostic.py`) on the current post-decouple
branch attributes the flagged rows, so calibration can target the rules that cost
precision without carrying recall. The pre-decouple column is kept beside it to show
what the sparse-timing sentinel decouple actually moved:

| Quantity | Current (post-decouple) | Pre-decouple |
|---|---|---|
| Total flags | 2,232 | 2,320 |
| False positives | 270 | 358 |
| True positives caught | 1,962 | 1,962 |
| `entity_monotony` fires | 2,067 rows, ~104 FP (fire-precision **0.949**) | 2,067, ~104 FP |
| `entity_monotony` unique recall carry | 1,934 of the 1,962 true catches | 1,938 |
| FP from the ML/EIF scorer alone (ML-only) | **165** | ~253 |
| FP from `entity_monotony` | ~104 | ~104 |
| FP from other heuristic rules | essentially none | essentially none |

*Source: fresh reviewed `rule_diagnostic` run at `ef92510` (ML pair, doc-sweep task).
Reproduce with `uv run --extra eif python -m evaluation.rule_diagnostic --zip
data/GeneratedLabelledFlows.zip`. Note `rule_diagnostic` prints precision/recall to
three decimals (0.879 / 0.998); the benchmark scripts print four (0.8790 / 0.9980).*

The takeaway is that the 12.1% residual error is **not** dominated by benign monotone
hubs — most of it is the ML path. The sparse-timing sentinel decouple targeted exactly
that ML-only tail: **ML-only false positives fell ~253 → 165** and total false
positives 358 → 270, taking precision **0.846 → 0.879** at a flat 0.998 recall — see "Decoupling
the sparse-timing sentinel from the ML feature matrix" in `FINDINGS.md`.

### Honest ceiling (CICIDS)

Precision 0.879 is the measured number on *this one labelled capture*. It is not a
production guarantee and not proof any flagged row is fraud.

- It is **anomaly-style evidence, not a fraud verdict** — the running system has no
  labels and cannot measure its own precision; only the benchmark can, because
  CICIDS ships labels.
- It is **one attack family and one hub**. The lift leans on a single, uniquely
  separable C2 (`205.174.165.73`). `K = 3` was **not** tuned to its fan-out.
- **Benign monotone hubs remain a plausible risk** for the `entity_monotony` gate
  (a DNS resolver, NTP source, load balancer or backup target is also a
  low-diversity, high-degree node). Degree narrows this risk; it does not remove it.
- The **diversity cut is a fixed 10th-percentile quantile**, which lands on ties at
  bin edges on real flow data; a robust fix needs an adaptive (gap/knee) cut. Tracked
  as a follow-up, not fixed on this branch.
- **The ML-only tail has since been shrunk.** The residual error was dominated by the
  ML/EIF path (~253 ML-only false positives pre-fix, **165** measured post-fix);
  decoupling the sparse-timing sentinel from the feature matrix lifted precision
  **0.846 → 0.879** at a flat 0.998 recall by cutting exactly that tail. It is a
  calibration of the anomaly-score axis, not a new labelled-precision guarantee —
  still ranking under uncertainty, never a fraud verdict. See `FINDINGS.md`
  "Decoupling the sparse-timing sentinel from the ML feature matrix".

---

## CTU-13 scenario 1 (Neris) — results history

The **opposite shape**, and the one the CICIDS rules miss. A single infected host
(`147.32.84.165`) runs the Neris botnet — spam, C2 and click fraud — so it *reaches
out to many distinct destinations*. Connecting to many counterparts reads as **high**
diversity, so both the monotony rule and the diversity-gated hub rule walk straight
past it. With microsecond timestamps the dense-timing rules are **active** here, so
this benchmark isolates a **method limit**: timing resolution alone (the thing CICIDS
lacked) still did not recover this bot.

| Stage | Recall | Precision | Flag rate | What changed |
|---|---|---|---|---|
| Before (timing / monotony only) | 0.113 | 0.005 | 0.757 | Microsecond timestamps present and dense-timing rules active, yet the diverse outbound bot is missed. The documented method limit. |
| + `asymmetric_degree` | 1.000 | 0.041 | 0.785 | An undirected actor graph flags a high-volume endpoint whose degree exceeds an adaptive floor **and** exceeds its reverse-role degree by ~10× **and** is monotone in service — covering both a broadcasting source and a passive fan-in hub, without asserting direction. Recovers recall, but overall precision stays low because other rules over-flag the background. |
| + actor-band entity gating | 1.000 | 0.978 | 0.033 | Apply the existing **actor cardinality-ratio band** to the columns `entity_monotony` baselines over, so the degenerate `Proto` / `State` categoricals (below the band) are excluded from per-entity baselining. The over-flagging that capped precision goes away; `asymmetric_degree` is untouched and still carries the recall. |
| **+ ML-tail sentinel decouple (current)** | **1.000** | **0.971** | **0.033** | The same feature-matrix fix that lifts CICIDS costs a little on the microsecond-clocked CTU mix: excluding the sentinel from the EIF axes trims precision 0.978 → 0.971, recall held at 1.000. Dropping the `dt` features entirely was **rejected** — it cost CTU **-4.8 pts** precision. |

*Source: `FINDINGS.md` "asymmetric endpoint degree" section and "The precision fix".
Reproduce with `uv run --extra eif python -m evaluation.ctu13_bot_benchmark`
(n = 62,000, base rate 0.032, microsecond timestamps, dense-timing rules active).
Verified by rina-approved review #37205 against mono's measured table #37143.*

**The new rule is a clean catch.** A per-rule diagnostic on this split shows
`asymmetric_degree` fires on **2,000 of 2,000** positives with **zero** false
fires, and *uniquely* carries **1,774** of them (the other 226 also trip another
rule) — `FINDINGS.md` lines 230–235.

### Honest ceiling (CTU-13)

Read this as *hypothesis-supporting evidence within one botnet family*, not a solved
problem.

- **The over-flagging that capped precision has been fixed (0.041 → 0.978).** The
  new rule always fired cleanly (2,000/2,000, zero false fires); the earlier 0.041
  came from *pre-existing broad rules* over-flagging the diverse NetFlow background —
  notably `entity_monotony` firing on the degenerate `Proto` / `State` columns.
  Excluding those degenerate categoricals from per-entity baselining (via the actor
  cardinality-ratio band) lifted verified precision to **0.978** at a 0.033 flag
  rate, recall held. An earlier per-rule counterfactual *projection* had estimated
  0.956; the actual verified figure on the re-run pipeline is **0.978**.
  `tests/test_ctu13_benchmark.py` still pins the **recall** win (≥ 0.95).
- **Same-family evidence — now tested on a second family.** Recall 1.000 is on the
  family the rule was developed against (Neris). A second labelled family (CTU-13
  scenario 3 / Rbot) has since been run: recall generalised (0.985), and once the rule
  was narrowed to the **source fan-out** shape its precision generalised too (0.056 →
  0.929, recall held). Both now hold across the two CTU-13 families. See "CTU-13
  scenario 3 (Rbot)" below.
- **Benign fan-in hubs no longer fire here (since the source fan-out narrowing).** A
  DNS resolver, NTP source or load balancer is a *fan-in* star (high in-degree, low
  out-degree); the source-only rule does not fire on it. That passive fan-in case is
  covered by `entity_monotony` / the hub gate instead, not `asymmetric_degree`.
- **The constants are limited-evidence guardrails.** `DEGREE_ASYMMETRY = 10` and the
  99th-percentile floor hold for asymmetry factors ≈ 10–100 on this one split plus a
  synthetic broadcaster; the rule over-fires below ≈ 10 and vanishes at ≥ 200. They are
  not scale-free constants.
- **A small precision tradeoff from the CICIDS ML-tail fix.** Decoupling the
  sparse-timing sentinel from the EIF matrix (a CICIDS precision win, 0.846 → 0.879)
  trims CTU-13 sc1 precision **0.978 → 0.971**, recall flat at 1.000. Net across the
  two primary captures: **+3.3 pts CICIDS, -0.7 pts CTU**; the "drop `dt` entirely"
  alternative was rejected for costing CTU **-4.8 pts**. See `FINDINGS.md` "Decoupling
  the sparse-timing sentinel from the ML feature matrix".

---

## CTU-13 scenario 3 (Rbot) — second-family generality test

The CTU-13 scenario 1 honest ceiling asks for a **second labelled family** before the
`asymmetric_degree` win is read as more than same-family evidence. Scenario 3 supplies
one: a different bot, **Rbot** (an IRC-controlled DDoS/scan botnet), captured the same
way (Argus bidirectional NetFlow, CC-BY). It told a two-part story — recall
generalised immediately, precision did not, and the precision gap was then closed by a
targeted directional change:

| Stage | Capture | Recall | Precision | Flag rate |
|---|---|---|---|---|
| (reference) | CTU-13 sc1 (Neris) | 1.000 | 0.978 | 0.033 |
| Direction-agnostic `asymmetric_degree` | CTU-13 sc3 (Rbot) | 0.985 | 0.056 | 0.567 |
| + source fan-out narrowing | CTU-13 sc3 (Rbot) | 0.985 | 0.929 | 0.034 |
| **+ ML-tail sentinel decouple (current)** | **CTU-13 sc3 (Rbot)** | **0.985** | **0.9319** | **0.034** |

*n = 62,000 rows, base rate 0.0323. Source: CTU-Malware-Capture-Botnet-44 detailed
bidirectional flow labels (Stratosphere Laboratory / CTU, CC-BY); a skip-if-absent
benchmark like the others. Original split finding measured by mono (#37642); the
source-fan-out narrowing and its numbers verified by rina (review #38226). The current
row adds the ML-tail sentinel decouple (`ef92510`): it shifts sc3's ML-only split
(flag `ml` 0.0023), lifting precision **0.929 → 0.9319** with recall (0.985) and flag
rate (0.034) flat — a real but small move, measured fresh for the doc sweep.*

**Recall generalised; precision first did not.** Recall 0.985 shows the
connectivity-asymmetry signal recovers a *second, different* bot family — the core
hypothesis holds across families. But the *direction-agnostic* rule's precision
collapsed to 0.056 at a 0.567 flag rate. The attribution was unambiguous, and — note —
**not** the scenario-1 story:

- `asymmetric_degree` itself fired on **34,995** rows — **1,970** true positives and
  **33,025** false positives, a stand-alone fire-precision of **0.056**. The rule that
  was a clean 2,000/2,000-zero-false-fire catch on Neris was the *direct* source of the
  false positives on Rbot.
- The scenario-1 culprit was ruled out: `entity_monotony`'s entity columns were empty
  here (no `Proto`/`State` over-flagging), so this was the actor-graph rule's own
  behaviour, not the previously-fixed degenerate-column issue.

The cause is structural: an **undirected** asymmetry rule cannot separate a bot's
**fan-out** (one source → many counterparts) from benign **fan-in** infrastructure
(DNS / NTP / load balancer: many clients → one server). Both are high-degree,
monotone, role-asymmetric stars, and on Rbot the benign fan-in hubs vastly outnumber
the bot.

**The fix: source fan-out only.** The rule was narrowed to fire only on the **source /
fan-out side**, where a value's out-degree dominates its in-degree (`out ≥ 10 × in`).
The source endpoint is taken by **schema column order** (source precedes destination
in flow logs — `SrcAddr` before `DstAddr`), *not* by parsing column names. A benign
fan-in hub is the opposite shape and no longer fires; that passive fan-in case is now
owned by `entity_monotony` / the hub gate. Verified end-to-end with **no detector
thresholds tuned**: precision **0.056 → 0.929**, flag rate **0.567 → 0.034**, recall
held at **0.985**. In attribution `asymmetric_degree` now fires **1,970 TP / 0 FP** on
Rbot — as clean as on Neris; the **151** residual false positives are **ML-only** (no
heuristic rule carries them).

**What this is — and is not.**

- **`asymmetric_degree` is now the diverse-bot fan-out signal** — recall *and*
  precision generalise across both CTU-13 families it has seen.
- **Fan-in C2 coverage does not live here.** A passive fan-in star (many hosts beacon
  one C2) is caught by `entity_monotony` / the hub gate, not `asymmetric_degree`.
- **No real external fan-in-bot benchmark exists, so fan-in generality is *guarded, not
  proved*.** The only real labelled fan-in C2 in our data is CICIDS (many hosts →
  `205.174.165.73`), where the catch is carried by `entity_monotony`
  (`asymmetric_degree` fires 0). CICIDS therefore serves as **no-regression evidence**
  that the fan-in case stays covered — **not** positive proof that fan-in detection
  generalises. No non-circular, natively-labelled fan-in capture was found to test that
  directly.
- **Still two scenarios of one dataset.** sc1 + sc3 are both CTU-13.

At the source-fan-out revision, this work left the protected gates unchanged:
CICIDS 0.998 / 0.846 / 0.037 and CTU-13 sc1 1.000 / 0.978 / 0.033 (the values as of
that revision). Their **current** post-decouple values are in the registry above —
CICIDS 0.998 / **0.879** / 0.036 and CTU-13 sc1 1.000 / **0.971** / 0.033.

Reproduce by fetching the scenario-3 capture and selecting the `sc3` scenario:

```bash
curl -o data/capture20110812.binetflow \
  https://mcfp.felk.cvut.cz/publicDatasets/CTU-Malware-Capture-Botnet-44/detailed-bidirectional-flow-labels/capture20110812.binetflow
uv run --extra eif python -m evaluation.ctu13_bot_benchmark --scenario sc3
```

`--scenario sc3` selects the Rbot capture and labels the output as scenario 3. An
explicit `--binetflow <path>` override is labelled by its matching registry scenario,
so it cannot be mis-reported under the scenario-1 heading. The combined runner also
carries it as `uv run --extra eif python -m evaluation.run_benchmarks --only
ctu13_sc3`. Like the other benchmarks, it is skip-if-absent when the capture is not
present locally.

---

## Excluded / exploratory sources (not fair tests)

These were tried and **deliberately not** promoted to benchmarks. They are recorded
so the registry's two kept datasets are understood as a *choice*, not all we looked
at (`FINDINGS.md` lines 8–23).

| Source | Dataset | Why excluded |
|---|---|---|
| Hugging Face | `mindweave/web-server-logs` | Flagged rows' bot-UA rate ≈ the base rate — **no lift** to measure. |
| Kaggle | `tunguz/clickstream-data-for-online-shopping` | **No labels**; surfaced over-long sessions only. |
| Local zip | CICIDS2017 PortScan flows | Attacks were **55%** of the sample — the majority, so not anomalous. |

A fair test needs a *rare*, externally-labelled attack population; the first three
fail on majority-class, missing-label or coarse-timestamp grounds.

### Dataset-pool sweep (web-bot and IDS candidates)

A later sweep assessed four further candidate datasets for the pool. Of the four, one
(Bournemouth) was wired and measured — the provisional, licence-pending **negative**
result in the registry above, detailed in its own section below — and **three were
evaluated and skipped** on honesty grounds. The skip reasons are recorded so each is a
documented decision, not a silent omission:

| Source / licence | Dataset | Why skipped |
|---|---|---|
| Zenodo 3477932 (CC-BY-4.0) | Web Robot Detection — server logs (*web-log domain*) | The labelled files are **aggregated per-session features** with no raw entities or timestamps; the raw per-request events carry entities and timestamps but **no joinable label** (session-ids and request-ids are different id spaces, no mapping). Deriving a label from IP / user-agent / time would be **circular leakage** — the detector keys on those same fields. No honest event-level label mapping exists. |
| AWS open-data (CSE-CIC-IDS2018) | CSE-CIC-IDS2018 botnet day (*netflow domain*) | The official processed ML CSVs are **IP-stripped** (no source/destination IP, only a bounded `Dst Port`), so the per-entity, actor-graph and monotony rules have no actor entities and stay **dormant** — it would not be a fair test of this detector. Recovering IPs would need CICFlowMeter reprocessing of the raw pcaps, out of evaluation-only scope. |
| Kaggle (ISIT-2024 "Bits and Bots") | Browser-interaction sessions (*web-log domain*) | The accessible competition files are **two bot classes** — `gremlins/` and `hlisa_traces/`, where HLISA is a tool that *generates* human-**like** bot traces, **not** real users. No human-labelled traffic is accessible (the IEEE competition description holds real-human data out as the evaluation set). With no honest bot-vs-human ground truth, a gremlin-vs-HLISA run would be **bot-vs-bot** — a category mismatch for an automation-ranking detector that would flag both classes — and **HLISA must never be labelled "human."** Skipped per boss decision. |

So three of the four candidates carry no honest, accessible, real-label test for this
detector, and only Bournemouth was measurable — itself a domain-transfer negative. The
sweep is a reminder that clean web-bot benchmarks pairing real entities, real
timestamps, and a real human-vs-bot label are genuinely scarce.

## UNSW-NB15 shard 1/4 — secondary, broad-IDS generality probe

UNSW-NB15 is now a **tracked secondary row**, with a first measured result on the
real raw data — but it is on a different footing from the two bot benchmarks above,
and the framing matters more than the number.

**What it is.** UNSW-NB15 is a frequently-cited *broad intrusion-detection* dataset.
Its labels cover **nine mixed attack families** (e.g. exploits, reconnaissance, DoS,
fuzzers, generic, shellcode), captured as a `Label` 0/1 flag plus an `attack_cat`
category. It is **not** a bot capture: there is no single beaconing-botnet population
isolated the way CICIDS-Ares and CTU-13-Neris are. So this row probes *generality* —
how the detector behaves on a heterogeneous IDS mix — and is explicitly **not** a
bot-detection win.

**The measured result.** Run with the real (gitignored) `data/UNSW-NB15_1.csv`
shard present, via `evaluation/run_benchmarks.py --only unsw`. The current figures
are on the same branch as the CTU-13 actor-band entity-gating fix above; the prior
pre-fix figures are kept to show the effect of the stricter gating:

| Run | Rows | Base rate | Flag rate | Recall | Precision |
|---|---|---|---|---|---|
| UNSW-NB15 shard 1/4 — cardinality-ratio band | 62,000 | 0.032 | 0.020 | 0.122 | 0.198 |
| **UNSW-NB15 shard 1/4 — scale-invariant selection (current)** | 62,000 | 0.032 | **0.062** | **1.000** | **0.519** |

*This is **shard 1 of 4** (`UNSW-NB15_1.csv` … `_4.csv`). The current figures are a
measured run of `uv run --extra eif python -m evaluation.run_benchmarks --only unsw`
with `data/UNSW-NB15_1.csv` present; they are not an estimate, and cover only this
one shard.*

**How to read it — the scale-invariant selector re-admits the IP actor columns.**
The prior 0.122 recall came from the cardinality-ratio band excluding `srcip`/`dstip`
at this row count (their ratio fell below `0.02`) — the very scale-dependence the
current change fixes. With the scale-invariant recurrence/shape selection, `srcip`
and `dstip` are correctly admitted as per-entity actors, so the entity/monotony
signal now fires on UNSW's monotone attack sources: recall rises to **1.000** at a
**0.062** flag rate, precision **0.519** (about **16×** the 0.032 base rate). This is
the actor signal *working* on this shard, not a false-positive flood — but it is
still **not a bot-detection result**: UNSW-NB15 is a broad-IDS mix of nine families,
not an isolated beaconing botnet, and catching monotone attack sources is incidental
to what the method targets. **This is an interpretation, not a proven attribution**:
confirming *which* attack families are recovered needs per-category (`attack_cat`)
and per-rule diagnostics across all four shards, which this single-shard run does not
provide. Read it as "the actor signal is scale-robust and fires broadly on this IDS
shard," never as a tracked bot number.

**Why raw shards, not stripped mirrors.** This result needed the **raw** flow CSVs.
Several Hugging Face mirrors of UNSW-NB15 ship only the pre-processed,
feature-engineered export (the 49-feature `UNSW_NB15_training-set.csv` style), with
the raw per-flow identifiers — source and destination addresses, ports, fine
timestamps — already dropped or aggregated. Those are exactly the **actor-endpoint
and timestamp columns** the detector keys on, so a stripped mirror cannot exercise
the per-entity, graph or timing signals at all. The benchmark therefore uses the
raw records from the official source:

> UNSW-NB15, Cyber Range Lab, UNSW Canberra.
> <https://research.unsw.edu.au/projects/unsw-nb15-dataset>
> Download the raw pcap-derived flow CSVs (`UNSW-NB15_1.csv` … `_4.csv`) with the
> full Argus/Bro feature set including `srcip`, `dstip`, `sport`, `dsport`, `Stime`,
> so the loader sees real entity columns and timestamps.

`evaluation/unsw_benchmark.py` remains **skip-if-absent**: with no shard present it
contributes no number; this row reflects the run with `UNSW-NB15_1.csv` in place.
Extending the measurement across all four shards is a natural follow-up.

---

## Bournemouth Web Bot Detection — web-log domain-transfer (provisional, negative)

This is the project's first **web-log domain** measurement, and it is an honest
**negative**. The detector was built and tuned on *network-flow* data (CICIDS, CTU-13);
Bournemouth is raw **Apache access logs** — a different domain entirely — so this row
asks whether any of the method transfers, and the answer is largely *no*.

> **Provisional / licence-pending.** These numbers are a **local, internal**
> evaluation result. The dataset's licence is unclear — research use is invited but
> copyright is reserved (CERTH ITI / Bournemouth University), with no formal open
> licence — so the figures are **not cleared for publication or redistribution**
> pending a licence decision. The data itself is never redistributed (gitignored), and
> the benchmark is skip-if-absent like the others.

| Run | Rows | Base rate | Flag rate | Recall | Precision |
|---|---|---|---|---|---|
| Bournemouth — cardinality-ratio band (session dormant) | 58,279 | 0.029 | 0.681 | 0.474 | 0.020 |
| **Bournemouth — scale-invariant selection (session admitted)** | 58,279 | 0.029 | **0.918** | **0.873** | **0.028** |

*Source: CERTH ITI / Bournemouth University, m4d.iti.gr (BORDaR record 272). Labels are
dataset-provided (folder `bots/` vs `humans/`), not derived — so the ground truth is
honest even though the result is poor. No detector thresholds were tuned.*

> **Qualitative evidence only — tiny positive set.** The rare-attack mix contains just
> **11 bot sessions** (263 human). These figures therefore rest on a very small positive
> population: treat this as a *qualitative* domain-transfer signal, **not** a
> statistically robust precision/recall estimate.

**How to read it — worse than chance, now shown directly.** Precision **0.028** sits
*below* the 0.029 base rate: a flagged row is *less* likely to be a bot than a random
one. The scale-invariant actor selection (no cardinality-ratio band) now **admits**
`session_id` as a per-entity actor — and that is exactly what makes the method limit
*visible* rather than hidden:

- **The session entity over-flags.** A session's per-entity monotony does **not**
  separate an evasive web bot from a human — a monotone human session looks as
  self-similar as a bot session — so `entity_monotony` fires on human sessions too.
  This is the prediction the earlier Phase-1 experiment made when it *forced* the
  session entity active (it caught **0 of 11** bot sessions and flagged monotone humans);
  under scale-invariant selection it is now the default, and the flag rate climbs to
  **~92%**. (A raw request-`path` column is also admitted as a pseudo-actor — content,
  not identity; a known residual, see below.)
- **Timing over-fires on page-load bursts.** The sub-second timing rules also misread the
  natural burst of near-simultaneous requests a single web page-load generates as
  automated cadence.

**What this is — and is not.** It is a clean **domain-transfer negative**, now shown
*directly*: the netflow-shaped signals (per-entity monotony, repetition, timing) do not
separate human-mimicking web bots from humans, so admitting the session entity floods
the output. It is **not** evidence the method is broken on its own domain — the netflow
gates remain strong at their current post-decouple values (CICIDS 0.998 / 0.879 / 0.036,
CTU-13 sc1 1.000 / 0.971 / 0.033, sc3 0.985 / 0.9319 / 0.034) — and it is **not** a
fraud verdict.

**It is a method limit, not a selection bug.** Bot and human diversity, timing CV,
request entropy and volume all overlap on web sessions, so no entity-selection choice
recovers detection here. Closing this gap needs **web-specific signals** (interaction
biometrics such as the mouse-movement data Bournemouth carries), a separate future
capability — see `evaluation/FINDINGS.md` and `TODO.md` (P3, item 12). A related
residual: a raw request-`path` field (non-URL-typed content) is still admitted as a
pseudo-actor; generic content-column detection is tracked as a follow-up. The result
stays a negative (precision below base rate), provisional/licence-pending.

Reproduce (the dataset is gitignored and licence-pending, so this is local/manual):

```bash
# place the dataset zip at data/web_bot_detection_dataset.zip, then:
uv run --extra eif python -m evaluation.bournemouth_benchmark
```

The combined runner also carries it as `uv run --extra eif python -m
evaluation.run_benchmarks --only bournemouth`. Like the other benchmarks,
`evaluation/bournemouth_benchmark.py` is **skip-if-absent** when the dataset is not
present locally.

Dataset files are **not** redistributed in this repository; download them from the
sources below.

- **CICIDS2017** — Canadian Institute for Cybersecurity (CIC), University of New
  Brunswick. <https://www.unb.ca/cic/datasets/ids-2017.html>. Cite: Iman Sharafaldin,
  Arash Habibi Lashkari, Ali A. Ghorbani, "Toward Generating a New Intrusion Detection
  Dataset and Intrusion Traffic Characterization," *4th International Conference on
  Information Systems Security and Privacy (ICISSP)*, 2018.
- **CTU-13** — Stratosphere Laboratory, CTU University, Czech Republic. Licence:
  **CC-BY** (<https://creativecommons.org/licenses/by/2.0/>). Cite: S. García, M. Grill,
  J. Stiborek, A. Zunino, "An empirical comparison of botnet detection methods,"
  *Computers & Security* 45 (2014) 100–123. CTU-13 fetch (369 MB, under the 400 MB
  ceiling):

  ```bash
  curl -o data/capture20110810.binetflow \
    https://mcfp.felk.cvut.cz/publicDatasets/CTU-Malware-Capture-Botnet-42/detailed-bidirectional-flow-labels/capture20110810.binetflow
  ```

The graph-anomaly grounding for `asymmetric_degree` (OddBall, the Akoglu–Tong–Koutra
survey, BotMiner) is documented in full in `FINDINGS.md` under "References". No claim in
this registry should be read as a fraud verdict — these works ground an *anomaly*
signal, not a ground-truth label.

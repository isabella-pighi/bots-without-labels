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
| **CICIDS2017 Friday-morning botnet (Ares)** | CIC / University of New Brunswick; academic terms (registration required) | NetFlow-style flow export; 61,966 rows (60,000 sampled benign + all bot) | Yes — `Label` ∈ {`Bot`, `BENIGN`} | 0.032 | **Minute**-quantised *at source* (`6/7/2017 8:59`) → dense-timing rules **gated off** | `Source IP` / `Destination IP` (degree floor ≈ 551) | **0.998** | **0.846** | **0.037** |
| **CTU-13 scenario 1 (Neris)** | Stratosphere Lab, CTU University; **CC-BY** | Argus bidirectional NetFlow; 62,000 rows (60,000 sampled benign + 2,000 bot) | Yes — directional `Label`; `From-Botnet` = positive | 0.032 | **Microsecond** (`2011/08/10 09:46:53.047277`) → dense-timing rules **active** | actor endpoints chosen by shape (source/destination address) | **1.000** | **0.978** | **0.033** |
| *Secondary —* **UNSW-NB15 shard 1/4** *(broad IDS, not a bot capture)* | UNSW Canberra Cyber Range Lab; academic terms | Raw pcap-derived flow CSV (`UNSW-NB15_1.csv`, shard 1 of 4); 62,000 rows | Yes — `Label` 0/1 + `attack_cat` (9 mixed attack families) | 0.032 | Second-resolution `Stime` | `srcip` / `dstip` | 0.122 | 0.198 | 0.020 |

The first two rows are the **primary, bot-specific** benchmarks and are the current
measured output on this branch. Both now hold high precision at recall ≥ 0.998
(CICIDS 0.846, CTU-13 0.978) — the CTU-13 figure rose from an earlier 0.041 once the
broad rule that was over-flagging the diverse NetFlow background was calibrated (see
its honest note below). The two captures still contrast deliberately on timestamp
resolution and bot shape; that contrast, not the precision gap, is the point.

The third row, **UNSW-NB15**, is a **secondary** entry on a deliberately different
footing: it is a *broad intrusion-detection* dataset of nine mixed attack families,
**not** a bot capture, so its modest numbers are read as a generality probe, not a
bot-detection result — see its section below.

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
took precision from *below the base rate* to 0.846.

| Stage | Recall | Precision | Flag rate | What changed |
|---|---|---|---|---|
| Pre-fix (global concentration capped) | 0.022 | 0.018 | — | Repetition/concentration downgraded to supporting-only; only sub-second timing left as strong evidence, and the clock is too coarse for it. Precision **below** the 0.032 base rate — a flagged row was *less* likely to be a bot than a random one. |
| Per-entity diversity baseline | 0.998 | 0.144 | 0.219 | Score each actor by how self-similar *its own* events are (`entity_monotony`). Recovers recall, but a busy *legitimate* channel is just as monotonous as a beacon, so precision is low at a high flag rate. |
| + relational hub discriminator | 0.998 | 0.441 | 0.072 | Escalate a monotone actor only if it is also a **hub** (≥ `MIN_HUB_DEGREE = 3` distinct counterparts). Removes the point-to-point benign channels diversity alone could not separate. |
| **+ timing calibration (current)** | **0.998** | **0.846** | **0.037** | Gate the dense-timing rules off on coarse clocks (adaptively, by detected resolution), so whole-minute bins stop firing as noise. |

*Source: `FINDINGS.md` lines 111–124. The arc is real intermediate output, kept to
show the progression; the last row is the current branch and reproduces today.*

**Note on the actor graph.** The `asymmetric_degree` rule does **not** fire on
CICIDS: the actor graph builds (`Source IP` / `Destination IP` endpoints, degree
floor ≈ 551) but no row clears the combined asymmetry/floor/monotony gate. So this
result and its no-regression are credited to the **timing calibration**, not to
the actor rule (`FINDINGS.md` lines 121–124).

### Per-rule attribution (where the residual error lives)

A checked diagnostic on this branch (`evaluation/rule_diagnostic.py`) attributes
the flagged rows so calibration targets the rules that cost precision without
carrying recall:

| Quantity | Value |
|---|---|
| Total flags | 2,320 |
| False positives | 358 |
| True positives caught | 1,962 |
| `entity_monotony` fires | 2,067 rows, ~104 FP (fire-precision **0.949**) |
| `entity_monotony` unique recall carry | 1,938 of the 1,962 true catches |
| FP from the ML/EIF scorer alone (ML-only) | ~253 |
| FP from `entity_monotony` | ~104 |
| FP from other heuristic rules | essentially none |

*Source: `FINDINGS.md` lines 146–156. Reproduce with
`uv run --extra eif python -m evaluation.rule_diagnostic --zip data/GeneratedLabelledFlows.zip`.*

The takeaway is that the 15.4% residual error is **not** dominated by benign
monotone hubs — most of it is the ML path, a separate calibration question.

### Honest ceiling (CICIDS)

Precision 0.846 is the measured number on *this one labelled capture*. It is not a
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
| **+ actor-band entity gating (current)** | **1.000** | **0.978** | **0.033** | Apply the existing **actor cardinality-ratio band** to the columns `entity_monotony` baselines over, so the degenerate `Proto` / `State` categoricals (below the band) are excluded from per-entity baselining. The over-flagging that capped precision goes away; `asymmetric_degree` is untouched and still carries the recall. |

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
- **Same-family evidence only.** Recall 1.000 is on the family the rule was developed
  against (Neris). It supports the hypothesis that connectivity asymmetry recovers a
  diverse directional bot; it is **not** proof of transfer to unseen families. A second
  labelled family remains future validation.
- **Passive fan-in hubs fire by design.** Because the rule is direction-agnostic, a
  benign monotone server, DNS resolver, NTP source or load balancer — a real one-sided
  star — is an explicit false-positive risk.
- **The constants are limited-evidence guardrails.** `DEGREE_ASYMMETRY = 10` and the
  99th-percentile floor hold for asymmetry factors ≈ 10–100 on this one split plus a
  synthetic broadcaster; the rule over-fires below ≈ 10 and vanishes at ≥ 200. They are
  not scale-free constants.

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
| UNSW-NB15 shard 1/4 — pre-fix | 62,000 | 0.032 | 0.201 | 0.561 | 0.090 |
| **UNSW-NB15 shard 1/4 — current** | 62,000 | 0.032 | **0.020** | **0.122** | **0.198** |

*This is **shard 1 of 4** (`UNSW-NB15_1.csv` … `_4.csv`). The current figures are a
measured run of `uv run --extra eif python -m evaluation.run_benchmarks --only unsw`
with `data/UNSW-NB15_1.csv` present (verified by rina-approved review #37205 against
mono's measured table #37143); they are not an estimate, and cover only this one
shard.*

**How to read it — above prevalence, and the change is gating, not regression.**
Precision **0.198** is about **6.2×** the 0.032 base rate, so a flagged row is far
more likely to be labelled an attack than a random row is. Recall **0.122** means
the detector now catches **12.2%** of the labelled attack slice (recall is coverage
of the positives, so it is *not* compared to the class base rate). The current-vs-
pre-fix move — flag rate 0.201 → 0.020, precision 0.090 → 0.198, recall 0.561 →
0.122 — is the **same stricter actor gating** that fixed CTU-13: excluding degenerate
low-cardinality categoricals from per-entity baselining makes the detector flag far
fewer rows, more precisely. On this broad-IDS shard that **reduces incidental
coverage** of attacks the method was never built to catch. Crucially, the earlier
0.561 recall was partly produced by the **same** degenerate-column over-flagging the
fix removed: `entity_monotony` baselining the bounded `Proto`/`State`-style
categoricals inflated the flag rate and incidentally swept up broad-IDS attacks. So
the stricter gating makes this secondary check **more conservative and more honest,
not strictly better** — a lower recall here is the over-flagging going away, not a
capability lost. This is **not** a bot regression: UNSW-NB15 is not a bot capture,
and the dropped flags are largely those incidental hits the looser gating happened
to surface. The detector still
targets the **automation / repetition / concentration** pattern — monotone,
high-volume, structurally repetitive actors — and many UNSW-NB15 attacks (an
exploit, a fuzzing run, a one-off reconnaissance probe) leave little of that
footprint, so a method built for beaconing automation would not be expected to flag
them. **This is an interpretation, not a proven attribution**: confirming *which*
attack families are recovered or missed needs per-category (`attack_cat`) and
per-rule diagnostics across all four shards, which this single-shard run does not
provide. Reading 0.122/0.198 as a "bot-detection result" would misrepresent both the
dataset and the method.

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

## Provenance and citations

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

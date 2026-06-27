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

Each benchmark is a **rare-attack mix**: nearly all benign traffic plus a small,
intact slice of one labelled botnet, sized so the attack is a realistic ~3%
minority. "Entity columns keyed by detector" are the actor-like columns the engine
picks out *by shape, never by name* — the addresses it builds its per-entity and
graph signals on. "Timestamp resolution" matters because the sub-second timing
rules gate themselves off when the clock is too coarse to carry a beacon cadence;
it is the axis on which our two kept benchmarks deliberately disagree.

## Registry

| Benchmark | Source / licence | Data shape | Labelled? | Base rate | Timestamp resolution | Entity columns (by detector) | Recall | Precision | Flag rate |
|---|---|---|---|---|---|---|---|---|---|
| **CICIDS2017 Friday-morning botnet (Ares)** | CIC / University of New Brunswick; academic terms (registration required) | NetFlow-style flow export; 61,966 rows (60,000 sampled benign + all bot) | Yes — `Label` ∈ {`Bot`, `BENIGN`} | 0.032 | **Minute**-quantised *at source* (`6/7/2017 8:59`) → dense-timing rules **gated off** | `Source IP` / `Destination IP` (degree floor ≈ 551) | **0.998** | **0.846** | **0.037** |
| **CTU-13 scenario 1 (Neris)** | Stratosphere Lab, CTU University; **CC-BY** | Argus bidirectional NetFlow; 62,000 rows (60,000 sampled benign + 2,000 bot) | Yes — directional `Label`; `From-Botnet` = positive | 0.032 | **Microsecond** (`2011/08/10 09:46:53.047277`) → dense-timing rules **active** | actor endpoints chosen by shape (source/destination address) | **1.000** | **0.041** | **0.785** |

Both rows are the **current** measured output on this branch. The two precision
figures look wildly different (0.846 vs 0.041) and that contrast is the point, not
a defect — see each benchmark's honest note below. The headline CTU-13 precision
is held down by *pre-existing* broad rules over-flagging a diverse NetFlow
background, **not** by the rule that recovers the bot.

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
| **+ `asymmetric_degree` (current)** | **1.000** | **0.041** | **0.785** | An undirected actor graph flags a high-volume endpoint whose degree exceeds an adaptive floor **and** exceeds its reverse-role degree by ~10× **and** is monotone in service — covering both a broadcasting source and a passive fan-in hub, without asserting direction. |

*Source: `FINDINGS.md` lines 180–235. Reproduce with
`uv run --extra eif python -m evaluation.ctu13_bot_benchmark` (n = 62,000, base
rate 0.032, microsecond timestamps, dense-timing rules active).*

**The new rule is a clean catch.** A per-rule diagnostic on this split shows
`asymmetric_degree` fires on **2,000 of 2,000** positives with **zero** false
fires, and *uniquely* carries **1,774** of them (the other 226 also trip another
rule) — `FINDINGS.md` lines 230–235.

### Honest ceiling (CTU-13)

Read this as *hypothesis-supporting evidence within one botnet family*, not a solved
problem.

- **The low overall precision (0.041) is not the new rule's doing.** The new rule
  fires cleanly (2,000/2,000, zero false fires). The 0.041 comes from *pre-existing
  broad rules* over-flagging the diverse NetFlow background — notably `entity_monotony`
  firing on the degenerate `Proto` / `State` columns. That is a separate calibration
  question, tracked, not introduced here. Pinning overall precision on this capture
  would lock in an unrelated limit — which is exactly why
  `tests/test_ctu13_benchmark.py` pins the **recall** win (≥ 0.95) and deliberately
  **not** overall precision.
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

## UNSW-NB15 (candidate, not yet a benchmark)

UNSW-NB15 is a frequently-cited IDS dataset, but it is **not currently a row in this
registry**, for two reasons worth recording so the gap is a decision, not an oversight:

- **It is a broad IDS dataset, not a bot-specific capture.** UNSW-NB15's labels cover
  nine general attack *categories* (e.g. exploits, reconnaissance, DoS, generic). Its
  nearest label, `Bot`-like activity, is not isolated as a single beaconing-botnet
  population the way CICIDS-Ares and CTU-13-Neris are. Dropping it in as-is would mix
  "intrusion" with "bot" and muddy what this registry measures.
- **Stripped Hugging Face mirrors are unsuitable.** Several HF mirrors of UNSW-NB15
  ship only the pre-processed/feature-engineered CSVs (the 49-feature
  `UNSW_NB15_training-set.csv` style export), with raw per-flow identifiers — source
  and destination addresses, ports, fine timestamps — already dropped or aggregated.
  Those are exactly the **actor-endpoint and timestamp columns** the detector keys on,
  so a stripped mirror cannot exercise the per-entity, graph or timing signals. A fair
  UNSW-NB15 benchmark would need the **raw flow records** from the official source:

  > UNSW-NB15, Cyber Range Lab, UNSW Canberra.
  > <https://research.unsw.edu.au/projects/unsw-nb15-dataset>
  > Download the raw pcap-derived flow CSVs (`UNSW-NB15_1.csv` … `_4.csv`) with the
  > full Argus/Bro feature set including `srcip`, `dstip`, `sport`, `dsport`, `Stime`,
  > so the loader sees real entity columns and timestamps.

  Until that raw data is in place, `evaluation/unsw_benchmark.py` is a
  **skip-if-absent wrapper only** — it does *not* contribute a tracked number to the
  registry — and the dataset is framed here as **broad IDS, not bot-specific**.

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

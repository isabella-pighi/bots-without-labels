---
name: netflow-botnet-reference
description: >
  The security-domain primer for anyone with zero network-security background working on this repo. Load
  this when you hit an unfamiliar term (flow, NetFlow, Argus, binetflow, bidirectional flow, C2, beaconing,
  fan-out, fan-in, From-Botnet/To-Botnet, base rate); when you touch a real capture under data/ (CTU-13
  capture20110810/20110812.binetflow, CICIDS2017 GeneratedLabelledFlows.zip, UNSW-NB15_1.csv, the
  Bournemouth web_bot_detection_dataset.zip); when a benchmark row in evaluation/BENCHMARKS.md or FINDINGS.md
  mentions Neris, Rbot, Ares, a host IP, microsecond vs minute clocks, or a licence; when you need to know
  which detector rule owns which attack shape; or when you must not confuse a synthetic archetype (invented)
  with a real malware family. Not the maths — that is bwl-detection-theory.
---

# NetFlow & botnet reference

You are reading a log of who-talked-to-whom on a network, trying to spot automated (bot) traffic hiding in
mostly-human background — **without** being told which rows are bots. This skill defines the vocabulary and
documents every real dataset the project measures against. Imperative runbook; British English; every jargon
term defined at first use.

## When NOT to use this skill

| If you need… | Go to |
|---|---|
| The detector's maths (entropy, robust z / MAD, isolation forest, Kneedle, adaptive percentiles) | `bwl-detection-theory` |
| Which constant/flag to change and its production-vs-guardrail status | `bwl-config-and-flags` |
| How to run a benchmark / measure a rule's firing (`rule_diagnostic`, `run_benchmarks`) | `bwl-diagnostics-and-tooling` |
| Environment setup, CLI anatomy, `data/` conventions, download traps | `bwl-build-run-operate` |
| What counts as evidence, tier discipline, the golden-number inventory | `bwl-validation-and-qa` |
| The live web-bot capability plan (mouse dynamics, TODO item 12) | `bwl-webbot-campaign` |
| Whether a result may be published, licences, novelty claims | `bwl-external-positioning` |

This skill is the *domain* pack: what the data **means**. The siblings above are *how to act on it*.

---

## 1. The flow — a phone bill, not a phone recording

A **flow** is one summary row for one conversation between two network endpoints over some time window. It
records *metadata only*: who, to whom, which protocol, how long, how many packets and bytes — **never the
payload**. The framing to keep in your head: a flow is the **itemised phone bill** (numbers dialled, call
duration, call count), **not a recording of the call**. Every detection idea in this repo must work from the
bill alone. If an idea needs the words spoken, it is out of scope.

- **NetFlow** — the generic name for this flow-summary format (originally a Cisco router feature).
- **Argus** — the specific flow tool that produced the CTU-13 captures. It emits richer fields than raw
  NetFlow (byte counts split by direction, a connection-state string).
- **binetflow** (`.binetflow`) — Argus **bi**directional NetFlow: one row aggregates **both directions** of a
  conversation (A→B and B→A folded together) instead of two half-flows. This is why a single row can carry
  `SrcBytes` (bytes the source sent) separately from `TotBytes` (both directions).

### Decode a real CTU-13 line, field by field

The header and a real row from `data/capture20110810.binetflow` (CTU-13 scenario 1):

```
StartTime,Dur,Proto,SrcAddr,Sport,Dir,DstAddr,Dport,State,sTos,dTos,TotPkts,TotBytes,SrcBytes,Label
2011/08/10 09:46:53.058760,20.360268,tcp,147.32.3.93,443,  <?>,147.32.84.59,51790,FPA_FRPA,0,0,133,81929,67597,flow=Background-Established-cmpgw-CVUT
```

| Field | Value | Meaning |
|---|---|---|
| `StartTime` | `2011/08/10 09:46:53.058760` | When the flow started. **Microsecond** precision (six digits after the second) — load-bearing; see §4. |
| `Dur` | `20.360268` | Flow duration, seconds. |
| `Proto` | `tcp` | Transport protocol (`tcp`, `udp`, `icmp`, …). |
| `SrcAddr` / `Sport` | `147.32.3.93` / `443` | Source IP and port. Port 443 = HTTPS. |
| `Dir` | `<?>` | Direction/flow-state arrow. `->` one-way, `<->` bidirectional established, `<?>` direction uncertain, `<-` reverse. (In this file: `<->` 2.19M rows, `->` 615k, `<?>` 6.2k, `<-` 7k.) |
| `DstAddr` / `Dport` | `147.32.84.59` / `51790` | Destination IP and port. |
| `State` | `FPA_FRPA` | Connection-state flags (TCP flag letters per direction, `_`-separated). Degenerate on some rows — see the CTU-13 precision trap in §4. |
| `sTos` / `dTos` | `0` / `0` | Type-of-service bytes (almost always 0 here; near-useless). |
| `TotPkts` | `133` | Total packets, both directions. |
| `TotBytes` | `81929` | Total bytes, both directions. |
| `SrcBytes` | `67597` | Bytes the **source** sent (the directional split bidirectional flows give you). |
| `Label` | `flow=Background-…` | Ground-truth annotation (real captures only). The `flow=` prefix is stripped by the loader. See §3. |

The `147.32.x.x` addresses are the CTU university's own network (the monitored LAN); external IPs are the
wider internet. The infected host in this scenario lives at `147.32.84.165` (§5).

---

## 2. Attack shapes — and which rule owns each

A **botnet** is a fleet of compromised machines (bots) taking orders from an attacker's **C2**
(command-and-control server). The traffic they generate has recognisable *shapes* in the flow bill. This
project detects **automation**, i.e. these shapes, not "badness" — it never asserts a row is malicious, only
*anomalously machine-like*. Four shapes matter, each owned by a specific rule in `bots_without_labels/rules.py`:

| Shape | Plain description | Flow-bill signature | Owned by |
|---|---|---|---|
| **Beaconing** | An infected host phones its C2 on a regular clock to fetch orders. | Same tiny flow, same counterpart, repeated at a fixed cadence. | `entity_monotony` (self-similarity of one actor's own events) + sub-second timing rules **if the clock is fine enough** |
| **Fan-in star (passive C2)** | Many infected hosts all beacon to **one** C2 server. | One destination with huge in-degree; every source monotone. | `entity_monotony` + the **hub gate** (`MIN_HUB_DEGREE = 3` distinct counterparts) |
| **Fan-out / spam-scan (broadcasting source)** | One infected host sprays many destinations (spam, port scan, click fraud). | One source with anomalously high out-degree, asymmetric to its in-degree, monotone in service. | `asymmetric_degree` (narrowed to the **source fan-out** shape) |
| **Human-mimicking web bot** | An evasive scraper/bot that spoofs a real browser and paces itself like a person. | Diffuse, low-volume, no beacon cadence — deliberately shapeless. | **No existing rule** — needs web-specific signals (mouse dynamics); open, tracked as TODO item 12 → `bwl-webbot-campaign` |

Two consequences worth internalising:
- **Fan-in and fan-out are different rules.** `asymmetric_degree` was *direction-agnostic* originally and
  fired on both; that wrecked precision on Rbot (§5). It now covers **source fan-out only**; fan-in C2s are
  `entity_monotony`'s job. This split is a load-bearing design decision (`bwl-architecture-contract`).
- **The web-bot shape is unsolved on purpose.** The flow/timing rules do not transfer to it (measured
  negative, §5 Bournemouth). Closing it is a new capability, not a tweak.

---

## 3. Directional labels — why `To-*` rows are excluded from truth

CTU-13's `Label` is **directional**. For the infected host it distinguishes:

| Label prefix | Meaning | Used as ground truth? |
|---|---|---|
| `From-Botnet` | Flow **generated by** the infected host (its own outbound behaviour). | **YES — positive.** This is bot *behaviour*. |
| `To-Botnet` | Traffic **towards** the infected host from others (scans, backscatter, victims). | **NO — excluded.** The sender is not necessarily a bot; attributing it to the target would be wrong. |
| `To-Normal`, `Background`, `Normal`, `LEGITIMATE` | Everything else. | Negative / background. |

The benchmark encodes exactly this policy (`evaluation/ctu13_bot_benchmark.py`): `POSITIVE_PREFIX =
"From-Botnet"`; `To-Botnet` / `To-Normal` are **excluded entirely** so they can never be scored as either a
hit or a false alarm. In scenario 1 there are in fact no `To-Botnet` rows, so the exclusion is *defensive* —
but keep it, because scenario 3 and others do carry them. The real label strings are verbose, e.g.
`flow=From-Botnet-V42-TCP-Attempt-SPAM`, `flow=From-Botnet-V42-TCP-CC1-HTTP-Not-Encrypted` (the `V42` ties
the row to CTU-Malware-Capture-Botnet-**42** = scenario 1; the `CC*` variants are individual C2 channels,
`SPAM` is the spam campaign). Match on the **prefix**, never the full string.

---

## 4. Timestamp resolution — the axis the two primary benchmarks split on

The single most important real-data fact: **how fine is the clock?** Beacon-cadence rules need sub-second
timing. If the source quantised timestamps to whole minutes, those rules cannot fire and the detector
**adaptively gates them off** so whole-minute bins do not spew false positives.

| Capture | Clock | Dense-timing rules | Bot shape here |
|---|---|---|---|
| CTU-13 (`.binetflow`) | **Microsecond** (`…09:46:53.058760`) | **Active** | Fan-out source (Neris) / scan-DDoS (Rbot) |
| CICIDS2017 (Friday morning) | **Minute**, quantised *at source* (`6/7/2017 8:59`) | **Gated off** | Fan-in star (Ares) — caught by concentration, not timing |

That contrast — fine clock + fan-out vs coarse clock + fan-in — is *the point* of running both. It is not a
precision competition between them.

**The CTU-13 precision trap (know this before touching `entity_monotony`).** On the diverse NetFlow
background, the `Proto` and `State` categorical columns are *degenerate* (a handful of repeated values), so
per-entity self-similarity baselining over them made almost every background host look "monotone" and
over-flagged. The fix was an **actor cardinality-ratio band** (roughly 0.02–0.5 distinct/rows): baseline only
over columns whose cardinality sits in that band, excluding the degenerate categoricals. This lifted verified
CTU-13 sc1 precision 0.041 → **0.978** with recall held. `asymmetric_degree` was untouched and still carries
the recall. (Mechanism/maths: `bwl-detection-theory`; incident: `bwl-failure-archaeology`.)

---

## 5. Dataset dossier

One section per real capture. **None of these files are committed** (`data/` is gitignored except its
README); download from the cited source. All numbers below are **recorded** in `evaluation/BENCHMARKS.md` /
`FINDINGS.md` (verified 2026-07-06 at repo commit 6fd33ac) — they are *synthetic-free, externally-labelled*
measurements, but still single-capture results, **not** production guarantees and **not** fraud verdicts.

### CTU-13 — the primary fine-clock benchmark (two families)

- **Provenance / licence.** Stratosphere Laboratory, CTU University, Prague. **CC-BY**
  (<https://creativecommons.org/licenses/by/2.0/>). Cite: S. García, M. Grill, J. Stiborek, A. Zunino, "An
  empirical comparison of botnet detection methods," *Computers & Security* 45 (2014) 100–123.
- **Shape.** 13 scenarios, each a real botnet run captured as Argus **bidirectional NetFlow**, microsecond
  clock. The benchmark samples 60,000 background + 2,000 bot ≈ **62,000 rows**, base rate ≈ 0.032.
- **Scenario 1 = Neris** (`data/capture20110810.binetflow`, CTU-Malware-Capture-Botnet-**42**, 369 MB). One
  infected host **`147.32.84.165`** runs Neris: **spam, C2, click-fraud**. It is a **broadcasting fan-out
  source** — the shape `asymmetric_degree` owns. This is the family the asymmetry rule was developed against.
  Fetch:
  ```bash
  curl -o data/capture20110810.binetflow \
    https://mcfp.felk.cvut.cz/publicDatasets/CTU-Malware-Capture-Botnet-42/detailed-bidirectional-flow-labels/capture20110810.binetflow
  ```
- **Scenario 3 = Rbot** (`data/capture20110812.binetflow`, Botnet-**44**, 640 MB) — the **generality probe**:
  a *different* bot (an IRC-controlled DDoS/scan botnet), captured the same way, run to test whether the win
  transfers beyond Neris. Fetch as above but Botnet-44/`capture20110812.binetflow`, then
  `uv run --extra eif python -m evaluation.ctu13_bot_benchmark --scenario sc3`.
- **What it proves / recorded numbers.**

  | Scenario | Recall | Precision | Flag rate | Note |
  |---|---|---|---|---|
  | sc1 / Neris | **1.000** | **0.978** | 0.033 | Fan-out; precision after the actor-band fix (was 0.041). |
  | sc3 / Rbot | **0.985** | **0.929** | 0.034 | **Recall generalised immediately** (0.985). Precision did *not* under the direction-agnostic rule (**0.056** at flag 0.567 — it fired on benign fan-in infrastructure); narrowing `asymmetric_degree` to the **source fan-out** shape recovered it to 0.929, recall held, **no thresholds tuned**. |

  The two-part Rbot story (recall transfers, precision must be earned per shape) is the clearest generality
  evidence in the repo — but it is still only two CTU-13 families, not an independent corpus. See
  `evaluation/FINDINGS.md` "The second-family test".

### CICIDS2017 — the coarse-clock / fan-in benchmark (Ares)

- **Provenance / licence.** Canadian Institute for Cybersecurity (CIC), University of New Brunswick.
  **Academic terms, registration required** — *not* CC-BY. <https://www.unb.ca/cic/datasets/ids-2017.html>.
  Cite: Sharafaldin, Lashkari, Ghorbani, ICISSP 2018.
- **Shape.** Friday-morning capture, NetFlow-style export. Benchmark = 60,000 sampled benign + all bot ≈
  **61,966 rows**, base rate ≈ 0.032. Label ∈ {`Bot`, `BENIGN`}. Archive: `data/GeneratedLabelledFlows.zip`,
  inner file `TrafficLabelling /Friday-WorkingHours-Morning.pcap_ISCX.csv` (the trailing space in the folder
  name is upstream, not a typo).
- **The bot.** The **Ares** botnet: a **passive fan-in star** — many infected hosts beacon to one C2 at
  **`205.174.165.73`** with near-identical flows. **Minute-quantised at source**, so timing rules are gated
  off (§4); the catch is carried by concentration/repetition (`entity_monotony`) + the hub gate.
- **What it proves / recorded numbers.** **Recall 0.998, precision 0.846, flag 0.037.** This is the
  headline "works on real, coarse-clock, fan-in" result. History: precision climbed 0.018 → 0.144 → 0.441 →
  **0.846** across the diversity baseline, hub gate, and timing calibration (`FINDINGS.md` "results history").
  Precision 0.846 is *this one capture*, not a field guarantee.

### UNSW-NB15 — secondary, mixed-family stress (raw shards)

- **Provenance.** UNSW Canberra (ACCS). **Secondary tier** — a *mixed* attack corpus, not a single isolated
  beaconing botnet, so it is a generality stressor rather than a headline.
- **Shape.** Nine attack families mixed under `Label == 1` (fuzzers, exploits, DoS, reconnaissance, …). The
  benchmark needs the **raw headerless shards** `data/UNSW-NB15_1.csv` … `_4.csv` (49 columns; the canonical
  header is applied in code — see `RAW_COLUMNS` in `evaluation/unsw_benchmark.py`), which carry `srcip` /
  `dstip` / `Stime` / `Label`. Only `_1.csv` is present locally by default.
- **What it proves / recorded numbers.** **Recall 0.122, precision 0.198, flag 0.020.** A deliberately
  **low** result: a detector tuned for beaconing automation is *not* expected to catch a grab-bag of
  one-shot exploits. It exists as a no-regression guard (it must not spike the flag rate), not a win.

### Bournemouth web-bot logs — domain-transfer negative (provisional, licence-pending)

- **Provenance / licence.** CERTH ITI / Bournemouth University (m4d.iti.gr). **Licence unclear** — research
  use invited, copyright reserved → **internal-only**; numbers **not cleared for publication or
  redistribution** pending a licence decision (`bwl-external-positioning`). Archive:
  `data/web_bot_detection_dataset.zip`.
- **Shape.** This is the **opposite domain**: raw HTTP **server access logs**, not network flows. Custom
  Apache combined format `%h %l [%t] "%r" %>s %b "%{Referer}" SESSIONID "%{User-Agent}"`. The host (`%h`) is
  anonymised to `-` in *every* line — **there is no IP**; the actor entity is the **per-session id** (8th
  field). Label is the dataset's own **folder split**: `phase1/data/web_logs/bots/` vs
  `web_logs/humans/` (bot tier advanced/moderate). ≈ **58,279 rows**, base rate ≈ 0.029. The archive also
  ships **mouse-movement JSON** per session (`phase1/data/mouse_movements/…`) — the raw material for the
  future interaction-biometric capability.
- **What it proves / recorded numbers.** **Recall 0.474, precision 0.020, flag 0.681 — a NEGATIVE result,
  and precision (0.020) sits *below* the base rate (0.029)** (worse than guessing; see §6). Two mechanisms:
  (1) sessions are few and large, so `session_id` cardinality ratio ≈ 0.005 falls **below the actor band** →
  actor rules go dormant; (2) the advanced/moderate bots spoof real browser UAs (only ~4 distinct), so
  diversity signals blur. **Interpretation:** flow/timing automation signals **do not transfer** to evasive,
  human-mimicking web bots. This is *why* TODO item 12 exists. Read the row as a domain-transfer probe, not
  a tuning failure. (`bwl-webbot-campaign`.)

### Candidate datasets that were assessed and SKIPPED

Do not waste a session re-litigating these (recorded in `BENCHMARKS.md` "Datasets assessed and skipped"):

| Candidate | Why skipped |
|---|---|
| Zenodo 3477932 web-robot logs (CC-BY-4.0) | Labelled files are per-session **aggregates** with no raw entities/timestamps; the raw events have no joinable label. Deriving one from IP/UA/time = **circular leakage** (the detector keys on those). |
| Kaggle ISIT-2024 "Bits and Bots" | Accessible files are **two bot classes** (`gremlins/`, `hlisa_traces/`); HLISA *generates* human-**like** bot traces — **not real humans**. A run would be bot-vs-bot. **HLISA must never be labelled "human."** Skipped per boss decision. |
| Kaggle `tunguz/clickstream…` | No labels; surfaced over-long sessions only. |

Clean, event-level, real-human-labelled **web-bot** corpora are genuinely scarce — that scarcity, not lack
of effort, is why the web-bot capability rests on one licence-pending negative.

---

## 6. Metrics at rare base rates — read this before trusting any number

Bots are **rare** (base rate a few percent), which breaks intuitions built on balanced data. Four terms
(maths detail in `bwl-detection-theory`):

| Term | Definition | On the CTU-13 sc1 worked example |
|---|---|---|
| **Base rate** | Fraction of rows that are *truly* bots. | 2,000 / 62,000 = **0.032** |
| **Flag rate** | Fraction the detector *flags*, right or wrong. | ≈ 0.033 → ≈ 2,046 rows flagged |
| **Recall** | Of the true bots, the fraction caught (TP / actual positives). | 2,000 / 2,000 = **1.000** |
| **Precision** | Of the flagged rows, the fraction that are truly bots (TP / flagged). | 2,000 / 2,046 ≈ **0.978** |

**The rule that catches people out:** *precision below the base rate means the detector is worse than random
guessing.* If 3.2% of rows are bots and you flag a bunch at 2.0% precision (Bournemouth), a flagged row is
*less* likely to be a bot than a row picked blind. High recall with sub-base-rate precision is **not** a
success — it is a flag firehose. Always check precision against the base rate before celebrating recall.

Guardrail context: the live decision rule is `is_bot = heuristic ≥ 0.70 OR ml_score > dynamic knee
threshold`, and the ML side is **rate-capped at 2%** so it cannot flood. On unlabelled production data the
detector **cannot measure its own precision** — only a labelled benchmark can. Never present a synthetic or
single-capture number as field accuracy; scores are anomaly rankings, **not probabilities**
(`bwl-change-control`, `bwl-external-positioning`).

---

## 7. Synthetic ARCHETYPES vs real FAMILIES — never conflate

Two completely different sources of "bots" live in this repo. Keep them apart in every sentence you write.

| | Synthetic **archetypes** | Real malware **families** |
|---|---|---|
| What | *Invented* behaviours planted into an unlabelled log by `bots_without_labels/inject.py` | Actual botnets captured in the wild |
| Names | `burst`, `mechanical_timing`, `diffuse_replay`, `stealth` (the `ARCHETYPES`/`DETECTABLE_ARCHETYPES` tuples are defined in `bots_without_labels/synthetic.py:23-24` and re-used by `inject.py`; only `burst` + `mechanical_timing` are `DETECTABLE_ARCHETYPES` — the timing ones the rules target) | **Neris** (CTU sc1), **Rbot** (CTU sc3), **Ares** (CICIDS) |
| Purpose | Stress test / regression: you planted them, so recall ≈ 1.0 is *by construction* | The real accuracy question: externally labelled, someone else drew the line |
| Trust | A green synthetic run means "no regression," **not** "works in the field" (detector + generator share one assumption) | Only these earn a row in `BENCHMARKS.md` |

Say "the `mechanical_timing` **archetype**" and "the **Neris family**" — never "the beacon bot" ambiguously.
The sample files under `data/samples/` (e.g. `hf_access_logs.csv`, the Kaggle clickstreams) are convenience
fixtures, not labelled field benchmarks.

---

## 8. Literature anchors (as cited by the repo)

These ground the *anomaly signal*; none is a ground-truth fraud label. Full detail: `FINDINGS.md`
"References" (external refs web-verified 2026-06-24 against dblp/Springer/USENIX).

| Work | What it anchors |
|---|---|
| **García et al. 2014**, *An empirical comparison of botnet detection methods*, Computers & Security 45:100–123 | The **CTU-13 dataset** itself. |
| **OddBall** — Akoglu, McGlohon, Faloutsos, PAKDD 2010 | **Near-star / degree** egonet anomalies — the structural pattern `asymmetric_degree` keys on. |
| Akoglu, Tong, Koutra, *Graph based anomaly detection: a survey*, DMKD 29(3) 2015 | Frames star/near-star and degree-distribution outliers as a primary structural-anomaly class. |
| **BotMiner** — Gu, Perdisci, Zhang, Lee, USENIX Security 2008 | Botnets are separable by **communication structure** (who-talks-to-whom), independent of protocol/payload — the premise the actor graph operationalises. |

---

## Provenance and maintenance

Authored 2026-07-04 (content re-verified 2026-07-06); repo at commit 6fd33ac. Numbers cited from
`evaluation/BENCHMARKS.md` and `evaluation/FINDINGS.md` and marked as recorded, not re-run (the full suite is
slow and gitignored data may be absent). Re-verify each volatile fact with the one-liner below.

| Fact | Re-verify (read-only) |
|---|---|
| Benchmark numbers (recall/precision/flag) | `grep -nE "Recall\|0\.978\|0\.929\|0\.846\|0\.474" evaluation/BENCHMARKS.md` |
| CTU-13 label policy (`From-Botnet` positive, `To-*` excluded) | `grep -nE "POSITIVE_PREFIX\|To-Botnet\|EXCLUDED" evaluation/ctu13_bot_benchmark.py` |
| CTU sc1 real label strings + infected host | `grep -aoE "flow=From-Botnet[^,]*" data/capture20110810.binetflow \| sort -u \| head` |
| Scenario → capture file map (sc1=Botnet-42, sc3=Botnet-44) | `grep -nE "SCENARIOS\|Botnet-4[24]\|capture2011081" evaluation/ctu13_bot_benchmark.py` |
| CICIDS host / minute clock / inner file | `grep -nE "205.174.165.73\|8:59\|Friday-WorkingHours" evaluation/cicids_bot_benchmark.py evaluation/BENCHMARKS.md` |
| Bournemouth format / no-IP / session actor / mouse data | `grep -nE "%h\|session\|humans/\|mouse" evaluation/bournemouth_benchmark.py` |
| Rule names owning each shape | `grep -nE "entity_monotony\|asymmetric_degree\|MIN_HUB_DEGREE" bots_without_labels/rules.py` |
| Synthetic archetype names | `grep -nE "ARCHETYPES\|DETECTABLE_ARCHETYPES" bots_without_labels/synthetic.py` |
| Decision rule / 2% rate cap | see `bwl-config-and-flags`, `bwl-detection-theory` |
| Repo commit these facts were pinned to | `git log --oneline -1` (expect 6fd33ac or a documented successor) |

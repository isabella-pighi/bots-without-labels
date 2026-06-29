# Real-data evaluation findings

The synthetic suite reports ~1.0 recall, but it is generated to carry exactly the
signatures the detector looks for, so it cannot tell us whether the method works
on real traffic. This is the record of testing it against independent, labelled
data, what failed, and what changed.

## What we ran

Three exploratory external sources plus two constructed, fair real-data benchmarks:

| Source | Dataset | Result |
|---|---|---|
| HuggingFace | `mindweave/web-server-logs` | flagged-rows' bot-UA rate ≈ base rate (no lift) |
| Kaggle | `tunguz/clickstream-data-for-online-shopping` | no labels; surfaced over-long sessions only |
| Local zip | CICIDS2017 PortScan flows | attacks were 55% of the sample → not anomalous |
| **Benchmark** | **CICIDS2017 Friday-morning botnet (Ares)** | **see below** |
| **Benchmark** | **CTU-13 scenario 1 (Neris)** | **see below** |

The first three were not fair tests: bots were either the majority, unlabelled,
or the timestamps too coarse for the timing rules. We kept two externally
labelled botnet captures, each a rare-attack (~1–3%) target the method is *meant*
to handle, but chosen to contrast on opposite axes:

- **CICIDS2017 Friday-morning** (`cicids_bot_benchmark.py`) is minute-quantised
  *at source*, so the sub-second timing rules have nothing to work with — and the
  bot is a **passive fan-in star** (many hosts beacon one C2).
- **CTU-13 scenario 1** (`ctu13_bot_benchmark.py`) is an Argus NetFlow capture
  with **microsecond** timestamps, and the bot is the opposite shape — one host
  *reaching out* to many destinations (spam + C2 + click fraud).

Together they separate a **data limit** (CICIDS lacks timing resolution) from a
**method limit** (CTU-13 has the resolution, yet timing alone still missed the
bot — see the third discriminator below).

## The failure

On the fair botnet benchmark, the pre-fix detector scored:

```
recall 0.022   precision 0.018   (base rate 0.032)
```

Precision **below the base rate** means a flagged row was *less* likely to be a
bot than one chosen at random. Root cause was a design tension, not a bug:

- The bot signal is concentration/repetition — the infected hosts beacon to one
  C2 (`205.174.165.73`) with near-identical flows.
- The "honest archetype" audit had downgraded repetition/concentration to
  *supporting-only* (capped at 0.24) to avoid flagging popular legitimate values,
  leaving only sub-second **timing** as strong evidence.
- Real logs here are minute-resolution, so the adaptive timing thresholds are set
  by busy benign minutes and never fire on the bot.

Net: the heuristics flagged busy-but-benign entities and missed obvious bots. The
synthetic suite stayed green because it privileges precisely the timing signature
real logs here lack — detector and benchmark sharing one assumption.

## The fix: per-entity behavioural diversity

Instead of *global* concentration (which fires on popular-but-human values), score
each **entity** (actor-like column, e.g. Source/Destination IP) by how
self-similar its *own* events are — the mean normalised entropy of its behaviour
across the other columns. A botnet host does one thing repeatedly (low diversity);
a popular legitimate host fans out (high diversity). See
`features.py::_entity_baseline` and the `entity_monotony` rule in `rules.py`.

Result on the same benchmark: recall went from near-zero to near-total, but
precision was only 0.144 at a 21.9% flag rate. Per-entity diversity is a strong
*ranking* signal, not a clean separator: a busy *legitimate* channel — a backup
job, a keepalive, one client hammering one server — is just as monotonous as a
beacon, and on real traffic these dominate the monotonous tail. Diversity alone
cannot tell them apart.

## The second discriminator: relational hub structure (roadmap item 9)

The remaining false positives and the genuine bots differ not in *how repetitive*
they are but in *how they are connected*. This is where the graph view (roadmap
item 9, "graph features on stable identifiers") earns its place, promoted for the
entity-monotony case.

In a network-flow capture each row is an edge between two stable identifiers —
here Source IP → Destination IP. A command-and-control server is a **hub**: a
single destination that many distinct compromised hosts converge on (a fan-in
star). A legitimate monotone channel is **point-to-point**: a single source
talking to a single destination, over and over. Both look identical to a
diversity-only view; they are obviously different the moment you count *distinct
counterparts* — the node's **degree**. High degree on a near-zero-diversity node
is the classic star-shaped anomaly that flow- and graph-anomaly methods key on
(e.g. the near-star pattern in graph outlier detection), and it is exactly the
shape a beaconing botnet draws.

So we no longer escalate `entity_monotony` to a strong, on-its-own flag on
monotony alone. When the log exposes relational structure — at least two stable
entity columns, so edges exist — a monotonous high-volume entity is escalated
**only if it is also a hub**, communicating with at least `MIN_HUB_DEGREE = 3`
distinct counterparts. `K = 3` is a deliberately small structural minimum (a star
needs more than a pair of spokes); it is *not* tuned to this botnet's observed
fan-out, which would be overfitting to one capture. When no such structure exists
(one or zero entity columns), the rule falls back to firing on monotony alone, so
single-identifier and low-dimensional logs are unaffected. See
`features.py::_entity_baseline` (now also computing per-column degree) and
`_hub_entity` in `rules.py`.

On the same CICIDS benchmark (n = 61,966 rows, base rate 0.032), the discriminator
lifted precision roughly threefold and more than halved the flag rate with no loss
of recall; subsequent timing calibration on this branch lifted it further. The
last row is the **current** branch output; the middle two are historical
intermediate stages, kept to show the progression:

| Stage | recall | precision | flag rate |
|---|---|---|---|
| Pre-fix (global concentration capped) | 0.022 | 0.018 | — |
| Per-entity diversity baseline | 0.998 | 0.144 | 0.219 |
| + relational hub discriminator (historical) | 0.998 | 0.441 | 0.072 |
| **+ later timing calibration (current branch)** | **0.998** | **0.846** | **0.037** |

The last row reproduces today with
`uv run --extra eif python -m evaluation.cicids_bot_benchmark --zip data/GeneratedLabelledFlows.zip`.
The new `asymmetric_degree` rule does **not** fire on CICIDS: the actor graph
builds (`Source IP` / `Destination IP` endpoints, degree floor ≈ 551), but no row
clears the combined asymmetry/floor/monotony gate, so the CICIDS result and its
no-regression are **not** credited to the new actor rule — they come from the
timing calibration.

## The honest ceiling

Precision 0.846 is the current measured number on *this* labelled capture — it is
not a production guarantee, and not proof that any flagged row is fraud. Four
caveats keep it honest:

- **It is anomaly-style evidence, not a fraud verdict.** The method is
  unsupervised; in production it ranks structurally unusual entities, and a hub
  flag means "monotone fan-in star", not "confirmed bot". The benchmark can
  measure precision only because CICIDS ships labels; the running system cannot.
- **It is one attack family and one hub.** The lift leans on a single, uniquely
  separable C2 (`205.174.165.73`). We did not tune `K` to it, but a 0.846 figure
  from one capture must not be read as a general precision, nor as evidence that
  `K = 3` is universally correct.
- **Benign monotone hubs remain a plausible risk for the `entity_monotony`
  gate.** A DNS resolver, an NTP source, a load balancer, or a backup target is
  *also* a low-diversity, high-degree node, so the gate *could* flag one. Degree
  narrows this risk; it does not eliminate it. Where timestamp resolution allows,
  sub-minute timing cadence is the next discriminator to separate a beacon from a
  busy benign hub.
- **The headline 0.846 is the whole detector, not the hub gate, and the residual
  error is mostly not heuristic.** Precision 0.846 means 15.4% of *all* flagged
  rows are not labelled bot in this capture — but that is the detector as a whole.
  A checked per-rule diagnostic on this branch (2,320 flags; 358 false positives)
  shows `entity_monotony` fired on 2,067 rows with ~104 false positives
  (fire-precision 0.949) and carries 1,938 of the 1,962 true-positive catches. Of
  the 358 false positives, ~253 come from the ML/EIF scorer alone (ML-only flags,
  attributable to no heuristic rule) and ~104 from `entity_monotony`; the other
  heuristic rules contribute essentially none. So the residual error is *not*
  dominated by benign monotone hubs — most of it is the ML path, a separate
  calibration question.

Two further limits are tracked as follow-ups, not fixed on this branch:

- **The diversity cut is a fixed 10th-percentile quantile.** On real flow data
  many entities share identical diversity values, so the quantile lands on a
  tie at a bin edge and the cut becomes sensitive to how ties break. A robust
  fix needs an *adaptive* cut (gap/knee detection on the diversity distribution),
  not a fixed quantile — a redesign, deferred to the threshold-calibration work.
- The rule stays deliberately **dormant on low-dimensional logs** (few columns →
  every actor looks monotonous, carrying no signal), via an absolute diversity
  ceiling. That is why the synthetic suite is unaffected.

## The third discriminator: asymmetric endpoint degree (CTU-13 / Neris)

The two CICIDS discriminators above handle a *passive fan-in star*: one C2 that
many monotone hosts beacon to. CTU-13 scenario 1 is the opposite shape, and the
one those rules miss. A single infected host (`147.32.84.165`) runs the Neris
botnet — spam, command-and-control, and click fraud — so it *reaches out to many
distinct destinations*. Connecting to many counterparts reads as **high**
behavioural diversity, so both the monotony rule and the diversity-gated hub rule
walk straight past it. On the fine-resolution CTU-13 mix the detector *before*
this work scored:

```
recall 0.1130   precision 0.0048   flag rate 0.7568   (base rate 0.032)
```

This was the documented **method limit**: sub-second timestamps alone — the thing
CICIDS lacked — did not recover the bot. The missing signal is neither timing nor
monotony; it is the **directional asymmetry of connectivity**.

### What shipped — and what it is not

The candidate began as a `directional_fanout` rule, but was deliberately reframed.
A schema-generic detector *cannot reliably tell a source column from a destination
column* without name or schema hints, and inferring direction from column names is
a coupling we have intentionally avoided throughout. So the shipped rule is
**direction-agnostic**: `asymmetric_degree`. It does **not** assert which way the
traffic flows.

It builds an **undirected relational actor graph** when the log exposes stable
actor-endpoint columns, and stays dormant when it does not (so low-dimensional
logs and the synthetic suite are unaffected):

- **Endpoint columns are chosen by shape, never by name** (`_actor_endpoint_columns`
  in `features.py`): a recurring, high-cardinality token column whose
  cardinality ratio sits in a band (`ACTOR_MIN_RATIO` = 0.02 to
  `ACTOR_MAX_RATIO` = 0.5). The band separates a genuine actor (an address, an
  account) from the two things it is confused with — a *bounded categorical*
  below the band (protocol, TCP state, region) and a *per-row edge identifier*
  above it (a flow id, a composite 5-tuple). This is what keeps **actor-endpoint
  columns separate from bounded context columns**.
- For each row's endpoint the graph records its **degree** (distinct counterparts
  in its own role), its **reverse-role degree** (the same value's degree when it
  appears in the *other* endpoint column — 0 if it never does), its volume, and
  its diversity over **context columns only** — excluding the counterpart
  endpoint, so a star that is diverse *in counterparts* but monotone *in service*
  still reads as low diversity.
- The `asymmetric_degree` rule (strong, weight 0.70) fires on a high-volume
  endpoint whose degree exceeds an **adaptive floor** (the 99th-percentile of the
  batch's own hub-subset degrees, `DEGREE_FLOOR_PERCENTILE`), **and** exceeds its
  reverse-role degree by an order of magnitude (`DEGREE_ASYMMETRY` = 10), **and**
  is monotone in service. Because the graph is undirected, this reads the
  *asymmetry between a value's two roles*, not a verified fan-out — so it covers
  both a broadcasting source (spam/scan/click-fraud) **and** a passive fan-in hub.

### Result

| Stage | recall | precision | flag rate |
|---|---|---|---|
| Before (timing/monotony only) | 0.113 | 0.005 | 0.757 |
| + asymmetric_degree | 1.000 | 0.041 | 0.785 |
| **+ actor-band entity gating (current)** | **1.000** | **0.978** | **0.033** |

Reproduce with `uv run --extra eif python -m evaluation.ctu13_bot_benchmark`
(n = 62,000 rows, base rate 0.032, microsecond timestamps, dense-timing rules
*active*). A per-rule diagnostic on this constructed split shows `asymmetric_degree`
fires on **2,000 of 2,000** positives with **zero** false fires, and *uniquely*
carries **1,774** of them (the other 226 also trip another rule). On this split it
is a clean catch.

### The precision fix: keep degenerate categoricals out of per-entity baselining

The middle-row 0.041 precision was never the new rule's doing — it came from
`entity_monotony` treating the degenerate `Proto` / `State` columns as if they were
actors and over-flagging the diverse NetFlow background (see the honest ceiling
below). The fix reuses machinery already in the codebase: the **actor
cardinality-ratio band** (`ACTOR_MIN_RATIO` = 0.02 to `ACTOR_MAX_RATIO` = 0.5) that
`_actor_endpoint_columns` uses to pick graph endpoints by *shape* is now also
applied to the columns `entity_monotony` baselines over (`_entity_columns`). `Proto`
and `State` are *bounded categoricals* — a handful of distinct values across the
whole batch — so their cardinality ratio sits **below** the band, and they are
excluded from per-entity baselining. A real actor column (`Source`/`Destination`
address) sits **in** the band and is kept. No constant was tuned to CTU-13; the same
band that already typed graph endpoints now types monotony entities.

The effect, verified end-to-end: CTU-13 precision rises **0.041 → 0.978** and the
flag rate falls **0.785 → 0.033**, with recall held at **1.000**. An earlier
per-rule *counterfactual projection* (removing the degenerate-column fires from the
diagnostic) estimated **0.956**; that was a projection, and the **actual verified
precision on the re-run pipeline is 0.978** — the number to cite. `asymmetric_degree`
is unchanged and still carries the recall (2,000/2,000, zero false fires). CICIDS is
**unchanged** (recall 0.998, precision 0.846, flag rate 0.037): there `Source IP` /
`Destination IP` stay *in* the band, so `entity_monotony` keeps its recall-carrying
role on that capture — the fix removes only the degenerate categoricals, not the
genuine actor columns.

The same band change also moved the **secondary** UNSW-NB15 broad-IDS check
(`evaluation/BENCHMARKS.md`): recall 0.561 → 0.122, precision 0.090 → 0.198, flag
rate 0.201 → 0.020. Its earlier recall was partly the *same* degenerate-column
over-flagging, so the stricter gating made that breadth check **more conservative
and honest, not strictly better** — and since UNSW-NB15 is a broad IDS dataset, not
a bot capture, the lower recall is no bot regression.

*Verification: rina-approved (review #37205) against mono's measured benchmark table
(#37143).*

### The honest ceiling (CTU-13)

Read this as *hypothesis-supporting evidence within one botnet family*, not a
solved problem:

- **Same-family evidence only.** Recall 1.0000 is on CTU-13 / Neris — the same
  family the rule was developed against. It supports the hypothesis that
  connectivity asymmetry recovers a diverse directional bot; it is **not** a
  general solution, nor proof that recall recovers on unseen families. A second
  labelled family or scenario remains future validation.
- **The over-flagging that capped precision is now fixed (0.041 → 0.978).** The low
  middle-row precision came from *pre-existing broad rules* over-flagging the diverse
  NetFlow background — notably `entity_monotony` on the degenerate `Proto`/`State`
  columns — never from the new rule. The actor-band entity gating above excludes
  those degenerate categoricals, lifting verified precision to **0.978** at a 0.033
  flag rate with recall held. This was the separate calibration question flagged
  here; it has now been addressed, not left as a standing limit.
- **Passive fan-in hubs fire by design.** Because the rule is direction-agnostic,
  a benign monotone server, DNS resolver, NTP source, or load balancer — a real
  one-sided star — is an **explicit false-positive risk**. Degree asymmetry
  narrows it; it does not eliminate it. Sub-minute timing cadence is the natural
  next discriminator where resolution allows.
- **The constants are limited-evidence guardrails, not universal constants.**
  `DEGREE_ASYMMETRY` = 10 and the 99th-percentile floor hold for asymmetry factors
  ≈ 10–100 on this one split plus a synthetic broadcaster; the rule over-fires
  below ≈ 10 and vanishes at ≥ 200 (beyond Neris's own ratio). They are *not*
  scale-free, and should not be read as tuned constants for other captures.

## Takeaway

The skeleton (unsupervised, role-driven, explainable) is sound; the gap was
calibration plus a missing per-entity view, and a benchmark that never tested
reality. The per-entity baseline recovered the passive fan-in bots; the relational
hub gate removed the busy-benign point-to-point channels that diversity alone could
not distinguish; and the undirected actor graph (`asymmetric_degree`) added the one
shape both missed — a diverse, high-degree endpoint that is asymmetric in its
connectivity. `tests/test_real_benchmark.py` pins the CICIDS stacked wins (recall
≥ 0.95, precision ≥ 0.35, flag rate ≤ 0.12); `tests/test_ctu13_benchmark.py` pins
the CTU-13 recall win (≥ 0.95). The separate rule that originally capped CTU-13
precision — `entity_monotony` over-flagging the degenerate `Proto`/`State` columns —
has since been calibrated by the actor-band entity gating, lifting verified CTU-13
precision to 0.978 with recall held. Both guards mean a future change that silently
reintroduces a real-data blind spot fails even with the synthetic suite green.

## References

The pattern `asymmetric_degree` keys on — a node whose degree is anomalously high
and asymmetric relative to its neighbourhood — is the classic **near-star** graph
outlier, long established in graph- and flow-anomaly research:

- **CTU-13 dataset.** S. Garcia, M. Grill, J. Stiborek, A. Zunino, "An empirical
  comparison of botnet detection methods," *Computers & Security* 45 (2014)
  100–123. (Cited in `evaluation/ctu13_bot_benchmark.py`; licence CC-BY.)
- **OddBall — degree/star egonet anomalies.** L. Akoglu, M. McGlohon, C.
  Faloutsos, "OddBall: Spotting Anomalies in Weighted Graphs," *PAKDD 2010*, LNCS
  6119, pp. 410–421. Establishes that a node's degree, weight, and neighbourhood
  follow predictable power laws, and that *near-star* nodes — high degree, sparse
  interconnection among neighbours — are a canonical structural anomaly.
- **Survey of graph anomaly detection.** L. Akoglu, H. Tong, D. Koutra,
  "Graph based anomaly detection and description: a survey," *Data Mining and
  Knowledge Discovery* 29(3) (2015) 626–688, DOI 10.1007/s10618-014-0365-y. Frames
  star/near-star and degree-distribution outliers as a primary structural-anomaly
  class.
- **Botnet communication structure.** G. Gu, R. Perdisci, J. Zhang, W. Lee,
  "BotMiner: Clustering Analysis of Network Traffic for Protocol- and
  Structure-Independent Botnet Detection," *USENIX Security 2008*, pp. 139–154.
  Establishes that botnets are separable by their *communication structure* —
  who-talks-to-whom — independent of protocol or payload, which is the premise the
  actor graph operationalises.

*Sourcing note:* the three external graph/botnet references were verified by web
search on 2026-06-24 against dblp, Springer, and the USENIX proceedings; the
CTU-13 citation is taken from the repository's own benchmark module. No claim here
should be read as a fraud verdict — these works ground an *anomaly* signal, not a
ground-truth label.

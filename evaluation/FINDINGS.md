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
| + later timing calibration | 0.998 | 0.846 | 0.037 |
| **+ ML-tail sentinel decouple (current branch)** | **0.998** | **0.879** | **0.036** |

The last row reproduces today with
`uv run --extra eif python -m evaluation.cicids_bot_benchmark --zip data/GeneratedLabelledFlows.zip`.
The new `asymmetric_degree` rule does **not** fire on CICIDS: the actor graph
builds (`Source IP` / `Destination IP` endpoints, degree floor ≈ 551), but no row
clears the combined asymmetry/floor/monotony gate, so the CICIDS result and its
no-regression are **not** credited to the new actor rule — they come from the
timing calibration.

## The honest ceiling

Precision 0.879 is the current measured number on *this* labelled capture — it is
not a production guarantee, and not proof that any flagged row is fraud. Four
caveats keep it honest:

- **It is anomaly-style evidence, not a fraud verdict.** The method is
  unsupervised; in production it ranks structurally unusual entities, and a hub
  flag means "monotone fan-in star", not "confirmed bot". The benchmark can
  measure precision only because CICIDS ships labels; the running system cannot.
- **It is one attack family and one hub.** The lift leans on a single, uniquely
  separable C2 (`205.174.165.73`). We did not tune `K` to it, but a 0.879 figure
  from one capture must not be read as a general precision, nor as evidence that
  `K = 3` is universally correct.
- **Benign monotone hubs remain a plausible risk for the `entity_monotony`
  gate.** A DNS resolver, an NTP source, a load balancer, or a backup target is
  *also* a low-diversity, high-degree node, so the gate *could* flag one. Degree
  narrows this risk; it does not eliminate it. Where timestamp resolution allows,
  sub-minute timing cadence is the next discriminator to separate a beacon from a
  busy benign hub.
- **The residual error is mostly not heuristic — and its ML-only tail has since been
  cut.** *Before* the ML-tail decouple, precision 0.846 meant 15.4% of *all* flagged
  rows were not labelled bot in this capture — but that is the detector as a whole.
  A checked per-rule diagnostic on that pre-fix branch (2,320 flags; 358 false
  positives) showed `entity_monotony` fired on 2,067 rows with ~104 false positives
  (fire-precision 0.949) and carried 1,938 of the 1,962 true-positive catches. Of
  the 358 false positives, ~253 came from the ML/EIF scorer alone (ML-only flags,
  attributable to no heuristic rule) and ~104 from `entity_monotony`; the other
  heuristic rules contributed essentially none. So the residual error was *not*
  dominated by benign monotone hubs — most of it was the ML path. That ML-only tail is
  exactly what the sparse-timing-sentinel decouple addressed, lifting precision to
  **0.879** (see "Decoupling the sparse-timing sentinel from the ML feature matrix").

Two further limits are tracked as follow-ups, not fixed on this branch:

- **The diversity cut is a fixed 10th-percentile quantile.** On real flow data
  many entities share identical diversity values, so the quantile lands on a
  tie at a bin edge and the cut becomes sensitive to how ties break. A robust
  fix needs an *adaptive* cut (gap/knee detection on the diversity distribution),
  not a fixed quantile — a redesign, deferred to the threshold-calibration work.
- The rule stays deliberately **dormant on low-dimensional logs** (few columns →
  every actor looks monotonous, carrying no signal), via an absolute diversity
  ceiling. That is why the synthetic suite is unaffected.

## Periodicity for slow/jittered beacons — a measured non-starter on our captures

The ceiling above nominates **sub-minute timing cadence** as the next discriminator to
separate a beacon from a busy benign hub, where the timestamp resolution allows. The
microsecond CTU-13 captures have exactly that resolution, so we tested the idea directly
— an **offline, supervised-label diagnostic**, no engine change. For every
`(SrcAddr, DstAddr)` channel with ≥ 30 events, a **robust periodicity score** = the
fraction of consecutive inter-arrival gaps within ±25% of that channel's median gap (an
autocorrelation-peak proxy over the whole series, so periods longer than the 10-second
run window are visible); a channel is labelled bot if the majority of its flows are
`From-Botnet`. Three measured facts, all pointing the same way.

**1. It does not separate bot from benign.**

| Capture | Bot channels (≥ 30 events) | Periodicity AUC | Reading |
|---|---|---|---|
| CTU-13 sc1 / Neris | 170 | 0.552 | no separation (≈ coin-flip) |
| CTU-13 sc3 / Rbot | 1 | 0.833 | **N = 1 — not separation; must not be quoted** |

**2. Zero headroom on the data we own.** 0 of 170 Neris and 0 of 1 Rbot bot beacon
channels have a period > 10 s — every beacon here already sits **inside** the current
10-second run window. Neris beacons are **sub-second bursts**, already owned by
`same_instant_burst` / `local_burst`; the single Rbot beacon is **3.7 s**. So a > 10 s
periodicity feature adds **no measurable recall** on these captures.

**3. Benign traffic is intensely periodic at the very same cadences.** At score ≥ 0.80
and period ≥ 1 s, **756 of 4,248** benign Rbot channels are strongly periodic — at the
same **3.6–3.7 s** cadence as the one Rbot bot beacon. A lone periodicity rule would
flag **756 benign channels to catch 1 bot**. (Neris has 0 benign and 0 bot at period
≥ 1 s, because its beacons are sub-second.)

**Two gates for any future periodicity work.**

1. **A real structural gap — but gated on data we do not own.** Periodicity is the right
   idea for *slow / jittered beacons with period > 10 s*, which the burst rules cannot
   see. But no capture we hold contains such a beacon, so the recall gain is
   **unmeasurable here** and cannot be claimed until a dataset with genuine slow beacons
   is in hand.
2. **Never a lone strong rule.** Benign traffic is periodic at bot cadences (measured
   **756 : 1** on Rbot), so periodicity carries a large false-fire risk. Any future use
   must be **supporting evidence, capped below the 0.70 decision cutoff**, or corroborated
   by the monotony / hub gates — never strong evidence on its own.

**Honest scope.** This tests the CTU-13 **microsecond fast beacons** only; it does *not*
prove slow beacons are undetectable in principle. It shows that on the data we own a
> 10 s periodicity feature has **zero measurable recall headroom and a measured precision
downside**. No detector thresholds were tuned, no rule was added, and the committed
benchmark numbers are unchanged.

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

The candidate began as a `directional_fanout` rule, and **first shipped deliberately
direction-agnostic**. A schema-generic detector cannot reliably tell a source column
from a destination column, and inferring direction by *parsing* column names is a
coupling we avoid. So the first `asymmetric_degree` read the *asymmetry between a
value's two roles* without asserting which way traffic flowed. That choice was later
revisited: the second-family (Rbot) test below showed the direction-agnostic form
over-fires on benign fan-in hubs, so the rule was narrowed to a **source fan-out**
signal — see "Closing the precision gap" in that section. The mechanism described
here is the shared graph machinery; the directional narrowing is the only part that
changed.

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
  is monotone in service. *Initially* — being undirected — this read the asymmetry
  between a value's two roles and so covered both a broadcasting source
  (spam/scan/click-fraud) **and** a passive fan-in hub. The Rbot test showed that
  the fan-in half is where benign infrastructure lives, so the rule was later
  narrowed to fire **only on the source/fan-out side** (see below); passive fan-in
  hubs are now left to `entity_monotony`'s hub escalation.

### Result

| Stage | recall | precision | flag rate |
|---|---|---|---|
| Before (timing/monotony only) | 0.113 | 0.005 | 0.757 |
| + asymmetric_degree | 1.000 | 0.041 | 0.785 |
| + actor-band entity gating | 1.000 | 0.978 | 0.033 |
| **+ ML-tail sentinel decouple (current)** | **1.000** | **0.971** | **0.033** |

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
applied to the columns `entity_monotony` baselines over (`_entity_columns`).
*(The cardinality-ratio band was later found to be scale-dependent and was
replaced with scale-invariant tests — see "Scale-invariant actor selection"
below. The account here describes the mechanism as it stood at the precision
fix.)* `Proto`
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
over-flagging, so the stricter gating made that breadth check more conservative.
*(This was superseded by the later scale-invariant selection, which re-admits
`srcip`/`dstip` and lifts UNSW recall to 1.000 — see "Scale-invariant actor
selection" above. UNSW is a broad IDS dataset, not a bot capture, so neither number
is a bot result.)*

*Verification: rina-approved (review #37205) against mono's measured benchmark table
(#37143).*

### Scale-invariant actor selection: the cardinality-ratio band was scale-dependent

A review of the feature engineering found that the cardinality-ratio band
(`distinct / n_rows` in `[0.02, 0.5]`) is **scale-dependent**: for a *fixed* actor
population the ratio shrinks as the log grows, so past ~2,000 rows a busy log with a
bounded host set falls out of the band and **both** the per-entity baseline and the
actor graph go silently dormant. The tracked NetFlow captures only stayed in-band
because their actor populations are *open* (distinct keeps growing with rows); a
64k-row internal subnet with 40 hosts would have quietly lost detection.

The band was replaced with three **scale-invariant** tests, all of which depend on
how values recur and what they look like, never on `distinct / n_rows`:

1. **Recurrence** — at least a couple of values recur `≥ ACTOR_MIN_EVENTS` (has
   baseline-able history; also excludes pure edge-ids). Already present for the actor
   graph; now the primary test for both paths.
2. **Repeat-mass** (`REPEAT_MASS_MIN`) — the fraction of rows in values that recur;
   excludes ephemeral / per-row columns (an ephemeral source port, a flow id) whose
   mass sits in near-unique values. Replaces the ratio *upper* bound.
3. **Value shape** (`STRUCTURED_TOKEN_MIN` + `VOCAB_MAX_DISTINCT`) — a bounded enum
   vocabulary (`Proto`, `State`, `Dir`) is **frequency-identical** to a small closed
   actor pool, so it is separated by *shape*: a small column of short non-identifier
   values is a vocabulary; an address / token column (or a large-distinct one) is an
   actor. This is what now keeps `Proto`/`State` out — the role the ratio floor served,
   done scale-invariantly. Replaces the ratio *lower* bound.

URL and URL-derived columns are also excluded outright (`_is_content_column`): a URL
path or referer is *content*, not an actor.

**Verified end-to-end — the tracked botnet numbers are bit-identical**: CICIDS
0.998 / 0.846 / 0.037, CTU-13 sc1 1.000 / 0.978 / 0.033, sc3 0.985 / 0.929 / 0.034,
because their actor populations were open (in-band) and their selected columns are
unchanged. The **secondary** rows changed, because the fix now correctly admits actor
columns the ratio band was excluding: **UNSW-NB15** re-admits `srcip`/`dstip` (recall
0.122 → 1.000, precision 0.198 → 0.519 — the actor signal now fires on this broad-IDS
shard, still not a bot result), and **Bournemouth** admits the web `session_id`
(flag 0.681 → 0.918 at that stage, still a negative below the base rate — the
session-entity method limit now shown *directly* rather than hidden by the band; see
the Bournemouth section). No thresholds were tuned; the new constants are
limited-evidence guardrails chosen with margin from the CTU-13 / CICIDS / UNSW
measurements. **Honest residual**: a closed pool of *short, unstructured* ids (bare
integers, usernames) is shape-ambiguous vs a vocabulary and is not detected — and a
raw request-`path` content column was, at this stage, admitted as a pseudo-actor.
Both became follow-ups H and I; the path pseudo-actor has since been demoted by value
grammar and the short-id case answered with an explicit override — see "Actor and
content residuals" below.

### The honest ceiling (CTU-13)

Read this as *hypothesis-supporting evidence within one botnet family*, not a
solved problem:

- **Same-family evidence — now tested on a second family, with a fix.** Recall
  1.0000 is on CTU-13 / Neris — the family the rule was developed against. A second
  labelled family (CTU-13 scenario 3 / Rbot) has since been run as a generality probe.
  Recall generalised immediately (0.985); precision did **not** at first (0.056),
  because the direction-agnostic rule fired on benign fan-in infrastructure too —
  but narrowing it to the **source fan-out** shape recovered precision to **0.929**
  with recall held. So both now generalise across the two families seen. This remains
  CTU-13-only evidence, and fan-in generality is *guarded, not proved* — see "The
  second-family test" below.
- **The over-flagging that capped precision is now fixed (0.041 → 0.978).** The low
  middle-row precision came from *pre-existing broad rules* over-flagging the diverse
  NetFlow background — notably `entity_monotony` on the degenerate `Proto`/`State`
  columns — never from the new rule. The actor-band entity gating above excludes
  those degenerate categoricals, lifting verified precision to **0.978** at a 0.033
  flag rate with recall held. This was the separate calibration question flagged
  here; it has now been addressed, not left as a standing limit.
- **Benign fan-in hubs no longer fire here (since the source fan-out narrowing).** A
  benign monotone server, DNS resolver, NTP source or load balancer is a *fan-in*
  star (high in-degree, low out-degree); the source-only rule does not fire on it, so
  it is no longer an `asymmetric_degree` false-positive risk. That passive fan-in case
  is handled by `entity_monotony` / the hub gate instead — and CICIDS is no-regression
  evidence for that path, not proof of fan-in generality.
- **The constants are limited-evidence guardrails, not universal constants.**
  `DEGREE_ASYMMETRY` = 10 and the 99th-percentile floor hold for asymmetry factors
  ≈ 10–100 on this one split plus a synthetic broadcaster; the rule over-fires
  below ≈ 10 and vanishes at ≥ 200 (beyond Neris's own ratio). They are *not*
  scale-free, and should not be read as tuned constants for other captures.

## The second-family test: CTU-13 scenario 3 / Rbot

The honest ceiling above asks for a *second labelled family* before reading the
`asymmetric_degree` win as anything more than same-family evidence. CTU-13 scenario
3 runs a different bot — **Rbot**, an IRC-controlled DDoS/scan botnet — captured the
same way (Argus bidirectional NetFlow, CC-BY). Running the identical pipeline on it
told a two-part story: the recall generalised straight away, the precision did not,
and the precision gap was then closed by a targeted directional change.

| Stage | Capture | Recall | Precision | Flag rate |
|---|---|---|---|---|
| (reference) | CTU-13 sc1 (Neris) | 1.000 | 0.978 | 0.033 |
| Direction-agnostic `asymmetric_degree` | CTU-13 sc3 (Rbot) | 0.985 | 0.056 | 0.567 |
| + source fan-out narrowing | CTU-13 sc3 (Rbot) | 0.985 | 0.929 | 0.034 |
| **+ ML-tail sentinel decouple (current)** | **CTU-13 sc3 (Rbot)** | **0.985** | **0.9319** | **0.034** |

(n = 62,000 rows, base rate 0.0323. Source: CTU-Malware-Capture-Botnet-44 detailed
bidirectional flow labels, Stratosphere Laboratory / CTU, CC-BY; a skip-if-absent
benchmark like the others.)

**Recall generalised; precision first did not.** Recall 0.985 says the
connectivity-asymmetry signal *does* recover a second, different bot family — the
core hypothesis holds across families. But the *direction-agnostic* rule's precision
collapsed to 0.056 at a 0.567 flag rate. The attribution was unambiguous, and — note
— **not** the scenario-1 story:

- `asymmetric_degree` itself fired on **34,995** rows, carrying **1,970** true
  positives and **33,025** false positives — a stand-alone fire-precision of
  **0.056**. The rule that was a clean 2,000/2,000-zero-FP catch on Neris was the
  *direct* source of the false positives on Rbot.
- The scenario-1 culprit was ruled out: `entity_monotony`'s entity columns were empty
  here (no `Proto`/`State` over-flagging), so this was the actor-graph rule's own
  behaviour, not the previously-fixed degenerate-column issue.

The root cause is structural: an **undirected** asymmetry rule cannot tell a bot's
**fan-out** (one source → many counterparts) from benign **fan-in** infrastructure (a
DNS resolver, NTP source or load balancer: many clients → one server). Both are
high-degree, monotone, role-asymmetric stars. On Rbot the benign fan-in hubs vastly
outnumber the bot, so firing on both halves floods the result with false positives.

### Closing the precision gap: source fan-out

The fix narrows the rule to the **source / fan-out side only**. The source endpoint is
taken by **schema column order** — source precedes destination in flow logs (`SrcAddr`
before `DstAddr`) — *not* by parsing column names, so the name-coupling we avoid
stays avoided; it is a positional convention, with the honest caveat that it assumes
that ordering. `asymmetric_degree` now fires only where a value's **out**-degree
dominates its **in**-degree (`out ≥ 10 × in`), i.e. the broadcasting-source shape. A
benign fan-in hub is the opposite (high in-degree, low out-degree) and no longer
trips it; that passive fan-in case is now owned by `entity_monotony`'s direction-
agnostic hub escalation, not here.

The effect on Rbot, verified end-to-end with **no detector thresholds tuned**:
precision **0.056 → 0.929** and flag rate **0.567 → 0.034**, recall held at **0.985**.
In attribution, `asymmetric_degree` now fires **1,970 true positives and 0 false
positives** on Rbot — as clean as it was on Neris. The **151** false positives in the
0.929-precision result are **ML-only** (no heuristic rule carries them); the
actor-graph rule contributes none.

### What this is — and is not

- **`asymmetric_degree` is now the diverse-bot fan-out signal.** It detects a
  broadcasting source (spam/scan/click-fraud). Recall *and* precision now generalise
  across both CTU-13 families it has seen.
- **Fan-in C2 coverage does not live here.** A passive fan-in star — many compromised
  hosts beaconing one C2 — is caught by `entity_monotony` / the hub gate, *not* by
  `asymmetric_degree`. The two rules cover the two opposite shapes.
- **There is no real external fan-in-bot benchmark, so fan-in generality is guarded,
  not proved.** A source-fan-out rule could in principle miss a bot that is *itself* a
  fan-in C2. The only real labelled fan-in C2 in our data is CICIDS (many hosts →
  `205.174.165.73`), and there the catch is carried by `entity_monotony`
  (`asymmetric_degree` fires 0). We use CICIDS as **no-regression evidence** that the
  fan-in case stays covered — **not** as positive proof that fan-in detection
  generalises. No non-circular, natively-labelled fan-in-bot capture was found to test
  that directly (absence of a benchmark is not proof the blind spot is empty).
- **Still two scenarios of one dataset.** sc1 + sc3 are both CTU-13; this is
  second-family evidence within that corpus, not a fully independent one.

At the source-fan-out revision, this work left the protected gates unchanged:
CICIDS 0.998 / 0.846 / 0.037 and CTU-13 sc1 1.000 / 0.978 / 0.033 (the values as of that
revision). Their **current** post-decouple values are CICIDS 0.879 and CTU-13 sc1 0.971
(see the `BENCHMARKS.md` registry).

*Original split finding measured by mono (#37642); the source-fan-out narrowing and
its numbers verified by rina (review #38226).*

## Domain transfer: web-server logs (Bournemouth)

Everything above is *network-flow* data. The first test on a **different domain** —
raw Apache access logs (Bournemouth Web Bot Detection) — is an honest **negative**, and
recording it matters as much as the wins. On 58,279 rows (base rate 0.029, real
folder-provided `bots/` vs `humans/` labels) the detector under scale-invariant actor
selection scored recall 0.873 and precision **0.028** (flag 0.918) — *below* the base
rate, i.e. worse than chance. The follow-up I-b fix (see "Actor and content residuals"
below) later removed a raw request-`path` **pseudo-actor** from that run, and the
current registry row reads recall **0.474**, precision **0.020**, flag **0.682** —
still below base rate; the fix removed a defect's artefact, it did not recover
detection. The scale-invariant actor selection (no cardinality-ratio band) **admits**
`session_id`, and that is what makes the method limit *visible*:

- **The session entity over-flags.** With `session_id` baselined as a per-entity actor,
  `entity_monotony` fires on human sessions too — a monotone human session is as
  self-similar as a bot session. Under the old cardinality-ratio band `session_id` fell
  out of range and stayed dormant (a quieter 68%-flag negative driven by timing alone);
  the scale-invariant selection shows the limit directly. (At this stage a raw
  request-`path` content column was also admitted as a pseudo-actor — content, not
  identity — and drove the flag rate to ~92%; since demoted, see below.)
- **Timing over-fires on page-load bursts.** The sub-second timing rules also misread the
  burst of near-simultaneous requests from a single web page-load as automated cadence.

So the netflow-tuned method does not transfer to web logs: its per-entity monotony does
not separate human-mimicking web bots from humans. No detector thresholds were tuned.
Two honest limits: the positive set is **tiny — only 11 bot sessions** (263 human), so
this is *qualitative* domain-transfer evidence, not a robust precision/recall estimate;
and the numbers are **provisional / local-internal** pending a licence decision
(research use invited, copyright reserved). The netflow gates are unchanged. *See
`evaluation/BENCHMARKS.md` for the full row and caveats.*

### The method limit, confirmed directly

Admitting `session_id` is not a *configuration* win — it is the method limit shown in
the open. `session_id` is the only real actor column in this log, and baselining it does
not recover detection: `entity_monotony` catches **0 of 11** Bournemouth bot sessions
and instead flags *monotone human* sessions. (This is exactly what an earlier Phase-1
experiment predicted when it *forced* the session entity active under the old band; the
scale-invariant selection now makes it the default.) The reason is that the
discriminating features simply do not separate the two classes here — bot and human
**diversity, timing coefficient-of-variation, request entropy, and volume
all overlap**. The human-mimicking web bots in this dataset are, on exactly the axes the
detector measures, indistinguishable from people.

So **entity selection is not the lever** — admitting the session entity produces active
false positives on monotone humans, with no recall to show for it. This is a **method
limit**: the detector's repetition / timing / concentration / diversity signals, which
work on mechanical automation and network botnets, **do not transfer to human-mimicking
web bots**. Closing the gap is not
calibration; it needs **web-specific signals** — interaction biometrics such as mouse
dynamics, which Bournemouth happens to carry — a separate future capability, tracked in
`TODO.md` (P3, item 12), not a tweak to the existing rules.

### Request-level session features — a negative-with-nuance probe

**All numbers in this subsection are INTERNAL / PROVISIONAL — Bournemouth Phase 0,
licence-pending (research use invited, copyright reserved). They are not field results
and must not appear in any external-facing artefact.**

Before closing the request-log route, we ran a *supervised separability* probe: could
session-level **request** features (volume, distinct paths, path entropy, referrer
continuity, status-code mix, HTTP-method fractions) separate the **hard** case —
`advanced_bot` vs `human` — even with labels in hand? This is a pre-registered research
question, deliberately kept apart from the unsupervised detector: it asks whether the
*signal exists*, not whether the pipeline finds it. The pipeline's own Phase-1 run
reproduced the negative this session — precision **0.0276**, recall 0.873, flag rate
0.918 (base 0.029; the registry row has since moved to 0.474/0.020/0.682 under the
follow-up I-b path demotion, still a negative) — and the floor any signal must beat is
the method's **0 of 11** bot sessions.

**Pre-registered bar:** a feature is promising *iff* it reaches AUC **≥ 0.75 train and
≥ 0.70 test** on `advanced_bot` vs `human`. Nothing clears it:

| Request feature (advanced_bot vs human) | AUC | Verdict |
|---|---|---|
| status-code mix / referrer-presence / HEAD-fraction | 0.500 (zero variance) | degenerate — no signal |
| volume / distinct_paths / path_entropy | 0.50–0.56 train | classes overlap |
| `referer_continuity` (best single feature) | 0.635 train / 0.767 test | fails the train bar |
| multivariate logistic (non-degenerate feats) | ≈ 0.80 in-collection (n = 30 test) | suggestive, but weak / small-n / unvalidated out-of-collection |
| *moderate* bots (for contrast) | 0.93–0.97 | separate well — but not the hard problem |

The single best request feature misses the bar; the multivariate ≈ 0.80 is on **30 test
sessions**, in-collection only, and is not a capability.

**The phase-2 artefact trap — record it so it is not mistaken for a breakthrough.** A
cross-collection model (train phase-1 → test phase-2) scores AUC **0.996**. That is a
**collection artefact, not capability.** Phase-2 humans issue **5–7× more requests per
session** than phase-2 bots (median **1,566 vs 286**, near-disjoint distributions),
whereas in phase-1 the same distributions overlap (**220 vs 211**). `req_count` **alone**
scores AUC **1.000 on phase-2 and 0.500 on phase-1** — the "0.996" is the model reading
phase-2's request-volume split, not bot behaviour. **Any cross-collection validation here
must sanity-check `req_count` first**, or it will mistake a collection quirk for a signal.

**Conclusion (negative-with-nuance).** Request-level features do **not** deliver robust,
generalisable separation of human-mimicking web bots. The in-collection multivariate
≈ 0.80 is too weak, too small-n, and unvalidated out-of-collection to justify an engine
change, and the headline cross-collection 0.996 is an artefact. This reinforces the
existing direction — **TODO item 12 / Phase 3a interaction biometrics (mouse dynamics)** —
as the route carrying a signal the request log lacks. The general caveat it underlines:
*supervised separability is not unsupervised detectability in the actual pipeline* — a
classifier handed labels finding ≈ 0.80 AUC in-collection says nothing about whether the
unlabelled detector would surface those sessions, and the pipeline's own run (precision
0.0276) shows it does not. No detector thresholds were tuned, no model was shipped, and
the committed benchmark numbers are unchanged.

## Decoupling the sparse-timing sentinel from the ML feature matrix

The CICIDS honest ceiling above named the residual error precisely: of 358 false
positives, ~253 were **ML-only** — flagged by the Extended Isolation Forest with no
heuristic rule behind them — and it called that "a separate calibration question".
This is that question, answered.

The engine marks rows it cannot time — an actor with too few events to estimate an
inter-arrival cadence — with a sentinel value (`SPARSE_TIMING_SENTINEL = 999`) in its
`dt` statistics. That sentinel was flowing straight into the **EIF feature matrix** on
the `dt__std` and `dt__cv` axes. A large constant sitting among real, small dispersion
values reads to an isolation forest as extreme spread, so the forest carved those
sparse-timing rows out as anomalies — manufacturing ML-only false positives from an
*absence* of data, not a presence of signal.

### The fix: median-fill the matrix, keep the rule input untouched

The feature matrix now **median-fills** the `dt` axes for sparse-timing rows and adds a
single `has_regular_timing` 0/1 indicator column, so "we could not time this actor" is
represented as a flag rather than as a fake extreme value (new helper `_matrix_timing`).
Crucially the cadence *rule* is left alone: `regular_timing` reads `context.dt_cv`,
which this change does not touch, so that heuristic is **byte-identical** — cadence
detection stays owned by the rule, and only the ML axis is recalibrated. A dedicated
test (`tests/test_features.py::test_sparse_timing_sentinel_decoupled_from_matrix`) pins
the decoupling.

The effect, measured end-to-end (85 tests pass; verified by @ml-engineer-reviewer- on
the actual diff): CICIDS/Ares precision rises **0.846 → 0.879**, recall held at
**0.998**, flag rate **0.037 → 0.036** — the lift comes from shrinking exactly the
ML-only tail the ceiling identified. On the microsecond-clocked CTU-13 sc1 (Neris) it
costs a small amount: precision **0.978 → 0.971**, recall held at **1.000**, flag rate
0.033. On the second-family probe CTU-13 sc3 (Rbot) it is a small *gain* the other way —
precision **0.929 → 0.9319**, recall and flag rate flat — because the same ML-only
recalibration helps there. Net across the two primary captures: **+3.3 pts CICIDS,
-0.7 pts CTU sc1**, both recalls flat.

A blunter variant — **dropping the `dt` features from the matrix entirely** — was
**rejected**: it cost CTU-13 **-4.8 pts** precision, because the `dt` axes still carry
real discriminating signal on a fine-resolution clock. Median-fill keeps that signal
for rows that have it while denying the sentinel a chance to masquerade as spread.

*Validation (fresh reviewed re-run at `ef92510`, ML pair): `uv run pytest -q` → 85
passed; `evaluation.cicids_bot_benchmark` → recall 0.998 / precision 0.879 / flag 0.036;
`evaluation.ctu13_bot_benchmark` → recall 1.000 / precision 0.971 / flag 0.033;
`… --scenario sc3` → recall 0.985 / precision 0.9319 / flag 0.034;
`evaluation.rule_diagnostic` → flagged 2,232 / fp 270 / ML-only 165. Confirmed by the
ML reviewer against the measured tables before entry.*

### The honest ceiling (ML-tail decouple)

Read this as an anomaly-axis calibration on two captures, not a general precision gain.

- **It is an anomaly-axis calibration, not a new labelled-precision guarantee.** The
  win is a cleaner EIF ranking on one capture; the scores remain rank-order signals
  under uncertainty, never calibrated fraud probabilities.
- **It is a small cross-capture tradeoff, judged net-positive.** CICIDS +3.3 pts
  against CTU -0.7 pts. That is a value judgement on two captures of two families, not
  proof the tradeoff generalises to unseen data.
- **The per-rule attribution has been recomputed.** On CICIDS the ML-only false
  positives fell **~253 → 165** and total false positives **358 → 270** (fresh reviewed
  `rule_diagnostic` at `ef92510`); the `BENCHMARKS.md` attribution table now carries
  current and pre-decouple columns side by side.

## Feeding actor-graph features into the EIF matrix — a measured dead end

`asymmetric_degree` recovers the diverse fan-out bot the repetition rules miss (the
actor-graph discriminator above). The obvious next thought is to hand the *same*
connectivity signal to the Extended Isolation Forest — put source out-degree, role
asymmetry and source volume into the feature matrix so the ML tail can lean on graph
structure too. It was tried, in two variants, and it is a **measured dead end**: every
variant regressed precision on every capture and bought no meaningful recall. Recorded
here so it is not re-attempted.

| Capture | Baseline (`2be1811`) | Variant (a): 3 graph features | Variant (b): asymmetry ratio only |
|---|---|---|---|
| CICIDS / Ares | 0.8790 | 0.7572 (**-12.2 pts**) | 0.8571 (-2.2 pts) |
| CTU-13 sc1 / Neris | 0.9713 | 0.9456 (-2.6 pts) | 0.9465 (-2.5 pts) |
| CTU-13 sc3 / Rbot | 0.9319 | 0.9116 (-2.0 pts) | 0.8920 (-4.0 pts) |

*Precision. Recall saw no meaningful gain (CICIDS 0.998, sc1 1.000, sc3 0.985 — sc3
rises trivially to 0.987 under (b)); no variant bought recall.* Variant (a) added
`log1p(source out-degree)`, `log1p(asymmetry ratio = degree / (reverse-role degree + 1))`
and `log1p(source volume)`; variant (b) added the asymmetry ratio alone. The damage is
worst on CICIDS — the fan-in star capture — where the three-feature variant cost **12
points** of precision, actively undoing the ML-tail precision the sparse-timing decouple
had just won.

### Why it fails: the guards live in the rules, not the features

The connectivity evidence is already owned by two rules — `asymmetric_degree` and
`entity_monotony` — and the reason they are safe is *not* the raw signal, it is the
**gates around it**:

- a **monotony ceiling** — a behaviourally diverse actor is never escalated;
- an **adaptive degree floor** — the 99th percentile over distinct-group sizes, so only
  genuinely high-degree endpoints qualify;
- an **order-of-magnitude asymmetry guard** — `DEGREE_ASYMMETRY ≈ 10`: a source must
  out-fan its reverse role by roughly 10× before it counts.

A raw graph feature in the EIF matrix carries **none** of these. The isolation forest
sees a busy but entirely benign source — a legitimate high-degree, high-volume server —
as an outlier on the degree/volume/asymmetry axes and isolates it as a **tier-3,
ML-only false positive**. The features therefore add false positives without adding any
discrimination the guarded rules did not already provide.

This is the **architecture contract's fan-out false-positive lesson (§6)** restated from
the other side: the fix for fan-out over-flagging was never "add more graph signal" or
"get the direction right" — it was the **gates**. Putting ungated graph features into
the ML matrix reintroduces exactly the un-gated over-flagging those guards were built to
prevent. **The problem is missing gates, not merely direction.**

### Honest scope

This is a negative result *as tried* — raw `log1p` connectivity features, ungated, on
the current three captures. It does not prove that no *gated* ML use of graph structure
could ever help; it shows that the naive "just add the features" route regresses
precision and should not be revisited without first carrying the rule guards into the
matrix. No headline benchmark numbers changed — the variants were not shipped, and the
`2be1811` baseline stands.

## Quantile-ranking the numeric value features — a measured wash (TODO item 5)

The numeric `<col>__val` features (flow duration, byte and packet counts) are fed to
the matrix as their median-filled raw magnitude. They are heavy-tailed, so the standing
idea (TODO item 5) was to replace the raw value with a **quantile-rank** transform —
each numeric column mapped to its rank in `[0, 1]`, uniform by construction — on the
theory that a heavy tail distorts the isolation forest's random-hyperplane cuts. One
premise correction first: robust *scaling* is **already done** — `anomaly._robust_standardize`
centres every column on its median and scales by MAD before the forest. That is a
*linear* map, so it fixes scale and centre but not tail *shape*; the quantile-rank is
the only part not already applied. It was probed offline (matrix transform only, no
engine change) on CICIDS, and it is a **measured wash**: recorded here so it is not
re-attempted.

| seed | baseline precision | quantile precision | Δ |
|---|---|---|---|
| 7  | 0.879 | 0.893 | **+0.014** |
| 13 | 0.740 | 0.967 | **+0.227** |
| 21 | 0.933 | 0.727 | **−0.206** |
| 42 | 0.933 | 0.767 | **−0.166** |

*Recall held at 0.998 on every seed; only the ML path moved (the heuristic never reads
`__val`).* The sign of the change is **not stable** — it swings ±0.2 purely on which
benign rows the mix samples. The first seed's +0.014 was the trap: measured alone it
reads as a small win; across seeds it is noise.

The reason is visible in the same table. The **baseline** precision already swings
**0.740–0.933** across seeds, and the ML-only flag rate swings with it (0.0005–0.0118).
The CICIDS residual is dominated by a small, intrinsically unstable **rate-capped EIF
tail**; quantile-ranking merely reshuffles *which* ~1 % of rows that tail isolates, and
whether the reshuffle helps or hurts is a coin-flip on the sample. The numeric
representation is not the lever — the tail's calibration is, and that is a separate open
problem (the ML-tail calibration bet), not something a feature-shape transform reaches.

**Honest scope.** This tests the quantile-rank transform on CICIDS across four seeds;
it does not prove no shape transform could ever help a *stabilised* tail. It shows that
on the capture where the ML path carries most of the residual error, the transform buys
no reliable precision and is swamped by tail variance an order of magnitude larger than
its mean effect. TODO item 5 ("compare robust vs quantile scaling") is answered:
measured-negative. No thresholds were tuned, no feature was shipped, and the committed
benchmark numbers are unchanged.

## Vectorising the feature-build loops — the row-loops are a red herring (no bit-identical win)

`_entity_baseline`, `_actor_graph` and `_temporal_context` iterate row-by-row in Python,
so the standing performance idea was to *vectorise the per-row loops*. Profiled on the
real CICIDS mix (62k rows, 84 feature columns), `build_features` takes **13.5s**, of which
`_entity_baseline` (4.2s) + `_actor_graph` (3.4s) are **56%** — linearly ~3.6 min at 1M
rows. So the cost is real. But three measurements show the idea, as scoped, does not reach it.

**1. The named per-row loops are 0.5% of the cost.** Instrumenting `_entity_baseline`'s hot
path: the `for index in range(n_rows)` members-build loop is **0.006s**; the
entropy-per-group work — ~97k small `np.unique`/Shannon-entropy calls, one per entity-group
× behaviour column — is **99%** (1.03s). Vectorising the row loops the idea names buys ~0.5%.

**2. The only real speedup is not bit-identical — so it is a behaviour change, not a refactor.**
A groupby-vectorised entropy (one `groupby([entity, colvalue]).size()` per column, replacing
the 97k `np.unique` sorts) runs **3.0×** faster on the hot path (1.01s → 0.34s). But its
output drifts from the current path by **4.4e-16 across 1,179 of 7,498 groups** — last-ULP,
because pandas' group reduction accumulates `-(p·log p)` differently from numpy's per-group
sum. A refactor's contract is *bit-identical* output; a last-ULP drift can in principle flip a
threshold tie and move a pinned benchmark number, so this cannot ride the behaviour-preservation
diff gate. It would have to be validated as a behaviour change (full benchmark no-regression).

**3. The bit-identical variant is slower.** Keeping the reduction as the identical numpy op in
`np.unique`'s ascending-value order (so counts and summation order match exactly) does reach
**max|diff| = 0** — but at **0.58×** (nearly 2× *slower*): the nested per-entity groupby and
MultiIndex construction cost more than the `np.unique` calls they remove.

**Conclusion.** On this code there is **no vectorisation that is both faster and bit-identical**:
the speedup (3× on ~½ of `build_features`) and the diff gate are mutually exclusive. The
proposed row-loop vectorisation targets the 0.5%, not the 99%. The real win exists only as a
benchmark-gated behaviour change, and its payoff (≈13.5s → ~10s at 62k; ≈3.6 min → ~2.5 min at
1M) is justified only by a genuine 1M-row / full-day workload, which the current benchmarks
(62k) do not pose. Parked until production-scale runs are real; revisit then on the
behaviour-change track, not as a refactor. Related note: the EIF fit does **not** scale with n
(`sample_size=min(4096, n)`, so each tree sees ≤4096 rows); only `decision_function` scoring
does, and it already costs ≈ `build_features` at 100k — so halving feature-build only gets the
end-to-end cost to ~half, never below.

Two adjacent refinements were scoped in the same pass and left unmeasured-or-parked:
*correlation-pruning the concentration features* (measured collinearity on CICIDS:
`context__conc` ↔ `Destination IP__conc` = **0.839** — the joint-context feature largely
duplicates the dominant categorical's concentration, but any precision effect is second-order
to the same rate-capped-tail variance that swamped the quantile probe, so it needs the same
multi-seed treatment before it means anything); and *numeric-coded identifier inference*
(TODO follow-up H) — a genuine gap (`_entity_columns`/`_actor_endpoint_columns` scan only
CATEGORICAL/TEXT roles, so a numeric session-id or numeric IP is skipped) but with **no
measured loss** on any capture we hold (CICIDS/CTU-13 addresses are string-typed and already
selected as actors), and a precision risk (a dtype-agnostic recurrence check could pull genuine
numeric *measurements* into the actor graph). Both await a dataset that actually exercises them.

## Attack-family coverage: the rest of CICIDS2017 (follow-up F)

The tracked CICIDS2017 benchmark measures the one family in the archive that is
actually a **botnet** (Ares). Roadmap follow-up F asked what the detector does with
the archive's other six labelled attack families — port scanning, DDoS, web attacks,
infiltration, credential brute force, DoS. These are *attacks, not bots*, so the six
new probes (`evaluation/cicids_family_benchmark.py`, wired into the unified runner)
are **secondary attack-coverage measurements**, built on the same rare-attack mix
convention as the sibling benchmarks and never citable as bot-detection results.

### Predicted first, then measured

Directional predictions were recorded on the review thread before running anything.
The grounding facts, measured from the slices themselves: every family slice is a
single NATed IP channel (`172.16.0.1 → 192.168.10.50`), so `asymmetric_degree`
should stay dormant everywhere — even the port scan fans out only in ports, not
IPs; the minute-quantised clock gates the dense-timing rules off; and the ML path's
2% flag-rate cap bounds ML-only recall at ~0.62 for a 2,000-positive mix. The
measured results (recall / precision / flag rate, base rate 0.032 except where
noted):

| Probe | Recall | Precision | Flag rate |
|---|---|---|---|
| `cicids_portscan` | 1.000 | 0.585 | 0.055 |
| `cicids_ddos` | 1.000 | 0.786 | 0.041 |
| `cicids_webattacks` (base 0.035) | **0.000** | **0.000** | 0.158 |
| `cicids_infiltration` (36 positives, base ~0.001) | 0.472 | 0.002 | 0.131 |
| `cicids_bruteforce` | 1.000 | 0.168 | 0.192 |
| `cicids_dos` | 0.040 | **0.008** | 0.160 |

Three results broke the predictions: recall 1.000 on PortScan, DDoS and BruteForce
sits far above the ~0.62 ML ceiling, and DoS came in far below its predicted band.
Per the methodology, the surprises were attributed with
`evaluation/rule_diagnostic.py` on all six mixes before being reported.

### One mechanism explains all six: `entity_monotony` in two regimes

Which regime a file lands in is decided by how many entity columns it qualifies:

- **Friday files (PortScan, DDoS)** qualify both `Source IP` and `Destination IP`,
  so the entity graph is active and the **hub-gated** monotony rule catches the
  dense single-channel attack outright — 2,000/2,000 positives on both families, at
  fire precision 0.636 (PortScan) and 0.958 (DDoS). Recall 1.000 comes from the
  heuristic path, not the ML tail.
- **Tuesday/Wednesday/Thursday files (BruteForce, DoS, WebAttacks, Infiltration)**
  qualify only `Destination IP`, so the entity graph is inactive and the **ungated
  single-entity-column low-diversity fallback** fires instead — on 7,500–9,600
  benign rows per mix at fire precision 0.000–0.175, which is where the 13–19% flag
  rates come from. The same fallback catches the BruteForce slice (a ~21-minute
  single-channel SSH-Patator burst: recall 1.000 at precision 0.168) while missing
  WebAttacks and DoS entirely, because the victim web server's entity shows high
  behavioural diversity.

Everything else behaved as predicted: dense-timing rules gated (60 s grid),
`asymmetric_degree` dormant (no IP fan-out), ML-only flags within the 2% cap on
every mix (211–457 rows).

### What stands, and what does not

The weak results are kept as first-class findings, not softened: **WebAttacks recall
0.000** (human-paced web attacks over one channel are invisible to this method on
this mix), **DoS precision 0.008 — below the 0.032 base rate**, worse than chance on
that mix, and **Infiltration precision 0.002** on the only 36 labelled flows the
archive holds (base rate ~0.001 caps precision near zero mechanically; qualitative
signal only). Nothing was tuned to improve any of them.

The honest ceiling: these are six slices of **one archive** with a minute-quantised,
AM/PM-less clock, so the contiguous slices are parse-order windows with partial
subfamily coverage (BruteForce = SSH-Patator only; DoS = slowloris + Heartbleed
only), and none of the numbers says anything about bot detection or transfers beyond
CICIDS2017. The one actionable discovery was the **ungated single-entity-column
monotony fallback**: it drove every weak probe's flag rate and both
at-or-below-chance precisions. Whether to gate or calibrate it was an engine
decision with regression risk to captures where the fallback carries recall, so it
was deliberately left untouched in that measurement-only pass and recorded as TODO
follow-up L — taken up, evidence-first, in the next section. Registry rows, mix
caveats and reproduce commands live in `evaluation/BENCHMARKS.md`, "CICIDS2017
attack-family coverage probes".

## The fallback hub gate: closing follow-up L without losing the recall it carried

Follow-up F left a precise question: the single-entity-column monotony fallback
flooded 13–19% of four CICIDS mixes with false positives, yet the same fallback was
the *only* thing catching the BruteForce burst (recall 1.000). Kill it and you lose
real recall; keep it and two probes score at or below chance. This is a
**detector-behaviour change** — it moves flag decisions — so it ran as a two-phase,
evidence-first arc with cross-model review at each step.

### Phase 1: attribute before touching anything

A read-only diagnostic pass (no engine edits) classified every registry mix by
regime and attributed the fallback's fires row by row, with each fired entity's
counterpart degree computed offline from the actor columns:

- The fallback executes on exactly four mixes (`cicids_webattacks`,
  `cicids_infiltration`, `cicids_bruteforce`, `cicids_dos`). Everywhere else it is
  structurally impossible (entity graph active) or dormant (no entity columns) —
  so the seven other registry rows cannot move, testably.
- **Every flooded fire was a point-to-point monotone channel** (counterpart
  degree < 3): WebAttacks 9,607/9,607 false fires point-to-point, Infiltration
  7,624/7,624, DoS 8,313 of 9,561. That is precisely the class the shipped
  relational hub gate exists to exclude.
- **Every recall-carrying fire was hub-shaped**: all 2,000 BruteForce true
  positives sat on entities with counterpart degree ≥ 3 and would pass a hub gate.

One mechanism, no second explanation needed: the fallback regime *is* the hub
gate's absence. Four candidate designs were assessed against the recorded failure
archaeology; the chosen one (re-apply the existing gate) was the only candidate
that removed the flood without touching the recall, without new constants, and
without the prohibited distinct/row-count ratio class. Killing the fallback
outright was rejected because it demonstrably costs the 2,000 BruteForce true
positives; a flag-mass cap was rejected as hiding the flood rather than removing
its cause.

### Phase 2: predict, implement, verify

Numeric predictions for all eleven registry rows were recorded **before**
implementation — seven rows predicted bit-identical (the gated path never executes
there; any movement at all would be an implementation bug, not jitter), four
fallback rows projected from the Phase 1 offline counterfactuals, with the explicit
stop condition that *any* BruteForce recall loss halts the work.

The implementation gates the fallback with the **existing** structural hub gate
(`MIN_HUB_DEGREE = 3`), sourcing counterpart degree from the relational actor
graph when the single entity column is a covered actor endpoint, and preserving
the bare fallback where no counterpart structure is derivable. `rules.py` and its
tests are the only files touched; no rule weight, cutoff, ML scoring or benchmark
definition changed.

Verified end-to-end (full registry re-runs, independently repeated by the ML
review), against prediction (recall / precision / flag rate):

| Probe | Before | After | Prediction |
|---|---|---|---|
| `cicids_bruteforce` | 1.000 / 0.168 / 0.192 | 1.000 / 0.600 / 0.054 | matched; recall held |
| `cicids_webattacks` | 0.000 / 0.000 / 0.158 | 0.000 / 0.000 / 0.005 | matched |
| `cicids_infiltration` | 0.472 / 0.002 / 0.131 | 0.472 / 0.053 / 0.005 | matched |
| `cicids_dos` | 0.040 / 0.008 / 0.160 | 0.040 / 0.046 / 0.028 | matched |

Zero prediction surprises at displayed precision. The seven protected rows —
Ares 0.998/0.879/0.036, CTU-13 sc1 1.000/0.971/0.033, CTU-13 sc3 0.985/0.932/0.034,
UNSW 1.000/0.519/0.062, Bournemouth 0.873/0.028/0.918 (its figure at that
verification; since revised by the follow-up I-b path demotion — see the next
section), PortScan 1.000/0.585/0.055, DDoS 1.000/0.786/0.041 — did not move. Validation: full suite 94 passed,
`tests/test_rules.py` 16 passed, pylint 10.00/10, `black --check` clean,
`git diff --check` clean.

### The honest ceiling (fallback hub gate)

- **This is a false-positive fix, not new coverage.** WebAttacks recall stays
  0.000 and DoS recall stays 0.040 — the gate removed floods, it caught nothing
  new, and DoS remains weak (precision 0.046, barely above the 0.032 base rate).
- **Benign hub-shaped fires survive by design** — DoS keeps 1,248 of them; that is
  the hub gate's inherent acceptance, unchanged from Ares.
- **The genuinely unpaired fallback regime** (one entity column, no derivable
  actor counterpart) stays ungated by design and is covered only by unit fixtures —
  no real registry row exercises it.
- **Protected-row equality was verified at benchmark-table precision** and via the
  existing regression guards, not by a per-row decision-vector diff.
- The moved numbers are **secondary attack-coverage measurements on one archive**;
  nothing here is bot-detection validation or a production-precision claim.

## Actor and content residuals: explicit overrides and the path-grammar demotion (follow-ups H and I)

The scale-invariant actor selection left three known residuals, all value-shape edge
cases (follow-ups H and I): an **integer-coded identifier** (a numeric session id or
IP) is typed numeric and never considered an actor (H); a **closed pool of short
unstructured ids** is shape-ambiguous against a bounded vocabulary (I-a); and a **raw
request-`path` column** — content, not identity — passed the actor shape tests (I-b).
The third was not cosmetic. On Bournemouth the raw `path` column occupied the
directional **source seat** of the actor graph and fired `asymmetric_degree` on
**53,467** of 58,279 rows — most of the 0.918 flag rate, and the carrier of most of
the apparent 0.873 recall.

Phase 1 ran evidence-first diagnostics before any engine edit
(`evaluation/FOLLOWUP_HI_PHASE1_EVIDENCE.md`, commit `f1aebbb`, with pre-run
predictions for all eleven registry rows). Two findings shaped the fix. First,
**heuristic inference for H and I-a is not shippable on current evidence**: numeric
and short-unstructured identity shapes overlap ordinary measure and vocabulary
columns too heavily to infer safely. Second, raw path content is **grammatically
separable**: the fraction of distinct values whose first character is a separator
measured **1.000** on two web logs' raw path columns and **0.000** on every admitted
actor/entity column across the CTU-13 / CICIDS / UNSW / Bournemouth mixes.

### The fix: explicit, default-off schema overrides plus a grammar demotion

For H and I-a the engine now ships **overrides, not inference**: `run
--entity-column COLUMN` (repeatable) declares an identity the detector cannot infer
and routes it into the *same* actor/entity machinery as inferred actors — the
identity-shape tests are bypassed, the volume/recurrence floors are kept, because
they guard the statistical validity of the adaptive thresholds; `--content-column
COLUMN` forces a column out of actor/entity selection when grammar and role
inference are insufficient. Unknown or conflicting column names exit 2 with a
message; overrides are recorded in `summary.json`. Both are **default-off**: with
neither flag, behaviour is identical except for the one deliberate change below.

For I-b, raw path-like content is **demoted from actor/entity selection by value
grammar** (`_is_path_shaped` in `bots_without_labels/features.py`): a column whose
distinct values start with a separator character at or above
`CONTENT_LEADING_SEPARATOR_MIN = 0.9` is content, never an actor. It is a
value-shape test — no column-name or dataset branch — and an explicit
`--entity-column` declaration outranks it.

The effect, verified end-to-end: the full-registry before/after output differs in
**exactly one line**. Bournemouth moves flag/recall/precision **0.918 / 0.873 / 0.028
→ 0.682 / 0.474 / 0.020**; rows 1–7 and 8–10 are byte-identical. On Bournemouth,
`asymmetric_degree` fires **53,467 → 0** while every other rule's fire count is
unchanged; entity columns reduce to `session_id` alone, the entity and actor graphs
go inactive, and `entity_monotony` runs the bare single-column fallback on the
**same 8,191 rows** as before (the one recorded Phase-1 prediction miss — it was
predicted to increase under the fallback regime and did not). The recall drop is the
point, not a loss: the removed fire was a near-blanket flag sweeping up bot rows by
volume — a measurement artefact of the defect. Bournemouth remains a domain-transfer
**negative below base rate**, and its numbers remain internal / provisional /
licence-pending.

*Verification: implemented by the ML pair and independently re-run under blocking ML
review (niho; PM brief #42074, handoff #42093) against the Phase 1 evidence package.*

### The honest ceiling (follow-ups H and I)

- **`CONTENT_LEADING_SEPARATOR_MIN = 0.9` is a limited-evidence guardrail.** The
  1.000-vs-0.000 separation rests on two web logs' raw path columns against four
  mixes' admitted actor columns. It stops content occupying an identity seat; it is
  **not** a web-bot model and **not** a Bournemouth recovery.
- **H and I-a are override-supported, not solved.** Heuristic numeric / short-id
  actor inference is recorded as not shippable on current evidence; the escape hatch
  requires the user to know the identity column. No real registry row exercises the
  override path — positive override behaviour is covered by unit fixtures
  (`tests/test_schema_overrides.py`) only.
- **The demotion changes exactly one registry row.** Everything it removed on
  Bournemouth was false structure; nothing new is detected anywhere.

## Takeaway

The skeleton (unsupervised, role-driven, explainable) is sound; the gap was
calibration plus a missing per-entity view, and a benchmark that never tested
reality. The per-entity baseline recovered the passive fan-in bots; the relational
hub gate removed the busy-benign point-to-point channels that diversity alone could
not distinguish; and the actor graph (`asymmetric_degree`, now a source fan-out
signal) added the one shape both missed — a diverse, high-degree broadcasting source. `tests/test_real_benchmark.py` pins the CICIDS stacked wins (recall
≥ 0.95, precision ≥ 0.35, flag rate ≤ 0.12); `tests/test_ctu13_benchmark.py` pins
the CTU-13 recall win (≥ 0.95). The separate rule that originally capped CTU-13
precision — `entity_monotony` over-flagging the degenerate `Proto`/`State` columns —
has since been calibrated by the actor-band entity gating, lifting verified CTU-13
precision to 0.978 with recall held. Both guards mean a future change that silently
reintroduces a real-data blind spot fails even with the synthetic suite green.

The second family both tested and improved `asymmetric_degree`: recall generalised to
Rbot immediately (0.985), and once the rule was narrowed to the **source fan-out**
shape its precision generalised too (0.056 → 0.929, recall held) — the
direction-agnostic form had been firing on benign fan-in infrastructure. The rule is
now the diverse-bot fan-out signal; passive fan-in C2s are covered by
`entity_monotony` / the hub gate. The honest residual: there is no real external
fan-in-bot benchmark, so fan-in generality is *guarded* by CICIDS no-regression (where
`entity_monotony` carries the fan-in C2), **not positively proved**, and the evidence
remains two CTU-13 scenarios, not an independent corpus.

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

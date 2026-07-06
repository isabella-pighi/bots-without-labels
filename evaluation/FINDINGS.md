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
(flag 0.681 → 0.918, still a negative below the base rate — the session-entity method
limit now shown *directly* rather than hidden by the band; see the Bournemouth
section). No thresholds were tuned; the new constants are limited-evidence guardrails
chosen with margin from the CTU-13 / CICIDS / UNSW measurements. **Honest residual**:
a closed pool of *short, unstructured* ids (bare integers, usernames) is
shape-ambiguous vs a vocabulary and is not detected — and a raw request-`path`
content column is still admitted as a pseudo-actor; both are tracked follow-ups.

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
folder-provided `bots/` vs `humans/` labels) the detector scored recall 0.873 and
precision **0.028** — *below* the base rate, i.e. worse than chance. The scale-invariant
actor selection (no cardinality-ratio band) now **admits** `session_id`, and that is
what makes the method limit *visible*:

- **The session entity over-flags.** With `session_id` baselined as a per-entity actor,
  `entity_monotony` fires on human sessions too — a monotone human session is as
  self-similar as a bot session — so the flag rate climbs to **~92%**. Under the old
  cardinality-ratio band `session_id` fell out of range and stayed dormant (a quieter
  68%-flag negative driven by timing alone); the scale-invariant selection shows the
  limit directly. (A raw request-`path` content column is also admitted as a
  pseudo-actor — content, not identity; a tracked residual.)
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

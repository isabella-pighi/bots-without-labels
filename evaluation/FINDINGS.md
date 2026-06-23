# Real-data evaluation findings

The synthetic suite reports ~1.0 recall, but it is generated to carry exactly the
signatures the detector looks for, so it cannot tell us whether the method works
on real traffic. This is the record of testing it against independent, labelled
data, what failed, and what changed.

## What we ran

Three external sources plus a constructed, fair real-data benchmark:

| Source | Dataset | Result |
|---|---|---|
| HuggingFace | `mindweave/web-server-logs` | flagged-rows' bot-UA rate ≈ base rate (no lift) |
| Kaggle | `tunguz/clickstream-data-for-online-shopping` | no labels; surfaced over-long sessions only |
| Local zip | CICIDS2017 PortScan flows | attacks were 55% of the sample → not anomalous |
| **Benchmark** | **CICIDS2017 Friday-morning botnet (Ares)** | **see below** |

The first three were not fair tests: bots were either the majority, unlabelled,
or the timestamps too coarse for the timing rules. The botnet capture is the
method's *ideal* target — rare (~1%), temporally dense, structurally distinct,
externally labelled — so it is the benchmark we kept (`cicids_bot_benchmark.py`).

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
lifts measured precision roughly threefold and more than halves the flag rate,
with no loss of recall:

| Stage | recall | precision | flag rate |
|---|---|---|---|
| Pre-fix (global concentration capped) | 0.022 | 0.018 | — |
| Per-entity diversity baseline | 0.998 | 0.144 | 0.219 |
| **+ relational hub discriminator** | **0.998** | **0.441** | **0.072** |

## The honest ceiling

Precision 0.441 is a measured number on *this* labelled capture — it is not a
production guarantee, and not proof that any flagged row is fraud. Four caveats
keep it honest:

- **It is anomaly-style evidence, not a fraud verdict.** The method is
  unsupervised; in production it ranks structurally unusual entities, and a hub
  flag means "monotone fan-in star", not "confirmed bot". The benchmark can
  measure precision only because CICIDS ships labels; the running system cannot.
- **It is one attack family and one hub.** The lift leans on a single, uniquely
  separable C2 (`205.174.165.73`). We did not tune `K` to it, but a 0.441 figure
  from one capture must not be read as a general precision, nor as evidence that
  `K = 3` is universally correct.
- **Benign monotone hubs remain a plausible risk for the `entity_monotony`
  gate.** A DNS resolver, an NTP source, a load balancer, or a backup target is
  *also* a low-diversity, high-degree node, so the gate *could* flag one. Degree
  narrows this risk; it does not eliminate it. Where timestamp resolution allows,
  sub-minute timing cadence is the next discriminator to separate a beacon from a
  busy benign hub.
- **The overall 0.441 is not the hub gate's precision, and the residual error is
  not the hub gate's fault.** Precision 0.441 means 55.9% of *all* flagged rows
  are not labelled bot in this capture — but that is the detector as a whole, not
  the hub rule. A checked per-rule diagnostic on this benchmark (4,451 flags;
  2,489 false positives) shows `entity_monotony` fired on 2,067 rows with only
  105 false positives — ~0.95 precision, and it accounts for *all* 1,962
  true-positive catches. It contributes ~4% of the residual false positives; the
  other ~96% come from the detector's other rules. So the residual error here is
  *not* dominated by benign monotone hubs; the headline 0.441 is dragged down by
  other rules flagging benign traffic, a separate calibration question.

Two further limits are tracked as follow-ups, not fixed on this branch:

- **The diversity cut is a fixed 10th-percentile quantile.** On real flow data
  many entities share identical diversity values, so the quantile lands on a
  tie at a bin edge and the cut becomes sensitive to how ties break. A robust
  fix needs an *adaptive* cut (gap/knee detection on the diversity distribution),
  not a fixed quantile — a redesign, deferred to the threshold-calibration work.
- The rule stays deliberately **dormant on low-dimensional logs** (few columns →
  every actor looks monotonous, carrying no signal), via an absolute diversity
  ceiling. That is why the synthetic suite is unaffected.

## Takeaway

The skeleton (unsupervised, role-driven, explainable) is sound; the gap was
calibration plus a missing per-entity view, and a benchmark that never tested
reality. The per-entity baseline recovered the bots; the relational hub gate then
removed the busy-benign point-to-point channels that diversity alone could not
distinguish. `tests/test_real_benchmark.py` now pins both stacked wins (recall
≥ 0.95, precision ≥ 0.35, flag rate ≤ 0.12) so a future change that silently
reintroduces the real-data blind spot fails even with the synthetic suite green.

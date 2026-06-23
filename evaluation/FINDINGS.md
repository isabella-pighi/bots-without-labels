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

Result on the same benchmark:

```
recall 0.998   precision 0.144   flag rate 0.219   (was 0.022 / 0.018)
```

Recall went from near-zero to near-total; precision improved ~8×.

## The honest ceiling

Per-entity diversity is a strong *ranking* signal but not a clean separator. Busy
*legitimate* servers are as low-diversity as bots — only the shared C2 hub is
uniquely separable — so precision tops out around 0.44 even at an oracle threshold,
and ~0.14 at a non-overfit adaptive one. Closing that gap needs a *second*
discriminator the current data can't supply: sub-minute timing regularity, or
relational structure ("one external hub contacted by many monotonous sources").

The rule is also deliberately **dormant on low-dimensional logs** (few columns →
every actor looks monotonous, carrying no signal), via an absolute diversity
ceiling. That is why the synthetic suite is unaffected.

## Takeaway

The skeleton (unsupervised, role-driven, explainable) is sound; the gap was
calibration plus a missing per-entity view, and a benchmark that never tested
reality. `tests/test_real_benchmark.py` now pins the win so a future change that
silently reintroduces the blind spot fails even with the synthetic suite green.

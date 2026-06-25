# Bots Without Labels

Bots Without Labels ranks the most automation-like actors in an event log that nobody has labeled. It is a ranking system under uncertainty, not a calibrated fraud verdict — every score means "this actor is unusual relative to this batch," never "this is a bot."

Use it to decide **where to look first**, not to decide who is guilty.

Real logs almost never ship with a ground-truth `is_bot` column, so you are detecting
anomalies you cannot directly measure. This project leans into that constraint: an
explainable rules classifier plus an unsupervised **Extended Isolation Forest**,
with a synthetic label-injection workflow to stress-test known failure modes. The
name is a nod to Peter Gabriel's *Games Without Frontiers*: detection played with no
labels to keep score by, so we plant our own.

## How it works

Two classifiers vote on every event:

- a transparent **rules** classifier — per-entity behavioral diversity, relational
  hub structure, an asymmetric-degree actor-graph signal, repetition/concentration,
  and timing (the timing rules are gated by detected timestamp resolution), and
- an **Extended Isolation Forest** for multivariate anomalies.

The decision is deliberately simple and inspectable:

```text
is_bot = heuristic_score >= 0.70 OR ml_score > dynamic_ml_threshold
```

Thresholds are **adaptive and batch-relative** (percentiles, knees, flag-rate caps)
because there are no labels to anchor a fixed cutoff. Scores are operational
estimates — rank-order signals — not measured fraud accuracy.

## The honest evaluation story

**Our synthetic tests lied to us first, and that is the most important lesson here.**
The synthetic suite reported near-perfect recall — because the generator planted
exactly the signatures the rules were already tuned to catch. Detector and benchmark
shared one assumption, so the suite measured agreement with ourselves, not detection.

Then we ran real, externally-labeled traffic (CICIDS2017 botnet). The story inverted:

- **Naive global concentration/repetition failed outright.** Recall **0.022**,
  precision **0.018** — *below* the 3.2% base rate. A flagged row was less likely to
  be a bot than a random one: the signals fired on busy-but-popular benign traffic
  and missed the obvious beaconing host.
- **Per-entity behavioral diversity fixed recall but flooded us with false
  positives.** Scoring each actor by how self-similar its own events are took recall
  **0.022 → 0.998** — but precision only reached **0.144** at a **21.9%** flag rate.
  A busy legitimate server looks just as monotonous as a bot.
- **Relational hub structure is what bought real precision.** Only escalating a
  monotonous actor when it sits in a many-sources-to-one-hub structure lifted
  precision **0.144 → 0.441** and cut the flag rate **0.219 → 0.072**, recall held.
- **Most remaining false positives are not the hub rule's fault.** They come from the
  other rules. On a sub-second NetFlow capture (CTU-13), an asymmetric-degree graph
  rule caught **2000/2000** bot flows with **zero** false fires and took recall
  **0.113 → 1.000** — yet overall precision stayed **~0.04**, because the other
  heuristics keep over-flagging diverse background. Fix the noisy rules, not the
  signal that works.
- **Timing features are conditional, not free.** CICIDS timestamps are
  minute-quantized at the source, so the sub-second burst rules fired on whole-minute
  bins — pure noise. Gating those rules off on coarse clocks (adaptively, by detected
  resolution) pushed CICIDS precision to **0.846** with recall unchanged at 0.998.

## What the evidence supports

- **Per-entity baselines and graph/hub features are the two design changes that
  actually moved the needle.** Everything else is calibration around them.
- On the CICIDS botnet, the stacked design holds recall **0.998** at precision
  **0.846** and a **3.7%** flag rate — a real, externally-labeled result.
- A connectivity-asymmetry graph signal can recover a *diverse* bot — one that
  defeats repetition-based rules — cleanly on its own (2000/2000, zero false fires).
- **Thresholds must be adaptive or batch-relative.** With no labels there is no fixed
  cutoff to trust. Every threshold that worked is a percentile or distribution-derived
  floor measured against the batch — never a hardcoded number, never tuned to a single
  known offender.

## What not to claim

- **Do not report synthetic recall/precision as field accuracy.** Synthetic injection
  is a stress test for known failure modes. It is necessary and it is insufficient.
  The only honest precision/recall numbers are from externally-labeled real data.
- **Do not call a score a probability.** These are rank-order anomaly signals, not
  calibrated fraud probabilities. Do not feed them into a cost-based threshold as if
  they were.
- **Do not claim generality from one attack family.** The diverse-bot graph win is
  same-family evidence (CTU-13/Neris, the family it was built against). It supports a
  hypothesis; it is not proof it transfers to unseen families.
- **Do not present the CTU-13 result as solved.** Recall is recovered; precision is
  not (~0.04 overall) — the diverse-background over-flagging is an open problem.
- **Do not trust timing signals on coarse timestamps.** Minute- or second-resolution
  logs cannot support sub-second burst or cadence features; the engine gates them off,
  and so should your interpretation.

## Quick Start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). See
[INSTALL.md](INSTALL.md) for details and a pip-only alternative.

```bash
git clone <this-repo>
cd bots-without-labels

# Generate a synthetic example log with planted bots (or bring your own)
uv run python -m bots_without_labels.cli generate --output data/sample.tsv

# Run the detector over a log and write predictions + artefacts
uv run --extra eif python -m bots_without_labels.cli run \
  --input data/sample.tsv --output-dir run-output

# Run the test suite
uv run --extra eif python -m pytest
```

The full narrative — load a log, infer its schema, score it, plant synthetic labels,
and read **synthetic-recall** stress results with charts — lives in the notebook:

```bash
uv run jupyter lab    # then open notebooks/bots_without_labels.ipynb
```

Point `generate`, `run`, or `load(...)` at any CSV/TSV/JSON file. Logs dropped under
`data/` are gitignored.

## Running against Kaggle or Hugging Face datasets

`run` takes a **local** CSV/TSV/JSON file — there is no built-in dataset fetcher.
Download the dataset with its own tooling, then point `run --input` at the file.

**Kaggle** (needs the `kaggle` CLI and an API token at `~/.kaggle/kaggle.json`):

```bash
pip install kaggle
kaggle datasets download -d tunguz/clickstream-data-for-online-shopping -p data/ --unzip
uv run --extra eif python -m bots_without_labels.cli run \
  --input data/<downloaded-file>.csv --output-dir run-output
```

**Hugging Face** (needs `huggingface_hub`):

```bash
pip install huggingface_hub
huggingface-cli download mindweave/web-server-logs --repo-type dataset \
  --local-dir data/web-server-logs
uv run --extra eif python -m bots_without_labels.cli run \
  --input data/web-server-logs/<downloaded-file>.csv --output-dir run-output
```

If a Hugging Face dataset ships only as Parquet/Arrow, export one split to a
format the loader reads first:

```bash
python -c "from datasets import load_dataset; \
load_dataset('mindweave/web-server-logs', split='train').to_csv('data/web-server-logs.csv')"
```

The commands work for any CSV/TSV/JSON dataset. Note that these two specific sets
were used in our real-data evaluation and were **not** fair tests — the Hugging Face
web logs showed no lift, and the Kaggle clickstream has no labels to measure against
(see `evaluation/FINDINGS.md`). A fair test needs a rare, externally-labeled attack
population, which is why the kept benchmarks are CICIDS and CTU-13.

## What's In Here

| Path | Purpose |
|---|---|
| `bots_without_labels/` | The detection package: parsing, features, rules, EIF, and CLI. |
| `evaluation/` | Real-data benchmarks (CICIDS, CTU-13) and the per-rule diagnostic; `FINDINGS.md` is the evaluation record. |
| `notebooks/` | The narrative analysis notebook. |
| `data/` | Where to place input logs (not committed). |
| `run-output/` | Generated artefacts and `predictions.tsv`. |
| `tests/` | The pytest suite, including skip-if-absent real-data benchmarks. |
| `development approach/` | The agentic development-team model: roles, prompts, principles, architecture. |
| `TODO.md` | The forward-looking roadmap. |

## Development Approach

`development approach/` documents the small agentic team behind the project — a
product manager, a pair of machine-learning engineers, and a pair of data scientists
who critique each other's work — with the prompts and principles that drive it.

## Licence

See [LICENSE](LICENSE).

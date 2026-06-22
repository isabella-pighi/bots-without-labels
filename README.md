# Bots Without Labels

Finding automated traffic in logs where **nobody has told you which rows are bots**.

Most bot-detection write-ups quietly assume labelled data. Real logs almost never
come with a ground-truth `is_bot` column, so you are left detecting anomalies you
can't measure. Bots Without Labels leans into that constraint: it combines an
explainable rules classifier with an unsupervised **Extended Isolation Forest**
to surface likely-automated events, and then — because the data is unlabelled —
it lets you **inject synthetic bots with known signatures** so you can finally
measure how much of the planted population the detector actually recovers.

The name is a nod to Peter Gabriel's *Games Without Frontiers*: detection played
out with no labels to keep score by, so we plant our own.

## Status

Bots Without Labels runs in two layers: a detection **engine** and a narrative
**notebook**.

| Area | State |
|---|---|
| Autodetecting loader for any CSV/TSV/JSON log | ✅ available |
| Schema-driven feature engineering | ✅ available |
| Rules + EIF anomaly detection | ✅ available |
| Dynamic (Kneedle) threshold selection | ✅ available |
| Synthetic data generator + label injection + measured recall/precision | ✅ available |
| Narrative analysis notebook (where results are read and visualised) | ✅ available |

On planted data the detector recovers **100% of burst, repeated-query,
reused-value, mechanical-timing, and low-entropy bots** at realistic prevalence,
with under 1% false positives on pure-legitimate traffic — measured, not claimed,
because the bots were planted on purpose.

## How It Works

Two classifiers vote on every event:

- a transparent **rules-based** classifier (repeated query/domain pairs,
  mechanical timing, same-second bursts, concentration), and
- an **Extended Isolation Forest (EIF)** unsupervised model for multivariate
  anomalies.

The decision is deliberately simple and inspectable:

```text
is_bot = heuristic_score >= 0.70 OR ml_score > dynamic_ml_threshold
```

Because there are no labels, results are **operational estimates**, not measured
fraud accuracy — which is exactly the gap the synthetic label-injection workflow
is designed to close.

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

The full story — load a log, infer its schema, score it, plant synthetic labels,
and read **measured** recall/precision with charts — lives in the narrative
notebook:

```bash
uv run jupyter lab    # then open notebooks/bots_without_labels.ipynb
```

You can also analyse your own log: point `generate`'s output, the `run` command,
or `load(...)` in the notebook at any CSV/TSV/JSON file. Logs you drop under
`data/` are gitignored.

## What's In Here

| Path | Purpose |
|---|---|
| `bots_without_labels/` | The detection package: parsing, features, rules, EIF, and CLI. |
| `notebooks/` | The narrative analysis notebook — where results are explored and visualised. |
| `data/` | Where to place input logs (not committed). |
| `run-output/` | Generated analysis: artefacts and `predictions.tsv` / `predictions-extended.tsv`. |
| `tests/` | The pytest suite for the pipeline and supporting modules. |
| `development approach/` | The agentic development-team model: roles, prompts, principles, and architecture. |
| `TODO.md` | The forward-looking roadmap. |

## Development Approach

`development approach/` documents the small agentic team behind the project — a
product manager, a pair of machine-learning engineers, and a pair of data
scientists who critique each other's work — with the prompts and principles
that drive it.

## Licence

See [LICENSE](LICENSE).

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

This repository is being generalised from a single ad-click pipeline into a tool
that runs on arbitrary logs. Current state:

| Area | State |
|---|---|
| Rules + EIF detection on click logs | ✅ working |
| Local review dashboard | ✅ working |
| Dynamic (Kneedle) threshold selection | ✅ working |
| Autodetecting loader for any CSV/TSV/JSON log | 🚧 in progress |
| Synthetic data generator + label injection + measured recall/precision | 🚧 in progress |
| Narrative analysis notebook | 🚧 in progress |

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

# Run the detector over a log and write predictions + artefacts
uv run --extra eif python -m bots_without_labels.cli run \
  --input data/your-log.tsv --output-dir run-output

# Explore the results in the local dashboard
uv run --extra eif python -m bots_without_labels.web --port 8000   # http://localhost:8000

# Run the test suite
uv run --extra eif python -m pytest
```

You supply your own log under `data/` (it is gitignored). A synthetic generator
that produces an example dataset — and doubles as ground truth for label
injection — is being added so the repo runs end-to-end on clone.

## What's In Here

| Path | Purpose |
|---|---|
| `bots_without_labels/` | The detection package: parsing, features, rules, EIF, CLI, and the HTTP dashboard (`web.py`). |
| `data/` | Where to place input logs (not committed). |
| `run-output/` | Generated analysis: artefacts and `predictions.tsv` / `predictions-extended.tsv`. |
| `tests/` | The pytest suite for the pipeline, dashboard, and supporting modules. |
| `development approach/` | The agentic development-team model: roles, prompts, principles, and architecture. |
| `TODO.md` | The forward-looking roadmap. |

## The Dashboard

Sections for **Overview**, **Decision Logic** (decision rule, dynamic EIF
threshold plot, probability-perspective summary), **Traffic Explorer**
(filterable candidate rows with per-event rule evidence and single-event lookup),
**Patterns**, and **Help** (a glossary of terms and output fields). It also serves
a feature-matrix viewer at `/features` and the prediction downloads.

## Development Approach

`development approach/` documents the small agentic team behind the project — a
product manager, a pair of machine-learning engineers, and a pair of data
scientists who critique each other's work — with the prompts and principles
that drive it.

## Licence

See [LICENSE](LICENSE).

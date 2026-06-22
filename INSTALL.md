# Install & Run

## Requirements

- Python **3.11 or newer**.
- [uv](https://docs.astral.sh/uv/) (recommended) — handles the virtual
  environment and dependencies from `uv.lock`.
- [Jupyter](https://jupyter.org/) to run the narrative notebook (`uv run jupyter lab`).

The Extended Isolation Forest backend (`isotree`) is an optional extra enabled
with `--extra eif`. It is recommended for the strongest anomaly model.

## Set Up

With uv, no manual environment step is needed — `uv run` creates and syncs the
environment on first use:

```bash
cd bots-without-labels
uv run --extra eif python -m pytest        # verifies the install (should pass)
```

Pip-only alternative:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[eif]"
python -m pytest
```

## Generate Results From A Log

Input logs are not committed to this repository (see `data/README.md`). Point the
CLI at your log:

```bash
uv run --extra eif python -m bots_without_labels.cli run \
  --input data/your-log.tsv \
  --output-dir run-output
```

This writes `predictions.tsv` and supporting artefacts under `run-output/`. Runs
are deterministic for a given input. To produce an example log with planted bots,
use `python -m bots_without_labels.cli generate --output data/sample.tsv`.

## Explore The Results

Open the narrative notebook to load a log, run the detector, inject synthetic
labels, and visualise the results inline:

```bash
uv run jupyter lab    # then open the notebook under notebooks/
```

## Outputs

- `run-output/predictions.tsv` — the two-column `event_id` / `is_bot` prediction.
- `run-output/predictions-extended.tsv` — review diagnostics.
- `run-output/artifacts/` — `summary.json`, event JSON, `features.tsv`, plots.

## Troubleshooting

- **`isotree` build issues** — it needs a C/C++ toolchain; install your
  platform's build tools, or omit `--extra eif` to fall back to the non-EIF path.
- **Slow first run** — `uv` downloads and builds dependencies once, then caches
  them.

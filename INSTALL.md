# Install & Run

## Requirements

- Python **3.11 or newer**.
- [uv](https://docs.astral.sh/uv/) (recommended) — handles the virtual
  environment and dependencies from `uv.lock`.
- A modern web browser for the dashboard.

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

## Run The Dashboard

```bash
uv run --extra eif python -m bots_without_labels.web --port 8000
```

Open <http://localhost:8000>. Options: `--port <n>` (default 8000),
`--host <addr>` (default `127.0.0.1`). The dashboard serves whatever analysis is
present under `run-output/` and can also start a new analysis in the browser via
**Run analysis** / file upload.

## Generate Results From A Log

Input logs are not committed to this repository (see `data/README.md`). Point the
CLI at your log, then open the dashboard:

```bash
uv run --extra eif python -m bots_without_labels.cli run \
  --input data/your-log.tsv \
  --output-dir run-output
```

This writes `predictions.tsv` and supporting artefacts under `run-output/`. Runs
are deterministic for a given input. (A synthetic generator that produces an
example log is being added — see `TODO.md`.)

## Outputs

- `run-output/predictions.tsv` — the two-column `event_id` / `is_bot` prediction.
- `run-output/predictions-extended.tsv` — review diagnostics.
- `run-output/artifacts/` — `summary.json`, event JSON, `features.tsv`, plots.

## Troubleshooting

- **Port already in use** — choose another port: `... --port 8011`.
- **`isotree` build issues** — it needs a C/C++ toolchain; install your
  platform's build tools, or omit `--extra eif` to fall back to the non-EIF path.
- **Slow first run** — `uv` downloads and builds dependencies once, then caches
  them.

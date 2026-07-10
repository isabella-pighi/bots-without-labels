---
name: bwl-build-run-operate
description: >
  Load when you need to set up, run, or operate this repo from scratch: installing the
  environment (uv, the optional `eif` extra / isotree), verifying the install, running the
  detector on a log, reading the artefacts it writes (predictions.tsv,
  predictions-extended.tsv, summary.json, features.tsv, selected_events.json,
  ml_score_threshold.png), running `generate`/`run`/`doctor`, fetching benchmark datasets,
  invoking the benchmark runner, or executing the notebook. Triggers include: "how do I run
  it", "install failed", "isotree/eif not found", "which backend is it using", "what does
  ml_backend / evidence_tier mean", "where are the outputs", "how do I fetch CICIDS/CTU-13",
  "pytest can't import", "black warning about Python 3.15", "there's no CI".
---

# Build, run, and operate Bots Without Labels

Imperative runbook. Every command below was executed against the repo at commit `8a85edd`
(see Provenance). **There is no CI.** No GitHub Actions, no server-side gate — validation is
local discipline. If you do not run the checks yourself, nobody does. That is the single most
important operational fact in this file.

**One-line domain primer** (full theory in `netflow-botnet-reference` /
`bwl-detection-theory`): the tool reads a log of events (NetFlow rows, HTTP access lines,
anything tabular), derives per-row features, scores each row with (a) transparent heuristic
**rules** and (b) an unsupervised **anomaly model** (Extended Isolation Forest, "EIF"), and
flags a row as a bot when either path fires. It never sees labels at run time.

## When NOT to use this skill

| If you are… | Use instead |
| --- | --- |
| Tuning a constant, kwarg, or CLI flag / adding a new one | `bwl-config-and-flags` |
| Measuring accuracy, reading `rule_diagnostic`, feature deviations, thresholds | `bwl-diagnostics-and-tooling` |
| Deciding whether a change is allowed, or needing the commit/review path | `bwl-change-control` |
| Adding a test or benchmark, or asking "what counts as evidence" | `bwl-validation-and-qa` |
| Understanding the maths (entropy, robust-z, Kneedle, rate cap) | `bwl-detection-theory` |
| A run gave wrong/surprising numbers and you need to triage why | `bwl-debugging-playbook` |
| The security terms (C2, botnet, flow, CTU-13, Ares) are unfamiliar | `netflow-botnet-reference` |

This skill covers the mechanical **set-up → run → read outputs → operate** loop only.

---

## 1. Build the environment

**Requirements:** Python **>= 3.11** (repo runs on 3.12 locally). `uv` is the package driver —
it creates and syncs the venv from `uv.lock` on first `uv run`. No manual venv step needed.

### Canonical path (uv) — and the install-verification command

```bash
cd bots-without-labels                     # the repo root, wherever it is cloned
uv run --extra eif python -m pytest        # verifies the install; expect ~80+ passed, all green
```

That single command *is* the install check: it syncs the env, pulls the optional EIF backend,
and runs the suite (~80+ tests at `8a85edd`; get the live count with
`uv run python -m pytest --collect-only -q | tail -1`). A green run means the
install is sound.

### The `eif` extra (isotree) — optional, and the detector degrades silently without it

- `eif` is an **optional extra** declared in `pyproject.toml`: `eif = ["isotree>=0.6.1"]`.
  `isotree` is the C/C++ Extended Isolation Forest library — the strongest anomaly backend.
- **Without it the detector does not error.** `bots_without_labels/anomaly.py::score_matrix`
  catches the `ImportError` and falls back to a dependency-free mean-absolute-robust-z
  deviation score. Weaker (it ignores feature interactions) but valid.
- **How to tell which backend actually ran:** read `ml_backend` in `summary.json` (or the last
  line of the run's stdout):
  | `ml_backend` | Meaning |
  | --- | --- |
  | `eif` | isotree installed and used — the real model |
  | `fallback` | isotree absent (or import failed); transparent robust-z stand-in |
  | `degenerate` | too few rows/features to score at all; constant score vector |
  Verified: hiding the module (`sys.modules['isotree']=None`) flips a run to
  `backend= fallback` with no exception. Installing `--extra eif` gives `ml_backend: "eif"`.
- **Always pass `--extra eif`** for benchmarks and any run whose numbers you will quote.
  Omitting it changes the model, not just its speed.

### Pip-only alternative (no uv)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[eif]"       # ".[eif]" installs the isotree extra too
python -m pytest              # should pass
```

### `doctor` — preflight without running the pipeline

```bash
uv run python -m bots_without_labels.cli doctor            # environment only
uv run python -m bots_without_labels.cli doctor --input data/x.tsv --output-dir run-output
```

`doctor` prints JSON with a `status` (`ok`/`failed`) and one row per check. It checks: Python
>= 3.11; `numpy`/`pandas`/`scipy` importable; the package importable; **isotree presence
(never fails the check — it is reported as advisory, since the fallback exists)**; output dir
writable; and the input file exists when `--input` is given. Exit code `0` when all pass, `1`
when any required check fails. Use it as the first move when a run misbehaves on a new host.

### Dev tooling (what "clean" means here)

| Tool | Command | Expected at `8a85edd` |
| --- | --- | --- |
| black | `uv run black --check bots_without_labels/` | `All done ✨`, files unchanged (line-length **88**, set in `pyproject.toml`) |
| pylint | `uv run pylint bots_without_labels` | **10/10** (design-metric checks disabled in `pyproject.toml`, mirroring Google's pylintrc) |
| pytest | `uv run --extra eif python -m pytest` | ~80+ passed, all green |

---

## 2. Known traps (each verified)

| Trap | What you see | Reality / fix |
| --- | --- | --- |
| Running pytest without uv | `ModuleNotFoundError` / wrong interpreter | Use `uv run python -m pytest` (or activate the venv for the pip path). `pyproject` sets `pythonpath=["."]` and `testpaths=["tests"]`; the runner must be the project env. |
| isotree absent | `ml_backend` reads `fallback` (not `eif`) | **Not an error.** The anomaly path silently degrades. If you expected `eif`, install it: `uv sync --extra eif` (or `uv run --extra eif …`). |
| black safety-check warning | `Warning: Python 3.12 cannot parse code formatted for Python 3.15…` | **Benign.** black still reports files unchanged (verified). It is a target-version note, not a failure. No `target-version` is pinned in `pyproject`. |
| isotree build fails | C/C++ compile errors on `pip install` | isotree needs a toolchain. Install platform build tools, or drop `--extra eif` and run on the `fallback` backend. |
| `degenerate` backend | `ml_backend: "degenerate"`, everything scored constant | Input had too few rows/features for the forest. Expected on tiny inputs; not a bug. |

---

## 3. Run — CLI anatomy

Entry point: `python -m bots_without_labels.cli` (console script also installed as
`bots-without-labels`). Three subcommands: `run`, `generate`, `doctor`. All verified live.

### `generate` — make a synthetic log with planted bots

```bash
uv run python -m bots_without_labels.cli generate \
  --output /tmp/tiny.tsv --legit 200 --bots 30 --seed 1
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--output` | (required) | Path to write the TSV log |
| `--legit` | 900 | Legitimate events |
| `--bots` | 100 | Bot events |
| `--seed` | 0 | Deterministic seed |

Prints `{output, total_events, planted_bots}`. This log carries the planted ground truth the
label-injection workflow measures against (theory: `bwl-detection-theory`,
`bwl-validation-and-qa`). **Synthetic numbers are a stress test, not field accuracy — never
quote them as detection performance.**

### `run` — detect on a log and write artefacts

```bash
uv run --extra eif python -m bots_without_labels.cli run \
  --input /tmp/tiny.tsv --output-dir run-output
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--input` | (required) | Path to a CSV/TSV/JSON log; format & schema auto-detected |
| `--output-dir` | `.` (CLI); README/INSTALL convention is `run-output/` | Directory for `predictions.tsv` + `artifacts/` |

The loader sniffs delimiter and format and infers each column's role (timestamp, category,
number, URL, id); a URL column has its query string expanded into columns automatically — you
do not describe the schema. Bad `--input` exits `2` with a stderr message. On success it
prints the full `summary.json` and a one-line stdout digest:
`Detection summary: 14/230 flagged (6.09%); ml_threshold=… (kneedle_descending); backend=eif`.

**The decision rule** (printed in every summary as `decision_rule`):

```
is_bot = heuristic_score >= 0.70  OR  ml_score > dynamic_ml_threshold
```

The ML threshold is chosen per-run by Kneedle on the sorted anomaly scores, then **rate-capped
so the ML path alone can flag at most 2% of rows** (method string gains `+rate_capped` when
the cap bites). Maths lives in `bwl-detection-theory`. These are scores, **not probabilities**
— do not describe them as such.

---

## 4. Read the artefacts

A `run` writes into `--output-dir`:

```
<output-dir>/
├── predictions.tsv                 two columns: <id>  is_bot(0/1)
├── predictions-extended.tsv        per-row scores + evidence tier + top reason
└── artifacts/
    ├── summary.json                the run's headline dict (also returned/printed)
    ├── features.tsv                the numeric feature matrix, one row per event
    ├── selected_events.json        top flagged rows w/ reasons + feature deviations
    └── ml_score_threshold.png      sorted anomaly scores with the threshold line
```

**All artefact writes are atomic** (`bots_without_labels/atomic.py`): each file is written to a
hidden temp sibling in the same directory then `os.replace`d into place, so a crashed run never
leaves a half-written artefact and readers never see a torn file.

### `predictions.tsv`
Header `<id_column>\tis_bot`. `<id_column>` is the log's own id column if the schema found one,
else a synthetic `row_id` (`row_0`, `row_1`, …). This is the deliverable.

### `predictions-extended.tsv` — columns
| Column | Meaning |
| --- | --- |
| `<id>` | row id |
| `is_bot` | 0/1 decision |
| `evidence_tier` | why selected (see table below) |
| `heuristic_score` | rule score in [0,1] |
| `ml_score` | anomaly score in [0,1] |
| `combined_score` | `max(heuristic, ml)`, used for ranking |
| `top_reason` | first rule reason string (blank for tier-3 / not-selected) |

### Evidence tiers (used across artefacts and `summary.json`)
| Tier | Name | Meaning |
| --- | --- | --- |
| 1 | both | heuristic **and** ML both fired — strongest |
| 2 | heuristic only | rules fired, ML did not |
| 3 | ML only | anomaly model fired, no rule reason (explained by feature deviations) |
| 0 | not selected | not flagged |

### `summary.json` — field by field
| Field | What it tells you |
| --- | --- |
| `input_path` | logged source path (or `display_input_path` if the caller overrode it) |
| `total_events`, `bot_events`, `bot_rate` | row count, flagged count, flagged share |
| `decision_rule` | the human-readable rule string (above) |
| `heuristic_cutoff` | 0.70 — the rule decision cutoff (calibrated to the rule weights) |
| `ml_threshold` | the anomaly cutoff actually applied this run |
| `ml_threshold_method` | e.g. `kneedle_descending`; gains `+rate_capped` when the 2% cap bound |
| `ml_backend` | `eif` / `fallback` / `degenerate` — **check this before trusting numbers** |
| `heuristic_flag_rate`, `ml_flag_rate` | share each path flagged independently |
| `evidence_tier_counts` | `{tier_1_both, tier_2_heuristic_only, tier_3_ml_only, not_selected}` |
| `id_column` | which column is the row id |
| `feature_names` | ordered feature list (matches `features.tsv` columns) |
| `schema` | inferred column roles |
| `rule_thresholds` | the per-rule thresholds/gates the rules chose this run (which rules were active, entity/actor columns, degree floors, etc.) |
| `top_reasons` | the 10 most common reason strings among flagged rows, with counts |

### `features.tsv`
`<id>` column then one column per `feature_names` entry, `%.6f` values. This is exactly what the
anomaly model scored; use it with `bwl-diagnostics-and-tooling` to inspect deviations.

### `selected_events.json` — the triage sample
A JSON list of the flagged rows, **highest `combined_score` first, capped at 500 rows** (it is a
reviewable sample, not the full set — `predictions.tsv` holds everything). Each record:
`event_id`, `evidence_tier`, `heuristic_score`, `ml_score`, `combined_score`, up to six
`reasons`, and `feature_deviations` — a list of `{feature, value, robust_z, batch_percentile}`
entries naming the features whose values sit furthest in the batch's tail. **This is what makes
a reasonless tier-3 (ML-only) flag reviewable:** no rule text, but the deviations say *which*
feature values were extreme.

### `ml_score_threshold.png`
Anomaly scores sorted descending, with a dashed vertical/horizontal line at the applied
threshold (labelled with its value). Read it to see whether the threshold sits in a genuine
elbow or on a flat shoulder. Not written when there are zero scored rows.

---

## 5. Data conventions

- `data/` is **gitignored except `data/README.md`** (`.gitignore` excludes `*.tsv *.csv *.json
  *.jsonl *.zip *.binetflow` and `data/samples/`). **Never commit a dataset.** They are large,
  often licence-restricted, and reproducible by fetch.
- Benchmark wrappers write only a **temporary** mix file per run and discard it; they never
  write or commit into `data/`.
- **~400 MB soft ceiling** on committed-workflow datasets, stated in the CTU-13 module
  docstring. Files above it (e.g. CTU-13 sc3 / Rbot at 640 MB) are opt-in local fetches.
- The benchmark runner and the real-data tests **skip cleanly when a dataset is absent** — a
  missing file is a skip, never a failure.

### Fetch commands (URLs verified from module docstrings)

| Dataset | Local path | Fetch | Notes |
| --- | --- | --- | --- |
| CTU-13 sc1 / Neris (tracked) | `data/capture20110810.binetflow` | `curl -o data/capture20110810.binetflow https://mcfp.felk.cvut.cz/publicDatasets/CTU-Malware-Capture-Botnet-42/detailed-bidirectional-flow-labels/capture20110810.binetflow` | 369 MB, under the ceiling. Licence CC-BY (Stratosphere Lab, CTU). |
| CTU-13 sc3 / Rbot (tracked, 2nd family) | `data/capture20110812.binetflow` | `curl -o data/capture20110812.binetflow https://mcfp.felk.cvut.cz/publicDatasets/CTU-Malware-Capture-Botnet-44/detailed-bidirectional-flow-labels/capture20110812.binetflow` | 640 MB, **above** the ceiling — opt-in. |
| CICIDS2017 Friday / Ares (tracked) | `data/GeneratedLabelledFlows.zip` | Obtain the "GeneratedLabelledFlows" archive from the CICIDS2017 source (UNB/CIC); no no-auth direct URL is embedded in the module. | Bot file inside zip: `TrafficLabelling /Friday-WorkingHours-Morning.pcap_ISCX.csv` (leading space is upstream). |
| UNSW-NB15 (secondary) | `data/UNSW-NB15_1.csv` … `_4.csv` | Gated behind the UNSW research portal (registration). No reliable no-auth link — wrapper ships dormant, skips if absent. | Must be the **raw headerless 49-col** shards (carry `srcip/dstip/Stime/Label`); the stripped HF "training-set" mirror is unusable. |
| Bournemouth Web Bot (secondary, web-log) | `data/web_bot_detection_dataset.zip` | `https://m4d.iti.gr/web-bot-detection-dataset/` — single ~32 MB public zip. | Research-use licence, not formally CC. **Numbers are internal/provisional pending licence confirmation.** |

---

## 6. Operate

### Run the benchmark suite (single entry point)

```bash
uv run --extra eif python -m evaluation.run_benchmarks                 # all present benchmarks
uv run --extra eif python -m evaluation.run_benchmarks --only ctu13,cicids2017
```

- **Do not run the full suite casually — it is slow** and needs the large datasets present.
  Absent datasets skip. Use `--only <keys>` to scope it. Valid keys: `cicids2017`, `ctu13`,
  `ctu13_sc3`, `unsw`, `bournemouth`. An unknown key exits `2` with the valid list.
- It prints **one** table (rows / base rate / flag / recall / precision) plus a per-benchmark
  caveat line, tagging each row `tracked` or `secondary`.
- For recorded numbers, cite the docs of record rather than re-running: `evaluation/BENCHMARKS.md`
  (registry) and `evaluation/FINDINGS.md` (narrative). **Tracked (real, externally labelled),
  as recorded 2026-07-04:** CICIDS2017/Ares recall 0.998 / precision 0.846 / flag 0.037;
  CTU-13 sc1/Neris 1.000 / 0.978 / 0.033; CTU-13 sc3/Rbot 0.985 / 0.929 / 0.034.
  **Secondary:** UNSW-NB15 1.000 / 0.519 / 0.062 (broad IDS, not a bot result); Bournemouth
  web logs 0.873 / 0.028 / 0.918 (**provisional, licence-pending; negative domain transfer**).
  Source: `evaluation/FINDINGS.md` / `evaluation/BENCHMARKS.md` — re-verify before quoting.
- The **synthetic** suite is a stress test only and runs via `pytest`, never appears in this
  table, and is never a tracked accuracy number.

### The narrative notebook

- Lives at `notebooks/bots_without_labels.ipynb`. Open with `uv run jupyter lab`.
- **Team rule (from `development approach/shared_agent_principles.md` §11): when you touch the
  notebook it must be executed top-to-bottom without errors**, with cells reflecting current
  outputs (not stale values), visualisations rendering, and interpretation honest on unlabelled
  data. Verify the *rendered* output, not just the source cells. Static string edits are not
  enough. This is Data-Scientist-role work (see `bwl-change-control` for who commits).

### A 60-second smoke test on a throwaway log

```bash
uv run python -m bots_without_labels.cli generate --output /tmp/tiny.tsv --legit 200 --bots 30 --seed 1
uv run --extra eif python -m bots_without_labels.cli run --input /tmp/tiny.tsv --output-dir /tmp/out
cat /tmp/out/artifacts/summary.json    # check ml_backend == "eif", sane bot_rate
```

Verified end-to-end at `8a85edd`: 230 events, 14 flagged (6.09%), `ml_backend: "eif"`,
`ml_threshold_method: "kneedle_descending"`.

---

## Provenance and maintenance

Authored **2026-07-04**; verified against the repo at commit **`8a85edd`** on **2026-07-06** by
running the cheap commands (generate + run + doctor on a `/tmp` log, `pytest --collect-only`,
`black --check`, forced-fallback backend probe). There is no CI; treat every number as
re-verifiable, not guaranteed-current.

| Volatile fact | One-line re-verification |
| --- | --- |
| Suite collects and passes | `uv run python -m pytest --collect-only -q \| tail -1` |
| CLI subcommands & flags | `uv run python -m bots_without_labels.cli --help && uv run python -m bots_without_labels.cli run --help` |
| Optional extra `eif` → isotree | `grep -A2 'optional-dependencies' pyproject.toml` |
| black line-length 88 / pylint config | `grep -nE 'line-length\|max-line-length' pyproject.toml` |
| `ml_backend` values | `grep -n 'degenerate\|fallback\|\"eif\"' bots_without_labels/anomaly.py` |
| Fallback triggers silently (no error) | `uv run python -c "import sys;sys.modules['isotree']=None;import numpy as np;from bots_without_labels.anomaly import score_matrix;print(score_matrix(np.random.rand(50,6))[1])"` |
| Decision rule / 0.70 cutoff / 2% cap | `grep -nE 'HEURISTIC_CUTOFF\|MAX_ML_FLAG_RATE\|DECISION_RULE' bots_without_labels/pipeline.py` |
| Artefact set & atomic writes | `sed -n '194,265p' bots_without_labels/pipeline.py` ; `cat bots_without_labels/atomic.py` |
| summary.json fields | run `… cli run` on a tiny log, inspect `artifacts/summary.json` |
| Benchmark keys & runner | `uv run python -m evaluation.run_benchmarks --help` |
| Dataset URLs / sizes / 400 MB ceiling | `sed -n '1,45p' evaluation/ctu13_bot_benchmark.py` (and sibling `*_benchmark.py` docstrings) |
| data/ gitignore policy | `cat .gitignore` (see the `data/*` lines) |
| Notebook top-to-bottom rule | `sed -n '194,209p' "development approach/shared_agent_principles.md"` |
| Tracked benchmark numbers | `cat evaluation/BENCHMARKS.md evaluation/FINDINGS.md` (authoritative; re-read, do not trust this table) |

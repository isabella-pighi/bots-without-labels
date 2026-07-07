# Input data

Input logs are **not** committed to this repository (this directory is gitignored
apart from this README).

Place a log here and point the CLI at it:

```bash
uv run --extra eif python -m bots_without_labels.cli run \
  --input data/your-log.tsv --output-dir run-output
```

The loader autodetects the format (CSV/TSV with a sniffed delimiter, or JSON /
JSON-lines) and infers each column's role — timestamps, categories, numbers,
URLs, identifiers — so you do not need to describe the schema. A URL column has
its query string expanded into ordinary columns automatically.

A synthetic data generator — which also produces the planted ground truth used by
the label-injection workflow — lets you generate a realistic example dataset
without supplying your own (see the roadmap in `TODO.md`).

## Benchmark datasets (not committed — fetch locally)

The real-data benchmarks under `evaluation/` measure the detector against
*independent, externally labelled* captures. Those files are **large and
licence-bound, so they are never committed** (`.gitignore` excludes every
`*.zip`, `*.csv`, `*.binetflow`, etc. in this directory). This has one direct
consequence for validation:

> **The real-data benchmark gates are a local/manual gate, not a CI gate.**
> `tests/test_real_benchmark.py`, `test_ctu13_benchmark.py`,
> `test_ctu13_sc3_benchmark.py` and `test_bournemouth_benchmark.py` each
> `skipif` the capture is absent, so CI (which has no datasets) runs the hermetic
> suite only and these tests **skip cleanly**. To run them you must fetch the
> data below and run locally with the `eif` backend:
> `uv run --extra eif python -m evaluation.run_benchmarks`.

| Dataset | File(s) in `data/` | Size | Licence | What it tests | Test |
|---|---|---|---|---|---|
| **CICIDS2017** (Fri, Ares botnet) | `GeneratedLabelledFlows.zip` | ~271 MB | UNB CIC, research use; cite Sharafaldin et al. 2018 | Fan-in C2, minute-quantised clock | `test_real_benchmark.py` |
| **CTU-13 sc1** (Neris) | `capture20110810.binetflow` | 369 MB | CC-BY (Stratosphere/CTU) | Microsecond fast beacons | `test_ctu13_benchmark.py` |
| **CTU-13 sc3** (Rbot) | `capture20110812.binetflow` | 640 MB | CC-BY (Stratosphere/CTU) | Second-family generality | `test_ctu13_sc3_benchmark.py` |
| **UNSW-NB15** | `UNSW-NB15_1.csv` (+ shards `_2`.._4) | ~161 MB each | UNSW Canberra, research-use; cite Moustafa & Slay 2015 | Broad attack mix | `evaluation/unsw_benchmark.py` |
| **Bournemouth web-bot** | `web_bot_detection_dataset.zip` | 32 MB | **unconfirmed** — treat numbers as internal until confirmed | Human-mimicking web bots (domain transfer) | `test_bournemouth_benchmark.py` |

### How to fetch

```bash
# CTU-13 scenario 1 / Neris (369 MB, CC-BY)
curl -o data/capture20110810.binetflow \
  https://mcfp.felk.cvut.cz/publicDatasets/CTU-Malware-Capture-Botnet-42/detailed-bidirectional-flow-labels/capture20110810.binetflow

# CTU-13 scenario 3 / Rbot (640 MB, CC-BY, opt-in — above the 400 MB working ceiling)
curl -o data/capture20110812.binetflow \
  https://mcfp.felk.cvut.cz/publicDatasets/CTU-Malware-Capture-Botnet-44/detailed-bidirectional-flow-labels/capture20110812.binetflow
```

The others are registration- or portal-gated, so download by hand into `data/`:

- **CICIDS2017** — UNB Canadian Institute for Cybersecurity: <https://www.unb.ca/cic/datasets/ids-2017.html> (use the `GeneratedLabelledFlows.zip` bundle).
- **UNSW-NB15** — UNSW Canberra: <https://research.unsw.edu.au/projects/unsw-nb15-dataset> (the CSV shards).
- **Bournemouth web-bot** — <https://m4d.iti.gr/web-bot-detection-dataset/> (single 32 MB zip). Licence is unconfirmed; keep any measured numbers internal until it is (see `evaluation/bournemouth_benchmark.py`).

Provenance and per-benchmark detail live in each `evaluation/*_benchmark.py`
module docstring; the recorded results live in `evaluation/BENCHMARKS.md`.

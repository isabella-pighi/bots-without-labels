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

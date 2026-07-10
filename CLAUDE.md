# CLAUDE.md

The operating contract for this repository lives in **[`AGENTS.md`](AGENTS.md)** —
read it first. It applies in full to Claude Code. This file adds only the
Claude-Code-specific notes.

## Claude Code specifics

- **Skills are the primary knowledge layer.** The `.claude/skills/bwl-*` playbooks
  load on trigger; lean on them rather than re-deriving. Load the matching skill
  *before* touching its subject — e.g. `bwl-architecture-contract` before changing
  a rule weight or the 0.70 cutoff, `bwl-change-control` before committing,
  `bwl-proof-and-analysis-toolkit` before attributing a precision move,
  `bwl-validation-and-qa` before claiming a number is citable,
  `bwl-failure-archaeology` before re-attempting a rejected idea.

- **Memory** persists in Claude Code's per-project memory directory
  (`~/.claude/projects/<project-slug>/memory/`, where the slug is derived from
  this repository's absolute path) with a one-line index in `MEMORY.md`. It is
  working context, **not** the source of truth (AGENTS.md §4) — verify any
  recalled file/flag/threshold against the current repository before acting on it.

- **The team.** "Use the team" / "Claude + OpenAI" means orchestrate the HCOM
  agents (product manager routes; Codex reviews Claude), not solo work. See
  `development approach/` and the `hcom-*` memories.

- **Non-negotiables restated** (full text in AGENTS.md): evidence over assertion;
  predict before you run; anomaly scores are not fraud proof; no unlabelled
  precision claims; refactors must be bit-identical; no direct-to-main; record
  negative results in `evaluation/FINDINGS.md`.

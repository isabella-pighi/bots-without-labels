#!/usr/bin/env python3
"""Flag golden-number drift between the skill library and the docs of record.

WHY THIS EXISTS
---------------
The same benchmark metrics (CICIDS 0.998/0.846/0.037, CTU-13 sc1 1.000/0.978/
0.033, ...) are quoted inside roughly ten skills for self-containedness. That is
fine for reading, but it is a *maintenance* hazard: when a benchmark is re-run
and a number moves, ``evaluation/BENCHMARKS.md`` gets updated but a stale copy
can survive in a skill nobody thought to touch.

HOW IT WORKS
------------
The docs of record are the single source of truth. This script:

1. Extracts every metric *triple* (three decimals in [0, 1] separated only by
   ``/`` or ``|`` or short glue like " / precision ") from
   ``evaluation/BENCHMARKS.md`` and ``evaluation/FINDINGS.md``. That set is the
   ALLOWLIST — the current registry numbers plus the documented historical
   progression rows.
2. Extracts the same triples from every ``.claude/skills/*/SKILL.md``.
3. Flags any skill triple that is NOT in the allowlist. A flag means either a
   typo, or a number the registry has since changed and the skill did not.
4. Reads every module-level numeric constant defined in ``bots_without_labels/``
   and ``evaluation/`` (``NAME = <number>``), then flags any skill that cites
   ``NAME = value`` with a value that disagrees with the source. This is the
   high-harm class: a stale ``HEURISTIC_CUTOFF`` or ``DEGREE_ASYMMETRY`` in a
   skill would send an engineer down a wrong path. Constants defined with
   different values in different modules (e.g. per-benchmark ``N_BOT``) are
   ambiguous and skipped.
5. Checks every commit hash cited in a skill's Provenance section is a real
   ancestor of ``HEAD`` — catching a typo, a fabricated hash, or a reference to
   a commit that only exists on an unmerged branch. (It does NOT demand the
   authoring stamp equal HEAD: a committed library's stamp always trails HEAD by
   the commit that added it, and that is correct, not drift.)

Numbers are normalised before comparison (``1.0`` == ``1.000``, ``0.02`` ==
``0.020``), so pure formatting never trips a false positive. Historical commit
references elsewhere in a skill (e.g. the incident hashes in
bwl-failure-archaeology) are deliberately ignored — only the Provenance stamp is
checked against HEAD.

USAGE
-----
    uv run python .claude/skills/bwl-docs-and-writing/scripts/check_golden_numbers.py
    # or plain: python3 .claude/skills/bwl-docs-and-writing/scripts/check_golden_numbers.py

Exit code 0 = clean, 1 = at least one drift/typo/stale-stamp flagged.
Options: --quiet (only print flags + verdict), --no-commit (skip the HEAD check).

Stdlib only. Safe: reads files and runs `git rev-parse` read-only; writes nothing.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# A decimal in [0, 1] as the docs write metrics: 0.998, 0.02, 1.000, 1.0.
_DECIMAL = r"(?:1\.0(?:00)?|0\.\d{2,4})"
# A metric CITATION triple as skills actually write one: three decimals joined
# by a slash, optionally with spaces and a label word ("0.998/0.846/0.037",
# "0.998 / 0.846 / 0.037", "recall 0.998 / precision 0.846 / flag 0.037").
# Requiring a slash separator is what keeps arithmetic (0.12+0.12+0.08),
# array/code (0.50, 0.70, 0.90) and before→after arrows (0.201 → 0.020) OUT.
_SEP = r"\s*/\s*(?:[A-Za-z]+\s+)?"
_SLASH_TRIPLE_RE = re.compile(rf"({_DECIMAL}){_SEP}({_DECIMAL}){_SEP}({_DECIMAL})")
# A pure-decimal markdown table cell, e.g. "0.998" or "**0.846**".
_DECIMAL_CELL = re.compile(rf"^(?:\*\*)?({_DECIMAL})(?:\*\*)?$")
_COMMIT_RE = re.compile(r"\b([0-9a-f]{7,40})\b")
# Lines that carry decimals as re-verification commands, not as claims; their
# numbers live inside grep patterns and must not be read as independent facts.
_COMMAND_HINT = re.compile(r"grep|rev-parse|pytest|collect-only")
# A numeric literal as source and skills write it: 100, 0.70, 4096, 65_536,
# 1e-3, 999.0, -1.
_NUMBER = r"-?\d[\d_]*(?:\.\d+)?(?:[eE]-?\d+)?"
# A module-level constant definition: NAME = <number>  (trailing comment ok).
_CONST_DEF_RE = re.compile(rf"^([A-Z][A-Z0-9_]+)\s*=\s*({_NUMBER})\s*(?:#.*)?$")


def _repo_root(start: Path) -> Path:
    """Return the repository root by walking up to the pyproject.toml marker."""
    for parent in [start, *start.parents]:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def _norm(dec: str) -> str:
    """Canonicalise a decimal string so 1.0 == 1.000 and 0.02 == 0.020."""
    text = f"{float(dec):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _table_triples(text: str) -> set[tuple[str, str, str]]:
    """Extract metric triples from markdown tables (the registry's own format).

    A metric triple is a run of three *consecutive* pure-decimal cells — which
    is exactly how the registry writes ``| ... | 0.998 | 0.846 | 0.037 |`` and
    how FINDINGS writes its progression rows — so an isolated base-rate cell
    (``0.032`` with text on either side) never chains into one.
    """
    out: set[tuple[str, str, str]] = set()
    for line in text.splitlines():
        if line.count("|") < 3:
            continue
        run: list[str] = []
        for cell in line.split("|"):
            match = _DECIMAL_CELL.match(cell.strip())
            if match:
                run.append(_norm(match.group(1)))
                continue
            for i in range(len(run) - 2):
                out.add((run[i], run[i + 1], run[i + 2]))
            run = []
        for i in range(len(run) - 2):
            out.add((run[i], run[i + 1], run[i + 2]))
    return out


def _slash_triples(text: str) -> set[tuple[str, str, str]]:
    """Extract slash-separated metric-citation triples (docs prose form)."""
    out: set[tuple[str, str, str]] = set()
    for line in text.splitlines():
        if _COMMAND_HINT.search(line):
            continue
        for match in _SLASH_TRIPLE_RE.finditer(line):
            out.add(tuple(_norm(g) for g in match.groups()))  # type: ignore[arg-type]
    return out


def _skill_triples_with_lines(text: str) -> list[tuple[int, str, tuple[str, str, str]]]:
    """Slash-citation triples in a skill, with line number and raw text."""
    found: list[tuple[int, str, tuple[str, str, str]]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _COMMAND_HINT.search(line):
            continue
        for match in _SLASH_TRIPLE_RE.finditer(line):
            norm = tuple(_norm(g) for g in match.groups())
            found.append((lineno, line.strip(), norm))  # type: ignore[arg-type]
    return found


def _num(raw: str) -> float:
    """Parse a numeric literal, tolerating underscores (65_536) and 1e-3."""
    return float(raw.replace("_", ""))


def _source_constants(py_files: list[Path]) -> dict[str, float]:
    """Map every module-level ``NAME = <number>`` to its value across modules.

    A name defined with conflicting values in different modules (e.g. the
    per-benchmark ``N_BOT``) is ambiguous — no single source truth — so it is
    dropped and never checked.
    """
    values: dict[str, float] = {}
    conflicting: set[str] = set()
    for path in py_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _CONST_DEF_RE.match(line)
            if not match:
                continue
            name, value = match.group(1), _num(match.group(2))
            if name in values and abs(values[name] - value) > 1e-9:
                conflicting.add(name)
            values[name] = value
    for name in conflicting:
        values.pop(name, None)
    return values


def _constant_flags(
    skill_files: list[Path], root: Path, constants: dict[str, float]
) -> list[str]:
    """Flag skills that cite ``NAME = value`` disagreeing with the source value."""
    # One matcher per known constant: the name, then up to a little glue
    # (``=``, spaces, an opening paren), then the number it is given.
    matchers = {
        name: re.compile(rf"\b{re.escape(name)}\b[\s=(]{{0,4}}({_NUMBER})")
        for name in constants
    }
    flags: list[str] = []
    for skill in skill_files:
        for lineno, line in enumerate(
            skill.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _COMMAND_HINT.search(line):
                continue
            for name, matcher in matchers.items():
                for hit in matcher.finditer(line):
                    cited = _num(hit.group(1))
                    if abs(cited - constants[name]) > 1e-9:
                        rel = skill.relative_to(root)
                        flags.append(
                            f"  CONST  {rel}:{lineno}\n"
                            f"         cites {name} = {hit.group(1)} — source is "
                            f"{constants[name]:g}\n"
                            f"         > {line.strip()[:100]}"
                        )
    return flags


def _git_ok(root: Path) -> bool:
    """Return True if this is a usable git checkout."""
    try:
        subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-dir"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _is_ancestor(root: Path, commit: str) -> bool:
    """True if ``commit`` is a real commit in HEAD's history.

    A provenance hash that is NOT an ancestor of HEAD is the thing worth
    flagging: a typo, a fabricated hash, or a commit that lives only on an
    unmerged branch. The authoring stamp of a just-committed library IS an
    ancestor of HEAD (HEAD is the commit that added the skills), so this does
    not go red the moment the library lands — unlike a naive "stamp == HEAD".
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],
            capture_output=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _provenance_tail(text: str) -> str:
    """Return the text at/after the last 'Provenance' heading (the stamp lives there)."""
    lowered = text.lower()
    idx = lowered.rfind("provenance")
    return text[idx:] if idx != -1 else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--quiet", action="store_true", help="only print flags + verdict"
    )
    parser.add_argument(
        "--no-commit", action="store_true", help="skip the HEAD provenance check"
    )
    args = parser.parse_args(argv)

    root = _repo_root(Path(__file__).resolve())
    docs = [root / "evaluation" / "BENCHMARKS.md", root / "evaluation" / "FINDINGS.md"]
    skills_dir = root / ".claude" / "skills"
    source_dirs = [root / "bots_without_labels", root / "evaluation"]

    missing = [d for d in docs if not d.is_file()] + (
        [] if skills_dir.is_dir() else [skills_dir]
    )
    if missing:
        print("ERROR: expected files not found:", ", ".join(str(m) for m in missing))
        return 1

    # 1. Allowlist of legitimate triples from the docs of record: the registry
    #    and progression tables, plus any slash-cited triples in the prose.
    allow: set[tuple[str, str, str]] = set()
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        allow |= _table_triples(text) | _slash_triples(text)

    # Source-of-truth constant values (bots_without_labels/ + evaluation/).
    py_files = sorted(f for d in source_dirs for f in d.glob("*.py"))
    constants = _source_constants(py_files)

    if not args.quiet:
        print(f"repo: {root}")
        print(
            f"allowlist: {len(allow)} metric triples from BENCHMARKS.md + FINDINGS.md"
        )
        print(f"constants: {len(constants)} module-level values from source")
        print()

    # 2/3. Scan skills; flag slash-cited triples not in the allowlist.
    skill_files = sorted(skills_dir.glob("*/SKILL.md"))
    triple_flags: list[str] = []
    for skill in skill_files:
        text = skill.read_text(encoding="utf-8")
        for lineno, raw, norm in _skill_triples_with_lines(text):
            if norm not in allow:
                rel = skill.relative_to(root)
                triple_flags.append(
                    f"  DRIFT  {rel}:{lineno}\n"
                    f"         cites {'/'.join(norm)} — not in BENCHMARKS.md/FINDINGS.md\n"
                    f"         > {raw[:100]}"
                )

    # 4. Constant citations vs source.
    const_flags = _constant_flags(skill_files, root, constants)

    # 5. Every commit hash cited in a Provenance section must be a real
    #    ancestor of HEAD (catches typos, fabricated hashes, unmerged refs).
    stamp_flags: list[str] = []
    git_available = not args.no_commit and _git_ok(root)
    if git_available:
        for skill in skill_files:
            tail = _provenance_tail(skill.read_text(encoding="utf-8"))
            bad = sorted(
                {h for h in _COMMIT_RE.findall(tail) if not _is_ancestor(root, h)}
            )
            if bad:
                rel = skill.relative_to(root)
                stamp_flags.append(
                    f"  PROV   {rel}: Provenance cites commit(s) not in HEAD's "
                    f"history: {bad} (typo, fabricated, or unmerged branch)"
                )

    # Report.
    if not args.quiet:
        print(f"scanned {len(skill_files)} skills")
        if git_available:
            print(
                "provenance: all cited commits are ancestors of HEAD"
                if not stamp_flags
                else f"provenance: {len(stamp_flags)} skill(s) cite " "unknown commits"
            )
        print()

    if triple_flags:
        print(f"METRIC DRIFT ({len(triple_flags)}):")
        print("\n".join(triple_flags))
        print()
    if const_flags:
        print(f"CONSTANT DRIFT ({len(const_flags)}):")
        print("\n".join(const_flags))
        print()
    if stamp_flags:
        print(f"UNKNOWN PROVENANCE COMMITS ({len(stamp_flags)}):")
        print("\n".join(stamp_flags))
        print()

    if triple_flags or const_flags or stamp_flags:
        print(
            "VERDICT: drift found — reconcile each flag against the docs of record "
            "(metrics), source (constants), or git history (provenance)."
        )
        return 1
    print(
        "VERDICT: clean — skill metrics match the docs, constants match source, "
        "provenance commits are real."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line interface for running and diagnosing Bots Without Labels."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from .pipeline import run_pipeline


def _input_file_error(path: Path) -> str | None:
    """Return a user-facing input-file error, or ``None`` when valid.

    Args:
        path: Input path provided by the user.

    Returns:
        Error text when the path is not a readable file; otherwise ``None``.
    """

    if not path.exists():
        return f"Input file '{path}' does not exist."
    if not path.is_file():
        return f"Input file '{path}' is not a file."
    return None


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _path_is_writable(path: Path) -> bool:
    target = path if path.exists() else path.parent
    if not target.exists():
        return False
    if not target.is_dir():
        return False

    try:
        with TemporaryDirectory(dir=target):
            return True
    except OSError:
        return False


def run_doctor(
    *,
    input_path: Path | None = None,
    output_dir: Path = Path("."),
) -> tuple[int, dict[str, object]]:
    """Check local runtime prerequisites without running the pipeline.

    Args:
        input_path: Optional input log path to verify.
        output_dir: Directory to test for artifact writability.

    Returns:
        A pair of ``(exit_code, payload)``. The payload is JSON-ready and
        contains check rows plus remediation advice when a check fails.
    """

    checks: list[dict[str, object]] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    python_version = platform.python_version()
    python_ok = sys.version_info >= (3, 11)
    add_check(
        "python",
        python_ok,
        f"Python {python_version}; required >= 3.11",
    )

    for module_name in ("numpy", "pandas", "scipy"):
        add_check(
            f"import:{module_name}",
            _module_available(module_name),
            f"Python module '{module_name}' is importable",
        )

    add_check(
        "package:bots_without_labels",
        _module_available("bots_without_labels"),
        "Bots Without Labels package is importable",
    )

    # The Extended Isolation Forest backend is optional; without it the detector
    # falls back to a dependency-free anomaly score, so this never fails the run.
    eif_available = _module_available("isotree")
    add_check(
        "optional:isotree",
        True,
        (
            "Extended Isolation Forest backend available"
            if eif_available
            else "isotree not installed; using the built-in fallback "
            "(install with: uv sync --extra eif)"
        ),
    )

    add_check(
        "output_dir",
        _path_is_writable(output_dir),
        f"Output directory '{output_dir}' is writable",
    )

    if input_path is not None:
        add_check(
            "input_file",
            input_path.is_file(),
            f"Input file '{input_path}' exists",
        )

    failed = [check for check in checks if not check["ok"]]
    status = "ok" if not failed else "failed"
    payload: dict[str, object] = {
        "status": status,
        "checks": checks,
        "advice": [],
    }
    if failed:
        payload["advice"] = [
            "Run `uv sync --extra eif` from the repository root.",
            "Check that the input path exists and the output directory is writable.",
        ]
    return (0 if not failed else 1, payload)


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface.

    Args:
        argv: Optional argument list. ``None`` uses ``sys.argv`` via argparse.

    Returns:
        Process exit code.
    """

    parser = argparse.ArgumentParser(prog="bots-without-labels")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Run detection on a log and write predictions and artefacts"
    )
    run_parser.add_argument("--input", required=True, help="Path to a CSV/TSV/JSON log")
    run_parser.add_argument(
        "--output-dir", default=".", help="Directory for artifacts and predictions.tsv"
    )
    run_parser.add_argument(
        "--entity-column",
        action="append",
        default=[],
        metavar="COLUMN",
        help=(
            "Explicitly declare COLUMN an actor/entity column (repeatable). "
            "Use when autodetection cannot see an identity — an integer-coded "
            "session id or IP, or a closed pool of short unstructured ids. "
            "Default off: without this flag behaviour is unchanged."
        ),
    )
    run_parser.add_argument(
        "--content-column",
        action="append",
        default=[],
        metavar="COLUMN",
        help=(
            "Explicitly declare COLUMN content, excluding it from actor/entity "
            "selection (repeatable). Use when a content-like column (e.g. a "
            "raw request path) is misread as an identity. Default off."
        ),
    )

    generate_parser = subparsers.add_parser(
        "generate", help="Write a synthetic example log with planted bots"
    )
    generate_parser.add_argument(
        "--output", required=True, help="Path to write the generated TSV log"
    )
    generate_parser.add_argument(
        "--legit", type=int, default=900, help="Legitimate events"
    )
    generate_parser.add_argument("--bots", type=int, default=100, help="Bot events")
    generate_parser.add_argument(
        "--seed", type=int, default=0, help="Deterministic seed"
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check local installation and runtime prerequisites",
    )
    doctor_parser.add_argument(
        "--input",
        help="Optional input TSV path to validate",
    )
    doctor_parser.add_argument(
        "--output-dir",
        default=".",
        help="Output directory to test for writability",
    )

    args = parser.parse_args(argv)
    if args.command == "run":
        input_path = Path(args.input)
        input_error = _input_file_error(input_path)
        if input_error is not None:
            print(input_error, file=sys.stderr)
            return 2
        try:
            summary = run_pipeline(
                input_path,
                Path(args.output_dir),
                entity_columns=tuple(args.entity_column),
                content_columns=tuple(args.content_column),
            )
        except ValueError as exc:
            # Unknown/conflicting override names are user errors, not crashes.
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(summary, indent=2))
        return 0
    if args.command == "generate":
        # pylint: disable=import-outside-toplevel
        from .synthetic import generate, write_log

        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        log = generate(n_legit=args.legit, n_bots=args.bots, seed=args.seed)
        write_log(output, log.frame)
        print(
            json.dumps(
                {
                    "output": str(output),
                    "total_events": int(log.frame.shape[0]),
                    "planted_bots": int(log.is_bot.sum()),
                },
                indent=2,
            )
        )
        return 0
    if args.command == "doctor":
        input_path = Path(args.input) if args.input else None
        exit_code, payload = run_doctor(
            input_path=input_path,
            output_dir=Path(args.output_dir),
        )
        print(json.dumps(payload, indent=2))
        return exit_code

    return 1


if __name__ == "__main__":
    sys.exit(main())

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
        return f"Input TSV '{path}' does not exist."
    if not path.is_file():
        return f"Input TSV '{path}' is not a file."
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
        input_path: Optional raw click TSV path to verify.
        output_dir: Directory to test for artifact writability.

    Returns:
        A pair of ``(exit_code, payload)``. The payload is JSON-ready and
        contains check rows plus remediation advice when a check fails.
    """

    checks: list[dict[str, object]] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    python_version = platform.python_version()
    python_ok = sys.version_info >= (3, 10)
    add_check(
        "python",
        python_ok,
        f"Python {python_version}; required >= 3.10",
    )

    for module_name in ("numpy", "pandas", "scipy", "isotree"):
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
        "run", help="Run classifiers and write artifacts"
    )
    run_parser.add_argument("--input", required=True, help="Path to raw click TSV")
    run_parser.add_argument(
        "--output-dir", default=".", help="Directory for artifacts and predictions.tsv"
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
        summary = run_pipeline(input_path, Path(args.output_dir))
        print(json.dumps(summary, indent=2))
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

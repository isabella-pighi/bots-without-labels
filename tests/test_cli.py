"""Tests for command-line diagnostics and JSON output."""

import json
from pathlib import Path

from bots_without_labels import cli


def test_doctor_reports_healthy_install(tmp_path: Path) -> None:
    input_path = tmp_path / "clicks.tsv"
    input_path.write_text("", encoding="utf-8")

    exit_code, payload = cli.run_doctor(
        input_path=input_path,
        output_dir=tmp_path,
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert all(check["ok"] for check in payload["checks"])


def test_doctor_reports_missing_input(tmp_path: Path) -> None:
    exit_code, payload = cli.run_doctor(
        input_path=tmp_path / "missing.tsv",
        output_dir=tmp_path,
    )

    assert exit_code == 1
    assert payload["status"] == "failed"
    failed_names = {check["name"] for check in payload["checks"] if not check["ok"]}
    assert failed_names == {"input_file"}


def test_doctor_command_prints_json(capsys, tmp_path: Path) -> None:
    exit_code = cli.main(["doctor", "--output-dir", str(tmp_path)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "ok"


def test_run_command_reports_missing_input_without_traceback(
    capsys, tmp_path: Path
) -> None:
    exit_code = cli.main(
        [
            "run",
            "--input",
            str(tmp_path / "missing.tsv"),
            "--output-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "does not exist" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""

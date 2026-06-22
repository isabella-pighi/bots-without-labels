"""Local HTTP dashboard for viewing and running Bots Without Labels analyses."""

from __future__ import annotations

# pylint: disable=too-many-lines

import argparse
import json
import os
import shlex
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

from .pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_OUTPUT_DIR = "run-output"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PIPELINE_LOCK = Lock()


class Handler(BaseHTTPRequestHandler):
    """Serve dashboard pages, JSON artefacts, uploads, and pipeline runs."""

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        """Route dashboard, feature, and JSON API GET requests."""
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(_dashboard_html())
        elif parsed.path == "/api/summary":
            self._send_json(_read_json(_canonical_artifacts_dir() / "summary.json"))
        elif parsed.path == "/api/anomalies":
            self._send_json(
                _read_json(_canonical_artifacts_dir() / "selected_events.json")
            )
        elif parsed.path == "/api/events":
            self._send_json(
                _read_json(_canonical_artifacts_dir() / "sample_events.json")
            )
        elif parsed.path == "/api/features":
            params = parse_qs(parsed.query)
            offset = _parse_int(params.get("offset", ["0"])[0], default=0)
            limit = min(_parse_int(params.get("limit", ["200"])[0], default=200), 1000)
            self._send_json(
                _read_features(
                    _canonical_artifacts_dir() / "features.tsv",
                    offset=offset,
                    limit=limit,
                )
            )
        elif parsed.path == "/features":
            self._send_html(_features_html())
        elif parsed.path == "/predictions.tsv":
            self._send_download(
                _canonical_output_root() / "predictions.tsv",
                "predictions.tsv",
                "text/tab-separated-values; charset=utf-8",
            )
        elif parsed.path == "/predictions-extended.tsv":
            self._send_download(
                _canonical_output_root() / "predictions-extended.tsv",
                "predictions-extended.tsv",
                "text/tab-separated-values; charset=utf-8",
            )
        elif parsed.path in (
            "/artifacts/risk_score_threshold.png",
            "/artifacts/combined_score_threshold.png",
        ):
            self._send_binary(
                _canonical_artifacts_dir() / "risk_score_threshold.png",
                "image/png",
            )
        elif parsed.path == "/artifacts/ml_score_threshold.png":
            self._send_binary(
                _canonical_artifacts_dir() / "ml_score_threshold.png", "image/png"
            )
        elif parsed.path == "/run":
            self._send_json(
                {
                    "error": (
                        "Use POST /run with JSON input or "
                        "POST /run?input=<path> to start a pipeline run"
                    )
                },
                status=405,
            )
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # pylint: disable=invalid-name
        """Handle pipeline runs from server paths or uploaded TSV files."""
        parsed = urlparse(self.path)
        if parsed.path == "/run":
            self._handle_run_post(parsed.query)
            return

        if parsed.path == "/upload":
            self._handle_upload_post()
            return

        self.send_error(404)

    def _handle_run_post(self, query: str) -> None:
        """Run the pipeline for a server-side input path."""
        input_path = self._run_input_path(query)
        if input_path is None:
            return
        if not input_path:
            self._send_json({"error": "Pass ?input=/path/to/raw.tsv"}, status=400)
            return
        try:
            safe_input_path = _validate_server_input_path(input_path)
            with PIPELINE_LOCK:
                summary = run_pipeline(safe_input_path, _canonical_output_root())
        except (OSError, ValueError) as exc:
            self._send_json({"error": str(exc)}, status=400)
        else:
            self._send_json(summary)

    def _run_input_path(self, query: str) -> str | None:
        """Read the pipeline input path from query parameters or JSON body."""
        params = parse_qs(query)
        input_path = params.get("input", [""])[0]
        if input_path:
            return input_path

        content_length = _parse_int(self.headers.get("Content-Length", "0"), default=0)
        if content_length <= 0:
            return ""
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "POST /run body must be valid JSON"}, status=400)
            return None
        if not isinstance(payload, dict):
            self._send_json(
                {"error": "POST /run body must be a JSON object"}, status=400
            )
            return None
        value = payload.get("input", "")
        return value if isinstance(value, str) else ""

    def _handle_upload_post(self) -> None:
        """Run the pipeline for an uploaded TSV file."""
        upload = self._uploaded_file()
        if upload is None:
            return
        suffix = Path(upload.get("filename") or "upload.tsv").suffix or ".tsv"
        tmp_path: Path | None = None
        status = 200
        try:
            with tempfile.NamedTemporaryFile(
                "wb", suffix=suffix, delete=False
            ) as handle:
                handle.write(upload["content"])
                tmp_path = Path(handle.name)
            with PIPELINE_LOCK:
                payload = run_pipeline(
                    tmp_path,
                    _canonical_output_root(),
                    display_input_path=str(upload["filename"]),
                )
        except (OSError, ValueError) as exc:
            payload = {"error": str(exc)}
            status = 400
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
        self._send_json(payload, status=status)

    def _uploaded_file(self) -> dict[str, object] | None:
        """Parse and validate the uploaded file payload."""
        content_type = self.headers.get("Content-Type", "")
        content_length = _parse_int(self.headers.get("Content-Length", "0"), default=0)
        if content_length <= 0:
            self._send_json(
                {"error": "Upload a TSV file before running the pipeline"}, status=400
            )
            return None
        if content_length > MAX_UPLOAD_BYTES:
            self._send_json(
                {"error": f"Upload exceeds the {MAX_UPLOAD_BYTES} byte limit"},
                status=413,
            )
            return None

        body = self.rfile.read(content_length)
        try:
            _fields, files = _parse_multipart_form(content_type, body)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return None

        upload = files.get("file")
        if not upload or not upload.get("filename"):
            self._send_json(
                {"error": "Upload a TSV file before running the pipeline"}, status=400
            )
            return None
        return upload

    def log_message(self, fmt: str, *args) -> None:  # pylint: disable=arguments-differ
        """Write server log messages to stdout for local CLI use."""
        print(f"{self.address_string()} - {fmt % args}")

    def _send_json(self, payload: object, status: int = 200) -> None:
        """Send a JSON response with a fixed UTF-8 content type."""
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html: str, status: int = 200) -> None:
        """Send a HTML response with a fixed UTF-8 content type."""
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_binary(self, path: Path, content_type: str) -> None:
        """Send a small binary dashboard artefact."""
        if not path.exists():
            self.send_error(404)
            return
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_download(self, path: Path, download_name: str, content_type: str) -> None:
        """Send a canonical run output as a named download."""
        if not path.exists():
            self.send_error(404)
            return
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Disposition", f'attachment; filename="{download_name}"'
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _read_json(path: Path) -> object:
    """Read a dashboard JSON artefact or return a user-facing error payload."""
    if not path.exists():
        return {"error": f"{path.name} not found; run the pipeline first"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": f"{path.name} is malformed; run the pipeline again"}
    except OSError as exc:
        return {"error": f"{path.name} could not be read: {exc}"}


def _canonical_output_root() -> Path:
    """Return the run-specific source-of-truth output directory."""
    return ROOT / CANONICAL_OUTPUT_DIR


def _canonical_artifacts_dir() -> Path:
    """Return the canonical run-specific artefact directory."""
    return _canonical_output_root() / "artifacts"


def _parse_int(value: str, default: int) -> int:
    """Parse a non-negative integer, falling back for malformed values."""
    try:
        return max(0, int(value))
    except ValueError:
        return default


def _validate_server_input_path(input_path: str) -> Path:
    """Normalise and validate a server-side input path.

    Args:
        input_path: Absolute path or path relative to ``ROOT``.

    Returns:
        Resolved path under ``ROOT``.

    Raises:
        ValueError: If the resolved path escapes ``ROOT`` or uses a symlink
            component beneath ``ROOT``.
    """
    root = ROOT.resolve()
    candidate = Path(input_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    normalised_candidate = Path(os.path.normpath(str(candidate)))
    _reject_symlink_components(normalised_candidate, root)
    path = normalised_candidate.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Server-side input path must be under {root}") from exc
    if not path.exists():
        raise ValueError(f"Input TSV '{path}' does not exist.")
    if not path.is_file():
        raise ValueError(f"Input TSV '{path}' is not a file.")
    return path


def _reject_symlink_components(path: Path, root: Path) -> None:
    """Reject symlinks in a normalised path below the dashboard root.

    Args:
        path: Normalised candidate path before symlink resolution.
        root: Resolved repository root.

    Raises:
        ValueError: If any existing component below ``root`` is a symlink.
    """
    try:
        path.relative_to(root)
    except ValueError:
        return
    root_parts = root.parts
    current = Path(root_parts[0])
    for part in path.parts[1:]:
        current /= part
        if current == root:
            continue
        if current.exists() and current.is_symlink():
            raise ValueError("Server-side input path must not use symlinks")


def _parse_multipart_form(
    content_type: str, body: bytes
) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    """Parse the small multipart subset used by dashboard uploads.

    Args:
        content_type: Request ``Content-Type`` header.
        body: Raw request body.

    Returns:
        Tuple of normal fields and file fields. File entries include
        ``filename`` and raw ``content`` bytes.

    Raises:
        ValueError: If the upload is not multipart or lacks a boundary.
    """
    params = _parse_content_type(content_type)
    if params.get("") != "multipart/form-data":
        raise ValueError("Upload request must use multipart/form-data")
    boundary = params.get("boundary", "")
    if not boundary:
        raise ValueError("Upload request is missing a multipart boundary")

    fields: dict[str, str] = {}
    files: dict[str, dict[str, object]] = {}
    boundary_bytes = ("--" + boundary).encode("utf-8")
    for part in body.split(boundary_bytes):
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"--\r\n"):
            part = part[:-4]
        elif part.endswith(b"--"):
            part = part[:-2]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        raw_headers, content = part.split(b"\r\n\r\n", 1)
        headers = raw_headers.decode("utf-8", errors="replace").split("\r\n")
        disposition = next(
            (
                line
                for line in headers
                if line.lower().startswith("content-disposition:")
            ),
            "",
        )
        params = _parse_content_disposition(disposition)
        name = params.get("name")
        if not name:
            continue
        filename = params.get("filename")
        if filename is not None:
            files[name] = {"filename": filename, "content": content}
        else:
            fields[name] = content.decode("utf-8", errors="replace")
    return fields, files


def _parse_content_disposition(header: str) -> dict[str, str]:
    """Parse Content-Disposition parameters from a multipart part header."""
    return _parse_header_parameters(header.removeprefix("Content-Disposition:"))


def _parse_content_type(header: str) -> dict[str, str]:
    """Parse Content-Type parameters while preserving quoted semicolons."""
    return _parse_header_parameters(header)


def _parse_header_parameters(header: str) -> dict[str, str]:
    """Parse semicolon-separated header parameters with shell-style quoting.

    ``shlex`` is used here because multipart filenames and boundaries may be
    quoted and can legally contain semicolons inside the quoted value.

    Args:
        header: Raw header value, optionally including the primary token.

    Returns:
        Mapping of lowercase parameter names to values. The primary token is
        stored under the empty-string key.

    Raises:
        ValueError: If the header contains unmatched quotes.
    """
    params: dict[str, str] = {}
    lexer = shlex.shlex(header, posix=True)
    lexer.whitespace = ";"
    lexer.whitespace_split = True
    lexer.commenters = ""
    for index, item in enumerate(lexer):
        item = item.strip()
        if index == 0 and "=" not in item:
            params[""] = item.lower()
            continue
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        params[key.strip().lower()] = value.strip()
    return params


def _read_features(path: Path, offset: int = 0, limit: int = 200) -> object:
    """Read a page of feature rows for the feature-matrix view."""
    if not path.exists():
        return {"error": f"{path.name} not found; run the pipeline first"}
    try:
        with path.open("r", encoding="utf-8") as handle:
            header = handle.readline().rstrip("\n").split("\t")
            feature_names = header[1:]
            rows = []
            for idx, line in enumerate(handle):
                if idx < offset:
                    continue
                if len(rows) >= limit:
                    break
                parts = line.rstrip("\n").split("\t")
                if len(parts) != len(header):
                    continue
                rows.append(
                    {
                        "event_id": parts[0],
                        "features": [float(value) for value in parts[1:]],
                    }
                )
    except ValueError:
        return {"error": f"{path.name} is malformed; run the pipeline again"}
    except OSError as exc:
        return {"error": f"{path.name} could not be read: {exc}"}
    return {
        "feature_names": feature_names,
        "offset": offset,
        "limit": limit,
        "rows": rows,
        "next_offset": offset + len(rows),
    }


def _dashboard_html() -> str:
    """Return the dashboard application's self-contained HTML document."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bots Without Labels Dashboard</title>
  <style>
    :root {
      color-scheme: light; --ink:#172026; --muted:#52616d; --line:#cfd7df;
      --bg:#f4f7fa; --panel:#ffffff; --accent:#0f6674;
      --accent-weak:#e2f0f2; --amber:#a35b00; --red:#aa4238;
      --green:#2f7d59; --blue:#4361a6; --purple:#7157a8;
    }
    html { scroll-behavior:smooth; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:Arial, Helvetica, sans-serif; color:var(--ink); background:var(--bg); }
    header { position:sticky; top:0; z-index:20; background:#fff; border-bottom:1px solid var(--line); padding:14px 22px; display:grid; gap:12px; }
    h1 { font-size:24px; margin:0; letter-spacing:0; }
    h2 { font-size:18px; margin:0 0 12px; }
    h3 { font-size:15px; margin:0 0 8px; }
    p { margin:0 0 10px; }
    main { margin:0; padding:0; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th, td {
      border-bottom:1px solid var(--line);
      padding:9px 8px;
      text-align:left;
      vertical-align:top;
    }
    th { color:var(--muted); font-weight:600; }
    .topbar { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }
    .brand-block { min-width:220px; }
    .utility-nav, .run-actions { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    .utility-nav { justify-content:flex-end; }
    .run-actions { justify-content:flex-start; }
    a, button, select, input { font:inherit; }
    a, button {
      color:#fff; background:var(--accent); border:0; border-radius:6px;
      padding:9px 12px; text-decoration:none; font-weight:650; cursor:pointer;
    }
    a:focus-visible, button:focus-visible, input:focus-visible,
    select:focus-visible { outline:3px solid #86d4de; outline-offset:2px; }
    button.nav, button.help-link { color:var(--accent); background:var(--accent-weak); }
    button.nav[aria-current="page"] { color:#fff; background:var(--accent); }
    button.help-link { padding:5px 8px; font-size:12px; }
    a.secondary { color:var(--accent); background:var(--accent-weak); }
    button:disabled { opacity:.55; cursor:not-allowed; }
    input, select { min-height:38px; padding:8px 10px; border:1px solid var(--line); border-radius:6px; background:#fff; }
    input { width:min(460px, 100%); }
    .dataset-runner { display:grid; grid-template-columns:minmax(260px, 1fr) minmax(280px,.9fr) auto; gap:10px; align-items:start; padding:10px; border:1px solid var(--line); border-radius:8px; background:#fbfcfd; }
    .dataset-fields { min-width:0; }
    .file-picker { display:flex; align-items:center; gap:10px; min-height:38px; }
    .file-label { display:inline-flex; align-items:center; min-height:38px; padding:8px 12px; border-radius:6px; color:#fff; background:var(--accent); font-weight:650; cursor:pointer; white-space:nowrap; }
    .file-name { min-width:0; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .visually-hidden-input { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
    .visually-hidden-input:focus + .file-label { outline:3px solid var(--accent-weak); outline-offset:2px; }
    .app-shell { display:grid; grid-template-columns:240px minmax(0,1fr); min-height:calc(100vh - 96px); }
    .sidebar { position:sticky; top:0; align-self:start; min-height:calc(100vh - 96px); padding:16px; border-right:1px solid var(--line); background:#fff; }
    .sidebar-title { color:var(--muted); font-size:12px; font-weight:750; letter-spacing:.04em; text-transform:uppercase; margin:0 0 10px; }
    .sidebar-nav { display:grid; gap:6px; }
    .sidebar-nav button.nav { width:100%; text-align:left; }
    .skip-link { position:absolute; left:16px; top:8px; z-index:100; transform:translateY(-140%); background:var(--accent); color:#fff; border-radius:6px; padding:9px 12px; font-weight:700; }
    .skip-link:focus { transform:translateY(0); outline:3px solid var(--accent-weak); outline-offset:2px; }
    .workspace { min-width:0; width:100%; max-width:1780px; padding:18px 22px 28px; overflow:visible; }
    .input-panel { display:block; }
    .input-panel.is-hidden { display:none; }
    .input-help { flex-basis:100%; color:var(--muted); font-size:12px; margin:3px 0 0; }
    .predictions-panel { border:1px solid var(--line); border-radius:6px; padding:10px; background:#fff; min-width:0; }
    .predictions-title { font-size:12px; font-weight:750; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; margin-bottom:6px; }
    .predictions-links { display:flex; flex-wrap:wrap; gap:8px; margin:8px 0; }
    .predictions-links a { padding:7px 9px; font-size:12px; }
    .path-ref { font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:12px; overflow-wrap:anywhere; }
    .topline { color:var(--muted); font-size:13px; margin-top:4px; }
    .page { display:none; }
    .page.active { display:block; }
    .panel, .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
    .panel { margin-bottom:16px; }
    .story, .chart-grid, .split { display:grid; grid-template-columns:1.2fr .8fr; gap:16px; align-items:start; }
    .three { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
    .metric-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
    .metric { border:1px solid var(--line); border-radius:8px; padding:13px; background:#fff; min-height:104px; }
    .metric-value { font-size:28px; font-weight:750; font-variant-numeric:tabular-nums; margin:6px 0; }
    .metric-label, .label { color:var(--muted); font-size:13px; }
    .analysis-brief-panel { width:100%; min-width:0; overflow:visible; }
    .analysis-brief-copy { display:grid; gap:10px; width:100%; max-width:none; min-width:0; }
    .analysis-brief-copy p { margin:0; color:var(--ink); font-size:15px; line-height:1.55; overflow-wrap:anywhere; }
    .chart-grid { grid-template-columns:repeat(3,minmax(0,1fr)); margin-bottom:16px; }
    .decision-flow { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; counter-reset:step; }
    .decision-step { position:relative; border:1px solid var(--line); border-radius:8px; padding:14px; background:#fbfcfd; min-height:138px; }
    .decision-step::before { counter-increment:step; content:counter(step); display:inline-grid; place-items:center; width:28px; height:28px; border-radius:999px; color:#fff; background:var(--accent); font-weight:750; margin-bottom:10px; }
    .decision-step h3 { font-size:14px; margin:0 0 6px; }
    .decision-step p { color:var(--muted); font-size:13px; line-height:1.45; margin:0; }
    .method-card { min-height:180px; }
    .formula-box { border:1px solid var(--line); border-radius:8px; background:#f8fbfc; padding:14px; font-family:Arial, Helvetica, sans-serif; }
    .formula-box code { font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space:normal; overflow-wrap:anywhere; }
    .threshold-plot { width:100%; max-height:420px; object-fit:contain; border:1px solid var(--line); border-radius:8px; background:#fff; }
    .explorer-chart-grid { grid-template-columns:repeat(2,minmax(0,1fr)); grid-template-areas:"methods regions" "families contributions" "domains domains"; }
    .explorer-card-methods { grid-area:methods; }
    .explorer-card-domains { grid-area:domains; }
    .explorer-card-regions { grid-area:regions; }
    .explorer-card-families { grid-area:families; }
    .explorer-card-contributions { grid-area:contributions; }
    .chart-body { display:grid; grid-template-columns:142px minmax(0,1fr); gap:14px; align-items:center; }
    .donut { width:142px; height:142px; }
    .legend { display:grid; gap:7px; }
    .legend-row { display:grid; grid-template-columns:14px minmax(0,1fr) auto; gap:7px; align-items:center; font-size:12px; }
    .swatch { width:12px; height:12px; border-radius:3px; }
    .class-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
    .class-card { display:grid; gap:8px; }
    .class-card.selected { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-weak); }
    .class-meta { display:flex; gap:8px; flex-wrap:wrap; color:var(--muted); font-size:12px; }
    .pill { display:inline-flex; align-items:center; border:1px solid var(--line); border-radius:999px; padding:3px 8px; background:#f9fbfb; white-space:nowrap; }
    .example { border-top:1px solid var(--line); padding-top:8px; color:var(--muted); font-size:13px; }
    .action-grid, .filter-grid, .term-grid, .help-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
    .action-card { min-height:142px; }
    .caveat, .notice { border-left:4px solid var(--amber); background:#fff8ee; padding:12px; margin-top:12px; color:#50320a; }
    .bar { height:22px; background:#e8edf0; border-radius:4px; overflow:hidden; margin:7px 0 12px; }
    .bar > span { display:block; height:100%; background:var(--accent); }
    .evidence-bars { display:grid; gap:9px; }
    .evidence-row { display:grid; gap:5px; width:100%; padding:8px; border:1px solid var(--line); border-radius:6px; background:#fbfcfc; color:var(--ink); text-align:left; font-size:12px; }
    button.evidence-row { cursor:pointer; }
    .evidence-row strong { display:flex; justify-content:space-between; gap:8px; align-items:center; }
    .evidence-track { height:10px; background:#e8edf0; border-radius:999px; overflow:hidden; }
    .evidence-fill { display:block; height:100%; background:var(--accent); min-width:2px; }
    .score-button { border:1px solid var(--line); border-radius:6px; padding:6px 8px; background:#fff; color:var(--ink); text-align:left; font:inherit; line-height:1.45; width:100%; }
    .score-button strong { color:var(--red); }
    .evidence-list { display:grid; gap:10px; margin-top:12px; }
    .evidence-item { border:1px solid var(--line); border-radius:6px; padding:10px; background:#fbfcfc; }
    .evidence-item h3 { margin:0 0 6px; font-size:14px; }
    .evidence-meta { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:6px; }
    .table-wrap { overflow:auto; contain:inline-size; }
    caption { text-align:left; color:var(--muted); font-size:12px; padding:0 0 8px; }
    .wrap { max-width:260px; overflow-wrap:anywhere; }
    .score { font-variant-numeric:tabular-nums; font-weight:650; }
    .bot { color:var(--red); }
    .loading { padding:20px; color:var(--muted); }
    .active-filters { display:flex; gap:8px; flex-wrap:wrap; margin:10px 0; }
    .pagination { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:12px 0; }
    .pagination .label { margin-left:auto; }
    .modal-backdrop { position:fixed; inset:0; background:rgba(20,32,39,.45); display:none; align-items:center; justify-content:center; padding:20px; z-index:30; }
    .modal-backdrop.open { display:flex; }
    .modal { background:#fff; color:var(--ink); max-width:560px; width:min(560px,100%); border-radius:8px; padding:18px; box-shadow:0 18px 60px rgba(0,0,0,.25); }
    .modal-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
    .global-filters { position:relative; z-index:1; padding:12px; }
    .control-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:8px; }
    .control-head h2 { margin:0 0 3px; }
    .filter-actions { display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end; }
    .filter-actions button { padding:7px 9px; font-size:12px; }
    .event-id-filter { display:grid; gap:4px; font-size:12px; font-weight:650; }
    .event-id-filter input { min-height:34px; padding:6px 8px; font-size:12px; min-width:200px; }
    .filter-guidance { color:var(--muted); font-size:12px; margin:0 0 8px; }
    .filter-grid { grid-template-columns:repeat(4,minmax(160px,1fr)); gap:8px; }
    .filter-grid label { display:grid; gap:4px; font-size:12px; font-weight:650; }
    .filter-grid input, .filter-grid select { min-height:34px; padding:6px 8px; font-size:12px; width:100%; }
    .filter-grid select[multiple] { min-height:116px; width:100%; }
    .filter-grid .label { font-size:11px; font-weight:400; }
    .sample-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-top:8px; }
    .sample-grid .metric { min-height:74px; padding:9px; }
    .sample-grid .metric-value { font-size:22px; margin:3px 0; }
    .clickable { cursor:pointer; }
    .clickable:focus { outline:3px solid var(--accent-weak); outline-offset:2px; }
    .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
    @media (max-width: 1000px) {
      .topbar, .app-shell, .story, .chart-grid, .split { grid-template-columns:1fr; }
      .explorer-chart-grid { grid-template-areas:"methods" "regions" "families" "contributions" "domains"; }
      header { align-items:start; }
      .topbar { display:grid; }
      .utility-nav { justify-content:flex-start; }
      .dataset-runner { grid-template-columns:1fr; }
      .run-actions { width:100%; }
      .sidebar { position:relative; min-height:auto; border-right:0; border-bottom:1px solid var(--line); }
      .sidebar-nav { grid-template-columns:repeat(4,minmax(0,1fr)); }
      .workspace { max-width:none; }
      .metric-grid, .three, .action-grid, .filter-grid, .term-grid, .help-grid, .decision-flow { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .sample-grid { grid-template-columns:1fr; }
      .class-grid { grid-template-columns:1fr; }
    }
    @media (max-width: 700px) {
      .workspace { padding:14px; }
      input { width:100%; }
      .utility-nav, .run-actions, .input-panel, .file-picker { width:100%; }
      .run-actions a, .run-actions button, .utility-nav a { flex:1; text-align:center; }
      .file-label { justify-content:center; }
      .sidebar { padding:12px 14px; }
      .sidebar-nav { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .sidebar-nav button.nav { text-align:center; min-width:0; }
      .metric-grid, .three, .action-grid, .filter-grid, .term-grid, .help-grid, .decision-flow { grid-template-columns:1fr; }
      .chart-body { grid-template-columns:1fr; }
      table { table-layout:fixed; font-size:11px; }
      th, td { padding:7px 5px; overflow-wrap:anywhere; }
    }
  </style>
</head>
<body>
  <a href="#dashboardMain" class="skip-link">Skip to dashboard content</a>
  <header>
    <div class="topbar">
      <div class="brand-block">
        <h1>Bots Without Labels Business Dashboard</h1>
        <div class="topline">Operational review view for current bot-click results.</div>
      </div>
      <nav class="utility-nav" aria-label="Dashboard tools">
        <a class="secondary" href="/features">Features</a>
      </nav>
    </div>
    <div class="dataset-runner" aria-label="Dataset source">
      <div class="dataset-fields">
        <div id="uploadInputPanel" class="input-panel">
          <div class="file-picker">
            <input id="inputFile" class="dataset-field visually-hidden-input" type="file" accept=".tsv,text/tab-separated-values,text/plain" aria-label="Upload input TSV" onchange="updateSelectedFile()">
            <label class="file-label" for="inputFile">Choose TSV</label>
            <span class="file-name" id="selectedFileName" aria-live="polite">No file selected</span>
          </div>
          <p class="input-help">Choose a local .tsv file to upload and analyse.</p>
        </div>
      </div>
      <div class="run-actions">
        <button id="runButton" onclick="runPipeline()">Run analysis</button>
        <button type="button" onclick="exportSelection()">Export CSV</button>
      </div>
    </div>
  </header>
  <main class="app-shell" id="dashboardMain" tabindex="-1">
    <div class="sr-only" id="pageStatus" aria-live="polite"></div>
    <aside class="sidebar" aria-label="Dashboard sections">
      <div class="sidebar-title">Sections</div>
      <nav class="sidebar-nav">
        <button type="button" class="nav" data-page="overview" aria-current="page" onclick="showPage('overview')">Overview</button>
        <button type="button" class="nav" data-page="decision" onclick="showPage('decision')">Decision Logic</button>
        <button type="button" class="nav" data-page="explorer" onclick="showPage('explorer')">Traffic Explorer</button>
        <button type="button" class="nav" data-page="patterns" onclick="showPage('patterns')">Patterns</button>
        <button type="button" class="nav" data-page="help" onclick="showPage('help')">Help</button>
      </nav>
    </aside>
    <div class="workspace">
      <section class="panel global-filters" aria-labelledby="filterTitle" hidden>
        <div class="control-head">
          <div>
            <h2 id="filterTitle">Explore detected anomalies</h2>
            <p class="label">Compact row-level controls for the full selected anomaly set. This is not the full all-traffic population.</p>
          </div>
          <div class="filter-actions">
            <label class="event-id-filter">Single event ID
              <input type="text" id="eventIdFilter" placeholder="e.g. evt_004840" autocomplete="off" oninput="applyEventIdFilter(this.value)">
            </label>
            <button type="button" onclick="clearFilters()">Clear filters</button>
          </div>
        </div>
        <p class="filter-guidance">Pick a value from each drop-down menu to narrow the selected anomaly set, or enter a single event ID to single out one anomaly. Chart rows also toggle matching filters.</p>
        <div class="filter-grid" id="filters"></div>
        <div class="active-filters" id="activeFilters"></div>
      </section>
    <section class="page active" id="page-overview">
      <div class="panel analysis-brief-panel">
        <h2>Executive View</h2>
        <div class="analysis-brief-copy">
          <p id="storyLead">Loading current run...</p>
          <p id="confidenceExplainer"></p>
        </div>
      </div>
      <div class="panel">
        <h2>Run Scorecard</h2>
        <div class="metric-grid" id="metrics"></div>
      </div>
      <section class="panel">
        <h2>Recommended actions</h2>
        <div class="action-grid" id="actionGuidance"></div>
      </section>
    </section>
    <section class="page" id="page-decision">
      <section class="panel">
        <h2>How The Classifier Decides</h2>
        <p class="label">The pipeline uses the two classifiers required by the brief: transparent rules for obvious automation and Extended Isolation Forest for subtle multivariate anomalies. Final selection is made directly from those two classifiers.</p>
        <div class="decision-flow" aria-label="Classifier decision journey">
          <article class="decision-step"><h3>Parse traffic</h3><p>Read timestamp, device context, and URL parameters such as clicked domain, query text, country-like context, and time to click.</p></article>
          <article class="decision-step"><h3>Engineer signals</h3><p>Create business-readable signals: repetition, apex-domain concentration, query entropy, mechanical timing, and device clustering.</p></article>
          <article class="decision-step"><h3>Run rules</h3><p>Apply deterministic heuristic rules and keep the rule evidence visible for audit and review.</p></article>
          <article class="decision-step"><h3>Run ML</h3><p>Score every event with Extended Isolation Forest and use the run-specific elbow threshold for the anomaly tail.</p></article>
          <article class="decision-step"><h3>Assign actions</h3><p>Flag events selected by rules, ML, or both, then map them into direct evidence-agreement tiers.</p></article>
        </div>
      </section>
      <section class="panel">
        <h2>Two-Classifier Decision Rule</h2>
        <div class="formula-box">
          <h3>Max Score</h3>
          <p><code>combined_score = max(heuristic_score, ml_score)</code></p>
        </div>
        <div class="formula-box">
          <h3>Decision rule</h3>
          <p><code>is_bot = heuristic_score &gt;= 0.70 OR ml_score &gt; dynamic_ml_threshold</code></p>
        </div>
        <br>
        <p class="label">The <code>0.70</code> threshold is the fixed high-evidence cutoff for the rules-based classifier. <code>dynamic_ml_threshold</code> is calculated from the current run's EIF anomaly scores; the plot below shows the score curve and the detected elbow used as that ML cutoff.</p>
      </section>
      <section class="panel">
        <h2>Dynamic Threshold Visual</h2>
        <p class="label">This plot shows the EIF anomaly-score threshold: events are sorted from most to least anomalous, and the marker is the run-specific elbow used as the ML cutoff. If the plot is unavailable, rerun the analysis to regenerate the artefacts.</p>
        <div>
          <h3>EIF anomaly-score elbow</h3>
          <img class="threshold-plot" src="/artifacts/ml_score_threshold.png" alt="Sorted EIF anomaly scores with Kneedle dynamic threshold line" onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'notice', textContent:'EIF threshold plot not available; run the pipeline to regenerate it.'}))">
        </div>
      </section>
      <section class="panel">
        <h2>Probability Perspective</h2>
        <p class="label">How likely is a flagged event to be a genuine bot? The data is unlabelled, so these are <strong>reasoned operational estimates, not measured probabilities</strong>. They express how much confidence the evidence justifies.</p>
        <div class="table-wrap"><table>
          <caption>Operational likelihood by evidence tier</caption>
          <thead><tr><th>Tier</th><th>Events</th><th>Likelihood (estimate)</th><th>Why</th></tr></thead>
          <tbody id="probabilityTiers"></tbody>
        </table></div>
        <div id="blendedPrecision" class="formula-box"></div>
        <p class="label">Agreement between the two classifiers is treated as corroboration, not an independent second opinion: both read the same engineered features, so their errors are correlated. Tier 1 sits high mainly because those events are mechanically extreme, not because of arithmetic on the two classifiers.</p>
      </section>
    </section>
    <section class="page" id="page-explorer">
      <section class="panel">
      <h2>Traffic Explorer</h2>
      <p class="label">Rows below are the selected candidate-bot events from
      <code>run-output/artifacts/selected_events.json</code>. Use the filters to understand
      why a row was selected and whether the evidence came from rules, the
      EIF anomaly tail, or both classifiers together.</p>
      <div class="chart-grid explorer-chart-grid">
        <div class="card explorer-card-methods"><h3>Method buckets (selected events only)</h3><div class="chart-body" id="sampleMethodChart"></div></div>
        <div class="card explorer-card-regions"><h3>Flagged regions</h3><div class="chart-body" id="regionsChart"></div></div>
        <div class="card explorer-card-families"><h3>Rule families</h3><div class="chart-body" id="familiesChart"></div></div>
        <div class="card explorer-card-contributions"><h3>Rule contributions</h3><div class="chart-body" id="contributionsChart"></div></div>
        <div class="card explorer-card-domains"><h3>Apex domains</h3><div class="evidence-bars" id="sampleDomainChart"></div></div>
      </div>
      <div class="pagination" id="explorerPagination"></div>
      <div class="table-wrap"><table>
        <caption>Selected candidate-bot rows for the current filter selection</caption>
        <thead><tr><th>Event</th><th>Evidence</th><th>Device cluster</th><th>Domain</th><th>Query</th><th>Scores</th><th>Action</th></tr></thead>
        <tbody id="filteredEvents"></tbody>
      </table></div>
      </section>
    </section>
    <section class="page" id="page-patterns">
      <section class="panel">
      <h2>Traffic Patterns</h2>
      <p class="label">These views explain the visible patterns inside the selected candidate-bot traffic: repeated query text, repeated query/domain pairs, apex-domain concentration, and the rule signals that fired most often.</p>
      <div class="split">
        <div class="card"><h3>Top query terms in detected anomalies</h3><div id="sampleQueries"></div></div>
        <div class="card"><h3>Top query/domain combinations</h3><div id="queryDomainPairs"></div></div>
      </div>
      <div class="panel"><h3>Summary top queries</h3><div id="summaryQueries"></div></div>
      </section>
    </section>
    <section class="page" id="page-help">
      <section class="panel">
      <h2>Help</h2>
      <p>Open a term for a short business definition and example.</p>
      <div class="help-grid" id="definitionButtons"></div>
      </section>
    </section>
    </div>
  </main>
  <div class="modal-backdrop" id="helpModal" role="dialog" aria-modal="true" aria-labelledby="modalTitle" aria-describedby="modalBody modalExample" onclick="if(event.target===this)closeDefinition()">
    <div class="modal">
      <div class="modal-head">
        <h2 id="modalTitle">Definition</h2>
        <button type="button" onclick="closeDefinition()">Close</button>
      </div>
      <p id="modalBody"></p>
      <p class="label" id="modalExample"></p>
    </div>
  </div>
  <div class="modal-backdrop" id="evidenceModal" role="dialog" aria-modal="true" aria-labelledby="evidenceTitle" aria-describedby="evidenceSummary" onclick="if(event.target===this)closeEvidence()">
    <div class="modal evidence-modal">
      <div class="modal-head">
        <h2 id="evidenceTitle">Rule evidence</h2>
        <button type="button" onclick="closeEvidence()">Close</button>
      </div>
      <p class="label" id="evidenceSummary"></p>
      <div class="evidence-list" id="evidenceBody"></div>
    </div>
  </div>
  <script>
    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      })[ch]);
    }
    function handlerAttr(code) {
      return escapeHtml(code);
    }
    function jsString(value) {
      return JSON.stringify(String(value ?? ''));
    }
    const colours = ['#b4483d', '#2f7d59', '#b26800', '#4361a6',
      '#7157a8', '#7b6870', '#4f6f7a', '#8a6f3f'];
    let anomalyEvents = [];
    let summaryData = {};
    let activeModalReturnFocus = null;
    let navigationAttached = false;
    let explorerPage = 0;
    const EXPLORER_PAGE_SIZE = 100;
    const filters = { method: [], tier: [], region: [], domain: [], eventId: '' };
    const definitions = {
      'bot / invalid click': ['A click that appears to be generated by automation rather than a person.', 'Example: a single query repeated hundreds of times at near-constant timing.'],
      'unlabelled data': ['The dataset carries no trusted "bot or not" answer, so accuracy can be estimated but not measured.', 'Example: manual review labels would be needed to calculate precision.'],
      'rules-based classifier': ['The deterministic layer that flags transparent, explainable patterns such as repetition, timing reuse, bursts, and concentration.', 'Example: a query/domain pair seen hundreds of times triggers a rule.'],
      'Extended Isolation Forest (EIF)': ['The unsupervised model that scores how easily an event can be isolated from the rest of the batch across many features at once.', 'Example: a rare combination of timing and concentration stands out even when no single rule fires.'],
      'anomaly score': ['A bounded 0-to-1 measure of how unusual an event looks. It is not a probability of fraud.', 'Example: a very rare feature combination scores near 1.'],
      'Kneedle threshold': ['A curve-shape method that finds the "elbow" in the sorted EIF scores, used to set the run-specific anomaly-tail cutoff.', 'Example: the ML cutoff moves with each batch instead of using a fixed percentile.'],
      'threshold': ['The run-specific cutoff used by the ML classifier, plus the fixed high-evidence cutoff used by the rules classifier.', 'Example: the rules path uses a fixed 0.70 cutoff; the ML path uses the run-specific Kneedle elbow.'],
      'evidence tier': ['A review-priority group based on which classifiers fired: 1 = both, 2 = rules only, 3 = ML only, 0 = not selected. It is not a confirmed fraud label.', 'Example: Tier 1 means both rules and ML selected the event; Tier 3 means ML-only.'],
      'confidence proxy': ['Review-priority label derived from the evidence tier: HIGH, MEDIUM, LOW, or NONE. It is not measured precision or recall.', 'Example: HIGH means both classifiers selected the event.'],
      'method bucket': ['Which classifiers selected the event: Heuristic + ML, Heuristic only, ML only, or Neither strong.', 'Example: a "Heuristic + ML" event was selected by both classifiers.'],
      'operational tier': ['The suggested handling action for an event: suppress, quarantine, or monitor.', 'Example: quarantine means review before suppressing traffic.'],
      'suppress': ['A high-confidence candidate for removal from billing or metrics after approval.', 'Example: repeated query/domain traffic with strong rule and ML evidence.'],
      'quarantine': ['Traffic to hold, delay, sample, or manually review before suppression.', 'Example: ML-only events should usually start here.'],
      'monitor': ['Traffic not selected for action, kept for trends and future labels.', 'Example: normal-looking traffic remains useful for drift checks.'],
      'pseudo-session': ['An inferred short activity window used for burst features, since the data has no real session identifier.', 'Example: clicks within a few seconds are grouped to spot bursts.'],
      'operational estimate': ['A reasoned confidence judgement used in place of measured probability while the data is unlabelled.', 'Example: the per-tier likelihood bands are operational estimates, not measured precision.'],
      'event_id': ['The click identifier provided in the input file.', 'Example: evt_004840 identifies one click.'],
      'is_bot': ['The binary prediction: 1 = candidate bot, 0 = not selected.', 'Example: an event marked is_bot = 1 appears in the detected anomaly set.'],
      'heuristic score': ['Bounded rules-based score from deterministic bot indicators.', 'Example: repeated query/domain pairs raise this score.'],
      'ML score': ['Bounded EIF anomaly score.', 'Example: a rare combination of features scores high.'],
      'combined score': ['Display and sorting aid: max(heuristic_score, ml_score). Not a classifier and not a fraud probability.', 'Example: a high combined score helps reviewers open the most suspicious rows first.'],
      'std_dev_ttc': ['Standard deviation of consecutive time-to-click gaps in a repeated group; low values indicate mechanical pacing.', 'Example: near-zero variation suggests automated timing.'],
      'query_entropy': ['Shannon entropy of the query characters; very low or very high values can both indicate scripted text.', 'Example: a random-looking seed string can have unusually high entropy.']
    };
    attachNavigation();
    async function load() {
      const [summary, events] = await Promise.all([fetch('/api/summary').then(r => r.json()), fetch('/api/anomalies').then(r => r.json())]);
      if (summary.error) { document.getElementById('metrics').innerHTML = `<div class="card">${escapeHtml(summary.error)}</div>`; return; }
      summaryData = summary;
      anomalyEvents = Array.isArray(events) ? events : [];
      renderDefinitions();
      renderSummary(summary);
      renderActions(summary);
      renderProbabilitySummary(summary);
      renderFilters(anomalyEvents, summary);
      renderLastAnalysedInput(summary);
      updateFilteredViews();
    }
    function renderProbabilitySummary(s) {
      const counts = (s.evidence_tiers || {}).counts || {};
      const t1 = Number(counts.tier_1_high || 0);
      const t2 = Number(counts.tier_2_medium || 0);
      const t3 = Number(counts.tier_3_low || 0);
      const total = t1 + t2 + t3;
      const weight = total || 1;
      // Per-tier likelihood bands are reasoned operational estimates.
      const tiers = [
        ['Tier 1: both classifiers', t1, '≈ 0.90+', 'Both methods selected it and the patterns are mechanically extreme.'],
        ['Tier 2: rules only', t2, '≈ 0.60-0.85', 'Explainable rule evidence from one method; some campaigns can mimic it.'],
        ['Tier 3: ML only', t3, '≈ 0.30-0.60', 'Statistically unusual but no explicit rule fired; investigate, do not auto-suppress.']
      ];
      document.getElementById('probabilityTiers').innerHTML = tiers.map(([label, n, band, why]) => `
        <tr><td>${escapeHtml(label)}</td><td>${count(n)}</td><td>${escapeHtml(band)}</td><td>${escapeHtml(why)}</td></tr>`).join('');
      const central = (t1 * 0.92 + t2 * 0.725 + t3 * 0.45) / weight;
      const floor = (t1 * 0.90 + t2 * 0.60 + t3 * 0.30) / weight;
      const ceiling = (t1 * 0.95 + t2 * 0.85 + t3 * 0.60) / weight;
      const truePos = Math.round(central * total);
      const falsePos = total - truePos;
      const t2Share = total ? t2 / total : 0;
      const wholePct = value => `${Math.round(value * 100)}%`;
      document.getElementById('blendedPrecision').innerHTML = `
        <h3>Blended estimate</h3>
        <p>Across all ${count(total)} selected events, the blended operational precision is roughly
        <strong>${wholePct(central)}</strong> (range ${wholePct(floor)}-${wholePct(ceiling)}): about ${count(truePos)} genuine bots
        and ${count(falsePos)} false positives among the selections.</p>
        <p class="label">This figure is dominated by Tier 2 (${wholePct(t2Share)} of the selection, rules only),
        which is the single largest source of uncertainty. Labelled validation should start there.</p>`;
    }
    function renderLastAnalysedInput(summary) {
      const inputPath = summary.input_path || '';
      const label = inputPath && !looksLikeTemporaryUploadPath(inputPath)
        ? inputPath
        : 'No file selected';
      document.getElementById('selectedFileName').textContent = label;
    }
    function looksLikeTemporaryUploadPath(value) {
      const path = String(value || '').toLowerCase();
      return path.includes('/var/folders/') || path.includes('/private/var/folders/') ||
        (path.includes('/tmp') && /[/]tmp[^/]*\\.tsv$/.test(path));
    }
    function pct(x) { return (100 * Number(x || 0)).toFixed(2) + '%'; }
    function count(x) { return Number(x || 0).toLocaleString(); }
    function score(x) { return Number(x || 0).toFixed(4); }
    function thresholdMethodLabel(method) {
      const value = String(method || '').toLowerCase();
      if (value === 'max_distance_descending_fallback') return 'max-distance fallback';
      if (value === 'kneedle_descending') return 'Kneedle elbow';
      if (value) return 'recorded run method';
      return 'run-specific method';
    }
    function combinedThresholdLabel(s) {
      return `ML threshold (${thresholdMethodLabel(s.ml_threshold_method)})`;
    }
    function mlThresholdLabel(s) {
      const method = thresholdMethodLabel(s.ml_threshold_method);
      return method === 'Kneedle elbow' ? 'EIF Kneedle threshold' : `EIF threshold (${method})`;
    }
    function combinedThresholdDescription(s) {
      const method = thresholdMethodLabel(s.threshold_method);
      if (method === 'max-distance fallback') {
        return 'The current run uses a max-distance fallback threshold';
      }
      if (method === 'Kneedle elbow') {
        return 'The current run uses a Kneedle elbow threshold';
      }
      return 'The current run uses its recorded ML threshold';
    }
    function renderSummary(s) {
      const total = Number(s.total_events || 0);
      const selected = Number(s.bot_events || 0);
      const threshold = score(s.threshold);
      document.getElementById('storyLead').textContent =
        `Bots Without Labels analysed ${count(total)} click events and selected ` +
        `${count(selected)} (${pct(s.bot_rate)}) as candidate bot traffic. ` +
        `The result is intentionally narrow: it identifies the traffic most ` +
        `consistent with automation while avoiding broad suppression of normal users.`;
      document.getElementById('confidenceExplainer').textContent =
        `The dashboard explains each decision through evidence tiers. HIGH ` +
        `means both classifiers agree, MEDIUM means rules only, and LOW means ` +
        `ML only. ${combinedThresholdDescription(s)} of ${threshold}.`;
      const metrics = [
        ['Events analysed', count(total)],
        ['Candidate bots', count(selected)],
        ['Selected rate', pct(s.bot_rate)],
        [
          'Tier 1 (High Confidence)',
          count(((s.evidence_tiers || {}).counts || {}).tier_1_high)
        ],
        [
          'Tier 2 (Medium Confidence)',
          count(((s.evidence_tiers || {}).counts || {}).tier_2_medium)
        ],
        [
          'Tier 3 (Low Confidence / Quarantine)',
          count(((s.evidence_tiers || {}).counts || {}).tier_3_low)
        ]
      ];
      document.getElementById('metrics').innerHTML = metrics.map(([k, v]) => `
        <div class="metric">
          <div class="metric-label">${escapeHtml(k)}</div>
          <div class="metric-value">${escapeHtml(v)}</div>
        </div>`).join('');
    }
    function renderDefinitions() {
      document.getElementById('definitionButtons').innerHTML = Object.keys(definitions)
        .map(term => `<button type="button" class="help-link" onclick="${handlerAttr(`openDefinition(${jsString(term)})`)}">${escapeHtml(term)}</button>`)
        .join('');
    }
    function renderBars(id, rows) {
      const max = Math.max(...rows.map(r => r[1]), 1);
      document.getElementById(id).innerHTML = rows.map(r => `<div class="label">${escapeHtml(r[0])} (${r[1].toLocaleString()})</div><div class="bar"><span style="width:${100*r[1]/max}%"></span></div>`).join('');
    }
    function renderDonut(id, label, rows, noun, filterName = '', scope = 'current scope') {
      const total = rows.reduce((sum, row) => sum + Number(row[1] || 0), 0);
      const interactive = Boolean(filterName);
      const radius = 46;
      const circumference = 2 * Math.PI * radius;
      let offset = 0;
      const segments = rows.map(([label, raw], index) => {
        const value = Number(raw || 0);
        const length = total ? (value / total) * circumference : 0;
        const gap = total && length > 3 ? 1.2 : 0;
        const dash = `${Math.max(length - gap, 0)} ${circumference}`;
        const click = interactive ? `onclick="${handlerAttr(`toggleFilterValue(${jsString(filterName)}, ${jsString(label)})`)}" class="clickable"` : '';
        const element = `<circle r="${radius}" cx="60" cy="60" ${click}
          fill="transparent" stroke="${colours[index % colours.length]}"
          stroke-width="22" stroke-dasharray="${dash}"
          stroke-dashoffset="${-offset}" transform="rotate(-90 60 60)">
          <title>${escapeHtml(label)}: ${count(value)} ${noun}; ${escapeHtml(scope)}</title></circle>`;
        offset += length;
        return element;
      }).join('');
      const legend = rows.map(([label, raw], index) => {
        const value = Number(raw || 0);
        const share = total ? `${((value / total) * 100).toFixed(1)}%` : '0.0%';
        const click = interactive ? ` onclick="${handlerAttr(`toggleFilterValue(${jsString(filterName)}, ${jsString(label)})`)}"` : '';
        const legendTag = interactive ? 'button' : 'div';
        const legendType = interactive ? ' type="button"' : '';
        const legendClass = interactive ? 'legend-row clickable' : 'legend-row';
        return `<${legendTag}${legendType} class="${legendClass}"${click}>
          <span class="swatch" style="background:${colours[index % colours.length]}"></span>
          <span>${escapeHtml(label)}</span>
          <strong>${count(value)} (${share})</strong>
        </${legendTag}>`;
      }).join('');
      document.getElementById(id).innerHTML = `
        <svg class="donut" viewBox="0 0 120 120" role="img"
          aria-label="${escapeHtml(label)} donut chart">
          <circle r="${radius}" cx="60" cy="60" fill="transparent"
            stroke="#e8edf0" stroke-width="22"></circle>
          ${segments}
          <text x="60" y="56" text-anchor="middle" font-size="15"
            font-weight="700">${count(total)}</text>
          <text x="60" y="73" text-anchor="middle" font-size="10"
            fill="#5c6870">${escapeHtml(noun)}</text>
        </svg>
        ${interactive ? '<p class="sr-only">Use the legend buttons below to apply filters with a keyboard.</p>' : ''}
        <div class="legend">${legend}</div>`;
    }
    function renderActions(s) {
      const tiers = s.operational_tiers || {};
      const actions = [
        ['Tier 1: approve suppression policy', tiers.suppress || definitions.suppress],
        ['Tier 2: quarantine and sample', tiers.quarantine || definitions.quarantine],
        ['Tier 3: investigate, do not auto-block', 'Use ML-only rows to find new bot patterns and build future labels.']
      ];
      document.getElementById('actionGuidance').innerHTML = actions.map(([tier, text]) => `
        <div class="card action-card">
          <h3>${escapeHtml(tier)}</h3>
          <p>${escapeHtml(text)}</p>
        </div>`).join('');
    }
    function attachNavigation() {
      if (navigationAttached) return;
      navigationAttached = true;
      document.querySelectorAll('button.nav').forEach(button => {
        button.onclick = () => showPage(button.dataset.page);
      });
      document.addEventListener('keydown', event => {
        const modal = document.querySelector('.modal-backdrop.open');
        if (!modal) return;
        if (event.key === 'Escape') {
          modal.id === 'evidenceModal' ? closeEvidence() : closeDefinition();
        } else if (event.key === 'Tab') {
          trapModalFocus(event, modal);
        }
      });
    }
    function setBackgroundModalState(open) {
      ['header', 'main'].forEach(selector => {
        const element = document.querySelector(selector);
        if (!element) return;
        element.inert = open;
        if (open) {
          element.setAttribute('aria-hidden', 'true');
        } else {
          element.removeAttribute('aria-hidden');
        }
      });
    }
    function modalFocusableElements(modal) {
      return [...modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
        .filter(item => !item.disabled && item.offsetParent !== null);
    }
    function trapModalFocus(event, modal) {
      const focusable = modalFocusableElements(modal);
      if (!focusable.length) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    function showPage(page, moveFocus = true) {
      document.querySelectorAll('.page').forEach(item => item.classList.remove('active'));
      const activePage = document.getElementById(`page-${page}`);
      activePage.classList.add('active');
      const globalFilters = document.querySelector('.global-filters');
      if (globalFilters) globalFilters.hidden = !['explorer', 'patterns'].includes(page);
      document.querySelectorAll('button.nav').forEach(button => {
        button.setAttribute('aria-current', button.dataset.page === page ? 'page' : 'false');
      });
      const heading = activePage.querySelector('h2');
      if (heading) {
        document.getElementById('pageStatus').textContent = `${heading.textContent} section selected`;
        if (moveFocus) {
          heading.setAttribute('tabindex', '-1');
          heading.focus({preventScroll:true});
        }
      }
    }
    function openDefinition(term) {
      const entry = definitions[term];
      if (!entry) return;
      activeModalReturnFocus = document.activeElement;
      document.getElementById('modalTitle').textContent = term;
      document.getElementById('modalBody').textContent = entry[0];
      document.getElementById('modalExample').textContent = entry[1];
      document.getElementById('helpModal').classList.add('open');
      setBackgroundModalState(true);
      document.querySelector('#helpModal button').focus();
    }
    function closeDefinition() {
      document.getElementById('helpModal').classList.remove('open');
      setBackgroundModalState(false);
      const returnTarget = activeModalReturnFocus;
      activeModalReturnFocus = null;
      if (returnTarget) returnTarget.focus();
    }
    function openEvidence(eventId) {
      const event = anomalyEvents.find(item => item.event_id === eventId);
      if (!event) return;
      activeModalReturnFocus = document.activeElement;
      document.getElementById('evidenceTitle').textContent =
        `Rule evidence for ${event.event_id}`;
      document.getElementById('evidenceSummary').textContent =
        `${tierLabel(event)}; ${methodBucket(event)}; action ${event.operational_tier}; combined ${score(event.combined_score)}, rules ${score(event.heuristic_score)}, ML ${score(event.ml_score)}.`;
      document.getElementById('evidenceBody').innerHTML = renderRuleEvidenceCards(event);
      document.getElementById('evidenceModal').classList.add('open');
      setBackgroundModalState(true);
      document.querySelector('#evidenceModal button').focus();
    }
    function closeEvidence() {
      document.getElementById('evidenceModal').classList.remove('open');
      setBackgroundModalState(false);
      const returnTarget = activeModalReturnFocus;
      activeModalReturnFocus = null;
      if (returnTarget) returnTarget.focus();
    }
    function methodBucket(event) {
      if (event.method_bucket) return event.method_bucket;
      const h = Number(event.heuristic_score || 0);
      const ml = Number(event.ml_score || 0);
      const thresholds = summaryData.tier_thresholds || {};
      const hCut = Number(thresholds.suppress_agreement_heuristic_score ?? 0.70);
      const mlCut = Number(thresholds.ml_agreement_score ?? 0.975);
      if (h >= hCut && ml > mlCut) return 'Heuristic + ML';
      if (h >= hCut) return 'Heuristic only';
      if (ml > mlCut) return 'ML only';
      return 'Neither strong';
    }
    function deviceLabel(event) {
      return `${event.region || 'unknown'} / ${event.browser || 'unknown'} / ${event.os || 'unknown'}`;
    }
    function uniqueRows(rows, getter) {
      return [...new Set(rows.map(getter).filter(Boolean))].sort();
    }
    function renderFilters(events) {
      const methods = uniqueRows(events, methodBucket);
      const tiers = uniqueRows(events, e => e.operational_tier);
      const regions = uniqueRows(events, e => e.region);
      const domains = uniqueRows(events, e => e.domain);
      document.getElementById('filters').innerHTML = `
        ${selectHtml('method', 'Method bucket (selected events only)', methods)}
        ${selectHtml('tier', 'Operational tier', tiers)}
        ${selectHtml('region', 'Region', regions)}
        ${selectHtml('domain', 'Domain', domains)}`;
      ['method', 'tier', 'region', 'domain'].forEach(name => {
        const select = document.getElementById(`filter-${name}`);
        select.value = filters[name].length ? filters[name][0] : '';
        select.onchange = event => {
          filters[name] = event.target.value ? [event.target.value] : [];
          updateFilteredViews(true);
        };
      });
    }
    function selectHtml(name, label, options) {
      return `<label>${escapeHtml(label)}<span class="label">Choose a value, or “All”.</span><select id="filter-${name}">
        <option value="">All</option>
        ${options.map(item => `<option>${escapeHtml(item)}</option>`).join('')}
      </select></label>`;
    }
    function applyEventIdFilter(value) {
      filters.eventId = String(value || '').trim();
      updateFilteredViews(true);
    }
    function filteredEvents() {
      const eventId = (filters.eventId || '').toLowerCase();
      return anomalyEvents.filter(event => {
        if (eventId && String(event.event_id || '').toLowerCase() !== eventId) return false;
        if (filters.method.length && !filters.method.includes(methodBucket(event))) return false;
        if (filters.tier.length && !filters.tier.includes(event.operational_tier)) return false;
        if (filters.region.length && !filters.region.includes(event.region)) return false;
        if (filters.domain.length && !filters.domain.includes(event.domain)) return false;
        return true;
      });
    }
    function updateFilteredViews(resetExplorerPage = false) {
      if (resetExplorerPage) explorerPage = 0;
      const rows = filteredEvents();
      renderExplorer(rows);
      renderQueries(rows, summaryData);
      renderSampleCharts(rows);
    }
    function renderSampleCharts(rows) {
      renderDonut('sampleMethodChart', 'Method buckets (selected events only)', countBy(rows, methodBucket), 'events', '', 'filtered selected-event set');
      renderDonut('regionsChart', 'Flagged regions', countBy(rows, e => e.region), 'events', '', 'filtered detected anomaly set');
      renderDonut('familiesChart', 'Rule families', countFamilies(rows), 'tags', '', 'filtered selected-event set');
      renderDonut('contributionsChart', 'Rule contributions', countContributions(rows), 'tags', '', 'filtered selected-event set');
      renderEvidenceBars('sampleDomainChart', countBy(rows, e => e.apex_domain || e.domain), rows.length, 'domain');
    }
    function tierLabel(event) {
      const tier = Number(event.evidence_tier || 0);
      if (tier === 1) return 'Tier 1: HIGH';
      if (tier === 2) return 'Tier 2: MEDIUM';
      if (tier === 3) return 'Tier 3: LOW';
      return 'Not flagged';
    }
    function renderExplorer(rows) {
      const chips = [
        'Focus: detected anomalies',
        filters.eventId && `Event ID: ${filters.eventId}`,
        filters.method.length && `Method: ${filters.method.join(', ')}`,
        filters.tier.length && `Tier: ${filters.tier.join(', ')}`,
        filters.region.length && `Region: ${filters.region.join(', ')}`,
        filters.domain.length && `Domain: ${filters.domain.join(', ')}`
      ].filter(Boolean);
      document.getElementById('activeFilters').innerHTML = chips.map(item => `<span class="pill">${escapeHtml(item)}</span>`).join('');
      const pageCount = Math.max(Math.ceil(rows.length / EXPLORER_PAGE_SIZE), 1);
      explorerPage = Math.min(explorerPage, pageCount - 1);
      const start = explorerPage * EXPLORER_PAGE_SIZE;
      const pageRows = rows.slice(start, start + EXPLORER_PAGE_SIZE);
      document.getElementById('explorerPagination').innerHTML = `
        <button type="button" ${explorerPage === 0 ? 'disabled' : ''} onclick="changeExplorerPage(-1)">Previous rows</button>
        <button type="button" ${explorerPage >= pageCount - 1 ? 'disabled' : ''} onclick="changeExplorerPage(1)">Next rows</button>
        <span class="label">Showing ${count(rows.length ? start + 1 : 0)}-${count(Math.min(start + EXPLORER_PAGE_SIZE, rows.length))} of ${count(rows.length)} detected anomalies</span>`;
      document.getElementById('filteredEvents').innerHTML = pageRows.map(e => `<tr>
        <td>${escapeHtml(e.event_id)}</td>
        <td><strong>${escapeHtml(tierLabel(e))}</strong><br><span class="label">${escapeHtml(methodBucket(e))}</span></td>
        <td>${escapeHtml(deviceLabel(e))}</td><td class="wrap">${escapeHtml(e.domain)}</td>
        <td class="wrap">${escapeHtml(e.query)}</td>
        <td><button type="button" class="score-button" onclick="${handlerAttr(`openEvidence(${jsString(e.event_id)})`)}"><strong>combined ${score(e.combined_score)}</strong><br>rules ${score(e.heuristic_score)}<br>ML ${score(e.ml_score)}<br>threshold ${score(summaryData.threshold)}</button></td>
        <td>${escapeHtml(e.operational_tier)}</td>
      </tr>`).join('');
    }
    function changeExplorerPage(direction) {
      explorerPage += direction;
      renderExplorer(filteredEvents());
    }
    function renderQueries(events, summary) {
      renderBars('sampleQueries', countBy(events, e => e.query));
      renderBars('queryDomainPairs', countBy(events, e => `${e.query} / ${e.domain}`));
      renderBars('summaryQueries', summary.top_queries || []);
    }
    function countBy(rows, getter) {
      const counts = new Map();
      rows.forEach(row => {
        const key = getter(row) || 'unknown';
        counts.set(key, (counts.get(key) || 0) + 1);
      });
      return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
    }
    function countFamilies(rows) {
      const counts = new Map();
      rows.forEach(row => {
        const families = new Set(
          (row.rule_contributions || []).map(item => item.family || 'unspecified')
        );
        families.forEach(family => {
          counts.set(family, (counts.get(family) || 0) + 1);
        });
      });
      return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
    }
    function countContributions(rows) {
      const counts = new Map();
      rows.forEach(row => {
        const labels = new Set(
          (row.rule_contributions || []).map(item => item.label || item.rule_id).filter(Boolean)
        );
        labels.forEach(label => {
          counts.set(label, (counts.get(label) || 0) + 1);
        });
      });
      return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
    }
    function renderEvidenceBars(id, rows, total = null, filterName = '') {
      const max = Math.max(...rows.map(row => row[1]), 1);
      document.getElementById(id).innerHTML = rows.map(([label, value]) => {
        const share = total ? `${((100 * value) / total).toFixed(1)}%` : '';
        const tag = filterName ? 'button' : 'div';
        const type = filterName ? ' type="button"' : '';
        const click = filterName ? ` onclick="${handlerAttr(`applyBarFilter(${jsString(filterName)}, ${jsString(label)})`)}"` : '';
        const suffix = share ? `${count(value)} (${share})` : count(value);
        return `<${tag}${type} class="evidence-row${filterName ? ' clickable' : ''}"${click}>
          <strong><span>${escapeHtml(label)}</span><span>${suffix}</span></strong>
          <span class="evidence-track" aria-hidden="true"><span class="evidence-fill" style="width:${(100 * value) / max}%"></span></span>
        </${tag}>`;
      }).join('');
    }
    function applyBarFilter(filterName, label) {
      toggleFilterValue(filterName, label);
    }
    function toggleFilterValue(name, value) {
      if (!Array.isArray(filters[name])) return;
      const isActive = filters[name].includes(value);
      filters[name] = isActive ? [] : [value];
      const select = document.getElementById(`filter-${name}`);
      if (select) select.value = isActive ? '' : value;
      updateFilteredViews(true);
      showPage('explorer');
    }
    function clearFilters() {
      Object.assign(filters, { method: [], tier: [], region: [], domain: [], eventId: '' });
      ['method', 'tier', 'region', 'domain'].forEach(name => {
        const select = document.getElementById(`filter-${name}`);
        if (select) select.value = '';
      });
      const eventIdInput = document.getElementById('eventIdFilter');
      if (eventIdInput) eventIdInput.value = '';
      updateFilteredViews(true);
    }
    function exportSelection() {
      const rows = filteredEvents();
      const header = ['export_scope','event_id','method_bucket','operational_tier','region','browser','os','domain','query','combined_score','heuristic_score','ml_score'];
      const exportScope = 'Filtered selected-event diagnostic export';
      const csv = [header.join(',')].concat(rows.map(row => header.map(key => {
        const value = key === 'export_scope' ? exportScope : (key === 'method_bucket' ? methodBucket(row) : row[key]);
        return `"${String(value ?? '').replace(/"/g, '""')}"`;
      }).join(','))).join('\\n');
      const blob = new Blob([csv], {type: 'text/csv'});
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'bots-without-labels-filtered-anomalies.csv';
      link.click();
      URL.revokeObjectURL(url);
    }
    function evidenceValue(value) {
      return escapeHtml(value === undefined || value === null ? 'not reported' : value);
    }
    function renderRuleEvidenceCards(event) {
      const contributions = event.rule_contributions || [];
      if (!contributions.length) {
        const reasons = event.reasons || [];
        if (!reasons.length) return '<p>No rule evidence was supplied for this row.</p>';
        return reasons.map(reason => `<article class="evidence-item"><h3>${escapeHtml(reason)}</h3></article>`).join('');
      }
      return contributions.map(item => {
        const strength = item.strength || 'supporting';
        const family = item.family || item.rule_family || 'general';
        const raw = item.weight === undefined ? '' : Number(item.weight).toFixed(3);
        const applied = item.applied_weight === undefined
          ? (item.uncapped_weight === undefined ? raw : Number(item.weight).toFixed(3))
          : Number(item.applied_weight).toFixed(3);
        const scoreText = raw && applied && raw !== applied
          ? `+${applied} applied of +${raw} raw`
          : (applied ? `+${applied} applied` : 'no score contribution reported');
        return `<article class="evidence-item">
          <h3>${escapeHtml(item.label || item.rule_id || 'Rule evidence')}</h3>
          <div class="evidence-meta">
            <span class="pill">${escapeHtml(strength)}</span>
            <span class="pill">${escapeHtml(family)}</span>
            <span class="pill">${escapeHtml(scoreText)}</span>
          </div>
          <p><strong>Observed:</strong> ${evidenceValue(item.observed)}</p>
          <p><strong>Threshold:</strong> ${evidenceValue(item.threshold)}</p>
          <p><strong>Why it fired:</strong> ${evidenceValue(item.reason || item.condition)}</p>
        </article>`;
      }).join('');
    }
    function updateSelectedFile() {
      const file = document.getElementById('inputFile').files[0];
      document.getElementById('selectedFileName').textContent = file ? file.name : 'No file selected';
    }
    async function runPipeline() {
      const file = document.getElementById('inputFile').files[0];
      if (!file) {
        document.getElementById('metrics').innerHTML = '<div class="card">Choose a TSV file before running the pipeline.</div>';
        return;
      }
      document.getElementById('runButton').disabled = true;
      document.getElementById('metrics').innerHTML = '<div class="card">Running pipeline...</div>';
      try {
        const response = await uploadAndRun(file);
        if (!response.ok) {
          const payload = await response.json();
          document.getElementById('metrics').innerHTML = `<div class="card">${escapeHtml(payload.error || 'Pipeline run failed')}</div>`;
          return;
        }
        await load();
      } finally {
        document.getElementById('runButton').disabled = false;
      }
    }
    function uploadAndRun(file) {
      const data = new FormData();
      data.append('file', file);
      return fetch('/upload', { method: 'POST', body: data });
    }
    load();
  </script>
</body>
</html>"""


def _features_html() -> str:
    """Return the feature-matrix viewer's self-contained HTML document."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bots Without Labels Features</title>
  <style>
    :root { color-scheme: light; --ink:#172026; --muted:#52616d; --line:#cfd7df; --bg:#f4f7fa; --panel:#ffffff; --accent:#0f6674; --accent-weak:#e2f0f2; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:Arial, Helvetica, sans-serif; color:var(--ink); background:var(--bg); }
    header { background:#ffffff; border-bottom:1px solid var(--line); padding:22px 28px; display:flex; align-items:center; justify-content:space-between; gap:16px; }
    h1 { font-size:24px; margin:0; letter-spacing:0; }
    main { max-width:1760px; margin:0 auto; padding:26px; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
    .actions { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    a, button { color:#ffffff; background:var(--accent); border:0; border-radius:6px; padding:9px 12px; text-decoration:none; font-weight:650; cursor:pointer; }
    a.secondary { color:var(--accent); background:var(--accent-weak); }
    .label { color:var(--muted); font-size:13px; }
    .table-wrap { overflow:auto; max-height:72vh; border:1px solid var(--line); border-radius:6px; margin-top:12px; }
    caption { text-align:left; color:var(--muted); font-size:12px; padding:0 0 8px; }
    table { width:100%; border-collapse:collapse; font-size:12px; white-space:nowrap; }
    th, td { border-bottom:1px solid var(--line); padding:8px; text-align:right; font-variant-numeric:tabular-nums; }
    th:first-child, td:first-child { text-align:left; position:sticky; left:0; background:#ffffff; }
    th { color:var(--muted); font-weight:600; background:#ffffff; position:sticky; top:0; }
  </style>
</head>
<body>
  <header>
    <h1>Bots Without Labels Features</h1>
    <div class="actions">
      <a class="secondary" href="/">Dashboard</a>
    </div>
  </header>
  <main>
    <section class="panel">
      <div class="actions">
        <button onclick="loadFeatures(0)">First Page</button>
        <button id="nextButton" onclick="loadFeatures(nextOffset)">Next Page</button>
        <span class="label" id="status"></span>
      </div>
      <div class="table-wrap">
        <table>
          <caption>Engineered feature values for pipeline audit</caption>
          <thead id="featureHead"></thead>
          <tbody id="featureRows"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    let nextOffset = 0;
    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      })[ch]);
    }
    async function loadFeatures(offset) {
      document.getElementById('status').textContent = 'Loading...';
      const payload = await fetch('/api/features?offset=' + encodeURIComponent(offset) + '&limit=200').then(r => r.json());
      if (payload.error) {
        document.getElementById('status').textContent = payload.error;
        return;
      }
      const columns = ['event_id', ...(payload.feature_names || [])];
      document.getElementById('featureHead').innerHTML = `<tr>${columns.map(name => `<th>${escapeHtml(name)}</th>`).join('')}</tr>`;
      document.getElementById('featureRows').innerHTML = (payload.rows || []).map(row => `<tr>
        <td>${escapeHtml(row.event_id)}</td>${(row.features || []).map(value => `<td>${escapeHtml(Number(value).toFixed(6))}</td>`).join('')}
      </tr>`).join('');
      nextOffset = payload.next_offset || 0;
      const rowsShown = (payload.rows || []).length;
      document.getElementById('nextButton').disabled = rowsShown < payload.limit;
      document.getElementById('status').textContent = rowsShown
        ? `Showing rows ${payload.offset} through ${payload.next_offset - 1}`
        : `No rows found at offset ${payload.offset}`;
    }
    loadFeatures(0);
  </script>
</body>
</html>"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse webserver command-line arguments.

    Args:
        argv: Optional argument list. Uses ``sys.argv`` when omitted.

    Returns:
        Parsed command-line namespace.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Start the local Bots Without Labels dashboard server.

    Args:
        argv: Optional argument list. Uses ``sys.argv`` when omitted.
    """
    args = parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving Bots Without Labels at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

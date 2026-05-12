#!/usr/bin/env python3
"""Small local server: browse runs/* transcripts + result.json (no file upload)."""

from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs, urlparse

VIEWER_ROOT: Final = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT: Final = VIEWER_ROOT.parent


class TranscriptViewerRequestHandler(BaseHTTPRequestHandler):
    """GET / serves the UI; /api/index lists runs; /api/run loads transcript + result."""

    protocol_version = "HTTP/1.1"
    viewer_root: Path = VIEWER_ROOT
    repo_root: Path = DEFAULT_REPO_ROOT
    runs_root: Path = DEFAULT_REPO_ROOT / "runs"

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, indent=None, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_bytes(
        self,
        data: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _under_runs(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.runs_root.resolve())
        except ValueError:
            return False
        return True

    def _safe_run_path(self, bundle: str, run: str) -> Path:
        if not _is_safe_path_segment(bundle) or not _is_safe_path_segment(run):
            raise ValueError("invalid bundle or run name")
        candidate = (self.runs_root / bundle / run).resolve()
        if not self._under_runs(candidate):
            raise ValueError("path outside runs directory")
        if not candidate.is_dir():
            raise FileNotFoundError("run directory not found")
        return candidate

    def _read_transcript_lines(self, run_dir: Path) -> list[dict[str, object]]:
        tpath = run_dir / "transcript.jsonl"
        if not tpath.is_file():
            raise FileNotFoundError("transcript.jsonl not found")
        lines = tpath.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, object]] = []
        for i, line in enumerate(lines, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"transcript.jsonl: invalid JSON on line {i}") from e
            if not isinstance(obj, dict):
                raise ValueError(f"transcript.jsonl: line {i} is not a JSON object")
            out.append(obj)
        return out

    def _read_result(self, run_dir: Path) -> dict[str, object] | None:
        rpath = run_dir / "result.json"
        if not rpath.is_file():
            return None
        try:
            data = json.loads(rpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError("result.json: invalid JSON") from e
        if not isinstance(data, dict):
            raise ValueError("result.json: root must be an object")
        return data

    def _build_index(self) -> dict[str, list[str]]:
        bundles: dict[str, list[str]] = {}
        root = self.runs_root
        if not root.is_dir():
            return bundles
        for bundle_dir in sorted(root.iterdir(), key=lambda p: p.name):
            if not bundle_dir.is_dir():
                continue
            run_names: list[str] = []
            for run_dir in sorted(bundle_dir.iterdir(), key=lambda p: p.name):
                if run_dir.is_dir() and (run_dir / "transcript.jsonl").is_file():
                    run_names.append(run_dir.name)
            if run_names:
                bundles[bundle_dir.name] = run_names
        return bundles

    def _relative_repo(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.repo_root.resolve()))
        except ValueError:
            return str(path)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            index_path = self.viewer_root / "index.html"
            if not index_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND.value, "index.html missing")
                return
            self.send_bytes(index_path.read_bytes(), "text/html; charset=utf-8")
            return

        if path == "/api/index":
            try:
                self.send_json({"bundles": self._build_index()})
            except OSError as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/run":
            params = parse_qs(parsed.query)
            bundle_vals = params.get("bundle", [])
            run_vals = params.get("run", [])
            if len(bundle_vals) != 1 or len(run_vals) != 1:
                self.send_json(
                    {"error": "exactly one bundle= and run= query parameter required"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            bundle_q, run_q = bundle_vals[0], run_vals[0]
            try:
                run_dir = self._safe_run_path(bundle_q, run_q)
                transcript = self._read_transcript_lines(run_dir)
                result_obj = self._read_result(run_dir)
                transcript_path = self._relative_repo(run_dir / "transcript.jsonl")
                result_path = (
                    self._relative_repo(run_dir / "result.json")
                    if (run_dir / "result.json").is_file()
                    else None
                )
                self.send_json(
                    {
                        "bundle": bundle_q,
                        "run": run_q,
                        "transcript": transcript,
                        "result": result_obj,
                        "transcript_path": transcript_path,
                        "result_path": result_path,
                    }
                )
            except FileNotFoundError as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.NOT_FOUND)
            except ValueError as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
            return

        self.send_error(HTTPStatus.NOT_FOUND.value, "Not found")


def _is_safe_path_segment(name: str) -> bool:
    if not name or len(name) > 512:
        return False
    if name in (".", ".."):
        return False
    for bad in ("/", "\\", "\x00"):
        if bad in name:
            return False
    return True


def _make_handler_class(
    viewer_root: Path,
    repo_root: Path,
    runs_root: Path,
) -> type[TranscriptViewerRequestHandler]:
    vr = viewer_root.resolve()
    rr = repo_root.resolve()
    sr = runs_root.resolve()

    class Bound(TranscriptViewerRequestHandler):
        viewer_root = vr
        repo_root = rr
        runs_root = sr

    return Bound


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="port (default: 8765)")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help=f"repository root (default: {DEFAULT_REPO_ROOT})",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=None,
        help="override runs directory (default: <repo-root>/runs)",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    runs_root = (args.runs_dir or (repo_root / "runs")).resolve()
    viewer_root = VIEWER_ROOT.resolve()

    handler = _make_handler_class(viewer_root, repo_root, runs_root)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Cyber-Bench transcript viewer — open {url}")
    print(f"Runs root: {runs_root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()

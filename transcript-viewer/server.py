#!/usr/bin/env python3
"""Small local server: browse Harbor jobs/* and legacy runs/* transcripts."""

from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs, urlparse

from harbor_transcript import (
    enrich_harbor_result,
    load_harbor_benchmark_context,
    load_trajectory_transcript,
    trial_has_agent_trace,
)

VIEWER_ROOT: Final = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT: Final = VIEWER_ROOT.parent
BENCHMARK_STATIC_JSON: Final = "benchmark_static.json"
SOURCE_RUNS: Final = "runs"
SOURCE_JOBS: Final = "jobs"


def _read_jsonl_dict_lines(
    path: Path,
    *,
    source_label: str,
    line_meta_key: str | None,
) -> tuple[list[dict[str, object]], list[str]]:
    """Parse JSONL; skip lines that are not JSON objects. Each warning names source_label and line no."""
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, object]] = []
    warnings: list[str] = []
    for i, line in enumerate(lines, start=1):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            warnings.append(f"{source_label}: skipped line {i} (invalid JSON)")
            continue
        if not isinstance(obj, dict):
            warnings.append(f"{source_label}: skipped line {i} (not a JSON object)")
            continue
        if line_meta_key is not None:
            obj[line_meta_key] = i
        out.append(obj)
    return out, warnings


class TranscriptViewerRequestHandler(BaseHTTPRequestHandler):
    """GET / serves the UI; /api/index lists runs; /api/run loads transcript + result."""

    protocol_version = "HTTP/1.1"
    viewer_root: Path = VIEWER_ROOT
    repo_root: Path = DEFAULT_REPO_ROOT
    runs_root: Path = DEFAULT_REPO_ROOT / "runs"
    jobs_root: Path = DEFAULT_REPO_ROOT / "jobs"

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

    def _under_jobs(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.jobs_root.resolve())
        except ValueError:
            return False
        return True

    def _safe_trial_path(self, job: str, trial: str) -> Path:
        if not _is_safe_path_segment(job) or not _is_safe_path_segment(trial):
            raise ValueError("invalid job or trial name")
        candidate = (self.jobs_root / job / trial).resolve()
        if not self._under_jobs(candidate):
            raise ValueError("path outside jobs directory")
        if not candidate.is_dir():
            raise FileNotFoundError("trial directory not found")
        return candidate

    def _safe_run_path(self, bundle: str, run: str) -> Path:
        if not _is_safe_path_segment(bundle) or not _is_safe_path_segment(run):
            raise ValueError("invalid bundle or run name")
        candidate = (self.runs_root / bundle / run).resolve()
        if not self._under_runs(candidate):
            raise ValueError("path outside runs directory")
        if not candidate.is_dir():
            raise FileNotFoundError("run directory not found")
        return candidate

    def _read_transcript_lines(self, run_dir: Path) -> tuple[list[dict[str, object]], list[str]]:
        tpath = run_dir / "transcript.jsonl"
        if not tpath.is_file():
            raise FileNotFoundError("transcript.jsonl not found")
        out, warnings = _read_jsonl_dict_lines(
            tpath,
            source_label="transcript.jsonl",
            line_meta_key=None,
        )
        if not out:
            raise ValueError("transcript.jsonl: no valid JSON objects")
        return out, warnings

    def _read_opencode_lines(self, run_dir: Path) -> tuple[list[dict[str, object]], list[str]]:
        opath = run_dir / "opencode.stdout.jsonl"
        if not opath.is_file():
            return [], []
        return _read_jsonl_dict_lines(
            opath,
            source_label="opencode.stdout.jsonl",
            line_meta_key="_opencode_line",
        )

    def _read_opencode_session_lines(self, run_dir: Path) -> tuple[list[dict[str, object]], list[str]]:
        opath = run_dir / "opencode.session.jsonl"
        if not opath.is_file():
            return [], []
        return _read_jsonl_dict_lines(
            opath,
            source_label="opencode.session.jsonl",
            line_meta_key="_opencode_session_line",
        )

    def _merge_opencode_transcript(
        self,
        transcript: list[dict[str, object]],
        opencode: list[dict[str, object]],
        opencode_session: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        if not opencode and not opencode_session:
            return transcript
        normalized = _normalize_opencode_session_events(opencode_session)
        normalized.extend(_normalize_opencode_events(opencode))
        prefix: list[dict[str, object]] = []
        suffix: list[dict[str, object]] = []
        for event in transcript:
            if event.get("event") in {"opencode_finish", "finish"}:
                suffix.append(event)
            else:
                prefix.append(event)
        return prefix + normalized + suffix

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

    def _first_transcript_start(self, run_dir: Path) -> dict[str, object] | None:
        tpath = run_dir / "transcript.jsonl"
        if not tpath.is_file():
            return None
        for line in tpath.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("event") == "start":
                return obj
        return None

    def _benchmark_meta_from_run(self, run_dir: Path) -> dict[str, object]:
        bundle_id = ""
        level: int | None = None
        backend: str | None = None
        rpath = run_dir / "result.json"
        if rpath.is_file():
            try:
                parsed = json.loads(rpath.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                bundle_id = str(parsed.get("bundle_id") or "")
                br = parsed.get("backend")
                backend = str(br) if isinstance(br, str) and br else backend
        start_ev = self._first_transcript_start(run_dir)
        if isinstance(start_ev, dict):
            if not bundle_id:
                bundle_id = str(start_ev.get("bundle_id") or "")
            lv = start_ev.get("level")
            if lv is not None:
                try:
                    level = int(lv)
                except (TypeError, ValueError):
                    level = None
            if not backend:
                sb = start_ev.get("backend")
                if isinstance(sb, str) and sb:
                    backend = sb
        return {"bundle_id": bundle_id, "level": level, "backend": backend, "manifest_path": ""}

    def _load_benchmark_context(self, run_dir: Path) -> dict[str, object]:
        snap = run_dir / BENCHMARK_STATIC_JSON
        if snap.is_file():
            try:
                raw = json.loads(snap.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return {
                    "source": "invalid_snapshot",
                    "file_path": self._relative_repo(snap),
                    "notice": f"benchmark_static.json is not valid JSON ({exc}).",
                    "sections": [],
                    **self._benchmark_meta_from_run(run_dir),
                }
            if isinstance(raw, dict):
                sections = raw.get("sections")
                if isinstance(sections, list):
                    out = {**raw}
                    out["source"] = "snapshot"
                    out["file_path"] = self._relative_repo(snap)
                    return out
        workspace = run_dir / "workspace"
        targets = workspace / "TARGETS.md"
        agent_md = workspace / ".opencode" / "agent" / "cyberbench.md"
        if targets.is_file() or agent_md.is_file():
            sections: list[dict[str, object]] = []
            if agent_md.is_file():
                sections.append(
                    {
                        "id": "agent_config",
                        "title": "Agent instructions (.opencode/agent/cyberbench.md)",
                        "content": agent_md.read_text(encoding="utf-8"),
                    }
                )
            if targets.is_file():
                sections.append(
                    {
                        "id": "targets",
                        "title": "Targets (TARGETS.md)",
                        "content": targets.read_text(encoding="utf-8"),
                    }
                )
            meta = self._benchmark_meta_from_run(run_dir)
            return {
                "version": 1,
                "backend": str(meta.get("backend") or "opencode"),
                "bundle_id": str(meta.get("bundle_id") or ""),
                "level": meta.get("level"),
                "manifest_path": "",
                "source": "workspace",
                "file_path": None,
                "notice": (
                    "Reconstructed from workspace files on disk (benchmark_static.json missing). "
                    "CLI prompt and manifest path are omitted."
                ),
                "sections": sections,
            }
        meta = self._benchmark_meta_from_run(run_dir)
        return {
            "version": 1,
            "bundle_id": str(meta.get("bundle_id") or ""),
            "level": meta.get("level"),
            "backend": meta.get("backend"),
            "manifest_path": "",
            "source": "missing",
            "file_path": None,
            "sections": [],
            "notice": (
                "No benchmark_static.json and no workspace/TARGETS.md found. "
                "Re-run with an up-to-date cyberbench to emit benchmark_static.json."
            ),
        }

    def _build_runs_index(self) -> dict[str, list[str]]:
        bundles: dict[str, list[str]] = {}
        root = self.runs_root
        if not root.is_dir():
            return bundles
        for bundle_dir in sorted(root.iterdir(), key=lambda p: p.name):
            if not bundle_dir.is_dir():
                continue
            run_names: list[str] = []
            for run_dir in sorted(
                bundle_dir.iterdir(), key=lambda p: p.name, reverse=True
            ):
                if run_dir.is_dir() and (run_dir / "transcript.jsonl").is_file():
                    run_names.append(run_dir.name)
            if run_names:
                bundles[bundle_dir.name] = run_names
        return bundles

    def _build_jobs_index(self) -> dict[str, list[str]]:
        jobs: dict[str, list[str]] = {}
        root = self.jobs_root
        if not root.is_dir():
            return jobs
        for job_dir in sorted(root.iterdir(), key=lambda p: p.name, reverse=True):
            if not job_dir.is_dir():
                continue
            trial_names: list[str] = []
            for trial_dir in sorted(job_dir.iterdir(), key=lambda p: p.name):
                if trial_dir.is_dir() and trial_has_agent_trace(trial_dir):
                    trial_names.append(trial_dir.name)
            if trial_names:
                jobs[job_dir.name] = trial_names
        return jobs

    def _load_harbor_run_payload(
        self,
        job_q: str,
        trial_q: str,
    ) -> dict[str, object]:
        trial_dir = self._safe_trial_path(job_q, trial_q)
        trial_result = self._read_result(trial_dir)
        transcript, parse_warnings = load_trajectory_transcript(
            trial_dir,
            trial_result=trial_result,
        )
        trajectory_path = trial_dir / "agent" / "trajectory.json"
        return {
            "source": SOURCE_JOBS,
            "bundle": job_q,
            "run": trial_q,
            "transcript": transcript,
            "result": enrich_harbor_result(trial_dir, trial_result),
            "transcript_path": (
                self._relative_repo(trajectory_path)
                if trajectory_path.is_file()
                else self._relative_repo(trial_dir / "agent")
            ),
            "trajectory_path": (
                self._relative_repo(trajectory_path)
                if trajectory_path.is_file()
                else None
            ),
            "opencode_path": None,
            "opencode_session_path": None,
            "result_path": (
                self._relative_repo(trial_dir / "result.json")
                if (trial_dir / "result.json").is_file()
                else None
            ),
            "benchmark_static_path": None,
            "benchmark_context": load_harbor_benchmark_context(
                trial_dir,
                self.repo_root,
                trial_result=trial_result,
            ),
            "parse_warnings": parse_warnings,
        }

    def _load_legacy_run_payload(self, bundle_q: str, run_q: str) -> dict[str, object]:
        run_dir = self._safe_run_path(bundle_q, run_q)
        transcript, tw = self._read_transcript_lines(run_dir)
        opencode, ow = self._read_opencode_lines(run_dir)
        opencode_session, sw = self._read_opencode_session_lines(run_dir)
        parse_warnings = [*tw, *ow, *sw]
        transcript = self._merge_opencode_transcript(transcript, opencode, opencode_session)
        static_path = run_dir / BENCHMARK_STATIC_JSON
        return {
            "source": SOURCE_RUNS,
            "bundle": bundle_q,
            "run": run_q,
            "transcript": transcript,
            "result": self._read_result(run_dir),
            "transcript_path": self._relative_repo(run_dir / "transcript.jsonl"),
            "trajectory_path": None,
            "opencode_path": (
                self._relative_repo(run_dir / "opencode.stdout.jsonl")
                if (run_dir / "opencode.stdout.jsonl").is_file()
                else None
            ),
            "opencode_session_path": (
                self._relative_repo(run_dir / "opencode.session.jsonl")
                if (run_dir / "opencode.session.jsonl").is_file()
                else None
            ),
            "result_path": (
                self._relative_repo(run_dir / "result.json")
                if (run_dir / "result.json").is_file()
                else None
            ),
            "benchmark_static_path": (
                self._relative_repo(static_path) if static_path.is_file() else None
            ),
            "benchmark_context": self._load_benchmark_context(run_dir),
            "parse_warnings": parse_warnings,
        }

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
                self.send_json(
                    {
                        "runs": self._build_runs_index(),
                        "jobs": self._build_jobs_index(),
                        # Legacy clients expect top-level "bundles" for runs only.
                        "bundles": self._build_runs_index(),
                    }
                )
            except OSError as e:
                self.send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/run":
            params = parse_qs(parsed.query)
            bundle_vals = params.get("bundle", [])
            run_vals = params.get("run", [])
            source_vals = params.get("source", [SOURCE_RUNS])
            if len(bundle_vals) != 1 or len(run_vals) != 1:
                self.send_json(
                    {"error": "exactly one bundle= and run= query parameter required"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            if len(source_vals) != 1 or source_vals[0] not in {SOURCE_RUNS, SOURCE_JOBS}:
                self.send_json(
                    {"error": f"source= must be {SOURCE_RUNS!r} or {SOURCE_JOBS!r}"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            bundle_q, run_q = bundle_vals[0], run_vals[0]
            source_q = source_vals[0]
            try:
                if source_q == SOURCE_JOBS:
                    payload = self._load_harbor_run_payload(bundle_q, run_q)
                else:
                    payload = self._load_legacy_run_payload(bundle_q, run_q)
                self.send_json(payload)
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


def _normalize_opencode_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    step = 0
    for event in events:
        event_type = event.get("type")
        if event_type == "error":
            out.append(
                {
                    "event": "opencode_error",
                    "source": "opencode",
                    "step": step,
                    "error": _opencode_error_message(event),
                    "opencode_line": event.get("_opencode_line"),
                    "raw": event,
                }
            )
            continue
        part = event.get("part")
        if not isinstance(part, dict):
            continue
        if event_type == "step_start":
            step += 1
            continue
        if event_type == "text":
            text = part.get("text")
            if isinstance(text, str) and text:
                out.append(
                    {
                        "event": "assistant",
                        "source": "opencode",
                        "step": step,
                        "message": {"role": "assistant", "content": text},
                        "opencode_line": event.get("_opencode_line"),
                    }
                )
            continue
        if event_type == "tool_use":
            tool_events = _normalize_opencode_tool_use(part, step, event.get("_opencode_line"))
            out.extend(tool_events)
            continue
        if event_type == "step_finish":
            out.append(
                {
                    "event": "opencode_step_finish",
                    "source": "opencode",
                    "step": step,
                    "reason": part.get("reason"),
                    "cost": part.get("cost"),
                    "tokens": part.get("tokens"),
                    "opencode_line": event.get("_opencode_line"),
                }
            )
    return out


def _normalize_opencode_session_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    message_roles: dict[str, str] = {}
    for event in events:
        if event.get("type") != "message":
            continue
        message_id = event.get("id")
        data = event.get("data")
        if not isinstance(message_id, str) or not isinstance(data, dict):
            continue
        role = data.get("role")
        if isinstance(role, str):
            message_roles[message_id] = role

    step = 0
    for event in events:
        if event.get("type") != "part":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        part_type = data.get("type")
        line_no = event.get("_opencode_session_line")
        message_id = event.get("message_id")
        role = message_roles.get(message_id) if isinstance(message_id, str) else None
        if part_type == "step-start":
            step += 1
            continue
        if part_type == "text" and role == "assistant":
            text = data.get("text")
            if isinstance(text, str) and text:
                out.append(
                    {
                        "event": "assistant",
                        "source": "opencode-session",
                        "step": step,
                        "message": {"role": "assistant", "content": text},
                        "opencode_session_line": line_no,
                    }
                )
            continue
        if part_type == "tool":
            tool_events = _normalize_opencode_tool_use(data, step, line_no)
            for tool_event in tool_events:
                tool_event["source"] = "opencode-session"
                tool_event["opencode_session_line"] = line_no
            out.extend(tool_events)
            continue
        if part_type == "step-finish":
            out.append(
                {
                    "event": "opencode_step_finish",
                    "source": "opencode-session",
                    "step": step,
                    "reason": data.get("reason"),
                    "cost": data.get("cost"),
                    "tokens": data.get("tokens"),
                    "opencode_session_line": line_no,
                }
            )
    return out


def _opencode_error_message(event: dict[str, object]) -> str:
    error = event.get("error")
    if not isinstance(error, dict):
        return "OpenCode error"
    name = error.get("name")
    data = error.get("data")
    message = error.get("message")
    if isinstance(data, dict):
        message = data.get("message") or message
    if not isinstance(message, str) or not message.strip():
        message = str(name) if name else "OpenCode error"
    if isinstance(name, str) and name and name not in message:
        return f"{name}: {message}"
    return message


def _normalize_opencode_tool_use(part: dict[str, object], step: int, line_no: object) -> list[dict[str, object]]:
    state = part.get("state")
    if not isinstance(state, dict):
        state = {}
    tool_input = state.get("input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    call_id = str(part.get("callID") or part.get("id") or f"opencode-{line_no}")
    command = str(tool_input.get("command") or "")
    tool_name = "submit_flag" if _is_submit_flag_command(command) else str(part.get("tool") or "tool")
    arguments: dict[str, object]
    if tool_name == "submit_flag":
        arguments = {"flag": _extract_flag_from_command(command), "command": command}
        result = _opencode_submit_result(str(state.get("output") or metadata.get("output") or ""))
    else:
        arguments = {"command": command, "description": tool_input.get("description")}
        result = _opencode_shell_result(state, metadata)
    assistant = {
        "event": "assistant",
        "source": "opencode",
        "step": step,
        "message": {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call_id,
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            ],
        },
        "opencode_line": line_no,
    }
    tool_result = {
        "event": "tool_result",
        "source": "opencode",
        "step": step,
        "tool_call_id": call_id,
        "result": result,
        "opencode_line": line_no,
    }
    return [assistant, tool_result]


def _opencode_shell_result(state: dict[object, object], metadata: dict[object, object]) -> dict[str, object]:
    output = str(state.get("output") or metadata.get("output") or "")
    exit_code_raw = metadata.get("exit")
    try:
        exit_code = int(exit_code_raw) if exit_code_raw is not None else None
    except (TypeError, ValueError):
        exit_code = None
    status = state.get("status")
    return {
        "ok": status == "completed" and exit_code in (None, 0),
        "exit_code": exit_code,
        "stdout": output,
        "stderr": "",
        "timed_out": status == "timed_out",
        "elapsed_seconds": _opencode_elapsed_seconds(state),
    }


def _opencode_elapsed_seconds(state: dict[object, object]) -> float | None:
    time_data = state.get("time")
    if not isinstance(time_data, dict):
        return None
    start = time_data.get("start")
    end = time_data.get("end")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
        return (end - start) / 1000
    return None


def _is_submit_flag_command(command: str) -> bool:
    return bool("submit_flag" in command.split()) or "./submit_flag" in command


def _extract_flag_from_command(command: str) -> str:
    for prefix in ("CYBERBENCH{", "CTF{"):
        start = command.find(prefix)
        if start >= 0:
            end = command.find("}", start)
            if end >= 0:
                return command[start : end + 1]
    return ""


def _opencode_submit_result(output: str) -> dict[str, object]:
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        parsed = {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _make_handler_class(
    viewer_root: Path,
    repo_root: Path,
    runs_root: Path,
    jobs_root: Path,
) -> type[TranscriptViewerRequestHandler]:
    vr = viewer_root.resolve()
    rr = repo_root.resolve()
    sr = runs_root.resolve()
    jr = jobs_root.resolve()

    class Bound(TranscriptViewerRequestHandler):
        viewer_root = vr
        repo_root = rr
        runs_root = sr
        jobs_root = jr

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
    parser.add_argument(
        "--jobs-dir",
        type=Path,
        default=None,
        help="override Harbor jobs directory (default: <repo-root>/jobs)",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    runs_root = (args.runs_dir or (repo_root / "runs")).resolve()
    jobs_root = (args.jobs_dir or (repo_root / "jobs")).resolve()
    viewer_root = VIEWER_ROOT.resolve()

    handler = _make_handler_class(viewer_root, repo_root, runs_root, jobs_root)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Cyber-Bench transcript viewer — open {url}")
    print(f"Harbor jobs root: {jobs_root}")
    print(f"Legacy runs root: {runs_root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()

"""Convert Harbor job trial artifacts to transcript-viewer event records."""

from __future__ import annotations

import json
import re
from pathlib import Path


def trial_has_agent_trace(trial_dir: Path) -> bool:
    agent = trial_dir / "agent"
    if not agent.is_dir():
        return False
    if (agent / "trajectory.json").is_file():
        return True
    return any(p.is_dir() and p.name.startswith("command-") for p in agent.iterdir())


def level_from_task_path(task_path: str) -> int | None:
    match = re.search(r"/l([0-4])(?:/|$)", task_path)
    if not match:
        return None
    return int(match.group(1))


def load_trajectory_transcript(
    trial_dir: Path,
    *,
    trial_result: dict[str, object] | None,
) -> tuple[list[dict[str, object]], list[str]]:
    trajectory_path = trial_dir / "agent" / "trajectory.json"
    if not trajectory_path.is_file():
        return commands_to_transcript(trial_dir, trial_result=trial_result)

    try:
        raw = json.loads(trajectory_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"trajectory.json: invalid JSON ({exc})") from exc
    if not isinstance(raw, dict):
        raise ValueError("trajectory.json: root must be an object")

    warnings: list[str] = []
    out: list[dict[str, object]] = [start_event(raw, trial_result)]
    steps = raw.get("steps")
    if not isinstance(steps, list):
        raise ValueError("trajectory.json: missing steps array")

    for step in steps:
        if not isinstance(step, dict):
            warnings.append("trajectory.json: skipped non-object step")
            continue
        if step.get("source") != "agent":
            continue
        out.extend(agent_step_events(step))

    finish = finish_event(trial_result, trial_dir)
    if finish is not None:
        out.append(finish)
    return out, warnings


def commands_to_transcript(
    trial_dir: Path,
    *,
    trial_result: dict[str, object] | None,
) -> tuple[list[dict[str, object]], list[str]]:
    agent = trial_dir / "agent"
    command_dirs = sorted(
        (p for p in agent.iterdir() if p.is_dir() and p.name.startswith("command-")),
        key=_command_dir_sort_key,
    )
    if not command_dirs:
        raise FileNotFoundError("no trajectory.json or agent/command-* logs found")

    out: list[dict[str, object]] = [
        {
            "event": "start",
            "source": "harbor",
            "bundle_id": _task_path_from_result(trial_result),
            "level": level_from_task_path(_task_path_from_result(trial_result)),
        }
    ]
    for index, cmd_dir in enumerate(command_dirs, start=1):
        out.extend(command_dir_events(cmd_dir, index))
    finish = finish_event(trial_result, trial_dir)
    if finish is not None:
        out.append(finish)
    return out, []


def enrich_harbor_result(
    trial_dir: Path,
    result: dict[str, object] | None,
) -> dict[str, object] | None:
    if result is None:
        return None
    enriched: dict[str, object] = dict(result)
    details_path = trial_dir / "verifier" / "details.json"
    if details_path.is_file():
        try:
            details = json.loads(details_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            details = None
        if isinstance(details, dict):
            enriched["verifier_details"] = details
            for key in (
                "reward",
                "solved_service_ids",
                "unsolved_service_ids",
                "submitted_flags",
            ):
                if key in details:
                    enriched[key] = details[key]
    task_path = _task_path_from_result(result)
    if task_path:
        enriched["task_path"] = task_path
    agent_info = result.get("agent_info")
    if isinstance(agent_info, dict):
        model_info = agent_info.get("model_info")
        if isinstance(model_info, dict) and model_info.get("name"):
            enriched["model"] = model_info["name"]
        if agent_info.get("name"):
            enriched["agent"] = agent_info["name"]
    agent_result = result.get("agent_result")
    if isinstance(agent_result, dict):
        if agent_result.get("cost_usd") is not None:
            enriched["cost_usd"] = agent_result["cost_usd"]
        metadata = agent_result.get("metadata")
        if isinstance(metadata, dict) and metadata.get("n_episodes") is not None:
            enriched["n_episodes"] = metadata["n_episodes"]
    verifier_result = result.get("verifier_result")
    if isinstance(verifier_result, dict):
        rewards = verifier_result.get("rewards")
        if isinstance(rewards, dict) and rewards.get("reward") is not None:
            enriched["reward"] = rewards["reward"]
    exc = result.get("exception_info")
    if isinstance(exc, dict):
        if exc.get("exception_type"):
            enriched["exception_type"] = exc["exception_type"]
        if exc.get("exception_message"):
            enriched["exception_message"] = exc["exception_message"]
        enriched["status"] = "error"
    return enriched


def load_harbor_benchmark_context(
    trial_dir: Path,
    repo_root: Path,
    *,
    trial_result: dict[str, object] | None,
) -> dict[str, object]:
    task_path = _task_path_from_result(trial_result)
    level = level_from_task_path(task_path)
    sections: list[dict[str, object]] = []

    if task_path:
        instruction = repo_root / task_path / "instruction.md"
        if instruction.is_file():
            sections.append(
                {
                    "id": "instruction",
                    "title": "Task instruction (instruction.md)",
                    "content": instruction.read_text(encoding="utf-8"),
                }
            )

    details_path = trial_dir / "verifier" / "details.json"
    if details_path.is_file():
        sections.append(
            {
                "id": "verifier_details",
                "title": "Verifier details (verifier/details.json)",
                "content": details_path.read_text(encoding="utf-8"),
            }
        )

    exc_path = trial_dir / "exception.txt"
    if exc_path.is_file():
        sections.append(
            {
                "id": "exception",
                "title": "Trial exception (exception.txt)",
                "content": exc_path.read_text(encoding="utf-8"),
            }
        )

    return {
        "version": 1,
        "backend": "harbor",
        "bundle_id": task_path,
        "level": level,
        "manifest_path": "",
        "source": "harbor_task" if sections else "missing",
        "file_path": task_path or None,
        "sections": sections,
        "notice": (
            None
            if sections
            else "No instruction.md or verifier details found for this trial."
        ),
    }


def start_event(
    trajectory: dict[str, object],
    trial_result: dict[str, object] | None,
) -> dict[str, object]:
    agent = trajectory.get("agent")
    model = ""
    agent_name = ""
    if isinstance(agent, dict):
        model = str(agent.get("model_name") or "")
        agent_name = str(agent.get("name") or "")
    task_path = _task_path_from_result(trial_result)
    task_name = ""
    if trial_result is not None:
        task_name = str(trial_result.get("task_name") or "")
    return {
        "event": "start",
        "source": "harbor",
        "model": model,
        "bundle_id": task_path or task_name,
        "level": level_from_task_path(task_path),
        "agent": agent_name,
    }


def agent_step_events(step: dict[str, object]) -> list[dict[str, object]]:
    step_id = step.get("step_id")
    step_num = int(step_id) if isinstance(step_id, int) else 0
    message_text = str(step.get("message") or "")
    tool_calls_raw = step.get("tool_calls")
    openai_tool_calls: list[dict[str, object]] = []
    if isinstance(tool_calls_raw, list):
        for tc in tool_calls_raw:
            if not isinstance(tc, dict):
                continue
            fn = str(tc.get("function_name") or "tool")
            args = tc.get("arguments")
            if not isinstance(args, dict):
                args = {}
            tool_name = "shell" if fn == "bash_command" else fn
            payload: dict[str, object] = {
                "command": str(args.get("keystrokes") or ""),
            }
            duration = args.get("duration")
            if duration is not None:
                payload["duration"] = duration
            openai_tool_calls.append(
                {
                    "id": str(tc.get("tool_call_id") or ""),
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(payload, ensure_ascii=False),
                    },
                }
            )

    assistant: dict[str, object] = {
        "event": "assistant",
        "source": "harbor",
        "step": step_num,
        "message": {
            "role": "assistant",
            "content": message_text,
        },
    }
    if openai_tool_calls:
        msg = assistant["message"]
        if isinstance(msg, dict):
            msg["tool_calls"] = openai_tool_calls

    metrics = step.get("metrics")
    if isinstance(metrics, dict):
        usage: dict[str, object] = {}
        for key in ("prompt_tokens", "completion_tokens", "cached_tokens", "cost_usd"):
            if metrics.get(key) is not None:
                usage[key] = metrics[key]
        if usage:
            assistant["usage"] = usage

    records: list[dict[str, object]] = [assistant]
    stdout = observation_stdout(step.get("observation"))
    if stdout and openai_tool_calls:
        first_id = openai_tool_calls[0].get("id")
        records.append(
            {
                "event": "tool_result",
                "source": "harbor",
                "step": step_num,
                "tool_call_id": first_id,
                "result": {
                    "ok": True,
                    "stdout": stdout,
                    "stderr": "",
                },
            }
        )
    return records


def command_dir_events(cmd_dir: Path, step: int) -> list[dict[str, object]]:
    command = _read_optional_text(cmd_dir / "command.txt")
    stdout = _read_optional_text(cmd_dir / "stdout.txt")
    stderr = _read_optional_text(cmd_dir / "stderr.txt")
    exit_code_raw = _read_optional_text(cmd_dir / "return-code.txt").strip()
    try:
        exit_code = int(exit_code_raw) if exit_code_raw else 0
    except ValueError:
        exit_code = None

    call_id = f"harbor-cmd-{cmd_dir.name}"
    assistant: dict[str, object] = {
        "event": "assistant",
        "source": "harbor",
        "step": step,
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "function": {
                        "name": "shell",
                        "arguments": json.dumps({"command": command}, ensure_ascii=False),
                    },
                }
            ],
        },
    }
    tool_result: dict[str, object] = {
        "event": "tool_result",
        "source": "harbor",
        "step": step,
        "tool_call_id": call_id,
        "result": {
            "ok": exit_code in (None, 0),
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        },
    }
    return [assistant, tool_result]


def finish_event(
    trial_result: dict[str, object] | None,
    trial_dir: Path,
) -> dict[str, object] | None:
    if trial_result is None:
        return None

    exc = trial_result.get("exception_info")
    status = "completed"
    if isinstance(exc, dict) and exc.get("exception_type"):
        status = str(exc["exception_type"])

    agent_result = trial_result.get("agent_result")
    cost_usd = None
    n_episodes = None
    if isinstance(agent_result, dict):
        cost_usd = agent_result.get("cost_usd")
        metadata = agent_result.get("metadata")
        if isinstance(metadata, dict):
            n_episodes = metadata.get("n_episodes")

    reward = None
    verifier_result = trial_result.get("verifier_result")
    if isinstance(verifier_result, dict):
        rewards = verifier_result.get("rewards")
        if isinstance(rewards, dict):
            reward = rewards.get("reward")

    details: dict[str, object] = {}
    details_path = trial_dir / "verifier" / "details.json"
    if details_path.is_file():
        try:
            parsed = json.loads(details_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            details = parsed
            if reward is None and parsed.get("reward") is not None:
                reward = parsed["reward"]

    task_path = _task_path_from_result(trial_result)
    model = ""
    agent_info = trial_result.get("agent_info")
    if isinstance(agent_info, dict):
        model_info = agent_info.get("model_info")
        if isinstance(model_info, dict):
            model = str(model_info.get("name") or "")

    summary: dict[str, object] = {
        "status": status,
        "task_path": task_path,
        "task_name": trial_result.get("task_name"),
        "model": model,
        "reward": reward,
        "cost_usd": cost_usd,
        "n_episodes": n_episodes,
        "solved_service_ids": details.get("solved_service_ids", []),
        "unsolved_service_ids": details.get("unsolved_service_ids", []),
        "submitted_flags": details.get("submitted_flags", []),
    }
    if isinstance(exc, dict):
        summary["exception_type"] = exc.get("exception_type")
        summary["exception_message"] = exc.get("exception_message")

    return {"event": "finish", "source": "harbor", "result": summary}


def observation_stdout(observation: object) -> str:
    if not isinstance(observation, dict):
        return ""
    results = observation.get("results")
    if not isinstance(results, list):
        return ""
    parts: list[str] = []
    for item in results:
        if isinstance(item, dict):
            content = item.get("content")
            if isinstance(content, str) and content:
                parts.append(content)
    return "\n".join(parts)


def _task_path_from_result(trial_result: dict[str, object] | None) -> str:
    if trial_result is None:
        return ""
    task_id = trial_result.get("task_id")
    if isinstance(task_id, dict):
        return str(task_id.get("path") or "")
    return ""


def _read_optional_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _command_dir_sort_key(path: Path) -> int:
    suffix = path.name.removeprefix("command-")
    return int(suffix) if suffix.isdigit() else 0

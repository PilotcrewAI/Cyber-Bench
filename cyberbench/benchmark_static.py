from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypedDict

STATIC_FILENAME = "benchmark_static.json"


class BenchmarkStaticSection(TypedDict):
    id: str
    title: str
    content: str


class BenchmarkStaticFile(TypedDict):
    version: Literal[1]
    backend: Literal["openrouter", "opencode"]
    bundle_id: str
    level: int | None
    manifest_path: str
    sections: list[BenchmarkStaticSection]


def write_benchmark_static(run_dir: Path, payload: BenchmarkStaticFile) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / STATIC_FILENAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, indent=2, sort_keys=True, ensure_ascii=False)


def build_openrouter_static(
    *,
    bundle_id: str,
    level: int | None,
    manifest_path: Path,
    initial_messages: list[dict[str, object]],
    tool_definitions: list[dict[str, object]],
) -> BenchmarkStaticFile:
    sections: list[BenchmarkStaticSection] = [
        {
            "id": "manifest",
            "title": "Bundle manifest path",
            "content": str(manifest_path.resolve()),
        }
    ]
    for idx, msg in enumerate(initial_messages):
        role = msg.get("role")
        if role == "system":
            sections.append(
                {
                    "id": f"system_{idx}",
                    "title": "System prompt (OpenRouter chat API)",
                    "content": _message_text(msg.get("content")),
                }
            )
        elif role == "user":
            sections.append(
                {
                    "id": f"user_{idx}",
                    "title": "Initial user message (targets & task)",
                    "content": _message_text(msg.get("content")),
                }
            )
    sections.append(
        {
            "id": "tools",
            "title": "Tool definitions (OpenRouter chat API)",
            "content": json.dumps(tool_definitions, indent=2, sort_keys=True, ensure_ascii=False),
        }
    )
    return {
        "version": 1,
        "backend": "openrouter",
        "bundle_id": bundle_id,
        "level": level,
        "manifest_path": str(manifest_path.resolve()),
        "sections": sections,
    }


def build_opencode_static(
    *,
    bundle_id: str,
    level: int | None,
    manifest_path: Path,
    workspace: Path,
    cli_prompt: str,
) -> BenchmarkStaticFile:
    agent_path = workspace / ".opencode" / "agent" / "cyberbench.md"
    targets_path = workspace / "TARGETS.md"
    sections: list[BenchmarkStaticSection] = [
        {
            "id": "manifest",
            "title": "Bundle manifest path",
            "content": str(manifest_path.resolve()),
        },
        {
            "id": "agent_config",
            "title": "Agent instructions (.opencode/agent/cyberbench.md)",
            "content": agent_path.read_text(encoding="utf-8"),
        },
        {
            "id": "targets",
            "title": "Targets (TARGETS.md)",
            "content": targets_path.read_text(encoding="utf-8"),
        },
        {
            "id": "cli_prompt",
            "title": "OpenCode CLI prompt",
            "content": cli_prompt,
        },
    ]
    return {
        "version": 1,
        "backend": "opencode",
        "bundle_id": bundle_id,
        "level": level,
        "manifest_path": str(manifest_path.resolve()),
        "sections": sections,
    }

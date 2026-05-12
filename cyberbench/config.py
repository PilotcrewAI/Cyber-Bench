from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
CYBERBENCH_MODEL_ENV = "CYBERBENCH_MODEL"


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def require_openrouter_key() -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set. Put it in .env or the environment.")
    return api_key


def resolve_model(cli_model: str | None) -> str:
    if cli_model:
        trimmed = cli_model.strip()
        if trimmed:
            return trimmed
    env_model = os.environ.get(CYBERBENCH_MODEL_ENV, "").strip()
    if env_model:
        return env_model
    return DEFAULT_MODEL


def path_slug(segment: str) -> str:
    """Single path segment derived from a model id, bundle id, or similar."""
    return segment.replace(":", "-").replace("/", "-")


def local_timestamp_slug() -> str:
    """Local wall-clock time on this machine (sortable, safe for directory names)."""
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")

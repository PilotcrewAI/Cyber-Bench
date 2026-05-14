from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

# Transient TLS/network failures (e.g. SSLV3_ALERT_BAD_RECORD_MAC) and overloaded gateways.
_RETRIES = 5
_RETRY_BASE_SEC = 1.0
_RETRY_MAX_SEC = 30.0
_RETRYABLE_HTTP = frozenset({429, 502, 503, 504})


def _retry_sleep_seconds(attempt: int) -> float:
    return min(_RETRY_BASE_SEC * (2**attempt), _RETRY_MAX_SEC)


def _is_transient_url_error(exc: urllib.error.URLError) -> bool:
    # Permanent misconfiguration (e.g. wrong CA); retrying will not help.
    if isinstance(exc.reason, ssl.SSLCertVerificationError):
        return False
    return True


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None


class OpenRouterClient:
    def __init__(self, api_key: str, *, app_title: str = "Cyber-Bench") -> None:
        self.api_key = api_key
        self.app_title = app_title

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "reasoning": {"effort": "high"},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        request = urllib.request.Request(
            OPENROUTER_CHAT_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/pilotcrew/cyber-bench",
                "X-Title": self.app_title,
            },
            method="POST",
        )
        last_error: BaseException | None = None
        for attempt in range(_RETRIES):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return _load_json_response(response.read())
            except urllib.error.HTTPError as exc:
                if exc.code in _RETRYABLE_HTTP and attempt < _RETRIES - 1:
                    _ = exc.read()
                    last_error = exc
                    time.sleep(_retry_sleep_seconds(attempt))
                    continue
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"OpenRouter request failed with HTTP {exc.code}: {body}"
                ) from exc
            except urllib.error.URLError as exc:
                # HTTPError is a subclass of URLError; already handled above.
                if attempt < _RETRIES - 1 and _is_transient_url_error(exc):
                    last_error = exc
                    time.sleep(_retry_sleep_seconds(attempt))
                    continue
                raise RuntimeError(f"OpenRouter request failed: {exc}") from exc
            except (ConnectionError, ssl.SSLError, TimeoutError) as exc:
                if attempt < _RETRIES - 1:
                    last_error = exc
                    time.sleep(_retry_sleep_seconds(attempt))
                    continue
                raise RuntimeError(f"OpenRouter request failed: {exc}") from exc
        assert last_error is not None
        raise RuntimeError(f"OpenRouter request failed after {_RETRIES} attempts") from last_error


def response_usage(response: dict[str, Any]) -> Usage:
    raw = response.get("usage") or {}
    cost = raw.get("cost")
    return Usage(
        prompt_tokens=int(raw.get("prompt_tokens") or 0),
        completion_tokens=int(raw.get("completion_tokens") or 0),
        total_tokens=int(raw.get("total_tokens") or 0),
        cost_usd=float(cost) if cost is not None else None,
    )


def _load_json_response(raw_body: bytes) -> dict[str, Any]:
    body = raw_body.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        snippet = body[:1000] if body else "<empty response>"
        raise RuntimeError(f"OpenRouter returned a non-JSON response: {exc}; body starts with: {snippet!r}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"OpenRouter returned a JSON response that was not an object: {parsed!r}")
    return parsed


def first_message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError(f"OpenRouter response did not include choices: {response}")
    return choices[0].get("message") or {}

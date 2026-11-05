"""Shared provider types and HTTP helpers."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx


class ProviderError(RuntimeError):
    """Raised when a provider cannot complete a request."""


class MissingAPIKey(ProviderError):
    """Raised when the selected provider needs a key that is not configured."""


@dataclass
class ToolCall:
    """A normalized tool call emitted by an LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssistantTurn:
    """A normalized assistant response."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None


class BaseProvider(ABC):
    """Common interface implemented by every LLM provider."""

    name: str = "provider"
    supports_tools: bool = True

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> AssistantTurn:
        """Send a chat request and return a normalized response."""

    # ── HTTP ────────────────────────────────────────────────────────────

    def _request(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """POST JSON with small retries for transient failures."""

        last_error: str | None = None
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            for attempt in range(3):
                try:
                    response = client.post(url, headers=headers, json=payload)
                except httpx.TimeoutException as exc:
                    raise ProviderError(
                        f"{self.name}: request timed out after {self.timeout:.0f}s."
                    ) from exc
                except httpx.RequestError as exc:
                    raise ProviderError(
                        f"{self.name}: could not reach {url} ({exc})."
                    ) from exc

                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue

                if response.status_code >= 400:
                    detail = _extract_error(response)
                    hint = ""
                    if response.status_code in {401, 403}:
                        hint = (
                            " Check that your API key is valid and exported in the "
                            "environment (or in ~/.hermes/.env)."
                        )
                    raise ProviderError(
                        f"{self.name}: API error {response.status_code}: {detail}.{hint}"
                    )

                try:
                    data = response.json()
                except ValueError as exc:
                    raise ProviderError(
                        f"{self.name}: API returned invalid JSON."
                    ) from exc
                if not isinstance(data, dict):
                    raise ProviderError(f"{self.name}: unexpected API response shape.")
                return data

        raise ProviderError(last_error or f"{self.name}: request failed.")


def _extract_error(response: httpx.Response) -> str:
    """Pull a human-readable error message out of an HTTP response."""

    try:
        data = response.json()
    except ValueError:
        return (response.text or response.reason_phrase or "unknown error")[:600]

    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail")
            if message:
                return str(message)[:600]
        if isinstance(error, str):
            return error[:600]
        for key in ("message", "detail"):
            if data.get(key):
                return str(data[key])[:600]
    return json.dumps(data, ensure_ascii=False)[:600]

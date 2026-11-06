"""OpenAI Chat Completions compatible provider.

Works with OpenAI, OpenRouter, DeepSeek, Groq, Google Gemini (AI Studio) and
local Ollama, plus Hugging Face serverless inference.
"""

from __future__ import annotations

import json
from typing import Any

from .base import AssistantTurn, BaseProvider, ProviderError, ToolCall


class OpenAICompatibleProvider(BaseProvider):
    def __init__(
        self,
        name: str,
        model: str,
        api_key: str | None = None,
        base_url: str = "",
        extra_headers: dict[str, str] | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(
            model=model, api_key=api_key, base_url=base_url, timeout=timeout
        )
        self.name = name
        self.extra_headers = extra_headers or {}

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> AssistantTurn:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = self._request(
            f"{self.base_url}/chat/completions",
            headers=headers,
            payload=payload,
        )
        return self.parse_response(data)

    def parse_response(self, data: dict[str, Any]) -> AssistantTurn:
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(f"{self.name}: API returned no choices.")

        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            # Some OpenAI-compatible servers return content blocks.
            content = "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )

        tool_calls: list[ToolCall] = []
        for index, raw in enumerate(message.get("tool_calls") or []):
            if not isinstance(raw, dict):
                continue
            function = raw.get("function") or {}
            call_id = str(raw.get("id") or f"call_{index}")
            name = str(function.get("name") or "")
            arguments = _decode_arguments(function.get("arguments"))
            if name:
                tool_calls.append(ToolCall(id=call_id, name=name, arguments=arguments))

        return AssistantTurn(
            content=str(content) if content is not None else None,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
        )


def _decode_arguments(raw: Any) -> dict[str, Any]:
    """Decode a tool-call arguments payload without crashing the loop."""

    if isinstance(raw, dict):
        return raw
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw_arguments": raw}
        if isinstance(value, dict):
            return value
        return {"_value": value}
    return {"_value": raw}

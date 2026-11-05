"""Native Anthropic Messages API provider."""

from __future__ import annotations

import json
from typing import Any

from .base import AssistantTurn, BaseProvider, ProviderError, ToolCall


class AnthropicProvider(BaseProvider):
    name = "Anthropic"

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.anthropic.com/v1",
        timeout: float = 120.0,
        max_tokens: int = 4096,
    ) -> None:
        super().__init__(model=model, api_key=api_key, base_url=base_url, timeout=timeout)
        self.max_tokens = max_tokens

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> AssistantTurn:
        system_parts, converted = convert_messages(messages)
        system = "\n\n".join(part for part in system_parts if part.strip())

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": converted,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": spec["function"]["name"],
                    "description": spec["function"].get("description", ""),
                    "input_schema": spec["function"].get("parameters", {}),
                }
                for spec in tools
                if spec.get("type") == "function" and "function" in spec
            ]

        data = self._request(
            f"{self.base_url}/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key or "",
                "anthropic-version": "2023-06-01",
            },
            payload=payload,
        )
        return self.parse_response(data)

    def parse_response(self, data: dict[str, Any]) -> AssistantTurn:
        blocks = data.get("content") or []
        if not isinstance(blocks, list):
            raise ProviderError("Anthropic: unexpected content shape.")

        texts: list[str] = []
        tool_calls: list[ToolCall] = []
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text" and block.get("text"):
                texts.append(str(block["text"]))
            elif block_type == "tool_use":
                arguments = block.get("input")
                if not isinstance(arguments, dict):
                    arguments = {"_value": arguments}
                tool_calls.append(
                    ToolCall(
                        id=str(block.get("id") or f"toolu_{index}"),
                        name=str(block.get("name") or ""),
                        arguments=arguments,
                    )
                )

        content = "\n".join(texts).strip() or None
        return AssistantTurn(
            content=content,
            tool_calls=[call for call in tool_calls if call.name],
            finish_reason=data.get("stop_reason"),
        )


def convert_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Convert normalized OpenAI-style history into Anthropic messages.

    Returns ``(system_parts, messages)``. Consecutive messages with the same
    role are merged because Anthropic expects alternating turns, and tool
    results are grouped into a single user turn.
    """

    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []

    def append(role: str, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"].extend(blocks)
        else:
            converted.append({"role": role, "content": blocks})

    for message in messages:
        role = message.get("role")
        if role == "system":
            text = message.get("content")
            if text:
                system_parts.append(str(text))
            continue

        if role == "user":
            text = message.get("content") or ""
            if isinstance(text, str):
                append("user", [{"type": "text", "text": text}])
            elif isinstance(text, list):
                append("user", text)
            continue

        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = message.get("content")
            if text:
                blocks.append({"type": "text", "text": str(text)})
            for raw_call in message.get("tool_calls") or []:
                if not isinstance(raw_call, dict):
                    continue
                function = raw_call.get("function") or {}
                name = function.get("name")
                if not name:
                    continue
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(raw_call.get("id") or "call_0"),
                        "name": str(name),
                        "input": _decode_arguments(function.get("arguments")),
                    }
                )
            append("assistant", blocks)
            continue

        if role == "tool":
            append(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": str(message.get("tool_call_id") or ""),
                        "content": str(message.get("content") or ""),
                    }
                ],
            )

    return system_parts, converted


def _decode_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw_arguments": raw}
        return value if isinstance(value, dict) else {"_value": value}
    return {"_value": raw}

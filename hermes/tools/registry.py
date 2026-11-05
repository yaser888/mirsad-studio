"""Tool registry: schemas, validation, approval, and execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

ApprovalCallback = Callable[["Tool", dict[str, Any]], bool]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]
    requires_approval: bool = False

    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def tools(self) -> list[Tool]:
        return [self._tools[name] for name in self.names()]

    def specs(self) -> list[dict[str, Any]]:
        return [self._tools[name].spec() for name in self.names()]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        approve: ApprovalCallback | None = None,
    ) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return (
                f"Error: unknown tool '{name}'. Available tools: "
                + ", ".join(self.names())
            )

        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return "Error: tool arguments must be a JSON object."

        properties = (tool.parameters or {}).get("properties") or {}
        required = (tool.parameters or {}).get("required") or []
        missing = [key for key in required if key not in arguments]
        if missing:
            return f"Error: missing required argument(s): {', '.join(missing)}."
        unknown = [key for key in arguments if key not in properties]
        if unknown:
            return (
                f"Error: unknown argument(s) for {name}: {', '.join(unknown)}. "
                f"Allowed: {', '.join(properties)}."
            )

        if tool.requires_approval:
            allowed = bool(approve and approve(tool, arguments))
            if not allowed:
                return (
                    "Action denied by the user. Do not retry the same action. "
                    "Explain what you wanted to do and ask how to proceed."
                )

        try:
            result = tool.func(**arguments)
        except TypeError as exc:
            return f"Error: invalid arguments for {name}: {exc}"
        except Exception as exc:  # noqa: BLE001 - surfaced to the model
            return f"Error: {type(exc).__name__}: {exc}"

        text = "" if result is None else str(result)
        if len(text) > 12_000:
            text = text[:12_000] + (
                f"\n... [tool output truncated, {len(text) - 12_000} characters omitted]"
            )
        return text

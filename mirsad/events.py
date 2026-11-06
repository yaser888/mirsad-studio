"""Event hooks used by the agent loop.

The core loop never writes to stdout directly. Front ends (the Rich CLI and
Mirsad Studio) subscribe to these events instead.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Any


class AgentEvents:
    """No-op event sink; override the methods a front end cares about."""

    def thinking(self, label: str) -> AbstractContextManager[None]:
        return nullcontext()

    def assistant(self, text: str) -> None:
        pass

    def tool_call(
        self, name: str, arguments: dict[str, Any], call_id: str = ""
    ) -> None:
        pass

    def tool_result(self, name: str, result: str, call_id: str = "") -> None:
        pass

    def plan(self, steps: list[str], note: str = "") -> None:
        pass

    def step(self, step: int, total: int) -> None:
        pass

"""The multi-step agent loop."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .events import AgentEvents
from .memory import Session, SessionStore, context_messages
from .prompts import STEP_LIMIT_NOTICE, build_system_prompt
from .providers.base import AssistantTurn, BaseProvider, ToolCall
from .tools import Tool, build_registry
from .tools.registry import ToolRegistry

ApprovalCallback = Callable[[Tool, dict[str, Any]], bool]


class AgentCancelled(RuntimeError):
    """Raised when the user stops a run."""


class Agent:
    """Runs a plan/act/observe loop against a provider and a tool registry."""

    def __init__(
        self,
        *,
        settings: Settings,
        provider: BaseProvider,
        session: Session,
        store: SessionStore,
        approval: ApprovalCallback | None = None,
        events: AgentEvents | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.session = session
        self.store = store
        self.approval = approval
        self.events = events or AgentEvents()
        self.cancel_check = cancel_check
        self.plan: list[str] = list(session.plan)

        self.session.provider = settings.provider
        self.session.model = provider.model
        self.session.workdir = str(settings.workdir)
        self.registry = self._build_registry()

    # ── public API ──────────────────────────────────────────────────────

    def run_turn(self, user_text: str) -> str:
        """Add a user message, run the agent loop, and return the final answer."""

        user_text = (user_text or "").strip()
        if not user_text:
            return ""

        self.session.messages.append({"role": "user", "content": user_text})
        self._save()

        try:
            for step in range(1, self.settings.max_steps + 1):
                self._ensure_active()
                self.events.step(step, self.settings.max_steps)
                with self.events.thinking(
                    f"Mirsad is thinking - step {step}/{self.settings.max_steps}"
                ):
                    turn = self.provider.chat(
                        self._build_messages(),
                        tools=self.registry.specs(),
                        temperature=self.settings.temperature,
                    )

                calls = self._record_assistant(turn, step)
                self._save()

                if turn.content and calls:
                    self.events.assistant(turn.content)

                if not calls:
                    answer = (turn.content or "").strip()
                    return answer or "(The model returned an empty response.)"

                for call_id, call in calls:
                    self._ensure_active()
                    self.events.tool_call(call.name, call.arguments, call_id)
                    result = self.registry.execute(
                        call.name,
                        call.arguments,
                        approve=self._approve,
                    )
                    self.events.tool_result(call.name, result, call_id)
                    self.session.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": call.name,
                            "content": result,
                        }
                    )
                    self._save()

            return self._finish_after_step_limit()
        except BaseException:
            self._close_pending_tool_calls()
            self._save()
            raise

    def set_workdir(self, path: str | Path) -> Path:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a directory: {resolved}")
        self.settings.workdir = resolved
        self.session.workdir = str(resolved)
        self.registry = self._build_registry()
        self._save()
        return resolved

    def set_provider(self, provider: BaseProvider, provider_id: str) -> None:
        self.provider = provider
        self.settings.provider = provider_id
        self.session.provider = provider_id
        self.session.model = provider.model
        self._save()

    def set_auto_approve(self, enabled: bool) -> None:
        self.settings.auto_approve = enabled
        self._save()

    def clear(self) -> None:
        self.session.messages.clear()
        self.session.plan.clear()
        self.plan.clear()
        self._save()

    def save(self) -> None:
        self._save()

    # ── internals ───────────────────────────────────────────────────────

    def _build_registry(self) -> ToolRegistry:
        return build_registry(self.settings.workdir, plan_callback=self._set_plan)

    def _build_messages(self, notice: str | None = None) -> list[dict[str, Any]]:
        system = build_system_prompt(
            workdir=self.settings.workdir,
            provider=self.settings.provider,
            model=self.provider.model,
            plan=self.plan,
            auto_approve=self.settings.auto_approve,
            max_steps=self.settings.max_steps,
        )
        if notice:
            system += "\n\n## Notice\n" + notice

        history = context_messages(self.session.messages, self.settings.max_history)
        return [{"role": "system", "content": system}, *history]

    def _record_assistant(
        self, turn: AssistantTurn, step: int
    ) -> list[tuple[str, ToolCall]]:
        """Append a normalized assistant message and return unique tool calls."""

        used_ids: set[str] = set()
        calls: list[tuple[str, ToolCall]] = []
        serialized_calls: list[dict[str, Any]] = []

        for index, call in enumerate(turn.tool_calls):
            base_id = call.id or f"call_{step}_{index}"
            call_id = base_id
            suffix = 1
            while call_id in used_ids:
                call_id = f"{base_id}_{suffix}"
                suffix += 1
            used_ids.add(call_id)
            calls.append((call_id, call))

            serialized_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
            )

        message: dict[str, Any] = {
            "role": "assistant",
            "content": (
                turn.content if turn.content else (None if serialized_calls else "")
            ),
        }
        if serialized_calls:
            message["tool_calls"] = serialized_calls
        self.session.messages.append(message)
        return calls

    def _set_plan(self, steps: list[str], note: str = "") -> str:
        self.plan = list(steps)
        self.session.plan = list(steps)
        self._save()
        self.events.plan(self.plan, note)
        return f"Plan updated with {len(self.plan)} step(s)."

    def _ensure_active(self) -> None:
        if self.cancel_check is None or not self.cancel_check():
            return
        self._close_pending_tool_calls()
        self._save()
        raise AgentCancelled("Run stopped by the user.")

    def _close_pending_tool_calls(self) -> None:
        """Add synthetic results so an interrupted turn remains valid history."""

        assistant_index: int | None = None
        for index in range(len(self.session.messages) - 1, -1, -1):
            message = self.session.messages[index]
            if message.get("role") == "assistant" and message.get("tool_calls"):
                assistant_index = index
                break
        if assistant_index is None:
            return

        pending: dict[str, str] = {}
        for call in self.session.messages[assistant_index].get("tool_calls") or []:
            call_id = str(call.get("id") or "")
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            if call_id:
                pending[call_id] = name

        for message in self.session.messages[assistant_index + 1 :]:
            if message.get("role") == "tool":
                pending.pop(str(message.get("tool_call_id") or ""), None)

        for call_id, name in pending.items():
            self.session.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": "Tool execution was interrupted before it completed.",
                }
            )

    def _approve(self, tool: Tool, arguments: dict[str, Any]) -> bool:
        if self.settings.auto_approve:
            return True
        if self.approval is None:
            return False
        return bool(self.approval(tool, arguments))

    def _finish_after_step_limit(self) -> str:
        self._ensure_active()
        with self.events.thinking("Preparing a summary"):
            turn = self.provider.chat(
                self._build_messages(notice=STEP_LIMIT_NOTICE),
                tools=None,
                temperature=self.settings.temperature,
            )

        content = (turn.content or "").strip()
        if content:
            self.session.messages.append({"role": "assistant", "content": content})
            self._save()

        if content:
            return f"Reached the step limit ({self.settings.max_steps}).\n\n{content}"
        return (
            f"Reached the step limit ({self.settings.max_steps}) without a final "
            "answer. Review the plan and continue with a narrower request."
        )

    def _save(self) -> None:
        self.store.save(self.session)

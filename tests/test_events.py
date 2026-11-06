from __future__ import annotations

from pathlib import Path

import pytest

from mirsad.agent import Agent, AgentCancelled
from mirsad.config import Settings
from mirsad.events import AgentEvents
from mirsad.memory import SessionStore
from mirsad.providers.base import AssistantTurn, ToolCall


class FakeProvider:
    name = "Fake"
    model = "fake-1"

    def __init__(self, turns: list[AssistantTurn]) -> None:
        self.turns = list(turns)

    def chat(self, messages, tools=None, temperature=0.2):
        if not self.turns:
            return AssistantTurn(content="done")
        return self.turns.pop(0)


class RecordingEvents(AgentEvents):
    def __init__(self) -> None:
        self.thinking_labels: list[str] = []
        self.steps: list[tuple[int, int]] = []
        self.assistant_messages: list[str] = []
        self.tool_calls: list[tuple[str, dict, str]] = []
        self.tool_results: list[tuple[str, str, str]] = []
        self.plans: list[tuple[list[str], str]] = []

    def thinking(self, label: str):
        self.thinking_labels.append(label)

        class Scope:
            def __enter__(self_inner):
                return None

            def __exit__(self_inner, *exc):
                return False

        return Scope()

    def step(self, step: int, total: int) -> None:
        self.steps.append((step, total))

    def assistant(self, text: str) -> None:
        self.assistant_messages.append(text)

    def tool_call(self, name, arguments, call_id="") -> None:
        self.tool_calls.append((name, arguments, call_id))

    def tool_result(self, name, result, call_id="") -> None:
        self.tool_results.append((name, result, call_id))

    def plan(self, steps, note="") -> None:
        self.plans.append((list(steps), note))


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        provider="openai",
        model="fake-1",
        temperature=0.2,
        max_steps=5,
        max_history=80,
        auto_approve=True,
        workdir=tmp_path,
    )


def _agent(tmp_path, provider, events=None, cancel_check=None) -> Agent:
    store = SessionStore(tmp_path / "sessions")
    session = store.new("openai", "fake-1", tmp_path)
    store.save(session)
    return Agent(
        settings=_settings(tmp_path),
        provider=provider,
        session=session,
        store=store,
        events=events,
        cancel_check=cancel_check,
    )


def test_default_events_are_noops():
    events = AgentEvents()
    with events.thinking("label"):
        pass
    events.step(1, 2)
    events.assistant("text")
    events.tool_call("read_file", {"path": "x"}, "id")
    events.tool_result("read_file", "ok", "id")
    events.plan(["one"], "note")


def test_agent_emits_events_for_plan_and_tools(tmp_path):
    provider = FakeProvider(
        [
            AssistantTurn(
                tool_calls=[
                    ToolCall(
                        id="call_plan",
                        name="update_plan",
                        arguments={"steps": ["Inspect", "Answer"], "note": "first"},
                    )
                ]
            ),
            AssistantTurn(content="The answer."),
        ]
    )
    events = RecordingEvents()
    agent = _agent(tmp_path, provider, events)

    answer = agent.run_turn("Explain the project")

    assert answer == "The answer."
    assert events.steps == [(1, 5), (2, 5)]
    assert events.thinking_labels == [
        "Mirsad is thinking - step 1/5",
        "Mirsad is thinking - step 2/5",
    ]
    assert events.plans == [(["Inspect", "Answer"], "first")]
    assert events.tool_calls[0][:2] == (
        "update_plan",
        {"steps": ["Inspect", "Answer"], "note": "first"},
    )
    assert events.tool_results[0][0] == "update_plan"


def test_agent_cancellation_closes_pending_tool_calls(tmp_path):
    cancelled = {"value": False}

    class CancellingProvider:
        name = "Fake"
        model = "fake-1"

        def chat(self, messages, tools=None, temperature=0.2):
            cancelled["value"] = True
            return AssistantTurn(
                tool_calls=[
                    ToolCall(
                        id="call_write",
                        name="write_file",
                        arguments={"path": "never.txt", "content": "x"},
                    )
                ]
            )

    agent = _agent(
        tmp_path,
        CancellingProvider(),
        cancel_check=lambda: cancelled["value"],
    )

    with pytest.raises(AgentCancelled):
        agent.run_turn("Do work")

    assert not (tmp_path / "never.txt").exists()
    roles = [message["role"] for message in agent.session.messages]
    assert roles == ["user", "assistant", "tool"]
    assert "interrupted" in agent.session.messages[-1]["content"].lower()

    reloaded = agent.store.load(agent.session.id)
    assert reloaded.messages[-1]["role"] == "tool"
    assert "interrupted" in reloaded.messages[-1]["content"].lower()

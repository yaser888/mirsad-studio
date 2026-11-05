from __future__ import annotations

from pathlib import Path

import pytest

from hermes.agent import Agent
from hermes.config import Settings
from hermes.memory import SessionStore
from hermes.providers.base import AssistantTurn, ToolCall


class FakeProvider:
    name = "Fake"
    model = "fake-1"

    def __init__(self, turns: list[AssistantTurn]) -> None:
        self.turns = list(turns)
        self.calls: list[dict] = []

    def chat(self, messages, tools=None, temperature=0.2):
        self.calls.append({"messages": messages, "tools": tools})
        if not self.turns:
            return AssistantTurn(content="done")
        return self.turns.pop(0)


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "provider": "openai",
        "model": "fake-1",
        "temperature": 0.2,
        "max_steps": 5,
        "max_history": 80,
        "auto_approve": True,
        "workdir": tmp_path,
    }
    values.update(overrides)
    return Settings(**values)


def test_agent_runs_plan_write_and_finishes(tmp_path):
    provider = FakeProvider(
        [
            AssistantTurn(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_plan",
                        name="update_plan",
                        arguments={"steps": ["Inspect", "Write file"]},
                    )
                ],
            ),
            AssistantTurn(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_write",
                        name="write_file",
                        arguments={"path": "hello.txt", "content": "hello hermes\n"},
                    )
                ],
            ),
            AssistantTurn(content="All done."),
        ]
    )
    store = SessionStore(tmp_path / "sessions")
    session = store.new("openai", "fake-1", tmp_path)
    store.save(session)
    agent = Agent(
        settings=_settings(tmp_path),
        provider=provider,
        session=session,
        store=store,
    )

    answer = agent.run_turn("Create hello.txt")

    assert answer == "All done."
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello hermes\n"
    assert agent.plan == ["Inspect", "Write file"]
    assert agent.session.plan == ["Inspect", "Write file"]

    tool_names = {spec["function"]["name"] for spec in provider.calls[0]["tools"]}
    assert {"update_plan", "write_file", "read_file", "run_command"} <= tool_names
    assert "Workspace:" in provider.calls[0]["messages"][0]["content"]

    roles = [message["role"] for message in session.messages]
    assert roles == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert session.messages[-1]["content"] == "All done."

    reloaded = store.load(session.id)
    assert reloaded.plan == ["Inspect", "Write file"]
    assert reloaded.messages[-1]["content"] == "All done."


def test_agent_respects_step_limit(tmp_path):
    provider = FakeProvider(
        [
            AssistantTurn(
                tool_calls=[
                    ToolCall(
                        id="call_plan",
                        name="update_plan",
                        arguments={"steps": ["step"]},
                    )
                ]
            ),
            AssistantTurn(content="Summary after the limit."),
        ]
    )
    store = SessionStore(tmp_path / "sessions")
    session = store.new("openai", "fake-1", tmp_path)
    store.save(session)
    agent = Agent(
        settings=_settings(tmp_path, max_steps=1),
        provider=provider,
        session=session,
        store=store,
    )

    answer = agent.run_turn("Do something")

    assert answer.startswith("Reached the step limit (1)")
    assert "Summary after the limit." in answer
    # The final summarization call must not offer tools.
    assert provider.calls[-1]["tools"] is None


def test_agent_denies_unapproved_write(tmp_path):
    provider = FakeProvider(
        [
            AssistantTurn(
                tool_calls=[
                    ToolCall(
                        id="call_write",
                        name="write_file",
                        arguments={"path": "nope.txt", "content": "x"},
                    )
                ]
            ),
            AssistantTurn(content="The write was denied."),
        ]
    )
    store = SessionStore(tmp_path / "sessions")
    session = store.new("openai", "fake-1", tmp_path)
    store.save(session)
    agent = Agent(
        settings=_settings(tmp_path, auto_approve=False),
        provider=provider,
        session=session,
        store=store,
        approval=lambda tool, arguments: False,
    )

    answer = agent.run_turn("Write a file")

    assert answer == "The write was denied."
    assert not (tmp_path / "nope.txt").exists()
    tool_message = next(
        message for message in session.messages if message["role"] == "tool"
    )
    assert "denied" in tool_message["content"].lower()


def test_agent_closes_tool_calls_on_interrupt(tmp_path):
    provider = FakeProvider(
        [
            AssistantTurn(
                tool_calls=[
                    ToolCall(
                        id="call_write",
                        name="write_file",
                        arguments={"path": "x.txt", "content": "x"},
                    )
                ]
            )
        ]
    )
    store = SessionStore(tmp_path / "sessions")
    session = store.new("openai", "fake-1", tmp_path)
    store.save(session)

    def interrupt(tool, arguments):
        raise KeyboardInterrupt

    agent = Agent(
        settings=_settings(tmp_path, auto_approve=False),
        provider=provider,
        session=session,
        store=store,
        approval=interrupt,
    )

    with pytest.raises(KeyboardInterrupt):
        agent.run_turn("Write a file")

    assert [message["role"] for message in session.messages] == [
        "user",
        "assistant",
        "tool",
    ]
    assert "interrupted" in session.messages[-1]["content"].lower()
    reloaded = store.load(session.id)
    assert reloaded.messages[-1]["role"] == "tool"

from __future__ import annotations

import pytest

from mirsad.memory import SessionStore, context_messages


def test_session_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    session = store.new("openai", "gpt-test", tmp_path)
    session.messages.append({"role": "user", "content": "مرحبا"})
    session.plan = ["step one"]
    path = store.save(session)

    assert path.is_file()
    assert session.id in {item["id"] for item in store.list()}

    loaded = store.load(session.id)
    assert loaded.messages[0]["content"] == "مرحبا"
    assert loaded.plan == ["step one"]
    assert loaded.provider == "openai"
    assert store.exists(session.id)

    summaries = store.list()
    assert summaries[0]["messages"] == 1
    assert summaries[0]["preview"] == "مرحبا"

    assert store.delete(session.id) is True
    assert store.exists(session.id) is False
    assert store.delete(session.id) is False


def test_invalid_session_id(tmp_path):
    store = SessionStore(tmp_path)
    with pytest.raises(ValueError):
        store.load("../../etc/passwd")


def test_missing_session(tmp_path):
    store = SessionStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.load("missing-id")


def test_context_messages_keeps_tool_groups():
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "a"},
        {"role": "tool", "tool_call_id": "2", "content": "b"},
        {"role": "tool", "tool_call_id": "3", "content": "c"},
        {"role": "user", "content": "next"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "last"},
    ]

    trimmed = context_messages(messages, max_messages=3)

    assert trimmed[0]["role"] == "user"
    assert trimmed[0]["content"] == "next"
    assert [message["role"] for message in trimmed] == [
        "user",
        "assistant",
        "user",
    ]


def test_context_messages_keeps_tool_call_with_results():
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "a"},
        {"role": "tool", "tool_call_id": "2", "content": "b"},
        {"role": "tool", "tool_call_id": "3", "content": "c"},
        {"role": "user", "content": "next"},
    ]

    trimmed = context_messages(messages, max_messages=2)

    assert [message["role"] for message in trimmed] == [
        "user",
        "assistant",
        "tool",
        "tool",
        "tool",
        "user",
    ]


def test_context_messages_no_change_when_short():
    messages = [{"role": "user", "content": "hi"}]
    assert context_messages(messages, max_messages=10) == messages

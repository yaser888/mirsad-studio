from __future__ import annotations

import pytest

from mirsad.config import ConfigError, Settings
from mirsad.providers.anthropic import AnthropicProvider, convert_messages
from mirsad.providers.base import MissingAPIKey
from mirsad.providers.factory import (
    create_provider,
    key_status,
    resolve_model,
    resolve_spec,
)
from mirsad.providers.openai_compat import OpenAICompatibleProvider


def test_openai_parse_tool_calls():
    provider = OpenAICompatibleProvider(
        name="Test", model="test-model", base_url="https://example.invalid/v1"
    )
    data = {
        "choices": [
            {
                "message": {
                    "content": "working",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path": "main.py"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }

    turn = provider.parse_response(data)
    assert turn.content == "working"
    assert turn.finish_reason == "tool_calls"
    assert turn.tool_calls[0].id == "call_1"
    assert turn.tool_calls[0].name == "read_file"
    assert turn.tool_calls[0].arguments == {"path": "main.py"}


def test_openai_parse_rejects_bad_arguments():
    provider = OpenAICompatibleProvider(
        name="Test", model="test-model", base_url="https://example.invalid/v1"
    )
    data = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "f", "arguments": "{not json"},
                        }
                    ],
                }
            }
        ]
    }
    turn = provider.parse_response(data)
    assert turn.tool_calls[0].arguments == {"_raw_arguments": "{not json"}


def test_anthropic_message_conversion_groups_tool_results():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "read it"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "read_file",
            "content": "ok",
        },
        {
            "role": "tool",
            "tool_call_id": "call_2",
            "name": "read_file",
            "content": "two",
        },
    ]

    system, converted = convert_messages(messages)

    assert system == ["You are helpful."]
    assert [message["role"] for message in converted] == ["user", "assistant", "user"]
    assert converted[1]["content"][0]["type"] == "tool_use"
    assert converted[1]["content"][0]["input"] == {"path": "a.txt"}
    assert [block["type"] for block in converted[2]["content"]] == [
        "tool_result",
        "tool_result",
    ]
    assert converted[2]["content"][0]["tool_use_id"] == "call_1"


def test_anthropic_parse_response():
    provider = AnthropicProvider(model="claude-test", api_key="x")
    data = {
        "content": [
            {"type": "text", "text": "Here is the plan."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "update_plan",
                "input": {"steps": ["one"]},
            },
        ],
        "stop_reason": "tool_use",
    }

    turn = provider.parse_response(data)
    assert turn.content == "Here is the plan."
    assert turn.tool_calls[0].id == "toolu_1"
    assert turn.tool_calls[0].arguments == {"steps": ["one"]}


def test_factory_requires_key(monkeypatch, tmp_path):
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "MIRSAD_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(provider="openai", workdir=tmp_path)
    with pytest.raises(MissingAPIKey):
        create_provider(settings)


def test_factory_ollama_needs_no_key(monkeypatch, tmp_path):
    monkeypatch.delenv("MIRSAD_API_KEY", raising=False)
    monkeypatch.delenv("MIRSAD_BASE_URL", raising=False)
    settings = Settings(provider="ollama", workdir=tmp_path, model="qwen-test")

    provider = create_provider(settings)

    assert provider.model == "qwen-test"
    assert provider.base_url == "http://localhost:11434/v1"


def test_factory_unknown_provider(tmp_path):
    settings = Settings(provider="no-such-provider", workdir=tmp_path)
    with pytest.raises(ConfigError):
        create_provider(settings)


def test_factory_gemini_uses_free_tier_default(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    settings = Settings(provider="gemini", workdir=tmp_path)

    spec = resolve_spec(settings)
    assert spec.env_key == "GEMINI_API_KEY"
    assert spec.default_model == "gemini-2.0-flash"
    assert spec.requires_key is True

    provider = create_provider(settings)
    assert provider.model == "gemini-2.0-flash"
    assert (
        provider.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    )


def test_factory_huggingface_requires_key(monkeypatch, tmp_path):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    settings = Settings(provider="huggingface", workdir=tmp_path)
    with pytest.raises(MissingAPIKey):
        create_provider(settings)


def test_key_status_lists_catalog_providers():
    statuses = {spec.id: has_key for spec, has_key in key_status()}
    assert set(statuses) == {
        "openai",
        "anthropic",
        "openrouter",
        "deepseek",
        "groq",
        "gemini",
        "huggingface",
        "ollama",
    }


def test_resolve_default_model(monkeypatch):
    monkeypatch.delenv("MIRSAD_MODEL", raising=False)
    settings = Settings(provider="deepseek")
    spec = resolve_spec(settings)
    assert resolve_model(settings, spec) == "deepseek-chat"

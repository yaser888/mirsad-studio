from __future__ import annotations

import json

from hermes import cli
from hermes.config import Settings
from hermes.providers.base import AssistantTurn


class FakeProvider:
    name = "Fake"
    model = "fake-1"

    def chat(self, messages, tools=None, temperature=0.2):
        return AssistantTurn(content="The answer.")


def test_ask_json_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "bootstrap_env", lambda: None)
    monkeypatch.setattr(cli, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda **kwargs: Settings(
            provider="openai",
            model="fake-1",
            workdir=tmp_path,
            auto_approve=True,
        ),
    )
    monkeypatch.setattr(cli, "create_provider", lambda settings: FakeProvider())

    exit_code = cli.main(["ask", "hello", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["answer"] == "The answer."
    assert payload["provider"] == "openai"
    assert payload["model"] == "fake-1"
    assert (tmp_path / "sessions" / f"{payload['session_id']}.json").is_file()


def test_sessions_list_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "bootstrap_env", lambda: None)
    monkeypatch.setattr(cli, "SESSIONS_DIR", tmp_path / "sessions")

    assert cli.main(["sessions", "list"]) == 0

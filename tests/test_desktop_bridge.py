from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("PySide6")

from mirsad.config import Settings
from mirsad.desktop import bridge as bridge_module
from mirsad.providers.base import MissingAPIKey
from mirsad.security import AuditLog, SecretVault


@pytest.fixture
def studio(tmp_path, monkeypatch):
    settings = Settings(
        provider="openai",
        model=None,
        temperature=0.2,
        max_steps=12,
        max_history=80,
        auto_approve=False,
        workdir=tmp_path,
    )
    monkeypatch.setattr(bridge_module, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(bridge_module, "AUDIT_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(bridge_module, "VAULT_FILE", tmp_path / "vault.dat")
    monkeypatch.setattr(bridge_module, "read_config_file", dict)
    monkeypatch.setattr(bridge_module, "load_settings", lambda **kwargs: settings)
    monkeypatch.setattr(bridge_module, "save_settings", lambda value: None)
    monkeypatch.setattr(bridge_module, "bootstrap_env", lambda: None)
    for name in ("OPENAI_API_KEY", "MIRSAD_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    bridge = bridge_module.StudioBridge()
    yield bridge, tmp_path, settings
    bridge.shutdown()


def _payload(raw: str) -> dict:
    return json.loads(raw)


def test_bridge_bootstrap_and_session_lifecycle(studio):
    bridge, tmp_path, _settings = studio

    boot = _payload(bridge.bootstrap())
    assert boot["ok"]
    state = boot["state"]
    assert state["app"] == "Mirsad Studio"
    assert state["version"] == "0.2.0"
    assert state["audit"]["ok"]
    assert state["audit"]["entries"] == 1
    assert state["sessions"] == []
    assert state["workspace"] == str(tmp_path)

    created = _payload(bridge.new_session())
    assert created["ok"]
    session_id = created["session"]["id"]
    assert created["session"]["messages"] == []

    sessions = bridge._sessions()
    assert [item["id"] for item in sessions] == [session_id]

    loaded = _payload(bridge.load_session(session_id))
    assert loaded["ok"]
    assert loaded["session"]["id"] == session_id

    deleted = _payload(bridge.delete_session(session_id))
    assert deleted["ok"]
    assert bridge._sessions() == []

    check = AuditLog(tmp_path / "audit.jsonl").verify()
    assert check.ok
    assert check.entries == 4


def test_bridge_settings_validation_and_persistence(studio):
    bridge, tmp_path, settings = studio

    invalid = _payload(bridge.save_settings(json.dumps({"provider": "not-a-provider"})))
    assert not invalid["ok"]
    assert "unknown provider" in invalid["error"].lower()

    saved = _payload(
        bridge.save_settings(
            json.dumps(
                {
                    "provider": "openai",
                    "model": "test-model",
                    "temperature": 0.3,
                    "max_steps": 7,
                    "max_history": 20,
                    "auto_approve": True,
                    "workdir": str(tmp_path),
                }
            )
        )
    )
    assert saved["ok"]
    assert settings.model == "test-model"
    assert settings.max_steps == 7
    assert settings.auto_approve is True
    assert saved["state"]["settings"]["max_steps"] == 7


def test_bridge_api_key_is_masked_and_audited(studio):
    bridge, tmp_path, _settings = studio
    vault = SecretVault(tmp_path / "vault.dat")
    if not vault.available:
        pytest.skip("Windows DPAPI is not available on this platform.")

    key = "sk-proj-" + "k" * 28
    saved = _payload(bridge.save_api_key("openai", key))
    assert saved["ok"]
    secrets = saved["state"]["vault"]["secrets"]
    assert secrets == [{"name": "OPENAI_API_KEY", "value": "set (****kkkk)"}]

    assert key not in json.dumps(saved)
    assert key not in (tmp_path / "vault.dat").read_text(encoding="utf-8")
    assert key not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert vault.get("OPENAI_API_KEY") == key

    removed = _payload(bridge.remove_api_key("openai"))
    assert removed["ok"]
    assert removed["state"]["vault"]["count"] == 0
    assert os.environ.get("OPENAI_API_KEY") is None
    assert vault.get("OPENAI_API_KEY") is None


def test_bridge_reports_missing_provider_key(studio, monkeypatch):
    bridge, _tmp_path, _settings = studio

    def fail(_settings):
        raise MissingAPIKey("No API key configured for this provider.")

    monkeypatch.setattr(bridge_module, "create_provider", fail)
    response = _payload(bridge.send_message("hello"))
    assert not response["ok"]
    assert "api key" in response["error"].lower()


def test_session_payload_redacts_credentials(studio):
    bridge, _tmp_path, _settings = studio
    session = bridge._store.new("openai", "fake-1", bridge._settings.workdir)
    session.messages.append(
        {
            "role": "user",
            "content": "Use sk-proj-" + "z" * 32 + " to call the API.",
        }
    )
    bridge._store.save(session)

    payload = bridge_module._session_payload(session)
    serialized = json.dumps(payload)
    assert "sk-proj-" not in serialized
    assert "[REDACTED]" in serialized
    assert payload["title"].startswith("Use [REDACTED]")

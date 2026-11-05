from __future__ import annotations

import json
from pathlib import Path

import pytest

from mirsad import config
from mirsad.config import load_dotenv, load_settings


def test_load_dotenv_parses_and_does_not_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nFOO=bar\nexport BAZ='qux'\nEMPTY=\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAZ", raising=False)
    monkeypatch.delenv("EMPTY", raising=False)

    load_dotenv(env_file)
    assert config.os.environ["FOO"] == "bar"
    assert config.os.environ["BAZ"] == "qux"
    assert config.os.environ["EMPTY"] == ""

    monkeypatch.setenv("FOO", "existing")
    load_dotenv(env_file)
    assert config.os.environ["FOO"] == "existing"


def test_settings_precedence(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "provider": "anthropic",
                "model": "claude-test",
                "temperature": 0.4,
                "max_steps": 5,
                "max_history": 30,
                "auto_approve": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)
    monkeypatch.setenv("MIRSAD_PROVIDER", "groq")
    monkeypatch.setenv("MIRSAD_MAX_STEPS", "7")
    monkeypatch.delenv("MIRSAD_MODEL", raising=False)
    monkeypatch.delenv("MIRSAD_AUTO_APPROVE", raising=False)

    settings = load_settings(provider="ollama", workdir=tmp_path)

    assert settings.provider == "ollama"  # explicit argument wins
    assert settings.model == "claude-test"  # config file model
    assert settings.temperature == 0.4
    assert settings.max_steps == 7  # environment overrides config.json
    assert settings.max_history == 30


def test_settings_explicit_max_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.json")
    monkeypatch.delenv("MIRSAD_MAX_STEPS", raising=False)

    settings = load_settings(workdir=tmp_path, max_steps=9, auto_approve=True)

    assert settings.max_steps == 9
    assert settings.auto_approve is True


def test_init_app_creates_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "app" / "config.json")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "app" / ".env")
    monkeypatch.setattr(config, "SESSIONS_DIR", tmp_path / "app" / "sessions")

    messages = config.init_app()
    assert (tmp_path / "app" / "config.json").is_file()
    assert (tmp_path / "app" / ".env").is_file()
    assert (tmp_path / "app" / "sessions").is_dir()
    assert any("Created config" in message for message in messages)

    # A second run must not overwrite by default.
    config_file = tmp_path / "app" / "config.json"
    config_file.write_text('{"provider": "custom"}\n', encoding="utf-8")
    messages = config.init_app()
    assert config_file.read_text(encoding="utf-8") == '{"provider": "custom"}\n'
    assert any("already exists" in message for message in messages)


def test_init_force_never_wipes_env_keys(tmp_path, monkeypatch):
    app = tmp_path / "app"
    monkeypatch.setattr(config, "APP_DIR", app)
    monkeypatch.setattr(config, "CONFIG_FILE", app / "config.json")
    monkeypatch.setattr(config, "ENV_FILE", app / ".env")
    monkeypatch.setattr(config, "SESSIONS_DIR", app / "sessions")

    config.init_app()
    env_file = app / ".env"
    env_file.write_text("OPENAI_API_KEY=super-secret\n", encoding="utf-8")

    config.init_app(force=True)

    assert env_file.read_text(encoding="utf-8") == "OPENAI_API_KEY=super-secret\n"


def test_invalid_workdir():
    with pytest.raises(config.ConfigError):
        load_settings(workdir=Path("definitely-not-a-real-directory-xyz"))

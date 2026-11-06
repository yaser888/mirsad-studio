from __future__ import annotations

from pathlib import Path

import pytest

from mirsad import cli
from mirsad.security import AuditLog


@pytest.fixture()
def doctor_env(tmp_path, monkeypatch):
    home = tmp_path / ".mirsad"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    monkeypatch.setattr(cli, "bootstrap_env", lambda: None)
    monkeypatch.setattr(cli, "APP_DIR", home)
    monkeypatch.setattr(cli, "CONFIG_FILE", home / "config.json")
    monkeypatch.setattr(cli, "ENV_FILE", home / ".env")
    monkeypatch.setattr(cli, "SESSIONS_DIR", sessions)
    monkeypatch.setattr(cli, "AUDIT_FILE", home / "audit.jsonl")
    monkeypatch.setattr(cli, "VAULT_FILE", home / "vault.dat")
    return home


def test_doctor_command_is_exposed():
    args = cli.build_parser().parse_args(["doctor"])
    assert args.command == "doctor"


def test_doctor_passes_on_healthy_environment(doctor_env, capsys):
    assert cli.main(["doctor"]) == 0


def test_doctor_fails_on_broken_audit_chain(doctor_env):
    audit_file = Path(doctor_env) / "audit.jsonl"
    log = AuditLog(audit_file)
    log.record("test.event", note="integrity")
    broken = audit_file.read_text(encoding="utf-8").replace('"event"', '"attacker"', 1)
    audit_file.write_text(broken, encoding="utf-8")

    assert cli.main(["doctor"]) == 1


def test_doctor_warns_when_home_missing(doctor_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "APP_DIR", Path(doctor_env) / "missing")
    assert cli.main(["doctor"]) == 0

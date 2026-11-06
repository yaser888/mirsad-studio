from __future__ import annotations

import json

import pytest

from mirsad import cli
from mirsad.security import AuditLog


@pytest.fixture()
def audit(tmp_path, monkeypatch):
    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(cli, "AUDIT_FILE", audit_file)
    monkeypatch.setattr(cli, "bootstrap_env", lambda: None)
    return audit_file


def test_audit_verify_reports_entry_count(audit, capsys):
    log = AuditLog(audit)
    log.record("tool.requested", tool="write_file", path="a.txt")
    log.record("run.finished", session="s-1", steps=1)

    assert cli.main(["audit", "verify"]) == 0


def test_audit_tail_shows_recent_entries(audit, capsys):
    log = AuditLog(audit)
    log.record("studio.opened", version="0.2.0")
    log.record("run.started", session="abc")

    assert cli.main(["audit", "tail"]) == 0


def test_audit_export_markdown_to_file(audit, tmp_path):
    log = AuditLog(audit)
    log.record("studio.opened", version="0.2.0")
    output = tmp_path / "trail.md"

    assert cli.main(["audit", "export", "--format", "markdown", "-o", str(output)]) == 0

    content = output.read_text(encoding="utf-8")
    assert "Mirsad audit trail" in content
    assert "studio.opened" in content
    assert output.read_text(encoding="utf-8").count("hash:") == 1


def test_audit_export_json_to_stdout(audit, capsys):
    log = AuditLog(audit)
    log.record("run.finished", session="s-1", steps=2)

    assert cli.main(["audit", "export", "--format", "json"]) == 0
    entries = json.loads(capsys.readouterr().out)
    assert entries[-1]["event"] == "run.finished"

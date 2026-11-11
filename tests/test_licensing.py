from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from mirsad import cli
from mirsad.licensing import (
    DEFAULT_SECRET,
    LicenseError,
    issue_token,
    load_license,
    save_license,
    verify_token,
)


def _manual_token(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload_b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    digest = hmac.new(
        DEFAULT_SECRET.encode(), payload_b64.encode(), hashlib.sha256
    ).digest()
    sig = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return f"MIRSAD1.{payload_b64}.{sig}"


def test_issue_and_verify_roundtrip():
    token = issue_token(plan="team", licensed_to="Yaser AI Studio", seats=3, days=30)
    info = verify_token(token)

    assert info.plan == "team"
    assert info.licensed_to == "Yaser AI Studio"
    assert info.seats == 3
    assert info.is_pro
    assert info.expires_label != "lifetime"


def test_verify_rejects_tampered_signature():
    token = issue_token(plan="pro", licensed_to="Yaser", seats=1, days=30)
    bad = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1:]

    with pytest.raises(LicenseError):
        verify_token(bad)


def test_verify_rejects_expired_token():
    token = _manual_token(
        {
            "plan": "pro",
            "licensed_to": "Yaser",
            "seats": 1,
            "exp": int(time.time()) - 3600,
        }
    )

    with pytest.raises(LicenseError):
        verify_token(token)


def test_load_license_missing_file_returns_community(tmp_path):
    info = load_license(tmp_path / "license.json")

    assert info.plan == "community"
    assert not info.is_pro


def test_save_license_persists_verified_token(tmp_path):
    license_file = tmp_path / "license.json"
    token = issue_token(plan="pro", licensed_to="Yaser", seats=1, days=30)

    info = save_license(token, license_file)

    assert info.plan == "pro"
    assert load_license(license_file).plan == "pro"


def test_license_issue_prints_token(capsys, monkeypatch):
    monkeypatch.setattr(cli, "bootstrap_env", lambda: None)

    assert (
        cli.main(["license", "issue", "--plan", "pro", "--to", "Test", "--days", "1"])
        == 0
    )
    assert capsys.readouterr().out.strip().startswith("MIRSAD1.")


def test_activate_and_report_flow(tmp_path, monkeypatch):
    license_file = tmp_path / "license.json"
    monkeypatch.setattr(cli, "LICENSE_FILE", license_file)
    monkeypatch.setattr(cli, "bootstrap_env", lambda: None)
    monkeypatch.setattr(cli, "AUDIT_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(cli, "SESSIONS_DIR", tmp_path / "sessions")
    (tmp_path / "sessions").mkdir()

    import mirsad.report as report_module

    monkeypatch.setattr(report_module.config, "AUDIT_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(report_module.config, "SESSIONS_DIR", tmp_path / "sessions")

    token = issue_token(plan="pro", licensed_to="Yaser", seats=1, days=30)
    assert cli.main(["activate", "--key", token]) == 0

    output = tmp_path / "report.html"
    assert cli.main(["report", "-o", str(output)]) == 0
    content = output.read_text(encoding="utf-8")
    assert "Compliance evidence pack" in content
    assert "PRO" in content


def test_report_requires_license(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "LICENSE_FILE", tmp_path / "license.json")
    monkeypatch.setattr(cli, "bootstrap_env", lambda: None)

    assert cli.main(["report", "-o", str(tmp_path / "report.html")]) == 3

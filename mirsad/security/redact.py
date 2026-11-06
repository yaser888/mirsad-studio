"""Secret redaction for logs and diagnostics."""

from __future__ import annotations

import re
from typing import Any

_PATTERNS = [
    re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgsk_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bor-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*"
        r"['\"]?[^\s'\"<>]{8,}"
    ),
]


def redact(text: str) -> str:
    """Replace likely credentials with a stable marker."""

    if not text:
        return text
    result = text
    for pattern in _PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


_SENSITIVE_KEYS = {
    "apikey",
    "authorization",
    "clientsecret",
    "credential",
    "credentials",
    "passphrase",
    "passwd",
    "password",
    "privatekey",
    "secret",
    "token",
}


def _is_sensitive_key(key: Any) -> bool:
    """Match credential-style keys even when spelled apiKey or access_token."""

    normalized = re.sub(r"[^a-z0-9]+", "", str(key).lower())
    if not normalized:
        return False
    if normalized in _SENSITIVE_KEYS:
        return True
    return normalized.endswith(
        ("apikey", "password", "passphrase", "secret", "token", "privatekey")
    )


def redact_structure(value: Any) -> Any:
    """Recursively redact credentials in JSON-like values.

    Detection works on both content (recognisable token formats) and context
    (keys such as ``password`` or ``apiKey``).  Redacting by key matters for
    weak or arbitrary test credentials that no value pattern would catch.
    """

    return _redact_value(value, sensitive=False)


def _redact_value(value: Any, sensitive: bool) -> Any:
    if isinstance(value, str):
        return "[REDACTED]" if sensitive and value else redact(value)
    if isinstance(value, dict):
        return {
            str(key): _redact_value(item, _is_sensitive_key(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, sensitive) for item in value]
    return value


def mask_secret(value: str | None) -> str:
    """Return a safe display string for a credential."""

    if not value:
        return "not set"
    if len(value) <= 8:
        return "set (****)"
    return f"set (****{value[-4:]})"

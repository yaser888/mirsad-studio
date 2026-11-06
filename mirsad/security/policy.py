"""Command and path policy shared by the CLI and Studio.

These checks are deliberately conservative, but they are not a sandbox. The
agent still runs with the permissions of the desktop user; approvals and the
workspace boundary are the primary controls.
"""

from __future__ import annotations

import re

# Commands refused even after approval. These target system-wide state rather
# than normal project work.
_DANGEROUS_PATTERNS = [
    re.compile(r"(?i)\brm\b[^\n]*(?:\s|^)(?:/|~|\$home|[a-z]:\\?)(?:\s|$)"),
    re.compile(r"(?i)\brm\s+-rf\s+--no-preserve-root\b"),
    re.compile(r"(?i)\bmkfs(?:\.[a-z0-9]+)?\b"),
    re.compile(r"(?i)\bformat\s+[a-z]:"),
    re.compile(r"(?i)\b(?:diskpart|clear-disk|initialize-disk|format-volume)\b"),
    re.compile(r"(?i)\b(?:shutdown|reboot|halt|poweroff)\b"),
    re.compile(r"(?i)\bremove-item\b[^\n]*\b-recurse\b[^\n]*[a-z]:\\"),
    re.compile(r"(?i)\bremove-item\b[^\n]*\b-recurse\b[^\n]*\$home"),
    re.compile(r"(?i)\bdel\s+/[fsq]\b[^\n]*[a-z]:\\"),
    re.compile(r"(?i)\b(?:rd|rmdir)\s+/s\s+/q\s+[a-z]:\\"),
    re.compile(r"(?i)\bdd\s+if=.*\bof=/dev/(?:sd|nvme|hd)"),
    re.compile(r"(?i)\b:\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:"),
    re.compile(r"(?i)\b(?:bcdedit|vssadmin\s+delete\s+shadows|wbadmin\s+delete)\b"),
    re.compile(r"(?i)\breg\s+delete\s+(?:hklm|hkey_local_machine)\b"),
    re.compile(r"(?i)\b(?:cipher\s+/w|takeown\s+/f\s+[a-z]:\\windows)\b"),
]

_SECRET_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    "credentials.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}

_SECRET_SUFFIXES = {
    ".pem",
    ".key",
    ".pfx",
    ".p12",
    ".kdbx",
    ".jks",
    ".keystore",
}

_SAFE_ENV_SUFFIXES = (".example", ".sample", ".template", ".dist")


def is_dangerous_command(command: str) -> bool:
    """Return True when a command targets catastrophic system-wide state."""

    return any(pattern.search(command or "") for pattern in _DANGEROUS_PATTERNS)


def is_secret_file(name: str) -> bool:
    """Detect files that normally contain credentials or private keys."""

    lowered = (name or "").lower()
    if not lowered:
        return False
    if lowered.startswith(".env"):
        return not lowered.endswith(_SAFE_ENV_SUFFIXES)
    if lowered in _SECRET_NAMES:
        return True
    if lowered.startswith("credentials.") and not lowered.endswith(
        (".example", ".sample", ".template")
    ):
        return True
    return any(lowered.endswith(suffix) for suffix in _SECRET_SUFFIXES)

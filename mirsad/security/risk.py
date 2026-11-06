"""Human-readable risk assessment for approval dialogs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .policy import is_secret_file
from .redact import redact

_HIGH_COMMAND = [
    (
        re.compile(
            r"(?i)\b(?:curl|wget|iwr|invoke-webrequest)\b.*\|\s*(?:sh|bash|zsh|iex|powershell)\b"
        ),
        "Downloads and executes remote code",
    ),
    (re.compile(r"(?i)\bgit\s+push\b.*(?:--force|-f)\b"), "Force-pushes Git history"),
    (
        re.compile(r"(?i)\b(?:npm|pnpm|yarn)\s+publish\b"),
        "Publishes a package publicly",
    ),
    (re.compile(r"(?i)\bpip\s+install\b"), "Changes the Python environment"),
    (
        re.compile(r"(?i)\b(?:reg\s+(?:add|delete)|schtasks|netsh|wmic)\b"),
        "Changes operating-system configuration",
    ),
    (re.compile(r"(?i)\bsudo\b|\brunas\b"), "Requests elevated privileges"),
    (
        re.compile(r"(?i)\bpowershell\b.*\s-(?:enc|encodedcommand)\b"),
        "Runs an encoded PowerShell payload",
    ),
]
_SENSITIVE_COMMAND = [
    (re.compile(r"(?i)\b(?:curl|wget|iwr|invoke-webrequest)\b"), "Uses the network"),
    (
        re.compile(r"(?i)\b(?:git\s+push|gh\s+release|docker\s+push)\b"),
        "Publishes to a remote service",
    ),
    (re.compile(r"(?i)\b(?:rm|del|erase|rd|rmdir|remove-item)\b"), "Deletes files"),
    (
        re.compile(r"(?i)\b(?:npm|pnpm|yarn|pip|uv)\s+(?:install|add|remove)\b"),
        "Modifies dependencies",
    ),
    (
        re.compile(r"(?i)\b(?:git\s+reset\s+--hard|git\s+clean)\b"),
        "Discards local changes",
    ),
    (re.compile(r"(?i)\b(?:ssh|scp|sftp)\b"), "Connects to another machine"),
    (re.compile(r"(?i)\b(?:chmod|chown|icacls|takeown)\b"), "Changes file permissions"),
]


@dataclass(frozen=True)
class RiskAssessment:
    level: str
    title: str
    reasons: tuple[str, ...]
    summary: str

    @property
    def elevated(self) -> bool:
        return self.level in {"elevated", "high"}


def assess_tool(
    name: str,
    arguments: dict[str, Any] | None,
    workdir: Path | str | None = None,
) -> RiskAssessment:
    arguments = arguments or {}
    if name == "run_command":
        return _assess_command(str(arguments.get("command") or ""))
    if name in {"write_file", "edit_file"}:
        return _assess_write(name, arguments, workdir)
    if name == "read_file":
        path = str(arguments.get("path") or "")
        if is_secret_file(Path(path).name):
            return RiskAssessment(
                "high",
                "Sensitive file",
                ("The path looks like a credential or private-key file.",),
                f"Read a protected file: {path}",
            )
    return RiskAssessment(
        "low",
        "Standard action",
        ("This tool does not modify the workspace or run a shell command.",),
        _summarize_arguments(name, arguments),
    )


def _assess_command(command: str) -> RiskAssessment:
    reasons: list[str] = []
    level = "elevated"
    for pattern, reason in _HIGH_COMMAND:
        if pattern.search(command):
            level = "high"
            reasons.append(reason)
    for pattern, reason in _SENSITIVE_COMMAND:
        if pattern.search(command):
            reasons.append(reason)
    if not reasons:
        reasons.append("This command runs with your desktop user permissions.")
    summary = redact(" ".join(command.split()))[:240]
    return RiskAssessment(
        level, "Shell command", tuple(dict.fromkeys(reasons)), summary
    )


def _assess_write(
    name: str,
    arguments: dict[str, Any],
    workdir: Path | str | None,
) -> RiskAssessment:
    path = str(arguments.get("path") or "")
    reasons: list[str] = []
    level = "elevated"
    if is_secret_file(Path(path).name):
        level = "high"
        reasons.append("The target looks like a credential or private-key file.")
    if Path(path).is_absolute():
        level = "high"
        reasons.append("The target uses an absolute path.")
    content = str(arguments.get("content") or arguments.get("new_string") or "")
    if len(content) > 80_000:
        level = "high"
        reasons.append("This is a very large file change.")
    if re.search(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]", content):
        reasons.append("The content may contain a credential.")
        if level != "high":
            level = "high"
    if not reasons:
        reasons.append("The file is inside the selected workspace.")
    action = "Overwrite" if name == "write_file" else "Edit"
    lines = content.count("\n") + (1 if content else 0)
    return RiskAssessment(
        level,
        "File write",
        tuple(dict.fromkeys(reasons)),
        f"{action} {path or '(no path)'} · {lines} line(s)",
    )


def _summarize_arguments(name: str, arguments: dict[str, Any]) -> str:
    if name == "web_fetch":
        return str(arguments.get("url") or "")
    if name == "web_search":
        return str(arguments.get("query") or "")
    if name == "read_file":
        return str(arguments.get("path") or "")
    return name

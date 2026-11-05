"""Persistent conversation sessions stored as JSON."""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Session:
    id: str
    created_at: str
    updated_at: str
    provider: str
    model: str
    workdir: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "provider": self.provider,
            "model": self.model,
            "workdir": self.workdir,
            "plan": self.plan,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        messages = data.get("messages") or []
        plan = data.get("plan") or []
        if not isinstance(messages, list):
            messages = []
        if not isinstance(plan, list):
            plan = []
        return cls(
            id=str(data.get("id") or ""),
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            provider=str(data.get("provider") or "openai"),
            model=str(data.get("model") or ""),
            workdir=str(data.get("workdir") or Path.cwd()),
            messages=[m for m in messages if isinstance(m, dict)],
            plan=[str(step) for step in plan],
        )


class SessionStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # ── paths ───────────────────────────────────────────────────────────

    def _path(self, session_id: str) -> Path:
        if not ID_PATTERN.fullmatch(session_id):
            raise ValueError(f"Invalid session id: {session_id!r}")
        return self.root / f"{session_id}.json"

    def path_for(self, session_id: str) -> Path:
        return self._path(session_id)

    # ── lifecycle ───────────────────────────────────────────────────────

    def new(self, provider: str, model: str, workdir: str | Path) -> Session:
        now = utc_now()
        session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_id = f"{session_id}-{secrets.token_hex(2)}"
        return Session(
            id=session_id,
            created_at=now,
            updated_at=now,
            provider=provider,
            model=model,
            workdir=str(workdir),
        )

    def save(self, session: Session) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(session.id)
        session.updated_at = utc_now()
        payload = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(payload + "\n", encoding="utf-8")
        os.replace(tmp_path, path)
        return path

    def load(self, session_id: str) -> Session:
        path = self._path(session_id)
        if not path.is_file():
            raise FileNotFoundError(f"Session not found: {session_id}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read session {session_id}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Session file is invalid: {path}")  # noqa: TRY004
        if not data.get("id"):
            data["id"] = session_id
        return Session.from_dict(data)

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if path.is_file():
            path.unlink()
            return True
        return False

    def exists(self, session_id: str) -> bool:
        return self._path(session_id).is_file()

    def list(self) -> list[dict[str, Any]]:
        """Return session summaries, newest first."""

        if not self.root.is_dir():
            return []
        summaries: list[dict[str, Any]] = []
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            messages = data.get("messages") or []
            preview = ""
            if isinstance(messages, list):
                for message in messages:
                    if (
                        isinstance(message, dict)
                        and message.get("role") == "user"
                        and message.get("content")
                    ):
                        preview = " ".join(str(message["content"]).split())
                        break
            summaries.append(
                {
                    "id": str(data.get("id") or path.stem),
                    "updated_at": str(data.get("updated_at") or ""),
                    "provider": str(data.get("provider") or ""),
                    "model": str(data.get("model") or ""),
                    "messages": len(messages) if isinstance(messages, list) else 0,
                    "preview": preview[:80],
                }
            )
        summaries.sort(key=lambda item: item["updated_at"], reverse=True)
        return summaries


def context_messages(
    messages: list[dict[str, Any]], max_messages: int = 80
) -> list[dict[str, Any]]:
    """Trim old history without separating tool results from their calls.

    The newest messages are kept. If the cut lands inside a run of tool
    results, we walk back to the assistant message that requested them.
    """

    if max_messages <= 0 or len(messages) <= max_messages:
        return messages

    start = len(messages) - max_messages
    while start > 0 and messages[start].get("role") == "tool":
        start -= 1
    # Anthropic requires the first turn to be a user message. Walk back to
    # the nearest user message; this can include a few extra messages.
    while start > 0 and messages[start].get("role") != "user":
        start -= 1
    return messages[start:]

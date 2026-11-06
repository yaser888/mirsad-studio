"""Qt bridge between the local Studio UI and the Mirsad agent runtime."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog

from .. import __version__
from ..agent import Agent, AgentCancelled
from ..config import (
    AUDIT_FILE,
    CONFIG_FILE,
    SESSIONS_DIR,
    VAULT_FILE,
    ConfigError,
    bootstrap_env,
    load_settings,
    read_config_file,
    save_settings,
)
from ..events import AgentEvents
from ..memory import Session, SessionStore
from ..providers import PROVIDERS
from ..providers.base import BaseProvider, ProviderError
from ..providers.factory import create_provider, key_status, resolve_model, resolve_spec
from ..security import (
    AuditLog,
    SecretVault,
    assess_tool,
    mask_secret,
    redact,
    redact_structure,
)
from ..security.vault import VaultError
from ..tools.files import read_workspace_file
from ..tools.files import unified_diff as compute_unified_diff


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _approval_diff(tool_name: str, arguments: dict[str, Any], workdir: Path) -> str:
    """Build a redacted unified diff for mutating tools before approval."""

    path = str(arguments.get("path") or "")
    if tool_name not in {"edit_file", "write_file"} or not path:
        return ""
    try:
        old_text = read_workspace_file(workdir, path) or ""
        if tool_name == "write_file":
            new_text = str(arguments.get("content") or "")
        else:
            old_string = str(arguments.get("old_string") or "")
            new_string = str(arguments.get("new_string") or "")
            new_text = (
                old_text.replace(old_string, new_string, 1)
                if old_string and old_string in old_text
                else new_string
            )
        diff_text = compute_unified_diff(old_text, new_text, path)
    except Exception:  # noqa: BLE001 - display-only diff helper must never block approval
        return ""
    return redact(diff_text)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _title_for(session: Session) -> str:
    for message in session.messages:
        if message.get("role") == "user" and message.get("content"):
            preview = " ".join(str(message["content"]).split())
            return redact(preview[:72]) or "Untitled operation"
    return "Untitled operation"


def _session_payload(session: Session) -> dict[str, Any]:
    return {
        "id": session.id,
        "title": _title_for(session),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "provider": session.provider,
        "model": session.model,
        "workdir": session.workdir,
        "plan": [redact(step) for step in session.plan],
        "messages": redact_structure(session.messages),
        "message_count": len(session.messages),
    }


@dataclass
class _PendingApproval:
    request_id: str
    tool_name: str
    arguments: dict[str, Any]
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


class _BridgeEvents(AgentEvents):
    def __init__(self, bridge: StudioBridge) -> None:
        self.bridge = bridge
        self.steps = 0

    @contextmanager
    def thinking(self, label: str):
        self.bridge._emit("typing", {"active": True, "label": label})
        try:
            yield
        finally:
            self.bridge._emit("typing", {"active": False, "label": ""})

    def step(self, step: int, total: int) -> None:
        self.steps = max(self.steps, step)
        self.bridge._emit("step", {"current": step, "total": total})

    def assistant(self, text: str) -> None:
        self.bridge._emit("assistant", {"content": text})

    def tool_call(
        self, name: str, arguments: dict[str, Any], call_id: str = ""
    ) -> None:
        risk = assess_tool(name, arguments, self.bridge._settings.workdir)
        self.bridge._emit(
            "tool",
            {
                "phase": "start",
                "id": call_id or uuid.uuid4().hex,
                "name": name,
                "arguments": redact_structure(arguments),
                "risk": risk.level,
                "risk_title": risk.title,
                "summary": risk.summary,
            },
        )
        self.bridge._audit_safe(
            "tool.requested",
            tool=name,
            risk=risk.level,
            arguments_sha256=_digest(_json(arguments)),
            argument_keys=sorted(arguments),
        )

    def tool_result(self, name: str, result: str, call_id: str = "") -> None:
        failed = (
            result.lstrip().lower().startswith(("error", "blocked", "action denied"))
        )
        self.bridge._emit(
            "tool",
            {
                "phase": "finish",
                "id": call_id,
                "name": name,
                "result": redact(result),
                "failed": failed,
            },
        )
        self.bridge._audit_safe(
            "tool.finished",
            tool=name,
            status="error" if failed else "ok",
            result_sha256=_digest(result),
            result_chars=len(result),
        )

    def plan(self, steps: list[str], note: str = "") -> None:
        self.bridge._emit("plan", {"steps": steps, "note": note})


class StudioBridge(QObject):
    """The single object exposed to the local web UI through QWebChannel."""

    event = Signal(str, str)
    themeChanged = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = SessionStore(SESSIONS_DIR)
        self._vault = SecretVault(VAULT_FILE)
        self._audit = AuditLog(AUDIT_FILE)
        self._session: Session | None = None
        self._settings = self._load_settings_safely()
        self._theme: str = "dark"
        self._thread: threading.Thread | None = None
        self._running = False
        self._cancel_event = threading.Event()
        self._pending: dict[str, _PendingApproval] = {}
        self._pending_lock = threading.RLock()
        self._audit_safe("studio.opened", version=__version__)

    # ── state ────────────────────────────────────────────────────────────

    def _load_settings_safely(self):
        try:
            data = read_config_file()
            workdir = data.get("workdir") or str(Path.home())
            return load_settings(workdir=workdir)
        except (ConfigError, OSError, ValueError):
            return load_settings(workdir=Path.home())

    def _provider_rows(self) -> list[dict[str, Any]]:
        statuses = {spec.id: configured for spec, configured in key_status()}
        rows: list[dict[str, Any]] = []
        for spec in PROVIDERS.values():
            try:
                model = (
                    resolve_model(self._settings, spec)
                    if spec.id == self._settings.provider
                    else spec.default_model
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                model = spec.default_model
            rows.append(
                {
                    "id": spec.id,
                    "label": spec.label,
                    "model": model,
                    "default_model": spec.default_model,
                    "env_key": spec.env_key,
                    "requires_key": spec.requires_key,
                    "configured": statuses.get(spec.id, False),
                    "note": spec.note,
                }
            )
        return rows

    def _state(self) -> dict[str, Any]:
        spec = resolve_spec(self._settings)
        model = resolve_model(self._settings, spec)
        statuses = {item.id: configured for item, configured in key_status()}
        try:
            vault_error = ""
            vault_secrets = []
            if self._vault.available:
                for name in self._vault.names():
                    vault_secrets.append(
                        {"name": name, "value": mask_secret(self._vault.get(name))}
                    )
        except VaultError as exc:
            vault_error = str(exc)
            vault_secrets = []
        audit = self._audit.verify()
        return {
            "app": "Mirsad Studio",
            "version": __version__,
            "workspace": str(self._settings.workdir),
            "config_file": str(CONFIG_FILE),
            "provider": {
                "id": spec.id,
                "label": spec.label,
                "model": model,
                "configured": statuses.get(spec.id, False),
            },
            "settings": {
                "provider": self._settings.provider,
                "model": self._settings.model,
                "temperature": self._settings.temperature,
                "max_steps": self._settings.max_steps,
                "max_history": self._settings.max_history,
                "auto_approve": self._settings.auto_approve,
                "workdir": str(self._settings.workdir),
            },
            "providers": self._provider_rows(),
            "vault": {
                "available": self._vault.available,
                "count": len(vault_secrets),
                "secrets": vault_secrets,
                "error": vault_error,
            },
            "audit": {
                "ok": audit.ok,
                "entries": audit.entries,
                "message": audit.message,
                "broken_at": audit.broken_at,
            },
            "sessions": self._sessions(),
            "session": _session_payload(self._session) if self._session else None,
            "running": self._running,
            "secure_transport": True,
        }

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        self.event.emit(name, _json(payload))

    def _sessions(self) -> list[dict[str, Any]]:
        summaries = []
        for item in self._store.list():
            summary = dict(item)
            summary["preview"] = redact(str(summary.get("preview") or ""))
            summaries.append(summary)
        return summaries

    def _toast(self, message: str, kind: str = "info") -> None:
        self._emit("toast", {"message": message, "kind": kind})

    def _audit_safe(self, event: str, **details: Any) -> None:
        try:
            self._audit.record(event, **details)
        except OSError:
            pass

    def _new_session(self) -> Session:
        spec = resolve_spec(self._settings)
        model = resolve_model(self._settings, spec)
        session = self._store.new(
            self._settings.provider, model, self._settings.workdir
        )
        self._store.save(session)
        self._session = session
        self._audit_safe(
            "session.created",
            session=session.id,
            provider=session.provider,
            model=session.model,
        )
        return session

    # ── slots used by the web UI ─────────────────────────────────────────

    @Slot(result=str)
    def bootstrap(self) -> str:
        bootstrap_env()
        try:
            state = self._state()
        except (ConfigError, ProviderError) as exc:
            return _json({"ok": False, "error": str(exc)})
        self._emit("state", state)
        return _json({"ok": True, "state": state})

    @Slot(result=str)
    def get_state(self) -> str:
        return _json({"ok": True, "state": self._state()})

    @Slot(result=str)
    def new_session(self) -> str:
        if self._running:
            return _json(
                {"ok": False, "error": "Finish or stop the current run first."}
            )
        session = self._new_session()
        self._emit("sessions", {"sessions": self._sessions()})
        self._emit("session", _session_payload(session))
        return _json({"ok": True, "session": _session_payload(session)})

    @Slot(str, result=str)
    def load_session(self, session_id: str) -> str:
        if self._running:
            return _json(
                {"ok": False, "error": "Finish or stop the current run first."}
            )
        try:
            session = self._store.load(session_id)
        except (FileNotFoundError, ValueError) as exc:
            return _json({"ok": False, "error": str(exc)})
        self._session = session
        self._audit_safe("session.opened", session=session.id)
        self._emit("session", _session_payload(session))
        return _json({"ok": True, "session": _session_payload(session)})

    @Slot(str, result=str)
    def delete_session(self, session_id: str) -> str:
        if self._running:
            return _json(
                {"ok": False, "error": "Finish or stop the current run first."}
            )
        try:
            deleted = self._store.delete(session_id)
        except ValueError as exc:
            return _json({"ok": False, "error": str(exc)})
        if not deleted:
            return _json({"ok": False, "error": "Session not found."})
        if self._session and self._session.id == session_id:
            self._session = None
            self._emit("session", {"id": None})
        self._audit_safe("session.deleted", session=session_id)
        self._emit("sessions", {"sessions": self._sessions()})
        return _json({"ok": True})

    @Slot(str, result=str)
    def send_message(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return _json({"ok": False, "error": "Enter a brief for Mirsad first."})
        if self._running:
            return _json({"ok": False, "error": "A run is already in progress."})

        try:
            spec = resolve_spec(self._settings)
            model = resolve_model(self._settings, spec)
            self._settings.model = self._settings.model or model
            provider = create_provider(self._settings)
        except (ProviderError, ConfigError) as exc:
            return _json({"ok": False, "error": str(exc)})

        if self._session is None:
            self._new_session()
        session = self._session
        assert session is not None
        session.provider = self._settings.provider
        session.model = provider.model
        session.workdir = str(self._settings.workdir)
        self._store.save(session)

        self._running = True
        self._cancel_event.clear()
        self._audit_safe(
            "run.started",
            session=session.id,
            provider=self._settings.provider,
            model=provider.model,
            prompt_sha256=_digest(text),
            prompt_chars=len(text),
            auto_approve=self._settings.auto_approve,
        )
        self._emit(
            "user",
            {
                "content": text,
                "session_id": session.id,
                "provider": self._settings.provider,
                "model": provider.model,
            },
        )
        self._emit("run", {"state": "running", "session_id": session.id})
        self._emit(
            "session.header",
            {
                "id": session.id,
                "title": _title_for(session),
                "provider": session.provider,
                "model": session.model,
                "workdir": session.workdir,
            },
        )
        self._thread = threading.Thread(
            target=self._run_turn,
            args=(session, self._settings, provider, text),
            daemon=True,
            name="mirsad-agent-run",
        )
        self._thread.start()
        return _json({"ok": True, "session_id": session.id})

    @Slot(str)
    def set_theme(self, theme: str) -> str:
        """Apply a UI theme ("dark" or "light") and notify the window."""

        next_theme = (theme or "dark").strip().lower()
        if next_theme not in {"dark", "light"}:
            next_theme = "dark"
        self._theme = next_theme
        self.themeChanged.emit(next_theme)
        return _json({"ok": True, "theme": next_theme})

    @Slot()
    def cancel_run(self) -> None:
        if not self._running:
            return
        self._cancel_event.set()
        self._deny_pending()
        self._emit("typing", {"active": False, "label": ""})
        self._emit("run", {"state": "stopping"})
        self._toast("Stopping after the current step.", "warning")

    @Slot(result=str)
    def verify_audit(self) -> str:
        check = self._audit.verify()
        self._emit(
            "audit",
            {
                "ok": check.ok,
                "entries": check.entries,
                "message": check.message,
                "broken_at": check.broken_at,
            },
        )
        return _json(
            {
                "ok": check.ok,
                "entries": check.entries,
                "message": check.message,
                "broken_at": check.broken_at,
            }
        )

    @Slot(result=str)
    def audit_entries(self) -> str:
        entries = []
        for entry in reversed(self._audit.tail(160)):
            details = entry.get("details") or {}
            entries.append(
                {
                    "seq": entry.get("seq"),
                    "ts": entry.get("ts"),
                    "event": entry.get("event"),
                    "summary": _audit_summary(entry.get("event", ""), details),
                    "hash": str(entry.get("hash", ""))[:12],
                }
            )
        check = self._audit.verify()
        return _json(
            {
                "ok": True,
                "entries": entries,
                "check": {
                    "ok": check.ok,
                    "entries": check.entries,
                    "message": check.message,
                    "broken_at": check.broken_at,
                },
            }
        )

    @Slot(str, result=str)
    def save_settings(self, payload: str) -> str:
        try:
            data = json.loads(payload or "{}")
            if not isinstance(data, dict):
                raise ValueError("Settings payload must be an object.")
            provider = str(data.get("provider") or self._settings.provider).lower()
            if provider not in PROVIDERS:
                raise ValueError(f"Unknown provider: {provider}")
            workdir = Path(
                str(data.get("workdir") or self._settings.workdir)
            ).expanduser()
            if not workdir.is_dir():
                raise ValueError(f"Workspace does not exist: {workdir}")
            temperature = max(0.0, min(2.0, float(data.get("temperature", 0.2))))
            max_steps = max(1, min(60, int(data.get("max_steps", 12))))
            max_history = max(8, min(500, int(data.get("max_history", 80))))
            model = str(data.get("model") or "").strip() or None
            auto_approve = bool(data.get("auto_approve", False))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return _json({"ok": False, "error": f"Invalid settings: {exc}"})

        self._settings.provider = provider
        self._settings.model = model
        self._settings.temperature = temperature
        self._settings.max_steps = max_steps
        self._settings.max_history = max_history
        self._settings.auto_approve = auto_approve
        self._settings.workdir = workdir.resolve()
        try:
            save_settings(self._settings)
        except OSError as exc:
            return _json({"ok": False, "error": f"Could not save settings: {exc}"})
        self._audit_safe(
            "settings.changed",
            provider=provider,
            model=model,
            temperature=temperature,
            max_steps=max_steps,
            max_history=max_history,
            auto_approve=auto_approve,
            workdir=str(self._settings.workdir),
        )
        if self._session:
            self._session.provider = provider
            self._session.model = model or self._session.model
            self._session.workdir = str(self._settings.workdir)
            self._store.save(self._session)
        self._emit("state", self._state())
        self._toast("Settings saved.", "success")
        return _json({"ok": True, "state": self._state()})

    @Slot(str, str, result=str)
    def save_api_key(self, provider: str, key: str) -> str:
        provider = (provider or "").lower().strip()
        if provider not in PROVIDERS:
            return _json({"ok": False, "error": "Unknown provider."})
        spec = PROVIDERS[provider]
        if not spec.requires_key or not spec.env_key:
            return _json(
                {"ok": False, "error": "This provider does not use an API key."}
            )
        key = (key or "").strip()
        if not key:
            return _json({"ok": False, "error": "Enter an API key first."})
        if not self._vault.available:
            return _json(
                {
                    "ok": False,
                    "error": "The encrypted vault requires Windows DPAPI. "
                    "Use a MIRSAD environment variable on this platform.",
                }
            )
        try:
            self._vault.set(spec.env_key, key)
        except VaultError as exc:
            return _json({"ok": False, "error": str(exc)})
        os.environ[spec.env_key] = key
        self._audit_safe(
            "credential.saved",
            provider=provider,
            env_key=spec.env_key,
            key_chars=len(key),
        )
        self._emit("state", self._state())
        self._toast(f"{spec.label} key saved to the encrypted vault.", "success")
        return _json({"ok": True, "state": self._state()})

    @Slot(str, result=str)
    def remove_api_key(self, provider: str) -> str:
        provider = (provider or "").lower().strip()
        if provider not in PROVIDERS:
            return _json({"ok": False, "error": "Unknown provider."})
        spec = PROVIDERS[provider]
        if not spec.env_key:
            return _json(
                {"ok": False, "error": "This provider does not use an API key."}
            )
        try:
            self._vault.delete(spec.env_key)
        except VaultError as exc:
            return _json({"ok": False, "error": str(exc)})
        os.environ.pop(spec.env_key, None)
        self._audit_safe("credential.removed", provider=provider, env_key=spec.env_key)
        self._emit("state", self._state())
        self._toast(f"{spec.label} key removed from the vault.", "success")
        return _json({"ok": True, "state": self._state()})

    @Slot(result=str)
    def choose_workspace(self) -> str:
        parent = QApplication.activeWindow()
        path = QFileDialog.getExistingDirectory(
            parent,
            "Choose a workspace",
            str(self._settings.workdir),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not path:
            return _json({"ok": False, "cancelled": True})
        return _json({"ok": True, "path": path})

    @Slot(str, bool)
    def resolve_approval(self, request_id: str, approved: bool) -> None:
        with self._pending_lock:
            pending = self._pending.get(request_id)
        if pending is None:
            return
        pending.approved = bool(approved)
        pending.event.set()

    @Slot(str)
    def open_external(self, url: str) -> None:
        from PySide6.QtCore import QUrl

        parsed = QUrl(url)
        if parsed.scheme().lower() in {"https", "http"}:
            QDesktopServices.openUrl(parsed)

    @Slot()
    def shutdown(self) -> None:
        self._cancel_event.set()
        self._deny_pending()

    # ── worker ───────────────────────────────────────────────────────────

    def _run_turn(
        self,
        session: Session,
        settings,
        provider: BaseProvider,
        text: str,
    ) -> None:
        events = _BridgeEvents(self)
        agent = Agent(
            settings=settings,
            provider=provider,
            session=session,
            store=self._store,
            approval=self._approval_callback,
            events=events,
            cancel_check=self._cancel_event.is_set,
        )
        try:
            answer = agent.run_turn(text)
            if answer:
                self._emit("assistant", {"content": answer})
            self._audit_safe(
                "run.finished",
                session=session.id,
                steps=events.steps,
                answer_sha256=_digest(answer or ""),
                answer_chars=len(answer or ""),
            )
            self._emit(
                "run",
                {
                    "state": "complete",
                    "session_id": session.id,
                    "steps": events.steps,
                },
            )
        except AgentCancelled:
            self._audit_safe("run.cancelled", session=session.id, steps=events.steps)
            self._emit("run", {"state": "cancelled", "session_id": session.id})
            self._toast("Run stopped. Progress was saved.", "warning")
        except ProviderError as exc:
            self._audit_safe("run.failed", session=session.id, error=type(exc).__name__)
            self._emit("error", {"message": redact(str(exc))})
            self._emit("run", {"state": "error", "session_id": session.id})
        except Exception as exc:  # noqa: BLE001 - surfaced to the desktop UI
            self._audit_safe("run.failed", session=session.id, error=type(exc).__name__)
            self._emit(
                "error",
                {"message": f"{type(exc).__name__}: {redact(str(exc))}"},
            )
            self._emit("run", {"state": "error", "session_id": session.id})
        finally:
            self._running = False
            try:
                refreshed = self._store.load(session.id)
                self._session = refreshed
                self._emit("session.sync", _session_payload(refreshed))
            except (FileNotFoundError, ValueError):
                pass
            self._emit("sessions", {"sessions": self._sessions()})
            self._emit("typing", {"active": False, "label": ""})

    def _approval_callback(self, tool, arguments: dict[str, Any]) -> bool:
        risk = assess_tool(tool.name, arguments, self._settings.workdir)
        request_id = uuid.uuid4().hex
        pending = _PendingApproval(request_id, tool.name, arguments)
        with self._pending_lock:
            self._pending[request_id] = pending
        self._audit_safe(
            "approval.requested",
            tool=tool.name,
            risk=risk.level,
            arguments_sha256=_digest(_json(arguments)),
        )
        self._emit(
            "approval.requested",
            {
                "id": request_id,
                "tool": tool.name,
                "arguments": redact_structure(arguments),
                "risk": risk.level,
                "risk_title": risk.title,
                "reasons": list(risk.reasons),
                "summary": risk.summary,
                "diff": _approval_diff(tool.name, arguments, self._settings.workdir),
            },
        )
        approved = pending.event.wait(timeout=600)
        with self._pending_lock:
            self._pending.pop(request_id, None)
        result = bool(approved and pending.approved)
        self._audit_safe(
            "approval.granted" if result else "approval.denied",
            tool=tool.name,
            risk=risk.level,
        )
        self._emit(
            "approval.resolved",
            {"id": request_id, "approved": result, "tool": tool.name},
        )
        return result

    def _deny_pending(self) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())
        for item in pending:
            item.approved = False
            item.event.set()


def _audit_summary(event: str, details: dict[str, Any]) -> str:
    if event == "tool.requested":
        return f"{details.get('tool', 'tool')} requested · {details.get('risk', 'low')} risk"
    if event == "tool.finished":
        return f"{details.get('tool', 'tool')} finished · {details.get('status', 'ok')}"
    if event.startswith("approval."):
        return f"{details.get('tool', 'action')} · {event.split('.')[-1]}"
    if event.startswith("run."):
        return f"Run {event.split('.')[-1]} · session {details.get('session', '—')}"
    if event.startswith("session."):
        return f"Session {event.split('.')[-1]}"
    if event == "credential.saved":
        return f"Credential stored · {details.get('provider', 'provider')}"
    if event == "settings.changed":
        return f"Settings updated · {details.get('provider', 'provider')}"
    if event == "studio.opened":
        return "Mirsad Studio opened"
    return event.replace(".", " ")

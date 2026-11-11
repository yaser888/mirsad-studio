"""Compliance evidence pack generated from the local audit chain.

This module is part of Mirsad Pro. It reads only local state (sessions,
audit chain) and emits a self-contained HTML file you can hand to an
auditor or your security reviewer. It never opens a network connection.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, config
from .memory import SessionStore
from .security import AuditLog


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _sessions_table(sessions_dir: Path) -> str:
    try:
        summaries = SessionStore(sessions_dir).list()[:25]
    except Exception:  # noqa: BLE001 - report should render even if sessions are corrupt
        summaries = []
    if not summaries:
        return "<p class='muted'>No sessions recorded yet.</p>"
    rows = [
        "<tr><th>ID</th><th>Updated</th><th>Provider</th><th>Model</th><th>Msgs</th></tr>",
    ]
    for item in summaries:
        rows.append(
            "<tr>"
            f"<td class='mono'>{_esc(item.get('id', ''))}</td>"
            f"<td>{_esc(item.get('updated_at', ''))}</td>"
            f"<td>{_esc(item.get('provider', ''))}</td>"
            f"<td>{_esc(item.get('model', ''))}</td>"
            f"<td class='right'>{_esc(item.get('messages', 0))}</td>"
            "</tr>"
        )
    return "<table>" + "".join(rows) + "</table>"


def _audit_events(audit: AuditLog, limit: int = 20) -> str:
    entries = audit.tail(limit)
    if not entries:
        return "<p class='muted'>No audit events recorded yet.</p>"
    items = []
    for entry in entries:
        items.append(
            "<li>"
            f"<span class='mono'>#{_esc(entry.get('seq'))} {_esc(entry.get('ts'))}</span> "
            f"<b>{_esc(entry.get('event'))}</b>"
            f"<div class='detail mono'>{_esc(entry.get('details', {}))}</div>"
            "</li>"
        )
    return "<ul class='events'>" + "".join(items) + "</ul>"


def build_report(license_info, *, limit_sessions: int = 25) -> str:
    audit = AuditLog(config.AUDIT_FILE)
    verify = audit.verify()
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    status_class = "ok" if verify.ok else "bad"
    events_html = _audit_events(audit)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Mirsad Pro — Compliance evidence pack</title>
<style>
  :root {{
    --ink: #0a0c0b; --panel: #121613; --paper: #f0eee7; --muted: #929a91; --line: #242b26; --copper: #d97757;
  }}
  body {{ background: var(--ink); color: var(--paper); font: 15px/1.6 system-ui, sans-serif; margin: 0; padding: 40px; }}
  main {{ max-width: 920px; margin: 0 auto; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 32px; }}
  h1 {{ font-family: Georgia, serif; font-weight: 400; font-size: 32px; margin: 0 0 4px; }}
  h2 {{ font-family: Georgia, serif; font-weight: 400; font-size: 19px; margin: 28px 0 10px; color: var(--copper); }}
  .eyebrow {{ font-family: Consolas, monospace; font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); }}
  .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
  .card {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }}
  .card b {{ color: var(--muted); font-size: 10px; text-transform: uppercase; font-family: Consolas, monospace; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 6px; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); font-size: 12px; }}
  th {{ color: var(--muted); font-size: 9px; text-transform: uppercase; }}
  .right {{ text-align: right; }}
  .mono {{ font-family: Consolas, monospace; font-size: 11px; }}
  .events {{ list-style: none; padding: 0; }}
  .events li {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; }}
  .detail {{ color: var(--muted); margin-top: 4px; word-break: break-word; }}
  .ok {{ color: #92b68e; }} .bad {{ color: #e06b63; }}
  .muted {{ color: var(--muted); }}
  footer {{ margin-top: 26px; font-family: Consolas, monospace; font-size: 10px; color: var(--muted); border-top: 1px solid var(--line); padding-top: 12px; }}
</style>
</head>
<body>
<main>
  <div class="eyebrow">Mirsad Pro — Evidence, not vibes</div>
  <h1>Compliance evidence pack</h1>
  <p class="muted">Generated {generated} · Mirsad Studio {_esc(__version__)}</p>

  <div class="grid">
    <div class="card"><b>Edition</b><br>Mirsad {_esc(license_info.plan.upper())}</div>
    <div class="card"><b>Licensed to</b><br>{_esc(license_info.licensed_to)}</div>
    <div class="card"><b>Seats</b><br>{_esc(license_info.seats)}</div>
    <div class="card"><b>Expires</b><br>{_esc(license_info.expires_label)}</div>
  </div>

  <h2>Audit chain verification</h2>
  <p class="{status_class}"><b>{_esc("VERIFIED" if verify.ok else "BROKEN")}</b> — {_esc(verify.message)}</p>

  <h2>Recent sessions</h2>
  {_sessions_table(config.SESSIONS_DIR)}

  <h2>Recent audit events</h2>
  {events_html}

  <footer>Generated locally from the machine you are reading this on. No data was sent anywhere.</footer>
</main>
</body>
</html>
"""

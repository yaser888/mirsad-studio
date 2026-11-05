"""Command-line interface for Hermes Agent."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from . import __version__, ui
from .agent import Agent
from .config import (
    CONFIG_FILE,
    ENV_FILE,
    SESSIONS_DIR,
    ConfigError,
    bootstrap_env,
    init_app,
    load_settings,
    read_config_file,
)
from .memory import Session, SessionStore
from .providers import PROVIDERS
from .providers.base import BaseProvider, MissingAPIKey, ProviderError
from .providers.factory import create_provider, key_status, resolve_model, resolve_spec
from .tools import build_registry

# ── parser ──────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes",
        description="Hermes Agent - a multi-step AI agent with tools, memory, and "
        "multi-provider LLM support.",
        epilog=(
            "Examples:\n"
            "  hermes init\n"
            "  hermes chat\n"
            "  hermes ask \"summarize this project and run its tests\"\n"
            "  hermes chat --provider ollama --model qwen2.5:7b\n"
            "  hermes sessions list\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"hermes-agent {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command")

    chat = subparsers.add_parser("chat", help="Start an interactive chat session.")
    _add_run_args(chat, with_session=True)

    ask = subparsers.add_parser("ask", help="Run one request and print the answer.")
    _add_run_args(ask, with_session=True)
    ask.add_argument("prompt", nargs="+", help="The request for the agent.")
    ask.add_argument(
        "--quiet", action="store_true", help="Hide tool output; print only the answer."
    )
    ask.add_argument(
        "--json", action="store_true", help="Print the result as JSON (implies --quiet)."
    )

    sessions = subparsers.add_parser("sessions", help="List, inspect, or delete sessions.")
    session_sub = sessions.add_subparsers(dest="session_command")
    session_list = session_sub.add_parser("list", help="List saved sessions.")
    session_list.set_defaults(session_command="list")
    session_show = session_sub.add_parser("show", help="Show a session transcript.")
    session_show.add_argument("session_id")
    session_delete = session_sub.add_parser("delete", help="Delete a session.")
    session_delete.add_argument("session_id")
    session_path = session_sub.add_parser("path", help="Print a session's file path.")
    session_path.add_argument("session_id")

    tools = subparsers.add_parser("tools", help="List available agent tools.")
    tools.set_defaults()

    providers = subparsers.add_parser("providers", help="List LLM providers and key status.")
    providers.set_defaults()

    config = subparsers.add_parser("config", help="Show effective configuration.")
    config.set_defaults()

    init = subparsers.add_parser("init", help="Create the Hermes config directory.")
    init.add_argument(
        "--force", action="store_true", help="Overwrite existing config/env files."
    )
    init.set_defaults()

    return parser


def _add_run_args(parser: argparse.ArgumentParser, with_session: bool) -> None:
    parser.add_argument(
        "-p",
        "--provider",
        choices=sorted(PROVIDERS),
        default=None,
        help="LLM provider (default: config or HERMES_PROVIDER).",
    )
    parser.add_argument("-m", "--model", default=None, help="Model name override.")
    parser.add_argument(
        "-w", "--workdir", default=None, help="Workspace directory (default: cwd)."
    )
    parser.add_argument("--temperature", type=float, default=None, help="0.0-2.0.")
    parser.add_argument("--max-steps", type=int, default=None, help="Agent step budget.")
    parser.add_argument(
        "--max-history", type=int, default=None, help="Messages sent as context."
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        default=None,
        help="Auto-approve all shell and file-write actions (use carefully).",
    )
    if with_session:
        parser.add_argument(
            "-s",
            "--session",
            default=None,
            help="Resume an existing session ID (see: hermes sessions list).",
        )


# ── entry point ─────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    bootstrap_env()
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if not raw_args:
        raw_args = ["chat"]

    parser = build_parser()
    args = parser.parse_args(raw_args)

    try:
        if args.command == "chat":
            return cmd_chat(args)
        if args.command == "ask":
            return cmd_ask(args)
        if args.command == "sessions":
            return cmd_sessions(args)
        if args.command == "tools":
            return cmd_tools()
        if args.command == "providers":
            return cmd_providers()
        if args.command == "config":
            return cmd_config()
        if args.command == "init":
            return cmd_init(args)
    except KeyboardInterrupt:
        ui.warn("\nInterrupted.")
        return 130
    except (ConfigError, MissingAPIKey, ProviderError, FileNotFoundError, ValueError) as exc:
        ui.error(str(exc))
        return 1

    parser.print_help()
    return 0


# ── chat ────────────────────────────────────────────────────────────────


def cmd_chat(args: argparse.Namespace) -> int:
    store, session, settings, provider = _prepare(args)

    agent = Agent(
        settings=settings,
        provider=provider,
        session=session,
        store=store,
        approval=lambda tool, arguments: ui.confirm_tool(tool.name, arguments),
    )
    ui.banner(settings.provider, provider.model, str(settings.workdir), session.id)
    if agent.plan:
        ui.plan(agent.plan)
    if settings.auto_approve:
        ui.warn("Auto-approve is ON: tool actions will run without confirmation.")

    while True:
        try:
            line = ui.user_prompt()
        except KeyboardInterrupt:
            ui.warn("\nUse /exit to quit.")
            continue

        text = line.strip()
        if not text:
            continue

        if text.startswith("/"):
            action, agent = _handle_chat_command(text, agent, store)
            if action == "exit":
                break
            continue

        try:
            answer = agent.run_turn(text)
            if answer:
                ui.assistant(answer)
        except KeyboardInterrupt:
            ui.warn("Interrupted. Progress so far has been saved.")
        except ProviderError as exc:
            ui.error(str(exc))
        except Exception as exc:  # noqa: BLE001 - keep the REPL alive
            ui.error(f"Unexpected error: {type(exc).__name__}: {exc}")

    agent.save()
    ui.info(f"Session saved: {agent.session.id}")
    return 0


def _handle_chat_command(
    text: str,
    agent: Agent,
    store: SessionStore,
) -> tuple[str, Agent]:
    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command in {"/exit", "/quit"}:
        return "exit", agent

    if command == "/help":
        ui.console.print(
            Panel(
                Text(
                    "/help              show this help\n"
                    "/exit, /quit       save and exit\n"
                    "/session           show session details\n"
                    "/plan              show the current plan\n"
                    "/tools             list available tools\n"
                    "/workdir [path]    show or change the workspace\n"
                    "/model [name]      show or change the model\n"
                    "/provider [id]     show or change the provider\n"
                    "/yes               toggle auto-approval\n"
                    "/clear             clear conversation history\n"
                    "/new               start a new session\n\n"
                    "Anything else is sent to the agent."
                ),
                border_style="cyan",
                padding=(1, 2),
            )
        )
        return "continue", agent

    if command == "/session":
        ui.kv_table(
            "Session",
            [
                ("id", agent.session.id),
                ("file", str(store.path_for(agent.session.id))),
                ("provider", agent.settings.provider),
                ("model", agent.provider.model),
                ("workdir", str(agent.settings.workdir)),
                ("messages", str(len(agent.session.messages))),
                ("created", agent.session.created_at),
                ("updated", agent.session.updated_at),
            ],
        )
        return "continue", agent

    if command == "/plan":
        ui.plan(agent.plan)
        return "continue", agent

    if command == "/tools":
        table = Table(title="Tools", border_style="cyan", header_style="dim")
        table.add_column("Name", style="bold")
        table.add_column("Approval")
        table.add_column("Description")
        for tool in agent.registry.tools():
            table.add_row(
                tool.name,
                "yes" if tool.requires_approval else "no",
                tool.description.split("\n")[0],
            )
        ui.console.print(table)
        return "continue", agent

    if command == "/workdir":
        if not argument:
            ui.info(f"Workspace: {agent.settings.workdir}")
        else:
            try:
                resolved = agent.set_workdir(argument)
                ui.success(f"Workspace changed to: {resolved}")
            except (OSError, ValueError) as exc:
                ui.error(str(exc))
        return "continue", agent

    if command == "/model":
        if not argument:
            ui.info(f"Model: {agent.provider.model}")
        else:
            agent.provider.model = argument
            agent.session.model = argument
            agent.save()
            ui.success(f"Model changed to: {argument}")
        return "continue", agent

    if command == "/provider":
        if not argument:
            ui.info(f"Provider: {agent.settings.provider}")
            return "continue", agent
        candidate = argument.lower().strip()
        if candidate not in PROVIDERS:
            ui.error(
                f"Unknown provider '{candidate}'. Available: {', '.join(sorted(PROVIDERS))}"
            )
            return "continue", agent

        old_provider = agent.settings.provider
        old_model = agent.settings.model
        agent.settings.provider = candidate
        agent.settings.model = None
        try:
            new_provider = create_provider(agent.settings)
        except ProviderError as exc:
            agent.settings.provider = old_provider
            agent.settings.model = old_model
            ui.error(str(exc))
            return "continue", agent
        agent.set_provider(new_provider, candidate)
        ui.success(f"Provider changed to: {candidate} ({new_provider.model})")
        return "continue", agent

    if command == "/yes":
        enabled = not agent.settings.auto_approve
        agent.set_auto_approve(enabled)
        ui.warn(f"Auto-approve is now {'ON' if enabled else 'OFF'}.")
        return "continue", agent

    if command == "/clear":
        try:
            confirmed = Confirm.ask(
                "Delete this session's conversation history?", default=False
            )
        except (EOFError, KeyboardInterrupt):
            confirmed = False
        if confirmed:
            agent.clear()
            ui.success("Conversation history cleared.")
        return "continue", agent

    if command == "/new":
        new_session = store.new(
            agent.settings.provider, agent.provider.model, agent.settings.workdir
        )
        store.save(new_session)
        agent.session = new_session
        agent.plan = []
        agent._save()
        ui.success(f"Started a new session: {new_session.id}")
        return "new", agent

    ui.warn(f"Unknown command: {command}. Type /help.")
    return "continue", agent


# ── ask ─────────────────────────────────────────────────────────────────


def cmd_ask(args: argparse.Namespace) -> int:
    store, session, settings, provider = _prepare(args)
    prompt_text = " ".join(args.prompt)

    quiet = args.quiet or args.json
    original_console = ui.console
    quiet_console: Console | None = None
    if quiet:
        quiet_console = Console(file=io.StringIO(), highlight=False)
        ui.console = quiet_console

    def approve(tool, arguments):
        # Keep approval prompts visible even in quiet/JSON mode.
        if quiet_console is None:
            return ui.confirm_tool(tool.name, arguments)
        ui.console = original_console
        try:
            return ui.confirm_tool(tool.name, arguments)
        finally:
            ui.console = quiet_console

    try:
        agent = Agent(
            settings=settings,
            provider=provider,
            session=session,
            store=store,
            approval=approve,
        )
        answer = agent.run_turn(prompt_text)
    finally:
        ui.console = original_console

    if args.json:
        print(
            json.dumps(
                {
                    "answer": answer,
                    "session_id": session.id,
                    "provider": settings.provider,
                    "model": provider.model,
                    "workdir": str(settings.workdir),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(answer)
    return 0


# ── sessions ────────────────────────────────────────────────────────────


def cmd_sessions(args: argparse.Namespace) -> int:
    store = SessionStore(SESSIONS_DIR)
    command = getattr(args, "session_command", None) or "list"

    if command == "list":
        summaries = store.list()
        if not summaries:
            ui.info("No saved sessions yet. Start one with: hermes chat")
            return 0
        table = Table(
            title="Sessions", border_style="cyan", header_style="dim", expand=True
        )
        table.add_column("ID", no_wrap=True)
        table.add_column("Updated", no_wrap=True)
        table.add_column("Provider/Model")
        table.add_column("Msgs", justify="right")
        table.add_column("Preview", overflow="fold")
        for item in summaries:
            table.add_row(
                item["id"],
                item["updated_at"],
                item["provider"] + "/" + item["model"],
                str(item["messages"]),
                Text(item["preview"]),
            )
        ui.console.print(table)
        return 0

    session_id = args.session_id
    if command == "path":
        path = store.path_for(session_id)
        print(path)
        return 0

    if command == "delete":
        if store.delete(session_id):
            ui.success(f"Deleted session: {session_id}")
            return 0
        ui.error(f"Session not found: {session_id}")
        return 1

    # show
    session = store.load(session_id)
    ui.kv_table(
        f"Session {session.id}",
        [
            ("created", session.created_at),
            ("updated", session.updated_at),
            ("provider", session.provider),
            ("model", session.model),
            ("workdir", session.workdir),
            ("messages", str(len(session.messages))),
        ],
    )
    if session.plan:
        ui.plan(session.plan)

    table = Table(
        title="Transcript", border_style="cyan", header_style="dim", expand=True
    )
    table.add_column("#", justify="right", width=3)
    table.add_column("Role", no_wrap=True)
    table.add_column("Content", overflow="fold")
    for index, message in enumerate(session.messages, start=1):
        role = str(message.get("role") or "?")
        content = message.get("content")
        if content is None:
            content = ""
        content = str(content)
        if message.get("tool_calls"):
            names = [
                str((call.get("function") or {}).get("name") or "?")
                for call in message["tool_calls"]
            ]
            content = f"[tool calls: {', '.join(names)}]\n{content}"
        if len(content) > 400:
            content = content[:400] + "..."
        table.add_row(str(index), role, Text(content))
    ui.console.print(table)
    return 0


# ── introspection ───────────────────────────────────────────────────────


def cmd_tools() -> int:
    registry = build_registry(Path.cwd())
    table = Table(title="Hermes tools", border_style="cyan", header_style="dim")
    table.add_column("Tool", style="bold", no_wrap=True)
    table.add_column("Approval", no_wrap=True)
    table.add_column("Description", overflow="fold")
    for tool in registry.tools():
        table.add_row(
            tool.name,
            "required" if tool.requires_approval else "-",
            tool.description.split("\n")[0],
        )
    ui.console.print(table)
    return 0


def cmd_providers() -> int:
    table = Table(title="LLM providers", border_style="cyan", header_style="dim")
    table.add_column("Provider", style="bold", no_wrap=True)
    table.add_column("Default model", overflow="fold")
    table.add_column("API key", no_wrap=True)
    table.add_column("Status", no_wrap=True)

    for spec, configured in key_status():
        if not spec.requires_key:
            status = "ready"
            key_label = "not needed"
        elif configured:
            status = "ready"
            key_label = spec.env_key or "HERMES_API_KEY"
        else:
            status = "missing key"
            key_label = spec.env_key or "HERMES_API_KEY"
        table.add_row(spec.label, spec.default_model, key_label, status)
    ui.console.print(table)
    ui.info(f"Config: {CONFIG_FILE}")
    ui.info(f"Env:    {ENV_FILE}")
    return 0


def cmd_config() -> int:
    settings = load_settings()
    spec = resolve_spec(settings)
    model = resolve_model(settings, spec)
    rows = [
        ("provider", settings.provider),
        ("model", model),
        ("temperature", str(settings.temperature)),
        ("max_steps", str(settings.max_steps)),
        ("max_history", str(settings.max_history)),
        ("auto_approve", str(settings.auto_approve)),
        ("workdir", str(settings.workdir)),
        ("config file", str(CONFIG_FILE)),
        ("env file", str(ENV_FILE)),
        ("sessions", str(SESSIONS_DIR)),
    ]
    ui.kv_table("Effective configuration", rows)

    if CONFIG_FILE.is_file():
        try:
            read_config_file()
            ui.success("config.json is valid.")
        except ConfigError as exc:
            ui.error(str(exc))
    else:
        ui.warn("No config.json yet. Run: hermes init")

    if ENV_FILE.is_file():
        ui.info(f"Env file found: {ENV_FILE}")
    else:
        ui.warn("No ~/.hermes/.env yet. Run: hermes init")

    table = Table(title="API keys", border_style="cyan", header_style="dim")
    table.add_column("Provider")
    table.add_column("Env var")
    table.add_column("Status")
    for provider_spec, configured in key_status():
        if not provider_spec.requires_key:
            status = "not needed"
        else:
            status = "set" if configured else "missing"
        table.add_row(
            provider_spec.label,
            provider_spec.env_key or "n/a",
            status,
        )
    ui.console.print(table)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    messages = init_app(force=args.force)
    for message in messages:
        ui.success(message)
    ui.console.print(
        Panel(
            Text(
                f"Next steps:\n"
                f"  1. Put your API key(s) in {ENV_FILE}\n"
                f"  2. Run: hermes providers\n"
                f"  3. Run: hermes chat\n\n"
                f"Tip: for a local model, install Ollama and run:\n"
                f"  hermes chat --provider ollama --model qwen2.5:7b"
            ),
            border_style="cyan",
            padding=(1, 2),
        )
    )
    return 0


# ── helpers ─────────────────────────────────────────────────────────────


def _prepare(
    args: argparse.Namespace,
) -> tuple[SessionStore, Session, Any, BaseProvider]:
    store = SessionStore(SESSIONS_DIR)
    session: Session | None = None
    if getattr(args, "session", None):
        session = store.load(args.session)

    workdir = args.workdir or (session.workdir if session else None)
    provider_id = args.provider or (session.provider if session else None)
    model = args.model or (session.model if session else None)
    auto_approve = True if args.yes else None

    settings = load_settings(
        provider=provider_id,
        model=model,
        workdir=workdir,
        temperature=args.temperature,
        max_steps=args.max_steps,
        max_history=args.max_history,
        auto_approve=auto_approve,
    )
    provider = create_provider(settings)

    if session is None:
        session = store.new(settings.provider, provider.model, settings.workdir)
        store.save(session)

    return store, session, settings, provider


if __name__ == "__main__":
    raise SystemExit(main())

"""Rich-powered terminal interface helpers."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from .events import AgentEvents

console = Console(highlight=False)


def banner(provider: str, model: str, workdir: str, session_id: str) -> None:
    title = Text("MIRSAD AGENT", style="bold cyan")
    subtitle = Text(
        "multi-step AI agent  |  tools  |  persistent memory",
        style="dim",
    )
    details = Text()
    details.append("\nprovider  ", style="dim")
    details.append(f"{provider} / {model}\n", style="bold")
    details.append("workspace ", style="dim")
    details.append(f"{workdir}\n", style="bold")
    details.append("session   ", style="dim")
    details.append(session_id, style="bold")

    body = Text.assemble(title, "\n", subtitle, details)
    console.print(Panel(body, border_style="cyan", padding=(1, 2)))
    console.print(Text("Type /help for commands, /exit to quit.\n", style="dim"))


def info(message: str) -> None:
    console.print(Text(message, style="cyan"))


def success(message: str) -> None:
    console.print(Text(message, style="green"))


def warn(message: str) -> None:
    console.print(Text(message, style="yellow"))


def error(message: str) -> None:
    console.print(Text(message, style="bold red"))


def assistant(text: str) -> None:
    if not text:
        return
    console.print()
    console.print(Markdown(text))


def tool_call(name: str, arguments: dict[str, Any]) -> None:
    if name == "update_plan":
        return
    console.print()
    console.print(
        Panel(
            Text(_preview_arguments(name, arguments)),
            title=f"tool: {name}",
            title_align="left",
            border_style="blue",
            padding=(0, 1),
        )
    )


def tool_result(name: str, result: str) -> None:
    result = result or "(empty)"
    is_error = result.lstrip().lower().startswith(("error", "blocked"))
    style = "red" if is_error else "green"
    preview = (
        result
        if len(result) <= 2500
        else result[:2500] + "\n... [output shortened in UI]"
    )
    console.print(
        Panel(
            Text(preview),
            title=f"result: {name}",
            title_align="left",
            border_style=style,
            padding=(0, 1),
        )
    )


def plan(steps: list[str], note: str = "") -> None:
    if not steps:
        warn("No plan has been set yet.")
        return
    table = Table(
        title="Plan" + (f" - {note}" if note else ""),
        title_style="bold cyan",
        show_header=True,
        header_style="dim",
        border_style="cyan",
        expand=False,
    )
    table.add_column("#", justify="right", width=3)
    table.add_column("Step")
    for index, step in enumerate(steps, start=1):
        table.add_row(str(index), Text(step))
    console.print(table)


def confirm_tool(name: str, arguments: dict[str, Any]) -> bool:
    """Ask the user to approve a sensitive tool call."""

    console.print()
    console.print(
        Panel(
            Text(_preview_arguments(name, arguments)),
            title=f"approval required: {name}",
            title_align="left",
            border_style="yellow",
            padding=(0, 1),
        )
    )
    if not sys.stdin.isatty():
        warn("Non-interactive session: action denied automatically.")
        return False
    try:
        return bool(Confirm.ask("Allow this action?", default=False))
    except (EOFError, KeyboardInterrupt):
        console.print()
        return False


@contextmanager
def thinking(label: str = "Mirsad is thinking") -> Iterator[None]:
    with console.status(f"[cyan]{label}...[/]", spinner="dots"):
        yield


def user_prompt() -> str:
    try:
        return Prompt.ask("[bold cyan]You[/]")
    except EOFError:
        return "/exit"


def kv_table(title: str, rows: list[tuple[str, str]]) -> None:
    table = Table(
        title=title, title_style="bold cyan", show_header=False, border_style="cyan"
    )
    table.add_column("Key", style="dim", no_wrap=True)
    table.add_column("Value")
    for key, value in rows:
        table.add_row(key, Text(str(value)))
    console.print(table)


def _preview_arguments(name: str, arguments: dict[str, Any]) -> str:
    if name == "run_command":
        return str(arguments.get("command", ""))

    if name in {"write_file", "edit_file"}:
        path = str(arguments.get("path", ""))
        if name == "write_file":
            content = str(arguments.get("content", ""))
            preview = content if len(content) <= 1200 else content[:1200] + "\n..."
            return f"path: {path}\n\n{preview}"
        old = str(arguments.get("old_string", ""))
        new = str(arguments.get("new_string", ""))
        return f"path: {path}\n\n- old:\n{old[:600]}\n\n+ new:\n{new[:600]}"

    try:
        return json.dumps(arguments, ensure_ascii=False, indent=2)[:1600]
    except (TypeError, ValueError):
        return str(arguments)[:1600]


class RichAgentEvents(AgentEvents):
    """Route agent events to the Rich terminal interface."""

    def thinking(self, label: str):
        return thinking(label)

    def assistant(self, text: str) -> None:
        assistant(text)

    def tool_call(
        self, name: str, arguments: dict[str, Any], call_id: str = ""
    ) -> None:
        tool_call(name, arguments)

    def tool_result(self, name: str, result: str, call_id: str = "") -> None:
        tool_result(name, result)

    def plan(self, steps: list[str], note: str = "") -> None:
        plan(steps, note)

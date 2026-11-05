"""Build the default Hermes toolset."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path

from . import files, web
from .registry import Tool, ToolRegistry

PlanCallback = Callable[[list[str], str], str]


def build_registry(
    workdir: Path,
    plan_callback: PlanCallback | None = None,
) -> ToolRegistry:
    """Create a registry whose file/shell tools are scoped to *workdir*."""

    registry = ToolRegistry()

    registry.register(
        Tool(
            name="read_file",
            description=(
                "Read a UTF-8 text file inside the workspace. Returns numbered lines. "
                "Use start_line/end_line for large files. Always read a file before "
                "editing it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path, relative to the workspace.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "First line to read (1-based). Default 1.",
                        "default": 1,
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to read. 0 means up to 500 lines from start.",
                        "default": 0,
                    },
                },
                "required": ["path"],
            },
            func=partial(files.read_file, workdir),
        )
    )

    registry.register(
        Tool(
            name="write_file",
            description=(
                "Create or overwrite a UTF-8 text file inside the workspace. Parent "
                "directories are created automatically. Prefer edit_file for small "
                "changes to existing files."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path."},
                    "content": {
                        "type": "string",
                        "description": "Complete new file content.",
                    },
                },
                "required": ["path", "content"],
            },
            func=partial(files.write_file, workdir),
            requires_approval=True,
        )
    )

    registry.register(
        Tool(
            name="edit_file",
            description=(
                "Replace one exact occurrence of old_string with new_string in an "
                "existing file. old_string must be unique in the file and include "
                "exact indentation. Read the file first."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path."},
                    "old_string": {
                        "type": "string",
                        "description": "Exact text to replace (must be unique).",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement text.",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
            func=partial(files.edit_file, workdir),
            requires_approval=True,
        )
    )

    registry.register(
        Tool(
            name="list_files",
            description=(
                "List files and directories in the workspace. Useful for exploring a "
                "project before reading files. Common heavy directories (.git, "
                "node_modules, venv) are skipped."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory to list. Default '.'.",
                        "default": ".",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern such as '*.py'. Default '*'.",
                        "default": "*",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Search subdirectories. Default true.",
                        "default": True,
                    },
                },
                "required": [],
            },
            func=partial(files.list_files, workdir),
        )
    )

    registry.register(
        Tool(
            name="search_text",
            description=(
                "Search text files in the workspace for a literal string or regular "
                "expression. Returns file:line matches. Great for finding symbols "
                "before reading a file."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text or regex to find."},
                    "path": {
                        "type": "string",
                        "description": "Directory or file to search. Default '.'.",
                        "default": ".",
                    },
                    "glob": {
                        "type": "string",
                        "description": "File glob filter, e.g. '*.py'. Default '*'.",
                        "default": "*",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum matches to return (1-200). Default 50.",
                        "default": 50,
                    },
                    "use_regex": {
                        "type": "boolean",
                        "description": "Treat query as a regular expression. Default false.",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
            func=partial(files.search_text, workdir),
        )
    )

    registry.register(
        Tool(
            name="run_command",
            description=(
                "Run a shell command in the workspace and return its exit code and "
                "output. On Windows it uses PowerShell; on Unix, bash. Use it to run "
                "tests, builds, linters, and git. Destructive system-wide commands "
                "are blocked. Requires user approval."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command line to execute.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (1-600). Default 60.",
                        "default": 60,
                    },
                },
                "required": ["command"],
            },
            func=partial(files.run_command, workdir),
            requires_approval=True,
        )
    )

    registry.register(
        Tool(
            name="web_search",
            description=(
                "Search the public web and return titles, URLs, and snippets. Useful "
                "for current documentation, errors, and unknown APIs."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results (1-10). Default 5.",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            func=web.web_search,
        )
    )

    registry.register(
        Tool(
            name="web_fetch",
            description=(
                "Fetch a public web page or text/JSON document and return readable "
                "text. Private/local addresses are blocked."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Public http(s) URL."},
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return. Default 9000.",
                        "default": 9000,
                    },
                },
                "required": ["url"],
            },
            func=web.web_fetch,
        )
    )

    def update_plan(steps: list[str], note: str = "") -> str:
        cleaned = [str(step).strip() for step in steps if str(step).strip()]
        if not cleaned:
            return "Error: plan must contain at least one step."
        if len(cleaned) > 20:
            return "Error: keep the plan to at most 20 steps."
        if plan_callback is None:
            return "Plan recorded."
        return plan_callback(cleaned, str(note or ""))

    registry.register(
        Tool(
            name="update_plan",
            description=(
                "Create or replace the visible task plan. Call this at the start of "
                "any multi-step task, then update it as work progresses. Steps should "
                "be short, concrete, and verifiable."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of task steps.",
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional short note about the plan.",
                        "default": "",
                    },
                },
                "required": ["steps"],
            },
            func=update_plan,
        )
    )

    return registry


__all__ = ["Tool", "ToolRegistry", "build_registry"]

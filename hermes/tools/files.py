"""File and shell tools available to the agent."""

from __future__ import annotations

import platform
import re
import subprocess
from pathlib import Path

MAX_READ_BYTES = 1_000_000
MAX_READ_LINES = 500
MAX_OUTPUT_CHARS = 12_000

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    "target",
}

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff",
    ".pdf", ".zip", ".gz", ".tar", ".7z", ".rar", ".exe", ".dll", ".so",
    ".dylib", ".pyc", ".pyo", ".class", ".jar", ".mp3", ".mp4", ".mov",
    ".avi", ".woff", ".woff2", ".ttf", ".otf", ".sqlite", ".db",
}

# Commands that are refused regardless of approval. These target destructive
# system-wide operations, not ordinary project work.
_DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\s+(/|~|\$home)(\s|$)", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\s+--no-preserve-root\b", re.IGNORECASE),
    re.compile(r"\bmkfs(\.[a-z0-9]+)?\b", re.IGNORECASE),
    re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
    re.compile(r"\bdiskpart\b", re.IGNORECASE),
    re.compile(r"\b(shutdown|reboot|halt|poweroff)\b", re.IGNORECASE),
    re.compile(r"\bremove-item\b[^\n]*\b-recurse\b[^\n]*([a-z]:\\(?:\s|$)|\s/\s*$)", re.IGNORECASE),
    re.compile(r"\bdel\s+/[fsq]\b[^\n]*[a-z]:\\(?:\s|$)", re.IGNORECASE),
    re.compile(r"\brd\s+/s\s+/q\s+[a-z]:\\?(?:\s|$)", re.IGNORECASE),
    re.compile(r"\bdd\s+if=.*\bof=/dev/(sd|nvme|hd)", re.IGNORECASE),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:", re.IGNORECASE),
]


class ToolError(RuntimeError):
    """A recoverable tool error shown to the model."""


def _resolve(workdir: Path, raw: str) -> Path:
    """Resolve *raw* inside the workspace, rejecting path escapes."""

    if not raw or not str(raw).strip():
        raise ToolError("Path must not be empty.")
    candidate = Path(str(raw)).expanduser()
    root = Path(workdir).resolve()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise ToolError(f"Could not resolve path '{raw}': {exc}") from exc
    if resolved != root and root not in resolved.parents:
        raise ToolError(
            f"Path '{raw}' is outside the workspace ({root}). "
            "Only files inside the workspace can be accessed."
        )
    return resolved


def _read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        return handle.read()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text) - limit} characters omitted]"


# ── file tools ──────────────────────────────────────────────────────────


def read_file(
    workdir: Path,
    path: str,
    start_line: int = 1,
    end_line: int = 0,
) -> str:
    target = _resolve(workdir, path)
    if target.is_dir():
        raise ToolError(f"'{path}' is a directory. Use list_files instead.")
    if not target.is_file():
        raise ToolError(f"File not found: {path}")
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        raise ToolError(
            f"File is {size:,} bytes, larger than the {MAX_READ_BYTES:,} byte "
            "limit. Read it in smaller pieces with start_line/end_line, or use "
            "search_text."
        )

    lines = _read_text(target).splitlines()
    total = len(lines)
    start = max(1, int(start_line or 1))
    end = int(end_line or 0)
    if start > total:
        return f"File has only {total} lines; start_line={start} is past the end."

    if end <= 0:
        end = start + MAX_READ_LINES - 1
    else:
        end = min(end, start + MAX_READ_LINES - 1)
    end = min(end, total)

    numbered = [f"{number:>5} | {lines[number - 1]}" for number in range(start, end + 1)]
    header = f"# {target.relative_to(Path(workdir).resolve())} (lines {start}-{end} of {total})"
    body = "\n".join(numbered)
    if end < total:
        body += f"\n... ({total - end} more lines; call read_file with start_line={end + 1})"
    return _truncate(f"{header}\n{body}")


def write_file(workdir: Path, path: str, content: str) -> str:
    target = _resolve(workdir, path)
    if target.is_dir():
        raise ToolError(f"'{path}' is a directory.")
    content = "" if content is None else str(content)
    existed = target.is_file()
    _write_text(target, content)
    action = "Overwrote" if existed else "Created"
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return f"{action} {target.relative_to(Path(workdir).resolve())} ({line_count} lines, {len(content)} bytes)."


def edit_file(workdir: Path, path: str, old_string: str, new_string: str) -> str:
    target = _resolve(workdir, path)
    if not target.is_file():
        raise ToolError(f"File not found: {path}")
    if old_string == new_string:
        raise ToolError("old_string and new_string are identical; nothing to change.")

    text = _read_text(target)
    occurrences = text.count(old_string)
    if occurrences == 0:
        raise ToolError(
            "old_string was not found. Read the file again and copy the exact text, "
            "including indentation."
        )
    if occurrences > 1:
        raise ToolError(
            f"old_string occurs {occurrences} times. Add more surrounding context so "
            "the edit is unambiguous."
        )

    updated = text.replace(old_string, new_string, 1)
    _write_text(target, updated)
    line_number = text[: text.index(old_string)].count("\n") + 1
    return f"Edited {target.relative_to(Path(workdir).resolve())} at line {line_number}."


def list_files(
    workdir: Path,
    path: str = ".",
    pattern: str = "*",
    recursive: bool = True,
) -> str:
    base = _resolve(workdir, path)
    if base.is_file():
        return str(base.relative_to(Path(workdir).resolve()))

    max_entries = 300
    iterator = base.rglob(pattern) if recursive else base.glob(pattern)
    entries: list[str] = []
    for item in iterator:
        try:
            relative = item.relative_to(base)
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        try:
            display = relative.as_posix()
            if item.is_dir():
                entries.append(f"{display}/")
            else:
                entries.append(f"{display}  ({_human_size(item.stat().st_size)})")
        except OSError:
            continue
        if len(entries) >= max_entries:
            break

    if not entries:
        return f"No files matching '{pattern}' under '{path}'."
    entries.sort(key=lambda value: (not value.endswith("/"), value.lower()))
    header = f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} under {path}:"
    body = "\n".join(entries)
    if len(entries) >= max_entries:
        body += f"\n... (limited to {max_entries} entries)"
    return _truncate(f"{header}\n{body}")


def search_text(
    workdir: Path,
    query: str,
    path: str = ".",
    glob: str = "*",
    max_results: int = 50,
    use_regex: bool = False,
) -> str:
    if not query:
        raise ToolError("query must not be empty.")
    base = _resolve(workdir, path)
    max_results = max(1, min(int(max_results or 50), 200))

    matcher: re.Pattern[str]
    try:
        matcher = re.compile(query if use_regex else re.escape(query), re.IGNORECASE)
    except re.error as exc:
        raise ToolError(f"Invalid regular expression: {exc}") from exc

    files = [base] if base.is_file() else base.rglob(glob)
    hits: list[str] = []
    scanned = 0
    for item in files:
        if len(hits) >= max_results:
            break
        if not item.is_file() or item.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            relative_parts = item.relative_to(base if base.is_dir() else base.parent).parts
        except ValueError:
            relative_parts = item.parts
        if any(part in SKIP_DIRS for part in relative_parts):
            continue
        try:
            if item.stat().st_size > 2_000_000:
                continue
            scanned += 1
            text = _read_text(item)
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if matcher.search(line):
                display = item.relative_to(Path(workdir).resolve())
                snippet = line.strip()
                if len(snippet) > 220:
                    snippet = snippet[:220] + "..."
                hits.append(f"{display}:{line_number}: {snippet}")
                if len(hits) >= max_results:
                    break

    if not hits:
        return f"No matches for '{query}' in {scanned} scanned file(s)."
    header = f"{len(hits)} match(es) for '{query}' (scanned {scanned} files):"
    suffix = "\n... (increase max_results to see more)" if len(hits) >= max_results else ""
    return _truncate(header + "\n" + "\n".join(hits) + suffix)


# ── shell tool ──────────────────────────────────────────────────────────


def run_command(workdir: Path, command: str, timeout: int = 60) -> str:
    command = str(command or "").strip()
    if not command:
        raise ToolError("command must not be empty.")

    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(command):
            raise ToolError(
                "Blocked: this command looks system-destructive. Refusing to run it."
            )

    try:
        timeout_seconds = max(1, min(int(timeout or 60), 600))
    except (TypeError, ValueError):
        timeout_seconds = 60

    if platform.system() == "Windows":
        argv = [
            "powershell",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ]
    else:
        argv = ["bash", "-lc", command]

    try:
        completed = subprocess.run(
            argv,
            cwd=str(workdir),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        partial = _decode_timeout_output(exc)
        return _truncate(
            f"Error: command timed out after {timeout_seconds}s."
            + (f"\nPartial output:\n{partial}" if partial else "")
        )
    except FileNotFoundError as exc:
        raise ToolError(f"Shell not found: {exc}") from exc
    except OSError as exc:
        raise ToolError(f"Could not run command: {exc}") from exc

    parts: list[str] = []
    if completed.stdout.strip():
        parts.append(completed.stdout.rstrip())
    if completed.stderr.strip():
        parts.append("[stderr]\n" + completed.stderr.rstrip())
    if not parts:
        parts.append("(no output)")
    body = "\n".join(parts)
    return _truncate(f"Exit code: {completed.returncode}\n{body}")


def _decode_timeout_output(exc: subprocess.TimeoutExpired) -> str:
    chunks: list[str] = []
    for value in (exc.stdout, exc.stderr):
        if isinstance(value, bytes):
            chunks.append(value.decode("utf-8", errors="replace"))
        elif value:
            chunks.append(str(value))
    return "\n".join(chunk.strip() for chunk in chunks if chunk.strip())


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"

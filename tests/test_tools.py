from __future__ import annotations

from hermes.tools import build_registry


def _allow(tool, arguments):
    return True


def _deny(tool, arguments):
    return False


def test_write_read_edit_and_search(tmp_path):
    registry = build_registry(tmp_path)

    created = registry.execute(
        "write_file",
        {"path": "src/hello.py", "content": "def hello():\n    return 'hi'\n"},
        approve=_allow,
    )
    assert "Created" in created

    read = registry.execute("read_file", {"path": "src/hello.py"})
    assert "def hello()" in read
    assert "lines 1-2 of 2" in read

    edited = registry.execute(
        "edit_file",
        {
            "path": "src/hello.py",
            "old_string": "return 'hi'",
            "new_string": "return 'hello'",
        },
        approve=_allow,
    )
    assert "Edited" in edited
    assert "return 'hello'" in (tmp_path / "src" / "hello.py").read_text(encoding="utf-8")

    listed = registry.execute("list_files", {"path": "src", "pattern": "*.py"})
    assert "hello.py" in listed

    found = registry.execute("search_text", {"query": "hello", "path": "src"})
    assert "hello.py:2" in found


def test_approval_is_required(tmp_path):
    registry = build_registry(tmp_path)

    denied = registry.execute(
        "write_file", {"path": "x.txt", "content": "data"}, approve=_deny
    )
    assert "denied" in denied.lower()
    assert not (tmp_path / "x.txt").exists()

    denied_without_callback = registry.execute(
        "write_file", {"path": "x.txt", "content": "data"}
    )
    assert "denied" in denied_without_callback.lower()


def test_path_escape_is_blocked(tmp_path):
    registry = build_registry(tmp_path)
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")

    result = registry.execute("read_file", {"path": "../outside-secret.txt"})
    assert "outside the workspace" in result


def test_command_runs_and_blocks_destructive(tmp_path):
    registry = build_registry(tmp_path)

    result = registry.execute(
        "run_command", {"command": "echo hermes-ok"}, approve=_allow
    )
    assert "hermes-ok" in result
    assert "Exit code: 0" in result

    blocked = registry.execute(
        "run_command", {"command": "rm -rf /"}, approve=_allow
    )
    assert "Blocked" in blocked

    blocked_windows = registry.execute(
        "run_command",
        {"command": r"rd /s /q C:\Users"},
        approve=_allow,
    )
    assert "Blocked" in blocked_windows


def test_command_handles_arabic_output(tmp_path):
    registry = build_registry(tmp_path)
    result = registry.execute(
        "run_command", {"command": "echo مرحبا"}, approve=_allow
    )
    assert "مرحبا" in result


def test_read_file_handles_cp1256(tmp_path):
    (tmp_path / "arabic.txt").write_bytes("مرحبا بالعالم".encode("cp1256"))
    registry = build_registry(tmp_path)

    result = registry.execute("read_file", {"path": "arabic.txt"})

    assert "مرحبا بالعالم" in result


def test_edit_file_handles_crlf(tmp_path):
    path = tmp_path / "crlf.txt"
    path.write_bytes(b"line one\r\nline two\r\n")
    registry = build_registry(tmp_path)

    result = registry.execute(
        "edit_file",
        {
            "path": "crlf.txt",
            "old_string": "line one\nline two",
            "new_string": "line one\nline three",
        },
        approve=_allow,
    )

    assert "Edited" in result
    assert path.read_bytes() == b"line one\r\nline three\r\n"


def test_unknown_tool_and_arguments(tmp_path):
    registry = build_registry(tmp_path)

    assert "unknown tool" in registry.execute("nope", {}).lower()
    assert "unknown argument" in registry.execute(
        "read_file", {"path": "x", "bogus": 1}
    ).lower()
    assert "missing required argument" in registry.execute("read_file", {}).lower()


def test_update_plan_callback(tmp_path):
    captured = {}

    def callback(steps, note):
        captured["steps"] = steps
        captured["note"] = note
        return "Plan updated."

    registry = build_registry(tmp_path, plan_callback=callback)
    result = registry.execute(
        "update_plan", {"steps": ["inspect", "implement"], "note": "v1"}
    )

    assert result == "Plan updated."
    assert captured == {"steps": ["inspect", "implement"], "note": "v1"}


def test_read_file_rejects_directory(tmp_path):
    registry = build_registry(tmp_path)
    result = registry.execute("read_file", {"path": "."})
    assert "directory" in result.lower()

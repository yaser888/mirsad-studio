from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from mirsad import cli


class _Handler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict]] = []

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("authorization"),
                "body": body,
            }
        )

        if len(type(self).requests) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps(
                                {"path": "e2e.txt", "content": "hello from e2e\n"}
                            ),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": "Wrote the file successfully."}
            finish_reason = "stop"

        payload = json.dumps(
            {
                "choices": [
                    {"message": message, "finish_reason": finish_reason}
                ]
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


def test_cli_end_to_end_with_local_openai_server(tmp_path, monkeypatch, capsys):
    _Handler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        monkeypatch.setenv("MIRSAD_BASE_URL", f"http://127.0.0.1:{port}/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setattr(cli, "SESSIONS_DIR", tmp_path / "sessions")
        monkeypatch.setattr(cli, "bootstrap_env", lambda: None)

        exit_code = cli.main(
            [
                "ask",
                "Write e2e.txt",
                "--provider",
                "openai",
                "--model",
                "fake-model",
                "--workdir",
                str(tmp_path),
                "--yes",
                "--json",
            ]
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["answer"] == "Wrote the file successfully."
    assert (tmp_path / "e2e.txt").read_text(encoding="utf-8") == "hello from e2e\n"

    assert len(_Handler.requests) == 2
    first = _Handler.requests[0]
    assert first["path"] == "/v1/chat/completions"
    assert first["authorization"] == "Bearer test-key"
    assert any(
        spec["function"]["name"] == "write_file"
        for spec in first["body"]["tools"]
    )

    second = _Handler.requests[1]
    messages = second["body"]["messages"]
    assert any(message.get("role") == "tool" for message in messages)
    tool_message = next(message for message in messages if message.get("role") == "tool")
    assert "Created e2e.txt" in tool_message["content"]

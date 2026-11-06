# Architecture

Mirsad is one agent runtime with two front ends. The desktop Studio and the
terminal client share the same loop, tools, sessions, providers, policy engine,
and audit ledger. This document explains the layers, the data flow, and the
decisions that keep the two surfaces consistent.

## 1. Design goals

1. **One engine, two surfaces.** No desktop-only agent logic and no CLI-only
   behavior. The loop emits events; each front end renders them.
2. **A narrow privilege boundary.** The UI is a local presentation layer. It
   reaches the runtime through explicit QWebChannel slots, never through file
   system or process APIs.
3. **Security at the tool boundary.** Approval, workspace resolution, secret
   detection, destructive-command policy, and risk scoring live below the model
   and below the UI, in the tool registry.
4. **Evidence by default.** Security-relevant actions append to a hash-chained
   ledger, and the UI can verify it.
5. **Boring persistence.** JSON files with atomic replacement. No database, no
   background service, no lock-in.
6. **Graceful degradation.** The Studio can run in demo mode without QWebChannel
   for previews and screenshots; the CLI works without PySide6 at all.
7. **English interface, multilingual work.** The UI is English-only and forces
   English numeric formatting. The agent responds in the language of the user's
   request.

## 2. Layers

```text
┌────────────────────────────────────────────────────────────────────┐
│ Front ends                                                         │
│  · Mirsad Studio (PySide6 + QtWebEngine + QWebChannel)             │
│  · Mirsad Agent CLI (argparse + Rich)                              │
├────────────────────────────────────────────────────────────────────┤
│ Front-end adapters                                                 │
│  · events.AgentEvents          (no-op contract)                    │
│  · ui.RichAgentEvents          (terminal renderer)                 │
│  · desktop.bridge._BridgeEvents (Qt signals + audit)               │
├────────────────────────────────────────────────────────────────────┤
│ Agent runtime                                                      │
│  · Agent.run_turn              plan → act → observe → repeat       │
│  · memory.SessionStore         atomic JSON sessions                │
│  · prompts.build_system_prompt workspace-aware system prompt       │
├────────────────────────────────────────────────────────────────────┤
│ Capabilities                                                       │
│  · providers/                  OpenAI-compatible, Anthropic        │
│  · tools/                      file, shell, web, plan              │
│  · security/                   policy, risk, redaction, vault,     │
│                                audit                               │
└────────────────────────────────────────────────────────────────────┘
```

The dependency direction is downward. The agent does not import the desktop
package. The desktop package imports the runtime. The CLI does the same.

## 3. The agent loop

`Agent.run_turn()` is the unit of work:

```text
append user message and save
for step in 1..max_steps:
    emit step(step, total)
    ask the provider with system prompt + trimmed history + tool schemas
    normalize assistant tool calls, assign unique IDs, save
    if no tool calls:
        return final assistant text
    for each tool call:
        check cancellation
        emit tool_call(name, arguments, id)
        registry.execute(name, arguments, approve=callback)
        emit tool_result(name, result, id)
        append tool message and save
ask the model for a summary without tools
return summary
```

Important properties:

- **Tool-call pairing is preserved.** Assistant messages retain `tool_calls`,
  and tool results carry the matching `tool_call_id`. Duplicate provider IDs are
  suffixed deterministically.
- **Every transition is persisted.** A crash or cancellation leaves a readable
  session, not a half-written file. Saves use a temporary file plus
  `os.replace`.
- **Cancellation is checked between steps and before each tool.** When a run is
  cancelled, pending tool calls are closed with an “interrupted” tool result so
  the transcript remains valid for the next provider call.
- **The step limit is a real stop.** At the limit, the runtime asks for a summary
  with tools disabled, rather than silently continuing.

## 4. Event contract

`mirsad/events.py` defines the front-end-neutral hook surface:

| Event | Payload | Terminal | Studio |
|---|---|---|---|
| `thinking(label)` | Context manager | Spinner | Typing indicator |
| `step(step, total)` | Integers | Status line | Plan progress |
| `assistant(text)` | Markdown string | Rendered answer | Chat transcript |
| `tool_call(name, args, id)` | Tool name, dict, ID | Tool panel | Activity card + audit |
| `tool_result(name, result, id)` | Tool name, text, ID | Result preview | Tool card update |
| `plan(steps, note)` | List of steps | Plan table | Plan panel |

The default implementation is a no-op. A front end overrides only what it
needs. This is why adding a new surface does not require changing the loop.

## 5. Studio architecture

### 5.1 Native shell

`desktop/window.py` creates a `QMainWindow` containing a `QWebEngineView`.
The page is a custom `StudioPage` subclass that:

- Allows only the bundled `index.html` as a main-frame navigation target.
- Refuses to create new windows.
- Routes JavaScript console messages into the Python logger at debug level.

The `QWebEngineProfile` is local and non-persistent: no HTTP cache, no
persistent cookies, English accept language, plugins and PDF viewer disabled,
local content denied remote URL access, and insecure content disallowed.

### 5.2 Bridge

`desktop/bridge.py` exposes a `StudioBridge(QObject)` to JavaScript through
`QWebChannel`. Slots include:

```text
bootstrap()                 get_state()               new_session()
load_session(id)            delete_session(id)        send_message(text)
cancel_run()                verify_audit()            audit_entries()
save_settings(json)         save_api_key(provider, key)
remove_api_key(provider)    choose_workspace()        resolve_approval(id, bool)
open_external(url)          shutdown()
```

Signals are a single `event(name, payloadJson)` channel. The front end switches
on the event name. Python emits state snapshots and deltas:

```text
state, sessions, session, session.header, session.sync,
user, assistant, tool, plan, step, typing, run, error,
audit, toast, approval.requested, approval.resolved
```

The bridge is the only place where Qt types and the runtime meet. It is also
where payloads are sanitized: session messages, tool arguments, plan steps, and
audit details pass through redaction before serialization.

### 5.3 Threading and approvals

A run executes on a Python thread so the Qt event loop stays responsive.

- The agent receives an approval callback that creates a `_PendingApproval`,
  emits `approval.requested`, and blocks on a `threading.Event`.
- The UI calls `resolve_approval(request_id, approved)` from the Qt thread,
  which sets the event and unblocks the worker.
- Cancellation sets a flag checked by the agent. If an approval is pending when
  the run is cancelled, it is denied and released.
- `shutdown()` denies any pending approval, requests cancellation, and joins
  the worker with a bounded timeout.

Qt signals are emitted from the worker thread. Qt queues them to the main
thread automatically because the bridge object lives in the main thread.

### 5.4 Interface

`desktop/web/` is a static application:

- `index.html` — semantic shell, inline SVG sprite, CSP.
- `styles.css` — editorial dark theme, responsive and compact-height layouts.
- `app.js` — state store, routing, QWebChannel bootstrap, demo adapter, Markdown
  renderer, tool cards, approvals, audit ledger, settings, command palette.

The interface boots in one of two modes:

1. **Live.** `qwebchannel.js` loads, the bridge is discovered, and
   `bootstrap()` returns real state.
2. **Demo.** If QWebChannel is unavailable after a short timeout, the app uses
   an in-memory demo adapter with sample sessions and audit entries. This keeps
   screenshots and browser previews functional without weakening the live path.

The UI keeps a small state object (`App`) and re-renders specific regions rather
than the whole document. Markdown is rendered by a custom parser that escapes
HTML first, then applies a constrained subset of formatting. Remote images and
raw HTML are not trusted.

### 5.5 Locale and rendering

The application forces `QLocale("en_US")`, Chromium `--lang=en-US`, and English
date formatting in JavaScript. This keeps digits, times, and numeric sequences
in Latin form on Arabic-locale Windows installations. The content language of
the agent is unaffected; only presentation is normalized.

The window requests a dark native title bar through DWM on Windows. On other
platforms, the standard window frame is used.

## 6. Persistence

### 6.1 Files

```text
~/.mirsad/
├── config.json        provider, model, limits, workspace, auto_approve
├── .env               optional keys and environment defaults
├── sessions/          one JSON file per session
├── vault.dat          DPAPI envelope with provider keys
├── audit.jsonl        hash-chained evidence
└── audit.jsonl.lock   one-byte cross-process lock
```

`MIRSAD_HOME` relocates the whole directory.

### 6.2 Session format

```json
{
  "id": "20261106-183012-a1b2",
  "created_at": "2026-11-06T18:30:12+00:00",
  "updated_at": "2026-11-06T18:34:51+00:00",
  "provider": "openai",
  "model": "gpt-4o-mini",
  "workdir": "C:\\Users\\you\\project",
  "plan": ["Inspect the project", "Run the tests", "Report"],
  "messages": [
    {"role": "user", "content": "..."},
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_1",
          "type": "function",
          "function": {"name": "read_file", "arguments": "{\"path\":\"app.py\"}"}
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_1",
      "name": "read_file",
      "content": "..."
    }
  ]
}
```

Session IDs match `[A-Za-z0-9_-]{1,64}` and are validated before path
construction, preventing traversal through a crafted ID.

### 6.3 Config precedence

```text
CLI flags > environment variables > config.json > defaults
```

`config.json` is merged atomically on save. `.env` loading never overwrites an
existing environment variable, and the user-level `.env` is loaded after the
project-level `.env`. Vault values are applied only when neither file nor
environment already provides the variable.

## 7. Provider layer

`providers/base.py` defines:

```python
class BaseProvider:
    name: str
    model: str

    def chat(messages, tools=None, temperature=0.2) -> AssistantTurn: ...
```

`AssistantTurn` carries either text content, a list of `ToolCall` objects, or
both. The normalized message format is OpenAI-compatible.

- `openai_compat.py` serves OpenAI, OpenRouter, DeepSeek, Groq, and Ollama,
  with provider-specific base URLs and headers.
- `anthropic.py` translates the normalized message list into Anthropic's native
  message and tool format, then translates the response back.
- `factory.py` resolves the provider spec, key, model, and base URL; it reports
  key status for the UI without revealing values.

Provider errors are translated into `ProviderError` or `MissingAPIKey`, which
the CLI prints and the bridge sends to the UI as an error event.

## 8. Tool layer

Every tool is a `Tool` dataclass with:

- JSON-schema parameters used for the model's tool definition.
- A callable bound to the workspace.
- A `requires_approval` flag.

`ToolRegistry.execute()` validates unknown tools, missing required arguments,
and unknown arguments before doing any work. It then invokes the approval
callback when required, calls the function, catches exceptions into a model-
readable error string, and truncates oversized output.

File resolution, secret guards, and destructive-command checks happen inside
the tool functions, not in the model prompt. A prompt instruction is not a
security control; a Python check is.

## 9. Audit protocol

`security/audit.py` implements an append-only JSONL ledger.

### Entry canonicalization

The digest covers a canonical JSON object containing `seq`, `ts`, `event`,
`prev`, and `details`, with sorted keys and compact separators. The `hash` field
itself is excluded. Details are redacted before hashing.

### Append

```text
acquire cross-process lock
re-read tail under the lock
compute seq = tail.seq + 1, prev = tail.hash
build entry, compute hash
append one UTF-8 line with O_APPEND
fsync
release lock
```

The re-read under the lock is essential. Caching the tail at construction time is
what caused duplicate sequences when two Studio windows started simultaneously;
the lock plus re-read makes concurrent appends linearizable.

### Verify

Verification walks the file under the same lock:

- Parse each non-empty line.
- Check `seq == expected`.
- Check `prev == previous hash`.
- Recompute the digest and compare.
- Stop at the first failure and report the line number.

The lock prevents a verification from observing a half-finished append.

### Events

Current events include:

```text
studio.opened, studio.closed
session.created, session.loaded, session.deleted
run.started, run.finished, run.cancelled, run.failed
tool.requested, tool.finished
approval.requested, approval.granted, approval.denied
settings.saved
credential.saved, credential.removed
audit.verified
```

Details contain identifiers, risk levels, tool names, argument keys, and SHA-256
digests of arguments — not raw credential values.

## 10. Packaging and launch

`pyproject.toml` defines:

- Package: `mirsad-agent`
- Console scripts: `mirsad` and `mirsad-studio`
- Core dependencies: `httpx`, `rich`
- Desktop extra: `PySide6>=6.7`
- Dev extra: `pytest`, `ruff`

The wheel contains the Python package and the entire `desktop/web` tree. The
source distribution additionally includes `tests`, `docs`, `site`, and the
README.

Launch paths:

```text
mirsad                      → CLI (defaults to chat)
mirsad studio [flags]       → lazy import of mirsad.desktop.app
mirsad-studio [flags]       → desktop entry point directly
python -m mirsad.desktop.app
python -m mirsad
```

`cmd_studio` imports the desktop package only when invoked, so a CLI-only
installation does not require PySide6. If the extra is missing, the command
prints an actionable install message and exits with status 2.

## 11. Testing strategy

The suite runs without network access and without a real model provider.

- **Agent tests** inject a fake provider and assert loop behavior, tool
  execution, plan events, and cancellation closure.
- **Event tests** verify the default no-op contract and the exact events emitted
  by a plan/tool turn.
- **Provider tests** use `httpx.MockTransport` to validate request shape and
  response normalization for OpenAI-compatible and Anthropic adapters.
- **Tool tests** exercise file operations, workspace escapes, secret guards,
  destructive commands, argument validation, and UTF-8/Arabic command output.
- **Security tests** cover redaction, secret detection, DPAPI round-trip and
  corruption handling, audit tamper detection, and real cross-process audit
  concurrency using three subprocesses.
- **Bridge tests** drive the Qt bridge without showing a window: bootstrap,
  session lifecycle, settings validation, masked keys, missing-key errors, and
  payload redaction.
- **CLI tests** cover one-shot JSON output, provider selection, empty session
  listings, and the Studio parser.
- **E2E local test** runs the agent against a local mock HTTP server to verify
  the full plan → tool → answer path over HTTP.

Visual behavior is verified separately by launching the real Qt application and
capturing screenshots in live and demo modes.

## 12. Extension points

- **New provider:** implement `BaseProvider`, register a `ProviderSpec` in
  `providers/__init__.py`, and let the factory resolve it.
- **New tool:** add a `Tool` in `tools/__init__.py` with a JSON schema and a
  callable bound to the workspace; set `requires_approval` appropriately.
- **New front end:** implement `AgentEvents`, construct an `Agent` with the
  shared settings, session store, and approval callback, and render events.
- **New audit event:** call `AuditLog.record(event, **details)`; details are
  redacted automatically.
- **New Studio surface:** add a `data-view` section, a route in `app.js`, and a
  bridge event if the surface needs new data.

## 13. Trade-offs

- **JSON over SQLite.** Sessions are human-readable and trivially portable, at
  the cost of full-file writes per message. The files are small and the write
  path is atomic.
- **Qt WebEngine over a pure native toolkit.** The HTML layer makes the editorial
  interface practical to build and iterate on; the native shell restores a real
  window, local-only loading, and a Python bridge. The cost is a larger binary
  and a Chromium runtime.
- **Pattern policy over a real sandbox.** The product is designed to be
  installable and useful without a VM or container, so approvals and heuristics
  carry the load. A future container backend could enforce the workspace
  boundary at the OS level.
- **Hash chain over external notarization.** The chain is self-contained and
  verifiable offline. It detects local modification but cannot prove integrity
  to a third party; that would require signing or an external append-only store.
- **Demo fallback.** The JavaScript demo adapter keeps previews and screenshots
  working when QWebChannel is absent. It is isolated from the live path and
  never writes to real state.

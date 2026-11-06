# Security model

Mirsad is a local-first agent that can read files, write files, and run shell
commands on your machine. That is the point — and it is also the risk. This
document describes what the product protects, how each control works, and where
the boundaries are.

> **Positioning.** Mirsad is hardened, not invincible. It does not claim to be
> an “unbreakable” sandbox or a substitute for OS-level isolation. The agent
> runs with the permissions of the desktop user. The controls below reduce blast
> radius and make behavior visible; they do not make arbitrary agent execution
> risk-free.

## 1. Assets and adversaries

### Assets

- Provider API keys stored in the DPAPI vault or environment.
- Source code, configuration, and data inside the selected workspace.
- Integrity of the shell and file operations the agent performs.
- Integrity and readability of the audit ledger.
- Session transcripts, which may contain sensitive project context.

### Adversaries and failure modes

| Threat | Example |
|---|---|
| Prompt injection | A fetched web page or repository file tells the model to exfiltrate `.env` or run a destructive command. |
| Model error | The model chooses a broad `rm`, a wrong path, or a large overwrite. |
| Credential leakage | A key is printed, logged, echoed into a session, or sent to the UI. |
| Workspace escape | A path such as `..\..\Windows` or a symlink points outside the project. |
| Local tampering | Another process edits or truncates the audit ledger. |
| Concurrent writers | Studio, the CLI, or multiple Studio windows append at once. |
| Interface compromise | A malicious page or remote resource is loaded into the desktop shell. |
| Supply chain | A compromised dependency or model provider. |

## 2. Trust boundaries

```text
┌─────────────────────────────── Windows user session ───────────────────────────────┐
│                                                                                    │
│  Studio window (local bundled UI)          Terminal                                 │
│        │ QWebChannel only                       │                                  │
│        ▼                                        ▼                                  │
│  ┌─────────────────────── Python agent runtime ────────────────────────┐           │
│  │  policy → risk → approval → tool registry → workspace tools         │           │
│  │  redaction → session store → audit log                              │           │
│  └───────────────┬───────────────────────────────┬─────────────────────┘           │
│                  │                               │                                 │
│        ~/.mirsad/config.json, .env        ~/.mirsad/sessions/                      │
│        ~/.mirsad/vault.dat (DPAPI)        ~/.mirsad/audit.jsonl                    │
│                                                                                    │
└────────────────────────────────────────────────────────────────────────────────────┘
                  │                                           │
                  ▼                                           ▼
          Provider API (HTTPS)                       Public web (HTTPS)
```

The Python process is the policy enforcement point. The browser interface is a
presentation layer: it cannot directly read files, spawn processes, or access
the vault. Every privileged action crosses an explicit QWebChannel slot.

## 3. Controls

### 3.1 Workspace boundary

`mirsad/tools/files.py` resolves every path against the selected workspace and
rejects escapes. The checks cover:

- Relative traversal (`..`) that resolves outside the workspace.
- Absolute paths outside the workspace.
- Symlink and junction resolution that lands outside the workspace.
- File reads, writes, edits, listings, and text searches.

The workspace is selected explicitly in Studio or with `-w/--workdir` in the
CLI. Changing it is a deliberate user action. The boundary is not a container:
a shell command can still access anything the desktop user can access. Treat
`run_command` as the highest-risk tool.

### 3.2 Approval and risk scoring

`write_file`, `edit_file`, and `run_command` require approval. The agent runtime
does not execute them when no approval callback is registered; the default is
deny.

The risk assessor (`mirsad/security/risk.py`) classifies actions:

| Level | Typical trigger |
|---|---|
| `low` | Reads, listings, searches, web fetches |
| `elevated` | Shell command or workspace file write |
| `high` | Destructive command, remote-code pipe, force push, package publish, OS configuration, absolute path, secret-shaped target, large write, credential-shaped content |

The approval dialog displays the actual command or change, the risk level, and
the reasons. Approvals are per action, not per session. Denials are returned to
the model with an instruction not to retry the same action.

`auto_approve` is off by default. When enabled it bypasses the approval prompt,
but it does **not** bypass the hard command policy or the workspace and secret
guards. The UI labels this setting as not recommended.

### 3.3 Destructive-command policy

`mirsad/security/policy.py` refuses commands that target catastrophic
system-wide state, including:

- Recursive deletion of a drive root, home directory, or `/`.
- Disk formatting and partitioning (`format`, `mkfs`, `diskpart`,
  `clear-disk`, `initialize-disk`, `format-volume`).
- Shutdown, reboot, halt, and power-off.
- Shadow-copy or backup deletion (`vssadmin delete shadows`, `wbadmin delete`).
- Registry deletion under HKLM/HKEY_LOCAL_MACHINE.
- Encoded PowerShell payloads and the classic fork bomb.
- `dd` writes to raw disks and Windows volume-encryption wipes.

These are blocked in the tool layer, after approval. The policy is intentionally
conservative and pattern-based. It can miss novel destructive commands and can
occasionally reject legitimate administration. It is a guardrail, not a formal
verifier.

### 3.4 Secret-file guard

Credential-shaped filenames are protected by default. The guard covers reads,
writes, edits, directory listings, and text searches:

- `.env`, `.env.local`, and similar variants — but not `.env.example`,
  `.env.sample`, `.env.template`, or `.env.dist`.
- `.netrc`, `.npmrc`, `.pypirc`, `.git-credentials`, `credentials.json`.
- `id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519`.
- `*.pem`, `*.key`, `*.pfx`, `*.p12`, `*.kdbx`, `*.jks`, `*.keystore`.
- `credentials.*` except explicit examples and templates.

Blocked operations return an explanatory error to the model rather than silently
returning empty content. For a deliberate, trusted task, an operator can set:

```text
MIRSAD_ALLOW_SECRET_FILES=1
```

This disables the guard globally for that process. Use it sparingly and never in
an unattended run.

### 3.5 Secret vault

Studio can store provider keys in `~/.mirsad/vault.dat`. On Windows:

- Keys are encrypted with **Windows DPAPI** (`CryptProtectData`) under the
  current user account, with application entropy.
- The file contains a JSON envelope with a version, cipher name, and Base64
  ciphertext. Plaintext keys never touch the file.
- Reads decrypt only in the current user context. Another Windows account cannot
  decrypt the vault.
- Saves are written to a temporary file and atomically replaced.
- The UI receives masked values such as `set (****abcd)`, never the key.
- Vault operations are audited by name and provider, never by value.

On non-Windows platforms the vault is unavailable and the UI reports this
plainly. Use `MIRSAD_*` environment variables there.

DPAPI protects data at rest from other users and from casual disk inspection.
It does not protect against malware running as the same user while the agent is
running, nor against a fully compromised Windows account.

### 3.6 Redaction

`mirsad/security/redact.py` removes credential-shaped content before it reaches
logs, UI events, session payloads, audit details, and risk summaries. It matches:

- OpenAI-style `sk-...` keys, including project and admin variants.
- Anthropic `sk-ant-...`, Groq `gsk_...`, OpenRouter `or-...`.
- Google API keys (`AIza...`), GitHub tokens (`ghp_...`, `github_pat_...`).
- AWS access key IDs (`AKIA...`).
- Bearer authorization headers.
- `api_key=`, `access_token:`, `secret=`, `password:` and similar assignments.
- Values under sensitive object keys such as `password`, `apiKey`,
  `access_token`, `client_secret`, `private_key`, and `authorization`.

Redaction is defense in depth, not a proof. A credential split across lines or
encoded in an unusual format may evade pattern matching. Never paste live
production credentials into a session you would not want stored on disk.

### 3.7 Hash-chained audit ledger

Every security-relevant event is appended to `~/.mirsad/audit.jsonl`. Each entry
contains:

```json
{
  "seq": 42,
  "ts": "2026-11-06T18:30:00.000+00:00",
  "event": "approval.granted",
  "details": {"tool": "run_command"},
  "prev": "<sha256 of previous entry>",
  "hash": "<sha256 of this entry's canonical fields>"
}
```

Verification walks the chain from the genesis value, checking sequence numbers,
previous-hash links, required fields, and the recomputed digest. The result
reports the first broken line. The Studio displays **VERIFIED** or **BROKEN**
consistently across Overview, Chat, Activity, and Settings.

What the chain detects:

- A changed or deleted detail, timestamp, event, or sequence number.
- A reordered, duplicated, or missing entry.
- Invalid JSON or a missing field.
- Accidental hand-editing.

What it does not prevent:

- An attacker with write access deleting the entire file and starting a new
  chain.
- An attacker recomputing every subsequent hash after editing an entry.
- Loss of the file through disk failure or ransomware.

For stronger guarantees, ship the ledger to an append-only external store or
sign entries with a key held outside the machine. The built-in chain is evidence
for the operator, not a notarization service.

#### Cross-process append protocol

Studio, the CLI, and additional Studio windows may append concurrently. Each
append takes an OS-level advisory lock on `audit.jsonl.lock`:

- Windows: `msvcrt.locking` on a one-byte lock file, with a bounded wait.
- POSIX: `flock(LOCK_EX)`.

Under the lock, the writer re-reads the tail of the ledger, computes the next
sequence and previous hash, appends a single line, flushes with `fsync`, and
releases the lock. This prevents the duplicate-sequence race that occurs when
two processes cache the same tail. A test launches three independent writer
processes and verifies all 36 entries form one valid chain.

### 3.8 Desktop hardening

The Studio shell is a Qt WebEngine view over bundled local files, not a browser
pointed at the internet.

- Main-frame navigation is restricted to the bundled `index.html`. Other local
  files and all remote URLs are blocked.
- JavaScript cannot open new windows.
- Local content cannot access remote URLs.
- Plugins and the PDF viewer are disabled.
- DNS prefetch, full-screen support, and insecure mixed content are disabled.
- The profile uses no HTTP cache, no persistent cookies, and an English accept
  language.
- External links are opened in the system browser only through an explicit
  bridge method that validates the scheme.
- The interface has a strict content-security policy in the HTML shell.
- QWebChannel exposes a narrow, typed bridge surface; no arbitrary Python
  evaluation or filesystem API is reachable from JavaScript.

The chat transcript renders model output through a controlled Markdown renderer
that escapes HTML before applying formatting. Tool arguments and results are
escaped before insertion.

### 3.9 Network behavior

- Mirsad has no telemetry and no analytics.
- The only outbound traffic is to the selected model provider, the optional web
  search backend, and URLs requested through `web_fetch`.
- `web_fetch` resolves the host and rejects private, loopback, link-local, and
  reserved addresses to reduce SSRF risk. Redirects are followed, so the final
  URL is re-checked by the client. This is not a substitute for an egress
  firewall.
- No remote content is loaded into the Studio interface.

### 3.10 Session data

Sessions are JSON files under `~/.mirsad/sessions/`. They contain the
conversation, plans, tool arguments, and tool results. They are redacted when
sent to the UI, but the on-disk session may contain sensitive project context
that was legitimately part of the task. Protect the `~/.mirsad` directory with
OS permissions and disk encryption.

Sessions are not encrypted at rest. The DPAPI vault covers provider keys, not
conversation history.

## 4. Operational guidance

- Keep `auto_approve` off unless you are supervising a short, trusted task.
- Read approval dialogs. A low-looking command can still be dangerous through
  its arguments.
- Use a dedicated workspace directory, not your entire home directory.
- Prefer a local model (Ollama) for sensitive repositories when provider policy
  allows.
- Rotate any key that you suspect was exposed, even if redaction appears to have
  caught it.
- Back up `~/.mirsad` only with encryption; it contains sessions and the vault.
- Verify the audit chain before drawing conclusions from the ledger, and
  preserve a copy before investigating tampering.
- Treat web content as untrusted input. Prompt injection is a model-level risk
  that no approval dialog can fully eliminate.

## 5. Known limitations

1. **No sandbox.** Shell commands run with the desktop user's full permissions.
   Workspace boundaries apply to file tools, not to arbitrary commands.
2. **Pattern-based policy.** Command blocking and secret detection are
   heuristics. They will miss some dangerous cases and reject some safe ones.
3. **Prompt injection.** A malicious page or file can attempt to steer the model.
   Approvals and policies reduce impact but do not remove the risk.
4. **Local audit tampering.** The chain is not externally anchored. A user or
   process with write access can rewrite it.
5. **Same-user malware.** DPAPI, redaction, and file permissions do not defend
   against malicious code already running as the same Windows user.
6. **No encrypted sessions.** Transcripts are plaintext JSON under `~/.mirsad`.
7. **Provider trust.** Prompts and tool results are sent to the selected model
   provider. Review that provider's retention and training policy.
8. **Windows-first vault.** DPAPI is Windows-only. Other platforms fall back to
   environment variables.
9. **Approval fatigue.** A user who approves without reading defeats the model.
   The UI explains risk, but it cannot enforce attention.

## 6. Reporting a vulnerability

If you find a security issue, do not open a public issue with exploit details.
Contact the maintainer privately with:

- A description of the issue and affected version.
- Reproduction steps or a proof of concept.
- The impact you believe is possible.
- Any suggested remediation.

You will receive an acknowledgment, a triage decision, and credit if you want
it. Please allow time for a fix before public disclosure.

## 7. Verification checklist

Before trusting a build:

```powershell
pytest tests/test_security.py -q
ruff check .
mirsad providers
```

Then in Studio:

1. Confirm the readiness card reports **Vault ready** on Windows.
2. Open **Audit trail** and run **Verify chain**.
3. Attempt to read `.env` through an operation; the secret guard should block it.
4. Attempt to write outside the workspace; the boundary should reject it.
5. Trigger a shell command; confirm the approval dialog shows the command, risk,
   and reasons.

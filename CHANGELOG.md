# Changelog

All notable changes to the Mirsad product are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-11-11

Commercial and operational follow-up to 0.2.0. Everything remains local-first:
no telemetry, no license server, no hosted dependency.

### Added

- Inline unified-diff preview for mutating tool approvals
  (`write_file` / `edit_file`) before the human checkpoint.
- Free AI server integrations: Google Gemini through AI Studio (free tier),
  Hugging Face serverless inference, and Groq free inference.
- White (light) UI theme for Mirsad Studio with a top-bar toggle, persisted
  on the device; native window framing adapts to the selected theme.
- `mirsad audit` subcommands from the terminal: verify the hash chain, tail
  the trail, and export it as JSON or Markdown.
- `mirsad doctor` health check: Python, home directory, config, sessions,
  audit chain, vault, desktop runtime, and provider key coverage.
- Commercial **Mirsad Pro** support: offline-signed license tokens (`activate`,
  `license`, `license issue`), and a Pro-gated standalone compliance evidence
  pack (`mirsad report`). See `docs/LICENSING.md`.
- Pricing and edition section on the marketing site.

### Security

- No claim of unbreakable protection. Controls are layered hardening with an
  explicit documented boundary; see `docs/SECURITY.md`.

## [0.2.0] - 2026-11-06

First public-style release of **Mirsad Studio** and the **Mirsad Agent** runtime.

### Added

- **Mirsad Studio desktop application** (`mirsad studio`, `mirsad-studio`).
  - Qt WebEngine shell hosting the bundled local interface via QWebChannel.
  - Surfaces: Overview, Operation, Audit trail, Control surface.
  - Approval flow with risk scoring, live tool activity, stop/cancel, toasts.
  - Command palette, keyboard shortcuts, demo mode, screenshot rendering.
  - Hardened web profile (no remote content from local pages, no persistent
    cookies, no plugins, no JS-initiated windows, navigation allow-list).

- **Security layer**
  - Windows DPAPI-backed secret vault (`~/.mirsad/vault.dat`).
  - SHA-256 hash-chained append-only audit ledger with cross-process locking.
  - Risk-scored approvals and deny-by-default tool execution.
  - Secret-file guard (`.env`, private keys, keystores, credential files).
  - Destructive-command policy for system-wide operations.
  - Credential redaction across sessions, events, audit details, and risk text.

- **Agent runtime**
  - Event hook contract (`AgentEvents`) shared by CLI and Studio.
  - Plan/act/observe loop with step budget and cancellation.
  - Persistent sessions with context trimming and tool-call pairing.

- **Documentation and marketing**
  - English-only README, `docs/SECURITY.md`, `docs/ARCHITECTURE.md`.
  - Marketing landing page at `site/index.html`.
  - Screenshot assets under `docs/assets/` and `site/assets/`.

- **Tests**
  - Security, events, desktop bridge, CLI, provider, tools, memory, and end-to-end suites.
  - Cross-process audit concurrency test.

### Fixed

- Sensitive-key redaction in structured values.
- Secret-file filtering in `list_files`.
- Cross-process audit sequence race.
- Studio audit state copy for broken chains.

## [0.1.0] - 2026-10-28

- Initial Hermes-based agent runtime: terminal chat, tools, sessions, providers,
  persistent memory, multi-provider LLM support.

[0.3.0]: https://github.com/yaser888/mirsad-studio/releases/tag/v0.3.0
[0.2.0]: https://github.com/yaser888/mirsad-studio/releases/tag/v0.2.0

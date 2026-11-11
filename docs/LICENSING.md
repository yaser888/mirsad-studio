# Mirsad licensing

Mirsad ships as a free and open **Community** edition (MIT licensed) and a paid
**Pro** edition that is unlocked with a signed license token. All verification
is performed locally; the app never phones home.

## Editions

| Edition | Price | Unlocks |
|---|---|---|
| Community | Free | The full agent, Studio, tools, audit chain, providers, themes. |
| Pro | See pricing page | Compliance evidence pack (`mirsad report`), priority support, and all future Pro features. |
| Team | Custom | Multi-seat licenses, team onboarding, dedicated support channel. |

## Activating a Pro license

```bash
mirsad activate --key MIRSAD1.<payload>.<signature>
mirsad license          # shows the current edition, status, and expiry
```

The license is stored at `~/.mirsad/license.json` and is re-verified on every
read. Editing the file invalidates the signature and returns the app to the
Community edition.

## Compliance evidence pack (Pro)

```bash
mirsad report -o evidence.html
```

Generates a standalone HTML document: edition and license details, the
audit-chain verification result, recent sessions, and recent audit events.
The file is suitable for an internal security review or an auditor. It never
opens a network connection.

## Issuing a license (owner helper)

The product owner can mint tokens with:

```bash
mirsad license issue --plan pro --to "Acme Corp" --seats 5 --days 365
mirsad license issue --plan team --to "Platform Team" --seats 25 --days 365
```

`mirsad license issue` is intentionally visible: it is a client-side helper,
not a server. Purchased customers receive tokens through the sales channel;
this command exists for evaluation and for the owner to issue keys manually.

## Security model and honest limitations

- Tokens are `MIRSAD1.<base64url-payload>.<base64url-HMAC-SHA256>`.
- The payload contains `plan`, `licensed_to`, `seats`, and `exp` (unix time,
  or `null` for a lifetime license).
- Verification is constant-time; the license file is re-verified on every use.
- **Limitation.** The default signing secret ships in the open-source client.
  A determined user can read the code and forge tokens against it. This scheme
  protects against casual copying and keeps the product easy to self-host for
  honest teams; it is not a DRM boundary.
- For production keys the owner should set `MIRSAD_LICENSE_SECRET` to a
  deployment-specific secret (and rotate it) on the machine that issues keys:

  ```bash
  MIRSAD_LICENSE_SECRET="$(openssl rand -hex 32)" mirsad license issue ...
  ```

  The client verifies with the same environment variable when present, or with
  the built-in default otherwise.
- Enterprise customers needing hard guarantees should move issuance behind an
  HSM/KMS and, if desired, a network-based activation endpoint. That is an
  infrastructure project, not a code change in this repo.

## Refund and seat terms

Seats are enforced per installation, not cryptographically. Pro licenses grant
a single installation; Team licenses grant up to the licensed seats. Refunds,
renewals, and support windows are handled outside the app in the sales channel.

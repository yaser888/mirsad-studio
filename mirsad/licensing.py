"""Offline license tokens for Mirsad editions.

Mirsad ships as an open Community edition today. A Pro edition is unlocked
with a signed token issued by the product owner. Verification is fully
offline: the client recomputes the signature and compares it in constant
time.

This is a pragmatic, indie-grade scheme. The default signing secret ships in
the source tree; the owner should override it with ``MIRSAD_LICENSE_SECRET``
for production keys and rotate it periodically. Anyone can read this code, so
a determined attacker could mint tokens against the default secret. For
enterprise deployments use a KMS/HSM-backed issuer and a distinct secret.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SECRET = "mirsad-pro-signing-key-v1"
LICENSE_PREFIX = "MIRSAD1"

LICENSE_FILE = (
    Path(os.environ.get("MIRSAD_HOME", Path.home() / ".mirsad")) / "license.json"
)


class LicenseError(RuntimeError):
    """Raised when a license token is invalid or expired."""


@dataclass(frozen=True)
class LicenseInfo:
    plan: str  # "community", "pro", or "team"
    licensed_to: str
    seats: int = 1
    expires_at: int | None = None

    @property
    def is_pro(self) -> bool:
        return self.plan in {"pro", "team"}

    @property
    def expires_label(self) -> str:
        if self.expires_at is None:
            return "lifetime"
        return (
            datetime.fromtimestamp(self.expires_at, tz=timezone.utc).date().isoformat()
        )


def _secret_bytes() -> bytes:
    return os.environ.get("MIRSAD_LICENSE_SECRET", DEFAULT_SECRET).encode("utf-8")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def issue_token(
    *,
    plan: str = "pro",
    licensed_to: str,
    seats: int = 1,
    days: int = 365,
    secret: bytes | None = None,
) -> str:
    """Issue a signed token. Owner-side helper, not for end users."""

    if plan not in {"pro", "team"}:
        raise LicenseError(f"Unknown plan: {plan}")
    if seats < 1:
        raise LicenseError("Seats must be at least 1.")
    expires = int(time.time()) + max(0, int(days)) * 86_400 if days else None
    payload = {
        "plan": plan,
        "licensed_to": str(licensed_to),
        "seats": int(seats),
        "exp": expires,
    }
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    digest = hmac.new(
        secret or _secret_bytes(), payload_b64.encode("ascii"), hashlib.sha256
    )
    return f"{LICENSE_PREFIX}.{payload_b64}.{_b64url_encode(digest.digest())}"


def verify_token(token: str, *, secret: bytes | None = None) -> LicenseInfo:
    """Verify a token. Raises LicenseError on any failure."""

    parts = (token or "").strip().split(".")
    if len(parts) != 3 or parts[0] != LICENSE_PREFIX:
        raise LicenseError("Malformed license token.")
    _, payload_b64, signature_b64 = parts
    try:
        expected = hmac.new(
            secret or _secret_bytes(), payload_b64.encode("ascii"), hashlib.sha256
        ).digest()
        provided = _b64url_decode(signature_b64)
    except (binascii.Error, ValueError) as exc:
        raise LicenseError("License signature is not valid base64.") from exc
    if not hmac.compare_digest(expected, provided):
        raise LicenseError("License signature does not match.")
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (json.JSONDecodeError, binascii.Error, ValueError) as exc:
        raise LicenseError("License payload is not valid.") from exc
    plan = str(payload.get("plan") or "community")
    if plan not in {"pro", "team"}:
        raise LicenseError(f"Unknown licensed plan: {plan}")
    expires = payload.get("exp")
    if expires is not None:
        try:
            expires = int(expires)
        except (TypeError, ValueError) as exc:
            raise LicenseError("License expiry is invalid.") from exc
        if expires < int(time.time()):
            raise LicenseError("License has expired.")
    return LicenseInfo(
        plan=plan,
        licensed_to=str(payload.get("licensed_to") or ""),
        seats=max(1, int(payload.get("seats") or 1)),
        expires_at=expires,
    )


def save_license(token: str, path: Path = LICENSE_FILE) -> LicenseInfo:
    """Verify and persist a token. Returns the verified license info."""

    info = verify_token(token)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"token": token.strip()}, indent=2) + "\n", encoding="utf-8"
    )
    return info


def load_license(path: Path = LICENSE_FILE) -> LicenseInfo:
    """Load and re-verify the persisted license. Never raises."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return verify_token(str(data.get("token") or ""))
    except (OSError, json.JSONDecodeError, LicenseError, TypeError):
        return LicenseInfo(plan="community", licensed_to="", seats=1)


def license_status(path: Path = LICENSE_FILE) -> tuple[LicenseInfo, str]:
    """Return the current license info and a human-readable one-line status."""

    info = load_license(path)
    if info.is_pro:
        return (
            info,
            f"Mirsad {info.plan.upper()} — licensed to {info.licensed_to} ({info.seats} seat(s), expires {info.expires_label}).",
        )
    return (
        info,
        "Mirsad Community — activate a Pro license with: mirsad activate --key <token>",
    )

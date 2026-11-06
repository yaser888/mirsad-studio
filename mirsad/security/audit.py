"""Append-only, hash-chained audit trail."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redact import redact_structure

GENESIS = "0" * 64
LOCK_TIMEOUT_SECONDS = 10.0


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    """Serialize access to the ledger across processes.

    The runtime does not assume a single Studio window: the terminal and more
    than one desktop process may append at the same time.  A dedicated lock
    file avoids interleaved reads of the tail.  The lock is advisory on POSIX
    and mandatory on Windows.
    """

    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "Timed out waiting for the audit log lock."
                        ) from None
                    time.sleep(0.02)
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class AuditCheck:
    ok: bool
    entries: int
    message: str
    broken_at: int | None = None


class AuditLog:
    """Write evidence entries linked by SHA-256 hashes.

    The chain detects accidental or deliberate modification after the fact. It
    is not a substitute for an external append-only store controlled by an
    administrator.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._last_hash, self._sequence = self._read_tail()

    def _read_tail(self) -> tuple[str, int]:
        if not self.path.is_file():
            return GENESIS, 0
        last_hash = GENESIS
        sequence = 0
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict) and entry.get("hash"):
                        last_hash = str(entry["hash"])
                        sequence = int(entry.get("seq") or sequence + 1)
        except OSError:
            return GENESIS, 0
        return last_hash, sequence

    @staticmethod
    def _digest(entry: dict[str, Any]) -> str:
        canonical = json.dumps(
            {
                "seq": entry["seq"],
                "ts": entry["ts"],
                "event": entry["event"],
                "prev": entry["prev"],
                "details": entry["details"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def record(self, event: str, **details: Any) -> dict[str, Any]:
        safe_details = redact_structure(details)
        with self._lock, _exclusive_lock(self.path):
            # Re-read under the cross-process lock.  Another window or the CLI
            # may have appended since this instance was constructed.
            last_hash, sequence = self._read_tail()
            entry: dict[str, Any] = {
                "seq": sequence + 1,
                "ts": _now(),
                "event": str(event),
                "details": safe_details,
                "prev": last_hash,
            }
            entry["hash"] = self._digest(entry)
            line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
            fd = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            self._last_hash = entry["hash"]
            self._sequence = entry["seq"]
            return entry

    def _read_entries(self) -> list[tuple[int, dict[str, Any] | None, str]]:
        rows: list[tuple[int, dict[str, Any] | None, str]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    rows.append((line_number, None, line))
                    continue
                rows.append(
                    (line_number, entry if isinstance(entry, dict) else {}, line)
                )
        return rows

    def verify(self) -> AuditCheck:
        if not self.path.is_file():
            return AuditCheck(True, 0, "No activity recorded yet.")
        previous = GENESIS
        count = 0
        try:
            with _exclusive_lock(self.path):
                rows = self._read_entries()
        except (OSError, TimeoutError) as exc:
            return AuditCheck(False, count, f"Could not read the audit log: {exc}")
        for line_number, entry, _raw in rows:
            if entry is None:
                return AuditCheck(
                    False,
                    count,
                    f"Line {line_number} is not valid JSON.",
                    line_number,
                )
            if not entry:
                return AuditCheck(
                    False,
                    count,
                    f"Line {line_number} is not an object.",
                    line_number,
                )
            if entry.get("seq") != count + 1:
                return AuditCheck(
                    False,
                    count,
                    f"Line {line_number} breaks the sequence.",
                    line_number,
                )
            if entry.get("prev") != previous:
                return AuditCheck(
                    False,
                    count,
                    f"Line {line_number} does not link to the previous entry.",
                    line_number,
                )
            try:
                digest = self._digest(entry)
            except (KeyError, TypeError):
                return AuditCheck(
                    False,
                    count,
                    f"Line {line_number} is missing fields.",
                    line_number,
                )
            if digest != entry.get("hash"):
                return AuditCheck(
                    False,
                    count,
                    f"Line {line_number} has been modified.",
                    line_number,
                )
            previous = str(entry["hash"])
            count += 1
        return AuditCheck(
            True,
            count,
            f"{count} {'entry' if count == 1 else 'entries'} verified.",
        )

    def tail(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            with _exclusive_lock(self.path):
                rows = self._read_entries()
        except (OSError, TimeoutError):
            return []
        entries = [entry for _line, entry, _raw in rows if entry]
        return entries[-max(1, min(int(limit), 1000)) :]

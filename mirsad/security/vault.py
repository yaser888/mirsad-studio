"""Encrypted secret storage backed by Windows DPAPI.

Keys never touch the plaintext config file. On Windows the vault is encrypted
for the current user with DPAPI; other accounts on the machine cannot decrypt
it. On other platforms the vault is unavailable and Mirsad uses environment
variables instead.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import platform
import threading
from ctypes import wintypes
from pathlib import Path

VAULT_VERSION = 1
_ENTROPY = b"mirsad-studio-vault-v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class VaultError(RuntimeError):
    """Raised when the secret vault cannot be read or written."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(
        len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
    ), buffer


def _protect(data: bytes) -> bytes:
    if platform.system() != "Windows":
        raise VaultError("Windows DPAPI is not available on this platform.")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    input_blob, input_buffer = _blob(data)
    entropy_blob, entropy_buffer = _blob(_ENTROPY)
    output_blob = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "Mirsad Studio secret vault",
        ctypes.byref(entropy_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    _ = (input_buffer, entropy_buffer)
    if not ok:
        raise VaultError(f"DPAPI encryption failed (error {ctypes.get_last_error()}).")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _unprotect(data: bytes) -> bytes:
    if platform.system() != "Windows":
        raise VaultError("Windows DPAPI is not available on this platform.")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    input_blob, input_buffer = _blob(data)
    entropy_blob, entropy_buffer = _blob(_ENTROPY)
    output_blob = _DataBlob()
    description = wintypes.LPWSTR()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        ctypes.byref(description),
        ctypes.byref(entropy_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    _ = (input_buffer, entropy_buffer)
    if description:
        kernel32.LocalFree(description)
    if not ok:
        raise VaultError(
            f"DPAPI decryption failed (error {ctypes.get_last_error()}). "
            "The vault may belong to another Windows account."
        )
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


class SecretVault:
    """A small DPAPI-protected key/value store."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        return platform.system() == "Windows"

    def _read(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            encrypted = base64.b64decode(str(envelope["data"]), validate=True)
            payload = _unprotect(encrypted)
            data = json.loads(payload.decode("utf-8"))
        except VaultError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise VaultError(f"Could not read the secret vault: {exc}") from exc
        if not isinstance(data, dict):
            raise VaultError("The secret vault has an invalid payload.")
        return {
            str(key): str(value)
            for key, value in data.items()
            if isinstance(key, str) and isinstance(value, str)
        }

    def _write(self, data: dict[str, str]) -> None:
        if not self.available:
            raise VaultError(
                "The encrypted vault is only available on Windows. "
                "Use MIRSAD_* environment variables on this platform."
            )
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        envelope = {
            "version": VAULT_VERSION,
            "cipher": "windows-dpapi",
            "data": base64.b64encode(_protect(payload)).decode("ascii"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.path)
        _restrict_file(self.path)

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._read().get(key)

    def set(self, key: str, value: str) -> None:
        key = str(key).strip()
        value = str(value or "").strip()
        if not key:
            raise VaultError("A secret key name is required.")
        if not value:
            self.delete(key)
            return
        with self._lock:
            data = self._read()
            data[key] = value
            self._write(data)

    def delete(self, key: str) -> None:
        with self._lock:
            data = self._read()
            if key not in data:
                return
            data.pop(key, None)
            self._write(data)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._read())

    def apply_to_env(self) -> None:
        """Use vault secrets only when no non-empty environment value exists."""

        if not self.available:
            return
        try:
            data = self._read()
        except VaultError:
            return
        for key, value in data.items():
            if value and not os.environ.get(key):
                os.environ[key] = value


def _restrict_file(path: Path) -> None:
    """Tighten permissions where the OS supports POSIX modes."""

    if platform.system() == "Windows":
        return
    try:
        path.chmod(0o600)
    except OSError:
        pass

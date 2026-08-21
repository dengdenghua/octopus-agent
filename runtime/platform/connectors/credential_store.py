"""加密凭据库(AES-256-GCM)。

对齐 WorkBuddy connector-states.v3.json 的凭据加密思路:
  - 主密钥随机生成,以 0600 权限存本机(~/.octopus/connectors/master.key)
  - 每个 secret 用随机 nonce + AES-256-GCM 加密,密文+nonce 存 JSON
  - 敏感值绝不明文落盘;get 时才解密

用法::

    store = CredentialStore()
    store.set_secret("westock-mcp", "access_token", "xxx")
    token = store.get_secret("westock-mcp", "access_token")
    store.delete_secret("westock-mcp", "access_token")
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import secrets
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CONNECTOR_ROOT = Path(os.path.expanduser("~/.octopus/connectors"))
MASTER_KEY_FILE = CONNECTOR_ROOT / "master.key"
CREDENTIALS_FILE = CONNECTOR_ROOT / "credentials.v1.json"
_KEY_LEN = 32  # AES-256


class CredentialStore:
    """AES-256-GCM 加密的本地凭据库(按 connector_id 分组)。"""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        master_key_file: str | Path | None = None,
        credentials_file: str | Path | None = None,
    ) -> None:
        self._root = Path(CONNECTOR_ROOT if root is None else root).expanduser()
        self._key_file = Path(
            self._root / "master.key" if master_key_file is None else master_key_file
        ).expanduser()
        self._cred_file = Path(
            self._root / "credentials.v1.json" if credentials_file is None else credentials_file
        ).expanduser()
        self._lock = threading.RLock()
        with self._lock:
            self._key = self._load_or_create_key()
            if self._cred_file.exists():
                self._ensure_private_permissions(self._cred_file)

    @staticmethod
    def _ensure_private_permissions(path: Path) -> None:
        """Ensure an existing secret-bearing file is accessible only by its owner."""

        try:
            path.chmod(0o600)
        except OSError as exc:
            raise RuntimeError(f"cannot secure connector credential file: {path}") from exc

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        """Persist a rename where the platform supports directory fsync."""

        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            directory_fd = os.open(directory, flags)
        except OSError:
            return
        try:
            with suppress(OSError):
                os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @classmethod
    def _atomic_write(cls, path: Path, payload: bytes) -> None:
        """Durably replace *path* without exposing a truncated destination."""

        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                fd = -1
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
            cls._ensure_private_permissions(path)
            cls._fsync_directory(path.parent)
        except Exception:
            if fd >= 0:
                os.close(fd)
            with suppress(FileNotFoundError):
                temporary_path.unlink()
            raise

    # ── 主密钥 ────────────────────────────────────────────────
    def _load_or_create_key(self) -> bytes:
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self._key_file.exists():
            encoded_key = self._key_file.read_bytes()
            self._ensure_private_permissions(self._key_file)
            try:
                key = base64.b64decode(encoded_key, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise RuntimeError("connector master key is not valid base64") from exc
            if len(key) != _KEY_LEN:
                raise RuntimeError(
                    f"connector master key must decode to {_KEY_LEN} bytes; got {len(key)}"
                )
            return key

        # A credential file without its original key is not recoverable. Generating
        # a replacement here would make that loss look like a healthy empty store.
        if self._cred_file.exists():
            raise RuntimeError("connector master key is missing for existing credentials")

        key = secrets.token_bytes(_KEY_LEN)
        self._atomic_write(self._key_file, base64.b64encode(key))
        return key

    # ── 加密原语 ──────────────────────────────────────────────
    @staticmethod
    def _encrypt(key: bytes, plaintext: str) -> dict[str, str]:
        nonce = secrets.token_bytes(12)
        aesgcm = AESGCM(key)
        ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return {
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ct).decode(),
        }

    @staticmethod
    def _decrypt(key: bytes, blob: dict[str, str]) -> str:
        nonce = base64.b64decode(blob["nonce"])
        ct = base64.b64decode(blob["ciphertext"])
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct, None).decode("utf-8")

    # ── 读写 ──────────────────────────────────────────────────
    def _read_all(self) -> dict[str, Any]:
        with self._lock:
            if not self._cred_file.exists():
                return {"version": 1, "connectors": {}}
            self._ensure_private_permissions(self._cred_file)
            try:
                data = json.loads(self._cred_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError("connector credential file is unreadable or corrupt") from exc
            if not isinstance(data, dict) or not isinstance(data.get("connectors"), dict):
                raise RuntimeError("connector credential file has an invalid structure")
            return data

    def _write_all(self, data: dict[str, Any]) -> None:
        with self._lock:
            payload = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
            self._atomic_write(self._cred_file, payload)

    # ── 对外 API ──────────────────────────────────────────────
    def set_secret(self, connector_id: str, key: str, value: str) -> None:
        with self._lock:
            data = self._read_all()
            conn = data["connectors"].setdefault(connector_id, {})
            conn[key] = self._encrypt(self._key, value)
            self._write_all(data)

    def get_secret(self, connector_id: str, key: str) -> str | None:
        with self._lock:
            data = self._read_all()
            blob = data.get("connectors", {}).get(connector_id, {}).get(key)
            if not blob:
                return None
            try:
                return self._decrypt(self._key, blob)
            except Exception:  # noqa: BLE001 — key mismatch/corrupt; treat as missing
                return None

    def delete_secret(self, connector_id: str, key: str) -> bool:
        with self._lock:
            data = self._read_all()
            conn = data.get("connectors", {}).get(connector_id, {})
            if key in conn:
                del conn[key]
                self._write_all(data)
                return True
            return False

    def list_secrets(self, connector_id: str) -> list[str]:
        with self._lock:
            data = self._read_all()
            return list(data.get("connectors", {}).get(connector_id, {}).keys())

    def clear_connector(self, connector_id: str) -> bool:
        with self._lock:
            data = self._read_all()
            if connector_id in data.get("connectors", {}):
                del data["connectors"][connector_id]
                self._write_all(data)
                return True
            return False

    def has_credentials(self, connector_id: str) -> bool:
        with self._lock:
            data = self._read_all()
            return bool(data.get("connectors", {}).get(connector_id, {}))


__all__ = ["CredentialStore", "CONNECTOR_ROOT"]

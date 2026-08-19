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
import json
import os
import secrets
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
        self._root = Path(root or CONNECTOR_ROOT)
        self._key_file = Path(master_key_file or MASTER_KEY_FILE)
        self._cred_file = Path(credentials_file or CREDENTIALS_FILE)
        self._key = self._load_or_create_key()

    # ── 主密钥 ────────────────────────────────────────────────
    def _load_or_create_key(self) -> bytes:
        self._root.mkdir(parents=True, exist_ok=True)
        if self._key_file.exists():
            return base64.b64decode(self._key_file.read_bytes())
        key = secrets.token_bytes(_KEY_LEN)
        fd = os.open(str(self._key_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, base64.b64encode(key))
        finally:
            os.close(fd)
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
        if not self._cred_file.exists():
            return {"version": 1, "connectors": {}}
        try:
            return json.loads(self._cred_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # noqa: BLE001
            return {"version": 1, "connectors": {}}

    def _write_all(self, data: dict[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self._cred_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))
        finally:
            os.close(fd)

    # ── 对外 API ──────────────────────────────────────────────
    def set_secret(self, connector_id: str, key: str, value: str) -> None:
        data = self._read_all()
        conn = data["connectors"].setdefault(connector_id, {})
        conn[key] = self._encrypt(self._key, value)
        self._write_all(data)

    def get_secret(self, connector_id: str, key: str) -> str | None:
        data = self._read_all()
        blob = data.get("connectors", {}).get(connector_id, {}).get(key)
        if not blob:
            return None
        try:
            return self._decrypt(self._key, blob)
        except Exception:  # noqa: BLE001 — key mismatch/corrupt; treat as missing
            return None

    def delete_secret(self, connector_id: str, key: str) -> bool:
        data = self._read_all()
        conn = data.get("connectors", {}).get(connector_id, {})
        if key in conn:
            del conn[key]
            self._write_all(data)
            return True
        return False

    def list_secrets(self, connector_id: str) -> list[str]:
        data = self._read_all()
        return list(data.get("connectors", {}).get(connector_id, {}).keys())

    def clear_connector(self, connector_id: str) -> bool:
        data = self._read_all()
        if connector_id in data.get("connectors", {}):
            del data["connectors"][connector_id]
            self._write_all(data)
            return True
        return False

    def has_credentials(self, connector_id: str) -> bool:
        data = self._read_all()
        return bool(data.get("connectors", {}).get(connector_id, {}))


__all__ = ["CredentialStore", "CONNECTOR_ROOT"]

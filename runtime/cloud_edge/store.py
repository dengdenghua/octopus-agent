"""SQLite persistence for device enrollment, entitlements and edge messages."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from runtime.platform.io.sqlite import connect_closing


class CloudEdgeStore:
    """Small durable control-plane store with tenant-scoped operations."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = connect_closing(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code_hash TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    public_key TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_seen_at INTEGER,
                    revoked_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_edge_devices_owner
                    ON devices(tenant_id, owner_id);
                CREATE TABLE IF NOT EXISTS challenges (
                    challenge_hash TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL REFERENCES devices(device_id),
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS entitlements (
                    tenant_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    expires_at INTEGER,
                    PRIMARY KEY(tenant_id, owner_id, feature)
                );
                CREATE TABLE IF NOT EXISTS edge_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    device_id TEXT NOT NULL REFERENCES devices(device_id),
                    source TEXT NOT NULL,
                    source_room_id TEXT NOT NULL,
                    source_message_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    published_at TEXT,
                    payload_json TEXT NOT NULL,
                    received_at INTEGER NOT NULL,
                    UNIQUE(tenant_id, owner_id, source, source_room_id, source_message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_edge_messages_owner_received
                    ON edge_messages(tenant_id, owner_id, received_at DESC);
                """
            )

    @staticmethod
    def _hash_secret(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def create_pairing_code(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        device_name: str,
        ttl_seconds: int = 600,
    ) -> dict[str, Any]:
        now = int(time.time())
        code = "oct_pair_" + secrets.token_urlsafe(24)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO pairing_codes VALUES (?, ?, ?, ?, ?, NULL)",
                (
                    self._hash_secret(code),
                    tenant_id,
                    owner_id,
                    device_name[:80],
                    now + max(60, min(int(ttl_seconds), 3600)),
                ),
            )
        return {"pairing_code": code, "expires_at": now + max(60, min(int(ttl_seconds), 3600))}

    def enroll(
        self, *, pairing_code: str, public_key: str, device_name: str = ""
    ) -> dict[str, Any] | None:
        now = int(time.time())
        code_hash = self._hash_secret(pairing_code)
        with self._lock, self._connect() as conn:
            # The process-local lock does not coordinate multiple workers.
            # Take SQLite's writer reservation before reading so claiming the
            # single-use code and creating the device form one transaction.
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM pairing_codes WHERE code_hash=?",
                (code_hash,),
            ).fetchone()
            if row is None or row["used_at"] is not None or int(row["expires_at"]) < now:
                return None
            claimed = conn.execute(
                """UPDATE pairing_codes SET used_at=?
                WHERE code_hash=? AND used_at IS NULL AND expires_at>=?""",
                (now, code_hash, now),
            )
            if claimed.rowcount != 1:
                return None
            device_id = "dev_" + uuid.uuid4().hex
            conn.execute(
                """INSERT INTO devices
                (device_id, tenant_id, owner_id, device_name, public_key, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    device_id,
                    row["tenant_id"],
                    row["owner_id"],
                    (device_name.strip() or row["device_name"])[:80],
                    public_key,
                    now,
                ),
            )
        return {
            "device_id": device_id,
            "tenant_id": str(row["tenant_id"]),
            "owner_id": str(row["owner_id"]),
        }

    def device(self, device_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        return dict(row) if row is not None else None

    def list_devices(self, *, tenant_id: str, owner_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT device_id, device_name, created_at, last_seen_at, revoked_at
                FROM devices WHERE tenant_id=? AND owner_id=? ORDER BY created_at DESC""",
                (tenant_id, owner_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke_device(self, *, tenant_id: str, owner_id: str, device_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """UPDATE devices SET revoked_at=?
                WHERE tenant_id=? AND owner_id=? AND device_id=? AND revoked_at IS NULL""",
                (int(time.time()), tenant_id, owner_id, device_id),
            )
        return cur.rowcount > 0

    def create_challenge(self, device_id: str, *, ttl_seconds: int = 120) -> str | None:
        device = self.device(device_id)
        if device is None or device.get("revoked_at") is not None:
            return None
        challenge = secrets.token_urlsafe(32)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO challenges VALUES (?, ?, ?, NULL)",
                (self._hash_secret(challenge), device_id, int(time.time()) + ttl_seconds),
            )
        return challenge

    def consume_challenge(self, *, device_id: str, challenge: str) -> bool:
        now = int(time.time())
        digest = self._hash_secret(challenge)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            claimed = conn.execute(
                """UPDATE challenges SET used_at=?
                WHERE challenge_hash=? AND device_id=?
                AND used_at IS NULL AND expires_at>=?""",
                (now, digest, device_id, now),
            )
        return claimed.rowcount == 1

    def touch_device(self, device_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE devices SET last_seen_at=? WHERE device_id=?", (int(time.time()), device_id)
            )

    def entitlements(self, *, tenant_id: str, owner_id: str) -> list[str]:
        now = int(time.time())
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT feature FROM entitlements
                WHERE tenant_id=? AND owner_id=? AND active=1
                AND (expires_at IS NULL OR expires_at>=?) ORDER BY feature""",
                (tenant_id, owner_id, now),
            ).fetchall()
        return [str(row["feature"]) for row in rows]

    def set_entitlement(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        feature: str,
        active: bool,
        expires_at: int | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO entitlements VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, owner_id, feature)
                DO UPDATE SET active=excluded.active, expires_at=excluded.expires_at""",
                (tenant_id, owner_id, feature, int(active), expires_at),
            )

    def ingest_messages(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        device_id: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, int]:
        received_at = int(time.time())
        accepted = 0
        duplicate = 0
        with self._lock, self._connect() as conn:
            for message in messages:
                try:
                    conn.execute(
                        """INSERT INTO edge_messages
                        (tenant_id, owner_id, device_id, source, source_room_id,
                         source_message_id, title, content, published_at, payload_json, received_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            tenant_id,
                            owner_id,
                            device_id,
                            str(message["source"])[:40],
                            str(message["source_room_id"])[:128],
                            str(message["source_message_id"])[:160],
                            str(message.get("title") or "")[:240],
                            str(message["content"])[:50_000],
                            str(message.get("published_at") or "")[:64] or None,
                            json.dumps(message.get("payload") or {}, ensure_ascii=False)[:100_000],
                            received_at,
                        ),
                    )
                    accepted += 1
                except sqlite3.IntegrityError:
                    duplicate += 1
        self.touch_device(device_id)
        return {"accepted": accepted, "duplicate": duplicate}

    def list_messages(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        limit: int = 100,
        after_id: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT id, device_id, source, source_room_id, source_message_id,
                title, content, published_at, received_at FROM edge_messages
                WHERE tenant_id=? AND owner_id=? AND id>? ORDER BY id ASC LIMIT ?""",
                (tenant_id, owner_id, max(0, after_id), max(1, min(limit, 500))),
            ).fetchall()
        return [dict(row) for row in rows]

"""Durable append-only log for Team Room messages.

Room chat used to be live-broadcast only, with a 20-line in-memory ring per
room — so a reconnect, restart, or any catch-up lost the transcript. This is a
small sqlite append-only log (ordered ``seq`` computed atomically inside the
INSERT, like ``group_store``) so room messages survive and can be replayed /
caught up on / searched.

Keyed by ``room_id`` (the team room). CollaborationStore is the canonical log
for linked rooms; this store remains the durable fallback and compatibility
shadow for standalone Team Room deployments.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.memory.cowork.ids import (
    normalize_actor_id,
    normalize_display_name,
    normalize_search_query,
    optional_cowork_id,
    require_cowork_id,
    require_message_text,
)
from runtime.platform.io.sqlite import connect_closing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS room_messages (
    room_id        TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    message_id     TEXT NOT NULL DEFAULT '',
    client_message_id TEXT NOT NULL DEFAULT '',
    participant_id TEXT,
    display_name   TEXT,
    text           TEXT NOT NULL,
    ts             TEXT NOT NULL,
    PRIMARY KEY (room_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_room_messages_room ON room_messages(room_id);
DROP INDEX IF EXISTS idx_room_messages_client_id;
CREATE UNIQUE INDEX IF NOT EXISTS idx_room_messages_client_sender_id
ON room_messages(room_id, participant_id, client_message_id)
WHERE client_message_id != '';
CREATE TABLE IF NOT EXISTS room_message_receipts (
    room_id        TEXT NOT NULL,
    message_id     TEXT NOT NULL,
    participant_id TEXT NOT NULL,
    status         TEXT NOT NULL,
    seq            INTEGER,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (room_id, message_id, participant_id)
);
CREATE INDEX IF NOT EXISTS idx_room_message_receipts_room
ON room_message_receipts(room_id, updated_at);
"""


def _default_dir() -> Path:
    from runtime.platform.process.paths import app_paths

    return app_paths().data_dir / "teamroom"


class RoomMessageStore:
    """Append-only, ordered room message log (sqlite, WAL, multi-process safe)."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._dir = Path(base_dir) if base_dir else _default_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "room_messages.db"
        self._lock = threading.Lock()
        with self._lock, self._connect() as conn:
            # Existing desktop databases predate message acknowledgements.
            # Add the nullable-compatible columns before creating the new
            # idempotency index; fresh databases get them from ``_SCHEMA``.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS room_messages ("
                "room_id TEXT NOT NULL, seq INTEGER NOT NULL, "
                "participant_id TEXT, display_name TEXT, text TEXT NOT NULL, "
                "ts TEXT NOT NULL, PRIMARY KEY (room_id, seq))"
            )
            columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(room_messages)").fetchall()
            }
            if "message_id" not in columns:
                conn.execute(
                    "ALTER TABLE room_messages ADD COLUMN message_id TEXT NOT NULL DEFAULT ''"
                )
            if "client_message_id" not in columns:
                conn.execute(
                    "ALTER TABLE room_messages "
                    "ADD COLUMN client_message_id TEXT NOT NULL DEFAULT ''"
                )
            conn.executescript(_SCHEMA)

    @property
    def base_dir(self) -> Path:
        return self._dir

    def _connect(self) -> sqlite3.Connection:
        conn = connect_closing(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def append(
        self,
        room_id: str,
        *,
        text: str,
        participant_id: str = "",
        display_name: str = "",
        message_id: str = "",
        client_message_id: str = "",
    ) -> int:
        """Append a line, stamping a per-room monotonic ``seq`` + ``ts``. The
        next ``seq`` is computed inside the INSERT so concurrent appends never
        collide. Returns the assigned seq."""
        room_id = require_cowork_id(room_id, label="room_id")
        participant_id = optional_cowork_id(participant_id, label="participant_id")
        message_id = optional_cowork_id(message_id, label="message_id")
        client_message_id = normalize_actor_id(
            client_message_id,
            label="client_message_id",
        )
        display_name = normalize_display_name(display_name)
        text = require_message_text(text)
        ts = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as conn:
            if client_message_id:
                existing = conn.execute(
                    "SELECT seq, participant_id, display_name, text, message_id "
                    "FROM room_messages WHERE room_id = ? AND participant_id = ? "
                    "AND client_message_id = ?",
                    (room_id, participant_id, client_message_id),
                ).fetchone()
                if existing:
                    if (
                        str(existing[1] or "") != participant_id
                        or str(existing[2] or "") != display_name
                        or str(existing[3] or "") != text
                        or (message_id and str(existing[4] or "") != message_id)
                    ):
                        raise ValueError(
                            "client_message_id already belongs to a different room message"
                        )
                    return int(existing[0])
            cur = conn.execute(
                "INSERT INTO room_messages("
                "room_id, seq, message_id, client_message_id, "
                "participant_id, display_name, text, ts) "
                "VALUES (?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM room_messages "
                "WHERE room_id = ?), ?, ?, ?, ?, ?, ?) RETURNING seq",
                (
                    room_id,
                    room_id,
                    message_id,
                    client_message_id,
                    participant_id,
                    display_name,
                    text,
                    ts,
                ),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def history(
        self, room_id: str, *, limit: int = 200, after_seq: int = 0
    ) -> list[dict[str, Any]]:
        """Messages for a room in order, those with ``seq > after_seq`` (for
        reconnect catch-up), capped at ``limit`` (the most recent ``limit``)."""
        room_id = require_cowork_id(room_id, label="room_id")
        limit = max(1, min(2000, limit))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, participant_id, display_name, text, ts, "
                "message_id, client_message_id FROM room_messages "
                "WHERE room_id = ? AND seq > ? ORDER BY seq DESC LIMIT ?",
                (room_id, int(after_seq), limit),
            ).fetchall()
            receipt_rows = conn.execute(
                "SELECT message_id, participant_id, status, seq, updated_at "
                "FROM room_message_receipts WHERE room_id=?",
                (room_id,),
            ).fetchall()
        receipts_by_message: dict[str, list[dict[str, Any]]] = {}
        for receipt in receipt_rows:
            receipts_by_message.setdefault(str(receipt[0]), []).append(
                {
                    "participant_id": str(receipt[1]),
                    "status": str(receipt[2]),
                    "seq": int(receipt[3]) if receipt[3] is not None else None,
                    "updated_at": str(receipt[4]),
                }
            )
        return [
            {
                "seq": int(r[0]),
                "participant_id": r[1] or "",
                "display_name": r[2] or "",
                "text": r[3],
                "ts": r[4],
                "message_id": r[5] or "",
                "client_message_id": r[6] or "",
                "receipts": receipts_by_message.get(str(r[5]), []),
            }
            for r in reversed(rows)
        ]

    def search(self, room_id: str, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Case-insensitive substring search over a room's messages (newest
        first). Small per-room volume → a plain scan, no FTS engine."""
        room_id = require_cowork_id(room_id, label="room_id")
        q = normalize_search_query(query)
        if not q:
            return []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, participant_id, display_name, text, ts, "
                "message_id, client_message_id FROM room_messages "
                "WHERE room_id = ? AND lower(text) LIKE ? ORDER BY seq DESC LIMIT ?",
                (room_id, f"%{q}%", max(1, min(200, limit))),
            ).fetchall()
        return [
            {
                "seq": int(r[0]),
                "participant_id": r[1] or "",
                "display_name": r[2] or "",
                "text": r[3],
                "ts": r[4],
                "message_id": r[5] or "",
                "client_message_id": r[6] or "",
            }
            for r in rows
        ]

    def record_receipt(
        self,
        room_id: str,
        *,
        message_id: str,
        participant_id: str,
        status: str,
        seq: int | None = None,
    ) -> dict[str, Any]:
        """Persist a monotonic delivered/read receipt for one participant."""
        room_id = require_cowork_id(room_id, label="room_id")
        message_id = require_cowork_id(message_id, label="message_id")
        participant_id = require_cowork_id(participant_id, label="participant_id")
        status = str(status or "").strip().lower()
        if status not in {"delivered", "read"}:
            raise ValueError("receipt status must be delivered or read")
        normalized_seq = int(seq) if seq is not None else None
        if normalized_seq is not None and normalized_seq < 1:
            raise ValueError("receipt seq must be >= 1")
        now = datetime.now(UTC).isoformat()
        rank = {"delivered": 1, "read": 2}
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT status, seq FROM room_message_receipts "
                "WHERE room_id=? AND message_id=? AND participant_id=?",
                (room_id, message_id, participant_id),
            ).fetchone()
            effective_status = status
            effective_seq = normalized_seq
            if existing:
                # Receipts are a monotonic state machine. A delayed
                # ``delivered`` packet must not downgrade ``read``, and a
                # stale cursor must not move a member's read position back.
                if rank.get(str(existing[0]), 0) >= rank[status]:
                    effective_status = str(existing[0])
                if existing[1] is not None:
                    effective_seq = max(int(existing[1]), normalized_seq or 0)
                if effective_status == str(existing[0]) and effective_seq == existing[1]:
                    return {
                        "room_id": room_id,
                        "message_id": message_id,
                        "participant_id": participant_id,
                        "status": effective_status,
                        "seq": existing[1],
                    }
            conn.execute(
                "INSERT INTO room_message_receipts "
                "(room_id, message_id, participant_id, status, seq, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(room_id, message_id, participant_id) DO UPDATE SET "
                "status=excluded.status, seq=COALESCE(excluded.seq, room_message_receipts.seq), "
                "updated_at=excluded.updated_at",
                (room_id, message_id, participant_id, effective_status, effective_seq, now),
            )
        return {
            "room_id": room_id,
            "message_id": message_id,
            "participant_id": participant_id,
            "status": effective_status,
            "seq": effective_seq,
        }

    def receipts(self, room_id: str, *, message_id: str | None = None) -> list[dict[str, Any]]:
        """Return durable receipts, optionally scoped to one message."""
        room_id = require_cowork_id(room_id, label="room_id")
        with self._lock, self._connect() as conn:
            if message_id:
                message_id = require_cowork_id(message_id, label="message_id")
                rows = conn.execute(
                    "SELECT message_id, participant_id, status, seq, updated_at "
                    "FROM room_message_receipts WHERE room_id=? AND message_id=? "
                    "ORDER BY updated_at ASC",
                    (room_id, message_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT message_id, participant_id, status, seq, updated_at "
                    "FROM room_message_receipts WHERE room_id=? ORDER BY updated_at ASC",
                    (room_id,),
                ).fetchall()
        return [
            {
                "room_id": room_id,
                "message_id": str(row[0]),
                "participant_id": str(row[1]),
                "status": str(row[2]),
                "seq": int(row[3]) if row[3] is not None else None,
                "updated_at": str(row[4]),
            }
            for row in rows
        ]

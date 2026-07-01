"""Unified collaboration-session storage.

This is the bottom-store step after the read-model bridge: a collaboration
thread owns its persistent room surface and heavyweight tasks directly. Legacy
``team_rooms`` / ``team_tasks`` stores can still be maintained as compatibility
projections, but the canonical session path no longer has to discover its room
and task state from separate JSON files.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.memory.cowork.ids import (
    normalize_display_name,
    normalize_search_query,
    optional_cowork_id,
    require_cowork_id,
    require_message_text,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS collaboration_rooms (
    session_id TEXT PRIMARY KEY,
    room_id    TEXT NOT NULL UNIQUE,
    room_json  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collab_rooms_room ON collaboration_rooms(room_id);

CREATE TABLE IF NOT EXISTS collaboration_tasks (
    task_id    TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    room_id    TEXT NOT NULL,
    status     TEXT NOT NULL,
    task_json  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collab_tasks_session ON collaboration_tasks(session_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_collab_tasks_room ON collaboration_tasks(room_id, updated_at);

CREATE TABLE IF NOT EXISTS collaboration_messages (
    session_id     TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    room_id        TEXT NOT NULL,
    participant_id TEXT,
    display_name   TEXT,
    text           TEXT NOT NULL,
    ts             TEXT NOT NULL,
    PRIMARY KEY (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_collab_messages_session ON collaboration_messages(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_collab_messages_room ON collaboration_messages(room_id, seq);
"""


def _default_dir() -> Path:
    from runtime.platform.process.paths import app_paths

    return app_paths().data_dir / "cowork"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _load(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


class CollaborationStore:
    """Canonical room/task storage keyed by collaboration session id."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._dir = Path(base_dir) if base_dir else _default_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "collaboration.db"
        self._lock = threading.Lock()
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    @property
    def base_dir(self) -> Path:
        return self._dir

    def _connect(self) -> sqlite3.Connection:
        self._dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        return conn

    def room_for_session(self, session_id: str) -> dict[str, Any] | None:
        if not session_id:
            return None
        session_id = require_cowork_id(session_id, label="session_id")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT room_json FROM collaboration_rooms WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return _load(row[0]) if row else None

    def room_by_id(self, room_id: str) -> dict[str, Any] | None:
        if not room_id:
            return None
        room_id = require_cowork_id(room_id, label="room_id")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT room_json FROM collaboration_rooms WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        return _load(row[0]) if row else None

    def session_id_for_room(self, room_id: str) -> str | None:
        if not room_id:
            return None
        room_id = require_cowork_id(room_id, label="room_id")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT session_id FROM collaboration_rooms WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        return str(row[0]) if row else None

    def upsert_room(self, session_id: str, room: dict[str, Any]) -> dict[str, Any]:
        session_id = require_cowork_id(session_id, label="session_id")
        payload = dict(room or {})
        room_id = require_cowork_id(
            payload.get("id") or payload.get("room_id") or f"collab-{session_id}",
            label="room_id",
        )
        payload["id"] = room_id
        now = _now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT created_at FROM collaboration_rooms WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            created_at = str(row[0]) if row else str(payload.get("created_at") or now)
            payload.setdefault("created_at", created_at)
            payload["updated_at"] = str(payload.get("updated_at") or now)
            existing_room = conn.execute(
                "SELECT session_id FROM collaboration_rooms WHERE room_id = ?",
                (room_id,),
            ).fetchone()
            if existing_room and str(existing_room[0]) != session_id:
                conn.execute(
                    "UPDATE collaboration_tasks SET session_id = ? WHERE room_id = ?",
                    (session_id, room_id),
                )
                conn.execute(
                    "UPDATE collaboration_messages SET session_id = ? WHERE room_id = ?",
                    (session_id, room_id),
                )
                conn.execute(
                    "DELETE FROM collaboration_rooms WHERE room_id = ?",
                    (room_id,),
                )
            conn.execute(
                "INSERT INTO collaboration_rooms(session_id, room_id, room_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "room_id = excluded.room_id, room_json = excluded.room_json, updated_at = excluded.updated_at",
                (session_id, room_id, _dump(payload), created_at, payload["updated_at"]),
            )
        return payload

    def upsert_room_by_id(self, room: dict[str, Any]) -> dict[str, Any] | None:
        payload = dict(room or {})
        room_id = require_cowork_id(
            payload.get("id") or payload.get("room_id") or "",
            label="room_id",
        )
        payload["id"] = room_id
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT session_id FROM collaboration_rooms WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        if not row:
            return self.upsert_room(f"team:{room_id}", payload)
        return self.upsert_room(str(row[0]), payload)

    def tasks_for_session(self, session_id: str) -> list[dict[str, Any]]:
        if not session_id:
            return []
        session_id = require_cowork_id(session_id, label="session_id")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT task_json FROM collaboration_tasks WHERE session_id = ? "
                "ORDER BY updated_at DESC, created_at DESC",
                (session_id,),
            ).fetchall()
        return [_load(row[0]) for row in rows]

    def tasks_for_room(self, room_id: str) -> list[dict[str, Any]]:
        if not room_id:
            return []
        room_id = require_cowork_id(room_id, label="room_id")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT task_json FROM collaboration_tasks WHERE room_id = ? "
                "ORDER BY updated_at DESC, created_at DESC",
                (room_id,),
            ).fetchall()
        return [_load(row[0]) for row in rows]

    def upsert_task(self, session_id: str, task: dict[str, Any]) -> dict[str, Any]:
        session_id = require_cowork_id(session_id, label="session_id")
        payload = dict(task or {})
        task_id = require_cowork_id(payload.get("id") or payload.get("task_id") or "", label="task_id")
        room_id = require_cowork_id(payload.get("room_id") or "", label="room_id")
        payload["id"] = task_id
        payload["room_id"] = room_id
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata.setdefault("collab_session_id", session_id)
        metadata.setdefault("source", "collab_session")
        payload["metadata"] = metadata
        now = _now()
        created_at = str(payload.get("created_at") or now)
        updated_at = str(payload.get("updated_at") or now)
        status = str(payload.get("status") or "pending")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO collaboration_tasks("
                "task_id, session_id, room_id, status, task_json, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET "
                "session_id = excluded.session_id, room_id = excluded.room_id, "
                "status = excluded.status, task_json = excluded.task_json, "
                "updated_at = excluded.updated_at",
                (task_id, session_id, room_id, status, _dump(payload), created_at, updated_at),
            )
        return payload

    def upsert_task_for_room(self, room_id: str, task: dict[str, Any]) -> dict[str, Any] | None:
        room_id = require_cowork_id(room_id, label="room_id")
        session_id = self.session_id_for_room(room_id)
        if not session_id:
            return None
        payload = dict(task or {})
        payload.setdefault("room_id", room_id)
        return self.upsert_task(session_id, payload)

    def delete_task(self, task_id: str) -> bool:
        if not task_id:
            return False
        task_id = require_cowork_id(task_id, label="task_id")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM collaboration_tasks WHERE task_id = ?",
                (task_id,),
            )
            return cur.rowcount > 0

    def append_message(
        self,
        session_id: str,
        *,
        room_id: str,
        text: str,
        participant_id: str = "",
        display_name: str = "",
    ) -> int:
        session_id = require_cowork_id(session_id, label="session_id")
        room_id = require_cowork_id(room_id, label="room_id")
        participant_id = optional_cowork_id(participant_id, label="participant_id")
        display_name = normalize_display_name(display_name)
        text = require_message_text(text)
        ts = _now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO collaboration_messages("
                "session_id, seq, room_id, participant_id, display_name, text, ts"
                ") VALUES (?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM collaboration_messages "
                "WHERE session_id = ?), ?, ?, ?, ?, ?) RETURNING seq",
                (session_id, session_id, room_id, participant_id, display_name, text, ts),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def append_message_for_room(
        self,
        room_id: str,
        *,
        text: str,
        participant_id: str = "",
        display_name: str = "",
    ) -> int | None:
        room_id = require_cowork_id(room_id, label="room_id")
        session_id = self.session_id_for_room(room_id)
        if not session_id:
            return None
        return self.append_message(
            session_id,
            room_id=room_id,
            text=text,
            participant_id=participant_id,
            display_name=display_name,
        )

    def messages_for_session(
        self,
        session_id: str,
        *,
        limit: int = 200,
        after_seq: int = 0,
    ) -> list[dict[str, Any]]:
        if not session_id:
            return []
        session_id = require_cowork_id(session_id, label="session_id")
        limit = max(1, min(2000, limit))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, room_id, participant_id, display_name, text, ts "
                "FROM collaboration_messages "
                "WHERE session_id = ? AND seq > ? ORDER BY seq DESC LIMIT ?",
                (session_id, int(after_seq), limit),
            ).fetchall()
        return [
            {
                "seq": int(row[0]),
                "room_id": row[1] or "",
                "participant_id": row[2] or "",
                "display_name": row[3] or "",
                "text": row[4],
                "ts": row[5],
            }
            for row in reversed(rows)
        ]

    def messages_for_room(
        self,
        room_id: str,
        *,
        limit: int = 200,
        after_seq: int = 0,
    ) -> list[dict[str, Any]]:
        if not room_id:
            return []
        room_id = require_cowork_id(room_id, label="room_id")
        limit = max(1, min(2000, limit))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, session_id, participant_id, display_name, text, ts "
                "FROM collaboration_messages "
                "WHERE room_id = ? AND seq > ? ORDER BY seq DESC LIMIT ?",
                (room_id, int(after_seq), limit),
            ).fetchall()
        return [
            {
                "seq": int(row[0]),
                "session_id": row[1] or "",
                "participant_id": row[2] or "",
                "display_name": row[3] or "",
                "text": row[4],
                "ts": row[5],
            }
            for row in reversed(rows)
        ]

    def search_messages(
        self,
        session_id: str,
        query: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        q = normalize_search_query(query)
        if not session_id or not q:
            return []
        session_id = require_cowork_id(session_id, label="session_id")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, room_id, participant_id, display_name, text, ts "
                "FROM collaboration_messages "
                "WHERE session_id = ? AND lower(text) LIKE ? ORDER BY seq DESC LIMIT ?",
                (session_id, f"%{q}%", max(1, min(200, limit))),
            ).fetchall()
        return [
            {
                "seq": int(row[0]),
                "room_id": row[1] or "",
                "participant_id": row[2] or "",
                "display_name": row[3] or "",
                "text": row[4],
                "ts": row[5],
            }
            for row in rows
        ]

    def search_messages_for_room(
        self,
        room_id: str,
        query: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        q = normalize_search_query(query)
        if not room_id or not q:
            return []
        room_id = require_cowork_id(room_id, label="room_id")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, session_id, participant_id, display_name, text, ts "
                "FROM collaboration_messages "
                "WHERE room_id = ? AND lower(text) LIKE ? ORDER BY seq DESC LIMIT ?",
                (room_id, f"%{q}%", max(1, min(200, limit))),
            ).fetchall()
        return [
            {
                "seq": int(row[0]),
                "session_id": row[1] or "",
                "participant_id": row[2] or "",
                "display_name": row[3] or "",
                "text": row[4],
                "ts": row[5],
            }
            for row in rows
        ]

"""Persistence for the thread-group model: an append-only membership event log
plus the thread-scoped shared blackboard.

The membership log is sqlite (ordered, append-only, multi-process safe via an
atomic ``seq`` computed inside the INSERT). The shared blackboard reuses the
existing ``SqliteBlackboard`` — it already persists with per-key writer
attribution + audit; we simply namespace it by ``thread_id`` instead of
``turn_id``, which is the whole "promote the per-turn board to a group board"
change. No new storage engine.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from runtime.memory.cowork.group import GroupState, MemberEvent, fold_state
from runtime.memory.cowork.ids import (
    normalize_actor_id,
    optional_cowork_id,
    require_cowork_id,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS group_events (
    thread_id   TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    event_json  TEXT NOT NULL,
    ts          TEXT NOT NULL,
    PRIMARY KEY (thread_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_group_events_thread ON group_events(thread_id);
"""


def _default_dir() -> Path:
    from runtime.platform.process.paths import app_paths

    return app_paths().data_dir / "cowork"


class GroupStore:
    """Append-only membership events + the thread-scoped shared blackboard."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._dir = Path(base_dir) if base_dir else _default_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._events_db = self._dir / "group_events.db"
        self._board_db = self._dir / "group_blackboard.db"
        self._lock = threading.Lock()
        self._ensure_schema()

    @property
    def base_dir(self) -> Path:
        return self._dir

    def _connect(self) -> sqlite3.Connection:
        self._dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._events_db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        return conn

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ── membership events ────────────────────────────────────────────────────
    def append(self, thread_id: str, event: MemberEvent) -> MemberEvent:
        """Append a membership/mode event, stamping ``seq`` + ``ts``. The next
        ``seq`` is computed inside the INSERT so concurrent appends never collide."""
        thread_id = require_cowork_id(thread_id, label="thread_id")
        event.actor = normalize_actor_id(event.actor)
        event.target_id = optional_cowork_id(event.target_id, label="target_id")
        event.ts = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO group_events(thread_id, seq, event_json, ts) "
                "VALUES (?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM group_events "
                "WHERE thread_id = ?), ?, ?) RETURNING seq",
                (thread_id, thread_id, _dump(event), event.ts),
            )
            row = cur.fetchone()
            event.seq = int(row[0]) if row else 0
        return event

    def events(self, thread_id: str) -> list[MemberEvent]:
        thread_id = require_cowork_id(thread_id, label="thread_id")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT event_json, seq, ts FROM group_events WHERE thread_id = ? ORDER BY seq",
                (thread_id,),
            ).fetchall()
        out: list[MemberEvent] = []
        for event_json, seq, ts in rows:
            ev = MemberEvent.from_dict(_load(event_json))
            ev.seq = int(seq)
            ev.ts = str(ts)
            out.append(ev)
        return out

    def state(self, thread_id: str, until_seq: int | None = None) -> GroupState:
        """The folded group (roster + mode). ``until_seq`` replays to a point."""
        thread_id = require_cowork_id(thread_id, label="thread_id")
        return fold_state(self.events(thread_id), until_seq=until_seq)

    # ── thread-scoped shared blackboard ──────────────────────────────────────
    def blackboard(self, thread_id: str):
        """The group's shared blackboard — the existing SqliteBlackboard, but
        namespaced by ``thread_id`` so it persists across turns and members."""
        from runtime.memory.runtime_state.blackboard_store import SqliteBlackboard

        thread_id = require_cowork_id(thread_id, label="thread_id")
        return SqliteBlackboard(self._board_db, thread_id)

    def blackboard_snapshot(self, thread_id: str) -> dict:
        """All shared-board keys → values for the thread (empty if none)."""
        thread_id = require_cowork_id(thread_id, label="thread_id")
        board = self.blackboard(thread_id)
        snap = getattr(board, "snapshot", None)
        if callable(snap):
            return snap()
        # Fallback: reconstruct from keys() if snapshot isn't exposed.
        keys = getattr(board, "keys", lambda: [])()
        return {k: board.read(k) for k in keys}


def _dump(event: MemberEvent) -> str:
    import json

    return json.dumps(event.to_dict(), ensure_ascii=False, default=str)


def _load(text: str) -> dict:
    import json

    data = json.loads(text)
    return data if isinstance(data, dict) else {}

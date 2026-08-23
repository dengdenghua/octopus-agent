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

from runtime.memory.cowork.group import (
    VALID_MODES,
    ContextGrant,
    GroupState,
    MemberEvent,
    fold_state,
)
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

    def ensure_member(
        self,
        thread_id: str,
        event: MemberEvent,
    ) -> tuple[MemberEvent | None, GroupState]:
        """Add one session member exactly once and return the canonical fold.

        Membership is a reference to an existing actor/agent id, not a cloned
        identity.  The folded read and conditional append share one SQLite
        write transaction so retries (including retries from another process)
        cannot create duplicate timeline events.
        """

        if event.action != "invite":
            raise ValueError("ensure_member requires an invite event")
        thread_id = require_cowork_id(thread_id, label="thread_id")
        event.actor = normalize_actor_id(event.actor)
        event.target_id = require_cowork_id(event.target_id, label="target_id")
        event.ts = datetime.now(UTC).isoformat()

        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT event_json, seq, ts FROM group_events WHERE thread_id = ? ORDER BY seq",
                (thread_id,),
            ).fetchall()
            existing_events: list[MemberEvent] = []
            for event_json, seq, ts in rows:
                existing = MemberEvent.from_dict(_load(event_json))
                existing.seq = int(seq)
                existing.ts = str(ts)
                existing_events.append(existing)
            current = fold_state(existing_events)
            member = current.member(event.target_id)
            if member is not None:
                if member.kind != event.target_kind:
                    raise ValueError(
                        f"member kind collision for {event.target_id}: "
                        f"{member.kind} != {event.target_kind}"
                    )
                return None, current

            event.seq = int(rows[-1][1]) + 1 if rows else 1
            conn.execute(
                "INSERT INTO group_events(thread_id, seq, event_json, ts) VALUES (?, ?, ?, ?)",
                (thread_id, event.seq, _dump(event), event.ts),
            )
            return event, fold_state([*existing_events, event])

    def remove_member_if_present(
        self,
        thread_id: str,
        *,
        actor: str,
        member_id: str,
    ) -> tuple[MemberEvent | None, GroupState]:
        """Remove one session member exactly once.

        A retry after the member has already left is a successful no-op and
        does not grow the event log.  ACL is intentionally outside this store;
        callers must authorize against the owning thread/room before invoking
        the mutation.
        """

        thread_id = require_cowork_id(thread_id, label="thread_id")
        actor = normalize_actor_id(actor)
        member_id = require_cowork_id(member_id, label="member_id")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT event_json, seq, ts FROM group_events WHERE thread_id = ? ORDER BY seq",
                (thread_id,),
            ).fetchall()
            existing_events: list[MemberEvent] = []
            for event_json, seq, ts in rows:
                existing = MemberEvent.from_dict(_load(event_json))
                existing.seq = int(seq)
                existing.ts = str(ts)
                existing_events.append(existing)
            current = fold_state(existing_events)
            if current.member(member_id) is None:
                return None, current

            event = MemberEvent(action="leave", actor=actor, target_id=member_id)
            event.seq = int(rows[-1][1]) + 1 if rows else 1
            event.ts = datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT INTO group_events(thread_id, seq, event_json, ts) VALUES (?, ?, ?, ?)",
                (thread_id, event.seq, _dump(event), event.ts),
            )
            return event, fold_state([*existing_events, event])

    def replace_agent_roster(
        self,
        thread_id: str,
        *,
        actor: str,
        agent_ids: list[str],
        mode: str,
    ) -> tuple[list[MemberEvent], GroupState]:
        """Atomically reconcile the agent roster and collaboration mode.

        The current fold, diff calculation, and all resulting event inserts run
        under one ``BEGIN IMMEDIATE`` transaction. Human members are preserved;
        the supplied ids are the complete desired *agent* roster. Returning the
        post-transaction fold lets callers replace optimistic UI state with the
        canonical server state in one response.
        """

        thread_id = require_cowork_id(thread_id, label="thread_id")
        actor = normalize_actor_id(actor)
        if mode not in VALID_MODES:
            raise ValueError(f"mode must be one of {sorted(VALID_MODES)}")

        desired: list[str] = []
        seen: set[str] = set()
        for raw_id in agent_ids:
            member_id = require_cowork_id(raw_id, label="agent_id")
            if member_id in seen:
                continue
            seen.add(member_id)
            desired.append(member_id)

        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT event_json, seq, ts FROM group_events WHERE thread_id = ? ORDER BY seq",
                (thread_id,),
            ).fetchall()
            existing_events: list[MemberEvent] = []
            for event_json, seq, ts in rows:
                event = MemberEvent.from_dict(_load(event_json))
                event.seq = int(seq)
                event.ts = str(ts)
                existing_events.append(event)
            current = fold_state(existing_events)
            current_by_id = {member.id: member for member in current.roster}

            events: list[MemberEvent] = []
            desired_set = set(desired)
            for member in current.roster:
                if member.kind == "agent" and member.id not in desired_set:
                    events.append(MemberEvent(action="leave", actor=actor, target_id=member.id))
            for member_id in desired:
                current_member = current_by_id.get(member_id)
                if current_member is not None and current_member.kind != "agent":
                    raise ValueError(f"agent_id collides with human member: {member_id}")
                if current_member is None or current_member.role != "participant":
                    events.append(
                        MemberEvent(
                            action="invite",
                            actor=actor,
                            target_id=member_id,
                            target_kind="agent",
                            role="participant",
                            grant=ContextGrant(),
                        )
                    )
            if current.mode != mode:
                events.append(
                    MemberEvent(action="mode", actor=actor, mode=mode)  # type: ignore[arg-type]
                )

            next_seq = int(rows[-1][1]) + 1 if rows else 1
            for offset, event in enumerate(events):
                event.seq = next_seq + offset
                event.ts = datetime.now(UTC).isoformat()
                conn.execute(
                    "INSERT INTO group_events(thread_id, seq, event_json, ts) VALUES (?, ?, ?, ?)",
                    (thread_id, event.seq, _dump(event), event.ts),
                )

            return events, fold_state([*existing_events, *events])

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

    def delete_thread(self, thread_id: str) -> bool:
        """Remove all state owned by a newly-created collaboration thread.

        Normal membership changes remain append-only.  This narrow deletion
        primitive exists for cross-store creation compensation: a project-group
        saga can remove its private, not-yet-returned thread when a later room
        or projection write fails.  The blackboard namespace is included so a
        retry cannot recover half-created group state.
        """

        thread_id = require_cowork_id(thread_id, label="thread_id")
        deleted = False
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM group_events WHERE thread_id = ?", (thread_id,))
            deleted = cur.rowcount > 0
        if self._board_db.exists():
            with self._lock, sqlite3.connect(str(self._board_db), timeout=5.0) as conn:
                # The board DB is lazily initialized, so tolerate a file that
                # exists without the table (for example after interrupted setup).
                table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='blackboard'"
                ).fetchone()
                if table is not None:
                    cur = conn.execute("DELETE FROM blackboard WHERE turn_id = ?", (thread_id,))
                    deleted = deleted or cur.rowcount > 0
        return deleted

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

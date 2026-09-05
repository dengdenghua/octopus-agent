"""Async coworkers — a member can be given a task to work in the background.

The biggest step toward "a workspace with colleagues" rather than a turn-by-turn
chat: assign a task to a member, they work between your turns, and the result
lands on the shared blackboard (attributed) so the whole group sees it — while
you keep talking to someone else.

This is the *data spine*: assign → claim → complete (writes to the group board) →
pending(). The actual agent execution is the one hot-path piece left as a seam —
a runner polls ``pending`` and calls ``complete``; nothing here touches the
streaming loop.
"""

from __future__ import annotations

import builtins
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from runtime.memory.cowork._group_sqlite_coordination import (
    cowork_storage_write_lock,
    require_delete_journals,
)
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.ids import (
    MAX_COWORK_MESSAGE_TEXT_LENGTH,
    normalize_actor_id,
    require_cowork_id,
)
from runtime.platform.io.sqlite import connect_closing

_STATUSES = ("pending", "working", "done", "failed", "cancelled")
_ACTIVE_STATUSES = ("staged", "pending", "working")
_ASYNC_TEXT_MAX_LENGTH = MAX_COWORK_MESSAGE_TEXT_LENGTH
_DEFAULT_MAX_ACTIVE_PER_THREAD = 512
_DEFAULT_MAX_ACTIVE_TOTAL = 4096


class AsyncWorkQueueFullError(RuntimeError):
    """Raised before enqueue when a bounded collaboration queue is full."""

    def __init__(self, health: dict[str, Any], requested: int) -> None:
        self.health = dict(health)
        self.requested = max(0, int(requested))
        super().__init__(
            "cowork background queue capacity exceeded "
            f"(requested={self.requested}, "
            f"thread_available={health.get('thread_available')}, "
            f"total_available={health.get('total_available')})"
        )


def _normalize_async_text(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    if len(text) > _ASYNC_TEXT_MAX_LENGTH:
        raise ValueError(f"invalid {label}: must be at most {_ASYNC_TEXT_MAX_LENGTH} chars")
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text):
        raise ValueError(f"invalid {label}: contains unsupported control characters")
    if any(ord(ch) == 127 for ch in text):
        raise ValueError(f"invalid {label}: contains unsupported control characters")
    return text


@dataclass
class AsyncTask:
    task_id: str
    thread_id: str
    assignee: str
    prompt: str
    status: str
    result: str | None
    created_by: str
    created_at: str
    updated_at: str
    attempts: int = 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "assignee": self.assignee,
            "prompt": self.prompt,
            "status": self.status,
            "result": self.result,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "attempts": self.attempts,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


class AsyncWorkStore:
    """Background task queue per thread; completion posts to the group board."""

    def __init__(
        self,
        base_dir: Path | str | None = None,
        group_store: GroupStore | None = None,
        *,
        max_active_per_thread: int = _DEFAULT_MAX_ACTIVE_PER_THREAD,
        max_active_total: int = _DEFAULT_MAX_ACTIVE_TOTAL,
    ) -> None:
        from runtime.platform.process.paths import app_paths

        d = Path(base_dir) if base_dir else app_paths().data_dir / "cowork"
        if group_store is not None and d.resolve() != group_store.base_dir.resolve():
            raise ValueError("AsyncWorkStore and GroupStore must share one storage directory")
        d.mkdir(parents=True, exist_ok=True)
        self._db = d / "async_work.db"
        self._lock = threading.Lock()
        self._groups = group_store or GroupStore(base_dir=d)
        self._max_active_total = max(1, int(max_active_total))
        self._max_active_per_thread = min(
            max(1, int(max_active_per_thread)),
            self._max_active_total,
        )
        board = self._groups.blackboard("async-schema")
        board.close()
        with cowork_storage_write_lock(d), self._lock, self._connect() as conn:
            self._ensure_schema(conn)

    def _connect(self) -> sqlite3.Connection:
        self._db.parent.mkdir(parents=True, exist_ok=True)
        if not self._groups.events_db_path.exists():
            self._groups.ensure_storage()
        if not self._groups.board_db_path.exists():
            board = self._groups.blackboard("async-schema")
            board.close()
        conn = connect_closing(str(self._db), timeout=10.0)
        # Keep every attached participant in DELETE mode; see GroupStore's
        # cross-database thread-deletion transaction invariant.
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            conn.execute("ATTACH DATABASE ? AS group_guard", (str(self._groups.events_db_path),))
            conn.execute("ATTACH DATABASE ? AS group_board", (str(self._groups.board_db_path),))
            require_delete_journals(conn, ("main", "group_guard", "group_board"))
        except Exception:
            conn.close()
            raise
        return conn

    @staticmethod
    def _assert_thread_writable(conn: sqlite3.Connection, thread_id: str) -> None:
        from runtime.memory.cowork.group_store import GroupThreadDeletingError

        if conn.execute(
            "SELECT 1 FROM group_guard.group_thread_delete_claims WHERE thread_id=? "
            "UNION ALL SELECT 1 FROM group_guard.group_thread_delete_tombstones "
            "WHERE thread_id=? LIMIT 1",
            (thread_id, thread_id),
        ).fetchone():
            raise GroupThreadDeletingError(thread_id)

    @staticmethod
    def _write_board(
        conn: sqlite3.Connection,
        thread_id: str,
        key: str,
        value: str,
        *,
        writer: str,
    ) -> None:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        row = conn.execute(
            "SELECT writers_json FROM group_board.blackboard WHERE turn_id=? AND key=?",
            (thread_id, key),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO group_board.blackboard(turn_id, key, value_json, writers_json, "
                "write_count, overwrite_count, updated_at) VALUES(?,?,?,?,?,?,?)",
                (thread_id, key, payload, json.dumps([writer]), 1, 0, time.time()),
            )
            return
        writers = set(json.loads(row[0] or "[]"))
        writers.add(writer)
        conn.execute(
            "UPDATE group_board.blackboard SET value_json=?, writers_json=?, "
            "write_count=write_count+1, overwrite_count=overwrite_count+1, updated_at=? "
            "WHERE turn_id=? AND key=?",
            (payload, json.dumps(sorted(writers)), time.time(), thread_id, key),
        )

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS async_tasks ("
            "task_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, assignee TEXT, "
            "prompt TEXT, status TEXT, result TEXT, created_by TEXT, created_at TEXT)"
        )
        self._migrate_schema(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_async_thread ON async_tasks(thread_id, status)"
        )
        conn.commit()

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(async_tasks)").fetchall()}
        if "updated_at" not in columns:
            conn.execute("ALTER TABLE async_tasks ADD COLUMN updated_at TEXT")
            conn.execute("UPDATE async_tasks SET updated_at = COALESCE(created_at, ?)", (_now(),))
        if "attempts" not in columns:
            conn.execute("ALTER TABLE async_tasks ADD COLUMN attempts INTEGER DEFAULT 0")
            conn.execute("UPDATE async_tasks SET attempts = COALESCE(attempts, 0)")

    def _row_to_task(self, row) -> AsyncTask:
        return AsyncTask(
            task_id=row[0],
            thread_id=row[1],
            assignee=row[2],
            prompt=row[3],
            status=row[4],
            result=row[5],
            created_by=row[6],
            created_at=row[7],
            updated_at=row[8] or row[7],
            attempts=int(row[9] or 0),
        )

    def assign(
        self,
        thread_id: str,
        assignee: str,
        prompt: str,
        *,
        actor: str,
        task_id: str | None = None,
    ) -> AsyncTask:
        normalized_task_id = task_id if task_id is not None else uuid4().hex
        return self.assign_batch(
            thread_id,
            [(normalized_task_id, assignee, prompt)],
            actor=actor,
        )[0]

    def assign_batch(
        self,
        thread_id: str,
        assignments: list[tuple[str, str, str]],
        *,
        actor: str,
        staged: bool = False,
    ) -> list[AsyncTask]:
        """Atomically enqueue a bounded batch, optionally hidden from runners.

        Staging lets a caller persist related collector metadata before the
        tasks become claimable. Capacity is reserved by staged rows, so two
        concurrent retries cannot overbook the queue.
        """

        thread_id = require_cowork_id(thread_id, label="thread_id")
        actor = normalize_actor_id(actor or "user", label="actor") or "user"
        if not assignments:
            return []
        now = _now()
        initial_status = "staged" if staged else "pending"
        tasks: list[AsyncTask] = []
        seen_ids: set[str] = set()
        for raw_task_id, raw_assignee, raw_prompt in assignments:
            normalized_task_id = require_cowork_id(raw_task_id, label="task_id")
            if normalized_task_id in seen_ids:
                raise ValueError("task_id must be unique within a batch")
            seen_ids.add(normalized_task_id)
            assignee = normalize_actor_id(raw_assignee, label="assignee")
            if not assignee:
                raise ValueError("assignee is required")
            prompt = _normalize_async_text(raw_prompt, label="prompt")
            tasks.append(
                AsyncTask(
                    normalized_task_id,
                    thread_id,
                    assignee,
                    prompt,
                    initial_status,
                    None,
                    actor,
                    now,
                    now,
                    0,
                )
            )
        with cowork_storage_write_lock(self._db.parent), self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            self._assert_thread_writable(conn, thread_id)
            health = self._queue_health(conn, thread_id)
            if len(tasks) > int(health["thread_available"]) or len(tasks) > int(
                health["total_available"]
            ):
                raise AsyncWorkQueueFullError(health, len(tasks))
            conn.executemany(
                "INSERT INTO async_tasks("
                "task_id, thread_id, assignee, prompt, status, result, "
                "created_by, created_at, updated_at, attempts"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        task.task_id,
                        task.thread_id,
                        task.assignee,
                        task.prompt,
                        task.status,
                        None,
                        task.created_by,
                        task.created_at,
                        task.updated_at,
                        task.attempts,
                    )
                    for task in tasks
                ],
            )
        return tasks

    def stage_batch(
        self,
        thread_id: str,
        assignments: list[tuple[str, str, str]],
        *,
        actor: str,
    ) -> list[AsyncTask]:
        return self.assign_batch(thread_id, assignments, actor=actor, staged=True)

    def activate_staged(self, task_ids: list[str] | tuple[str, ...]) -> int:
        """Atomically expose an entire staged batch to background runners."""

        normalized = list(
            dict.fromkeys(require_cowork_id(item, label="task_id") for item in task_ids)
        )
        if not normalized:
            return 0
        placeholders = ",".join("?" for _ in normalized)
        with cowork_storage_write_lock(self._db.parent), self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"SELECT task_id,thread_id,status FROM async_tasks WHERE task_id IN ({placeholders})",  # nosec B608 - placeholders only
                normalized,
            ).fetchall()
            if len(rows) != len(normalized) or any(str(row[2]) != "staged" for row in rows):
                return 0
            for thread_id in {str(row[1]) for row in rows}:
                self._assert_thread_writable(conn, thread_id)
            updated = conn.execute(
                f"UPDATE async_tasks SET status='pending',updated_at=? WHERE status='staged' "  # nosec B608 - placeholders only
                f"AND task_id IN ({placeholders})",
                (_now(), *normalized),
            ).rowcount
        return int(updated or 0)

    def discard_staged(self, task_ids: list[str] | tuple[str, ...]) -> int:
        """Rollback tasks that never completed their collector binding."""

        normalized = list(
            dict.fromkeys(require_cowork_id(item, label="task_id") for item in task_ids)
        )
        if not normalized:
            return 0
        placeholders = ",".join("?" for _ in normalized)
        with cowork_storage_write_lock(self._db.parent), self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            deleted = conn.execute(
                f"DELETE FROM async_tasks WHERE status='staged' "  # nosec B608 - placeholders only
                f"AND task_id IN ({placeholders})",
                normalized,
            ).rowcount
        return int(deleted or 0)

    def cancel_batch(
        self,
        task_ids: list[str] | tuple[str, ...],
        *,
        reason: str = "collaboration cancelled by user",
    ) -> int:
        """Atomically retire queued or running tasks without publishing output.

        A Python worker that is already inside a provider call may take time to
        unwind.  The terminal ``cancelled`` row is therefore also a generation
        fence: ``complete`` and ``fail`` only accept ``working`` rows, so a late
        result can no longer reach the shared blackboard or collector.
        """

        normalized = list(
            dict.fromkeys(require_cowork_id(item, label="task_id") for item in task_ids)
        )
        if not normalized:
            return 0
        cancellation_reason = _normalize_async_text(reason, label="cancellation reason")
        placeholders = ",".join("?" for _ in normalized)
        with cowork_storage_write_lock(self._db.parent), self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"SELECT DISTINCT thread_id FROM async_tasks WHERE task_id IN ({placeholders})",  # nosec B608 - placeholders only
                normalized,
            ).fetchall()
            for row in rows:
                self._assert_thread_writable(conn, str(row[0]))
            updated = conn.execute(
                "UPDATE async_tasks SET status='cancelled',result=?,updated_at=? "
                f"WHERE status IN ('staged','pending','working') AND task_id IN ({placeholders})",  # nosec B608 - placeholders only
                (cancellation_reason, _now(), *normalized),
            ).rowcount
        return int(updated or 0)

    def _set_status(
        self,
        task_id: str,
        status: str,
        *,
        result: str | None = None,
        expected_status: str | None = None,
    ) -> bool:
        task_id = require_cowork_id(task_id, label="task_id")
        if status not in _STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        if result is not None:
            result = _normalize_async_text(result, label="result")
        where = "WHERE task_id=?"
        params: tuple[object, ...]
        if expected_status is None:
            params = (status, result, _now(), task_id)
        else:
            where = "WHERE task_id=? AND status=?"
            params = (status, result, _now(), task_id, expected_status)
        with cowork_storage_write_lock(self._db.parent), self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT thread_id FROM async_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if row is None:
                return False
            self._assert_thread_writable(conn, str(row[0]))
            cur = conn.execute(
                "UPDATE async_tasks SET status=?, result=COALESCE(?, result), updated_at=? "  # nosec B608 — WHERE built from ? placeholders; values parameterized
                f"{where}",
                params,
            )
            return cur.rowcount > 0

    def claim(self, task_id: str) -> bool:
        """A runner takes the task (pending → working). False if not pending."""
        task_id = require_cowork_id(task_id, label="task_id")
        with cowork_storage_write_lock(self._db.parent), self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT thread_id FROM async_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if row is None:
                return False
            self._assert_thread_writable(conn, str(row[0]))
            cur = conn.execute(
                "UPDATE async_tasks SET status='working', updated_at=?, "
                "attempts=COALESCE(attempts, 0) + 1 "
                "WHERE task_id=? AND status='pending'",
                (_now(), task_id),
            )
            return cur.rowcount > 0

    def complete(self, task_id: str, result: str, *, blackboard_key: str | None = None) -> bool:
        """Mark done and post the result to the group's shared blackboard,
        attributed to the assignee — so the whole thread sees the output."""
        task_id = require_cowork_id(task_id, label="task_id")
        result = _normalize_async_text(result, label="result")
        if blackboard_key is not None:
            blackboard_key = require_cowork_id(blackboard_key, label="blackboard_key")
        with cowork_storage_write_lock(self._db.parent), self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM async_tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                return False
            task = self._row_to_task(row)
            self._assert_thread_writable(conn, task.thread_id)
            if task.status != "working":
                return False
            conn.execute(
                "UPDATE async_tasks SET status='done', result=?, updated_at=? "
                "WHERE task_id=? AND status='working'",
                (result, _now(), task_id),
            )
            key = blackboard_key or f"task:{task.assignee}:{task_id[:8]}"
            self._write_board(
                conn,
                task.thread_id,
                key,
                result,
                writer=task.assignee,
            )
            return True

    def fail(self, task_id: str, error: str) -> bool:
        task_id = require_cowork_id(task_id, label="task_id")
        error = _normalize_async_text(error, label="error")
        return self._set_status(
            task_id,
            "failed",
            result=error,
            expected_status="working",
        )

    def recover_stale_working(
        self,
        *,
        max_age_seconds: float = 900.0,
        max_attempts: int = 3,
    ) -> dict[str, int]:
        """Return abandoned ``working`` tasks to the queue after a process crash.

        A task gets ``max_attempts`` claims before being marked failed, which
        prevents one permanently-bad prompt from being re-run forever.
        """
        try:
            max_age_seconds = max(0.0, float(max_age_seconds))
        except (TypeError, ValueError):
            max_age_seconds = 900.0
        try:
            max_attempts = max(1, min(int(max_attempts), 100))
        except (TypeError, ValueError):
            max_attempts = 3
        cutoff = (datetime.now(UTC) - timedelta(seconds=max_age_seconds)).isoformat()
        now = _now()
        with cowork_storage_write_lock(self._db.parent), self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            writable = (
                "AND NOT EXISTS (SELECT 1 FROM group_guard.group_thread_delete_claims "
                "WHERE thread_id=async_tasks.thread_id) "
                "AND NOT EXISTS (SELECT 1 FROM group_guard.group_thread_delete_tombstones "
                "WHERE thread_id=async_tasks.thread_id)"
            )
            failed = conn.execute(
                "UPDATE async_tasks SET status='failed', updated_at=?, "
                "result=COALESCE(result, ?) "
                "WHERE status='working' AND COALESCE(updated_at, created_at) <= ? "
                f"AND COALESCE(attempts, 0) >= ? {writable}",  # nosec B608 - fixed SQL
                (now, "task abandoned after repeated worker restarts", cutoff, max_attempts),
            ).rowcount
            # A process may stop after capacity reservation but before the
            # collector binding becomes runnable. Retire that invisible lease
            # so it cannot consume queue capacity forever.
            failed += conn.execute(
                "UPDATE async_tasks SET status='failed', updated_at=?, "
                "result=COALESCE(result, ?) WHERE status='staged' "
                "AND COALESCE(updated_at, created_at) <= ?",
                (now, "task staging did not complete", cutoff),
            ).rowcount
            requeued = conn.execute(
                "UPDATE async_tasks SET status='pending', result=NULL, updated_at=? "
                "WHERE status='working' AND COALESCE(updated_at, created_at) <= ? "
                f"AND COALESCE(attempts, 0) < ? {writable}",  # nosec B608 - fixed SQL
                (now, cutoff, max_attempts),
            ).rowcount
        return {"requeued": requeued, "failed": failed}

    def staged_older_than(self, *, max_age_seconds: float) -> list[AsyncTask]:
        """Read staged reservations eligible for crash recovery."""

        try:
            max_age_seconds = max(0.0, float(max_age_seconds))
        except (TypeError, ValueError):
            max_age_seconds = 900.0
        cutoff = (datetime.now(UTC) - timedelta(seconds=max_age_seconds)).isoformat()
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM async_tasks WHERE status='staged' "
                "AND COALESCE(updated_at, created_at) <= ? ORDER BY created_at",
                (cutoff,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get(self, task_id: str) -> AsyncTask | None:
        task_id = require_cowork_id(task_id, label="task_id")
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM async_tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def pending(self, thread_id: str) -> list[AsyncTask]:
        thread_id = require_cowork_id(thread_id, label="thread_id")
        return self._by_status(thread_id, "pending")

    def threads_with_pending(self) -> list[str]:
        """Distinct threads that have at least one pending task (for a runner)."""
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT thread_id FROM async_tasks WHERE status='pending' "
                "GROUP BY thread_id ORDER BY MIN(created_at), thread_id"
            ).fetchall()
        out: list[str] = []
        for row in rows:
            try:
                out.append(require_cowork_id(row[0], label="thread_id"))
            except ValueError:
                continue
        return out

    def counts(self, thread_id: str | None = None) -> dict[str, int]:
        """Task counts by status for diagnostics/UI badges."""
        if thread_id is None:
            sql = "SELECT status, COUNT(*) FROM async_tasks GROUP BY status"
            args: tuple[str, ...] = ()
        else:
            thread_id = require_cowork_id(thread_id, label="thread_id")
            sql = "SELECT status, COUNT(*) FROM async_tasks WHERE thread_id=? GROUP BY status"
            args = (thread_id,)
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(sql, args).fetchall()
        out = {status: 0 for status in _STATUSES}
        for status, count in rows:
            if status in out:
                out[str(status)] = int(count or 0)
        return out

    def _queue_health(self, conn: sqlite3.Connection, thread_id: str) -> dict[str, Any]:
        placeholders = ",".join("?" for _ in _ACTIVE_STATUSES)
        thread_active = int(
            conn.execute(
                f"SELECT COUNT(*) FROM async_tasks WHERE thread_id=? "  # nosec B608 - static placeholders
                f"AND status IN ({placeholders})",
                (thread_id, *_ACTIVE_STATUSES),
            ).fetchone()[0]
            or 0
        )
        total_active = int(
            conn.execute(
                f"SELECT COUNT(*) FROM async_tasks WHERE status IN ({placeholders})",  # nosec B608 - static placeholders
                _ACTIVE_STATUSES,
            ).fetchone()[0]
            or 0
        )
        staged = int(
            conn.execute(
                "SELECT COUNT(*) FROM async_tasks WHERE thread_id=? AND status='staged'",
                (thread_id,),
            ).fetchone()[0]
            or 0
        )
        thread_available = max(0, self._max_active_per_thread - thread_active)
        total_available = max(0, self._max_active_total - total_active)
        ratio = max(
            thread_active / self._max_active_per_thread,
            total_active / self._max_active_total,
        )
        pressure = (
            "saturated"
            if thread_available == 0 or total_available == 0
            else "high"
            if ratio >= 0.9
            else "elevated"
            if ratio >= 0.75
            else "normal"
        )
        return {
            "schema": "octopus.cowork_queue_health.v1",
            "pressure": pressure,
            "staged": staged,
            "thread_active": thread_active,
            "thread_limit": self._max_active_per_thread,
            "thread_available": thread_available,
            "total_active": total_active,
            "total_limit": self._max_active_total,
            "total_available": total_available,
        }

    def queue_health(self, thread_id: str) -> dict[str, Any]:
        """Capacity and pressure snapshot used by APIs and operators."""

        thread_id = require_cowork_id(thread_id, label="thread_id")
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            return self._queue_health(conn, thread_id)

    def list(self, thread_id: str) -> list[AsyncTask]:
        thread_id = require_cowork_id(thread_id, label="thread_id")
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM async_tasks WHERE thread_id=? ORDER BY created_at", (thread_id,)
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def _by_status(self, thread_id: str, status: str) -> builtins.list[AsyncTask]:
        thread_id = require_cowork_id(thread_id, label="thread_id")
        if status not in _STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        with self._lock, self._connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM async_tasks WHERE thread_id=? AND status=? ORDER BY created_at",
                (thread_id, status),
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

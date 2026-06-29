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

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from runtime.memory.cowork.group_store import GroupStore

_STATUSES = ("pending", "working", "done", "failed")


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
        self, base_dir: Path | str | None = None, group_store: GroupStore | None = None
    ) -> None:
        from runtime.platform.process.paths import app_paths

        d = Path(base_dir) if base_dir else app_paths().data_dir / "cowork"
        d.mkdir(parents=True, exist_ok=True)
        self._db = d / "async_work.db"
        self._lock = threading.Lock()
        self._groups = group_store or GroupStore(base_dir=d)
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS async_tasks ("
                "task_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, assignee TEXT, "
                "prompt TEXT, status TEXT, result TEXT, created_by TEXT, created_at TEXT)"
            )
            self._migrate_schema(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_async_thread ON async_tasks(thread_id, status)"
            )

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(async_tasks)").fetchall()
        }
        if "updated_at" not in columns:
            conn.execute("ALTER TABLE async_tasks ADD COLUMN updated_at TEXT")
            conn.execute("UPDATE async_tasks SET updated_at = COALESCE(created_at, ?)", (_now(),))
        if "attempts" not in columns:
            conn.execute("ALTER TABLE async_tasks ADD COLUMN attempts INTEGER DEFAULT 0")
            conn.execute("UPDATE async_tasks SET attempts = COALESCE(attempts, 0)")

    def _row_to_task(self, row) -> AsyncTask:
        return AsyncTask(
            task_id=row[0], thread_id=row[1], assignee=row[2], prompt=row[3],
            status=row[4], result=row[5], created_by=row[6], created_at=row[7],
            updated_at=row[8] or row[7], attempts=int(row[9] or 0),
        )

    def assign(self, thread_id: str, assignee: str, prompt: str, *, actor: str) -> AsyncTask:
        if not assignee or not prompt:
            raise ValueError("assignee and prompt are required")
        now = _now()
        task = AsyncTask(uuid4().hex, thread_id, assignee, prompt, "pending", None,
                         actor or "user", now, now, 0)
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            conn.execute(
                "INSERT INTO async_tasks("
                "task_id, thread_id, assignee, prompt, status, result, "
                "created_by, created_at, updated_at, attempts"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (task.task_id, thread_id, assignee, prompt, "pending", None,
                 task.created_by, task.created_at, task.updated_at, task.attempts),
            )
        return task

    def _set_status(self, task_id: str, status: str, *, result: str | None = None) -> bool:
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            cur = conn.execute(
                "UPDATE async_tasks SET status=?, result=COALESCE(?, result), updated_at=? "
                "WHERE task_id=?",
                (status, result, _now(), task_id),
            )
            return cur.rowcount > 0

    def claim(self, task_id: str) -> bool:
        """A runner takes the task (pending → working). False if not pending."""
        with self._lock, sqlite3.connect(str(self._db)) as conn:
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
        task = self.get(task_id)
        if task is None:
            return False
        ok = self._set_status(task_id, "done", result=result)
        if ok:
            key = blackboard_key or f"task:{task.assignee}:{task_id[:8]}"
            self._groups.blackboard(task.thread_id).write(key, result, writer=task.assignee)
        return ok

    def fail(self, task_id: str, error: str) -> bool:
        return self._set_status(task_id, "failed", result=error)

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
        cutoff = (datetime.now(UTC) - timedelta(seconds=max_age_seconds)).isoformat()
        now = _now()
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            failed = conn.execute(
                "UPDATE async_tasks SET status='failed', updated_at=?, "
                "result=COALESCE(result, ?) "
                "WHERE status='working' AND COALESCE(updated_at, created_at) <= ? "
                "AND COALESCE(attempts, 0) >= ?",
                (now, "task abandoned after repeated worker restarts", cutoff, max_attempts),
            ).rowcount
            requeued = conn.execute(
                "UPDATE async_tasks SET status='pending', updated_at=? "
                "WHERE status='working' AND COALESCE(updated_at, created_at) <= ? "
                "AND COALESCE(attempts, 0) < ?",
                (now, cutoff, max_attempts),
            ).rowcount
        return {"requeued": requeued, "failed": failed}

    def get(self, task_id: str) -> AsyncTask | None:
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            row = conn.execute("SELECT * FROM async_tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def pending(self, thread_id: str) -> list[AsyncTask]:
        return self._by_status(thread_id, "pending")

    def threads_with_pending(self) -> list[str]:
        """Distinct threads that have at least one pending task (for a runner)."""
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            rows = conn.execute(
                "SELECT DISTINCT thread_id FROM async_tasks WHERE status='pending'"
            ).fetchall()
        return [r[0] for r in rows]

    def counts(self, thread_id: str | None = None) -> dict[str, int]:
        """Task counts by status for diagnostics/UI badges."""
        if thread_id is None:
            sql = "SELECT status, COUNT(*) FROM async_tasks GROUP BY status"
            args: tuple[str, ...] = ()
        else:
            sql = (
                "SELECT status, COUNT(*) FROM async_tasks "
                "WHERE thread_id=? GROUP BY status"
            )
            args = (thread_id,)
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            rows = conn.execute(sql, args).fetchall()
        out = {status: 0 for status in _STATUSES}
        for status, count in rows:
            if status in out:
                out[str(status)] = int(count or 0)
        return out

    def list(self, thread_id: str) -> list[AsyncTask]:
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            rows = conn.execute(
                "SELECT * FROM async_tasks WHERE thread_id=? ORDER BY created_at", (thread_id,)
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def _by_status(self, thread_id: str, status: str) -> list[AsyncTask]:
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            rows = conn.execute(
                "SELECT * FROM async_tasks WHERE thread_id=? AND status=? ORDER BY created_at",
                (thread_id, status),
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

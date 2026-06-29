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
from datetime import UTC, datetime
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_async_thread ON async_tasks(thread_id, status)"
            )

    def _row_to_task(self, row) -> AsyncTask:
        return AsyncTask(
            task_id=row[0], thread_id=row[1], assignee=row[2], prompt=row[3],
            status=row[4], result=row[5], created_by=row[6], created_at=row[7],
        )

    def assign(self, thread_id: str, assignee: str, prompt: str, *, actor: str) -> AsyncTask:
        if not assignee or not prompt:
            raise ValueError("assignee and prompt are required")
        task = AsyncTask(uuid4().hex, thread_id, assignee, prompt, "pending", None,
                         actor or "user", _now())
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            conn.execute(
                "INSERT INTO async_tasks VALUES (?,?,?,?,?,?,?,?)",
                (task.task_id, thread_id, assignee, prompt, "pending", None,
                 task.created_by, task.created_at),
            )
        return task

    def _set_status(self, task_id: str, status: str, *, result: str | None = None) -> bool:
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            cur = conn.execute(
                "UPDATE async_tasks SET status=?, result=COALESCE(?, result) "
                "WHERE task_id=?",
                (status, result, task_id),
            )
            return cur.rowcount > 0

    def claim(self, task_id: str) -> bool:
        """A runner takes the task (pending → working). False if not pending."""
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            cur = conn.execute(
                "UPDATE async_tasks SET status='working' WHERE task_id=? AND status='pending'",
                (task_id,),
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

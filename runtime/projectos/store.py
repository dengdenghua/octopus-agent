"""Persistent store for the Project OS global state (sqlite, json columns).

Three tables — projects / milestones / tasks — mirroring the model. All writes
go through here so the engine never touches disk; reads return typed dataclasses.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from uuid import uuid4

from runtime.projectos.model import Milestone, Project, Task

_TERMINAL_TASK_STATUSES = frozenset({"done", "failed", "rejected"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS milestones (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, doc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, milestone_id TEXT NOT NULL, doc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS thread_projects (
    thread_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ms_project ON milestones(project_id);
CREATE INDEX IF NOT EXISTS idx_task_ms ON tasks(milestone_id);
CREATE INDEX IF NOT EXISTS idx_project_events_project
    ON project_events(project_id, created_at);
"""


def _default_dir() -> Path:
    from runtime.platform.process.paths import app_paths

    return app_paths().data_dir / "projectos"


class ProjectStore:
    def __init__(self, base_dir: Path | str | None = None) -> None:
        d = Path(base_dir) if base_dir else _default_dir()
        d.mkdir(parents=True, exist_ok=True)
        self._db = d / "projectos.db"
        self._lock = threading.Lock()
        with self._lock, sqlite3.connect(str(self._db)) as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db), timeout=10.0)

    # ── projects ─────────────────────────────────────────────────────────────
    def save_project(self, project: Project) -> Project:
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO projects(id, doc) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET doc=excluded.doc",
                (project.id, json.dumps(project.to_dict(), ensure_ascii=False)),
            )
        return project

    def get_project(self, project_id: str) -> Project | None:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT doc FROM projects WHERE id=?", (project_id,)).fetchone()
        return Project.from_dict(json.loads(row[0])) if row else None

    def list_projects(self) -> list[Project]:
        with self._lock, self._conn() as conn:
            rows = conn.execute("SELECT doc FROM projects ORDER BY id").fetchall()
        return [Project.from_dict(json.loads(r[0])) for r in rows]

    # ── audit events ────────────────────────────────────────────────────────
    def append_event(
        self,
        project_id: str,
        *,
        kind: str,
        payload: dict,
        event_id: str | None = None,
        created_at: float | None = None,
    ) -> dict:
        project = str(project_id or "").strip()
        event_kind = str(kind or "").strip()
        if not project or not event_kind:
            raise ValueError("project_id and kind are required")
        event = {
            "id": event_id or f"EV-{uuid4().hex[:12]}",
            "project_id": project,
            "kind": event_kind,
            "payload": dict(payload or {}),
            "created_at": float(created_at if created_at is not None else time.time()),
        }
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO project_events(id, project_id, kind, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    event["id"],
                    event["project_id"],
                    event["kind"],
                    json.dumps(event["payload"], ensure_ascii=False),
                    event["created_at"],
                ),
            )
        return event

    def events_for_project(
        self,
        project_id: str,
        *,
        limit: int = 100,
    ) -> list[dict]:
        project = str(project_id or "").strip()
        if not project:
            return []
        bounded_limit = max(1, min(int(limit or 100), 500))
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT id, project_id, kind, payload, created_at "
                "FROM project_events WHERE project_id=? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (project, bounded_limit),
            ).fetchall()
        events = [
            {
                "id": str(row[0]),
                "project_id": str(row[1]),
                "kind": str(row[2]),
                "payload": json.loads(row[3]),
                "created_at": float(row[4]),
            }
            for row in rows
        ]
        events.reverse()
        return events

    # ── thread bindings ─────────────────────────────────────────────────────
    def bind_thread(self, thread_id: str, project_id: str) -> None:
        thread = str(thread_id or "").strip()
        project = str(project_id or "").strip()
        if not thread or not project:
            return
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO thread_projects(thread_id, project_id) VALUES (?, ?) "
                "ON CONFLICT(thread_id) DO UPDATE SET project_id=excluded.project_id",
                (thread, project),
            )

    def project_for_thread(self, thread_id: str) -> Project | None:
        thread = str(thread_id or "").strip()
        if not thread:
            return None
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT project_id FROM thread_projects WHERE thread_id=?",
                (thread,),
            ).fetchone()
        if not row:
            return None
        return self.get_project(str(row[0]))

    # ── milestones ───────────────────────────────────────────────────────────
    def save_milestone(self, project_id: str, ms: Milestone) -> Milestone:
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO milestones(id, project_id, doc) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET doc=excluded.doc, project_id=excluded.project_id",
                (ms.id, project_id, json.dumps(ms.to_dict(), ensure_ascii=False)),
            )
        return ms

    def get_milestone(self, ms_id: str) -> Milestone | None:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT doc FROM milestones WHERE id=?", (ms_id,)).fetchone()
        return Milestone.from_dict(json.loads(row[0])) if row else None

    def milestones_for(self, project_id: str) -> list[Milestone]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT doc FROM milestones WHERE project_id=?", (project_id,)
            ).fetchall()
        return [Milestone.from_dict(json.loads(r[0])) for r in rows]

    # ── tasks ────────────────────────────────────────────────────────────────
    def save_task(self, task: Task, *, allow_terminal_rewrite: bool = False) -> Task:
        """Persist ``task``.

        Terminal task rows are immutable by default so a stale worker callback
        cannot downgrade ``done`` to ``failed`` or replace a failed task's
        diagnostic output. Recovery/operator actions that intentionally reopen
        work must pass ``allow_terminal_rewrite=True``.
        """
        with self._lock, self._conn() as conn:
            existing_row = conn.execute(
                "SELECT doc FROM tasks WHERE id=?",
                (task.id,),
            ).fetchone()
            if existing_row and not allow_terminal_rewrite:
                existing = Task.from_dict(json.loads(existing_row[0]))
                if existing.status in _TERMINAL_TASK_STATUSES:
                    return existing
            conn.execute(
                "INSERT INTO tasks(id, milestone_id, doc) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET doc=excluded.doc, milestone_id=excluded.milestone_id",
                (task.id, task.milestone_id, json.dumps(task.to_dict(), ensure_ascii=False)),
            )
        return task

    def get_task(self, task_id: str) -> Task | None:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT doc FROM tasks WHERE id=?", (task_id,)).fetchone()
        return Task.from_dict(json.loads(row[0])) if row else None

    def tasks_for_milestone(self, ms_id: str) -> list[Task]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT doc FROM tasks WHERE milestone_id=?", (ms_id,)
            ).fetchall()
        return [Task.from_dict(json.loads(r[0])) for r in rows]

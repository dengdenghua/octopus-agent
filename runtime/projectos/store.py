"""Persistent store for the Project OS global state (sqlite, json columns).

Three tables — projects / milestones / tasks — mirroring the model. All writes
go through here so the engine never touches disk; reads return typed dataclasses.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from runtime.projectos.model import Milestone, Project, Task

_TERMINAL_PROJECT_STATUSES = frozenset({"done", "failed"})
_TERMINAL_MILESTONE_STATUSES = frozenset({"done", "failed"})
_TERMINAL_TASK_STATUSES = frozenset({"done", "failed", "rejected"})
_TASK_TYPES = frozenset({"design", "code", "research", "analysis", "review"})
_TASK_STATUSES = frozenset({"pending", "ready", "running", "blocked", "done", "failed", "rejected"})
_MILESTONE_STATUSES = frozenset({"pending", "active", "in_progress", "blocked", "done", "failed"})
_PROJECT_STATUSES = frozenset({"planning", "running", "blocked", "done", "failed"})
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,239}$")
_SAFE_KIND_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_TEXT_LENGTH = 65_536
_MAX_NAME_LENGTH = 512
_MAX_LIST_ITEMS = 512
_MAX_JSON_BYTES = 1024 * 1024

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


def _require_id(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID_RE.fullmatch(text):
        raise ValueError(
            f"invalid {label}: use 1-240 letters, numbers, dot, underscore, colon, @, or hyphen"
        )
    return text


def _optional_id(value: object, *, label: str) -> str | None:
    text = str(value or "").strip()
    return _require_id(text, label=label) if text else None


def _require_kind(value: object) -> str:
    text = str(value or "").strip()
    if not _SAFE_KIND_RE.fullmatch(text):
        raise ValueError("invalid event kind")
    return text


def _text(
    value: object,
    *,
    label: str,
    max_length: int = _MAX_TEXT_LENGTH,
    default: str = "",
) -> str:
    text = str(value if value is not None else default).strip()
    if not text:
        text = default
    if len(text) > max_length or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text):
        raise ValueError(f"invalid {label}: too long or contains unsupported control characters")
    if any(ord(ch) == 127 for ch in text):
        raise ValueError(f"invalid {label}: contains unsupported control characters")
    return text


def _id_list(values: object, *, label: str) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        if len(out) >= _MAX_LIST_ITEMS:
            break
        safe = _optional_id(value, label=label)
        if safe:
            out.append(safe)
    return out


def _text_list(values: object, *, label: str) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        if len(out) >= _MAX_LIST_ITEMS:
            break
        text = _text(value, label=label, max_length=4096)
        if text:
            out.append(text)
    return out


def _json_value(value: Any, *, label: str) -> Any:
    try:
        blob = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: not JSON serializable") from exc
    if len(blob.encode("utf-8")) > _MAX_JSON_BYTES:
        raise ValueError(f"invalid {label}: JSON payload exceeds {_MAX_JSON_BYTES} bytes")
    try:
        return json.loads(blob)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label}: JSON round-trip failed") from exc


def _json_dict(value: Any, *, label: str) -> dict[str, Any]:
    normalized = _json_value(value or {}, label=label)
    return normalized if isinstance(normalized, dict) else {}


def _normalize_project(project: Project) -> Project:
    project_id = _require_id(project.id, label="project_id")
    return Project(
        id=project_id,
        name=_text(project.name, label="project name", max_length=_MAX_NAME_LENGTH, default=project_id),
        goal=_text(project.goal, label="project goal"),
        milestone_ids=_id_list(project.milestone_ids, label="milestone_id"),
        current_ms=_optional_id(project.current_ms, label="milestone_id"),
        status=project.status if project.status in _PROJECT_STATUSES else "planning",
    )


def _normalize_milestone(ms: Milestone) -> Milestone:
    ms_id = _require_id(ms.id, label="milestone_id")
    return Milestone(
        id=ms_id,
        name=_text(ms.name, label="milestone name", max_length=_MAX_NAME_LENGTH, default=ms_id),
        goal=_text(ms.goal, label="milestone goal"),
        spec=_json_dict(ms.spec, label="milestone spec"),
        success_criteria=_text_list(ms.success_criteria, label="success criterion"),
        status=ms.status if ms.status in _MILESTONE_STATUSES else "pending",
        dependencies=_id_list(ms.dependencies, label="milestone dependency"),
        task_ids=_id_list(ms.task_ids, label="task_id"),
    )


def _normalize_task(task: Task) -> Task:
    task_id = _require_id(task.id, label="task_id")
    milestone_id = _require_id(task.milestone_id, label="milestone_id")
    return Task(
        id=task_id,
        milestone_id=milestone_id,
        type=task.type if task.type in _TASK_TYPES else "code",
        goal=_text(task.goal, label="task goal"),
        assigned_role=_optional_id(task.assigned_role, label="assigned_role") or "engineer",
        assigned_agent=_optional_id(task.assigned_agent, label="assigned_agent") or "",
        status=task.status if task.status in _TASK_STATUSES else "pending",
        depends_on=_id_list(task.depends_on, label="task dependency"),
        input=_json_dict(task.input, label="task input"),
        output=_json_value(task.output, label="task output"),
        qa_verdict=(
            _json_dict(task.qa_verdict, label="task qa_verdict")
            if task.qa_verdict is not None
            else None
        ),
        attempts=max(0, min(int(task.attempts or 0), 100)),
    )


def _project_from_doc(raw: str) -> Project | None:
    try:
        return _normalize_project(Project.from_dict(json.loads(raw)))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _milestone_from_doc(raw: str) -> Milestone | None:
    try:
        return _normalize_milestone(Milestone.from_dict(json.loads(raw)))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _task_from_doc(raw: str) -> Task | None:
    try:
        return _normalize_task(Task.from_dict(json.loads(raw)))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


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
    def save_project(self, project: Project, *, allow_terminal_rewrite: bool = False) -> Project:
        """Persist ``project``.

        Terminal project rows are immutable by default so a stale tick cannot
        downgrade a completed project back to ``running``/``blocked``. Operator
        recovery paths must pass ``allow_terminal_rewrite=True`` explicitly.
        """
        project = _normalize_project(project)
        with self._lock, self._conn() as conn:
            existing_row = conn.execute(
                "SELECT doc FROM projects WHERE id=?",
                (project.id,),
            ).fetchone()
            if existing_row and not allow_terminal_rewrite:
                existing = _project_from_doc(existing_row[0])
                if existing is None:
                    raise ValueError(f"corrupt existing project row: {project.id}")
                if existing.status in _TERMINAL_PROJECT_STATUSES:
                    return existing
            conn.execute(
                "INSERT INTO projects(id, doc) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET doc=excluded.doc",
                (project.id, json.dumps(project.to_dict(), ensure_ascii=False)),
            )
        return project

    def get_project(self, project_id: str) -> Project | None:
        project_id = _require_id(project_id, label="project_id")
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT doc FROM projects WHERE id=?", (project_id,)).fetchone()
        return _project_from_doc(row[0]) if row else None

    def list_projects(self) -> list[Project]:
        with self._lock, self._conn() as conn:
            rows = conn.execute("SELECT doc FROM projects ORDER BY id").fetchall()
        projects: list[Project] = []
        for row in rows:
            project = _project_from_doc(row[0])
            if project is not None:
                projects.append(project)
        return projects

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
        project = _require_id(project_id, label="project_id")
        event_kind = _require_kind(kind)
        event_payload = _json_dict(payload, label="event payload")
        safe_event_id = (
            _require_id(event_id, label="event_id")
            if event_id is not None
            else f"EV-{uuid4().hex[:12]}"
        )
        event = {
            "id": safe_event_id,
            "project_id": project,
            "kind": event_kind,
            "payload": event_payload,
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
        project = _require_id(project_id, label="project_id")
        bounded_limit = max(1, min(int(limit or 100), 500))
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT id, project_id, kind, payload, created_at "
                "FROM project_events WHERE project_id=? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (project, bounded_limit),
            ).fetchall()
        events = []
        for row in rows:
            try:
                events.append(
                    {
                        "id": _require_id(row[0], label="event_id"),
                        "project_id": _require_id(row[1], label="project_id"),
                        "kind": _require_kind(row[2]),
                        "payload": _json_dict(json.loads(row[3]), label="event payload"),
                        "created_at": float(row[4]),
                    }
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        events.reverse()
        return events

    # ── thread bindings ─────────────────────────────────────────────────────
    def bind_thread(self, thread_id: str, project_id: str) -> None:
        thread = _require_id(thread_id, label="thread_id")
        project = _require_id(project_id, label="project_id")
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO thread_projects(thread_id, project_id) VALUES (?, ?) "
                "ON CONFLICT(thread_id) DO UPDATE SET project_id=excluded.project_id",
                (thread, project),
            )

    def project_for_thread(self, thread_id: str) -> Project | None:
        thread = _require_id(thread_id, label="thread_id")
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT project_id FROM thread_projects WHERE thread_id=?",
                (thread,),
            ).fetchone()
        if not row:
            return None
        try:
            return self.get_project(str(row[0]))
        except ValueError:
            return None

    # ── milestones ───────────────────────────────────────────────────────────
    def save_milestone(
        self,
        project_id: str,
        ms: Milestone,
        *,
        allow_terminal_rewrite: bool = False,
    ) -> Milestone:
        """Persist ``ms``.

        Terminal milestone rows are immutable by default for the same reason as
        terminal tasks/projects: a stale engine tick must not reopen or block a
        milestone that another tick has already completed.
        """
        project_id = _require_id(project_id, label="project_id")
        ms = _normalize_milestone(ms)
        with self._lock, self._conn() as conn:
            existing_row = conn.execute(
                "SELECT doc FROM milestones WHERE id=?",
                (ms.id,),
            ).fetchone()
            if existing_row and not allow_terminal_rewrite:
                existing = _milestone_from_doc(existing_row[0])
                if existing is None:
                    raise ValueError(f"corrupt existing milestone row: {ms.id}")
                if existing.status in _TERMINAL_MILESTONE_STATUSES:
                    return existing
            conn.execute(
                "INSERT INTO milestones(id, project_id, doc) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET doc=excluded.doc, project_id=excluded.project_id",
                (ms.id, project_id, json.dumps(ms.to_dict(), ensure_ascii=False)),
            )
        return ms

    def get_milestone(self, ms_id: str) -> Milestone | None:
        ms_id = _require_id(ms_id, label="milestone_id")
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT doc FROM milestones WHERE id=?", (ms_id,)).fetchone()
        return _milestone_from_doc(row[0]) if row else None

    def milestones_for(self, project_id: str) -> list[Milestone]:
        project_id = _require_id(project_id, label="project_id")
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT doc FROM milestones WHERE project_id=?", (project_id,)
            ).fetchall()
        milestones: list[Milestone] = []
        for row in rows:
            milestone = _milestone_from_doc(row[0])
            if milestone is not None:
                milestones.append(milestone)
        return milestones

    # ── tasks ────────────────────────────────────────────────────────────────
    def save_task(self, task: Task, *, allow_terminal_rewrite: bool = False) -> Task:
        """Persist ``task``.

        Terminal task rows are immutable by default so a stale worker callback
        cannot downgrade ``done`` to ``failed`` or replace a failed task's
        diagnostic output. Recovery/operator actions that intentionally reopen
        work must pass ``allow_terminal_rewrite=True``.
        """
        task = _normalize_task(task)
        with self._lock, self._conn() as conn:
            existing_row = conn.execute(
                "SELECT doc FROM tasks WHERE id=?",
                (task.id,),
            ).fetchone()
            if existing_row and not allow_terminal_rewrite:
                existing = _task_from_doc(existing_row[0])
                if existing is None:
                    raise ValueError(f"corrupt existing task row: {task.id}")
                if existing.status in _TERMINAL_TASK_STATUSES:
                    return existing
            conn.execute(
                "INSERT INTO tasks(id, milestone_id, doc) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET doc=excluded.doc, milestone_id=excluded.milestone_id",
                (task.id, task.milestone_id, json.dumps(task.to_dict(), ensure_ascii=False)),
            )
        return task

    def get_task(self, task_id: str) -> Task | None:
        task_id = _require_id(task_id, label="task_id")
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT doc FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _task_from_doc(row[0]) if row else None

    def tasks_for_milestone(self, ms_id: str) -> list[Task]:
        ms_id = _require_id(ms_id, label="milestone_id")
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT doc FROM tasks WHERE milestone_id=?", (ms_id,)
            ).fetchall()
        tasks: list[Task] = []
        for row in rows:
            task = _task_from_doc(row[0])
            if task is not None:
                tasks.append(task)
        return tasks

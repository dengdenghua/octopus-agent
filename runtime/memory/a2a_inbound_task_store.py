"""Durable A2A server TaskStore backed by the standard-library SQLite driver."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from a2a.server.context import ServerCallContext
from a2a.server.owner_resolver import OwnerResolver, resolve_user_scope
from a2a.server.tasks.task_store import TaskStore
from a2a.types import ListTasksRequest, ListTasksResponse, Task
from a2a.utils.errors import InvalidParamsError
from a2a.utils.task import decode_page_token, encode_page_token

from runtime.platform.io.sqlite import connect_closing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS a2a_inbound_tasks (
    owner       TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    context_id  TEXT NOT NULL DEFAULT '',
    status      INTEGER NOT NULL DEFAULT 0,
    payload     BLOB NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (owner, task_id)
);
CREATE INDEX IF NOT EXISTS idx_a2a_inbound_owner_updated
ON a2a_inbound_tasks(owner, updated_at DESC, task_id DESC);
CREATE INDEX IF NOT EXISTS idx_a2a_inbound_context
ON a2a_inbound_tasks(owner, context_id, updated_at DESC);
"""


class A2ASqliteTaskStore(TaskStore):
    """Cross-restart, owner-scoped implementation of the official A2A store API."""

    def __init__(
        self,
        base_dir: Path | str,
        *,
        owner_resolver: OwnerResolver = resolve_user_scope,
    ) -> None:
        self._dir = Path(base_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "inbound_tasks.db"
        self._lock = threading.RLock()
        self._owner_resolver = owner_resolver
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = connect_closing(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        return conn

    def _save(self, task: Task, owner: str) -> None:
        timestamp = datetime.now(UTC).isoformat()
        if task.HasField("status") and task.status.HasField("timestamp"):
            timestamp = task.status.timestamp.ToDatetime(tzinfo=UTC).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO a2a_inbound_tasks"
                "(owner,task_id,context_id,status,payload,updated_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(owner,task_id) DO UPDATE SET context_id=excluded.context_id,"
                "status=excluded.status,payload=excluded.payload,updated_at=excluded.updated_at",
                (
                    owner,
                    task.id,
                    task.context_id,
                    int(task.status.state),
                    task.SerializeToString(deterministic=True),
                    timestamp,
                ),
            )

    async def save(self, task: Task, context: ServerCallContext) -> None:
        await asyncio.to_thread(self._save, task, self._owner_resolver(context))

    def _get(self, task_id: str, owner: str) -> Task | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM a2a_inbound_tasks WHERE owner=? AND task_id=?",
                (owner, task_id),
            ).fetchone()
        return Task.FromString(bytes(row[0])) if row else None

    async def get(self, task_id: str, context: ServerCallContext) -> Task | None:
        return await asyncio.to_thread(self._get, task_id, self._owner_resolver(context))

    def _list(
        self,
        params: ListTasksRequest,
        owner: str,
    ) -> ListTasksResponse:
        sql = "SELECT task_id,payload FROM a2a_inbound_tasks WHERE owner=?"
        values: list[Any] = [owner]
        if params.context_id:
            sql += " AND context_id=?"
            values.append(params.context_id)
        if params.status:
            sql += " AND status=?"
            values.append(int(params.status))
        if params.HasField("status_timestamp_after"):
            sql += " AND updated_at>=?"
            values.append(
                params.status_timestamp_after.ToDatetime(tzinfo=UTC).isoformat()
            )
        sql += " ORDER BY updated_at DESC,task_id DESC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(values)).fetchall()
        tasks = [(str(task_id), Task.FromString(bytes(payload))) for task_id, payload in rows]
        start = 0
        if params.page_token:
            cursor = decode_page_token(params.page_token)
            matching = next((index for index, (task_id, _task) in enumerate(tasks) if task_id == cursor), None)
            if matching is None:
                raise InvalidParamsError(f"Invalid page token: {params.page_token}")
            start = matching
        size = max(1, min(int(params.page_size or 50), 100))
        page = tasks[start : start + size]
        next_index = start + size
        next_token = encode_page_token(tasks[next_index][0]) if next_index < len(tasks) else ""
        return ListTasksResponse(
            tasks=[task for _task_id, task in page],
            total_size=len(tasks),
            page_size=size,
            next_page_token=next_token,
        )

    async def list(
        self,
        params: ListTasksRequest,
        context: ServerCallContext,
    ) -> ListTasksResponse:
        return await asyncio.to_thread(self._list, params, self._owner_resolver(context))

    def _delete(self, task_id: str, owner: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM a2a_inbound_tasks WHERE owner=? AND task_id=?",
                (owner, task_id),
            )

    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        await asyncio.to_thread(self._delete, task_id, self._owner_resolver(context))


__all__ = ["A2ASqliteTaskStore"]

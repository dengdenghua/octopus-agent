"""Durable local mirror of remote A2A task lifecycle events."""

from __future__ import annotations

import builtins
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.platform.io.sqlite import connect_closing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS a2a_tasks (
    local_task_id  TEXT PRIMARY KEY,
    agent_id       TEXT NOT NULL,
    remote_task_id TEXT NOT NULL DEFAULT '',
    context_id     TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL,
    request_json   TEXT NOT NULL DEFAULT '{}',
    result_json    TEXT,
    error          TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    terminal_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_a2a_tasks_agent
ON a2a_tasks(agent_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_a2a_tasks_status
ON a2a_tasks(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS a2a_task_events (
    local_task_id TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    event_type    TEXT NOT NULL,
    status        TEXT NOT NULL,
    payload_json  TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    PRIMARY KEY (local_task_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_a2a_task_events_task
ON a2a_task_events(local_task_id, seq);
"""

_TASK_SCHEMA = "octopus.a2a_task.v1"
_EVENT_SCHEMA = "octopus.a2a_task_event.v1"
_STATES = frozenset(
    {
        "submitted",
        "working",
        "completed",
        "failed",
        "canceled",
        "input_required",
        "rejected",
        "auth_required",
        "unknown",
    }
)
_TERMINAL = frozenset({"completed", "failed", "canceled", "rejected"})


def canonical_a2a_state(value: Any) -> str:
    text = str(value if value is not None else "").strip().lower()
    numeric = {
        "0": "unknown",
        "1": "submitted",
        "2": "working",
        "3": "completed",
        "4": "failed",
        "5": "canceled",
        "6": "input_required",
        "7": "rejected",
        "8": "auth_required",
    }
    if text in numeric:
        return numeric[text]
    text = text.removeprefix("task_state_").replace("-", "_")
    return text if text in _STATES else "unknown"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json_dict(value: Any, *, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > 1024 * 1024:
        raise ValueError(f"{label} exceeds 1048576 bytes")
    decoded = json.loads(encoded)
    return decoded if isinstance(decoded, dict) else {}


def _dump(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


_COLUMNS = (
    "local_task_id,agent_id,remote_task_id,context_id,status,request_json,result_json,"
    "error,created_at,updated_at,terminal_at"
)


def _from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "schema": _TASK_SCHEMA,
        "local_task_id": str(row[0]),
        "agent_id": str(row[1]),
        "remote_task_id": str(row[2] or ""),
        "context_id": str(row[3] or ""),
        "status": str(row[4]),
        "request": _load(row[5]) or {},
        "result": _load(row[6]),
        "error": str(row[7]) if row[7] else None,
        "created_at": str(row[8]),
        "updated_at": str(row[9]),
        "terminal_at": str(row[10]) if row[10] else None,
    }


class A2ATaskStore:
    def __init__(self, base_dir: Path | str) -> None:
        self._dir = Path(base_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "tasks.db"
        self._lock = threading.RLock()
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        self._dir.mkdir(parents=True, exist_ok=True)
        conn = connect_closing(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        return conn

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        local_task_id: str,
        event_type: str,
        status: str,
        payload: dict[str, Any],
        timestamp: str,
    ) -> None:
        seq = int(
            conn.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM a2a_task_events WHERE local_task_id=?",
                (local_task_id,),
            ).fetchone()[0]
        )
        conn.execute(
            "INSERT INTO a2a_task_events"
            "(local_task_id,seq,event_type,status,payload_json,created_at) VALUES (?,?,?,?,?,?)",
            (local_task_id, seq, event_type, status, _dump(payload), timestamp),
        )

    def create(
        self,
        *,
        local_task_id: str,
        agent_id: str,
        request: dict[str, Any],
        context_id: str = "",
    ) -> dict[str, Any]:
        task, _created = self.create_once(
            local_task_id=local_task_id,
            agent_id=agent_id,
            request=request,
            context_id=context_id,
        )
        return task

    def create_once(
        self,
        *,
        local_task_id: str,
        agent_id: str,
        request: dict[str, Any],
        context_id: str = "",
    ) -> tuple[dict[str, Any], bool]:
        """Atomically create a task and report whether this caller owns dispatch."""
        local_task_id = str(local_task_id or "").strip()
        agent_id = str(agent_id or "").strip()
        if not local_task_id or not agent_id:
            raise ValueError("local_task_id and agent_id are required")
        request_payload = _json_dict(request, label="a2a request")
        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM a2a_tasks WHERE local_task_id=?", (local_task_id,)
            ).fetchone()
            if row:
                current = _from_row(row)
                if current["agent_id"] != agent_id or current["request"] != request_payload:
                    raise ValueError("local_task_id already belongs to a different A2A task")
                return current, False
            conn.execute(
                "INSERT INTO a2a_tasks"
                "(local_task_id,agent_id,context_id,status,request_json,created_at,updated_at) "
                "VALUES (?,?,?,'submitted',?,?,?)",
                (
                    local_task_id,
                    agent_id,
                    str(context_id or ""),
                    _dump(request_payload),
                    timestamp,
                    timestamp,
                ),
            )
            self._append_event(
                conn,
                local_task_id=local_task_id,
                event_type="submitted",
                status="submitted",
                payload={"agent_id": agent_id, "context_id": str(context_id or "")},
                timestamp=timestamp,
            )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM a2a_tasks WHERE local_task_id=?", (local_task_id,)
            ).fetchone()
        return _from_row(row), True

    def update(
        self,
        local_task_id: str,
        *,
        status: Any,
        remote_task_id: str = "",
        context_id: str = "",
        result: dict[str, Any] | None = None,
        error: str | None = None,
        event_type: str = "updated",
        event_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = canonical_a2a_state(status)
        result_payload = _json_dict(result, label="a2a result") if result is not None else None
        event = _json_dict(event_payload, label="a2a event")
        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM a2a_tasks WHERE local_task_id=?", (local_task_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"A2A task not found: {local_task_id}")
            current = _from_row(row)
            if current["status"] in _TERMINAL and state != current["status"]:
                raise ValueError("terminal A2A task state is immutable")
            terminal_at = timestamp if state in _TERMINAL else current["terminal_at"]
            conn.execute(
                "UPDATE a2a_tasks SET remote_task_id=?,context_id=?,status=?,result_json=?,"
                "error=?,updated_at=?,terminal_at=? WHERE local_task_id=?",
                (
                    str(remote_task_id or current["remote_task_id"]),
                    str(context_id or current["context_id"]),
                    state,
                    _dump(result_payload)
                    if result_payload is not None
                    else (
                        _dump(current["result"]) if isinstance(current["result"], dict) else None
                    ),
                    str(error)[:4000] if error else None,
                    timestamp,
                    terminal_at,
                    local_task_id,
                ),
            )
            self._append_event(
                conn,
                local_task_id=local_task_id,
                event_type=str(event_type or "updated")[:120],
                status=state,
                payload=event,
                timestamp=timestamp,
            )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM a2a_tasks WHERE local_task_id=?", (local_task_id,)
            ).fetchone()
        return _from_row(row)

    def get(self, local_task_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM a2a_tasks WHERE local_task_id=?", (local_task_id,)
            ).fetchone()
        return _from_row(row) if row else None

    def list(
        self,
        *,
        agent_id: str = "",
        status: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        state = canonical_a2a_state(status) if status else ""
        if status and state == "unknown" and str(status).strip().lower() not in {"unknown", "0"}:
            raise ValueError(f"invalid A2A task status: {status}")
        sql = f"SELECT {_COLUMNS} FROM a2a_tasks WHERE 1=1"
        params: list[Any] = []
        if agent_id:
            sql += " AND agent_id=?"
            params.append(agent_id)
        if state:
            sql += " AND status=?"
            params.append(state)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_from_row(row) for row in rows]

    def events(self, local_task_id: str, *, after_seq: int = 0) -> builtins.list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT seq,event_type,status,payload_json,created_at FROM a2a_task_events "
                "WHERE local_task_id=? AND seq>? ORDER BY seq",
                (local_task_id, max(0, int(after_seq))),
            ).fetchall()
        return [
            {
                "schema": _EVENT_SCHEMA,
                "local_task_id": local_task_id,
                "seq": int(seq),
                "event_type": str(event_type),
                "status": str(status),
                "payload": _load(payload_json) or {},
                "created_at": str(created_at),
            }
            for seq, event_type, status, payload_json, created_at in rows
        ]


__all__ = ["A2ATaskStore", "canonical_a2a_state"]

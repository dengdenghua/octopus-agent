"""Durable SQLite trace store for agent runtime facts.

This module is intentionally a sidecar to the existing JSONL journals.
JSONL remains append-only source material; this store gives product
surfaces and recovery code a Marvis-like read model for messages,
events, approvals, checkpoints, and token usage.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Literal

ApprovalDecision = Literal[
    "requested", "approved", "rejected", "timeout", "connection_lost", "error"
]
TaskRunStatus = Literal[
    "running",
    "completed",
    "failed",
    "interrupted",
    "cancelled",
    "unknown",
]

_TASK_RUN_TERMINAL_EVENTS: dict[str, TaskRunStatus] = {
    "TASK_RUN_COMPLETED": "completed",
    "TASK_RUN_FINISHED": "completed",
    "RUN_FINISHED": "completed",
    "TASK_RUN_FAILED": "failed",
    "RUN_FAILED": "failed",
    "REACT_ERROR": "failed",
    "TASK_RUN_INTERRUPTED": "interrupted",
    "RUN_INTERRUPTED": "interrupted",
    "REACT_CANCELLED": "interrupted",
    "TASK_RUN_CANCELLED": "cancelled",
    "RUN_CANCELLED": "cancelled",
}
_TASK_RUN_START_EVENTS: frozenset[str] = frozenset({
    "TASK_RUN_STARTED",
    "RUN_STARTED",
})
_TOOL_START_EVENTS: frozenset[str] = frozenset({
    "TOOL_CALL_START",
    "TOOL_START",
    "SUB_TOOL_START",
})
_TOOL_END_EVENTS: frozenset[str] = frozenset({
    "TOOL_CALL_END",
    "TOOL_CALL_FINISH",
    "TOOL_END",
    "SUB_TOOL_END",
})


_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    thread_id   TEXT NOT NULL,
    turn_id     TEXT,
    agent_id    TEXT,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trace_messages_thread ON messages(thread_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_messages_turn ON messages(turn_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_messages_agent ON messages(agent_id, id);

CREATE TABLE IF NOT EXISTS agui_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    thread_id   TEXT,
    turn_id     TEXT,
    task_id     TEXT,
    agent_id    TEXT,
    item_id     TEXT,
    event_type  TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trace_events_thread ON agui_events(thread_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_events_turn ON agui_events(turn_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_events_task ON agui_events(task_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_events_agent ON agui_events(agent_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_events_type ON agui_events(event_type, id);

CREATE TABLE IF NOT EXISTS approvals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    requested_at   TEXT NOT NULL,
    decided_at     TEXT,
    thread_id      TEXT,
    turn_id        TEXT,
    task_id        TEXT,
    agent_id       TEXT,
    tool_name      TEXT NOT NULL,
    tool_call_id   TEXT NOT NULL,
    args_preview   TEXT NOT NULL DEFAULT '',
    decision       TEXT NOT NULL,
    reason         TEXT NOT NULL DEFAULT '',
    metadata       TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trace_approvals_thread ON approvals(thread_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_approvals_tool_call ON approvals(tool_call_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_approvals_decision ON approvals(decision, id);

CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT NOT NULL,
    task_id           TEXT NOT NULL,
    thread_id         TEXT,
    turn_id           TEXT,
    agent_id          TEXT,
    checkpoint_type   TEXT NOT NULL,
    iteration         INTEGER NOT NULL DEFAULT 0,
    summary           TEXT NOT NULL DEFAULT '',
    state             TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trace_checkpoints_task ON agent_checkpoints(task_id, iteration, id);
CREATE INDEX IF NOT EXISTS idx_trace_checkpoints_thread ON agent_checkpoints(thread_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_checkpoints_type ON agent_checkpoints(checkpoint_type, id);

CREATE TABLE IF NOT EXISTS llm_token_usage (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT NOT NULL,
    task_id          TEXT,
    thread_id        TEXT,
    turn_id          TEXT,
    agent_id         TEXT,
    iteration        INTEGER NOT NULL DEFAULT 0,
    model            TEXT NOT NULL DEFAULT '',
    input_tokens     INTEGER NOT NULL DEFAULT 0,
    output_tokens    INTEGER NOT NULL DEFAULT 0,
    thinking_tokens  INTEGER NOT NULL DEFAULT 0,
    cached_tokens    INTEGER NOT NULL DEFAULT 0,
    cost_usd         REAL NOT NULL DEFAULT 0,
    is_local         INTEGER NOT NULL DEFAULT 0,
    metadata         TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trace_tokens_task ON llm_token_usage(task_id, iteration, id);
CREATE INDEX IF NOT EXISTS idx_trace_tokens_thread ON llm_token_usage(thread_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_tokens_agent ON llm_token_usage(agent_id, id);

CREATE TABLE IF NOT EXISTS resume_requests (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT NOT NULL,
    thread_id         TEXT NOT NULL,
    checkpoint_id     INTEGER NOT NULL,
    task_id           TEXT,
    status            TEXT NOT NULL,
    intent            TEXT NOT NULL DEFAULT '{}',
    confirmed_at      TEXT,
    consumed_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_trace_resume_requests_thread ON resume_requests(thread_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_resume_requests_checkpoint ON resume_requests(checkpoint_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_resume_requests_status ON resume_requests(status, id);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _json_loads(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


class AgentTraceStore:
    """SQLite-backed read model for agent trace facts."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.executescript(_SCHEMA)

    def record_message(
        self,
        *,
        thread_id: str,
        role: str,
        content: str,
        turn_id: str | None = None,
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages(ts, thread_id, turn_id, agent_id, role, content, metadata) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    ts or _now_iso(),
                    _clean_str(thread_id),
                    _optional_str(turn_id),
                    _optional_str(agent_id),
                    _clean_str(role),
                    str(content or ""),
                    _json_dumps(metadata),
                ),
            )
            return int(cur.lastrowid)

    def record_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any] | None,
        thread_id: str | None = None,
        turn_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        item_id: str | None = None,
        ts: str | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO agui_events("
                "ts, thread_id, turn_id, task_id, agent_id, item_id, event_type, payload"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts or _now_iso(),
                    _optional_str(thread_id),
                    _optional_str(turn_id),
                    _optional_str(task_id),
                    _optional_str(agent_id),
                    _optional_str(item_id),
                    _clean_str(event_type),
                    _json_dumps(payload),
                ),
            )
            return int(cur.lastrowid)

    def record_task_run_started(
        self,
        *,
        task_id: str,
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
        title: str = "",
        goal: str = "",
        mode: str = "",
        metadata: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> int:
        payload = {
            "schema": "octopus.task_run.started.v1",
            "title": str(title or ""),
            "goal": str(goal or ""),
            "mode": str(mode or ""),
            "metadata": metadata or {},
        }
        return self.record_event(
            event_type="TASK_RUN_STARTED",
            payload=payload,
            thread_id=thread_id,
            turn_id=turn_id,
            task_id=task_id,
            agent_id=agent_id,
            ts=ts,
        )

    def record_task_run_finished(
        self,
        *,
        task_id: str,
        status: TaskRunStatus,
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
        summary: str = "",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> int:
        event_type = {
            "completed": "TASK_RUN_COMPLETED",
            "failed": "TASK_RUN_FAILED",
            "interrupted": "TASK_RUN_INTERRUPTED",
            "cancelled": "TASK_RUN_CANCELLED",
        }.get(status, "TASK_RUN_FINISHED")
        payload = {
            "schema": "octopus.task_run.finished.v1",
            "status": status,
            "summary": str(summary or ""),
            "reason": str(reason or ""),
            "metadata": metadata or {},
        }
        return self.record_event(
            event_type=event_type,
            payload=payload,
            thread_id=thread_id,
            turn_id=turn_id,
            task_id=task_id,
            agent_id=agent_id,
            ts=ts,
        )

    def record_approval(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        decision: ApprovalDecision,
        reason: str = "",
        args_preview: str = "",
        thread_id: str | None = None,
        turn_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        requested_at: str | None = None,
        decided_at: str | None = None,
    ) -> int:
        requested = requested_at or _now_iso()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO approvals("
                "requested_at, decided_at, thread_id, turn_id, task_id, agent_id, "
                "tool_name, tool_call_id, args_preview, decision, reason, metadata"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    requested,
                    decided_at or requested,
                    _optional_str(thread_id),
                    _optional_str(turn_id),
                    _optional_str(task_id),
                    _optional_str(agent_id),
                    _clean_str(tool_name),
                    _clean_str(tool_call_id),
                    str(args_preview or ""),
                    _clean_str(decision),
                    str(reason or ""),
                    _json_dumps(metadata),
                ),
            )
            return int(cur.lastrowid)

    def record_checkpoint(
        self,
        *,
        task_id: str,
        checkpoint_type: str,
        state: dict[str, Any],
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
        iteration: int = 0,
        summary: str = "",
        ts: str | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO agent_checkpoints("
                "ts, task_id, thread_id, turn_id, agent_id, checkpoint_type, iteration, summary, state"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts or _now_iso(),
                    _clean_str(task_id),
                    _optional_str(thread_id),
                    _optional_str(turn_id),
                    _optional_str(agent_id),
                    _clean_str(checkpoint_type),
                    int(iteration or 0),
                    str(summary or ""),
                    _json_dumps(state),
                ),
            )
            return int(cur.lastrowid)

    def record_token_usage(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        task_id: str | None = None,
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
        iteration: int = 0,
        model: str = "",
        thinking_tokens: int = 0,
        cached_tokens: int = 0,
        cost_usd: float = 0.0,
        is_local: bool = False,
        metadata: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO llm_token_usage("
                "ts, task_id, thread_id, turn_id, agent_id, iteration, model, "
                "input_tokens, output_tokens, thinking_tokens, cached_tokens, cost_usd, "
                "is_local, metadata"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts or _now_iso(),
                    _optional_str(task_id),
                    _optional_str(thread_id),
                    _optional_str(turn_id),
                    _optional_str(agent_id),
                    int(iteration or 0),
                    str(model or ""),
                    max(0, int(input_tokens or 0)),
                    max(0, int(output_tokens or 0)),
                    max(0, int(thinking_tokens or 0)),
                    max(0, int(cached_tokens or 0)),
                    float(cost_usd or 0.0),
                    1 if is_local else 0,
                    _json_dumps(metadata),
                ),
            )
            return int(cur.lastrowid)

    def record_resume_request(
        self,
        *,
        thread_id: str,
        checkpoint_id: int,
        task_id: str | None = None,
        status: str = "pending",
        intent: dict[str, Any] | None = None,
        confirmed_at: str | None = None,
        consumed_at: str | None = None,
        ts: str | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO resume_requests("
                "ts, thread_id, checkpoint_id, task_id, status, intent, confirmed_at, consumed_at"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts or _now_iso(),
                    _clean_str(thread_id),
                    int(checkpoint_id or 0),
                    _optional_str(task_id),
                    _clean_str(status) or "pending",
                    _json_dumps(_sanitize_resume_intent(intent)),
                    _optional_str(confirmed_at),
                    _optional_str(consumed_at),
                ),
            )
            return int(cur.lastrowid)

    def messages(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self._query(
            "messages",
            filters={
                "thread_id": thread_id,
                "turn_id": turn_id,
                "agent_id": agent_id,
            },
            limit=limit,
            offset=offset,
        )
        return [_decode_row(row, json_fields=("metadata",)) for row in rows]

    def events(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self._query(
            "agui_events",
            filters={
                "thread_id": thread_id,
                "turn_id": turn_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "event_type": event_type,
            },
            limit=limit,
            offset=offset,
        )
        return [_decode_row(row, json_fields=("payload",)) for row in rows]

    def approvals(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        tool_call_id: str | None = None,
        decision: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self._query(
            "approvals",
            filters={
                "thread_id": thread_id,
                "turn_id": turn_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "tool_call_id": tool_call_id,
                "decision": decision,
            },
            limit=limit,
            offset=offset,
        )
        return [_decode_row(row, json_fields=("metadata",)) for row in rows]

    def token_usage(
        self,
        *,
        task_id: str | None = None,
        thread_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self._query(
            "llm_token_usage",
            filters={
                "task_id": task_id,
                "thread_id": thread_id,
                "agent_id": agent_id,
            },
            limit=limit,
            offset=offset,
        )
        return [_decode_row(row, json_fields=("metadata",), bool_fields=("is_local",)) for row in rows]

    def resume_requests(
        self,
        *,
        thread_id: str | None = None,
        checkpoint_id: int | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        filters: dict[str, str | None] = {}
        if thread_id is not None:
            filters["thread_id"] = thread_id
        if status is not None:
            filters["status"] = status
        rows = self._query(
            "resume_requests",
            filters=filters,
            limit=limit,
            offset=offset,
        )
        items = [_decode_row(row, json_fields=("intent",)) for row in rows]
        if checkpoint_id is not None:
            items = [row for row in items if int(row.get("checkpoint_id") or 0) == int(checkpoint_id)]
        return items

    def latest_pending_resume_request(
        self,
        *,
        thread_id: str,
    ) -> dict[str, Any] | None:
        rows = self.resume_requests(thread_id=thread_id, status="pending", limit=1)
        return rows[0] if rows else None

    def confirm_resume_request(
        self,
        *,
        thread_id: str,
        checkpoint_id: int,
        confirmation_text: str = "",
    ) -> dict[str, Any] | None:
        request = self.latest_pending_resume_request(thread_id=thread_id)
        if request is None or int(request.get("checkpoint_id") or 0) != int(checkpoint_id or 0):
            return None
        intent = _sanitize_resume_intent(request.get("intent"))
        intent["requires_confirmation"] = False
        intent["confirmed"] = True
        if confirmation_text:
            intent["confirmation_text"] = confirmation_text
        confirmed_at = _now_iso()
        with self._lock:
            self._conn.execute(
                "UPDATE resume_requests SET status = ?, confirmed_at = ?, intent = ? WHERE id = ?",
                (
                    "confirmed",
                    confirmed_at,
                    _json_dumps(intent),
                    int(request["id"]),
                ),
            )
        return self.resume_requests(thread_id=thread_id, checkpoint_id=checkpoint_id, status="confirmed", limit=1)[0]

    def consume_resume_request(self, request_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM resume_requests WHERE id = ?",
                (int(request_id),),
            ).fetchone()
            if row is None:
                return None
            consumed_at = _now_iso()
            self._conn.execute(
                "UPDATE resume_requests SET status = ?, consumed_at = ? WHERE id = ?",
                ("consumed", consumed_at, int(request_id)),
            )
        with self._lock:
            updated = self._conn.execute(
                "SELECT * FROM resume_requests WHERE id = ?",
                (int(request_id),),
            ).fetchone()
        return _decode_row(updated, json_fields=("intent",)) if updated is not None else None

    def checkpoints(
        self,
        *,
        task_id: str | None = None,
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
        checkpoint_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self._query(
            "agent_checkpoints",
            filters={
                "task_id": task_id,
                "thread_id": thread_id,
                "turn_id": turn_id,
                "agent_id": agent_id,
                "checkpoint_type": checkpoint_type,
            },
            limit=limit,
            offset=offset,
        )
        return [_decode_row(row, json_fields=("state",)) for row in rows]

    def latest_checkpoint(
        self,
        *,
        task_id: str,
        checkpoint_type: str | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["task_id = ?"]
        params: list[Any] = [task_id]
        if checkpoint_type is not None:
            clauses.append("checkpoint_type = ?")
            params.append(checkpoint_type)
        sql = (
            "SELECT * FROM agent_checkpoints WHERE "
            + " AND ".join(clauses)
            + " ORDER BY iteration DESC, id DESC LIMIT 1"
        )
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return _decode_row(row, json_fields=("state",)) if row is not None else None

    def checkpoint_by_id(self, checkpoint_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agent_checkpoints WHERE id = ?",
                (int(checkpoint_id),),
            ).fetchone()
        return _decode_row(row, json_fields=("state",)) if row is not None else None

    def resume_proposal(self, checkpoint_id: int) -> dict[str, Any] | None:
        checkpoint = self.checkpoint_by_id(checkpoint_id)
        if checkpoint is None:
            return None
        return _resume_proposal_from_checkpoint(checkpoint)

    def resume_proposals(
        self,
        *,
        task_id: str | None = None,
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
        checkpoint_type: str | None = None,
        limit: int = 5,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        checkpoints = self.checkpoints(
            task_id=task_id,
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            checkpoint_type=checkpoint_type,
            limit=limit,
            offset=offset,
        )
        return [_resume_proposal_from_checkpoint(checkpoint) for checkpoint in checkpoints]

    def task_run(self, task_id: str) -> dict[str, Any] | None:
        task_id = _clean_str(task_id)
        if not task_id:
            return None
        events = self.events(task_id=task_id, limit=10000)
        checkpoints = self.checkpoints(task_id=task_id, limit=10000)
        token_rows = self.token_usage(task_id=task_id, limit=10000)
        if not events and not checkpoints and not token_rows:
            return None
        approvals = self._approvals_for_task(task_id)
        return _task_run_from_rows(
            task_id=task_id,
            events=events,
            checkpoints=checkpoints,
            token_rows=token_rows,
            approvals=approvals,
            include_events=True,
        )

    def task_runs(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
        status: TaskRunStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self._task_run_ids(
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
        )
        runs: list[dict[str, Any]] = []
        for row in rows:
            run = self.task_run(str(row["task_id"]))
            if run is None:
                continue
            if status is not None and run.get("status") != status:
                continue
            run.pop("events", None)
            runs.append(run)
        start = max(0, int(offset or 0))
        end = start + max(0, int(limit or 0))
        return runs[start:end]

    def task_run_review(self, task_id: str) -> dict[str, Any] | None:
        run = self.task_run(task_id)
        if run is None:
            return None
        approvals = self._approvals_for_task(str(run["task_id"]))
        return _task_run_review_from_run(run, approvals)

    def stats(
        self,
        *,
        thread_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            counts = {
                "messages": self._count_locked(
                    "messages",
                    {
                        "thread_id": thread_id,
                        "turn_id": turn_id,
                        "agent_id": agent_id,
                    },
                ),
                "events": self._count_locked(
                    "agui_events",
                    {
                        "thread_id": thread_id,
                        "turn_id": turn_id,
                        "task_id": task_id,
                        "agent_id": agent_id,
                    },
                ),
                "approvals": self._count_locked(
                    "approvals",
                    {
                        "thread_id": thread_id,
                        "turn_id": turn_id,
                        "task_id": task_id,
                        "agent_id": agent_id,
                    },
                ),
                "checkpoints": self._count_locked(
                    "agent_checkpoints",
                    {
                        "thread_id": thread_id,
                        "turn_id": turn_id,
                        "task_id": task_id,
                        "agent_id": agent_id,
                    },
                ),
                "token_usage": self._count_locked(
                    "llm_token_usage",
                    {
                        "thread_id": thread_id,
                        "turn_id": turn_id,
                        "task_id": task_id,
                        "agent_id": agent_id,
                    },
                ),
                "resume_requests": self._count_locked(
                    "resume_requests",
                    {
                        "thread_id": thread_id,
                    },
                ),
            }
            token_where, token_params = self._where_params(
                {
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "task_id": task_id,
                    "agent_id": agent_id,
                }
            )
            token_row = self._conn.execute(
                "SELECT "
                "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
                "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
                "COALESCE(SUM(thinking_tokens), 0) AS thinking_tokens, "
                "COALESCE(SUM(cached_tokens), 0) AS cached_tokens, "
                "COALESCE(SUM(cost_usd), 0) AS cost_usd "
                f"FROM llm_token_usage{token_where}",
                token_params,
            ).fetchone()
        return {
            **counts,
            "token_totals": {
                "input_tokens": int(token_row["input_tokens"]) if token_row else 0,
                "output_tokens": int(token_row["output_tokens"]) if token_row else 0,
                "thinking_tokens": int(token_row["thinking_tokens"]) if token_row else 0,
                "cached_tokens": int(token_row["cached_tokens"]) if token_row else 0,
                "cost_usd": float(token_row["cost_usd"]) if token_row else 0.0,
            },
        }

    def _where_params(self, filters: dict[str, str | None]) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for key, value in filters.items():
            if value is None:
                continue
            clauses.append(f"{key} = ?")
            params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return where, params

    def _query(
        self,
        table: str,
        *,
        filters: dict[str, str | None],
        limit: int,
        offset: int,
    ) -> list[sqlite3.Row]:
        where, params = self._where_params(filters)
        sql = f"SELECT * FROM {table}{where} ORDER BY id ASC LIMIT ? OFFSET ?"
        params.extend([max(0, int(limit or 0)), max(0, int(offset or 0))])
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def _count_locked(self, table: str, filters: dict[str, str | None] | None = None) -> int:
        where, params = self._where_params(filters or {})
        row = self._conn.execute(f"SELECT COUNT(*) AS c FROM {table}{where}", params).fetchone()
        return int(row["c"]) if row else 0

    def _task_run_ids(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[sqlite3.Row]:
        parts: list[str] = []
        params: list[Any] = []
        for table in ("agui_events", "agent_checkpoints", "llm_token_usage"):
            clauses = ["task_id IS NOT NULL", "task_id != ''"]
            for key, value in (
                ("thread_id", thread_id),
                ("turn_id", turn_id),
                ("agent_id", agent_id),
            ):
                if value is not None:
                    clauses.append(f"{key} = ?")
                    params.append(value)
            parts.append(
                f"SELECT task_id, MAX(ts) AS updated_at FROM {table} "
                f"WHERE {' AND '.join(clauses)} GROUP BY task_id"
            )
        sql = (
            "SELECT task_id, MAX(updated_at) AS updated_at FROM ("
            + " UNION ALL ".join(parts)
            + ") GROUP BY task_id ORDER BY updated_at DESC, task_id ASC"
        )
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def _approvals_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._query(
            "approvals",
            filters={"task_id": task_id},
            limit=10000,
            offset=0,
        )
        return [_decode_row(row, json_fields=("metadata",)) for row in rows]

    def close(self) -> None:
        with self._lock, contextlib.suppress(sqlite3.Error):
            self._conn.close()

    def __enter__(self) -> AgentTraceStore:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


def _optional_str(value: Any) -> str | None:
    text = _clean_str(value)
    return text or None


def _decode_row(
    row: sqlite3.Row,
    *,
    json_fields: tuple[str, ...] = (),
    bool_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    out = dict(row)
    for field in json_fields:
        out[field] = _json_loads(out.get(field))
    for field in bool_fields:
        out[field] = bool(out.get(field))
    return out


def _event_key(event_type: Any) -> str:
    return _clean_str(event_type).replace("-", "_").upper()


def _event_status(event_type: Any, payload: Any | None = None) -> TaskRunStatus | None:
    key = _event_key(event_type)
    if key in _TASK_RUN_START_EVENTS:
        return "running"
    if key == "TASK_RUN_FINISHED" and isinstance(payload, dict):
        status = str(payload.get("status") or "").lower()
        if status in {
            "running",
            "completed",
            "failed",
            "interrupted",
            "cancelled",
            "unknown",
        }:
            return status  # type: ignore[return-value]
    return _TASK_RUN_TERMINAL_EVENTS.get(key)


def _ts_max(values: list[str]) -> str | None:
    clean = [value for value in values if isinstance(value, str) and value]
    return max(clean) if clean else None


def _tool_name_from_payload(payload: Any) -> str:
    raw = payload if isinstance(payload, dict) else {}
    for key in ("tool", "tool_name", "name"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _tool_event_failed(payload: Any) -> bool:
    raw = payload if isinstance(payload, dict) else {}
    if raw.get("is_error") is True:
        return True
    status = str(raw.get("status") or raw.get("decision") or "").lower()
    return status in {"error", "failed", "failure", "rejected", "cancelled"}


def _task_run_from_rows(
    *,
    task_id: str,
    events: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    token_rows: list[dict[str, Any]],
    approvals: list[dict[str, Any]],
    include_events: bool,
) -> dict[str, Any]:
    sorted_events = sorted(events, key=lambda row: (str(row.get("ts") or ""), int(row.get("id") or 0)))
    start_event = next(
        (event for event in sorted_events if _event_key(event.get("event_type")) in _TASK_RUN_START_EVENTS),
        sorted_events[0] if sorted_events else None,
    )
    terminal_events = [
        event
        for event in sorted_events
        if _event_key(event.get("event_type")) in _TASK_RUN_TERMINAL_EVENTS
    ]
    latest_terminal = terminal_events[-1] if terminal_events else None
    start_payload = start_event.get("payload") if isinstance(start_event, dict) else {}
    start_payload = start_payload if isinstance(start_payload, dict) else {}
    finish_payload = latest_terminal.get("payload") if isinstance(latest_terminal, dict) else {}
    finish_payload = finish_payload if isinstance(finish_payload, dict) else {}
    status = (
        _event_status(latest_terminal.get("event_type"), finish_payload)  # type: ignore[union-attr]
        if latest_terminal is not None
        else ("running" if sorted_events else "unknown")
    )
    status = status or "unknown"

    tool_starts = [
        event
        for event in sorted_events
        if _event_key(event.get("event_type")) in _TOOL_START_EVENTS
    ]
    tool_ends = [
        event
        for event in sorted_events
        if _event_key(event.get("event_type")) in _TOOL_END_EVENTS
    ]
    tool_names = sorted({
        name
        for event in (*tool_starts, *tool_ends)
        if (name := _tool_name_from_payload(event.get("payload")))
    })

    token_totals = {
        "input_tokens": sum(int(row.get("input_tokens") or 0) for row in token_rows),
        "output_tokens": sum(int(row.get("output_tokens") or 0) for row in token_rows),
        "thinking_tokens": sum(int(row.get("thinking_tokens") or 0) for row in token_rows),
        "cached_tokens": sum(int(row.get("cached_tokens") or 0) for row in token_rows),
        "cost_usd": sum(float(row.get("cost_usd") or 0.0) for row in token_rows),
    }
    ts_values = [
        str(row.get("ts") or "")
        for row in (*sorted_events, *checkpoints, *token_rows)
    ]
    completed_at = str(latest_terminal.get("ts") or "") if latest_terminal is not None else None
    run = {
        "task_id": task_id,
        "thread_id": _first_nonempty(
            start_event,
            sorted_events,
            checkpoints,
            token_rows,
            "thread_id",
        ),
        "turn_id": _first_nonempty(
            start_event,
            sorted_events,
            checkpoints,
            token_rows,
            "turn_id",
        ),
        "agent_id": _first_nonempty(
            start_event,
            sorted_events,
            checkpoints,
            token_rows,
            "agent_id",
        ),
        "status": status,
        "title": str(start_payload.get("title") or ""),
        "goal": str(start_payload.get("goal") or ""),
        "mode": str(start_payload.get("mode") or ""),
        "summary": str(finish_payload.get("summary") or ""),
        "reason": str(finish_payload.get("reason") or ""),
        "started_at": str(start_event.get("ts") or "") if isinstance(start_event, dict) else None,
        "completed_at": completed_at or None,
        "updated_at": _ts_max(ts_values),
        "latest_event_type": sorted_events[-1].get("event_type") if sorted_events else None,
        "event_count": len(sorted_events),
        "tool_calls_started": len(tool_starts),
        "tool_calls_finished": len(tool_ends),
        "tool_errors": sum(1 for event in tool_ends if _tool_event_failed(event.get("payload"))),
        "tool_names": tool_names,
        "approval_count": len(approvals),
        "approval_rejections": sum(
            1
            for row in approvals
            if str(row.get("decision") or "").lower()
            in {"rejected", "timeout", "connection_lost", "error"}
        ),
        "checkpoint_count": len(checkpoints),
        "token_usage_count": len(token_rows),
        "token_totals": token_totals,
    }
    if include_events:
        run["events"] = sorted_events
    return run


def _first_nonempty(
    start_event: dict[str, Any] | None,
    events: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    token_rows: list[dict[str, Any]],
    key: str,
) -> str | None:
    rows: list[dict[str, Any]] = []
    if isinstance(start_event, dict):
        rows.append(start_event)
    rows.extend(events)
    rows.extend(checkpoints)
    rows.extend(token_rows)
    for row in rows:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _task_run_review_from_run(
    run: dict[str, Any],
    approvals: list[dict[str, Any]],
) -> dict[str, Any]:
    events = run.get("events") if isinstance(run.get("events"), list) else []
    findings = _task_run_findings(run, approvals, events)
    score, score_reasons = _task_run_review_score(run, findings)
    return {
        "schema": "octopus.task_run_review.v1",
        "task_id": run.get("task_id"),
        "thread_id": run.get("thread_id"),
        "turn_id": run.get("turn_id"),
        "agent_id": run.get("agent_id"),
        "status": run.get("status"),
        "score": score,
        "score_reasons": score_reasons,
        "findings": findings,
        "replay": _task_run_replay(events, approvals),
        "learning_candidates": _task_run_learning_candidates(run, findings),
        "backlog_candidates": _task_run_backlog_candidates(run, findings),
        "summary": {
            "title": run.get("title") or "",
            "goal": run.get("goal") or "",
            "mode": run.get("mode") or "",
            "tool_calls_started": run.get("tool_calls_started") or 0,
            "tool_calls_finished": run.get("tool_calls_finished") or 0,
            "tool_errors": run.get("tool_errors") or 0,
            "approval_count": run.get("approval_count") or 0,
            "approval_rejections": run.get("approval_rejections") or 0,
            "checkpoint_count": run.get("checkpoint_count") or 0,
            "token_totals": run.get("token_totals") or {},
        },
    }


def _task_run_findings(
    run: dict[str, Any],
    approvals: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    status = str(run.get("status") or "unknown")
    if status in {"failed", "interrupted", "cancelled", "unknown"}:
        findings.append({
            "type": "terminal_status",
            "severity": "high" if status in {"failed", "cancelled"} else "medium",
            "title": f"Task ended as {status}",
            "evidence": {
                "status": status,
                "reason": run.get("reason") or "",
                "latest_event_type": run.get("latest_event_type"),
            },
            "recommendation": "Create a regression replay case from this run before changing prompts or tools.",
        })

    failed_tool_events = [
        event for event in events
        if _event_key(event.get("event_type")) in _TOOL_END_EVENTS
        and _tool_event_failed(event.get("payload"))
    ]
    for event in failed_tool_events[:5]:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        findings.append({
            "type": "tool_error",
            "severity": "high",
            "title": f"Tool failed: {_tool_name_from_payload(payload) or 'unknown'}",
            "evidence": {
                "event_id": event.get("id"),
                "tool": _tool_name_from_payload(payload),
                "status": payload.get("status"),
                "is_error": payload.get("is_error"),
                "output_preview": _truncate(payload.get("output") or payload.get("output_preview"), 280),
            },
            "recommendation": "Capture this tool input/output pair as a replay fixture or add a preflight validation rule.",
        })

    started = int(run.get("tool_calls_started") or 0)
    finished = int(run.get("tool_calls_finished") or 0)
    if started > finished:
        findings.append({
            "type": "dangling_tool_call",
            "severity": "medium",
            "title": "Tool call started without matching completion",
            "evidence": {"started": started, "finished": finished},
            "recommendation": "Check cancellation, background task, or event bridge handling for unmatched tool calls.",
        })

    rejected = [
        row for row in approvals
        if str(row.get("decision") or "").lower()
        in {"rejected", "timeout", "connection_lost", "error"}
    ]
    for row in rejected[:5]:
        findings.append({
            "type": "permission_friction",
            "severity": "medium",
            "title": f"Permission blocked or failed: {row.get('tool_name')}",
            "evidence": {
                "tool": row.get("tool_name"),
                "decision": row.get("decision"),
                "reason": row.get("reason") or "",
                "trust_gateway": _trust_gateway_from_approval(row),
            },
            "recommendation": "Decide whether this should become a static policy rule, a safer alternative tool, or an agent planning constraint.",
        })

    risky_approvals = [
        row for row in approvals
        if str(row.get("decision") or "").lower() == "approved"
        and _approval_risk_level(row) in {"high", "critical"}
    ]
    for row in risky_approvals[:5]:
        findings.append({
            "type": "high_risk_approval",
            "severity": "medium",
            "title": f"High-risk tool approved: {row.get('tool_name')}",
            "evidence": {
                "tool": row.get("tool_name"),
                "risk_level": _approval_risk_level(row),
                "trust_gateway": _trust_gateway_from_approval(row),
            },
            "recommendation": "Keep this approval visible in replay and require evidence that the action stayed within scope.",
        })

    if (
        status == "completed"
        and not findings
        and int(run.get("tool_calls_finished") or 0) > 0
    ):
        findings.append({
            "type": "success_pattern",
            "severity": "info",
            "title": "Completed with tools and no detected failures",
            "evidence": {
                "tool_names": run.get("tool_names") or [],
                "checkpoint_count": run.get("checkpoint_count") or 0,
            },
            "recommendation": "Store as a positive replay example if the user outcome was actually useful.",
        })
    return findings


def _task_run_review_score(
    run: dict[str, Any],
    findings: list[dict[str, Any]],
) -> tuple[float, list[str]]:
    status = str(run.get("status") or "unknown")
    score = {
        "completed": 1.0,
        "running": 0.4,
        "failed": 0.2,
        "interrupted": 0.25,
        "cancelled": 0.2,
        "unknown": 0.3,
    }.get(status, 0.3)
    reasons = [f"status:{status}"]
    penalties = {
        "tool_error": 0.2,
        "permission_friction": 0.12,
        "high_risk_approval": 0.06,
        "dangling_tool_call": 0.1,
        "terminal_status": 0.05,
    }
    for finding in findings:
        ftype = str(finding.get("type") or "")
        penalty = penalties.get(ftype, 0.0)
        if penalty:
            score -= penalty
            reasons.append(f"{ftype}:-{penalty:.2f}")
    score = round(max(0.0, min(1.0, score)), 3)
    return score, reasons


def _task_run_replay(
    events: list[dict[str, Any]],
    approvals: list[dict[str, Any]],
) -> dict[str, Any]:
    approval_by_call = {
        str(row.get("tool_call_id") or ""): row
        for row in approvals
        if row.get("tool_call_id")
    }
    steps: list[dict[str, Any]] = []
    for event in events:
        event_type = _event_key(event.get("event_type"))
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type in _TASK_RUN_START_EVENTS:
            steps.append({
                "kind": "task_start",
                "ts": event.get("ts"),
                "goal": payload.get("goal") or "",
                "mode": payload.get("mode") or "",
            })
        elif event_type in _TOOL_START_EVENTS:
            tool_call_id = str(
                payload.get("tool_call_id")
                or payload.get("id")
                or event.get("item_id")
                or ""
            )
            approval = approval_by_call.get(tool_call_id)
            steps.append({
                "kind": "tool_start",
                "ts": event.get("ts"),
                "tool": _tool_name_from_payload(payload),
                "tool_call_id": tool_call_id,
                "input_preview": _truncate(payload.get("input") or payload.get("input_preview"), 500),
                "approval": _approval_replay_fragment(approval),
            })
        elif event_type in _TOOL_END_EVENTS:
            steps.append({
                "kind": "tool_end",
                "ts": event.get("ts"),
                "tool": _tool_name_from_payload(payload),
                "status": payload.get("status") or ("error" if payload.get("is_error") else "success"),
                "is_error": bool(_tool_event_failed(payload)),
                "output_preview": _truncate(payload.get("output") or payload.get("output_preview"), 500),
            })
        elif event_type in _TASK_RUN_TERMINAL_EVENTS or event_type.startswith("REACT_"):
            steps.append({
                "kind": "task_event",
                "ts": event.get("ts"),
                "event_type": event.get("event_type"),
                "status": payload.get("status"),
                "reason": payload.get("reason") or payload.get("message") or "",
            })
    return {
        "replayable": bool(steps),
        "step_count": len(steps),
        "steps": steps,
        "safety": {
            "raw_messages_included": False,
            "tool_outputs_truncated": True,
            "approval_args_are_previews": True,
        },
    }


def _task_run_learning_candidates(
    run: dict[str, Any],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for finding in findings:
        ftype = str(finding.get("type") or "")
        if ftype == "tool_error":
            tool = ((finding.get("evidence") or {}).get("tool") if isinstance(finding.get("evidence"), dict) else "") or "tool"
            out.append({
                "kind": "failure_pattern",
                "priority": "P0",
                "memory_bucket": "experience",
                "title": f"Tool failure pattern: {tool}",
                "text": f"When `{tool}` fails in task `{run.get('task_id')}`, add preflight validation or fallback planning before retrying.",
            })
        elif ftype == "permission_friction":
            tool = ((finding.get("evidence") or {}).get("tool") if isinstance(finding.get("evidence"), dict) else "") or "tool"
            out.append({
                "kind": "permission_pattern",
                "priority": "P1",
                "memory_bucket": "project_knowledge",
                "title": f"Permission friction: {tool}",
                "text": f"Review whether `{tool}` should be governed by a static allow/deny rule or replaced by a safer workflow.",
            })
        elif ftype == "success_pattern":
            out.append({
                "kind": "success_pattern",
                "priority": "P2",
                "memory_bucket": "experience",
                "title": "Positive tool-use run",
                "text": f"Task `{run.get('task_id')}` completed using {', '.join(run.get('tool_names') or [])}; consider using it as a positive replay example.",
            })
    return out


def _task_run_backlog_candidates(
    run: dict[str, Any],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if any(f.get("type") in {"terminal_status", "tool_error"} for f in findings):
        out.append({
            "priority": "P0",
            "experiment": "Create deterministic replay case",
            "hypothesis": "A replay case from this TaskRun will prevent repeating the same failure mode.",
            "minimal_implementation": "Convert replay.steps into a fixture and assert expected planning/tool behavior.",
            "validation_metric": "Replay passes before prompt/tool changes are accepted.",
        })
    if any(f.get("type") == "permission_friction" for f in findings):
        out.append({
            "priority": "P1",
            "experiment": "Permission policy tuning",
            "hypothesis": "Explicit policy or safer alternative tools reduce repeated approval friction.",
            "minimal_implementation": "Review trust_gateway evidence and add one narrow rule or planning constraint.",
            "validation_metric": "Future runs show fewer rejected approvals for the same tool category.",
        })
    if any(f.get("type") == "success_pattern" for f in findings):
        out.append({
            "priority": "P2",
            "experiment": "Positive replay seed",
            "hypothesis": "Successful TaskRuns can protect useful behavior during self-evolution.",
            "minimal_implementation": "Add this run to a positive replay dataset with its tool sequence and outcome.",
            "validation_metric": "Candidate prompt/tool changes preserve the success pattern.",
        })
    return out


def _approval_replay_fragment(approval: dict[str, Any] | None) -> dict[str, Any] | None:
    if not approval:
        return None
    return {
        "decision": approval.get("decision"),
        "reason": approval.get("reason") or "",
        "risk_level": _approval_risk_level(approval),
        "source": (_trust_gateway_from_approval(approval) or {}).get("source"),
    }


def _trust_gateway_from_approval(row: dict[str, Any]) -> dict[str, Any] | None:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return None
    trust = metadata.get("trust_gateway")
    return trust if isinstance(trust, dict) else None


def _approval_risk_level(row: dict[str, Any]) -> str:
    trust = _trust_gateway_from_approval(row) or {}
    risk = trust.get("risk") if isinstance(trust.get("risk"), dict) else {}
    level = risk.get("level") if isinstance(risk, dict) else None
    return str(level or "").lower()


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _state_str(state: dict[str, Any], key: str) -> str:
    value = state.get(key)
    return value if isinstance(value, str) else ""


def _state_len(state: dict[str, Any], key: str) -> int:
    value = state.get(key)
    return len(value) if isinstance(value, list) else 0


def _recovery_hints(checkpoint: dict[str, Any]) -> dict[str, Any]:
    state = checkpoint.get("state")
    state = state if isinstance(state, dict) else {}
    working_set = state.get("working_set_snapshot")
    working_set = working_set if isinstance(working_set, list) else []
    paths: list[str] = []
    for item in working_set:
        if isinstance(item, str):
            path = item
        elif isinstance(item, dict):
            path = str(item.get("path") or "")
        else:
            path = ""
        if path:
            paths.append(path)
        if len(paths) >= 4:
            break
    return {
        "phase": _state_str(state, "current_phase"),
        "progress": _state_str(state, "progress_summary") or str(checkpoint.get("summary") or ""),
        "messages": _state_len(state, "messages_snapshot"),
        "steps": _state_len(state, "steps_snapshot"),
        "working_set": paths,
    }


def _resume_proposal_from_checkpoint(checkpoint: dict[str, Any]) -> dict[str, Any]:
    from runtime.core.cerebrum.checkpoint_integrity import validate_trace_checkpoint

    hints = _recovery_hints(checkpoint)
    integrity = validate_trace_checkpoint(checkpoint)
    working_set_count = len(hints["working_set"])
    title = (
        f"Resume from {hints['phase']}"
        if hints["phase"]
        else "Resume from latest checkpoint"
    )
    steps = [
        (
            f"Restore the agent into phase {hints['phase']}."
            if hints["phase"]
            else "Restore the agent into the latest recorded phase."
        ),
        f"Continue from iteration {int(checkpoint.get('iteration') or 0) + 1}.",
        (
            f"Rehydrate {working_set_count} working-set file"
            f"{'' if working_set_count == 1 else 's'} and ignore raw message snapshots."
        ),
        (
            f"Use the last progress summary: {hints['progress']}"
            if hints["progress"]
            else "Review the latest progress summary before resuming."
        ),
    ]
    return {
        "checkpoint": {
            "id": checkpoint["id"],
            "task_id": checkpoint["task_id"],
            "thread_id": checkpoint.get("thread_id"),
            "agent_id": checkpoint.get("agent_id"),
            "type": checkpoint["checkpoint_type"],
            "iteration": checkpoint["iteration"],
            "timestamp": checkpoint["ts"],
        },
        "recovery_hints": {
            "phase": hints["phase"] or None,
            "progress": hints["progress"] or None,
            "message_count": hints["messages"],
            "step_count": hints["steps"],
            "working_set": hints["working_set"],
        },
        "resume_plan": {
            "title": title,
            "steps": steps,
        },
        "safety": {
            "raw_state_included": False,
            "raw_message_snapshots_included": False,
            "integrity": integrity.to_dict(),
        },
    }


def _sanitize_resume_intent(intent: Any) -> dict[str, Any]:
    raw = intent if isinstance(intent, dict) else {}
    safety = raw.get("safety") if isinstance(raw.get("safety"), dict) else {}
    return {
        "schema": "octopus.resume_intent.v1",
        "requires_confirmation": bool(raw.get("requires_confirmation", False)),
        "confirmed": bool(raw.get("confirmed", False)),
        "source": _clean_str(raw.get("source")) or "resume_proposal_block",
        "checkpoint_id": int(raw.get("checkpoint_id") or 0),
        "task_id": _clean_str(raw.get("task_id")) or None,
        "checkpoint_type": _clean_str(raw.get("checkpoint_type")) or "unknown",
        "iteration": int(raw.get("iteration") or 0),
        "continue_from_iteration": int(raw.get("continue_from_iteration") or 0),
        "phase": _clean_str(raw.get("phase")) or None,
        "working_set": [
            str(path).strip()
            for path in (raw.get("working_set") if isinstance(raw.get("working_set"), list) else [])
            if isinstance(path, str) and path.strip()
        ][:32],
        "safety": {
            "raw_state_included": bool(safety.get("raw_state_included") is True),
            "raw_message_snapshots_included": bool(
                safety.get("raw_message_snapshots_included") is True,
            ),
        },
    }


__all__ = ["AgentTraceStore", "ApprovalDecision"]

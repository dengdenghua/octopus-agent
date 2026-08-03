"""SQLite storage mixin for the agent trace store."""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .trace_store import AgentTraceStore

from ._trace_store_models import (
    ApprovalDecision,
    TaskRunStatus,
    _clean_str,
    _evaluate_task_run_replay_case,
    _json_dumps,
    _json_loads,
    _now_iso,
    _replay_gate_from_evaluations,
    _task_run_from_rows,
    _task_run_replay_case_from_review,
    _task_run_review_from_loop_checkpoint,
    _task_run_review_from_run,
)
from ._trace_store_recovery import (
    _resume_proposal_from_checkpoint,
    _sanitize_resume_intent,
)
from ._trace_store_schema import _SCHEMA


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


class _TraceStoreStorageMixin:
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
        return [
            _decode_row(row, json_fields=("metadata",), bool_fields=("is_local",)) for row in rows
        ]

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
            items = [
                row for row in items if int(row.get("checkpoint_id") or 0) == int(checkpoint_id)
            ]
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
            # Atomic compare-and-set: only the caller that flips a STILL-pending
            # request wins. The latest_pending lookup above can be stale across
            # connections, so the ``status = 'pending'`` guard (not just id) is
            # what stops two racing confirms from both succeeding (TOCTOU).
            cur = self._conn.execute(
                "UPDATE resume_requests SET status = ?, confirmed_at = ?, intent = ? "
                "WHERE id = ? AND status = ?",
                (
                    "confirmed",
                    confirmed_at,
                    _json_dumps(intent),
                    int(request["id"]),
                    "pending",
                ),
            )
            if cur.rowcount == 0:
                return None  # lost the race — already confirmed/consumed elsewhere
        confirmed_rows = self.resume_requests(
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            status="confirmed",
            limit=1,
        )
        return confirmed_rows[0] if confirmed_rows else None

    def consume_resume_request(self, request_id: int) -> dict[str, Any] | None:
        with self._lock:
            # Atomic single-consumer transition: the ``status != 'consumed'``
            # guard means only ONE connection's UPDATE matches the row, so a
            # racing second consume gets rowcount 0 and returns None instead of
            # re-running the resume (TOCTOU double-consume).
            cur = self._conn.execute(
                "UPDATE resume_requests SET status = ?, consumed_at = ? "
                "WHERE id = ? AND status != ?",
                ("consumed", _now_iso(), int(request_id), "consumed"),
            )
            if cur.rowcount == 0:
                return None  # no such request, or already consumed elsewhere
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
            "SELECT * FROM agent_checkpoints WHERE "  # nosec B608 — WHERE built from ? placeholders; values parameterized
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
            limit=limit if status is None else None,
            offset=offset if status is None else 0,
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
        if status is None:
            return runs
        start = max(0, int(offset or 0))
        end = start + max(0, int(limit or 0))
        return runs[start:end]

    def task_run_review(self, task_id: str) -> dict[str, Any] | None:
        run = self.task_run(task_id)
        if run is None:
            return None
        loop_checkpoint = self.latest_checkpoint(
            task_id=str(run["task_id"]),
            checkpoint_type="loop_run",
        )
        if isinstance(loop_checkpoint, dict):
            return _task_run_review_from_loop_checkpoint(run, loop_checkpoint)
        approvals = self._approvals_for_task(str(run["task_id"]))
        return _task_run_review_from_run(run, approvals)

    def task_run_replay_case(self, task_id: str) -> dict[str, Any] | None:
        review = self.task_run_review(task_id)
        if review is None:
            return None
        return _task_run_replay_case_from_review(review)

    def evaluate_task_run_replay_case(self, task_id: str) -> dict[str, Any] | None:
        replay_case = self.task_run_replay_case(task_id)
        if replay_case is None:
            return None
        return _evaluate_task_run_replay_case(replay_case)

    def task_run_replay_cases(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
        status: TaskRunStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is None:
            rows = self._task_run_ids(
                thread_id=thread_id,
                turn_id=turn_id,
                agent_id=agent_id,
                limit=limit,
                offset=offset,
            )
            task_ids = [str(row["task_id"]) for row in rows]
        else:
            runs = self.task_runs(
                thread_id=thread_id,
                turn_id=turn_id,
                agent_id=agent_id,
                status=status,
                limit=limit,
                offset=offset,
            )
            task_ids = [str(run.get("task_id") or "") for run in runs]
        cases = [
            case for task_id in task_ids if (case := self.task_run_replay_case(task_id)) is not None
        ]
        return {
            "schema": "octopus.task_run_replay_case_corpus.v1",
            "cases": cases,
            "total": len(cases),
            "limit": limit,
            "offset": offset,
        }

    def evaluate_task_run_replay_cases(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
        status: TaskRunStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        corpus = self.task_run_replay_cases(
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        evaluations = [
            _evaluate_task_run_replay_case(case)
            for case in corpus.get("cases", [])
            if isinstance(case, dict)
        ]
        passed = sum(1 for item in evaluations if item.get("passed") is True)
        failed = sum(1 for item in evaluations if item.get("passed") is False)
        return {
            "schema": "octopus.task_run_replay_evaluation_corpus.v1",
            "passed": passed,
            "failed": failed,
            "total": len(evaluations),
            "limit": limit,
            "offset": offset,
            "evaluations": evaluations,
        }

    def replay_gate(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
        status: TaskRunStatus | None = None,
        min_cases: int = 1,
        min_score: float = 1.0,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        corpus = self.evaluate_task_run_replay_cases(
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        evaluations = [item for item in corpus.get("evaluations", []) if isinstance(item, dict)]
        return _replay_gate_from_evaluations(
            evaluations,
            min_cases=min_cases,
            min_score=min_score,
            filters={
                "thread_id": thread_id,
                "turn_id": turn_id,
                "agent_id": agent_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            },
        )

    def replay_gate_for_task_ids(
        self,
        task_ids: list[str],
        *,
        min_cases: int = 1,
        min_score: float = 1.0,
    ) -> dict[str, Any]:
        clean_task_ids = [task_id for task_id in dict.fromkeys(task_ids) if task_id]
        evaluations = [
            evaluation
            for task_id in clean_task_ids
            if (evaluation := self.evaluate_task_run_replay_case(task_id)) is not None
        ]
        return _replay_gate_from_evaluations(
            evaluations,
            min_cases=min_cases,
            min_score=min_score,
            filters={"task_ids": clean_task_ids},
        )

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
                "SELECT "  # nosec B608 — WHERE built from ? placeholders; values parameterized
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
        sql = f"SELECT * FROM {table}{where} ORDER BY id ASC LIMIT ? OFFSET ?"  # nosec B608 — table is internal literal; values parameterized
        params.extend([max(0, int(limit or 0)), max(0, int(offset or 0))])
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def _count_locked(self, table: str, filters: dict[str, str | None] | None = None) -> int:
        where, params = self._where_params(filters or {})
        row = self._conn.execute(f"SELECT COUNT(*) AS c FROM {table}{where}", params).fetchone()  # nosec B608 — table is internal literal; values parameterized
        return int(row["c"]) if row else 0

    def _task_run_ids(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        agent_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
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
                f"SELECT task_id, MAX(ts) AS updated_at FROM {table} "  # nosec B608 — table is internal literal; WHERE uses ? placeholders
                f"WHERE {' AND '.join(clauses)} GROUP BY task_id"
            )
        sql = (
            "SELECT task_id, MAX(updated_at) AS updated_at FROM ("  # nosec B608 — parts built from ? placeholders; values parameterized
            + " UNION ALL ".join(parts)
            + ") GROUP BY task_id ORDER BY updated_at DESC, task_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([max(0, int(limit or 0)), max(0, int(offset or 0))])
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

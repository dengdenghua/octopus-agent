"""Trace-read endpoint handlers for the agent trace router.

Read-only endpoints over the durable agent trace store: stats, events,
task runs, replay cases/evaluations, the replay gate, and the per-task
process timeline.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query

from runtime.memory.runtime_state.process_timeline import build_task_run_process_timeline

from ._agent_trace_router_stores import RouterDeps, _get_experience_ledger, _get_store


def register_trace_endpoints(router, deps: RouterDeps) -> None:
    @router.get("/api/agent-trace/stats")
    def api_agent_trace_stats(
        thread_id: str | None = Query(default=None),
        turn_id: str | None = Query(default=None),
        task_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return _get_store(store=deps.store, db_path=deps.db_path).stats(
            thread_id=thread_id,
            turn_id=turn_id,
            task_id=task_id,
            agent_id=agent_id,
        )

    @router.get("/api/agent-trace/events")
    def api_agent_trace_events(
        thread_id: str | None = Query(default=None),
        turn_id: str | None = Query(default=None),
        task_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        rows = _get_store(store=deps.store, db_path=deps.db_path).events(
            thread_id=thread_id,
            turn_id=turn_id,
            task_id=task_id,
            agent_id=agent_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )
        return {"events": rows, "limit": limit, "offset": offset}

    @router.get("/api/agent-trace/task-runs")
    def api_agent_trace_task_runs(
        thread_id: str | None = Query(default=None),
        turn_id: str | None = Query(default=None),
        task_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        trace = _get_store(store=deps.store, db_path=deps.db_path)
        if task_id:
            run = trace.task_run(task_id)
            rows = [run] if run is not None else []
            if status is not None:
                rows = [row for row in rows if row.get("status") == status]
            return {"task_runs": rows, "limit": limit, "offset": offset}
        rows = trace.task_runs(
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            status=status,  # type: ignore[arg-type]
            limit=limit,
            offset=offset,
        )
        return {"task_runs": rows, "limit": limit, "offset": offset}

    @router.get("/api/agent-trace/task-runs/{task_id}")
    def api_agent_trace_task_run(task_id: str) -> dict[str, Any]:
        run = _get_store(store=deps.store, db_path=deps.db_path).task_run(task_id)
        if run is None:
            raise HTTPException(404, "task run not found")
        return {"task_run": run}

    @router.get("/api/agent-trace/task-runs/{task_id}/review")
    def api_agent_trace_task_run_review(task_id: str) -> dict[str, Any]:
        review = _get_store(store=deps.store, db_path=deps.db_path).task_run_review(task_id)
        if review is None:
            raise HTTPException(404, "task run not found")
        return {"review": review}

    @router.get("/api/agent-trace/task-runs/{task_id}/replay-case")
    def api_agent_trace_task_run_replay_case(task_id: str) -> dict[str, Any]:
        replay_case = _get_store(store=deps.store, db_path=deps.db_path).task_run_replay_case(
            task_id
        )
        if replay_case is None:
            raise HTTPException(404, "task run not found")
        return {"replay_case": replay_case}

    @router.get("/api/agent-trace/task-runs/{task_id}/replay-evaluation")
    def api_agent_trace_task_run_replay_evaluation(task_id: str) -> dict[str, Any]:
        evaluation = _get_store(store=deps.store, db_path=deps.db_path).evaluate_task_run_replay_case(
            task_id,
        )
        if evaluation is None:
            raise HTTPException(404, "task run not found")
        return {"evaluation": evaluation}

    @router.get("/api/agent-trace/replay-cases")
    def api_agent_trace_replay_cases(
        thread_id: str | None = Query(default=None),
        turn_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return _get_store(store=deps.store, db_path=deps.db_path).task_run_replay_cases(
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            status=status,  # type: ignore[arg-type]
            limit=limit,
            offset=offset,
        )

    @router.get("/api/agent-trace/replay-evaluations")
    def api_agent_trace_replay_evaluations(
        thread_id: str | None = Query(default=None),
        turn_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return _get_store(store=deps.store, db_path=deps.db_path).evaluate_task_run_replay_cases(
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            status=status,  # type: ignore[arg-type]
            limit=limit,
            offset=offset,
        )

    @router.get("/api/agent-trace/replay-gate")
    def api_agent_trace_replay_gate(
        thread_id: str | None = Query(default=None),
        turn_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
        min_cases: int = Query(default=1, ge=0, le=1000),
        min_score: float = Query(default=1.0, ge=0.0, le=1.0),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return _get_store(store=deps.store, db_path=deps.db_path).replay_gate(
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            status=status,  # type: ignore[arg-type]
            min_cases=min_cases,
            min_score=min_score,
            limit=limit,
            offset=offset,
        )

    @router.get("/api/agent-trace/task-runs/{task_id}/process-timeline")
    def api_agent_trace_task_run_process_timeline(task_id: str) -> dict[str, Any]:
        trace = _get_store(store=deps.store, db_path=deps.db_path)
        run = trace.task_run(task_id)
        if run is None:
            raise HTTPException(404, "task run not found")
        review = trace.task_run_review(task_id)
        if review is None:
            raise HTTPException(404, "task run not found")
        ledger = _get_experience_ledger(
            experience_ledger=deps.experience_ledger,
            experience_ledger_path=deps.experience_ledger_path,
        )
        timeline = build_task_run_process_timeline(
            task_run=run,
            review=review,
            approvals=trace.approvals(task_id=task_id, limit=10000),
            experience_records=ledger.records_for_task(task_id),
        )
        return {"timeline": timeline}

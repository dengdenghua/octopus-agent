"""Review, experience-ledger, and review-queue endpoint handlers for the agent
trace router.

These endpoints cover committing/queueing task-run reviews, querying the
experience ledger (records, weekly/quality summaries, recall), and managing
the review queue (items, summary, decisions).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query

from ._agent_trace_router_stores import (
    RouterDeps,
    _get_experience_ledger,
    _get_review_queue,
    _get_store,
)


def register_review_endpoints(router, deps: RouterDeps) -> None:
    @router.post("/api/agent-trace/task-runs/{task_id}/review/commit")
    def api_agent_trace_commit_task_run_review(task_id: str) -> dict[str, Any]:
        review = _get_store(store=deps.store, db_path=deps.db_path).task_run_review(task_id)
        if review is None:
            raise HTTPException(404, "task run not found")
        result = _get_experience_ledger(
            experience_ledger=deps.experience_ledger,
            experience_ledger_path=deps.experience_ledger_path,
        ).add_from_task_run_review(review)
        return {"commit": result}

    @router.post("/api/agent-trace/task-runs/{task_id}/review/queue")
    def api_agent_trace_queue_task_run_review(task_id: str) -> dict[str, Any]:
        review = _get_store(store=deps.store, db_path=deps.db_path).task_run_review(task_id)
        if review is None:
            raise HTTPException(404, "task run not found")
        result = _get_review_queue(
            review_queue=deps.review_queue,
            review_queue_path=deps.review_queue_path,
        ).add_from_task_run_review(review)
        return {"queue": result}

    @router.get("/api/agent-trace/experience-ledger")
    def api_agent_trace_experience_ledger(
        status: str | None = Query(default=None),
        bucket: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        priority: str | None = Query(default=None),
        include_contradicted: bool = Query(default=False),
        min_reliability: float = Query(default=0.0, ge=0.0, le=1.0),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return _get_experience_ledger(
            experience_ledger=deps.experience_ledger,
            experience_ledger_path=deps.experience_ledger_path,
        ).records(
            status=status,
            bucket=bucket,
            kind=kind,
            priority=priority,
            include_contradicted=include_contradicted,
            min_reliability=min_reliability,
            limit=limit,
            offset=offset,
        )

    @router.get("/api/agent-trace/experience-ledger/weekly-summary")
    def api_agent_trace_experience_weekly_summary(
        week_start: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return _get_experience_ledger(
            experience_ledger=deps.experience_ledger,
            experience_ledger_path=deps.experience_ledger_path,
        ).weekly_summary(week_start=week_start)

    @router.get("/api/agent-trace/experience-ledger/quality-summary")
    def api_agent_trace_experience_quality_summary(
        limit: int = Query(default=10000, ge=1, le=50000),
    ) -> dict[str, Any]:
        return _get_experience_ledger(
            experience_ledger=deps.experience_ledger,
            experience_ledger_path=deps.experience_ledger_path,
        ).quality_summary(limit=limit)

    @router.get("/api/agent-trace/experience-ledger/recall")
    def api_agent_trace_experience_recall(
        q: str = Query(default=""),
        bucket: str | None = Query(default=None),
        min_reliability: float = Query(default=0.0, ge=0.0, le=1.0),
        limit: int = Query(default=10, ge=1, le=50),
    ) -> dict[str, Any]:
        return _get_experience_ledger(
            experience_ledger=deps.experience_ledger,
            experience_ledger_path=deps.experience_ledger_path,
        ).recall(
            q,
            bucket=bucket,
            min_reliability=min_reliability,
            limit=limit,
        )

    @router.get("/api/agent-trace/review-queue")
    def api_agent_trace_review_queue(
        status: str | None = Query(default=None),
        target_bucket: str | None = Query(default=None),
        priority: str | None = Query(default=None),
        source_task_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return _get_review_queue(
            review_queue=deps.review_queue,
            review_queue_path=deps.review_queue_path,
        ).items(
            status=status,
            target_bucket=target_bucket,
            priority=priority,
            source_task_id=source_task_id,
            limit=limit,
            offset=offset,
        )

    @router.get("/api/agent-trace/review-queue/summary")
    def api_agent_trace_review_queue_summary() -> dict[str, Any]:
        return _get_review_queue(
            review_queue=deps.review_queue,
            review_queue_path=deps.review_queue_path,
        ).summary()

    @router.post("/api/agent-trace/review-queue/{item_id}/decision")
    def api_agent_trace_review_queue_decision(
        item_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return _get_review_queue(
                review_queue=deps.review_queue,
                review_queue_path=deps.review_queue_path,
            ).decide(
                item_id,
                action=str(payload.get("action") or ""),
                reason=str(payload.get("reason") or ""),
                promoted_to=payload.get("promoted_to"),
            )
        except KeyError:
            raise HTTPException(404, "review queue item not found") from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

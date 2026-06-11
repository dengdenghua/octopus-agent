"""Read-only API for the durable agent trace store."""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from runtime.memory.learning.experience_ledger import ExperienceLedger
from runtime.memory.runtime_state.process_timeline import build_task_run_process_timeline
from runtime.memory.learning.promotion_applier import PromotionApplier
from runtime.memory.learning.review_queue import ReviewQueue
from runtime.memory.diagnostics.trace_store import AgentTraceStore
from runtime.safety.evolution.proposal_ledger import ProposalLedger

_STORE_LOCK = threading.Lock()
_STORE_INSTANCE: AgentTraceStore | None = None
_STORE_DB_PATH: Path | None = None
_EXPERIENCE_LOCK = threading.Lock()
_EXPERIENCE_INSTANCE: ExperienceLedger | None = None
_EXPERIENCE_PATH: Path | None = None
_REVIEW_QUEUE_LOCK = threading.Lock()
_REVIEW_QUEUE_INSTANCE: ReviewQueue | None = None
_REVIEW_QUEUE_PATH: Path | None = None


def _default_db_path() -> Path:
    from runtime.platform.process.paths import app_paths

    return app_paths().agent_trace_path


def _default_experience_ledger_path() -> Path:
    from runtime.platform.process.paths import app_paths

    return app_paths().experience_ledger_path


def _default_review_queue_path() -> Path:
    from runtime.platform.process.paths import app_paths

    return app_paths().review_queue_path


def _default_promotion_audit_path() -> Path:
    from runtime.platform.process.paths import app_paths

    return app_paths().promotion_audit_path


def _default_proposal_ledger_path() -> Path:
    from runtime.platform.process.paths import app_paths

    return app_paths().proposal_ledger_path


def _get_store(
    *,
    store: AgentTraceStore | None = None,
    db_path: Path | None = None,
) -> AgentTraceStore:
    if store is not None:
        return store
    target = Path(db_path) if db_path is not None else _default_db_path()
    global _STORE_INSTANCE, _STORE_DB_PATH
    with _STORE_LOCK:
        if _STORE_INSTANCE is None or target != _STORE_DB_PATH:
            if _STORE_INSTANCE is not None:
                with contextlib.suppress(Exception):
                    _STORE_INSTANCE.close()
            _STORE_INSTANCE = AgentTraceStore(target)
            _STORE_DB_PATH = target
        return _STORE_INSTANCE


def _get_experience_ledger(
    *,
    experience_ledger: ExperienceLedger | None = None,
    experience_ledger_path: Path | None = None,
) -> ExperienceLedger:
    if experience_ledger is not None:
        return experience_ledger
    target = (
        Path(experience_ledger_path)
        if experience_ledger_path is not None
        else _default_experience_ledger_path()
    )
    global _EXPERIENCE_INSTANCE, _EXPERIENCE_PATH
    with _EXPERIENCE_LOCK:
        if _EXPERIENCE_INSTANCE is None or target != _EXPERIENCE_PATH:
            _EXPERIENCE_INSTANCE = ExperienceLedger(target)
            _EXPERIENCE_PATH = target
        return _EXPERIENCE_INSTANCE


def _get_review_queue(
    *,
    review_queue: ReviewQueue | None = None,
    review_queue_path: Path | None = None,
) -> ReviewQueue:
    if review_queue is not None:
        return review_queue
    target = (
        Path(review_queue_path)
        if review_queue_path is not None
        else _default_review_queue_path()
    )
    global _REVIEW_QUEUE_INSTANCE, _REVIEW_QUEUE_PATH
    with _REVIEW_QUEUE_LOCK:
        if _REVIEW_QUEUE_INSTANCE is None or target != _REVIEW_QUEUE_PATH:
            _REVIEW_QUEUE_INSTANCE = ReviewQueue(target)
            _REVIEW_QUEUE_PATH = target
        return _REVIEW_QUEUE_INSTANCE


def _get_promotion_applier(
    *,
    experience_ledger: ExperienceLedger | None = None,
    experience_ledger_path: Path | None = None,
    review_queue: ReviewQueue | None = None,
    review_queue_path: Path | None = None,
    promotion_audit_path: Path | None = None,
    proposal_ledger_path: Path | None = None,
) -> PromotionApplier:
    return PromotionApplier(
        review_queue=_get_review_queue(
            review_queue=review_queue,
            review_queue_path=review_queue_path,
        ),
        experience_ledger=_get_experience_ledger(
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
        ),
        proposal_ledger=ProposalLedger(
            proposal_ledger_path or _default_proposal_ledger_path(),
        ),
        audit_path=promotion_audit_path or _default_promotion_audit_path(),
    )


def create_agent_trace_router(
    *,
    store: AgentTraceStore | None = None,
    db_path: Path | None = None,
    experience_ledger: ExperienceLedger | None = None,
    experience_ledger_path: Path | None = None,
    review_queue: ReviewQueue | None = None,
    review_queue_path: Path | None = None,
    promotion_audit_path: Path | None = None,
    proposal_ledger_path: Path | None = None,
) -> APIRouter:
    router = APIRouter(tags=["agent-trace"])

    @router.get("/api/agent-trace/stats")
    def api_agent_trace_stats(
        thread_id: str | None = Query(default=None),
        turn_id: str | None = Query(default=None),
        task_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return _get_store(store=store, db_path=db_path).stats(
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
        rows = _get_store(store=store, db_path=db_path).events(
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
        trace = _get_store(store=store, db_path=db_path)
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
        run = _get_store(store=store, db_path=db_path).task_run(task_id)
        if run is None:
            raise HTTPException(404, "task run not found")
        return {"task_run": run}

    @router.get("/api/agent-trace/task-runs/{task_id}/review")
    def api_agent_trace_task_run_review(task_id: str) -> dict[str, Any]:
        review = _get_store(store=store, db_path=db_path).task_run_review(task_id)
        if review is None:
            raise HTTPException(404, "task run not found")
        return {"review": review}

    @router.get("/api/agent-trace/task-runs/{task_id}/process-timeline")
    def api_agent_trace_task_run_process_timeline(task_id: str) -> dict[str, Any]:
        trace = _get_store(store=store, db_path=db_path)
        run = trace.task_run(task_id)
        if run is None:
            raise HTTPException(404, "task run not found")
        review = trace.task_run_review(task_id)
        if review is None:
            raise HTTPException(404, "task run not found")
        ledger = _get_experience_ledger(
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
        )
        timeline = build_task_run_process_timeline(
            task_run=run,
            review=review,
            approvals=trace.approvals(task_id=task_id, limit=10000),
            experience_records=ledger.records_for_task(task_id),
        )
        return {"timeline": timeline}

    @router.post("/api/agent-trace/task-runs/{task_id}/review/commit")
    def api_agent_trace_commit_task_run_review(task_id: str) -> dict[str, Any]:
        review = _get_store(store=store, db_path=db_path).task_run_review(task_id)
        if review is None:
            raise HTTPException(404, "task run not found")
        result = _get_experience_ledger(
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
        ).add_from_task_run_review(review)
        return {"commit": result}

    @router.post("/api/agent-trace/task-runs/{task_id}/review/queue")
    def api_agent_trace_queue_task_run_review(task_id: str) -> dict[str, Any]:
        review = _get_store(store=store, db_path=db_path).task_run_review(task_id)
        if review is None:
            raise HTTPException(404, "task run not found")
        result = _get_review_queue(
            review_queue=review_queue,
            review_queue_path=review_queue_path,
        ).add_from_task_run_review(review)
        return {"queue": result}

    @router.get("/api/agent-trace/experience-ledger")
    def api_agent_trace_experience_ledger(
        status: str | None = Query(default=None),
        bucket: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        priority: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return _get_experience_ledger(
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
        ).records(
            status=status,
            bucket=bucket,
            kind=kind,
            priority=priority,
            limit=limit,
            offset=offset,
        )

    @router.get("/api/agent-trace/experience-ledger/weekly-summary")
    def api_agent_trace_experience_weekly_summary(
        week_start: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return _get_experience_ledger(
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
        ).weekly_summary(week_start=week_start)

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
            review_queue=review_queue,
            review_queue_path=review_queue_path,
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
            review_queue=review_queue,
            review_queue_path=review_queue_path,
        ).summary()

    @router.post("/api/agent-trace/review-queue/{item_id}/decision")
    def api_agent_trace_review_queue_decision(
        item_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return _get_review_queue(
                review_queue=review_queue,
                review_queue_path=review_queue_path,
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

    @router.post("/api/agent-trace/review-queue/promotions/plan")
    def api_agent_trace_review_queue_promotion_plan(
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = payload or {}
        return _get_promotion_applier(
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
            review_queue=review_queue,
            review_queue_path=review_queue_path,
            promotion_audit_path=promotion_audit_path,
            proposal_ledger_path=proposal_ledger_path,
        ).plan(
            item_id=body.get("item_id"),
            target=body.get("target"),
            limit=int(body.get("limit") or 50),
        )

    @router.post("/api/agent-trace/review-queue/promotions/apply")
    def api_agent_trace_review_queue_promotion_apply(
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = payload or {}
        return _get_promotion_applier(
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
            review_queue=review_queue,
            review_queue_path=review_queue_path,
            promotion_audit_path=promotion_audit_path,
            proposal_ledger_path=proposal_ledger_path,
        ).apply(
            item_id=body.get("item_id"),
            target=body.get("target"),
            limit=int(body.get("limit") or 50),
        )

    @router.get("/api/agent-trace/review-queue/promotions/audit")
    def api_agent_trace_review_queue_promotion_audit(
        item_id: str | None = Query(default=None),
        target: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return _get_promotion_applier(
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
            review_queue=review_queue,
            review_queue_path=review_queue_path,
            promotion_audit_path=promotion_audit_path,
            proposal_ledger_path=proposal_ledger_path,
        ).audit(
            item_id=item_id,
            target=target,
            limit=limit,
            offset=offset,
        )

    @router.get("/api/agent-trace/approvals")
    def api_agent_trace_approvals(
        thread_id: str | None = Query(default=None),
        tool_call_id: str | None = Query(default=None),
        decision: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        rows = _get_store(store=store, db_path=db_path).approvals(
            thread_id=thread_id,
            tool_call_id=tool_call_id,
            decision=decision,
            limit=limit,
            offset=offset,
        )
        return {"approvals": rows, "limit": limit, "offset": offset}

    @router.get("/api/agent-trace/token-usage")
    def api_agent_trace_token_usage(
        task_id: str | None = Query(default=None),
        thread_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        rows = _get_store(store=store, db_path=db_path).token_usage(
            task_id=task_id,
            thread_id=thread_id,
            agent_id=agent_id,
            limit=limit,
            offset=offset,
        )
        return {"usage": rows, "limit": limit, "offset": offset}

    @router.get("/api/agent-trace/checkpoints")
    def api_agent_trace_checkpoints(
        task_id: str | None = Query(default=None),
        thread_id: str | None = Query(default=None),
        turn_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
        checkpoint_type: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        rows = _get_store(store=store, db_path=db_path).checkpoints(
            task_id=task_id,
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            checkpoint_type=checkpoint_type,
            limit=limit,
            offset=offset,
        )
        return {"checkpoints": rows, "limit": limit, "offset": offset}

    @router.get("/api/agent-trace/checkpoints/latest")
    def api_agent_trace_latest_checkpoint(
        task_id: str,
        checkpoint_type: str | None = Query(default=None),
    ) -> dict[str, Any]:
        checkpoint = _get_store(store=store, db_path=db_path).latest_checkpoint(
            task_id=task_id,
            checkpoint_type=checkpoint_type,
        )
        if checkpoint is None:
            raise HTTPException(404, "checkpoint not found")
        return {"checkpoint": checkpoint}

    @router.get("/api/agent-trace/checkpoints/{checkpoint_id}/resume-proposal")
    def api_agent_trace_resume_proposal(checkpoint_id: int) -> dict[str, Any]:
        proposal = _get_store(store=store, db_path=db_path).resume_proposal(checkpoint_id)
        if proposal is None:
            raise HTTPException(404, "checkpoint not found")
        return {"proposal": proposal}

    @router.get("/api/agent-trace/resume-proposals")
    def api_agent_trace_resume_proposals(
        task_id: str | None = Query(default=None),
        thread_id: str | None = Query(default=None),
        turn_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
        checkpoint_type: str | None = Query(default=None),
        limit: int = Query(default=5, ge=1, le=50),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        proposals = _get_store(store=store, db_path=db_path).resume_proposals(
            task_id=task_id,
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            checkpoint_type=checkpoint_type,
            limit=limit,
            offset=offset,
        )
        return {"proposals": proposals, "limit": limit, "offset": offset}

    @router.get("/api/agent-trace/resume-requests")
    def api_agent_trace_resume_requests(
        thread_id: str | None = Query(default=None),
        checkpoint_id: int | None = Query(default=None),
        status: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        rows = _get_store(store=store, db_path=db_path).resume_requests(
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {"requests": rows, "limit": limit, "offset": offset}

    return router


__all__ = ["create_agent_trace_router"]

"""Read-only API for the durable agent trace store."""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from runtime.memory.diagnostics.trace_store import AgentTraceStore
from runtime.memory.learning.experience_ledger import ExperienceLedger
from runtime.memory.learning.promotion_applier import PromotionApplier
from runtime.memory.learning.review_queue import ReviewQueue
from runtime.memory.runtime_state.process_timeline import build_task_run_process_timeline
from runtime.platform.process.paths import app_paths
from runtime.safety.evolution.governance_audit import append_governance_audit_event
from runtime.safety.evolution.policy_review_rules import (
    build_policy_review_rule_drafts,
    install_policy_review_rule_draft,
    verify_policy_review_rule_draft,
)
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


def _source_task_ids_from_promotion_plan(plan: dict[str, Any]) -> list[str]:
    out: list[str] = []
    actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
    for action in actions:
        if not isinstance(action, dict):
            continue
        item = action.get("item") if isinstance(action.get("item"), dict) else {}
        source_task_ids = item.get("source_task_ids")
        if not isinstance(source_task_ids, list):
            continue
        for task_id in source_task_ids:
            text = str(task_id or "").strip()
            if text and text not in out:
                out.append(text)
    return out


def _promotion_plan_has_target(plan: dict[str, Any], target: str) -> bool:
    actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("action") != "apply":
            continue
        if str(action.get("target") or "") == target:
            return True
    return False


def _queue_repeated_trust_denials(
    summary: dict[str, Any],
    *,
    review_queue: ReviewQueue,
    min_occurrences: int,
) -> dict[str, Any]:
    by_tool = summary.get("by_tool") if isinstance(summary.get("by_tool"), dict) else {}
    recent = summary.get("recent") if isinstance(summary.get("recent"), list) else []
    touched: list[dict[str, Any]] = []
    created = 0
    updated = 0
    for tool_name, count in sorted(by_tool.items(), key=lambda item: str(item[0])):
        occurrences = int(count or 0)
        if occurrences < min_occurrences:
            continue
        examples = [
            item for item in recent
            if isinstance(item, dict) and str(item.get("tool_name") or "") == str(tool_name)
        ]
        latest = examples[-1] if examples else {}
        result = review_queue.upsert_item(
            source="trust_denials",
            source_kind="tool_policy_denial",
            candidate_kind="policy_review",
            priority="P1" if occurrences < 5 else "P0",
            target_bucket="policy_review",
            title=f"Review repeated denials for {tool_name}",
            text=(
                f"Tool {tool_name} was denied {occurrences} time(s). "
                f"Latest reason: {latest.get('reason') or 'not recorded'}."
            ),
            metadata={
                "summary_schema": summary.get("schema"),
                "tool_name": tool_name,
                "occurrences": occurrences,
                "latest_denial": latest,
            },
            source_task_ids=[
                str(item.get("task_id") or "")
                for item in examples
                if isinstance(item, dict) and item.get("task_id")
            ],
            thread_ids=[
                str(item.get("thread_id") or "")
                for item in examples
                if isinstance(item, dict) and item.get("thread_id")
            ],
            turn_ids=[
                str(item.get("turn_id") or "")
                for item in examples
                if isinstance(item, dict) and item.get("turn_id")
            ],
            agent_ids=[
                str(item.get("agent_id") or "")
                for item in examples
                if isinstance(item, dict) and item.get("agent_id")
            ],
            tags=["trust_denial", "policy_review", str(tool_name)],
        )
        created += int(result.get("created") or 0)
        updated += int(result.get("updated") or 0)
        touched.extend(result.get("items") or [])
    return {
        "schema": "octopus.trust_denial_review_queue.v1",
        "min_occurrences": min_occurrences,
        "created": created,
        "updated": updated,
        "items": touched,
    }


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
    approval_policy_path: Path | None = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    router = APIRouter(tags=["agent-trace"])

    def _auth(request: Request, *, force: bool = False) -> str | None:
        from .openai_gateway_router import _resolve_actor

        return _resolve_actor(
            request,
            identity_store,
            True if force and identity_store is not None else require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

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

    @router.get("/api/agent-trace/task-runs/{task_id}/replay-case")
    def api_agent_trace_task_run_replay_case(task_id: str) -> dict[str, Any]:
        replay_case = _get_store(store=store, db_path=db_path).task_run_replay_case(task_id)
        if replay_case is None:
            raise HTTPException(404, "task run not found")
        return {"replay_case": replay_case}

    @router.get("/api/agent-trace/task-runs/{task_id}/replay-evaluation")
    def api_agent_trace_task_run_replay_evaluation(task_id: str) -> dict[str, Any]:
        evaluation = _get_store(store=store, db_path=db_path).evaluate_task_run_replay_case(
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
        return _get_store(store=store, db_path=db_path).task_run_replay_cases(
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
        return _get_store(store=store, db_path=db_path).evaluate_task_run_replay_cases(
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
        return _get_store(store=store, db_path=db_path).replay_gate(
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
        include_contradicted: bool = Query(default=False),
        min_reliability: float = Query(default=0.0, ge=0.0, le=1.0),
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
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
        ).weekly_summary(week_start=week_start)

    @router.get("/api/agent-trace/experience-ledger/quality-summary")
    def api_agent_trace_experience_quality_summary(
        limit: int = Query(default=10000, ge=1, le=50000),
    ) -> dict[str, Any]:
        return _get_experience_ledger(
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
        ).quality_summary(limit=limit)

    @router.get("/api/agent-trace/experience-ledger/recall")
    def api_agent_trace_experience_recall(
        q: str = Query(default=""),
        bucket: str | None = Query(default=None),
        min_reliability: float = Query(default=0.0, ge=0.0, le=1.0),
        limit: int = Query(default=10, ge=1, le=50),
    ) -> dict[str, Any]:
        return _get_experience_ledger(
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
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
        plan = _get_promotion_applier(
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
        source_task_ids = _source_task_ids_from_promotion_plan(plan)
        trace = _get_store(store=store, db_path=db_path)
        plan["replay_gate"] = trace.replay_gate_for_task_ids(
            source_task_ids,
            min_cases=int(body.get("min_replay_cases") or 1),
            min_score=float(body.get("min_replay_score") or 1.0),
        )
        return plan

    @router.post("/api/agent-trace/review-queue/promotions/apply")
    def api_agent_trace_review_queue_promotion_apply(
        request: Request,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        actor = _auth(request, force=True)
        body = payload or {}
        applier = _get_promotion_applier(
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
            review_queue=review_queue,
            review_queue_path=review_queue_path,
            promotion_audit_path=promotion_audit_path,
            proposal_ledger_path=proposal_ledger_path,
        )
        limit = int(body.get("limit") or 50)
        plan = applier.plan(
            item_id=body.get("item_id"),
            target=body.get("target"),
            limit=limit,
        )
        source_task_ids = _source_task_ids_from_promotion_plan(plan)
        min_cases = int(body.get("min_replay_cases") or 1)
        min_score = float(body.get("min_replay_score") or 1.0)
        if int(plan.get("applicable") or 0) <= 0:
            min_cases = 0
        replay_gate = _get_store(store=store, db_path=db_path).replay_gate_for_task_ids(
            source_task_ids,
            min_cases=min_cases,
            min_score=min_score,
        )
        if (
            _promotion_plan_has_target(plan, "policy_review")
            and replay_gate.get("passed") is not True
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "policy_review promotion requires replay evidence",
                    "replay_gate": replay_gate,
                    "promotion_plan": plan,
                },
            )
        override = body.get("override_replay_gate") is True
        if replay_gate.get("passed") is not True and not override:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "replay gate did not pass",
                    "replay_gate": replay_gate,
                    "promotion_plan": plan,
                },
            )
        override_reason = str(body.get("override_reason") or "").strip()
        if replay_gate.get("passed") is not True and override and not override_reason:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "override_reason is required when replay gate is blocked",
                    "replay_gate": replay_gate,
                    "promotion_plan": plan,
                },
            )
        # In single-user local dev there may be no identity store; the boundary
        # is explicit here so audit actor is never accepted from request JSON.
        override_actor = actor or "local_operator"
        result = applier.apply(
            item_id=body.get("item_id"),
            target=body.get("target"),
            limit=limit,
            decision_context={
                "schema": "octopus.promotion_decision_context.v1",
                "replay_gate": replay_gate,
                "override_replay_gate": override,
                "override_reason": override_reason if override else "",
                "override_actor": override_actor if override else "",
                "source": "agent_trace_router",
            },
        )
        result["replay_gate"] = replay_gate
        result["override_replay_gate"] = override
        return result

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

    @router.get("/api/agent-trace/review-queue/promotions/audit/summary")
    def api_agent_trace_review_queue_promotion_audit_summary() -> dict[str, Any]:
        return _get_promotion_applier(
            experience_ledger=experience_ledger,
            experience_ledger_path=experience_ledger_path,
            review_queue=review_queue,
            review_queue_path=review_queue_path,
            promotion_audit_path=promotion_audit_path,
            proposal_ledger_path=proposal_ledger_path,
        ).audit_summary()

    @router.get("/api/agent-trace/policy-review/rule-drafts")
    def api_agent_trace_policy_review_rule_drafts(
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        report = build_policy_review_rule_drafts(
            ledger_path=proposal_ledger_path or _default_proposal_ledger_path(),
            limit=limit,
        )
        report["verified"] = sum(
            1
            for draft in report.get("drafts") or []
            if verify_policy_review_rule_draft(draft).get("ok") is True
        )
        return report

    @router.post("/api/agent-trace/policy-review/rule-drafts/install")
    def api_agent_trace_policy_review_rule_draft_install(
        request: Request,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        actor = _auth(request, force=True) or "local_operator"
        body = payload or {}
        draft_id = str(body.get("draft_id") or "").strip()
        if not draft_id:
            raise HTTPException(400, "draft_id is required")
        report = build_policy_review_rule_drafts(
            ledger_path=proposal_ledger_path or _default_proposal_ledger_path(),
            limit=int(body.get("limit") or 100),
        )
        draft = next(
            (
                item for item in report.get("drafts") or []
                if isinstance(item, dict) and str(item.get("draft_id") or "") == draft_id
            ),
            None,
        )
        if draft is None:
            raise HTTPException(404, "policy review rule draft not found")
        try:
            result = install_policy_review_rule_draft(
                draft,
                policy_path=approval_policy_path or app_paths().permissions_path,
                confirm_install=body.get("confirm_install") is True,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        append_governance_audit_event(
            event_type="policy_review_rule_install",
            target="approval_policy",
            status="installed",
            artifact=result,
            decision_context={
                "schema": "octopus.policy_review_rule_install_context.v1",
                "actor": actor,
                "draft_id": draft_id,
                "source": "agent_trace_router",
            },
            audit_path=promotion_audit_path or _default_promotion_audit_path(),
        )
        return result

    @router.get("/api/agent-trace/review-queue/promotions/audit/export")
    def api_agent_trace_review_queue_promotion_audit_export(
        request: Request,
    ) -> dict[str, Any]:
        _auth(request, force=True)
        from runtime.safety.evolution.governance_audit import (
            export_governance_audit_bundle,
        )

        return export_governance_audit_bundle(
            audit_path=promotion_audit_path or _default_promotion_audit_path(),
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

    @router.get("/api/agent-trace/trust-denials/summary")
    def api_agent_trace_trust_denials_summary(
        request: Request,
        thread_id: str | None = Query(default=None),
        turn_id: str | None = Query(default=None),
        task_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
        limit: int = Query(default=1000, ge=1, le=5000),
        queue_repeated: bool = Query(default=False),
        min_occurrences: int = Query(default=2, ge=1, le=100),
    ) -> dict[str, Any]:
        from runtime.safety.audit.trust_gateway import summarize_trust_denials

        rows = _get_store(store=store, db_path=db_path).approvals(
            thread_id=thread_id,
            turn_id=turn_id,
            task_id=task_id,
            agent_id=agent_id,
            limit=limit,
        )
        summary = summarize_trust_denials(rows)
        if queue_repeated:
            # Injecting review-queue rows is a state mutation; gate it behind
            # auth like the sibling write/install endpoints (the read-only
            # summary path stays open like other GETs).
            _auth(request, force=True)
            summary["queue"] = _queue_repeated_trust_denials(
                summary,
                review_queue=_get_review_queue(
                    review_queue=review_queue,
                    review_queue_path=review_queue_path,
                ),
                min_occurrences=min_occurrences,
            )
        return summary

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

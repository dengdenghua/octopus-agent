from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

try:
    from fastapi import APIRouter, HTTPException, Query, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Query = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]

from runtime.sensing._fastapi_guard import require_fastapi
from runtime.platform.process.paths import app_paths
from runtime.platform.process.task_supervisor import (
    LostTaskLease,
    TaskLeaseConflict,
    TaskSupervisor,
    TaskSupervisorStore,
    build_task_runs_overview,
    task_lease_health,
)


class TaskApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approved: bool
    reason: str | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_reason(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None


class TaskTakeoverRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: str | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_reason(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None


def _default_supervisor() -> TaskSupervisor:
    return TaskSupervisor(TaskSupervisorStore(app_paths().task_runs_path))


def create_task_runs_router(
    *,
    supervisor: TaskSupervisor | None = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    require_fastapi(__name__)

    router = APIRouter(tags=["task-runs"])

    def _store() -> TaskSupervisorStore:
        return (supervisor or _default_supervisor()).store

    def _auth(request: Request) -> str | None:
        if require_auth and identity_store is None:
            raise HTTPException(401, "auth required")
        from runtime.sensing.gateway.openai_gateway_router import _resolve_actor

        return _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    def _supervisor() -> TaskSupervisor:
        return supervisor or _default_supervisor()

    @router.get("/api/task-runs")
    def api_task_runs(
        request: Request,
        status: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        owner_id: str | None = Query(default=None),
        thread_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        actor = _auth(request)
        effective_owner = actor if require_auth else owner_id
        page = _store().list_page(
            status=status,
            kind=kind,
            owner_id=effective_owner,
            thread_id=thread_id,
            limit=limit,
            offset=offset,
        )
        tasks = page["items"]
        return {
            "schema": "octopus.task_runs.v1",
            "tasks": [task.model_dump(mode="json") for task in tasks],
            "items": [_task_run_payload(task) for task in tasks],
            "total": page["total"],
            "count": len(tasks),
            "limit": page["limit"],
            "offset": page["offset"],
            "filters": {
                "status": status,
                "kind": kind,
                "owner_id": effective_owner,
                "thread_id": thread_id,
            },
        }

    @router.get("/api/task-runs/overview")
    def api_task_runs_overview(
        request: Request,
        owner_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        actor = _auth(request)
        effective_owner = actor if require_auth else owner_id
        if effective_owner:
            tasks = _store().list(owner_id=effective_owner, limit=1_000_000)
            overview = build_task_runs_overview(tasks)
        else:
            overview = _store().overview()
        return {
            **overview,
            "filters": {
                "owner_id": effective_owner,
            },
        }

    @router.get("/api/task-runs/recovery-queue")
    def api_task_runs_recovery_queue(
        request: Request,
        status: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        owner_id: str | None = Query(default=None),
        thread_id: str | None = Query(default=None),
        include_monitor: bool = Query(default=False),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        actor = _auth(request)
        effective_owner = actor if require_auth else owner_id
        queue = _store().recovery_queue(
            status=status,
            kind=kind,
            owner_id=effective_owner,
            thread_id=thread_id,
            include_monitor=include_monitor,
            limit=limit,
        )
        return {
            **queue,
            "filters": {
                "status": status,
                "kind": kind,
                "owner_id": effective_owner,
                "thread_id": thread_id,
                "include_monitor": include_monitor,
            },
        }

    @router.get("/api/task-runs/{task_id}")
    def api_task_run(task_id: str, request: Request) -> dict[str, Any]:
        actor = _auth(request)
        task = _store().get(task_id)
        if task is None:
            raise HTTPException(404, "task run not found")
        if require_auth and task.owner_id not in {None, "", actor}:
            raise HTTPException(404, "task run not found")
        return {
            "schema": "octopus.task_run.v1",
            "task_run": task.model_dump(mode="json"),
            "lease_health": task_lease_health(task),
        }

    @router.post("/api/task-runs/{task_id}/approval-decision")
    def api_task_run_approval_decision(
        task_id: str,
        body: TaskApprovalDecisionRequest,
        request: Request,
    ) -> dict[str, Any]:
        actor = _auth(request)
        task = _store().get(task_id)
        if task is None:
            raise HTTPException(404, "task run not found")
        if require_auth and task.owner_id not in {None, "", actor}:
            raise HTTPException(404, "task run not found")
        try:
            updated = _supervisor().record_approval_decision(
                task_id,
                approved=body.approved,
                decided_by=actor,
                reason=body.reason or "",
            )
        except LostTaskLease as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, "task run not found") from exc
        return {
            "schema": "octopus.task_run_approval_decision.v1",
            "task_run": updated.model_dump(mode="json"),
            "lease_health": task_lease_health(updated),
        }

    @router.post("/api/task-runs/{task_id}/takeover")
    def api_task_run_takeover(
        task_id: str,
        request: Request,
        body: TaskTakeoverRequest | None = None,
    ) -> dict[str, Any]:
        actor = _auth(request)
        task = _store().get(task_id)
        if task is None:
            raise HTTPException(404, "task run not found")
        if require_auth and task.owner_id not in {None, "", actor}:
            raise HTTPException(404, "task run not found")
        try:
            updated = _supervisor().takeover_task(
                task_id,
                by=actor,
                reason=(body.reason if body is not None else None) or "",
            )
        except TaskLeaseConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, "task run not found") from exc
        return {
            "schema": "octopus.task_run_takeover.v1",
            "task_run": updated.model_dump(mode="json"),
            "lease_health": task_lease_health(updated),
        }

    return router


def _task_run_payload(task: Any) -> dict[str, Any]:
    return {
        "task_run": task.model_dump(mode="json"),
        "lease_health": task_lease_health(task),
    }


__all__ = [
    "TaskApprovalDecisionRequest",
    "TaskTakeoverRequest",
    "create_task_runs_router",
]

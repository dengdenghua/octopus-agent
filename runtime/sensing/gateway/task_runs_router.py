from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Query, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Query = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]

from runtime.platform.process.paths import app_paths
from runtime.platform.process.task_supervisor import TaskSupervisor, TaskSupervisorStore


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
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

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
        tasks = _store().list(
            status=status,
            kind=kind,
            owner_id=effective_owner,
            thread_id=thread_id,
            limit=limit,
            offset=offset,
        )
        return {
            "schema": "octopus.task_runs.v1",
            "tasks": [task.model_dump(mode="json") for task in tasks],
            "total": len(tasks),
            "limit": limit,
            "offset": offset,
            "filters": {
                "status": status,
                "kind": kind,
                "owner_id": effective_owner,
                "thread_id": thread_id,
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
        }

    return router


__all__ = ["create_task_runs_router"]

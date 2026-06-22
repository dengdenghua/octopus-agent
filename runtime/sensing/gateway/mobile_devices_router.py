"""Mobile-device router · ``/api/mobile/*``.

Bridges phones running octopus-mobile into the team as remote members:

  * ``POST /api/mobile/register`` — phone announces itself + heartbeats.
  * ``GET  /api/mobile/devices``  — connected phones (for roster/pickers).
  * ``GET  /api/mobile/next``     — phone polls for its next device task.
  * ``POST /api/mobile/result``   — phone reports a task result.
  * ``POST /api/mobile/dispatch`` — queue a task to a phone (used by tests /
    ad-hoc; the team-task dispatcher calls the registry directly).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    device_id: str
    name: str = ""
    model: str = ""


class DispatchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    device_id: str
    task_id: str
    goal: str = ""


class ResultRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    device_id: str
    task_id: str
    ok: bool = False
    output: str = ""
    error: str | None = None


class _Empty(BaseModel):
    items: list[Any] = Field(default_factory=list)


def create_mobile_devices_router() -> Any:
    """Build + return the router. ``app.include_router(create_mobile_devices_router())``."""
    try:
        from fastapi import APIRouter
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("fastapi not installed") from exc

    from runtime.execution.agents.mobile_device import get_mobile_registry

    router = APIRouter(tags=["mobile"])

    @router.post("/api/mobile/register")
    def register(body: RegisterRequest) -> dict[str, Any]:
        reg = get_mobile_registry()
        entry = reg.register(body.device_id, body.name, body.model)
        return {"ok": True, "device": entry}

    @router.get("/api/mobile/devices")
    def list_devices() -> dict[str, Any]:
        return {"devices": get_mobile_registry().list_devices()}

    @router.get("/api/mobile/next")
    def next_task(device_id: str) -> dict[str, Any]:
        task = get_mobile_registry().next_task(device_id)
        return {"task": task}

    @router.post("/api/mobile/result")
    def post_result(body: ResultRequest) -> dict[str, Any]:
        get_mobile_registry().post_result(
            body.device_id, body.task_id, ok=body.ok, output=body.output, error=body.error
        )
        return {"ok": True}

    @router.post("/api/mobile/dispatch")
    def dispatch(body: DispatchRequest) -> dict[str, Any]:
        ok = get_mobile_registry().dispatch(body.device_id, body.task_id, body.goal)
        if not ok:
            return {"ok": False, "error": f"unknown device: {body.device_id}"}
        return {"ok": True}

    return router

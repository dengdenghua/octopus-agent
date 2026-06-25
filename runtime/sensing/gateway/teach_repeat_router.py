"""Teach & Repeat API.

This router backs the chat-header REC affordance. Recording is intentionally
opt-in: nothing starts until the user confirms in the UI and calls
``/record/start``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


@dataclass
class _Recording:
    thread_id: str
    name: str
    description: str
    started_at: str
    step_count: int = 0


_RECORDINGS: dict[str, _Recording] = {}
_TEMPLATES: dict[str, dict[str, Any]] = {}


class StartRecordingRequest(BaseModel):
    thread_id: str
    name: str
    description: str | None = None


class StopRecordingRequest(BaseModel):
    thread_id: str
    use_llm: bool = False
    model_name: str | None = None


class TemplateUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_teach_repeat_router(
    *,
    journal: Any = None,
    registry: Any = None,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/teach-repeat/record/start")
    def start_recording(body: StartRecordingRequest) -> dict[str, Any]:
        thread_id = body.thread_id.strip()
        if not thread_id:
            raise HTTPException(400, "thread_id is required")
        name = body.name.strip() or "对话回放学习"
        rec = _Recording(
            thread_id=thread_id,
            name=name,
            description=(body.description or "").strip(),
            started_at=_now(),
        )
        _RECORDINGS[thread_id] = rec
        return {"recording": True, "thread_id": thread_id, "name": name}

    @router.post("/api/teach-repeat/record/stop")
    def stop_recording(body: StopRecordingRequest) -> dict[str, Any]:
        thread_id = body.thread_id.strip()
        rec = _RECORDINGS.pop(thread_id, None)
        if rec is None:
            raise HTTPException(404, "No active recording for this thread")

        # The real "recording" is the journal Trajectory react_loop already
        # wrote for this conversation. Forge a reusable skill from it via the
        # active single-demo forge (no min_hits wait). The immune gate still
        # quarantines macros over dangerous primitives for human approval.
        if journal is None or registry is None:
            return {
                "name": rec.name,
                "status": "no_runtime",
                "forged": [],
                "step_count": 0,
            }

        try:
            from runtime.memory.journal.journal import TrajectoryEvent
            from runtime.safety.recovery.skill_forge import SkillForge
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, f"forge unavailable: {exc}") from exc

        trajs = [
            e.trajectory
            for e in journal.read_by_type("trajectory")
            if isinstance(e, TrajectoryEvent)
            and getattr(e.trajectory, "thread_id", None) == thread_id
            and e.trajectory.outcome.success
        ]
        if not trajs:
            return {
                "name": rec.name,
                "status": "no_successful_trajectory",
                "forged": [],
                "thread_id": thread_id,
                "step_count": 0,
            }

        result = SkillForge(journal=journal, registry=registry).forge_selected(trajs)
        status = (
            "promoted"
            if result.promoted
            else "quarantined"
            if result.quarantined
            else "shadow_failed"
            if result.shadow_failed
            else "no_candidate"
        )
        return {
            "name": rec.name,
            "status": status,
            "forged": list(result.promoted),
            "quarantined": list(result.quarantined),
            "candidates_total": result.candidates_total,
            "thread_id": thread_id,
            "step_count": sum(t.step_count for t in trajs),
        }

    @router.get("/api/teach-repeat/record/status")
    def recording_status(thread_id: str) -> dict[str, Any]:
        rec = _RECORDINGS.get(thread_id)
        if rec is None:
            return {"recording": False, "step_count": 0, "name": ""}
        return {
            "recording": True,
            "step_count": rec.step_count,
            "name": rec.name,
        }

    @router.get("/api/teach-repeat/templates")
    def list_templates(skip: int = 0, limit: int = 100, search: str = "", tag: str = "") -> dict[str, Any]:
        items = list(_TEMPLATES.values())
        if search:
            needle = search.lower()
            items = [
                item
                for item in items
                if needle in str(item.get("name", "")).lower()
                or needle in str(item.get("description", "")).lower()
            ]
        if tag:
            items = [item for item in items if tag in (item.get("tags") or [])]
        total = len(items)
        page = items[skip : skip + limit]
        return {
            "templates": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "description": item["description"],
                    "step_count": len(item.get("steps") or []),
                    "param_count": len(item.get("params") or []),
                    "tags": item.get("tags") or [],
                    "use_count": item.get("use_count") or 0,
                    "last_used_at": item.get("last_used_at"),
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("updated_at"),
                    "params": item.get("params") or [],
                }
                for item in page
            ],
            "total": total,
        }

    @router.get("/api/teach-repeat/templates/{template_id}")
    def get_template(template_id: str) -> dict[str, Any]:
        template = _TEMPLATES.get(template_id)
        if template is None:
            raise HTTPException(404, "Template not found")
        return template

    @router.put("/api/teach-repeat/templates/{template_id}")
    def update_template(template_id: str, body: TemplateUpdateRequest) -> dict[str, Any]:
        template = _TEMPLATES.get(template_id)
        if template is None:
            raise HTTPException(404, "Template not found")
        if body.name is not None:
            template["name"] = body.name
        if body.description is not None:
            template["description"] = body.description
        if body.tags is not None:
            template["tags"] = body.tags
        template["updated_at"] = _now()
        return template

    @router.delete("/api/teach-repeat/templates/{template_id}")
    def delete_template(template_id: str) -> dict[str, Any]:
        _TEMPLATES.pop(template_id, None)
        return {"ok": True}

    @router.post("/api/teach-repeat/templates/{template_id}/replay")
    def replay_template(template_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if template_id not in _TEMPLATES:
            raise HTTPException(404, "Template not found")
        _TEMPLATES[template_id]["use_count"] = int(_TEMPLATES[template_id].get("use_count") or 0) + 1
        _TEMPLATES[template_id]["last_used_at"] = _now()
        return {
            "workflow_id": template_id,
            "status": "completed",
            "step_results": [],
            "params_used": (body or {}).get("params") or {},
            "total_duration_ms": 0,
            "error": None,
            "started_at": _now(),
            "completed_at": _now(),
        }

    @router.post("/api/teach-repeat/templates/{template_id}/replay/adaptive")
    def replay_template_adaptive(template_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return replay_template(template_id, body)

    @router.post("/api/teach-repeat/templates/{template_id}/duplicate")
    def duplicate_template(template_id: str) -> dict[str, Any]:
        template = _TEMPLATES.get(template_id)
        if template is None:
            raise HTTPException(404, "Template not found")
        new_id = f"rec_{uuid4().hex[:12]}"
        clone = {**template, "id": new_id, "name": f"{template['name']} copy", "created_at": _now(), "updated_at": _now()}
        _TEMPLATES[new_id] = clone
        return clone

    return router


__all__ = ["create_teach_repeat_router"]

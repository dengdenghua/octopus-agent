"""Project OS API — drive milestone-driven projects over HTTP.

Reads (project state + report) are public; mutations (plan / tick / run) are
auth-gated, mirroring the cowork router. The engine uses LLM hooks when a model
router is available, else deterministic stubs so the endpoints always work.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from runtime.projectos.engine import (
    ProjectEngine,
    stub_decompose_tasks,
    stub_generate_milestones,
)
from runtime.projectos.store import ProjectStore


class PlanBody(BaseModel):
    name: str = Field(min_length=1)
    goal: str = Field(min_length=1)


class RunBody(BaseModel):
    max_ticks: int = 50


def create_projects_router(
    *,
    store: ProjectStore | None = None,
    model_router: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    """Create the ``/api/projects/*`` router."""
    project_store = store or ProjectStore()

    def _engine() -> ProjectEngine:
        if model_router is not None:
            from runtime.projectos.llm_hooks import create_llm_hooks

            return ProjectEngine(project_store, **create_llm_hooks(model_router))
        return ProjectEngine(
            project_store,
            generate_milestones=stub_generate_milestones,
            decompose_tasks=stub_decompose_tasks,
        )

    def _auth_dep(request: Request) -> None:
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request, identity_store, require_auth,
            jwt_secret=jwt_secret, jwt_issuer=jwt_issuer, jwt_audience=jwt_audience,
        )

    router = APIRouter(tags=["projectos"])

    def _full_state(project_id: str) -> dict[str, Any]:
        project = project_store.get_project(project_id)
        if project is None:
            raise HTTPException(404, "project not found")
        mss = project_store.milestones_for(project_id)
        return {
            "project": project.to_dict(),
            "milestones": [m.to_dict() for m in mss],
            "tasks": {
                m.id: [t.to_dict() for t in project_store.tasks_for_milestone(m.id)]
                for m in mss
            },
        }

    @router.get("/api/projects")
    def list_projects() -> dict[str, Any]:
        return {"projects": [p.to_dict() for p in project_store.list_projects()]}

    @router.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        return _full_state(project_id)

    @router.get("/api/projects/{project_id}/report")
    def report(project_id: str) -> dict[str, Any]:
        """A milestone report: each milestone + its tasks' status/output."""
        project = project_store.get_project(project_id)
        if project is None:
            raise HTTPException(404, "project not found")
        out = []
        for m in project_store.milestones_for(project_id):
            out.append({
                "id": m.id, "name": m.name, "status": m.status,
                "success_criteria": m.success_criteria,
                "tasks": [
                    {"id": t.id, "role": t.assigned_role, "type": t.type,
                     "status": t.status, "output": t.output}
                    for t in project_store.tasks_for_milestone(m.id)
                ],
            })
        return {"project": project.name, "status": project.status, "milestones": out}

    @router.post("/api/projects", dependencies=[Depends(_auth_dep)])
    def plan(body: PlanBody) -> dict[str, Any]:
        """Turn a one-line goal into a project with generated milestones."""
        project = _engine().plan(body.name, body.goal)
        return {"ok": True, **_full_state(project.id)}

    @router.post("/api/projects/{project_id}/tick", dependencies=[Depends(_auth_dep)])
    def tick(project_id: str) -> dict[str, Any]:
        """Advance the project one loop iteration."""
        if project_store.get_project(project_id) is None:
            raise HTTPException(404, "project not found")
        return _engine().tick(project_id)

    @router.post("/api/projects/{project_id}/run", dependencies=[Depends(_auth_dep)])
    def run(project_id: str, body: RunBody) -> dict[str, Any]:
        """Drive the loop until the project is done/blocked or max_ticks."""
        if project_store.get_project(project_id) is None:
            raise HTTPException(404, "project not found")
        return _engine().run(project_id, max_ticks=body.max_ticks)

    return router

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
from runtime.projectos.cowork_bridge import full_project_state, run_project_from_group
from runtime.projectos.store import ProjectStore


class PlanBody(BaseModel):
    name: str = Field(min_length=1)
    goal: str = Field(min_length=1)


class RunBody(BaseModel):
    max_ticks: int = 50


class RecoverBody(BaseModel):
    task_ids: list[str] = Field(default_factory=list)
    reset_attempts: bool = True
    clear_outputs: bool = True
    run: bool = False
    max_ticks: int = 50


class TaskInterventionBody(BaseModel):
    action: str = Field(min_length=1)
    assigned_agent: str | None = None
    assigned_role: str | None = None
    output: Any = None
    reason: str = ""
    reset_attempts: bool = True
    cascade: bool = True
    run: bool = False
    max_ticks: int = 50


class FromGroupBody(BaseModel):
    name: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    run: bool = True
    max_ticks: int = 50


def create_projects_router(
    *,
    store: ProjectStore | None = None,
    group_store: Any = None,
    model_router: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    """Create the ``/api/projects/*`` router."""
    project_store = store or ProjectStore()

    def _group_store():
        if group_store is not None:
            return group_store
        from runtime.memory.cowork.group_store import GroupStore

        return GroupStore()

    def _base_hooks() -> dict[str, Any]:
        """Intelligence hooks: LLM when a model router is available, else stubs."""
        if model_router is not None:
            from runtime.projectos.llm_hooks import create_llm_hooks

            return create_llm_hooks(model_router)
        return {
            "generate_milestones": stub_generate_milestones,
            "decompose_tasks": stub_decompose_tasks,
        }

    def _engine() -> ProjectEngine:
        return ProjectEngine(project_store, **_base_hooks())

    def _auth_dep(request: Request) -> None:
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request, identity_store, require_auth,
            jwt_secret=jwt_secret, jwt_issuer=jwt_issuer, jwt_audience=jwt_audience,
        )

    router = APIRouter(tags=["projectos"])

    def _full_state(project_id: str) -> dict[str, Any]:
        state = full_project_state(project_store, project_id)
        if state is None:
            raise HTTPException(404, "project not found")
        return state

    @router.get("/api/projects")
    def list_projects() -> dict[str, Any]:
        return {"projects": [p.to_dict() for p in project_store.list_projects()]}

    @router.get("/api/projects/by-thread/{thread_id}")
    def get_project_by_thread(thread_id: str) -> dict[str, Any]:
        project = project_store.project_for_thread(thread_id)
        if project is None:
            raise HTTPException(404, "project not found for thread")
        return _full_state(project.id)

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

    @router.get("/api/projects/{project_id}/events")
    def events(project_id: str, limit: int = 100) -> dict[str, Any]:
        """Project audit trail: recoveries, interventions, and future operator actions."""
        if project_store.get_project(project_id) is None:
            raise HTTPException(404, "project not found")
        return {
            "project_id": project_id,
            "events": project_store.events_for_project(project_id, limit=limit),
        }

    @router.post("/api/projects", dependencies=[Depends(_auth_dep)])
    def plan(body: PlanBody) -> dict[str, Any]:
        """Turn a one-line goal into a project with generated milestones."""
        project = _engine().plan(body.name, body.goal)
        return {"ok": True, **_full_state(project.id)}

    @router.post("/api/projects/from-group/{thread_id}", dependencies=[Depends(_auth_dep)])
    def from_group(thread_id: str, body: FromGroupBody) -> dict[str, Any]:
        """Turn a custom cowork group into a project team: plan milestones and (by
        default) run them, routing each task to the group's ACTUAL members by
        capability — not the fixed 4 roles. This is "assemble a group → turn on
        project mode"."""
        try:
            return run_project_from_group(
                project_store,
                _group_store(),
                thread_id,
                name=body.name,
                goal=body.goal,
                hooks=_base_hooks(),
                run=body.run,
                max_ticks=body.max_ticks,
            )
        except ValueError as exc:
            raise HTTPException(400, "group has no participant agents to staff the project")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"project run failed: {exc}") from exc

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

    @router.post("/api/projects/{project_id}/recover", dependencies=[Depends(_auth_dep)])
    def recover(project_id: str, body: RecoverBody) -> dict[str, Any]:
        """Reopen blocked project work after an operator fixes the cause."""
        if project_store.get_project(project_id) is None:
            raise HTTPException(404, "project not found")
        engine = _engine()
        recovered = engine.recover(
            project_id,
            task_ids=body.task_ids,
            reset_attempts=body.reset_attempts,
            clear_outputs=body.clear_outputs,
        )
        if body.run:
            return {
                "ok": True,
                "recover": recovered,
                "run": engine.run(project_id, max_ticks=body.max_ticks),
                **_full_state(project_id),
            }
        return {"ok": True, "recover": recovered, **_full_state(project_id)}

    @router.post(
        "/api/projects/{project_id}/tasks/{task_id}/intervene",
        dependencies=[Depends(_auth_dep)],
    )
    def intervene_task(project_id: str, task_id: str, body: TaskInterventionBody) -> dict[str, Any]:
        """Manually reassign, reset, complete, or skip a task."""
        if project_store.get_project(project_id) is None:
            raise HTTPException(404, "project not found")
        engine = _engine()
        intervention = engine.intervene_task(
            project_id,
            task_id,
            action=body.action,
            assigned_agent=body.assigned_agent,
            assigned_role=body.assigned_role,
            output=body.output,
            reason=body.reason,
            reset_attempts=body.reset_attempts,
            cascade=body.cascade,
        )
        if any(str(event).startswith("task_not_found:") for event in intervention["events"]):
            raise HTTPException(404, "task not found")
        if any(str(event).startswith("unknown_task_action:") for event in intervention["events"]):
            raise HTTPException(400, "unknown task intervention action")
        if body.run:
            return {
                "ok": True,
                "intervention": intervention,
                "run": engine.run(project_id, max_ticks=body.max_ticks),
                **_full_state(project_id),
            }
        return {"ok": True, "intervention": intervention, **_full_state(project_id)}

    return router

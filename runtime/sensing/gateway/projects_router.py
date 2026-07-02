"""Project OS API — drive milestone-driven projects over HTTP.

Reads (project state + report) are public; mutations (plan / tick / run) are
auth-gated, mirroring the cowork router. The engine uses LLM hooks when a model
router is available, else deterministic stubs so the endpoints always work.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from runtime.projectos.cowork_bridge import full_project_state, run_project_from_group
from runtime.projectos.engine import (
    DEFAULT_RUN_MAX_TICKS,
    HARD_MAX_RUN_TICKS,
    ProjectEngine,
    stub_decompose_tasks,
    stub_generate_milestones,
)
from runtime.projectos.store import ProjectStore
from runtime.projectos.timeline import project_process_timeline


class PlanBody(BaseModel):
    name: str = Field(min_length=1)
    goal: str = Field(min_length=1)


class RunBody(BaseModel):
    max_ticks: int = Field(default=DEFAULT_RUN_MAX_TICKS, ge=1, le=HARD_MAX_RUN_TICKS)


class RecoverBody(BaseModel):
    task_ids: list[str] = Field(default_factory=list)
    reset_attempts: bool = True
    clear_outputs: bool = True
    run: bool = False
    max_ticks: int = Field(default=DEFAULT_RUN_MAX_TICKS, ge=1, le=HARD_MAX_RUN_TICKS)


class TaskInterventionBody(BaseModel):
    action: str = Field(min_length=1)
    assigned_agent: str | None = None
    assigned_role: str | None = None
    output: Any = None
    reason: str = ""
    reset_attempts: bool = True
    cascade: bool = True
    run: bool = False
    max_ticks: int = Field(default=DEFAULT_RUN_MAX_TICKS, ge=1, le=HARD_MAX_RUN_TICKS)


class FromGroupBody(BaseModel):
    name: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    run: bool = True
    max_ticks: int = Field(default=DEFAULT_RUN_MAX_TICKS, ge=1, le=HARD_MAX_RUN_TICKS)


def create_projects_router(
    *,
    store: ProjectStore | None = None,
    group_store: Any = None,
    collaboration_store: Any = None,
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
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    router = APIRouter(tags=["projectos"])

    def _bad_request(exc: ValueError) -> HTTPException:
        return HTTPException(400, str(exc))

    def _project_or_404(project_id: str):
        try:
            project = project_store.get_project(project_id)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        if project is None:
            raise HTTPException(404, "project not found")
        return project

    def _full_state(project_id: str) -> dict[str, Any]:
        try:
            state = full_project_state(project_store, project_id)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        if state is None:
            raise HTTPException(404, "project not found")
        return state

    def _project_to_collaboration(project_id: str, *, thread_id: str = "") -> None:
        if collaboration_store is None:
            return
        try:
            state = full_project_state(project_store, project_id)
            if state is None:
                return
            project = state.get("project") if isinstance(state.get("project"), dict) else {}
            session_id = thread_id or f"project:{project_id}"
            room_id = f"project:{project_id}"
            if thread_id:
                try:
                    group_state = _group_store().state(thread_id)
                    linked_room = getattr(group_state, "room_id", "") or ""
                    if linked_room:
                        room_id = str(linked_room)
                except Exception:  # noqa: BLE001
                    room_id = f"project:{project_id}"
            upsert_room = getattr(collaboration_store, "upsert_room", None)
            if callable(upsert_room):
                upsert_room(
                    session_id,
                    {
                        "id": room_id,
                        "name": project.get("name") or f"Project {project_id}",
                        "metadata": {
                            "source": "projectos",
                            "project_id": project_id,
                            **({"thread_id": thread_id} if thread_id else {}),
                        },
                    },
                )
            upsert_project_task = getattr(collaboration_store, "upsert_project_task", None)
            if not callable(upsert_project_task):
                return
            milestones = state.get("milestones") if isinstance(state.get("milestones"), list) else []
            tasks_by_ms = state.get("tasks") if isinstance(state.get("tasks"), dict) else {}
            for milestone in milestones:
                if not isinstance(milestone, dict):
                    continue
                milestone_id = str(milestone.get("id") or "")
                tasks = tasks_by_ms.get(milestone_id) if isinstance(tasks_by_ms, dict) else []
                if not isinstance(tasks, list):
                    continue
                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    assigned_agent = str(task.get("assigned_agent") or "")
                    assigned_role = str(task.get("assigned_role") or "")
                    upsert_project_task(
                        session_id=session_id,
                        room_id=room_id,
                        project_id=project_id,
                        milestone_id=milestone_id,
                        task={
                            "id": task.get("id"),
                            "kind": "project",
                            "title": task.get("goal") or task.get("id"),
                            "description": task.get("goal") or "",
                            "status": task.get("status") or "pending",
                            "assignees": [
                                item
                                for item in (
                                    {"name": assigned_agent, "role": "agent"},
                                    {"name": assigned_role, "role": "role"},
                                )
                                if item["name"]
                            ],
                            "artifacts": (
                                [{"kind": "project_task_output", "output": task.get("output")}]
                                if task.get("output") not in (None, "", {}, [])
                                else []
                            ),
                            "metadata": {
                                "source": "projectos",
                                "project_id": project_id,
                                "milestone_id": milestone_id,
                                "task_type": task.get("type"),
                                "assigned_agent": assigned_agent,
                                "assigned_role": assigned_role,
                                "attempts": task.get("attempts"),
                            },
                        },
                    )
        except Exception:  # noqa: BLE001 - projection must not block Project OS writes
            return

    @router.get("/api/projects")
    def list_projects() -> dict[str, Any]:
        return {"projects": [p.to_dict() for p in project_store.list_projects()]}

    @router.get("/api/projects/by-thread/{thread_id}")
    def get_project_by_thread(thread_id: str) -> dict[str, Any]:
        try:
            project = project_store.project_for_thread(thread_id)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        if project is None:
            raise HTTPException(404, "project not found for thread")
        return _full_state(project.id)

    @router.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        return _full_state(project_id)

    @router.get("/api/projects/{project_id}/report")
    def report(project_id: str) -> dict[str, Any]:
        """A milestone report: each milestone + its tasks' status/output."""
        project = _project_or_404(project_id)
        out = []
        try:
            milestones = project_store.milestones_for(project_id)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        for m in milestones:
            out.append(
                {
                    "id": m.id,
                    "name": m.name,
                    "status": m.status,
                    "success_criteria": m.success_criteria,
                    "tasks": [
                        {
                            "id": t.id,
                            "role": t.assigned_role,
                            "type": t.type,
                            "status": t.status,
                            "output": t.output,
                        }
                        for t in project_store.tasks_for_milestone(m.id)
                    ],
                }
            )
        return {"project": project.name, "status": project.status, "milestones": out}

    @router.get("/api/projects/{project_id}/events")
    def events(project_id: str, limit: int = 100) -> dict[str, Any]:
        """Project audit trail: recoveries, interventions, and future operator actions."""
        _project_or_404(project_id)
        try:
            audit_events = project_store.events_for_project(project_id, limit=limit)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {
            "project_id": project_id,
            "events": audit_events,
        }

    @router.get("/api/projects/{project_id}/process-timeline")
    def process_timeline(project_id: str, limit: int = 100) -> dict[str, Any]:
        """Project process timeline: persisted plan/run/control evidence."""
        _project_or_404(project_id)
        try:
            timeline = project_process_timeline(project_store, project_id, limit=limit)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        if timeline is None:
            raise HTTPException(404, "project not found")
        return {"timeline": timeline}

    @router.post("/api/projects", dependencies=[Depends(_auth_dep)])
    def plan(body: PlanBody) -> dict[str, Any]:
        """Turn a one-line goal into a project with generated milestones."""
        try:
            project = _engine().plan(body.name, body.goal)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        _project_to_collaboration(project.id)
        return {"ok": True, **_full_state(project.id)}

    @router.post("/api/projects/from-group/{thread_id}", dependencies=[Depends(_auth_dep)])
    def from_group(thread_id: str, body: FromGroupBody) -> dict[str, Any]:
        """Turn a custom cowork group into a project team: plan milestones and (by
        default) run them, routing each task to the group's ACTUAL members by
        capability — not the fixed 4 roles. This is "assemble a group → turn on
        project mode"."""
        try:
            result = run_project_from_group(
                project_store,
                _group_store(),
                thread_id,
                name=body.name,
                goal=body.goal,
                hooks=_base_hooks(),
                run=body.run,
                max_ticks=body.max_ticks,
            )
            project = result.get("project") if isinstance(result.get("project"), dict) else {}
            project_id = str(project.get("id") or "")
            if project_id:
                _project_to_collaboration(project_id, thread_id=thread_id)
            return result
        except ValueError as exc:
            raise _bad_request(exc) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"project run failed: {exc}") from exc

    @router.post("/api/projects/{project_id}/tick", dependencies=[Depends(_auth_dep)])
    def tick(project_id: str) -> dict[str, Any]:
        """Advance the project one loop iteration."""
        _project_or_404(project_id)
        try:
            result = _engine().tick(project_id)
            thread_project = project_store.thread_for_project(project_id)
            _project_to_collaboration(project_id, thread_id=thread_project or "")
            return result
        except ValueError as exc:
            raise _bad_request(exc) from exc

    @router.post("/api/projects/{project_id}/run", dependencies=[Depends(_auth_dep)])
    def run(project_id: str, body: RunBody) -> dict[str, Any]:
        """Drive the loop until the project is done/blocked or max_ticks."""
        _project_or_404(project_id)
        try:
            result = _engine().run(project_id, max_ticks=body.max_ticks)
            thread_project = project_store.thread_for_project(project_id)
            _project_to_collaboration(project_id, thread_id=thread_project or "")
            return result
        except ValueError as exc:
            raise _bad_request(exc) from exc

    @router.post("/api/projects/{project_id}/recover", dependencies=[Depends(_auth_dep)])
    def recover(project_id: str, body: RecoverBody) -> dict[str, Any]:
        """Reopen blocked project work after an operator fixes the cause."""
        _project_or_404(project_id)
        engine = _engine()
        try:
            recovered = engine.recover(
                project_id,
                task_ids=body.task_ids,
                reset_attempts=body.reset_attempts,
                clear_outputs=body.clear_outputs,
            )
        except ValueError as exc:
            raise _bad_request(exc) from exc
        if body.run:
            try:
                run_result = engine.run(project_id, max_ticks=body.max_ticks)
            except ValueError as exc:
                raise _bad_request(exc) from exc
            thread_project = project_store.thread_for_project(project_id)
            _project_to_collaboration(project_id, thread_id=thread_project or "")
            return {"ok": True, "recover": recovered, "run": run_result, **_full_state(project_id)}
        thread_project = project_store.thread_for_project(project_id)
        _project_to_collaboration(project_id, thread_id=thread_project or "")
        return {"ok": True, "recover": recovered, **_full_state(project_id)}

    @router.post(
        "/api/projects/{project_id}/tasks/{task_id}/intervene",
        dependencies=[Depends(_auth_dep)],
    )
    def intervene_task(project_id: str, task_id: str, body: TaskInterventionBody) -> dict[str, Any]:
        """Manually reassign, reset, complete, or skip a task."""
        _project_or_404(project_id)
        engine = _engine()
        try:
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
        except ValueError as exc:
            raise _bad_request(exc) from exc
        if any(str(event).startswith("task_not_found:") for event in intervention["events"]):
            raise HTTPException(404, "task not found")
        if any(str(event).startswith("unknown_task_action:") for event in intervention["events"]):
            raise HTTPException(400, "unknown task intervention action")
        if body.run:
            try:
                run_result = engine.run(project_id, max_ticks=body.max_ticks)
            except ValueError as exc:
                raise _bad_request(exc) from exc
            thread_project = project_store.thread_for_project(project_id)
            _project_to_collaboration(project_id, thread_id=thread_project or "")
            return {
                "ok": True,
                "intervention": intervention,
                "run": run_result,
                **_full_state(project_id),
            }
        thread_project = project_store.thread_for_project(project_id)
        _project_to_collaboration(project_id, thread_id=thread_project or "")
        return {"ok": True, "intervention": intervention, **_full_state(project_id)}

    return router

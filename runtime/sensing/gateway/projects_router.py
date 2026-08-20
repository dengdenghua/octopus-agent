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
from runtime.safety.auth.principal import CurrentPrincipal, resolve_principal
from runtime.safety.auth.scope import scope_from_principal


class PlanBody(BaseModel):
    name: str = Field(min_length=1)
    goal: str = Field(min_length=1)


class MoveThreadBody(BaseModel):
    thread_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)


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
    thread_store: Any = None,
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

    def _principal(request: Request) -> CurrentPrincipal | None:
        principal = resolve_principal(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )
        if principal is not None:
            request.state.project_principal = principal
        return principal

    def _scoped_store(request: Request) -> ProjectStore:
        principal = _principal(request)
        if principal is None:
            return project_store
        allow_cross_tenant = bool(principal.roles.intersection({"admin", "operator"}))
        return project_store.with_scope(
            scope_from_principal(principal, allow_cross_tenant=allow_cross_tenant)
        )

    def _engine(principal: CurrentPrincipal | None = None) -> ProjectEngine:
        scope = scope_from_principal(
            principal,
            allow_cross_tenant=bool(
                principal is not None and principal.roles.intersection({"admin", "operator"})
            ),
        )
        return ProjectEngine(
            project_store,
            **_base_hooks(),
            owner_id=principal.actor_id if principal is not None else "",
            tenant_id=principal.tenant_id if principal is not None else "",
            scope=scope,
        )

    def _auth_dep(request: Request) -> None:
        _principal(request)

    router = APIRouter(tags=["projectos"], dependencies=[Depends(_auth_dep)])

    def _bad_request(exc: ValueError) -> HTTPException:
        return HTTPException(400, str(exc))

    def _project_or_404(
        request: Request,
        project_id: str,
        *,
        allow_operator: bool = True,
    ):
        try:
            project = _scoped_store(request).get_project(project_id)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        if project is None:
            raise HTTPException(404, "project not found")
        principal = _principal(request)
        if principal is not None:
            global_operator = bool(principal.roles.intersection({"admin", "operator"}))
            if not project.owner_id or not project.tenant_id:
                if not (allow_operator and global_operator):
                    raise HTTPException(404, "project not found")
            elif project.tenant_id != principal.tenant_id or (
                project.owner_id != principal.actor_id and not global_operator
            ):
                raise HTTPException(404, "project not found")
        return project

    def _thread_access(request: Request, thread_id: str) -> CurrentPrincipal | None:
        principal = _principal(request)
        if principal is None:
            return None
        if thread_store is None or not hasattr(thread_store, "get"):
            raise HTTPException(503, "thread ownership unavailable")
        thread = thread_store.get(thread_id)
        if thread is None:
            raise HTTPException(404, "thread not found")
        metadata = thread.get("metadata") if isinstance(thread, dict) else {}
        owner = metadata.get("owner_actor_id") if isinstance(metadata, dict) else None
        stored_tenant = (
            str(metadata.get("tenant_id") or "").strip() if isinstance(metadata, dict) else ""
        )
        if not principal.tenant_id.startswith("legacy:") and stored_tenant != principal.tenant_id:
            raise HTTPException(404, "thread not found")
        if stored_tenant and stored_tenant != principal.tenant_id:
            raise HTTPException(404, "thread not found")
        if owner != principal.actor_id and not principal.roles.intersection({"admin", "operator"}):
            raise HTTPException(404, "thread not found")
        return principal

    def _full_state(request: Request, project_id: str) -> dict[str, Any]:
        _project_or_404(request, project_id)
        try:
            state = full_project_state(_scoped_store(request), project_id)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        if state is None:
            raise HTTPException(404, "project not found")
        return state

    def _project_to_collaboration(
        request: Request, project_id: str, *, thread_id: str = ""
    ) -> None:
        if collaboration_store is None:
            return
        try:
            state = full_project_state(_scoped_store(request), project_id)
            if state is None:
                return
            raw_project = state.get("project")
            project = raw_project if isinstance(raw_project, dict) else {}
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
                            "tenant_id": project.get("tenant_id") or "",
                            **({"thread_id": thread_id} if thread_id else {}),
                        },
                    },
                )
            upsert_project_task = getattr(collaboration_store, "upsert_project_task", None)
            if not callable(upsert_project_task):
                return
            raw_milestones = state.get("milestones")
            milestones = raw_milestones if isinstance(raw_milestones, list) else []
            raw_tasks = state.get("tasks")
            tasks_by_ms = raw_tasks if isinstance(raw_tasks, dict) else {}
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
                                "tenant_id": project.get("tenant_id") or "",
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
    def list_projects(request: Request) -> dict[str, Any]:
        principal = _principal(request)
        projects = _scoped_store(request).list_projects()
        if principal is not None:
            global_operator = bool(principal.roles.intersection({"admin", "operator"}))
            visible: list[Any] = []
            for project in projects:
                if project.tenant_id and project.tenant_id != principal.tenant_id:
                    continue
                if not project.owner_id or not project.tenant_id:
                    if global_operator:
                        visible.append(project)
                    continue
                if project.owner_id == principal.actor_id or global_operator:
                    visible.append(project)
            projects = visible
        return {"projects": [p.to_dict() for p in projects]}

    @router.get("/api/projects/by-thread/{thread_id}")
    def get_project_by_thread(request: Request, thread_id: str) -> dict[str, Any]:
        _thread_access(request, thread_id)
        try:
            project = _scoped_store(request).project_for_thread(thread_id)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        if project is None:
            raise HTTPException(404, "project not found for thread")
        return _full_state(request, project.id)

    @router.get("/api/projects/thread-map")
    def thread_project_map(request: Request) -> dict[str, str]:
        principal = _principal(request)
        scoped_store = _scoped_store(request)
        mapping = scoped_store.thread_project_map()
        if principal is None:
            return mapping
        filtered: dict[str, str] = {}
        for thread_id, project_id in mapping.items():
            project = scoped_store.get_project(project_id)
            if project is None or project.tenant_id != principal.tenant_id:
                continue
            if project.owner_id == principal.actor_id or principal.roles.intersection(
                {"admin", "operator"}
            ):
                filtered[thread_id] = project_id
        return filtered

    @router.get("/api/projects/{project_id}")
    def get_project(request: Request, project_id: str) -> dict[str, Any]:
        return _full_state(request, project_id)

    @router.get("/api/projects/{project_id}/report")
    def report(request: Request, project_id: str) -> dict[str, Any]:
        """A milestone report: each milestone + its tasks' status/output."""
        project = _project_or_404(request, project_id)
        out = []
        try:
            scoped_store = _scoped_store(request)
            milestones = scoped_store.milestones_for(project_id)
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
                        for t in scoped_store.tasks_for_milestone(m.id)
                    ],
                }
            )
        return {"project": project.name, "status": project.status, "milestones": out}

    @router.get("/api/projects/{project_id}/pm")
    def pm_console(request: Request, project_id: str) -> dict[str, Any]:
        """PM 驾驶舱：里程碑健康度、燃尽、风险/阻塞、下一步、指派。"""
        project = _project_or_404(request, project_id)
        try:
            scoped_store = _scoped_store(request)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        from runtime.projectos.pm import build_pm_report

        report = build_pm_report(scoped_store, project_id)
        return {
            "project_id": project_id,
            "project": project.name,
            "status": project.status,
            "pm": report or {},
        }

    @router.get("/api/projects/{project_id}/retro")
    def retro(request: Request, project_id: str) -> dict[str, Any]:
        """复盘：完工项目的交付、成本与建议。"""
        project = _project_or_404(request, project_id)
        try:
            scoped_store = _scoped_store(request)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        from runtime.projectos.pm import build_retro

        return {"project_id": project_id, "project": project.name, "retro": build_retro(scoped_store, project_id) or {}}

    @router.get("/api/projects/{project_id}/events")
    def events(request: Request, project_id: str, limit: int = 100) -> dict[str, Any]:
        """Project audit trail: recoveries, interventions, and future operator actions."""
        _project_or_404(request, project_id)
        try:
            audit_events = _scoped_store(request).events_for_project(project_id, limit=limit)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {
            "project_id": project_id,
            "events": audit_events,
        }

    @router.get("/api/projects/{project_id}/process-timeline")
    def process_timeline(request: Request, project_id: str, limit: int = 100) -> dict[str, Any]:
        """Project process timeline: persisted plan/run/control evidence."""
        _project_or_404(request, project_id)
        try:
            timeline = project_process_timeline(_scoped_store(request), project_id, limit=limit)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        if timeline is None:
            raise HTTPException(404, "project not found")
        return {"timeline": timeline}

    @router.post("/api/projects", dependencies=[Depends(_auth_dep)])
    def plan(request: Request, body: PlanBody) -> dict[str, Any]:
        """Turn a one-line goal into a project with generated milestones."""
        principal = _principal(request)
        try:
            project = _engine(principal).plan(body.name, body.goal)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        _project_to_collaboration(request, project.id)
        return {"ok": True, **_full_state(request, project.id)}

    @router.post("/api/projects/move", dependencies=[Depends(_auth_dep)])
    def move_thread(request: Request, body: MoveThreadBody) -> dict[str, Any]:
        project = _project_or_404(request, body.project_id)
        _thread_access(request, body.thread_id)
        try:
            _scoped_store(request).bind_thread(body.thread_id, project.id)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {"ok": True, "thread_id": body.thread_id, "project_id": project.id}

    @router.delete("/api/projects/{project_id}", dependencies=[Depends(_auth_dep)])
    def delete_project(request: Request, project_id: str) -> dict[str, Any]:
        _project_or_404(request, project_id)
        try:
            _scoped_store(request).delete_project(project_id)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {"ok": True, "project_id": project_id}

    @router.post("/api/projects/from-group/{thread_id}", dependencies=[Depends(_auth_dep)])
    def from_group(request: Request, thread_id: str, body: FromGroupBody) -> dict[str, Any]:
        """Turn a custom cowork group into a project team: plan milestones and (by
        default) run them, routing each task to the group's ACTUAL members by
        capability — not the fixed 4 roles. This is "assemble a group → turn on
        project mode"."""
        principal = _thread_access(request, thread_id)
        try:
            result = run_project_from_group(
                _scoped_store(request),
                _group_store(),
                thread_id,
                name=body.name,
                goal=body.goal,
                hooks=_base_hooks(),
                run=body.run,
                max_ticks=body.max_ticks,
                owner_id=principal.actor_id if principal is not None else "",
                tenant_id=principal.tenant_id if principal is not None else "",
            )
            raw_project = result.get("project")
            project = raw_project if isinstance(raw_project, dict) else {}
            project_id = str(project.get("id") or "")
            if project_id:
                _project_to_collaboration(request, project_id, thread_id=thread_id)
            return result
        except ValueError as exc:
            raise _bad_request(exc) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"project run failed: {exc}") from exc

    @router.post("/api/projects/{project_id}/tick", dependencies=[Depends(_auth_dep)])
    def tick(request: Request, project_id: str) -> dict[str, Any]:
        """Advance the project one loop iteration."""
        _project_or_404(request, project_id)
        try:
            result = _engine(_principal(request)).tick(project_id)
            thread_project = _scoped_store(request).thread_for_project(project_id)
            _project_to_collaboration(request, project_id, thread_id=thread_project or "")
            return result
        except ValueError as exc:
            raise _bad_request(exc) from exc

    @router.post("/api/projects/{project_id}/run", dependencies=[Depends(_auth_dep)])
    def run(request: Request, project_id: str, body: RunBody) -> dict[str, Any]:
        """Drive the loop until the project is done/blocked or max_ticks."""
        _project_or_404(request, project_id)
        try:
            result = _engine(_principal(request)).run(project_id, max_ticks=body.max_ticks)
            thread_project = _scoped_store(request).thread_for_project(project_id)
            _project_to_collaboration(request, project_id, thread_id=thread_project or "")
            return result
        except ValueError as exc:
            raise _bad_request(exc) from exc

    @router.post("/api/projects/{project_id}/recover", dependencies=[Depends(_auth_dep)])
    def recover(request: Request, project_id: str, body: RecoverBody) -> dict[str, Any]:
        """Reopen blocked project work after an operator fixes the cause."""
        _project_or_404(request, project_id)
        engine = _engine(_principal(request))
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
            thread_project = _scoped_store(request).thread_for_project(project_id)
            _project_to_collaboration(request, project_id, thread_id=thread_project or "")
            return {
                "ok": True,
                "recover": recovered,
                "run": run_result,
                **_full_state(request, project_id),
            }
        thread_project = _scoped_store(request).thread_for_project(project_id)
        _project_to_collaboration(request, project_id, thread_id=thread_project or "")
        return {"ok": True, "recover": recovered, **_full_state(request, project_id)}

    @router.post(
        "/api/projects/{project_id}/tasks/{task_id}/intervene",
        dependencies=[Depends(_auth_dep)],
    )
    def intervene_task(
        request: Request,
        project_id: str,
        task_id: str,
        body: TaskInterventionBody,
    ) -> dict[str, Any]:
        """Manually reassign, reset, complete, or skip a task."""
        _project_or_404(request, project_id)
        engine = _engine(_principal(request))
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
            thread_project = _scoped_store(request).thread_for_project(project_id)
            _project_to_collaboration(request, project_id, thread_id=thread_project or "")
            return {
                "ok": True,
                "intervention": intervention,
                "run": run_result,
                **_full_state(request, project_id),
            }
        thread_project = _scoped_store(request).thread_for_project(project_id)
        _project_to_collaboration(request, project_id, thread_id=thread_project or "")
        return {
            "ok": True,
            "intervention": intervention,
            **_full_state(request, project_id),
        }

    return router

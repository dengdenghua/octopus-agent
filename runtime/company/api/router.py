from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.company.core import (
    BindProjectTeamRoomRequest,
    BulkImportPatentRecordsRequest,
    CompanyStore,
    CreatePatentRecordRequest,
    CreatePatentRiskRequest,
    CreatePatentSearchTopicRequest,
    CreateProjectBlueprintRequest,
    CreateProjectMilestoneRequest,
    CreateProjectRequest,
    CreateProjectTaskDependencyRequest,
    CreateProjectTaskRequest,
    DispatchProjectTaskRequest,
    MaterializedAgentWire,
    MaterializeTeamAssemblyMemberRequest,
    MaterializeTeamAssemblyMemberResponse,
    ProjectTeamAssemblyMember,
    UpdatePatentRecordRequest,
    UpdatePatentRiskRequest,
    UpdatePatentSearchTopicRequest,
    UpdateProjectMilestoneRequest,
    UpdateProjectRequest,
    UpdateProjectTaskRequest,
    project_task_to_team_task_payload,
)

try:
    from fastapi import APIRouter, HTTPException, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]
    FASTAPI_AVAILABLE = False


TeamTaskDispatcher = Callable[
    [Any, dict[str, Any], bool],
    dict[str, Any] | Awaitable[dict[str, Any]],
]
TeamRoomCreator = Callable[
    [Any, dict[str, Any]],
    dict[str, Any] | Awaitable[dict[str, Any]],
]
TeamRoomUpdater = Callable[
    [Any, str, dict[str, Any]],
    dict[str, Any] | Awaitable[dict[str, Any]],
]


def create_company_router(
    *,
    state_path: Path | None = None,
    team_task_dispatcher: TeamTaskDispatcher | None = None,
    team_room_creator: TeamRoomCreator | None = None,
    team_room_updater: TeamRoomUpdater | None = None,
    agent_registry: Any = None,
    runtime: Any = None,
) -> Any:
    """Create Company Workbench planning routes."""
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(tags=["company"])
    store = CompanyStore(state_path)

    @router.get("/api/company/projects")
    def list_projects() -> dict[str, Any]:
        projects = store.list_projects()
        return {
            "projects": [p.model_dump() for p in projects],
            "count": len(projects),
        }

    @router.post("/api/company/projects")
    def create_project(body: CreateProjectRequest) -> dict[str, Any]:
        return store.create_project(body).model_dump()

    @router.post("/api/company/projects/blueprint")
    def create_project_blueprint(
        body: CreateProjectBlueprintRequest,
    ) -> dict[str, Any]:
        return store.create_project_blueprint(body).model_dump()

    @router.get("/api/company/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        project = store.get_project(project_id)
        if project is None:
            raise HTTPException(404, f"project not found: {project_id}")
        return project.model_dump()

    @router.patch("/api/company/projects/{project_id}")
    def update_project(
        project_id: str,
        body: UpdateProjectRequest,
    ) -> dict[str, Any]:
        try:
            project = store.update_project(project_id, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if project is None:
            raise HTTPException(404, f"project not found: {project_id}")
        return project.model_dump()

    @router.delete("/api/company/projects/{project_id}")
    def delete_project(project_id: str) -> dict[str, Any]:
        deleted = store.delete_project(project_id)
        if not deleted:
            raise HTTPException(404, f"project not found: {project_id}")
        return {"deleted": True, "project_id": project_id}

    @router.post("/api/company/projects/{project_id}/team-assembly")
    def assemble_project_team(project_id: str) -> dict[str, Any]:
        assembly = store.assemble_project_team(project_id)
        if assembly is None:
            raise HTTPException(404, f"project not found: {project_id}")
        return assembly.model_dump()

    @router.post("/api/company/projects/{project_id}/team-assembly/{member_id}/materialize")
    async def materialize_team_assembly_member(
        request: Request,
        project_id: str,
        member_id: str,
        body: MaterializeTeamAssemblyMemberRequest,
    ) -> dict[str, Any]:
        project = store.get_project(project_id)
        if project is None:
            raise HTTPException(404, f"project not found: {project_id}")
        assembly = _assembly_metadata(project.model_dump())
        if assembly is None:
            raise HTTPException(409, "project team has not been assembled")
        member = _find_assembly_member(assembly, member_id)
        if member is None:
            raise HTTPException(404, f"team assembly member not found: {member_id}")
        if member.kind == "human" or member.status == "requires_human":
            raise HTTPException(409, "human roles must be bound to a real member")
        if member.status == "matched" and member.source_agent_id:
            existing = _materialized_existing_response(
                project=project.model_dump(),
                member=member,
                registry=agent_registry,
            )
            if team_room_updater is not None:
                sync = await _sync_project_team_room(
                    request,
                    store,
                    project,
                    team_room_updater,
                )
                existing.team_room_synced = sync["synced"]
                existing.team_room_id = sync["team_room_id"]
            return existing.model_dump()

        from runtime.execution.agents.loader import load_agent
        from runtime.execution.agents.scaffold import scaffold_agent

        agent_id = body.agent_id or _materialized_agent_id(project.id, member)
        display_name = body.display_name or member.display_name or member.role
        identity_card = _materialized_identity_card(
            project.model_dump(),
            member,
            agent_id=agent_id,
            display_name=display_name,
        )
        description = _materialized_agent_description(project.model_dump(), member)
        try:
            result = scaffold_agent(
                agent_id=agent_id,
                display_name=display_name,
                description=description,
                model=body.model,
                soul=_materialized_agent_soul(project.model_dump(), member, identity_card),
                tool_groups=_materialized_agent_tool_groups(member),
                extra_affinity=member.skills,
                private_skills=_materialized_agent_private_skills(member),
                metadata={
                    "source": "company_workbench",
                    "project_id": project.id,
                    "assembly_member_id": member.id,
                    "slot_id": member.slot_id,
                    "kind": member.kind,
                    "level": member.level,
                    "identity_card": identity_card,
                },
                extra_files={
                    "agent-core/COMPANY_ROLE.md": _materialized_role_contract(
                        project.model_dump(),
                        member,
                        identity_card,
                    ),
                    "memory/company_identity.json": json.dumps(
                        identity_card,
                        ensure_ascii=False,
                        indent=2,
                    ),
                },
                creator="company_workbench",
                template_id=_materialized_template_id(member),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                500,
                f"failed to create agent files: {type(exc).__name__}: {exc}",
            ) from exc

        hot_loaded = False
        if runtime is not None and agent_registry is not None:
            try:
                agent = load_agent(result.agent_dir, runtime, result.agent_dir.parent / "_shared")
                if hasattr(agent_registry, "replace"):
                    agent_registry.replace(agent)
                else:
                    agent_registry.register(agent)
                hot_loaded = True
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                raise HTTPException(
                    500,
                    f"agent load failed after creation: {type(exc).__name__}: {exc}",
                ) from exc

        updated_member = _mark_member_materialized(
            member,
            agent_id=result.agent_id,
            display_name=display_name,
            hot_loaded=hot_loaded,
            agent_dir=result.agent_dir,
            identity_card=identity_card,
        )
        updated_project = _replace_assembly_member(store, project_id, assembly, updated_member)
        if updated_project is None:
            raise HTTPException(404, f"project not found: {project_id}")
        sync = await _sync_project_team_room(
            request,
            store,
            updated_project,
            team_room_updater,
        )
        response = MaterializeTeamAssemblyMemberResponse(
            project=updated_project,
            member=updated_member,
            agent=MaterializedAgentWire(
                id=result.agent_id,
                name=display_name,
                description=description,
                agent_dir=str(result.agent_dir),
                identity_card=identity_card,
            ),
            created=True,
            hot_loaded=hot_loaded,
            requires_reload=not hot_loaded,
            team_room_synced=sync["synced"],
            team_room_id=sync["team_room_id"],
        )
        return response.model_dump()

    @router.post("/api/company/projects/{project_id}/team-room")
    async def bind_team_room(
        request: Request,
        project_id: str,
        body: BindProjectTeamRoomRequest,
    ) -> dict[str, Any]:
        project = store.get_project(project_id)
        if project is None:
            raise HTTPException(404, f"project not found: {project_id}")
        if project.team_room_id and not body.force_new and not body.team_room_id:
            return {
                "created": False,
                "team_room_id": project.team_room_id,
                "team": None,
                "project": project.model_dump(),
            }

        created = False
        team: dict[str, Any] | None = None
        team_room_id = (body.team_room_id or "").strip()
        if not team_room_id:
            if team_room_creator is None:
                raise HTTPException(503, "team room creator is not configured")
            payload = _team_room_payload_for_project(project.model_dump(), body)
            created_team = team_room_creator(request, payload)
            team = await created_team if isinstance(created_team, Awaitable) else created_team
            team_room_id = str(team.get("id") or "").strip()
            created = True
        if not team_room_id:
            raise HTTPException(400, "team_room_id is required")

        updated = store.update_project(
            project_id,
            UpdateProjectRequest(
                team_room_id=team_room_id,
                metadata={
                    **dict(project.metadata),
                    "team_room": {
                        "id": team_room_id,
                        "created": created,
                        "source": "company_workbench",
                    },
                },
            ),
        )
        if updated is None:
            raise HTTPException(404, f"project not found: {project_id}")
        return {
            "created": created,
            "team_room_id": team_room_id,
            "team": team,
            "project": updated.model_dump(),
        }

    @router.get("/api/company/projects/{project_id}/milestones")
    def list_milestones(project_id: str) -> dict[str, Any]:
        if store.get_project(project_id) is None:
            raise HTTPException(404, f"project not found: {project_id}")
        milestones = store.list_milestones(project_id)
        return {
            "milestones": [m.model_dump() for m in milestones],
            "count": len(milestones),
        }

    @router.post("/api/company/projects/{project_id}/milestones")
    def create_milestone(
        project_id: str,
        body: CreateProjectMilestoneRequest,
    ) -> dict[str, Any]:
        milestone = store.create_milestone(project_id, body)
        if milestone is None:
            raise HTTPException(404, f"project not found: {project_id}")
        return milestone.model_dump()

    @router.patch("/api/company/milestones/{milestone_id}")
    def update_milestone(
        milestone_id: str,
        body: UpdateProjectMilestoneRequest,
    ) -> dict[str, Any]:
        try:
            milestone = store.update_milestone(milestone_id, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if milestone is None:
            raise HTTPException(404, f"milestone not found: {milestone_id}")
        return milestone.model_dump()

    @router.get("/api/company/projects/{project_id}/tasks")
    def list_tasks(project_id: str) -> dict[str, Any]:
        if store.get_project(project_id) is None:
            raise HTTPException(404, f"project not found: {project_id}")
        tasks = store.list_tasks(project_id)
        return {
            "tasks": [t.model_dump() for t in tasks],
            "count": len(tasks),
        }

    @router.get("/api/company/projects/{project_id}/artifacts")
    def list_artifacts(project_id: str) -> dict[str, Any]:
        artifacts = store.list_artifacts(project_id)
        if artifacts is None:
            raise HTTPException(404, f"project not found: {project_id}")
        return {
            "artifacts": [artifact.model_dump() for artifact in artifacts],
            "count": len(artifacts),
        }

    @router.get("/api/company/projects/{project_id}/insights")
    def list_insights(project_id: str) -> dict[str, Any]:
        insights = store.list_insights(project_id)
        if insights is None:
            raise HTTPException(404, f"project not found: {project_id}")
        counts = {
            "risk": sum(1 for item in insights if item.kind == "risk"),
            "next_action": sum(
                1 for item in insights if item.kind == "next_action"
            ),
            "decision": sum(1 for item in insights if item.kind == "decision"),
        }
        return {
            "insights": [insight.model_dump() for insight in insights],
            "count": len(insights),
            "counts": counts,
        }

    @router.post("/api/company/projects/{project_id}/tasks")
    def create_task(
        project_id: str,
        body: CreateProjectTaskRequest,
    ) -> dict[str, Any]:
        task = store.create_task(project_id, body)
        if task is None:
            raise HTTPException(404, "project or milestone not found")
        return task.model_dump()

    @router.patch("/api/company/tasks/{task_id}")
    def update_task(
        task_id: str,
        body: UpdateProjectTaskRequest,
    ) -> dict[str, Any]:
        try:
            task = store.update_task(task_id, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if task is None:
            raise HTTPException(404, f"task not found or invalid relation: {task_id}")
        return task.model_dump()

    @router.post("/api/company/tasks/{task_id}/dispatch")
    async def dispatch_task(
        request: Request,
        task_id: str,
        body: DispatchProjectTaskRequest,
    ) -> dict[str, Any]:
        if team_task_dispatcher is None:
            raise HTTPException(503, "team task dispatcher is not configured")
        task = store.get_task(task_id)
        if task is None:
            raise HTTPException(404, f"task not found: {task_id}")
        if task.team_task_id and not body.force_new:
            return {
                "created": False,
                "run_requested": body.run,
                "team_task_id": task.team_task_id,
                "team_task": None,
                "project_task": task.model_dump(),
            }
        payload = project_task_to_team_task_payload(
            task,
            room_id=body.room_id or _project_team_room_id(store, task.project_id),
            sop_template=body.sop_template,
        )
        payload["metadata"] = {
            **dict(payload.get("metadata") or {}),
            "source": "company_workbench",
            "company_project_id": task.project_id,
            "company_task_id": task.id,
            "company_milestone_id": task.milestone_id,
            "output_contract": _project_update_output_contract(),
        }
        dispatched = team_task_dispatcher(request, payload, body.run)
        if isinstance(dispatched, Awaitable):
            team_task = await dispatched
        else:
            team_task = dispatched
        team_task_id = str(team_task.get("id") or "").strip()
        if not team_task_id:
            raise HTTPException(502, "team task dispatcher returned no task id")
        updated = store.update_task(
            task_id,
            UpdateProjectTaskRequest(
                status="doing" if body.run else None,
                team_task_id=team_task_id,
                metadata={
                    **dict(task.metadata),
                    "dispatch": {
                        "team_task_id": team_task_id,
                        "room_id": team_task.get("room_id"),
                        "run_requested": body.run,
                    },
                },
            ),
        )
        if updated is None:
            raise HTTPException(404, f"task not found: {task_id}")
        return {
            "created": True,
            "run_requested": body.run,
            "team_task_id": team_task_id,
            "team_task": team_task,
            "project_task": updated.model_dump(),
        }

    @router.get("/api/company/projects/{project_id}/dependencies")
    def list_dependencies(project_id: str) -> dict[str, Any]:
        if store.get_project(project_id) is None:
            raise HTTPException(404, f"project not found: {project_id}")
        dependencies = store.list_dependencies(project_id)
        return {
            "dependencies": [d.model_dump() for d in dependencies],
            "count": len(dependencies),
        }

    @router.post("/api/company/projects/{project_id}/dependencies")
    def create_dependency(
        project_id: str,
        body: CreateProjectTaskDependencyRequest,
    ) -> dict[str, Any]:
        dependency = store.create_dependency(project_id, body)
        if dependency is None:
            raise HTTPException(400, "invalid dependency")
        return dependency.model_dump()

    @router.get("/api/company/projects/{project_id}/gantt")
    def get_gantt(project_id: str) -> dict[str, Any]:
        rows = store.gantt_view(project_id)
        if rows is None:
            raise HTTPException(404, f"project not found: {project_id}")
        return {
            "items": [row.model_dump() for row in rows],
            "count": len(rows),
        }

    # ── Patent / FTO endpoints ──────────────────────────────────────────
    # Used by the patent-fto-screener agent (see
    # runtime/sensing/siphon/agent_market_sources/hardware-startup/agent-plugins/
    # patent-fto-screener/). All endpoints are project-scoped.

    @router.get("/api/company/projects/{project_id}/patents/topics")
    def list_patent_topics(project_id: str) -> dict[str, Any]:
        if store.get_project(project_id) is None:
            raise HTTPException(404, f"project not found: {project_id}")
        topics = store.list_patent_topics(project_id)
        return {"topics": [t.model_dump() for t in topics], "count": len(topics)}

    @router.post("/api/company/projects/{project_id}/patents/topics")
    def create_patent_topic(
        project_id: str,
        body: CreatePatentSearchTopicRequest,
    ) -> dict[str, Any]:
        topic = store.create_patent_topic(project_id, body)
        if topic is None:
            raise HTTPException(404, f"project not found: {project_id}")
        return topic.model_dump()

    @router.patch("/api/company/patents/topics/{topic_id}")
    def update_patent_topic(
        topic_id: str,
        body: UpdatePatentSearchTopicRequest,
    ) -> dict[str, Any]:
        try:
            topic = store.update_patent_topic(topic_id, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if topic is None:
            raise HTTPException(404, f"patent topic not found: {topic_id}")
        return topic.model_dump()

    @router.get("/api/company/projects/{project_id}/patents")
    def list_patents(project_id: str) -> dict[str, Any]:
        if store.get_project(project_id) is None:
            raise HTTPException(404, f"project not found: {project_id}")
        patents = store.list_patents(project_id)
        return {"patents": [p.model_dump() for p in patents], "count": len(patents)}

    @router.post("/api/company/projects/{project_id}/patents")
    def create_patent(
        project_id: str,
        body: CreatePatentRecordRequest,
    ) -> dict[str, Any]:
        record = store.create_patent(project_id, body)
        if record is None:
            raise HTTPException(404, "project or topic not found")
        return record.model_dump()

    @router.patch("/api/company/patents/{patent_id}")
    def update_patent(
        patent_id: str,
        body: UpdatePatentRecordRequest,
    ) -> dict[str, Any]:
        try:
            record = store.update_patent(patent_id, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if record is None:
            raise HTTPException(404, f"patent not found: {patent_id}")
        return record.model_dump()

    @router.post("/api/company/projects/{project_id}/patents/bulk-import")
    def bulk_import_patents(
        project_id: str,
        body: BulkImportPatentRecordsRequest,
    ) -> dict[str, Any]:
        """Bulk import a patent corpus (e.g. from xlsx) into the project.

        The patent-import-xlsx skill calls this after parsing a spreadsheet.
        Server-side dedup runs on (project_id, publication_number) → fallback
        (project_id, application_number) → fallback (project_id, title, applicant).
        Existing records are merged with non-empty new fields rather than
        overwritten.
        """
        try:
            counts = store.bulk_import_patents(project_id, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if counts is None:
            raise HTTPException(404, f"project not found: {project_id}")
        return {
            "project_id": project_id,
            "source_label": body.source_label,
            **counts,
            "total": counts["created"] + counts["updated"] + counts["skipped"],
        }

    @router.get("/api/company/projects/{project_id}/patents/risks")
    def list_patent_risks(project_id: str) -> dict[str, Any]:
        if store.get_project(project_id) is None:
            raise HTTPException(404, f"project not found: {project_id}")
        risks = store.list_patent_risks(project_id)
        return {"risks": [r.model_dump() for r in risks], "count": len(risks)}

    @router.post("/api/company/projects/{project_id}/patents/risks")
    def create_patent_risk(
        project_id: str,
        body: CreatePatentRiskRequest,
    ) -> dict[str, Any]:
        risk = store.create_patent_risk(project_id, body)
        if risk is None:
            raise HTTPException(404, "project or patent record not found")
        return risk.model_dump()

    @router.patch("/api/company/patents/risks/{risk_id}")
    def update_patent_risk(
        risk_id: str,
        body: UpdatePatentRiskRequest,
    ) -> dict[str, Any]:
        try:
            risk = store.update_patent_risk(risk_id, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if risk is None:
            raise HTTPException(404, f"patent risk not found: {risk_id}")
        return risk.model_dump()

    def _sync_team_task_event(payload: dict[str, Any]) -> dict[str, Any] | None:
        return _sync_company_task_from_team_event(store, payload)

    router.store = store  # type: ignore[attr-defined]
    router.sync_team_task_event = _sync_team_task_event  # type: ignore[attr-defined]
    return router


def _project_team_room_id(store: CompanyStore, project_id: str) -> str:
    project = store.get_project(project_id)
    if project is None:
        return project_id
    return project.team_room_id or project.id


def _project_update_output_contract() -> dict[str, Any]:
    return {
        "name": "project_update_v1",
        "instructions": [
            "Keep the normal answer concise and useful for the task.",
            "If you identify project management updates, include one fenced json block.",
            "Use empty arrays when a category has no concrete update.",
            "Do not invent risks, actions, or decisions that are not supported by the work.",
        ],
        "schema": {
            "risks": [
                {
                    "title": "short risk title",
                    "description": "why it matters",
                    "severity": "low | medium | high",
                    "owner": "optional owner",
                    "status": "open | watching | mitigated",
                },
            ],
            "next_actions": [
                {
                    "title": "concrete next step",
                    "description": "optional detail",
                    "owner": "optional owner",
                    "due_at": "optional ISO date",
                    "status": "todo | doing | done",
                },
            ],
            "decisions": [
                {
                    "title": "decision made or proposed",
                    "rationale": "why this decision is recommended",
                    "status": "proposed | accepted | rejected",
                },
            ],
        },
    }


def _sync_company_task_from_team_event(
    store: CompanyStore,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if payload.get("type") != "task:progress":
        return None
    team_task = payload.get("task")
    if not isinstance(team_task, dict):
        return None
    metadata = team_task.get("metadata")
    if not isinstance(metadata, dict):
        return None
    if metadata.get("source") != "company_workbench":
        return None
    company_task_id = str(metadata.get("company_task_id") or "").strip()
    if not company_task_id:
        return None
    project_task = store.get_task(company_task_id)
    if project_task is None:
        return None

    server_time = str(payload.get("server_time") or "")
    event = str(payload.get("event") or "")
    team_status = str(team_task.get("status") or "")
    next_status = _company_status_from_team_status(team_status, project_task.status)
    next_progress = _company_progress_from_team_event(
        payload,
        team_status=team_status,
        current_progress=project_task.progress,
    )
    sync_meta = {
        "team_task_id": team_task.get("id") or payload.get("task_id"),
        "room_id": team_task.get("room_id") or payload.get("room_id"),
        "status": team_status,
        "event": event,
        "synced_at": server_time,
    }
    if payload.get("role"):
        sync_meta["role"] = payload.get("role")
    if payload.get("completed_roles") is not None:
        sync_meta["completed_roles"] = payload.get("completed_roles")
    if payload.get("total_roles") is not None:
        sync_meta["total_roles"] = payload.get("total_roles")

    update: dict[str, Any] = {
        "team_task_id": str(team_task.get("id") or payload.get("task_id") or ""),
        "metadata": {
            **dict(project_task.metadata),
            "team_task_sync": sync_meta,
        },
    }
    if next_status is not None:
        update["status"] = next_status
    if next_progress is not None:
        update["progress"] = next_progress
    if team_status == "running" and not project_task.actual_start_at:
        update["actual_start_at"] = server_time or None
    if team_status in {"done", "failed", "cancelled"}:
        update["actual_end_at"] = server_time or None
    artifacts = team_task.get("produced_artifacts")
    if isinstance(artifacts, list) and artifacts:
        update["metadata"]["team_task_artifacts"] = artifacts

    updated = store.update_task(company_task_id, UpdateProjectTaskRequest(**update))
    return updated.model_dump() if updated is not None else None


def _company_status_from_team_status(
    team_status: str,
    current_status: str,
) -> str | None:
    if team_status == "pending":
        return "todo" if current_status in {"todo", "doing"} else None
    if team_status == "running":
        return "doing"
    if team_status == "done":
        return "done"
    if team_status == "failed":
        return "blocked"
    if team_status == "cancelled":
        return "cancelled"
    return None


def _company_progress_from_team_event(
    payload: dict[str, Any],
    *,
    team_status: str,
    current_progress: int,
) -> int | None:
    if team_status == "done":
        return 100
    raw = payload.get("progress")
    if isinstance(raw, (int, float)):
        progress = int(round(raw * 100 if 0 <= raw <= 1 else raw))
        return max(current_progress, max(0, min(99, progress)))
    return None


def _team_room_payload_for_project(
    project: dict[str, Any],
    body: BindProjectTeamRoomRequest,
) -> dict[str, Any]:
    members = body.members or _team_members_for_project(project)
    return {
        "id": body.team_room_id or f"company-{project['id']}",
        "name": body.name or f"{project['name']} 工作间",
        "members": members,
        "leaderId": body.leaderId or members[0]["name"],
    }


async def _sync_project_team_room(
    request: Any,
    store: CompanyStore,
    project: Any,
    team_room_updater: TeamRoomUpdater | None,
) -> dict[str, Any]:
    team_room_id = str(getattr(project, "team_room_id", None) or "").strip()
    if not team_room_id or team_room_updater is None:
        return {"synced": False, "team_room_id": team_room_id or None}

    refreshed = store.get_project(str(project.id))
    if refreshed is None:
        return {"synced": False, "team_room_id": team_room_id}

    payload = _team_room_payload_for_project(
        refreshed.model_dump(),
        BindProjectTeamRoomRequest(
            team_room_id=team_room_id,
            name=f"{refreshed.name} 工作间",
        ),
    )
    updated = team_room_updater(request, team_room_id, payload)
    await updated if isinstance(updated, Awaitable) else updated
    return {"synced": True, "team_room_id": team_room_id}


def _assembly_metadata(project: dict[str, Any]) -> dict[str, Any] | None:
    metadata = project.get("metadata")
    assembly = metadata.get("team_assembly") if isinstance(metadata, dict) else None
    return assembly if isinstance(assembly, dict) else None


def _find_assembly_member(
    assembly: dict[str, Any],
    member_id: str,
) -> ProjectTeamAssemblyMember | None:
    raw_members = assembly.get("members")
    if not isinstance(raw_members, list):
        return None
    for item in raw_members:
        if not isinstance(item, dict):
            continue
        if member_id in {
            str(item.get("id") or ""),
            str(item.get("slot_id") or ""),
            str(item.get("role") or ""),
        }:
            return ProjectTeamAssemblyMember.model_validate(item)
    return None


def _replace_assembly_member(
    store: CompanyStore,
    project_id: str,
    assembly: dict[str, Any],
    member: ProjectTeamAssemblyMember,
) -> Any | None:
    raw_members = assembly.get("members")
    if not isinstance(raw_members, list):
        return None
    updated_members: list[dict[str, Any]] = []
    replaced = False
    for item in raw_members:
        if isinstance(item, dict) and str(item.get("id") or "") == member.id:
            updated_members.append(member.model_dump())
            replaced = True
        else:
            updated_members.append(item)
    if not replaced:
        return None
    refreshed_assembly = {
        **assembly,
        "updated_at": _utc_now_iso(),
        "members": updated_members,
        "summary": _assembly_summary_from_raw(updated_members, assembly.get("budget_profile")),
    }
    project = store.get_project(project_id)
    if project is None:
        return None
    return store.update_project(
        project_id,
        UpdateProjectRequest(
            metadata={
                **dict(project.metadata),
                "team_assembly": refreshed_assembly,
            },
        ),
    )


def _assembly_summary_from_raw(
    raw_members: list[Any],
    budget_profile: Any,
) -> dict[str, Any]:
    members = [
        item for item in raw_members
        if isinstance(item, dict)
    ]
    matched = [m for m in members if m.get("status") == "matched"]
    human = [
        m for m in members
        if m.get("kind") == "human" or m.get("status") == "requires_human"
    ]
    digital_twins = [m for m in members if m.get("kind") == "digital_twin"]
    total_cost = sum(_monthly_cost_number(str(m.get("monthly_cost") or "")) for m in members)
    profile = budget_profile if isinstance(budget_profile, dict) else {}
    return {
        "total_slots": len(members),
        "matched_agents": len(matched),
        "human_roles": len(human),
        "digital_twins": len(digital_twins),
        "estimated_monthly_cost": total_cost,
        "budget_tier": profile.get("tier") or profile.get("label") or "",
    }


def _monthly_cost_number(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def _materialized_existing_response(
    *,
    project: dict[str, Any],
    member: ProjectTeamAssemblyMember,
    registry: Any,
) -> MaterializeTeamAssemblyMemberResponse:
    from runtime.execution.agents.loader import default_agents_root

    agent_id = member.source_agent_id or ""
    hot_loaded = bool(registry is not None and hasattr(registry, "has") and registry.has(agent_id))
    display_name = member.source_agent_name or member.display_name or agent_id
    identity_card = _member_identity_card(member)
    return MaterializeTeamAssemblyMemberResponse(
        project=project,
        member=member,
        agent=MaterializedAgentWire(
            id=agent_id,
            name=display_name,
            description=member.responsibility,
            agent_dir=str(default_agents_root() / agent_id),
            identity_card=identity_card,
        ),
        created=False,
        hot_loaded=hot_loaded,
        requires_reload=not hot_loaded,
    )


def _member_identity_card(member: ProjectTeamAssemblyMember) -> dict[str, Any]:
    raw = member.metadata.get("identity_card")
    if isinstance(raw, dict):
        return raw
    materialized = member.metadata.get("materialized")
    if isinstance(materialized, dict):
        nested = materialized.get("identity_card")
        if isinstance(nested, dict):
            return nested
    return {}


def _mark_member_materialized(
    member: ProjectTeamAssemblyMember,
    *,
    agent_id: str,
    display_name: str,
    hot_loaded: bool,
    agent_dir: Path,
    identity_card: dict[str, Any],
) -> ProjectTeamAssemblyMember:
    metadata = {
        **dict(member.metadata),
        "identity_card": identity_card,
        "materialized": {
            "agent_id": agent_id,
            "agent_dir": str(agent_dir),
            "hot_loaded": hot_loaded,
            "created_at": _utc_now_iso(),
            "identity_card": identity_card,
        },
    }
    return ProjectTeamAssemblyMember.model_validate({
        **member.model_dump(),
        "status": "matched",
        "source_agent_id": agent_id,
        "source_agent_name": display_name,
        "source_agent_category": member.kind,
        "match_score": max(member.match_score, 100),
        "installed_skills": list(dict.fromkeys([
            *member.installed_skills,
            *_materialized_agent_private_skills(member),
        ])),
        "arms": list(dict.fromkeys([
            *member.arms,
            *_materialized_agent_tool_groups(member),
        ])),
        "metadata": metadata,
    })


def _materialized_agent_id(project_id: str, member: ProjectTeamAssemblyMember) -> str:
    base = _ascii_slug(member.role or member.display_name or member.slot_id)
    if not base:
        base = _ascii_slug(member.slot_id) or "role"
    prefix = "twin" if member.kind == "digital_twin" else "agent"
    suffix = _ascii_slug(project_id)[-8:] or "project"
    return f"company_{suffix}_{prefix}_{base}"[:64].rstrip("_-")


def _ascii_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip().lower())
    return re.sub(r"_+", "_", slug).strip("_-")


def _materialized_template_id(member: ProjectTeamAssemblyMember) -> str:
    if member.kind == "digital_twin":
        return "digital-twin"
    haystack = " ".join([
        member.role,
        member.display_name,
        member.responsibility,
        *member.skills,
    ]).lower()
    if "research" in haystack or "market" in haystack or "web" in haystack:
        return "knowledge-search"
    if "data" in haystack or "analysis" in haystack:
        return "data-analyst"
    if "plan" in haystack or "budget" in haystack:
        return "exec-assistant"
    return "team-qa"


def _materialized_agent_description(
    project: dict[str, Any],
    member: ProjectTeamAssemblyMember,
) -> str:
    parts = [
        f"Company project role: {member.display_name or member.role}.",
        f"Project: {project.get('name') or project.get('id')}.",
    ]
    if member.responsibility:
        parts.append(f"Responsibility: {member.responsibility}")
    if member.level:
        parts.append(f"Level: {member.level}.")
    return " ".join(parts)


def _materialized_identity_card(
    project: dict[str, Any],
    member: ProjectTeamAssemblyMember,
    *,
    agent_id: str,
    display_name: str,
) -> dict[str, Any]:
    seed = f"{project.get('id')}::{member.id}::{agent_id}"
    created_at = _utc_now_iso()
    birth_date = _persona_birth_date(seed)
    mbti = _seeded_choice(seed, ["INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "ENFJ", "ISTJ", "ESTJ"])
    temperament = _seeded_choice(
        seed + ":temperament",
        ["strategic", "analytical", "operator", "connector", "reviewer", "builder"],
    )
    return {
        "identity_number": f"HA-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:10].upper()}",
        "agent_id": agent_id,
        "display_name": display_name,
        "kind": member.kind,
        "role": member.role,
        "level": member.level or _capability_band(member.capability_score),
        "capability_score": member.capability_score,
        "monthly_cost": member.monthly_cost,
        "project_id": project.get("id"),
        "project_name": project.get("name"),
        "born_at": created_at,
        "persona_birth_date": birth_date,
        "western_zodiac": _western_zodiac(birth_date),
        "chinese_zodiac": _chinese_zodiac(int(birth_date[:4])),
        "mbti_seed": mbti,
        "temperament": temperament,
        "skill_pack": _materialized_agent_private_skills(member),
        "tool_pack": _materialized_agent_tool_groups(member),
        "responsibility": member.responsibility,
        "growth_stage": "initialized",
        "evolution_points": 0,
    }


def _persona_birth_date(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    year = 1990 + int(digest[:2], 16) % 31
    month = 1 + int(digest[2:4], 16) % 12
    day = 1 + int(digest[4:6], 16) % 28
    return f"{year:04d}-{month:02d}-{day:02d}"


def _seeded_choice(seed: str, choices: list[str]) -> str:
    index = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)
    return choices[index % len(choices)]


def _western_zodiac(date_text: str) -> str:
    month = int(date_text[5:7])
    day = int(date_text[8:10])
    cutoffs = [
        ((1, 20), "Capricorn"), ((2, 19), "Aquarius"), ((3, 21), "Pisces"),
        ((4, 20), "Aries"), ((5, 21), "Taurus"), ((6, 22), "Gemini"),
        ((7, 23), "Cancer"), ((8, 23), "Leo"), ((9, 23), "Virgo"),
        ((10, 24), "Libra"), ((11, 23), "Scorpio"), ((12, 22), "Sagittarius"),
    ]
    for (cutoff_month, cutoff_day), previous in cutoffs:
        if (month, day) < (cutoff_month, cutoff_day):
            return previous
    return "Capricorn"


def _chinese_zodiac(year: int) -> str:
    animals = [
        "Rat", "Ox", "Tiger", "Rabbit", "Dragon", "Snake",
        "Horse", "Goat", "Monkey", "Rooster", "Dog", "Pig",
    ]
    return animals[(year - 2020) % 12]


def _capability_band(score: int) -> str:
    if score >= 90:
        return "expert"
    if score >= 75:
        return "senior"
    if score >= 55:
        return "mid"
    return "junior"


def _materialized_agent_soul(
    project: dict[str, Any],
    member: ProjectTeamAssemblyMember,
    identity_card: dict[str, Any],
) -> str:
    skills = ", ".join(member.skills[:8]) or "project collaboration"
    return f"""# Soul

You are {member.display_name or member.role}, a company project collaborator in Octopus.

## Project Context

- Project: {project.get("name") or project.get("id")}
- Identity number: {identity_card.get("identity_number")}
- Role: {member.role}
- Level: {member.level or "adaptive"}
- Persona seed: {identity_card.get("mbti_seed")} · {identity_card.get("temperament")}
- Responsibility: {member.responsibility or "Help move the project forward with concrete work."}
- Core skills: {skills}

## Operating Style

- Work proactively from the current milestone and budget constraints.
- Ask for missing business context only when it blocks execution.
- Produce concrete artifacts, decisions, risks, and next actions.
- Stay aligned with the team room and hand off work clearly.

---

_This identity was materialized from a Company Workbench team assembly slot._
"""


def _materialized_role_contract(
    project: dict[str, Any],
    member: ProjectTeamAssemblyMember,
    identity_card: dict[str, Any],
) -> str:
    skills = "\n".join(f"- {skill}" for skill in identity_card.get("skill_pack", [])) or "- project_collaboration"
    tools = "\n".join(f"- {tool}" for tool in identity_card.get("tool_pack", [])) or "- none"
    return f"""# Company Role Contract

## Identity

- Identity number: {identity_card.get("identity_number")}
- Agent ID: {identity_card.get("agent_id")}
- Display name: {identity_card.get("display_name")}
- Kind: {identity_card.get("kind")}
- Role: {identity_card.get("role")}
- Level: {identity_card.get("level")}
- Monthly cost: {identity_card.get("monthly_cost") or "unpriced"}

## Persona Seed

- Born at: {identity_card.get("born_at")}
- Persona birth date: {identity_card.get("persona_birth_date")}
- MBTI seed: {identity_card.get("mbti_seed")}
- Western zodiac: {identity_card.get("western_zodiac")}
- Chinese zodiac: {identity_card.get("chinese_zodiac")}
- Temperament: {identity_card.get("temperament")}

## Project Assignment

- Project: {project.get("name") or project.get("id")}
- Responsibility: {member.responsibility or "Help move the project forward."}

## Skill Pack

{skills}

## Tool Pack

{tools}

## Growth

- Growth stage: {identity_card.get("growth_stage")}
- Evolution points: {identity_card.get("evolution_points")}

This file is the stable company-facing contract for the agent. Update it only when the role, value, skill pack, or project assignment changes.
"""


def _materialized_agent_tool_groups(member: ProjectTeamAssemblyMember) -> list[str]:
    haystack = " ".join([
        member.role,
        member.display_name,
        member.responsibility,
        *member.skills,
    ]).lower()
    arms: list[str] = []
    if any(token in haystack for token in ("research", "market", "web", "evidence")):
        arms.append("web_read")
    if any(token in haystack for token in ("write", "artifact", "report", "plan", "gantt", "file")):
        arms.append("fs_writer")
    if member.kind == "digital_twin" and "web_read" not in arms:
        arms.append("web_read")
    return list(dict.fromkeys(arms))


def _materialized_agent_private_skills(member: ProjectTeamAssemblyMember) -> list[str]:
    skills = [
        skill.strip()
        for skill in [*member.skills, *member.installed_skills]
        if skill.strip()
    ]
    if member.kind == "digital_twin":
        skills.extend(["domain_judgement", "human_context_review"])
    return list(dict.fromkeys(skills))


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _team_members_for_project(project: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = project.get("metadata")
    assembly = metadata.get("team_assembly") if isinstance(metadata, dict) else None
    raw_members = assembly.get("members") if isinstance(assembly, dict) else None
    if not isinstance(raw_members, list):
        return _default_team_members()

    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_members:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "matched":
            continue
        agent_id = str(item.get("source_agent_id") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        display_name = str(
            item.get("source_agent_name")
            or item.get("display_name")
            or agent_id,
        )
        responsibility = str(item.get("responsibility") or "").strip()
        role = str(item.get("display_name") or item.get("role") or "").strip()
        description = " · ".join(
            part for part in (role, responsibility) if part
        ) or f"Assembled company project agent: {agent_id}"
        members.append({
            "name": agent_id,
            "display_name": display_name,
            "description": description,
        })

    if not members:
        return _default_team_members()
    if "general" not in seen:
        members.insert(0, _default_team_members()[0])
    return members


def _default_team_members() -> list[dict[str, Any]]:
    return [
        {
            "name": "general",
            "display_name": "General",
            "description": "Coordinates the project and asks for missing context.",
        },
        {
            "name": "planner",
            "display_name": "Planner",
            "description": "Breaks goals into milestones, dependencies, and budgets.",
        },
        {
            "name": "researcher",
            "display_name": "Researcher",
            "description": "Collects market, technical, and operational evidence.",
        },
        {
            "name": "implementer",
            "display_name": "Implementer",
            "description": "Turns plans into concrete drafts, files, and actions.",
        },
        {
            "name": "reviewer",
            "display_name": "Reviewer",
            "description": "Checks risks, gaps, quality, and decision readiness.",
        },
        {
            "name": "synthesizer",
            "display_name": "Synthesizer",
            "description": "Combines outputs into reports and next actions.",
        },
    ]


__all__ = ["create_company_router"]

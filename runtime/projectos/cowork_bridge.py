"""Run a Project OS project on a custom cowork group.

The 4 roles (PM/Engineer/Research/QA) are only the *default* routing. When you
freely pull members into a cowork thread, those members become the project team:
this bridge turns the thread's roster into the agent pool and routes each task to
the best-fit member (nominate: relevance × past competence) instead of a fixed
role. So "assemble a group, then turn on project mode" just works — any roster.
"""

from __future__ import annotations

from typing import Any

from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.nominate import CompetenceStore, suggest
from runtime.projectos.engine import (
    AgentAssigner,
    ProjectEngine,
    _default_assign,
    stub_decompose_tasks,
    stub_generate_milestones,
)
from runtime.projectos.model import Task
from runtime.projectos.store import ProjectStore


def roster_from_group(group_store: GroupStore, thread_id: str) -> list[tuple[str, str]]:
    """The group's participant agents as (agent_id, family) candidates. Humans and
    observers are excluded — they don't auto-execute tasks."""
    state = group_store.state(thread_id)
    return [
        (m.id, m.id)  # roster only knows ids; the id doubles as the domain token
        for m in state.roster
        if m.kind == "agent" and m.role == "participant" and not m.muted
    ]


def nominate_assigner(
    roster: list[tuple[str, str]], competence: CompetenceStore | None = None
) -> AgentAssigner:
    """An assigner that routes each task to the best-fit *group member*.

    Ranks the roster for the task's goal (keyword relevance, boosted by recorded
    competence); falls back to the first member, then to role routing if the
    group has no agents. Always prefers a real member over a fixed role."""

    def _assign(task: Task) -> str:
        if not roster:
            return _default_assign(task)
        ranked = suggest(task.goal, roster, competence)
        if ranked:
            return str(ranked[0]["agent_id"])
        return roster[0][0]  # no keyword match → still keep it in the group

    return _assign


def engine_for_group(
    project_store: ProjectStore,
    group_store: GroupStore,
    thread_id: str,
    *,
    hooks: dict[str, Any] | None = None,
    competence: CompetenceStore | None = None,
) -> ProjectEngine:
    """A ProjectEngine whose task→agent routing uses the cowork thread's roster.

    ``hooks`` supplies generate/decompose/execute/qa (LLM in production, stubs in
    tests). The assigner is always the roster-aware one, so the custom group runs
    the project."""
    roster = roster_from_group(group_store, thread_id)
    kwargs = dict(hooks or {})
    kwargs.setdefault("generate_milestones", stub_generate_milestones)
    kwargs.setdefault("decompose_tasks", stub_decompose_tasks)
    kwargs["assign_agent"] = nominate_assigner(roster, competence)
    return ProjectEngine(project_store, **kwargs)


def full_project_state(project_store: ProjectStore, project_id: str) -> dict[str, Any] | None:
    """Return the complete Project OS read-model for API and realtime callers."""
    project = project_store.get_project(project_id)
    if project is None:
        return None
    milestones = project_store.milestones_for(project_id)
    tasks_by_ms = {
        milestone.id: [
            _task_read_model(project.id, task)
            for task in project_store.tasks_for_milestone(milestone.id)
        ]
        for milestone in milestones
    }
    return {
        "project": project.to_dict(),
        "milestones": [milestone.to_dict() for milestone in milestones],
        "tasks": tasks_by_ms,
        "available_actions": _project_available_actions(project.status),
        "action_specs": _project_action_specs(project.id, project.status),
    }


def _project_available_actions(status: str) -> list[str]:
    if status == "blocked":
        return ["recover", "recover_and_run"]
    if status in {"planning", "running"}:
        return ["run", "tick"]
    if status == "done":
        return ["inspect", "report"]
    return ["inspect"]


def _project_action_specs(project_id: str, status: str) -> list[dict[str, Any]]:
    specs = {
        "recover": {
            "action": "recover",
            "label": "Recover",
            "api": {
                "method": "POST",
                "path": f"/api/projects/{project_id}/recover",
                "body": {"run": False},
            },
            "realtime_command": "/project recover",
        },
        "recover_and_run": {
            "action": "recover_and_run",
            "label": "Recover and run",
            "api": {
                "method": "POST",
                "path": f"/api/projects/{project_id}/recover",
                "body": {"run": True},
            },
            "realtime_command": "/project recover run",
        },
        "run": {
            "action": "run",
            "label": "Run",
            "api": {
                "method": "POST",
                "path": f"/api/projects/{project_id}/run",
                "body": {"max_ticks": 50},
            },
        },
        "tick": {
            "action": "tick",
            "label": "Tick",
            "api": {"method": "POST", "path": f"/api/projects/{project_id}/tick"},
        },
        "inspect": {
            "action": "inspect",
            "label": "Inspect",
            "api": {"method": "GET", "path": f"/api/projects/{project_id}"},
        },
        "report": {
            "action": "report",
            "label": "Report",
            "api": {"method": "GET", "path": f"/api/projects/{project_id}/report"},
        },
    }
    return [specs[action] for action in _project_available_actions(status)]


def _task_read_model(project_id: str, task: Task) -> dict[str, Any]:
    raw = task.to_dict()
    raw["available_actions"] = _task_available_actions(task.status)
    raw["action_specs"] = _task_action_specs(project_id, task)
    return raw


def _task_available_actions(status: str) -> list[str]:
    if status in {"failed", "rejected", "blocked"}:
        return ["reassign", "reset", "complete", "skip"]
    if status in {"pending", "ready"}:
        return ["reassign", "reset", "complete", "skip"]
    if status == "running":
        return ["reassign", "reset"]
    if status == "done":
        return ["reset"]
    return ["inspect"]


def _task_action_specs(project_id: str, task: Task) -> list[dict[str, Any]]:
    specs = {
        "reassign": {
            "action": "reassign",
            "label": "Reassign",
            "api": {
                "method": "POST",
                "path": f"/api/projects/{project_id}/tasks/{task.id}/intervene",
                "body": {"action": "reassign", "assigned_agent": ""},
            },
            "realtime_command": f"/project task {task.id} reassign agent=<agent-id>",
            "requires": ["assigned_agent"],
        },
        "reset": {
            "action": "reset",
            "label": "Reset",
            "api": {
                "method": "POST",
                "path": f"/api/projects/{project_id}/tasks/{task.id}/intervene",
                "body": {"action": "reset", "cascade": True},
            },
            "realtime_command": f"/project task {task.id} reset",
        },
        "complete": {
            "action": "complete",
            "label": "Complete",
            "api": {
                "method": "POST",
                "path": f"/api/projects/{project_id}/tasks/{task.id}/intervene",
                "body": {"action": "complete", "output": ""},
            },
            "realtime_command": f'/project task {task.id} complete output="<result>"',
            "requires": ["output"],
        },
        "skip": {
            "action": "skip",
            "label": "Skip",
            "api": {
                "method": "POST",
                "path": f"/api/projects/{project_id}/tasks/{task.id}/intervene",
                "body": {"action": "skip", "reason": ""},
            },
            "realtime_command": f'/project task {task.id} skip reason="<reason>"',
        },
        "inspect": {
            "action": "inspect",
            "label": "Inspect",
        },
    }
    return [specs[action] for action in _task_available_actions(task.status)]


def project_run_trace(
    *,
    thread_id: str,
    roster: list[str],
    reused: bool,
    result: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Compact audit trace for Project OS runs over a cowork group."""
    project = state.get("project") if isinstance(state.get("project"), dict) else {}
    milestones = state.get("milestones") if isinstance(state.get("milestones"), list) else []
    tasks_by_ms = state.get("tasks") if isinstance(state.get("tasks"), dict) else {}
    history = result.get("history") if isinstance(result.get("history"), list) else []
    tick_events: list[dict[str, Any]] = []
    for index, tick in enumerate(history, start=1):
        if not isinstance(tick, dict):
            continue
        tick_events.append(
            {
                "tick": index,
                "project_status": tick.get("project_status"),
                "current_ms": tick.get("current_ms"),
                "events": [
                    str(event)
                    for event in (tick.get("events") or [])
                    if str(event or "").strip()
                ],
            }
        )

    milestone_summaries: list[dict[str, Any]] = []
    for milestone in milestones:
        if not isinstance(milestone, dict):
            continue
        ms_id = str(milestone.get("id") or "")
        tasks = tasks_by_ms.get(ms_id) if isinstance(tasks_by_ms, dict) else []
        tasks = tasks if isinstance(tasks, list) else []
        milestone_summaries.append(
            {
                "id": ms_id,
                "name": milestone.get("name"),
                "status": milestone.get("status"),
                "task_count": len(tasks),
                "done_task_count": sum(
                    1 for task in tasks
                    if isinstance(task, dict) and task.get("status") == "done"
                ),
                "assignments": [
                    {
                        "task_id": task.get("id"),
                        "type": task.get("type"),
                        "status": task.get("status"),
                        "assigned_agent": task.get("assigned_agent"),
                        "available_actions": task.get("available_actions") or [],
                    }
                    for task in tasks
                    if isinstance(task, dict)
                ],
            }
        )

    return {
        "schema": "octopus.projectos.run_trace.v1",
        "thread_id": thread_id,
        "project_id": project.get("id"),
        "project_name": project.get("name"),
        "project_status": result.get("final_status") or project.get("status"),
        "reused": reused,
        "roster": roster,
        "tick_count": result.get("ticks", len(tick_events)),
        "tick_events": tick_events,
        "milestones": milestone_summaries,
    }


def run_project_from_group(
    project_store: ProjectStore,
    group_store: GroupStore,
    thread_id: str,
    *,
    name: str,
    goal: str,
    hooks: dict[str, Any] | None = None,
    run: bool = True,
    max_ticks: int = 50,
    competence: CompetenceStore | None = None,
    actor: str = "project-os",
    reuse_active: bool = False,
) -> dict[str, Any]:
    """Create a Project OS project from a cowork group and optionally run it.

    This is the shared contract for the HTTP `/api/projects/from-group/*` route
    and the realtime project-mode turn. Keeping both surfaces on one helper
    prevents the product from having two subtly different meanings of
    "project mode".
    """
    from runtime.memory.cowork.service import set_mode

    roster = [agent_id for agent_id, _ in roster_from_group(group_store, thread_id)]
    if not roster:
        raise ValueError("group has no participant agents to staff the project")

    # Project execution is a collaboration mode of the group; reflect the
    # state transition before planning so subsequent realtime turns see it.
    set_mode(group_store, thread_id, actor=actor, mode="project")
    engine = engine_for_group(
        project_store,
        group_store,
        thread_id,
        hooks=hooks,
        competence=competence,
    )
    project = project_store.project_for_thread(thread_id) if reuse_active else None
    reused = bool(project is not None and project.status not in {"done", "failed"})
    if not reused:
        project = engine.plan(name, goal)
        project_store.bind_thread(thread_id, project.id)
    result = (
        engine.run(project.id, max_ticks=max_ticks)
        if run
        else {"final_status": project.status}
    )
    state = full_project_state(project_store, project.id)
    if state is None:
        raise RuntimeError(f"project disappeared after planning: {project.id}")
    trace = project_run_trace(
        thread_id=thread_id,
        roster=roster,
        reused=reused,
        result=result,
        state=state,
    )
    return {
        "ok": True,
        "roster": roster,
        "result": result,
        "reused": reused,
        "trace": trace,
        **state,
    }

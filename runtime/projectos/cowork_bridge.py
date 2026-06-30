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
    return {
        "project": project.to_dict(),
        "milestones": [milestone.to_dict() for milestone in milestones],
        "tasks": {
            milestone.id: [
                task.to_dict()
                for task in project_store.tasks_for_milestone(milestone.id)
            ]
            for milestone in milestones
        },
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
    return {"ok": True, "roster": roster, "result": result, "reused": reused, **state}

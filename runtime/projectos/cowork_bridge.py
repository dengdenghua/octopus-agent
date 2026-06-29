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
from runtime.projectos.engine import AgentAssigner, ProjectEngine, _default_assign
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
    kwargs["assign_agent"] = nominate_assigner(roster, competence)
    return ProjectEngine(project_store, **kwargs)

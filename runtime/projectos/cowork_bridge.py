"""Run a Project OS project on a custom cowork group.

The 4 roles (PM/Engineer/Research/QA) are only the *default* routing. When you
freely pull members into a cowork thread, those members become the project team:
this bridge turns the thread's roster into the agent pool and routes each task to
the best-fit member (nominate: relevance × past competence) instead of a fixed
role. So "assemble a group, then turn on project mode" just works — any roster.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.nominate import CompetenceStore, suggest
from runtime.projectos.engine import (
    DEFAULT_RUN_MAX_TICKS,
    AgentAssigner,
    ProjectEngine,
    _default_assign,
    normalize_run_ticks,
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


def _compose_swarm_output(result: dict[str, Any], prompt: str) -> str:
    """Turn a group_fanout result into a project-task deliverable: the primary
    reply + supporting angles, labeled so the QA gate sees who said what."""
    synthesis = result.get("synthesis") if isinstance(result.get("synthesis"), dict) else {}
    primary = str(synthesis.get("primary_reply") or "").strip()
    support = [
        r for r in (result.get("replies") or [])
        if isinstance(r, dict) and r.get("ok") and str(r.get("reply") or "").strip()
    ]
    if not primary and not support:
        return "[swarm] 无人回应"
    lines = [f"# 蜂群交付 · {prompt[:80]}", ""]
    if primary:
        lines.append(f"**主要观点（{synthesis.get('primary_agent_id') or '?'}）**\n{primary}")
        lines.append("")
    if len(support) > 1:
        lines.append("**支撑角度**")
        for r in support:
            who = str(r.get("display_name") or r.get("agent_id") or "?")
            body = str(r.get("reply") or "").strip()
            if body and r.get("agent_id") != synthesis.get("primary_agent_id"):
                lines.append(f"- {who}: {body[:800]}")
    return "\n".join(lines)


def _compose_cluster_output(result: Any, prompt: str) -> str:
    final = str(getattr(result, "final_output", "") or "").strip()
    if final:
        return f"# 集群交付\n{final}"
    return "[cluster] 团队流水线未产出可交付内容"


def team_execute_for_group(
    roster: list[tuple[str, str]],
    *,
    agent_caller: Callable[[str, str, int], dict[str, Any]] | None = None,
    debate_rounds: int = 2,
) -> Callable[[Task, dict[str, Any]], Any]:
    """ProjectEngine.run_task_team hook: execute a project task node as a team.

    - ``swarm`` (蜂群) → ``run_group_fanout`` over the roster, optional debate
      rounds, arbitration synthesis as the deliverable.
    - ``cluster`` (集群) → ``TeamRunner`` parallel pipeline: the roster becomes
      the researcher pool, the assigned agent becomes the synthesizer.

    This is the seam that lets 项目模式 reuse the cluster/swarm engines we
    optimized instead of running every project task single-agent.
    """
    members = [{"name": mid, "display_name": mid} for mid, _ in roster]
    ids = [mid for mid, _ in roster]

    def _call_agent(agent_id: str, prompt: str, timeout_s: int = 300) -> dict[str, Any]:
        if agent_caller is not None:
            return agent_caller(agent_id, prompt, timeout_s)
        from runtime.execution.subagents import call_subagent

        try:
            result = call_subagent(
                agent_id,
                prompt,
                context={"source": "projectos_team_task"},
                timeout_s=timeout_s,
                timeout_seconds=float(timeout_s),
            )
            return {
                "success": bool(result.get("success")),
                "output": str(result.get("output") or result.get("parsed") or ""),
                "error": result.get("error"),
            }
        except Exception as exc:  # noqa: BLE001 — isolate one member's failure
            return {
                "success": False,
                "output": "",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _run(task: Task, context: dict[str, Any]) -> Any:
        prompt = task.goal
        milestone_goal = context.get("milestone_goal")
        if milestone_goal:
            prompt = f"Milestone: {milestone_goal}\nTask: {task.goal}"
        if task.team_mode == "swarm":
            return _run_swarm(prompt)
        return _run_cluster(task, prompt)

    def _run_swarm(prompt: str) -> str:
        from runtime.execution.agents.group_fanout import run_group_fanout

        n = max(1, len(members))
        result = run_group_fanout(
            prompt,
            members,
            agent_caller=_call_agent,
            max_members=n,
            max_concurrency=min(32, n),
            scale_mode="safe",
            debate_rounds=debate_rounds,
        )
        return _compose_swarm_output(result, prompt)

    def _run_cluster(task: Task, prompt: str) -> str:
        if not ids:
            raise RuntimeError("project cluster task needs at least one roster member")
        from runtime.safety.organization import (
            AgentSpec,
            CoordinationProtocol,
            Role,
            TeamTopology,
        )
        from runtime.safety.organization.team_runner import TeamRunner

        pool_id = ids[0]
        synth_id = task.assigned_agent or pool_id
        topology = TeamTopology(
            name="project-cluster",
            protocol=CoordinationProtocol.PARALLEL,
            agents={
                # The assigned (best-fit) member leads: plans the task, then
                # merges the pool into the deliverable. Same agent runs both
                # roles (plan → pool → synthesize), which is the "cluster" feel.
                Role.PLANNER: AgentSpec(agent_id=synth_id),
                # The whole roster is the researcher pool (one replica per member).
                Role.RESEARCHER: AgentSpec(agent_id=pool_id, parallel_replicas=len(ids)),
                Role.SYNTHESIZER: AgentSpec(agent_id=synth_id),
            },
        )

        def _role_caller(
            *,
            agent_id: str,
            prompt: str,
            context: dict[str, Any] | None = None,
            timeout_seconds: int | None = None,
            use_cheap_model: bool = False,
            event_emitter: Callable[[dict[str, Any]], None] | None = None,
        ) -> dict[str, Any]:
            role = (context or {}).get("team_role")
            idx = (context or {}).get("team_replica_index")
            actual = agent_id
            if role == "researcher" and isinstance(idx, int) and 1 <= idx <= len(ids):
                actual = ids[idx - 1]
            return _call_agent(actual, prompt, timeout_s=timeout_seconds or 300)

        runner = TeamRunner(role_caller=_role_caller, timeout_seconds=900)
        return _compose_cluster_output(runner.run(topology, prompt), prompt)

    return _run


def engine_for_group(
    project_store: ProjectStore,
    group_store: GroupStore,
    thread_id: str,
    *,
    hooks: dict[str, Any] | None = None,
    competence: CompetenceStore | None = None,
    owner_id: str = "",
    tenant_id: str = "",
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
    # 项目模式 × 集群/蜂群：有可执行成员时注入任务级团队执行器，让声明了
    # team_mode 的任务节点跑成蜂群/集群，而不是一律单 agent。
    if roster:
        kwargs["run_task_team"] = team_execute_for_group(roster)
    return ProjectEngine(
        project_store,
        **kwargs,
        owner_id=owner_id,
        tenant_id=tenant_id,
    )


def ensure_project_for_thread(
    project_store: ProjectStore,
    group_store: GroupStore,
    thread_id: str,
    *,
    name: str,
    goal: str,
    owner_id: str = "",
    tenant_id: str = "",
) -> str | None:
    """Create (if missing) a Project OS project bound to a cowork thread.

    Returns the project_id (existing or freshly planned), or ``None`` when the
    group has no participant agents to staff it. Used by the cowork mode switch
    so entering "project" mode always has a real project for the workbench 项目
    tab to render. Planning uses stub/deterministic hooks (no LLM call); actual
    execution stays user-triggered via Run/Tick so a mere mode switch never
    auto-runs a project.
    """
    roster = [a for a, _ in roster_from_group(group_store, thread_id)]
    if not roster:
        return None
    existing = project_store.project_for_thread(thread_id)
    if existing is not None:
        return existing.id
    engine = engine_for_group(
        project_store,
        group_store,
        thread_id,
        owner_id=owner_id,
        tenant_id=tenant_id,
    )
    project = engine.plan(name or "当前项目", goal or name or "当前目标")
    project_store.bind_thread(thread_id, project.id)
    return project.id


def full_project_state(project_store: ProjectStore, project_id: str) -> dict[str, Any] | None:
    """Return the complete Project OS read-model for API and realtime callers.

    Includes the derived PM console (``pm``) — milestone health, burndown,
    risks/blockers, next actions, assignments — plus a ``retro`` once the
    project reaches a terminal state.
    """
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
    from runtime.projectos.pm import build_pm_report, build_retro

    pm = build_pm_report(project_store, project_id)
    retro = (
        build_retro(project_store, project_id)
        if project.status in ("done", "failed")
        else None
    )
    return {
        "project": project.to_dict(),
        "milestones": [milestone.to_dict() for milestone in milestones],
        "tasks": tasks_by_ms,
        "pm": pm,
        "retro": retro,
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
                "body": {"max_ticks": DEFAULT_RUN_MAX_TICKS},
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
                    str(event) for event in (tick.get("events") or []) if str(event or "").strip()
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
                    1 for task in tasks if isinstance(task, dict) and task.get("status") == "done"
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
    max_ticks: int = DEFAULT_RUN_MAX_TICKS,
    competence: CompetenceStore | None = None,
    actor: str = "project-os",
    reuse_active: bool = False,
    owner_id: str = "",
    tenant_id: str = "",
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
        owner_id=owner_id,
        tenant_id=tenant_id,
    )
    project = project_store.project_for_thread(thread_id) if reuse_active else None
    reused = bool(project is not None and project.status not in {"done", "failed"})
    if not reused:
        project = engine.plan(name, goal)
        project_store.bind_thread(thread_id, project.id)
    result = (
        engine.run(project.id, max_ticks=normalize_run_ticks(max_ticks))
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
    project_store.append_event(
        project.id,
        kind="project.run_from_group",
        payload={
            "thread_id": thread_id,
            "roster": roster,
            "reused": reused,
            "run": run,
            "max_ticks": normalize_run_ticks(max_ticks),
            "trace": trace,
        },
    )
    return {
        "ok": True,
        "roster": roster,
        "result": result,
        "reused": reused,
        "trace": trace,
        **state,
    }

"""Project OS on a custom cowork group: roles aren't fixed — your pulled-in
members become the team and tasks route to them by capability."""

from __future__ import annotations

import sqlite3

import pytest

from runtime.memory.cowork import service
from runtime.memory.cowork.group import MemberEvent
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.session import link_room
from runtime.projectos import cowork_bridge
from runtime.projectos.cowork_bridge import (
    engine_for_group,
    nominate_assigner,
    roster_from_group,
    run_project_from_group,
    team_execute_for_group,
)
from runtime.projectos.engine import stub_decompose_tasks, stub_generate_milestones
from runtime.projectos.model import Milestone, Task
from runtime.projectos.store import ProjectStore
from runtime.projectos.timeline import project_process_timeline


def _attached_group(tmp_path):
    group_store = GroupStore(base_dir=tmp_path / "cowork")
    service.invite_member(
        group_store,
        "thread-attach-failure",
        actor="owner",
        target_id="planner",
        kind="agent",
    )
    service.set_mode(
        group_store,
        "thread-attach-failure",
        actor="owner",
        mode="swarm",
    )
    link_room(
        group_store,
        "thread-attach-failure",
        "room-existing",
        actor="owner",
    )
    return group_store


def _project_table_counts(store: ProjectStore) -> dict[str, int]:
    with sqlite3.connect(str(store._db)) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "projects",
                "milestones",
                "tasks",
                "thread_projects",
                "project_events",
            )
        }


def test_roster_excludes_humans_observers_muted(tmp_path) -> None:
    gs = GroupStore(base_dir=tmp_path)
    service.invite_member(gs, "t", actor="u", target_id="db-agent", kind="agent")
    service.invite_member(gs, "t", actor="u", target_id="me", kind="human")
    service.invite_member(gs, "t", actor="u", target_id="watcher", kind="agent", role="observer")
    service.invite_member(gs, "t", actor="u", target_id="ui-agent", kind="agent")
    gs.append("t", MemberEvent(action="mute", actor="u", target_id="ui-agent"))
    ids = {a for a, _ in roster_from_group(gs, "t")}
    assert ids == {"db-agent"}  # human/observer/muted all excluded


def test_assigner_routes_to_best_member() -> None:
    # Agents are named for their domain (matching is by 3+ char id tokens).
    roster = [("database-expert", "database-expert"), ("frontend-designer", "frontend-designer")]
    assign = nominate_assigner(roster)
    assert (
        assign(Task(id="T", milestone_id="M", type="code", goal="optimize database index"))
        == "database-expert"
    )
    assert (
        assign(Task(id="T", milestone_id="M", type="design", goal="design the frontend layout"))
        == "frontend-designer"
    )
    # no keyword match → still a group member (not a fixed role)
    assert assign(Task(id="T", milestone_id="M", type="code", goal="zzz")) in {
        "database-expert",
        "frontend-designer",
    }


def test_empty_roster_falls_back_to_role() -> None:
    assign = nominate_assigner([])
    assert assign(Task(id="T", milestone_id="M", type="research", goal="x")) == "research"


def test_project_runs_on_custom_group(tmp_path) -> None:
    gs = GroupStore(base_dir=tmp_path)
    for a in ("database-expert", "frontend-designer", "qa-bot"):
        service.invite_member(gs, "thread-1", actor="u", target_id=a, kind="agent")

    def decompose(ms: Milestone) -> list[Task]:
        return [
            Task(id=f"{ms.id}-T1", milestone_id=ms.id, type="code", goal="database schema work"),
            Task(
                id=f"{ms.id}-T2",
                milestone_id=ms.id,
                type="design",
                goal="frontend screens design",
                depends_on=[f"{ms.id}-T1"],
            ),
        ]

    eng = engine_for_group(
        ProjectStore(base_dir=tmp_path),
        gs,
        "thread-1",
        hooks={"generate_milestones": stub_generate_milestones, "decompose_tasks": decompose},
    )
    p = eng.plan("custom", "build an app")
    eng.run(p.id, max_ticks=50)

    # every task was assigned to an ACTUAL group member, by capability
    pool = {a for a, _ in roster_from_group(gs, "thread-1")}
    for m in eng.store.milestones_for(p.id):
        for t in eng.store.tasks_for_milestone(m.id):
            assert t.assigned_agent in pool
    # the db task went to the db member, the ui task to the ui member
    ms1_tasks = {t.goal: t.assigned_agent for t in eng.store.tasks_for_milestone("MS1")}
    assert ms1_tasks["database schema work"] == "database-expert"
    assert ms1_tasks["frontend screens design"] == "frontend-designer"


def test_project_from_group_can_reuse_active_thread_project(tmp_path) -> None:
    gs = GroupStore(base_dir=tmp_path / "cowork")
    for a in ("research-agent", "build-agent"):
        service.invite_member(gs, "thread-1", actor="u", target_id=a, kind="agent")
    store = ProjectStore(base_dir=tmp_path / "projectos")
    hooks = {"generate_milestones": stub_generate_milestones}

    first = run_project_from_group(
        store,
        gs,
        "thread-1",
        name="x",
        goal="ship it",
        hooks=hooks,
        run=True,
        max_ticks=1,
        reuse_active=True,
    )
    pid = first["project"]["id"]
    assert first["reused"] is False
    assert first["trace"]["schema"] == "octopus.projectos.run_trace.v1"
    assert first["trace"]["tick_events"]
    assert first["trace"]["milestones"][0]["assignments"]
    assert first["trace"]["milestones"][0]["assignments"][0]["available_actions"]
    assert first["available_actions"] == ["run", "tick"]
    assert first["action_specs"][0]["api"]["path"] == f"/api/projects/{pid}/run"
    assert first["tasks"]["MS1"][0]["available_actions"]
    assert first["tasks"]["MS1"][0]["action_specs"]
    assert first["tasks"]["MS1"][0]["action_specs"][0]["api"]["path"].startswith(
        f"/api/projects/{pid}/tasks/"
    )
    assert store.project_for_thread("thread-1").id == pid
    assert first["project"]["status"] == "running"

    second = run_project_from_group(
        store,
        gs,
        "thread-1",
        name="x",
        goal="ship it again",
        hooks=hooks,
        run=True,
        max_ticks=50,
        reuse_active=True,
    )
    assert second["project"]["id"] == pid
    assert second["reused"] is True
    assert second["trace"]["reused"] is True
    assert second["trace"]["project_id"] == pid
    assert second["result"]["final_status"] == "done"
    assert second["available_actions"] == ["inspect", "report"]
    events = store.events_for_project(pid)
    assert "project.run_from_group" in [event["kind"] for event in events]
    timeline = project_process_timeline(store, pid)
    assert timeline is not None
    assert timeline["schema"] == "octopus.projectos.process_timeline.v1"
    assert timeline["thread_id"] == "thread-1"
    assert timeline["overview"]["assigned_agent_count"] >= 1
    assert any(
        node["kind"] == "project.run_from_group"
        and node["data"]["trace"]["thread_id"] == "thread-1"
        for node in timeline["timeline"]
    )


def test_from_group_endpoint_turns_a_group_into_a_project_team(tmp_path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.sensing.gateway.projects_router import create_projects_router

    gs = GroupStore(base_dir=tmp_path)
    for a in ("research-agent", "build-agent"):
        service.invite_member(gs, "team-1", actor="u", target_id=a, kind="agent")

    app = FastAPI()
    app.include_router(
        create_projects_router(store=ProjectStore(base_dir=tmp_path), group_store=gs)
    )
    client = TestClient(app)

    resp = client.post(
        "/api/projects/from-group/team-1",
        json={"name": "x", "goal": "ship it", "run": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["roster"]) == {"research-agent", "build-agent"}
    assert body["result"]["final_status"] == "done"
    # every task ran on a real group member
    pool = {"research-agent", "build-agent"}
    for tasks in body["tasks"].values():
        for t in tasks:
            assert t["assigned_agent"] in pool

    # a group with no agents is rejected (can't staff a project)
    GroupStore(base_dir=tmp_path)  # empty thread
    assert (
        client.post(
            "/api/projects/from-group/empty-thread", json={"name": "x", "goal": "g"}
        ).status_code
        == 400
    )


def test_from_group_default_attaches_without_execution_or_changing_response_mode(
    tmp_path,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.sensing.gateway.projects_router import create_projects_router

    gs = GroupStore(base_dir=tmp_path / "cowork")
    for agent_id in ("research-agent", "build-agent"):
        service.invite_member(
            gs,
            "team-attach",
            actor="u",
            target_id=agent_id,
            kind="agent",
        )
    service.set_mode(gs, "team-attach", actor="u", mode="swarm")
    store = ProjectStore(base_dir=tmp_path / "projectos")
    app = FastAPI()
    app.include_router(create_projects_router(store=store, group_store=gs))

    response = TestClient(app).post(
        "/api/projects/from-group/team-attach",
        json={"name": "Attached", "goal": "Plan without starting"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["final_status"] == body["project"]["status"]
    assert all(
        task["status"] == "pending" and task["attempts"] == 0
        for tasks in body["tasks"].values()
        for task in tasks
    )
    assert gs.state("team-attach").mode == "swarm"
    events = store.events_for_project(body["project"]["id"])
    attached = [event for event in events if event["kind"] == "project.attached_from_group"]
    assert len(attached) == 1
    assert attached[0]["payload"]["response_mode"] == "swarm"
    assert attached[0]["payload"]["run"] is False


@pytest.mark.parametrize("failure_stage", ["bind", "state", "event"])
def test_new_project_attach_failure_removes_shell_and_preserves_group(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    group_store = _attached_group(tmp_path)
    project_store = ProjectStore(base_dir=tmp_path / "projectos")
    thread_id = "thread-attach-failure"
    before_state = group_store.state(thread_id).to_dict()
    before_events = [event.to_dict() for event in group_store.events(thread_id)]
    planned_ids: list[str] = []
    real_bind = project_store.bind_thread

    def capture_bind(inner_thread_id: str, project_id: str, **kwargs) -> None:
        planned_ids.append(project_id)
        real_bind(inner_thread_id, project_id, **kwargs)
        if failure_stage == "bind":
            raise RuntimeError("injected bind failure after commit")

    monkeypatch.setattr(project_store, "bind_thread", capture_bind)
    if failure_stage == "state":
        monkeypatch.setattr(
            cowork_bridge,
            "full_project_state",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected attach state failure")
            ),
        )
    elif failure_stage == "event":
        monkeypatch.setattr(
            project_store,
            "append_event",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected attach event failure")
            ),
        )

    with pytest.raises(RuntimeError, match="injected"):
        run_project_from_group(
            project_store,
            group_store,
            thread_id,
            name="Attach failure",
            goal="Leave no project shell",
            run=False,
        )

    assert len(planned_ids) == 1
    project_id = planned_ids[0]
    assert project_store.get_project(project_id) is None
    assert project_store.milestones_for(project_id) == []
    assert project_store.events_for_project(project_id) == []
    assert project_store.project_for_thread(thread_id) is None
    assert _project_table_counts(project_store) == {
        "projects": 0,
        "milestones": 0,
        "tasks": 0,
        "thread_projects": 0,
        "project_events": 0,
    }
    assert group_store.state(thread_id).to_dict() == before_state
    assert [event.to_dict() for event in group_store.events(thread_id)] == before_events


def test_run_failure_after_attach_keeps_recoverable_project(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_store = _attached_group(tmp_path)
    project_store = ProjectStore(base_dir=tmp_path / "projectos")
    thread_id = "thread-attach-failure"
    before_state = group_store.state(thread_id).to_dict()

    def fail_run(*_args, **_kwargs):
        raise RuntimeError("injected execution failure")

    monkeypatch.setattr("runtime.projectos.engine.ProjectEngine.run", fail_run)

    with pytest.raises(RuntimeError, match="injected execution failure"):
        run_project_from_group(
            project_store,
            group_store,
            thread_id,
            name="Recoverable run",
            goal="Keep state after execution starts",
            run=True,
        )

    projects = project_store.list_projects()
    assert len(projects) == 1
    project = projects[0]
    assert project_store.project_for_thread(thread_id).id == project.id
    assert project_store.milestones_for(project.id)
    assert project_store.events_for_project(project.id)
    assert group_store.state(thread_id).to_dict() == before_state


# ── 项目模式 × 蜂群/集群（任务级 team_mode）──────────────────────


def test_team_swarm_runs_task_as_fanout() -> None:
    """swarm 任务节点：蜂群 fan-out 覆盖整个 roster，交付物 = 仲裁合成。"""
    roster = [("researcher-a", "researcher-a"), ("researcher-b", "researcher-b")]
    calls: list[str] = []

    def caller(agent_id: str, prompt: str, timeout_s: int = 300) -> dict:
        calls.append(agent_id)
        return {"success": True, "output": f"视角 from {agent_id}"}

    run_team = team_execute_for_group(roster, agent_caller=caller, debate_rounds=1)
    out = run_team(
        Task(
            id="T", milestone_id="M", type="research", goal="怎么给这个功能定价", team_mode="swarm"
        ),
        {},
    )
    assert out.startswith("# 蜂群交付")
    assert "researcher-a" in calls and "researcher-b" in calls
    assert "视角 from" in out


def test_team_cluster_runs_task_as_role_pipeline() -> None:
    """cluster 任务节点：roster 当研究员池，指派 agent 当队长/合成器。"""
    roster = [("researcher-a", "researcher-a"), ("researcher-b", "researcher-b")]
    calls: list[str] = []

    def caller(agent_id: str, prompt: str, timeout_s: int = 300) -> dict:
        calls.append(agent_id)
        return {"success": True, "output": f"out by {agent_id}"}

    run_team = team_execute_for_group(roster, agent_caller=caller, debate_rounds=1)
    out = run_team(
        Task(
            id="T",
            milestone_id="M",
            type="code",
            goal="build the thing",
            team_mode="cluster",
            assigned_agent="lead-agent",
        ),
        {},
    )
    assert out.startswith("# 集群交付")
    # 每个 roster 成员作为研究员副本各跑一次，队长也跑了计划+合成。
    assert set(calls) >= {"researcher-a", "researcher-b", "lead-agent"}


def test_engine_for_group_wires_team_executor_and_runs_swarm_node(tmp_path) -> None:
    """engine_for_group 注入 run_task_team；stub 分解的 research 节点走蜂群，
    而不是单 agent execute —— 项目×蜂群端到端。"""
    gs = GroupStore(base_dir=tmp_path)
    for a in ("researcher-a", "researcher-b"):
        service.invite_member(gs, "thread-1", actor="u", target_id=a, kind="agent")

    called: list[str] = []

    def caller(agent_id: str, prompt: str, timeout_s: int = 300) -> dict:
        called.append(agent_id)
        return {"success": True, "output": f"out by {agent_id}"}

    eng = engine_for_group(
        ProjectStore(base_dir=tmp_path),
        gs,
        "thread-1",
        hooks={
            "generate_milestones": stub_generate_milestones,
            "decompose_tasks": stub_decompose_tasks,
        },
    )
    # 手动注入一个走 fan-out 的 team executor（避免真实 call_subagent）。
    eng._run_task_team = team_execute_for_group(  # noqa: SLF001
        roster_from_group(gs, "thread-1"), agent_caller=caller, debate_rounds=1
    )
    p = eng.plan("custom", "设计一套定价策略")
    eng.run(p.id, max_ticks=50)
    assert "researcher-a" in called and "researcher-b" in called


def _managed_project_context() -> dict:
    return {
        "project_id": "P-managed",
        "owner_id": "alice",
        "tenant_id": "tenant-a",
        "thread_id": "thread-managed",
        "milestone_goal": "secure delivery",
        "workspace_path": "/managed/thread-managed",
        "runtime_session_metadata": {
            "workspace_path": "/managed/thread-managed",
            "_artifact_output_root": "/managed/thread-managed/output/final",
            "preserved": "yes",
        },
    }


def _assert_team_scope(calls: list[dict], explicit_runner) -> None:
    assert calls
    for call in calls:
        assert call["runner"] is explicit_runner
        context = call["context"]
        assert context["thread_id"] == "thread-managed"
        assert context["actor"] == "alice"
        assert context["tenant_id"] == "tenant-a"
        assert context["workspace_path"] == "/managed/thread-managed"
        assert context["source"] == "projectos_team_task"
        assert context["task_id"] == "T-managed"
        assert context["runtime_session_metadata"] == {
            "workspace_path": "/managed/thread-managed",
            "_artifact_output_root": "/managed/thread-managed/output/final",
            "preserved": "yes",
            "source": "projectos_team_task",
            "project_id": "P-managed",
            "task_id": "T-managed",
            "tenant_id": "tenant-a",
        }


def test_team_swarm_propagates_managed_project_scope(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_call_subagent(agent_id, prompt, **kwargs):
        calls.append({"agent_id": agent_id, "prompt": prompt, **kwargs})
        return {"success": True, "output": f"swarm output from {agent_id}"}

    def explicit_runner(prompt: str, **kwargs) -> str:
        return "unused"

    monkeypatch.setattr("runtime.execution.subagents.call_subagent", fake_call_subagent)
    run_team = team_execute_for_group(
        [("researcher-a", "researcher-a"), ("researcher-b", "researcher-b")],
        subagent_runner=explicit_runner,
        debate_rounds=0,
    )
    output = run_team(
        Task(
            id="T-managed",
            milestone_id="M",
            type="research",
            goal="research safely",
            team_mode="swarm",
        ),
        _managed_project_context(),
    )

    assert output.startswith("# 蜂群交付")
    _assert_team_scope(calls, explicit_runner)


def test_team_cluster_propagates_managed_project_scope(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_call_subagent(agent_id, prompt, **kwargs):
        calls.append({"agent_id": agent_id, "prompt": prompt, **kwargs})
        return {"success": True, "output": f"cluster output from {agent_id}"}

    def explicit_runner(prompt: str, **kwargs) -> str:
        return "unused"

    monkeypatch.setattr("runtime.execution.subagents.call_subagent", fake_call_subagent)
    run_team = team_execute_for_group(
        [("researcher-a", "researcher-a"), ("researcher-b", "researcher-b")],
        subagent_runner=explicit_runner,
    )
    output = run_team(
        Task(
            id="T-managed",
            milestone_id="M",
            type="code",
            goal="build safely",
            team_mode="cluster",
            assigned_agent="lead-agent",
        ),
        _managed_project_context(),
    )

    assert output.startswith("# 集群交付")
    _assert_team_scope(calls, explicit_runner)

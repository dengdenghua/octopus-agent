"""Project OS on a custom cowork group: roles aren't fixed — your pulled-in
members become the team and tasks route to them by capability."""

from __future__ import annotations

from runtime.memory.cowork import service
from runtime.memory.cowork.group import MemberEvent
from runtime.memory.cowork.group_store import GroupStore
from runtime.projectos.cowork_bridge import (
    engine_for_group,
    nominate_assigner,
    roster_from_group,
    run_project_from_group,
)
from runtime.projectos.engine import stub_generate_milestones
from runtime.projectos.model import Milestone, Task
from runtime.projectos.store import ProjectStore


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
    assert assign(Task(id="T", milestone_id="M", type="code", goal="optimize database index")) \
        == "database-expert"
    assert assign(Task(id="T", milestone_id="M", type="design", goal="design the frontend layout")) \
        == "frontend-designer"
    # no keyword match → still a group member (not a fixed role)
    assert assign(Task(id="T", milestone_id="M", type="code", goal="zzz")) in {
        "database-expert", "frontend-designer"
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
            Task(id=f"{ms.id}-T2", milestone_id=ms.id, type="design", goal="frontend screens design",
                 depends_on=[f"{ms.id}-T1"]),
        ]

    eng = engine_for_group(
        ProjectStore(base_dir=tmp_path), gs, "thread-1",
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

    resp = client.post("/api/projects/from-group/team-1", json={"name": "x", "goal": "ship it"})
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
    assert client.post(
        "/api/projects/from-group/empty-thread", json={"name": "x", "goal": "g"}
    ).status_code == 400

"""Human-required nodes in the project task DAG.

A real person has to be able to own a node, and an agent must never silently stand
in for one. An AI that "does the human part" would pass QA and then be sealed into
the delivery fingerprint — the very guarantee the acceptance gate rests on.
"""

from __future__ import annotations

import pytest

from runtime.projectos._store_helpers import _normalize_task
from runtime.projectos.cowork_bridge import team_execute_for_group
from runtime.projectos.engine import HUMAN_NODE_UNCLAIMED, ProjectEngine
from runtime.projectos.model import Milestone, Task, normalize_team_mode
from runtime.projectos.store import ProjectStore


def _store_and_engine(tmp_path, decompose, **kwargs):
    store = ProjectStore(base_dir=tmp_path)
    engine = ProjectEngine(
        store,
        generate_milestones=lambda goal: [
            Milestone(id="M1", name="现场拍摄", goal=goal, success_criteria=["照片合格"])
        ],
        decompose_tasks=decompose,
        qa_task=lambda task, ms: {"approved": True, "reason": "ok"},
        **kwargs,
    )
    return store, engine


def _shoot(mode):
    def decompose(ms):
        return [
            Task(
                id=f"{ms.id}-T1",
                milestone_id=ms.id,
                type="code",
                goal="现场拍摄 20 张实物图",
                team_mode=mode,
                acceptance_criteria=["照片合格"],
            )
        ]

    return decompose


def _events(result):
    return [event for tick in result["history"] for event in tick["events"]]


@pytest.mark.parametrize("mode", ["human", "hybrid"])
def test_human_modes_survive_every_team_mode_sanitiser(mode):
    """All three read paths share one normaliser.

    When each site kept its own whitelist, a new mode survived in one place and was
    silently downgraded to ``single`` in another — which is exactly how a human
    node would have reached an AI executor.
    """
    assert normalize_team_mode(mode) == mode
    assert normalize_team_mode(mode.upper()) == mode
    assert (
        Task.from_dict(
            {"id": "T1", "milestone_id": "M1", "type": "code", "goal": "g", "team_mode": mode}
        ).team_mode
        == mode
    )
    assert (
        _normalize_task(
            Task(id="T1", milestone_id="M1", type="code", goal="g", team_mode=mode)
        ).team_mode
        == mode
    )


def test_unknown_team_mode_still_falls_back_to_single():
    assert normalize_team_mode("banana") == "single"
    assert normalize_team_mode(None) == "single"
    assert normalize_team_mode("") == "single"


@pytest.mark.parametrize("mode", ["human", "hybrid"])
def test_human_node_is_never_executed_by_an_agent(tmp_path, mode):
    executed = []

    def executor(task, context):
        executed.append(task.id)
        return "AI 替真人拍的照片"

    store, engine = _store_and_engine(tmp_path, _shoot(mode), execute_task=executor)
    project = engine.plan("商品上新", "拍 20 张实物图并写标题")
    result = engine.run(project.id, max_ticks=5)

    tasks = store.tasks_for_milestone("M1")
    assert executed == []  # the AI executor was never offered this node
    assert [t.status for t in tasks] == ["blocked"]
    assert tasks[0].output == HUMAN_NODE_UNCLAIMED
    # The assigner must not fill an agent id: that would show a bot on a human
    # node in the workbench and hand it to the executor it must never reach.
    assert tasks[0].assigned_agent == ""
    assert "task_awaiting_human:M1-T1" in _events(result)


def test_human_node_is_not_treated_as_an_unauthorized_agent(tmp_path):
    """A phase's agent allow-list governs AI members only.

    Before this, a human node kept an empty assignee, failed the authorization
    check, and died with an assignment error instead of waiting for a person.
    """
    from runtime.projectos.governance import phase_fingerprint

    store = ProjectStore(base_dir=tmp_path)
    milestone = Milestone(
        id="M1",
        name="现场拍摄",
        goal="拍 20 张实物图",
        spec={"phase_agents": ["agent-a"]},
        success_criteria=["照片合格"],
    )
    engine = ProjectEngine(
        store,
        generate_milestones=lambda goal: [milestone],
        decompose_tasks=_shoot("human"),
        qa_task=lambda task, ms: {"approved": True, "reason": "ok"},
    )
    project = engine.plan("商品上新", "拍 20 张实物图")
    saved = store.milestones_for(project.id)[0]
    store.append_event(
        project.id,
        kind="project.phase_authorized",
        payload={"milestone_id": "M1", "fingerprint": phase_fingerprint(saved)},
    )
    result = engine.run(project.id, max_ticks=5)

    task = store.tasks_for_milestone("M1")[0]
    assert task.output == HUMAN_NODE_UNCLAIMED
    assert not any("assignment" in event for event in _events(result))


def test_waiting_on_a_human_is_not_reported_as_a_dag_deadlock(tmp_path):
    store, engine = _store_and_engine(tmp_path, _shoot("human"))
    project = engine.plan("商品上新", "拍 20 张实物图")
    result = engine.run(project.id, max_ticks=5)

    events = _events(result)
    assert "milestone_blocked_human:M1" in events
    assert "project_blocked:awaiting_human" in events
    assert not any(e.startswith("milestone_blocked_dag:") for e in events)
    assert result["final_status"] == "blocked"


@pytest.mark.parametrize("mode", ["human", "hybrid"])
def test_injected_human_runner_completes_the_node(tmp_path, mode):
    store, engine = _store_and_engine(
        tmp_path,
        _shoot(mode),
        run_task_human=lambda task, context: "真人交付：20 张照片",
    )
    project = engine.plan("商品上新", "拍 20 张实物图")
    result = engine.run(project.id, max_ticks=5)

    task = store.tasks_for_milestone("M1")[0]
    assert task.status == "done"
    assert task.output == "真人交付：20 张照片"
    assert result["final_status"] == "done"


def test_ai_team_engine_refuses_a_human_node():
    """Defence in depth: the bridge is callable on its own, so it refuses too."""
    run_team = team_execute_for_group(
        [("researcher-a", "researcher-a")],
        agent_caller=lambda *a, **kw: {"success": True, "output": "out"},
    )
    with pytest.raises(RuntimeError, match="human task"):
        run_team(
            Task(id="T", milestone_id="M", type="code", goal="g", team_mode="human"),
            {},
        )

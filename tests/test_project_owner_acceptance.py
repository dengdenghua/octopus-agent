import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from runtime.projectos.acceptance import delivery_accepted, delivery_fingerprint
from runtime.projectos.engine import ProjectEngine, stub_decompose_tasks
from runtime.projectos.model import Milestone
from runtime.projectos.store import ProjectStore
from runtime.protocol import Turn
from runtime.sensing.gateway.realtime_project_acceptance import accept_delivery


def setup(tmp_path):
    store = ProjectStore(tmp_path)
    engine = ProjectEngine(
        store,
        generate_milestones=lambda _: [
            Milestone(
                id="first", name="first", goal="first", spec={"requires_owner_acceptance": True}
            ),
            Milestone(
                id="second",
                name="second",
                goal="second",
                dependencies=["first"],
                spec={"requires_owner_acceptance": True},
            ),
        ],
        decompose_tasks=stub_decompose_tasks,
        execute_task=lambda *_: "delivery",
        qa_task=lambda *_: {"approved": True},
        gate_milestone=lambda *_: {"met": True},
    )
    project = engine.plan("release", "release")
    return store, engine, project


def test_engine_waits_for_owner_before_advancing(tmp_path):
    store, engine, project = setup(tmp_path)
    result = engine.run(project.id)
    assert "awaiting_owner_acceptance:first" in result["history"][-1]["events"]
    assert store.get_milestone("second").status == "pending"
    from runtime.projectos.pm import build_pm_report

    report = build_pm_report(store, project.id)
    assert report["next_actions"][0]["type"] == "owner_acceptance"
    assert report["overall_progress"] == 0.5  # Undecomposed phase two still counts.
    assert report["awaiting_acceptance_count"] == 1
    ms = store.get_milestone("first")
    tasks = store.tasks_for_milestone(ms.id)
    store.append_event(
        project.id,
        kind="project.delivery_accepted",
        payload={"milestone_id": ms.id, "fingerprint": delivery_fingerprint(ms, tasks)},
    )
    assert delivery_accepted(store, project.id, ms, tasks)
    tasks[0].output = "changed"
    assert not delivery_accepted(store, project.id, ms, tasks)
    result = engine.run(project.id)
    assert store.get_milestone("first").status == "done"
    assert "awaiting_owner_acceptance:second" in result["history"][-1]["events"]


@pytest.mark.parametrize("action", ["accept", "decline", "timeout"])
def test_acceptance_records_only_approved_delivery(tmp_path, action):
    store, engine, project = setup(tmp_path)
    engine.run(project.id)
    store.project_for_thread = lambda _: store.get_project(project.id)
    emitter = SimpleNamespace(
        request_approval=AsyncMock(return_value={"action": action}),
        is_turn_interrupted=lambda _: False,
    )
    if action == "timeout":
        emitter.request_approval.side_effect = TimeoutError()
    runtime = SimpleNamespace(_emit_agent_message=AsyncMock())
    asyncio.run(
        accept_delivery(
            runtime,
            Turn(threadId="thread"),
            None,
            emitter,
            project_store=store,
            thread_id="thread",
            milestone_id="first",
            owner_id="",
            tenant_id="",
        )
    )
    accepted = delivery_accepted(
        store, project.id, store.get_milestone("first"), store.tasks_for_milestone("first")
    )
    assert accepted == (action == "accept")
    assert store.get_milestone("second").status == "pending"


@pytest.mark.parametrize("change", ["task_goal", "task_criteria", "phase_goal", "approved_brief"])
def test_acceptance_is_invalidated_when_reviewed_requirements_change(tmp_path, change):
    store, engine, project = setup(tmp_path)
    engine.run(project.id)
    ms = store.get_milestone("first")
    tasks = store.tasks_for_milestone(ms.id)
    store.append_event(project.id, kind="project.delivery_accepted",
                       payload={"milestone_id": ms.id, "fingerprint": delivery_fingerprint(ms, tasks)})
    if change == "task_goal":
        tasks[0].goal = "expanded goal"
    elif change == "task_criteria":
        tasks[0].acceptance_criteria = ["new criterion"]
    elif change == "phase_goal":
        ms.goal = "new phase goal"
    else:
        ms.spec["approved_brief"] = "changed scope"
    assert not delivery_accepted(store, project.id, ms, tasks)


@pytest.mark.parametrize("output", [None, "", " \n ", {}, [], {"text": "", "files": []}])
def test_done_task_without_deliverable_cannot_open_acceptance(tmp_path, output):
    store, engine, project = setup(tmp_path)
    engine.run(project.id)
    tasks = store.tasks_for_milestone("first")
    tasks[0].output = output
    store.save_task(tasks[0], allow_terminal_rewrite=True)
    store.project_for_thread = lambda _: store.get_project(project.id)
    emitter = SimpleNamespace(request_approval=AsyncMock(), is_turn_interrupted=lambda _: False)
    runtime = SimpleNamespace(_emit_agent_message=AsyncMock())
    asyncio.run(accept_delivery(runtime, Turn(threadId="thread"), None, emitter,
                               project_store=store, thread_id="thread", milestone_id="first",
                               owner_id="", tenant_id=""))
    emitter.request_approval.assert_not_awaited()
    assert not delivery_accepted(store, project.id, store.get_milestone("first"), tasks)
    assert "未提供交付内容" in runtime._emit_agent_message.call_args.args[-1]

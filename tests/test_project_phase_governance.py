import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from runtime.memory.cowork.group_store import GroupStore
from runtime.projectos.engine import ProjectEngine, stub_decompose_tasks
from runtime.projectos.governance import phase_fingerprint, record_usage, reported_cost
from runtime.projectos.model import Milestone
from runtime.projectos.store import ProjectStore
from runtime.protocol import Turn
from runtime.sensing.gateway.realtime_project_phase import adjust_budget, authorize_phase


def setup(tmp_path, cap=None):
    store = ProjectStore(tmp_path / "projects")
    calls = []

    def execute(task, context):
        calls.append(task.id)
        context["record_project_usage"]({"governance": {"root_id": "turn", "cost_usd": 1}})
        return "result"

    engine = ProjectEngine(
        store,
        generate_milestones=lambda _: [
            Milestone(
                id="phase",
                name="phase",
                goal="phase",
                spec={"phase_agents": ["general"], "ai_budget_usd": cap},
            )
        ],
        decompose_tasks=stub_decompose_tasks,
        execute_task=execute,
        assign_agent=lambda _: "general",
        qa_task=lambda *_: {"approved": True},
        gate_milestone=lambda *_: {"met": True},
    )
    project = engine.plan("project", "goal")
    return store, engine, project, calls


def test_unapproved_phase_never_decomposes_or_executes(tmp_path):
    store, engine, project, calls = setup(tmp_path)
    result = engine.run(project.id)
    assert result["ticks"] == 1
    assert not calls
    assert not store.tasks_for_milestone("phase")
    assert "awaiting_phase_authorization:phase" in result["history"][0]["events"]


def test_task_count_limit_blocks_model_expansion_before_execution(tmp_path):
    store, engine, project, calls = setup(tmp_path)
    ms = store.get_milestone("phase")
    ms.spec["max_tasks"] = 1
    store.save_milestone(project.id, ms)
    store.append_event(project.id, kind="project.phase_authorized",
                       payload={"fingerprint": phase_fingerprint(ms)})
    result = engine.run(project.id)
    assert result["final_status"] == "blocked"
    assert not calls
    assert not store.tasks_for_milestone(ms.id)
    errors = [e["payload"].get("error", "") for e in store.events_for_project(project.id)
              if e["kind"] == "project.decompose_failed"]
    assert any("数量上限" in error for error in errors)


@pytest.mark.parametrize("change", ["criteria", "brief", "deadline", "dependencies"])
def test_changed_approved_scope_requires_new_approval(tmp_path, change):
    store, engine, project, calls = setup(tmp_path)
    ms = store.get_milestone("phase")
    store.append_event(project.id, kind="project.phase_authorized",
                       payload={"fingerprint": phase_fingerprint(ms)})
    if change == "criteria":
        ms.success_criteria = ["new acceptance standard"]
    elif change == "brief":
        ms.spec["approved_brief"] = "expanded delivery scope"
    elif change == "deadline":
        ms.due_at = "2026-10-01"
    else:
        # Verify fingerprint independently: an unmet dependency also pauses the engine.
        ms.dependencies = ["new-prerequisite"]
    from runtime.projectos.governance import phase_authorized

    assert not phase_authorized(store, project.id, ms)
    if change != "dependencies":
        store.save_milestone(project.id, ms)
        result = engine.run(project.id)
        assert not calls
        assert "awaiting_phase_authorization:phase" in result["history"][0]["events"]


def test_execution_progress_does_not_invalidate_phase_approval():
    ms = Milestone(id="M", name="M", goal="goal", spec={"phase_agents": ["b", "a"]})
    approved = phase_fingerprint(ms)
    ms.status = "in_progress"
    ms.task_ids = ["T1"]
    ms.spec["phase_agents"] = ["a", "b"]
    assert phase_fingerprint(ms) == approved


def test_pre_execution_context_failure_does_not_record_unknown_cost(tmp_path, monkeypatch):
    from runtime.projectos.governance import budget_reached

    store, engine, project, calls = setup(tmp_path, cap=2)
    ms = store.get_milestone("phase")
    store.append_event(project.id, kind="project.phase_authorized",
                       payload={"fingerprint": phase_fingerprint(ms)})

    def fail_context(*_):
        raise RuntimeError("workspace unavailable")

    monkeypatch.setattr(engine, "_context", fail_context)
    engine.run(project.id, max_ticks=1)
    assert not calls
    assert not budget_reached(store, project.id, ms)


def test_reported_budget_is_durable_idempotent_and_stops_next_task(tmp_path):
    store, engine, project, calls = setup(tmp_path, cap=1)
    ms = store.get_milestone("phase")
    store.append_event(
        project.id, kind="project.phase_authorized", payload={"fingerprint": phase_fingerprint(ms)}
    )
    engine.run(project.id)
    assert len(calls) == 1
    record_usage(store, project.id, {"governance": {"root_id": "turn", "cost_usd": 1}})
    assert reported_cost(ProjectStore(tmp_path / "projects"), project.id) == 1
    result = engine.run(project.id)
    assert len(calls) == 1
    assert "project_budget_paused:phase" in result["history"][0]["events"]


def test_missing_usage_identifies_task_without_inventing_zero_cost(tmp_path):
    from runtime.projectos.governance import budget_pause_message, budget_status

    store, engine, project, _ = setup(tmp_path, cap=2)
    ms = store.get_milestone("phase")
    record_usage(store, project.id, {}, task_id="phase-T1", milestone_id=ms.id)
    status = budget_status(store, project.id, ms)
    assert status["missing_task_ids"] == ["phase-T1"]
    assert "phase-T1" in budget_pause_message(status)
    event = next(e for e in store.events_for_project(project.id) if e["kind"] == "project.usage_missing")
    assert event["payload"]["cost_usd"] is None
    assert event["payload"]["milestone_id"] == ms.id


def test_late_receipt_resolves_only_matching_execution_and_survives_restart(tmp_path):
    from runtime.projectos.governance import budget_status

    store, _, project, _ = setup(tmp_path, cap=2)
    ms = store.get_milestone("phase")
    for root, task in [("member-a", "T1"), ("member-b", "T2")]:
        record_usage(store, project.id, {"governance": {"root_id": root, "cost_usd": None}}, task_id=task)
    record_usage(store, project.id, {"governance": {"root_id": "unrelated", "cost_usd": 0}})
    assert budget_status(store, project.id, ms)["missing_task_ids"] == ["T1", "T2"]
    receipt = {"governance": {"root_id": "member-a", "cost_usd": 0.5}}
    record_usage(store, project.id, receipt)
    record_usage(store, project.id, receipt)
    fresh = ProjectStore(tmp_path / "projects")
    assert budget_status(fresh, project.id, ms)["missing_task_ids"] == ["T2"]
    record_usage(fresh, project.id, {"governance": {"root_id": "member-b", "cost_usd": 0.25}})
    status = budget_status(fresh, project.id, ms)
    assert not status["paused"]
    assert status["reported_cost_usd"] == 0.75


def test_reconciled_receipt_still_enforces_cap(tmp_path):
    from runtime.projectos.governance import budget_status

    store, _, project, _ = setup(tmp_path, cap=2)
    ms = store.get_milestone("phase")
    record_usage(store, project.id, {"governance": {"root_id": "a"}}, task_id="T1")
    record_usage(store, project.id, {"governance": {"root_id": "a", "cost_usd": 2}})
    status = budget_status(store, project.id, ms)
    assert status["reason"] == "limit_reached"
    assert not status["missing_task_ids"]


@pytest.mark.parametrize("root", [None, "", "  ", "__unreported__", 42])
def test_uncorrelated_gap_cannot_be_cleared_by_another_receipt(tmp_path, root):
    from runtime.projectos.governance import budget_status

    store, _, project, _ = setup(tmp_path, cap=2)
    ms = store.get_milestone("phase")
    assert not record_usage(store, project.id, {"governance": {"root_id": root, "cost_usd": 0}}, task_id="T1")
    record_usage(store, project.id, {"governance": {"root_id": "new-run", "cost_usd": 0}})
    assert budget_status(store, project.id, ms)["reason"] == "usage_missing"


def test_legacy_missing_marker_is_not_erased_by_new_receipt(tmp_path):
    from runtime.projectos.governance import budget_status

    store, _, project, _ = setup(tmp_path, cap=2)
    ms = store.get_milestone("phase")
    record_usage(store, project.id, {"governance": {"root_id": "a", "cost_usd": 0}})
    with store._conn() as conn:
        conn.execute("INSERT INTO project_reported_usage VALUES (?,?,?)", (project.id, "__unreported__", 0))
    record_usage(store, project.id, {"governance": {"root_id": "a", "cost_usd": 0.2}})
    assert budget_status(store, project.id, ms)["reason"] == "usage_missing"


def test_delete_project_cleans_receipts_and_gaps_without_touching_other_projects(tmp_path):
    from runtime.projectos._store_project_deletion import ProjectDeletedError

    store, engine, project, _ = setup(tmp_path, cap=2)
    other = engine.plan("other", "goal")
    for item in (project, other):
        record_usage(store, item.id, {"governance": {"root_id": "paid", "cost_usd": 0.5}})
        record_usage(store, item.id, {"governance": {"root_id": "missing"}}, task_id="T1")
    assert store.delete_project(project.id)
    with store._conn() as conn:
        for table in ("project_reported_usage", "project_missing_usage"):
            rows = conn.execute(f"SELECT project_id FROM {table}").fetchall()
            assert [row[0] for row in rows] == [other.id]
    with pytest.raises(ProjectDeletedError):
        record_usage(store, project.id, {"governance": {"root_id": "late", "cost_usd": 0.5}})


@pytest.mark.parametrize("missing", [False, True])
def test_budget_reason_and_workbench_agree(tmp_path, missing):
    from runtime.projectos.governance import budget_status
    from runtime.projectos.pm import build_pm_report

    store, engine, project, _ = setup(tmp_path, cap=1)
    ms = store.get_milestone("phase")
    store.append_event(project.id, kind="project.phase_authorized",
                       payload={"fingerprint": phase_fingerprint(ms)})
    if missing:
        record_usage(store, project.id, {})
    else:
        record_usage(store, project.id, {"governance": {"root_id": "r", "cost_usd": 1}})
    ms.status = "in_progress"
    store.save_milestone(project.id, ms)
    status = budget_status(store, project.id, ms)
    assert status["reason"] == ("usage_missing" if missing else "limit_reached")
    report = build_pm_report(store, project.id)
    assert report["milestones"][0]["health"] == "blocked"
    assert report["blockers"]
    assert report["next_actions"][0]["type"] == "budget_review"
    assert all(not action["task_id"] for action in report["next_actions"])
    assert ("提高预算不能" in report["next_actions"][0]["task"]) == missing


@pytest.mark.parametrize("action", ["accept", "decline", "timeout"])
def test_phase_members_added_only_after_phase_approval(tmp_path, action):
    store, engine, project, calls = setup(tmp_path)
    store.project_for_thread = lambda _: store.get_project(project.id)
    groups = GroupStore(tmp_path / "group")
    runtime = SimpleNamespace(
        _cowork_group_store=groups,
        _emit_agent_message=AsyncMock(),
        _agent_registry=SimpleNamespace(
            has=lambda id: id == "general", get=lambda _: SimpleNamespace(display_name="General")
        ),
    )
    emitter = SimpleNamespace(
        request_approval=AsyncMock(return_value={"action": action}),
        is_turn_interrupted=lambda _: False,
    )
    if action == "timeout":
        emitter.request_approval.side_effect = TimeoutError()
    ok = asyncio.run(
        authorize_phase(
            runtime,
            Turn(threadId="thread"),
            None,
            emitter,
            store=store,
            project=project,
            owner_id="",
            tenant_id="",
        )
    )
    assert ok == (action == "accept")
    assert bool(groups.state("thread").roster) == ok
    assert not calls


def test_unknown_cost_pauses_configured_budget(tmp_path):
    store, engine, project, calls = setup(tmp_path, cap=10)
    ms = store.get_milestone("phase")
    store.append_event(
        project.id, kind="project.phase_authorized", payload={"fingerprint": phase_fingerprint(ms)}
    )
    record_usage(store, project.id, {})
    assert "project_budget_paused:phase" in engine.run(project.id)["history"][0]["events"]
    assert not calls


@pytest.mark.parametrize("action", ["accept", "decline"])
def test_budget_change_requires_approval_and_invalidates_phase_authority(tmp_path, action):
    from runtime.projectos.governance import phase_authorized
    store, engine, project, calls = setup(tmp_path, cap=1)
    store.project_for_thread = lambda _: store.get_project(project.id)
    ms = store.get_milestone("phase")
    store.append_event(project.id, kind="project.phase_authorized", payload={"fingerprint": phase_fingerprint(ms)})
    emitter = SimpleNamespace(request_approval=AsyncMock(return_value={"action": action}), is_turn_interrupted=lambda _: False)
    runtime = SimpleNamespace(_emit_agent_message=AsyncMock())
    asyncio.run(adjust_budget(runtime, Turn(threadId="thread"), None, emitter,
                             store=store, project=project, value="2", owner_id="", tenant_id=""))
    fresh = store.get_milestone("phase")
    assert fresh.spec["ai_budget_usd"] == (2 if action == "accept" else 1)
    assert phase_authorized(store, project.id, fresh) == (action == "decline")
    assert not calls

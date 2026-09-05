"""AsyncWorkRunner: drives pending tasks via an injected executor (no LLM)."""

from __future__ import annotations

import shutil
import sqlite3
import sys
import threading

import pytest

from runtime.memory.cowork import service
from runtime.memory.cowork.async_runner import AsyncWorkRunner
from runtime.memory.cowork.async_work import AsyncWorkStore
from runtime.memory.cowork.collaboration_store import CollaborationStore
from runtime.memory.cowork.group import ContextGrant, MemberEvent
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.nominate import CompetenceStore
from runtime.memory.cowork.runtime import (
    _collector_completion_observer,
    _execute_subagent_task,
    create_cowork_runtime,
)


def _setup(tmp_path):
    gs = GroupStore(base_dir=tmp_path)
    aw = AsyncWorkStore(base_dir=tmp_path, group_store=gs)
    return gs, aw


def test_runner_executes_and_posts_to_board(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    seen = {}

    def execute(task, context):
        seen["prompt"] = task.prompt
        seen["context"] = context
        return f"done: {task.prompt}"

    runner = AsyncWorkRunner(aw, gs, execute)
    aw.assign("t", "worker", "find slow query", actor="user")
    assert runner.drain("t") == 1
    assert aw.pending("t") == []
    assert seen["prompt"] == "find slow query"
    # result posted to the shared blackboard
    assert any(v == "done: find slow query" for v in gs.blackboard_snapshot("t").values())


def test_cancelled_working_task_discards_late_result(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    started = threading.Event()
    release = threading.Event()
    observed = []

    def execute(_task, _context):
        started.set()
        assert release.wait(timeout=2)
        return "late result must not be published"

    runner = AsyncWorkRunner(
        aw,
        gs,
        execute,
        completion_observer=lambda *args: observed.append(args),
    )
    task = aw.assign("cancel-thread", "worker", "slow work", actor="user")
    worker = threading.Thread(target=lambda: runner.run_one(task))
    worker.start()
    assert started.wait(timeout=1)

    assert aw.cancel_batch([task.task_id], reason="stopped") == 1
    release.set()
    worker.join(timeout=2)

    current = aw.get(task.task_id)
    assert current is not None
    assert current.status == "cancelled"
    assert current.result == "stopped"
    assert gs.blackboard_snapshot("cancel-thread") == {}
    assert observed == []


def test_retry_task_completion_updates_durable_collector_generation(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    collaboration = CollaborationStore(base_dir=tmp_path)
    collaboration.create_collaboration_run(
        run_id="retry-run",
        session_id="t",
        kind="group_fanout",
    )
    collaboration.claim_collaboration_run("retry-run", worker_id="coordinator")
    collaboration.create_collaboration_collector(
        run_id="retry-run",
        child_ids=["worker", "reviewer"],
    )
    collaboration.record_collaboration_collector_result(
        "retry-run", child_id="worker", status="failed", result={"error": "first"}
    )
    collaboration.record_collaboration_collector_result(
        "retry-run", child_id="reviewer", status="success", result={"reply": "ok"}
    )
    collaboration.reopen_collaboration_collector("retry-run")
    task = aw.assign("t", "worker", "retry focused task", actor="user")
    collaboration.bind_collaboration_collector_retry_task(
        "retry-run",
        child_id="worker",
        task_id=task.task_id,
    )
    runner = AsyncWorkRunner(
        aw,
        gs,
        lambda _task, _context: "recovered result",
        completion_observer=_collector_completion_observer(collaboration),
    )

    assert runner.drain("t") == 1
    collector = collaboration.collaboration_collector("retry-run")
    assert collector is not None
    assert collector["status"] == "completed"
    assert collector["success_count"] == 2
    worker = next(item for item in collector["results"] if item["child_id"] == "worker")
    assert worker["attempt"] == 2
    assert worker["result"]["reply"] == "recovered result"


def test_retry_executor_restarts_when_member_steering_arrives_mid_call(
    tmp_path,
    monkeypatch,
) -> None:
    _gs, async_store = _setup(tmp_path)
    collaboration = CollaborationStore(base_dir=tmp_path)
    collaboration.create_collaboration_run(
        run_id="steered-retry",
        session_id="t",
        kind="group_fanout",
    )
    collaboration.claim_collaboration_run("steered-retry", worker_id="coordinator")
    collaboration.create_collaboration_collector(
        run_id="steered-retry",
        child_ids=["worker"],
    )
    collaboration.record_collaboration_collector_result(
        "steered-retry", child_id="worker", status="failed", result={"error": "first"}
    )
    collaboration.reopen_collaboration_collector("steered-retry")
    task = async_store.assign("t", "worker", "original brief", actor="user")
    collaboration.bind_collaboration_collector_retry_task(
        "steered-retry",
        child_id="worker",
        task_id=task.task_id,
    )
    collaboration.submit_collaboration_collector_steering(
        "steered-retry",
        child_id="worker",
        text="先保留兼容性",
    )
    calls: list[dict] = []

    def fake_call_subagent(_agent_id, prompt, **kwargs):
        calls.append({"prompt": prompt, **kwargs})
        if len(calls) == 1:
            collaboration.submit_collaboration_collector_steering(
                "steered-retry",
                child_id="worker",
                text="再补并发回归",
            )
        return {
            "success": True,
            "output": f"answer-{len(calls)}",
            "session_id": "continuable-session",
        }

    monkeypatch.setattr("runtime.execution.subagents.call_subagent", fake_call_subagent)

    assert _execute_subagent_task(task, {}, collaboration_store=collaboration) == "answer-2"
    assert "先保留兼容性" in calls[0]["prompt"]
    assert "先保留兼容性" in calls[1]["prompt"]
    assert "再补并发回归" in calls[1]["prompt"]
    assert calls[1]["continue_session_id"] == "continuable-session"


def test_runner_passes_grant_sliced_history(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    # worker joined at message 5 with from_join → should only see messages 5..
    service.invite_member(
        gs,
        "t",
        actor="u",
        target_id="worker",
        kind="agent",
        grant=ContextGrant(scope="from_join"),
        at_message=5,
    )
    captured = {}

    def execute(task, context):
        captured["history"] = context["history"]
        captured["scope"] = context["grant_scope"]
        return "ok"

    runner = AsyncWorkRunner(
        aw, gs, execute, history_provider=lambda _t: [f"m{i}" for i in range(10)]
    )
    aw.assign("t", "worker", "summarize", actor="u")
    runner.drain("t")
    assert captured["scope"] == "from_join"
    assert captured["history"] == [f"m{i}" for i in range(5, 10)]  # 0..4 not leaked


def test_runner_records_competence_on_success_and_failure(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    comp = CompetenceStore(base_dir=tmp_path)
    runner = AsyncWorkRunner(aw, gs, lambda t, c: "ok", competence=comp)
    aw.assign("t", "worker", "database tuning", actor="u")
    runner.drain("t")
    assert comp.competence("worker", "database") == 1.0  # 1 success

    def boom(task, context):
        raise RuntimeError("model down")

    failing = AsyncWorkRunner(aw, gs, boom, competence=comp)
    tid = aw.assign("t", "worker", "database tuning", actor="u").task_id
    failing.drain("t")
    assert aw.get(tid).status == "failed"
    assert comp.competence("worker", "database") == 0.5  # 1 win / 2 total


def test_drain_all_across_threads(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    runner = AsyncWorkRunner(aw, gs, lambda t, c: "r")
    aw.assign("t1", "w", "a", actor="u")
    aw.assign("t2", "w", "b", actor="u")
    assert set(aw.threads_with_pending()) == {"t1", "t2"}
    assert runner.drain_all() == 2
    assert aw.threads_with_pending() == []


def test_tick_round_robins_threads_before_returning_to_large_backlog(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    runner = AsyncWorkRunner(
        aw,
        gs,
        lambda task, _context: task.prompt,
        max_concurrency=1,
        max_tasks_per_tick=2,
    )
    heavy = [aw.assign("heavy", "w", f"heavy-{index}", actor="u") for index in range(3)]
    light = aw.assign("light", "w", "light-1", actor="u")

    assert runner.tick_once() == 2

    assert aw.get(heavy[0].task_id).status == "done"
    assert [aw.get(task.task_id).status for task in heavy[1:]] == ["pending", "pending"]
    assert aw.get(light.task_id).status == "done"
    assert runner.status()["last_concurrency"] == 1


def test_tick_adapts_concurrency_to_backlog(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    lock = threading.Lock()
    two_workers_started = threading.Event()
    active = 0
    peak = 0

    def execute(task, _context):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active >= 2:
                two_workers_started.set()
        assert two_workers_started.wait(timeout=2)
        with lock:
            active -= 1
        return task.prompt

    runner = AsyncWorkRunner(aw, gs, execute, max_concurrency=4)
    for index in range(4):
        aw.assign("t", "w", f"task-{index}", actor="u")

    assert runner.tick_once() == 4
    assert peak == 2
    status = runner.status()
    assert status["max_concurrency"] == 4
    assert status["last_concurrency"] == 2


def test_tick_once_records_success_health(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    runner = AsyncWorkRunner(aw, gs, lambda t, c: "r")
    aw.assign("t", "w", "a", actor="u")

    assert runner.tick_once() == 1

    status = runner.status()
    assert status["running"] is False
    assert status["total_ticks"] == 1
    assert status["total_failures"] == 0
    assert status["consecutive_failures"] == 0
    assert status["last_error"] is None
    assert status["last_ran_count"] == 1
    assert status["last_recovered"] == {"requeued": 0, "failed": 0}
    assert status["last_success_at"]


def test_tick_once_records_recovered_stale_health(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    task = aw.assign("t", "worker", "recover during tick", actor="u")
    assert aw.claim(task.task_id) is True
    with aw._lock, sqlite3.connect(str(aw._db)) as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE async_tasks SET updated_at='2000-01-01T00:00:00+00:00' WHERE task_id=?",
            (task.task_id,),
        )
    runner = AsyncWorkRunner(aw, gs, lambda t, c: "rerun", recover_stale_seconds=1)

    assert runner.tick_once() == 1

    status = runner.status()
    assert status["total_ticks"] == 1
    assert status["last_recovered"] == {"requeued": 1, "failed": 0}
    assert status["last_ran_count"] == 1


def test_tick_once_records_failure_health(tmp_path, monkeypatch) -> None:
    gs, aw = _setup(tmp_path)
    runner = AsyncWorkRunner(aw, gs, lambda t, c: "r")

    monkeypatch.setattr(
        aw, "threads_with_pending", lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    )

    assert runner.tick_once() == 0

    status = runner.status()
    assert status["total_ticks"] == 1
    assert status["total_failures"] == 1
    assert status["consecutive_failures"] == 1
    assert status["last_error"] == "RuntimeError: db down"
    assert status["last_failure_at"]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows cannot delete an open sqlite file; removed-under-live-store is a POSIX-only scenario",
)
def test_tick_once_self_heals_missing_async_work_directory(tmp_path) -> None:
    base_dir = tmp_path / "cowork"
    gs = GroupStore(base_dir=base_dir)
    aw = AsyncWorkStore(base_dir=base_dir, group_store=gs)
    runner = AsyncWorkRunner(aw, gs, lambda t, c: "r")

    shutil.rmtree(base_dir)

    assert runner.tick_once() == 0
    assert base_dir.exists()
    assert aw._db.exists()  # noqa: SLF001 - verifies storage self-heal path
    status = runner.status()
    assert status["total_ticks"] == 1
    assert status["total_failures"] == 0
    assert status["last_error"] is None


def test_drain_all_recovers_stale_working_before_polling(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    task = aw.assign("t", "worker", "recover during drain", actor="u")
    assert aw.claim(task.task_id) is True
    with aw._lock, sqlite3.connect(str(aw._db)) as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE async_tasks SET updated_at='2000-01-01T00:00:00+00:00' WHERE task_id=?",
            (task.task_id,),
        )

    runner = AsyncWorkRunner(
        aw,
        gs,
        lambda t, c: f"rerun: {t.prompt}",
        recover_stale_seconds=1,
    )

    assert runner.drain_all() == 1
    finished = aw.get(task.task_id)
    assert finished.status == "done"
    assert finished.attempts == 2
    assert finished.result == "rerun: recover during drain"


def test_stale_working_tasks_are_recovered_or_failed(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    retry = aw.assign("t", "worker", "retry me", actor="u")
    fail = aw.assign("t", "worker", "give up", actor="u")
    assert aw.claim(retry.task_id) is True
    assert aw.claim(fail.task_id) is True

    with aw._lock, sqlite3.connect(str(aw._db)) as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE async_tasks SET updated_at='2000-01-01T00:00:00+00:00' WHERE task_id=?",
            (retry.task_id,),
        )
        conn.execute(
            "UPDATE async_tasks SET updated_at='2000-01-01T00:00:00+00:00', attempts=3 "
            "WHERE task_id=?",
            (fail.task_id,),
        )

    recovered = aw.recover_stale_working(max_age_seconds=1, max_attempts=3)

    assert recovered == {"requeued": 1, "failed": 1}
    assert aw.get(retry.task_id).status == "pending"
    assert aw.get(fail.task_id).status == "failed"


def test_stale_staged_retry_settles_reopened_collector_after_restart(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    collaboration = CollaborationStore(base_dir=tmp_path)
    collaboration.create_collaboration_run(
        run_id="retry-crash",
        session_id="t",
        kind="group_fanout",
    )
    collaboration.claim_collaboration_run("retry-crash", worker_id="coordinator")
    collaboration.create_collaboration_collector(
        run_id="retry-crash",
        child_ids=["worker"],
    )
    collaboration.record_collaboration_collector_result(
        "retry-crash",
        child_id="worker",
        status="failed",
        result={"error": "provider timeout"},
    )
    task = aw.stage_batch(
        "t",
        [("retry-crash-task", "worker", "retry focused task")],
        actor="user",
    )[0]
    collaboration.bind_collaboration_collector_retry_task(
        "retry-crash",
        child_id="worker",
        task_id=task.task_id,
    )
    collaboration.reopen_collaboration_collector("retry-crash", child_ids=["worker"])
    with aw._lock, sqlite3.connect(str(aw._db)) as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE async_tasks SET updated_at='2000-01-01T00:00:00+00:00' WHERE task_id=?",
            (task.task_id,),
        )

    runner = AsyncWorkRunner(
        aw,
        gs,
        lambda _task, _context: "unused",
        completion_observer=_collector_completion_observer(collaboration),
        recover_stale_seconds=1,
    )

    assert runner.recover_stale() == {"requeued": 0, "failed": 1}
    collector = collaboration.collaboration_collector("retry-crash")
    assert collector is not None
    assert collector["status"] == "completed"
    assert collector["generation"] == 2
    assert collector["attempt_count"] == 2
    assert collector["results"][0]["attempt"] == 2
    assert collector["results"][0]["status"] == "failed"
    assert collector["results"][0]["result"]["error"] == "task staging did not complete"


def test_runtime_dispatches_through_subagent_bridge(tmp_path, monkeypatch) -> None:
    from runtime.execution.subagents import get_sub_agent_runner, set_sub_agent_runner

    seen = {}

    def fake_call_subagent(agent_id, prompt, **kwargs):
        seen["agent_id"] = agent_id
        seen["prompt"] = prompt
        seen["context"] = kwargs["context"]
        return {"success": True, "output": "worker result"}

    previous_runner = get_sub_agent_runner()
    monkeypatch.setattr("runtime.execution.subagents.call_subagent", fake_call_subagent)
    set_sub_agent_runner(lambda **_kwargs: "available")
    try:
        runtime = create_cowork_runtime(base_dir=tmp_path, enable_runner=True)
        runtime.group_store.append(
            "t",
            MemberEvent(action="invite", actor="u", target_id="worker"),
        )
        task = runtime.async_store.assign("t", "worker", "do background work", actor="u")

        assert runtime.runner.drain("t") == 1
        assert runtime.async_store.get(task.task_id).status == "done"
        assert seen["agent_id"] == "worker"
        assert seen["prompt"] == "do background work"
        assert seen["context"]["source"] == "cowork_async_task"
        assert runtime.group_store.blackboard_snapshot("t")
        status = runtime.status("t")
        assert status["runner_status"]["total_ticks"] == 0
        assert status["runner_status"]["last_error"] is None
    finally:
        set_sub_agent_runner(previous_runner)


def test_runtime_does_not_enable_runner_without_subagent_executor(tmp_path) -> None:
    runtime = create_cowork_runtime(base_dir=tmp_path, enable_runner=True)

    assert runtime.runner is None
    assert runtime.runner_enabled is False
    assert "not configured" in runtime.runner_reason
    assert runtime.status("t")["task_counts"] == {
        "pending": 0,
        "working": 0,
        "done": 0,
        "failed": 0,
        "cancelled": 0,
    }


def test_runtime_applies_configured_collector_retention_on_startup(
    tmp_path,
    monkeypatch,
) -> None:
    first = create_cowork_runtime(base_dir=tmp_path, enable_runner=False)
    store = first.collaboration_store
    store.create_collaboration_run(
        run_id="startup-retention",
        session_id="retention-thread",
        kind="group_fanout",
    )
    store.claim_collaboration_run("startup-retention", worker_id="worker-a")
    store.create_collaboration_collector(
        run_id="startup-retention",
        child_ids=["worker"],
    )
    store.record_collaboration_collector_result(
        "startup-retention",
        child_id="worker",
        status="success",
        result={"reply": "old body"},
    )
    store.transition_collaboration_run("startup-retention", status="completed")
    with sqlite3.connect(tmp_path / "collaboration.db") as conn:
        conn.execute(
            "UPDATE collaboration_collectors SET updated_at='2020-01-01T00:00:00+00:00' "
            "WHERE run_id='startup-retention'"
        )
    monkeypatch.setenv("OCTOPUS_COWORK_COLLECTOR_RETENTION_SECONDS", "1")
    monkeypatch.setenv("OCTOPUS_COWORK_COLLECTOR_RETENTION_COUNT", "0")

    restarted = create_cowork_runtime(base_dir=tmp_path, enable_runner=False)

    assert restarted.collector_retention == {
        "archived": 1,
        "run_ids": ["startup-retention"],
    }
    assert (
        restarted.collaboration_store.collaboration_collector("startup-retention")["archived"]
        is True
    )


def test_runtime_reads_queue_and_scheduler_limits_from_environment(
    tmp_path,
    monkeypatch,
) -> None:
    from runtime.execution.subagents import get_sub_agent_runner, set_sub_agent_runner

    previous_runner = get_sub_agent_runner()
    monkeypatch.setenv("OCTOPUS_COWORK_QUEUE_PER_THREAD_LIMIT", "2")
    monkeypatch.setenv("OCTOPUS_COWORK_QUEUE_TOTAL_LIMIT", "3")
    monkeypatch.setenv("OCTOPUS_COWORK_RUNNER_MAX_CONCURRENCY", "2")
    monkeypatch.setenv("OCTOPUS_COWORK_RUNNER_MAX_TASKS_PER_TICK", "5")
    set_sub_agent_runner(lambda **_kwargs: "available")
    try:
        runtime = create_cowork_runtime(base_dir=tmp_path, enable_runner=True)
        status = runtime.status("t")
        assert status["queue_health"]["thread_limit"] == 2
        assert status["queue_health"]["total_limit"] == 3
        assert status["runner_status"]["max_concurrency"] == 2
        assert status["runner_status"]["max_tasks_per_tick"] == 5
    finally:
        set_sub_agent_runner(previous_runner)

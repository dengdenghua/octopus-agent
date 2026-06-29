"""AsyncWorkRunner: drives pending tasks via an injected executor (no LLM)."""

from __future__ import annotations

from runtime.memory.cowork import service
from runtime.memory.cowork.async_runner import AsyncWorkRunner
from runtime.memory.cowork.async_work import AsyncWorkStore
from runtime.memory.cowork.group import ContextGrant
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.nominate import CompetenceStore


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


def test_runner_passes_grant_sliced_history(tmp_path) -> None:
    gs, aw = _setup(tmp_path)
    # worker joined at message 5 with from_join → should only see messages 5..
    service.invite_member(gs, "t", actor="u", target_id="worker", kind="agent",
                          grant=ContextGrant(scope="from_join"), at_message=5)
    captured = {}

    def execute(task, context):
        captured["history"] = context["history"]
        captured["scope"] = context["grant_scope"]
        return "ok"

    runner = AsyncWorkRunner(aw, gs, execute, history_provider=lambda _t: [f"m{i}" for i in range(10)])
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

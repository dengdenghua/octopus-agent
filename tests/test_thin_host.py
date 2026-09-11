"""External execution keeps durable host services without extra model hops."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from runtime.memory.threads.compaction import CompactionPolicy
from runtime.memory.threads.event_log import EventLog
from runtime.protocol.items import AgentMessageItem, Turn, TurnParams, TurnStatus
from runtime.safety.approval.guardian_review import (
    AutoReviewApprovalProvider,
    approval_router_for_stack,
)
from runtime.sensing.gateway.realtime_thread_ops import _maybe_compact_locked, compact_thread
from runtime.sensing.gateway.realtime_turn_input import external_model_owner


@pytest.mark.parametrize("engine", ["opencode", "codex", "octopus"])
@pytest.mark.parametrize("manual", [False, True])
def test_history_compacts_durably_without_extra_external_engine_model_call(
    tmp_path, engine, manual
):
    from runtime.platform.process.keyed_lock import KeyedLock

    log = EventLog(tmp_path / "history.jsonl")
    log.thread_started("thread")
    original_ids = []
    for index in range(5):
        turn = Turn(threadId="thread")
        original_ids.append(turn.id)
        log.turn_started("thread", turn)
        log.turn_updated(
            "thread",
            turn.id,
            execution={
                "engine": engine,
                "driver": "react" if engine == "octopus" else f"{engine}_server",
                "phase": "primary",
                "invocation": 1,
                "reason": "explicit_engine",
            },
        )
        item = AgentMessageItem(text=f"Result {index}: recorded evidence")
        log.item_started("thread", turn.id, item)
        log.item_completed("thread", turn.id, item)
        log.turn_completed("thread", turn.id, TurnStatus.COMPLETED)
    router = Mock()
    router.call.return_value = SimpleNamespace(text="Summarized history")
    runtime = SimpleNamespace(
        _compaction_policy=CompactionPolicy(trigger_at=5, keep_recent=2),
        _summary_router=router,
        _compaction_locks=KeyedLock(),
        _log_for=lambda _: log,
    )
    emitter = SimpleNamespace(notify=AsyncMock())
    if manual:
        result = asyncio.run(compact_thread(runtime, "thread", emitter))
        assert result["compacted"] is True
    else:
        asyncio.run(_maybe_compact_locked(runtime, "thread", log, emitter))
    replayed = EventLog(log.path).replay()
    assert len(replayed) == 3
    assert [t.id for t in replayed[-2:]] == original_ids[-2:]
    assert replayed[0].items
    assert emitter.notify.await_count == 2
    assert router.call.call_count == (1 if engine == "octopus" else 0)


def test_independent_approval_service_does_not_touch_planner():
    reviewer = object()

    class Host:
        approval_router = reviewer

        @property
        def planner(self):
            raise AssertionError("native planner must not be loaded for approval")

    assert approval_router_for_stack(Host()) is reviewer
    assert (
        approval_router_for_stack(
            SimpleNamespace(
                approval_router=None,
                planner=SimpleNamespace(router=reviewer),
            )
        )
        is None
    )
    assert (
        approval_router_for_stack(SimpleNamespace(planner=SimpleNamespace(router=reviewer)))
        is reviewer
    )


def test_missing_review_service_denies_without_running_native_planner():
    from runtime.safety.approval.approval_gate import ApprovalRequest

    provider = AutoReviewApprovalProvider(
        approval_router_for_stack(SimpleNamespace(approval_router=None)),
        user_intent="run tests",
    )
    decision = provider.request(
        ApprovalRequest(
            thread_id="thread",
            tool_name="exec_shell",
            tool_call_id="call",
            args_preview="pytest",
        )
    )
    assert decision.approved is False


@pytest.mark.parametrize("ready", [False, True])
def test_opencode_admission_is_scoped_and_never_probes_native_or_codex(monkeypatch, ready):
    from runtime.execution.engines import EngineSelectionError
    from runtime.platform.models import ParsedIntent
    from runtime.sensing.gateway.realtime_execution import select_turn_execution

    probe = Mock(return_value={"available": ready, "reason": None if ready else "offline"})
    monkeypatch.setattr("runtime.execution.opencode_backend.inspect_readiness", probe)
    other = Mock(side_effect=AssertionError("must not probe another engine"))
    monkeypatch.setattr(
        "runtime.sensing.gateway.realtime_execution.codex_readiness_for_turn", other
    )
    turn = Turn(
        threadId="thread",
        params=TurnParams(
            threadId="thread",
            executionEngine="opencode",
            owner_actor_id="alice",
            tenant_id="tenant",
        ),
    )
    request = select_turn_execution(
        object(),
        turn,
        object(),
        ParsedIntent(
            raw="task",
            normalized_goal="task",
            intent_type="task",
        ),
        project_command=False,
        group_fanout=False,
        topology_id=None,
        codex_partner=False,
        reflection_fast_path=True,
    )
    if ready:
        assert asyncio.run(request).engine == "opencode"
    else:
        with pytest.raises(EngineSelectionError, match="offline"):
            asyncio.run(request)
    scope = probe.call_args.args[0]
    assert (scope.actor_id, scope.tenant_id) == ("alice", "tenant")
    other.assert_not_called()


@pytest.mark.parametrize(
    "selected,preview,expected",
    [
        ("opencode", "codex", "opencode"),
        ("codex", "opencode", "codex"),
        ("octopus", "opencode", None),
        ("auto", "opencode", "opencode"),
        ("auto", "codex", "codex"),
        ("auto", "garbage", None),
    ],
)
def test_external_model_owner_does_not_override_explicit_native_choice(selected, preview, expected):
    params = TurnParams(
        threadId="thread",
        executionEngine=selected,
        input=[
            {
                "type": "text",
                "text": "task",
                "metadata": {"context": {"execution_engine": preview}},
            }
        ],
    )
    assert external_model_owner(params) == expected

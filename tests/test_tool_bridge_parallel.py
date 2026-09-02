"""Tests for the lane-B parallel tool execution path in tool_bridge.

The native tool loop in ``runtime.sensing.gateway.tool_bridge`` now runs
multiple independent ``tool_use`` blocks concurrently in a single
agent message round, rather than serially. These tests pin:

  * ordering: tool_result blocks come back in the order the assistant
    emitted the tool_use blocks (not in completion order)
  * disabled by stack metadata: ``parallel_tool_use=False`` falls back
    to the serial path
  * serial-barrier tools (``todo_write`` / ``exit_plan_mode``) force
    serial execution even when otherwise parallelizable
  * single-tool rounds always go serial (no thread-pool overhead)
  * concurrency speedup: 3 calls each "sleeping" 80ms wall-clock should
    finish in roughly 80ms (parallel) rather than 240ms (serial)
"""

from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace

import pytest

import runtime.sensing.gateway.tool_bridge as tool_bridge
from runtime.execution.suckers.builtins import _list_cwd, _read_file
from runtime.execution.suckers.registry import Skill, SkillRegistry
from runtime.execution.tool_engine.executor import ToolExecutor
from runtime.memory.journal import InMemoryJournal, journal_context
from runtime.platform.models import CostEntry, ParsedIntent
from runtime.platform.process.session import Session, session_scope
from runtime.platform.process.streaming import stream_run
from runtime.safety.approval.cancellation import (
    CancellationSource,
    current_cancellation_token,
    scoped_cancellation,
)
from runtime.safety.auth import TrustEngine
from runtime.sensing.gateway._tool_bridge_loop import (
    _native_plan_reconciliation_milestones,
)
from runtime.sensing.gateway.tool_bridge import stream_agentic_fallback
from runtime.sensing.model_router.models import (
    ModelResponse,
    ModelStreamEvent,
    ToolCall,
)


def _agent():
    return SimpleNamespace(
        agent_id="coder",
        capabilities={"code_mode_unlock": True},
        soul="",
    )


def test_native_plan_reconciliation_detects_only_successful_post_todo_milestones() -> None:
    calls = [
        ToolCall(id="todo", name="todo_write", input={"items": []}),
        ToolCall(id="write", name="edit_file", input={"path": "app.py"}),
        ToolCall(id="verify", name="run_tests", input={}),
        ToolCall(id="read", name="read_file", input={"path": "app.py"}),
    ]
    blocks = [
        {"tool_use_id": "todo", "content": "ok"},
        {"tool_use_id": "write", "content": "ok"},
        {"tool_use_id": "verify", "content": "failed", "is_error": True},
        {"tool_use_id": "read", "content": "source"},
    ]

    assert _native_plan_reconciliation_milestones(calls, blocks) == ["workspace/document write"]


def test_native_plan_reconciliation_ignores_milestones_before_latest_todo() -> None:
    calls = [
        ToolCall(id="write", name="edit_file", input={"path": "README.md"}),
        ToolCall(id="todo", name="todo_write", input={"items": []}),
    ]
    blocks = [
        {"tool_use_id": "write", "content": "ok"},
        {"tool_use_id": "todo", "content": "ok"},
    ]

    assert _native_plan_reconciliation_milestones(calls, blocks) == []


def _slow_sum_handler(a: int = 0, b: int = 0, sleep_ms: int = 80) -> dict:
    time.sleep(sleep_ms / 1000.0)
    return {"sum": a + b}


def _make_stack(router, *, metadata: dict | None = None):
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="slow_sum",
            description="Add two numbers slowly.",
            affinity=["math"],
            trusted_source="skill://public/slow_sum",
            handler=_slow_sum_handler,
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="todo_write",
            description="Update todo list.",
            affinity=["meta"],
            trusted_source="skill://public/todo_write",
            handler=lambda **kw: {"ok": True},
        ),
        verify_tests=False,
    )
    return SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
        metadata=metadata or {},
    )


class _RouterEmitting:
    """Mock router that emits a configurable list of tool_use blocks
    on the first round, then text on the second."""

    def __init__(self, calls_round1: list[ToolCall]):
        self._calls_round1 = calls_round1
        self.calls = 0

    def call_stream(self, req):
        self.calls += 1
        if self.calls == 1:
            for c in self._calls_round1:
                yield ModelStreamEvent(type="tool_use", tool_call=c)
            yield ModelStreamEvent(type="done", final=ModelResponse(text="", tool_calls=[]))
            return
        yield ModelStreamEvent(type="text_delta", delta="done")
        yield ModelStreamEvent(type="done", final=ModelResponse(text="done"))


def _intent():
    return ParsedIntent(
        raw="add three pairs in parallel",
        intent_type="task",
        normalized_goal="add three pairs",
        user_context={
            "conversation_id": "thread-parallel",
            "metadata": {"mode": "code"},
        },
    )


def test_parallel_path_preserves_emission_order() -> None:
    calls = [
        ToolCall(id=f"t-{i}", name="slow_sum", input={"a": i, "b": 1, "sleep_ms": 50})
        for i in range(3)
    ]
    router = _RouterEmitting(calls)
    events = list(stream_agentic_fallback(_make_stack(router), _intent(), _agent()))

    tool_end_events = [e for e in events if e[0] == "tool_end"]
    assert len(tool_end_events) == 3
    # Order must match the assistant's emission order, not whichever
    # finished first.
    assert [e[1]["id"] for e in tool_end_events] == ["t-0", "t-1", "t-2"]
    # And every tool_end on the parallel path carries the marker.
    assert all(e[1].get("parallel") is True for e in tool_end_events)


def test_native_tool_turn_persists_one_learnable_trajectory() -> None:
    """Executor step receipts must be grouped into one terminal turn sample."""

    calls = [
        ToolCall(id=f"traj-{i}", name="slow_sum", input={"a": i, "b": 1, "sleep_ms": 0})
        for i in range(3)
    ]
    stack = _make_stack(_RouterEmitting(calls))
    # Production app wiring keeps these references identical. Make that
    # contract explicit for this lightweight stack double.
    stack.journal = stack.executor.journal

    events = list(stream_agentic_fallback(stack, _intent(), _agent()))

    assert any(event[0] == "done" for event in events)
    trajectory_events = stack.journal.read_by_type("trajectory")
    assert len(trajectory_events) == 1
    trajectory_event = trajectory_events[0]
    trajectory = trajectory_event.trajectory
    assert trajectory.strategy_id == "native_tool_loop"
    assert trajectory.thread_id == "thread-parallel"
    assert trajectory.outcome.success is True
    assert trajectory.outcome.degraded is False
    assert [step.step_id for step in trajectory.steps] == [0, 1, 2]
    assert [str(step.action.sucker_id) for step in trajectory.steps] == [
        "slow_sum",
        "slow_sum",
        "slow_sum",
    ]
    assert trajectory_event.agent_id == "coder"
    step_events = stack.journal.read_by_type("step")
    assert {event.task_id for event in step_events} == {trajectory.task_id}


def test_native_tool_turn_uses_ordinals_when_provider_reuses_call_id() -> None:
    calls = [
        ToolCall(id="reused", name="slow_sum", input={"a": 1, "b": 1, "sleep_ms": 40}),
        ToolCall(id="reused", name="slow_sum", input={"a": 20, "b": 1, "sleep_ms": 0}),
    ]
    stack = _make_stack(_RouterEmitting(calls))
    stack.journal = stack.executor.journal

    events = list(stream_agentic_fallback(stack, _intent(), _agent()))

    tool_ends = [event for event in events if event[0] == "tool_end"]
    assert len(tool_ends) == 2
    assert [event[1]["id"] for event in tool_ends] == ["reused", "reused"]
    assert '"sum":2' in tool_ends[0][1]["output"].replace(" ", "")
    assert '"sum":21' in tool_ends[1][1]["output"].replace(" ", "")

    trajectory = stack.journal.read_by_type("trajectory")[0].trajectory
    assert [step.step_id for step in trajectory.steps] == [0, 1]
    assert [step.action.args["a"] for step in trajectory.steps] == [1, 20]


def test_native_tool_turn_marks_bridge_only_error_as_degraded() -> None:
    calls = [
        ToolCall(id="valid", name="slow_sum", input={"a": 1, "b": 1, "sleep_ms": 0}),
        ToolCall(id="missing", name="not_registered", input={}),
    ]
    stack = _make_stack(_RouterEmitting(calls))
    stack.journal = stack.executor.journal

    events = list(stream_agentic_fallback(stack, _intent(), _agent()))

    tool_ends = [event for event in events if event[0] == "tool_end"]
    assert [event[1]["is_error"] for event in tool_ends] == [False, True]
    trajectory = stack.journal.read_by_type("trajectory")[0].trajectory
    assert trajectory.outcome.success is True
    assert trajectory.outcome.degraded is True
    assert trajectory.outcome.disposition == "completed_with_warning"
    assert [step.step_id for step in trajectory.steps] == [0, 1]
    assert trajectory.steps[1].result.status == "failed"
    assert trajectory.steps[1].result.error_type == "skill_not_found"


def test_native_tool_turn_persists_missing_only_as_degraded_trajectory() -> None:
    stack = _make_stack(_RouterEmitting([ToolCall(id="missing", name="not_registered", input={})]))
    stack.journal = stack.executor.journal

    events = list(stream_agentic_fallback(stack, _intent(), _agent()))

    tool_end = next(event for event in events if event[0] == "tool_end")
    assert tool_end[1]["is_error"] is True
    trajectory_events = stack.journal.read_by_type("trajectory")
    assert len(trajectory_events) == 1
    trajectory = trajectory_events[0].trajectory
    assert trajectory.outcome.success is True
    assert trajectory.outcome.degraded is True
    assert trajectory.outcome.disposition == "completed_with_warning"
    assert len(trajectory.steps) == 1
    assert str(trajectory.steps[0].action.sucker_id) == "not_registered"
    assert trajectory.steps[0].result.status == "failed"
    assert trajectory.steps[0].result.error_type == "skill_not_found"


def test_native_tool_turn_finalizes_once_when_generator_is_closed() -> None:
    stack = _make_stack(
        _RouterEmitting([ToolCall(id="close-me", name="slow_sum", input={"a": 1, "b": 1})])
    )
    stack.journal = stack.executor.journal
    stream = stream_agentic_fallback(stack, _intent(), _agent())

    assert next(event for event in stream if event[0] == "tool_end")[0] == "tool_end"
    stream.close()
    stream.close()

    trajectory_events = stack.journal.read_by_type("trajectory")
    assert len(trajectory_events) == 1
    trajectory = trajectory_events[0].trajectory
    assert trajectory.outcome.success is False
    assert trajectory.outcome.disposition == "cancelled"
    assert [step.step_id for step in trajectory.steps] == [0]


def test_native_tool_turn_finalizes_checkpoint_exception_once(monkeypatch) -> None:
    class Router:
        def __init__(self) -> None:
            self.calls = 0

        def call_stream(self, req):
            del req
            self.calls += 1
            if self.calls == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(id="before-checkpoint", name="slow_sum", input={}),
                )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            raise ValueError("checkpoint parser exploded")

    monkeypatch.setattr(tool_bridge, "MAX_TOOL_ROUNDS", 1)
    stack = _make_stack(Router())
    stack.journal = stack.executor.journal

    with pytest.raises(ValueError, match="checkpoint parser exploded"):
        list(stream_agentic_fallback(stack, _intent(), _agent()))

    trajectory_events = stack.journal.read_by_type("trajectory")
    assert len(trajectory_events) == 1
    trajectory = trajectory_events[0].trajectory
    assert trajectory.outcome.success is False
    assert trajectory.outcome.disposition == "failed"
    assert [step.step_id for step in trajectory.steps] == [0]


def test_native_turn_budget_and_trajectory_use_exact_model_plus_step_cost() -> None:
    first_cost = CostEntry(tokens_in=31, tokens_out=7, usd=0.40)
    second_cost = CostEntry(tokens_in=19, tokens_out=5, usd=0.20)

    class Router:
        def __init__(self) -> None:
            self.calls = 0

        def call_stream(self, req):
            del req
            self.calls += 1
            if self.calls == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(id="costed", name="slow_sum", input={"a": 2, "b": 3}),
                )
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(
                        text="",
                        input_tokens=first_cost.tokens_in,
                        output_tokens=first_cost.tokens_out,
                        cost=first_cost,
                    ),
                )
                return
            yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(
                    text="done",
                    input_tokens=second_cost.tokens_in,
                    output_tokens=second_cost.tokens_out,
                    cost=second_cost,
                ),
            )

    class RecordingExecutor(ToolExecutor):
        def __init__(self, registry, immunity) -> None:
            super().__init__(registry, immunity)
            self.seen_budgets = []

        def execute_step(self, *args, **kwargs):
            self.seen_budgets.append(kwargs["budget"])
            return super().execute_step(*args, **kwargs)

    stack = _make_stack(Router())
    recording_executor = RecordingExecutor(stack.executor.registry, TrustEngine())
    stack.executor = recording_executor
    stack.journal = recording_executor.journal
    budget_intent = ParsedIntent(
        raw="calculate one value",
        intent_type="task",
        normalized_goal="calculate one value",
        user_context={"conversation_id": "thread-budget-cost"},
    )

    list(stream_agentic_fallback(stack, budget_intent, _agent()))

    trajectory = stack.journal.read_by_type("trajectory")[0].trajectory
    step_cost = trajectory.steps[0].result.cost
    expected_model_tokens = first_cost.tokens + second_cost.tokens
    expected_model_usd = first_cost.usd + second_cost.usd
    assert trajectory.outcome.cost.tokens == expected_model_tokens + step_cost.tokens
    assert trajectory.outcome.cost.usd == pytest.approx(expected_model_usd + step_cost.usd)
    assert len(recording_executor.seen_budgets) == 1
    turn_budget = recording_executor.seen_budgets[0]
    assert turn_budget.tokens_spent == trajectory.outcome.cost.tokens
    assert turn_budget.usd_spent == pytest.approx(trajectory.outcome.cost.usd)


def test_model_actual_budget_overrun_blocks_returned_tool_calls() -> None:
    executed = threading.Event()
    over_limit = CostEntry(tokens_in=100_001, tokens_out=1, usd=11.0)

    def must_not_run(a: int = 0, b: int = 0, sleep_ms: int = 0) -> dict:
        del a, b, sleep_ms
        executed.set()
        return {"ok": True}

    registry = SkillRegistry()
    for skill in (
        Skill(
            name="slow_sum",
            description="Must be blocked after model budget overrun.",
            affinity=["math"],
            trusted_source="skill://public/slow_sum",
            handler=must_not_run,
        ),
        Skill(
            name="todo_write",
            description="Update todo list.",
            affinity=["meta"],
            trusted_source="skill://public/todo_write",
            handler=lambda **_kwargs: {"ok": True},
        ),
    ):
        registry.register(skill, verify_tests=False)

    class Router:
        def call_stream(self, req):
            del req
            yield ModelStreamEvent(
                type="tool_use",
                tool_call=ToolCall(id="over-budget", name="slow_sum", input={}),
            )
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(
                    text="",
                    input_tokens=over_limit.tokens_in,
                    output_tokens=over_limit.tokens_out,
                    cost=over_limit,
                ),
            )

    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=Router(), planner_model="mock"),
        metadata={},
    )

    events = list(stream_agentic_fallback(stack, _intent(), _agent()))

    assert not executed.is_set()
    assert stack.executor.journal.read_by_type("step") == []
    assert any(
        event[0] == "error" and event[1].get("kind") == "budget_exceeded" for event in events
    )
    trajectory = stack.executor.journal.read_by_type("trajectory")[0].trajectory
    assert trajectory.outcome.success is False
    assert trajectory.outcome.degraded is True
    assert trajectory.outcome.disposition == "failed"
    assert trajectory.outcome.cost.tokens == over_limit.tokens
    assert trajectory.outcome.cost.usd == pytest.approx(over_limit.usd)
    assert trajectory.steps[0].result.error_type == "budget_exceeded"


def test_pure_model_actual_budget_overrun_persists_a_bounded_failed_trajectory() -> None:
    over_limit = CostEntry(tokens_in=100_001, tokens_out=1, usd=11.0)

    class Router:
        def call_stream(self, req):
            del req
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(
                    text="too expensive",
                    input_tokens=over_limit.tokens_in,
                    output_tokens=over_limit.tokens_out,
                    cost=over_limit,
                ),
            )

    stack = _make_stack(Router())
    stack.journal = stack.executor.journal

    events = list(stream_agentic_fallback(stack, _intent(), _agent()))

    assert any(
        event[0] == "error" and event[1].get("kind") == "budget_exceeded" for event in events
    )
    trajectory = stack.journal.read_by_type("trajectory")[0].trajectory
    assert trajectory.outcome.success is False
    assert trajectory.outcome.degraded is True
    assert trajectory.outcome.disposition == "failed"
    assert trajectory.outcome.cost.tokens == over_limit.tokens
    assert len(trajectory.steps) == 1
    step = trajectory.steps[0]
    assert str(step.action.sucker_id) == "native_model_response"
    assert step.result.status == "failed"
    assert step.result.error_type == "budget_exceeded"


def test_native_finalizer_retries_same_frozen_event_after_temporary_write_failure() -> None:
    class FailOnceJournal(InMemoryJournal):
        def __init__(self) -> None:
            super().__init__()
            self.trajectory_write_calls = 0

        def write_trajectory_once(self, event):
            self.trajectory_write_calls += 1
            if self.trajectory_write_calls == 1:
                raise OSError("temporary journal failure")
            return super().write_trajectory_once(event)

    stack = _make_stack(
        _RouterEmitting([ToolCall(id="retry-persist", name="slow_sum", input={"a": 1, "b": 2})])
    )
    journal = FailOnceJournal()
    stack.executor.journal = journal
    stack.journal = journal

    events = list(stream_agentic_fallback(stack, _intent(), _agent()))

    assert any(event[0] == "done" for event in events)
    assert journal.trajectory_write_calls == 2
    trajectories = journal.read_by_type("trajectory")
    assert len(trajectories) == 1
    assert trajectories[0].trajectory.outcome.success is True


def test_native_tool_turn_preserves_authoritative_realtime_scope() -> None:
    call = ToolCall(id="scoped", name="slow_sum", input={"a": 1, "b": 1, "sleep_ms": 0})
    stack = _make_stack(_RouterEmitting([call]))
    stack.journal = stack.executor.journal
    agent = _agent()
    intent = ParsedIntent(
        raw="run the scoped tool",
        intent_type="task",
        normalized_goal="run the scoped tool",
        user_context={},
    )
    turn_session = Session(
        actor="owner-a",
        agent=agent,
        thread_id="real-thread",
        conversation_id="real-thread",
        metadata={"tenant_id": "tenant-a", "owner_actor_id": "owner-a"},
    )

    with (
        session_scope(turn_session),
        journal_context(
            agent_id="coder",
            conversation_id="real-thread",
            tenant_id="tenant-a",
            owner_actor_id="owner-a",
        ),
    ):
        list(stream_agentic_fallback(stack, intent, agent))

    trajectory_event = stack.journal.read_by_type("trajectory")[0]
    assert trajectory_event.conversation_id == "real-thread"
    assert trajectory_event.trajectory.thread_id == "real-thread"
    assert trajectory_event.agent_id == "coder"
    assert trajectory_event.tenant_id == "tenant-a"
    assert trajectory_event.owner_actor_id == "owner-a"
    assert trajectory_event.actor == "owner-a"


def test_native_tool_turn_does_not_promote_confidential_trace() -> None:
    call = ToolCall(id="private", name="slow_sum", input={"a": 1, "b": 1, "sleep_ms": 0})
    stack = _make_stack(_RouterEmitting([call]))
    stack.journal = stack.executor.journal
    intent = ParsedIntent(
        raw="private calculation",
        intent_type="task",
        normalized_goal="private calculation",
        privacy="confidential",
    )

    list(stream_agentic_fallback(stack, intent, _agent()))

    assert len(stack.journal.read_by_type("step")) == 1
    assert stack.journal.read_by_type("trajectory") == []


def test_late_steering_supersedes_a_provisional_final_answer() -> None:
    class Router:
        def __init__(self) -> None:
            self.requests = []

        def call_stream(self, req):
            self.requests.append(req)
            text = "old answer" if len(self.requests) == 1 else "corrected answer"
            yield ModelStreamEvent(type="text_delta", delta=text)
            yield ModelStreamEvent(type="done", final=ModelResponse(text=text))

    router = Router()
    drains = iter([[], ["先核对数据再回答"], [], []])
    intent = ParsedIntent(
        raw="summarize the result",
        intent_type="task",
        normalized_goal="summarize the result",
        user_context={"conversation_id": "thread-steer", "metadata": {"mode": "chat"}},
    )
    events = list(
        stream_agentic_fallback(
            _make_stack(router),
            intent,
            _agent(),
            steering_drain=lambda: next(drains, []),
        )
    )

    assert len(router.requests) == 2
    assert any(
        message.role == "user" and message.content == "先核对数据再回答"
        for message in router.requests[1].messages
    )
    assert "old answer" not in "".join(str(event[1]) for event in events if event[0] == "text")
    assert "corrected answer" in "".join(str(event[1]) for event in events if event[0] == "text")


def test_continuation_steering_starts_with_priority_response_protocol() -> None:
    class Router:
        def __init__(self) -> None:
            self.requests = []

        def call_stream(self, req):
            self.requests.append(req)
            yield ModelStreamEvent(type="text_delta", delta="已先回答，再继续。")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="已先回答，再继续。"),
            )

    router = Router()
    intent = ParsedIntent(
        raw="什么情况？",
        intent_type="task",
        normalized_goal="什么情况？",
        user_context={
            "conversation_id": "thread-steer-continuation",
            "live_steering": True,
        },
    )

    list(stream_agentic_fallback(_make_stack(router), intent, _agent()))

    messages = router.requests[0].messages
    user_index = max(index for index, message in enumerate(messages) if message.role == "user")
    assert messages[user_index].content == "什么情况？"
    assert messages[user_index - 1].role == "system"
    assert "LIVE USER FOLLOW-UP — HIGH PRIORITY" in str(messages[user_index - 1].content)


def test_steering_cancels_a_cooperative_tool_and_continues_the_same_turn() -> None:
    started = threading.Event()
    cancelled = threading.Event()

    def wait_for_signal(a: int = 0, b: int = 0, sleep_ms: int = 0) -> dict:
        started.set()
        token = current_cancellation_token()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not token.is_cancelled:
            time.sleep(0.01)
        if token.is_cancelled:
            cancelled.set()
            return {"error": token.reason}
        return {"ok": True}

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="slow_sum",
            description="Wait until redirected.",
            affinity=["io"],
            trusted_source="skill://public/slow_sum",
            handler=wait_for_signal,
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="todo_write",
            description="Update todo list.",
            affinity=["meta"],
            trusted_source="skill://public/todo_write",
            handler=lambda **_kwargs: {"ok": True},
        ),
        verify_tests=False,
    )

    class Router:
        def __init__(self) -> None:
            self.requests = []

        def call_stream(self, req):
            self.requests.append(req)
            if len(self.requests) == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(id="wait-1", name="slow_sum", input={}),
                )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            yield ModelStreamEvent(type="text_delta", delta="已按新要求继续")
            yield ModelStreamEvent(type="done", final=ModelResponse(text="已按新要求继续"))

    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
        metadata={},
    )
    sent = False

    def steering_drain() -> list[str]:
        nonlocal sent
        if started.is_set() and not sent:
            sent = True
            return ["停止等待，直接给出当前结论"]
        return []

    intent = ParsedIntent(
        raw="wait for the result",
        intent_type="task",
        normalized_goal="wait for the result",
        user_context={"conversation_id": "thread-live-redirect"},
    )
    began = time.monotonic()
    events = list(
        stream_agentic_fallback(
            stack,
            intent,
            _agent(),
            steering_drain=steering_drain,
        )
    )

    assert time.monotonic() - began < 1.0
    assert cancelled.is_set()
    assert len(router.requests) == 2
    assert any(
        message.role == "user" and message.content == "停止等待，直接给出当前结论"
        for message in router.requests[1].messages
    )
    assert any(
        message.role == "system"
        and "LIVE USER FOLLOW-UP — HIGH PRIORITY" in str(message.content)
        and "directly answer or acknowledge" in str(message.content)
        for message in router.requests[1].messages
    )
    tool_end = next(event for event in events if event[0] == "tool_end")
    assert tool_end[1]["is_error"] is True
    assert tool_end[1]["status"] == "cancelled"
    assert "已按新要求继续" in "".join(str(event[1]) for event in events if event[0] == "text")
    trajectory = stack.executor.journal.read_by_type("trajectory")[0].trajectory
    assert trajectory.outcome.success is True
    assert trajectory.outcome.degraded is True
    assert trajectory.outcome.disposition == "completed_with_warning"
    assert trajectory.steps[0].result.status == "failed"
    assert trajectory.steps[0].result.error_type == "cancelled"


def test_parent_cancellation_is_not_recorded_as_semantic_error_or_completed() -> None:
    started = threading.Event()

    def wait_for_parent_cancel(a: int = 0, b: int = 0, sleep_ms: int = 0) -> dict:
        del a, b, sleep_ms
        started.set()
        token = current_cancellation_token()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not token.is_cancelled:
            time.sleep(0.01)
        assert token.is_cancelled
        return {"error": token.reason}

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="slow_sum",
            description="Wait for an external parent cancellation.",
            affinity=["io"],
            trusted_source="skill://public/slow_sum",
            handler=wait_for_parent_cancel,
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="todo_write",
            description="Update todo list.",
            affinity=["meta"],
            trusted_source="skill://public/todo_write",
            handler=lambda **_kwargs: {"ok": True},
        ),
        verify_tests=False,
    )
    router = _RouterEmitting([ToolCall(id="cancel-parent", name="slow_sum", input={})])
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
        metadata={},
    )
    source = CancellationSource()

    def cancel_after_start() -> None:
        assert started.wait(timeout=2.0)
        source.cancel(reason="external interrupt")

    canceller = threading.Thread(
        target=cancel_after_start,
        daemon=True,
    )
    canceller.start()

    with scoped_cancellation(source.token):
        events = list(stream_agentic_fallback(stack, _intent(), _agent()))
    canceller.join(timeout=2.0)

    tool_end = next(event for event in events if event[0] == "tool_end")
    assert tool_end[1]["is_error"] is True
    assert tool_end[1]["status"] == "cancelled"
    step_event = stack.executor.journal.read_by_type("step")[0]
    assert step_event.step.result.status == "failed"
    assert step_event.step.result.error_type == "cancelled"
    trajectory = stack.executor.journal.read_by_type("trajectory")[0].trajectory
    assert trajectory.outcome.success is False
    assert trajectory.outcome.degraded is True
    assert trajectory.outcome.disposition == "cancelled"
    assert trajectory.steps[0].result.error_type == "cancelled"


def test_steering_terminates_a_real_subprocess_tree() -> None:
    started = threading.Event()

    def long_command(a: int = 0, b: int = 0, sleep_ms: int = 0) -> dict:
        started.set()
        return stream_run(
            [sys.executable, "-c", "import time; time.sleep(10); print('too late')"],
            timeout=15,
        )

    registry = SkillRegistry()
    for skill in (
        Skill(
            name="slow_sum",
            description="Run a long cancellable command.",
            affinity=["shell"],
            trusted_source="skill://public/slow_sum",
            handler=long_command,
        ),
        Skill(
            name="todo_write",
            description="Update todo list.",
            affinity=["meta"],
            trusted_source="skill://public/todo_write",
            handler=lambda **_kwargs: {"ok": True},
        ),
    ):
        registry.register(skill, verify_tests=False)
    router = _RouterEmitting(
        [ToolCall(id="process-1", name="slow_sum", input={})],
    )
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
        metadata={},
    )
    sent = False

    def steering_drain() -> list[str]:
        nonlocal sent
        if started.is_set() and not sent:
            sent = True
            return ["停止这个命令，直接继续"]
        return []

    began = time.monotonic()
    events = list(
        stream_agentic_fallback(
            stack,
            _intent(),
            _agent(),
            steering_drain=steering_drain,
        )
    )

    assert time.monotonic() - began < 2.0
    tool_end = next(event for event in events if event[0] == "tool_end")
    assert tool_end[1]["status"] == "cancelled"
    assert "too late" not in tool_end[1]["output"]


def test_steering_cancels_every_running_parallel_tool() -> None:
    started: set[str] = set()
    cancelled: set[str] = set()
    state_lock = threading.Lock()

    def cooperative_sum(label: str = "") -> dict:
        with state_lock:
            started.add(label)
        token = current_cancellation_token()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not token.is_cancelled:
            time.sleep(0.01)
        if token.is_cancelled:
            with state_lock:
                cancelled.add(label)
            return {"error": token.reason}
        return {"ok": True}

    registry = SkillRegistry()
    for skill in (
        Skill(
            name="slow_sum",
            description="Run cancellable parallel work.",
            affinity=["math"],
            trusted_source="skill://public/slow_sum",
            handler=cooperative_sum,
        ),
        Skill(
            name="todo_write",
            description="Update todo list.",
            affinity=["meta"],
            trusted_source="skill://public/todo_write",
            handler=lambda **_kwargs: {"ok": True},
        ),
    ):
        registry.register(skill, verify_tests=False)

    calls = [
        ToolCall(id=f"parallel-{label}", name="slow_sum", input={"label": label})
        for label in ("a", "b", "c")
    ]
    router = _RouterEmitting(calls)
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
        metadata={},
    )
    sent = False

    def steering_drain() -> list[str]:
        nonlocal sent
        with state_lock:
            all_started = len(started) == 3
        if all_started and not sent:
            sent = True
            return ["停止这一批并行操作"]
        return []

    events = list(
        stream_agentic_fallback(
            stack,
            _intent(),
            _agent(),
            steering_drain=steering_drain,
        )
    )

    assert cancelled == {"a", "b", "c"}
    tool_ends = [event for event in events if event[0] == "tool_end"]
    assert len(tool_ends) == 3
    assert all(event[1]["parallel"] is True for event in tool_ends)
    assert all(event[1]["is_error"] is True for event in tool_ends)
    assert all(event[1]["status"] == "cancelled" for event in tool_ends)


def test_steering_prevents_queued_serial_tools_from_starting() -> None:
    started: list[str] = []
    first_started = threading.Event()

    def serial_work(label: str = "") -> dict:
        started.append(label)
        if label == "first":
            first_started.set()
        token = current_cancellation_token()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not token.is_cancelled:
            time.sleep(0.01)
        return {"error": token.reason} if token.is_cancelled else {"ok": True}

    registry = SkillRegistry()
    for skill in (
        Skill(
            name="slow_sum",
            description="Run cancellable serial work.",
            affinity=["math"],
            trusted_source="skill://public/slow_sum",
            handler=serial_work,
        ),
        Skill(
            name="todo_write",
            description="Update todo list.",
            affinity=["meta"],
            trusted_source="skill://public/todo_write",
            handler=lambda **_kwargs: {"ok": True},
        ),
    ):
        registry.register(skill, verify_tests=False)
    router = _RouterEmitting(
        [
            ToolCall(id=f"serial-{label}", name="slow_sum", input={"label": label})
            for label in ("first", "second", "third")
        ]
    )
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
        metadata={"parallel_tool_use": False},
    )
    sent = False

    def steering_drain() -> list[str]:
        nonlocal sent
        if first_started.is_set() and not sent:
            sent = True
            return ["后面的操作都不要执行"]
        return []

    events = list(
        stream_agentic_fallback(
            stack,
            _intent(),
            _agent(),
            steering_drain=steering_drain,
        )
    )

    assert started == ["first"]
    tool_ends = [event for event in events if event[0] == "tool_end"]
    assert len(tool_ends) == 3
    assert all(event[1]["is_error"] is True for event in tool_ends)
    assert all(event[1]["status"] == "cancelled" for event in tool_ends)


def test_steering_abandons_an_idle_model_stream_without_waiting_for_timeout() -> None:
    stream_started = threading.Event()
    stream_cancelled = threading.Event()

    class Router:
        def __init__(self) -> None:
            self.requests = []

        def call_stream(self, req):
            self.requests.append(req)
            if len(self.requests) == 1:
                stream_started.set()
                token = current_cancellation_token()
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and not token.is_cancelled:
                    time.sleep(0.01)
                if token.is_cancelled:
                    stream_cancelled.set()
                    return
                yield ModelStreamEvent(type="text_delta", delta="stale answer")
                return
            yield ModelStreamEvent(type="text_delta", delta="fresh answer")
            yield ModelStreamEvent(type="done", final=ModelResponse(text="fresh answer"))

    router = Router()
    sent = False

    def steering_drain() -> list[str]:
        nonlocal sent
        if stream_started.is_set() and not sent:
            sent = True
            return ["不要再等，换一个方向回答"]
        return []

    began = time.monotonic()
    intent = ParsedIntent(
        raw="answer when ready",
        intent_type="task",
        normalized_goal="answer when ready",
        user_context={"conversation_id": "thread-model-redirect"},
    )
    events = list(
        stream_agentic_fallback(
            _make_stack(router),
            intent,
            _agent(),
            steering_drain=steering_drain,
        )
    )

    assert time.monotonic() - began < 1.0
    assert stream_cancelled.wait(timeout=0.2)
    assert len(router.requests) == 2
    assert any(
        message.role == "user" and message.content == "不要再等，换一个方向回答"
        for message in router.requests[1].messages
    )
    assert any(
        message.role == "system" and "LIVE USER FOLLOW-UP — HIGH PRIORITY" in str(message.content)
        for message in router.requests[1].messages
    )
    visible = "".join(str(event[1]) for event in events if event[0] == "text")
    assert "stale answer" not in visible
    assert "fresh answer" in visible


def test_quality_tools_are_scope_sensitive() -> None:
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="run_tests",
            description="Run tests.",
            affinity=["quality", "test"],
            trusted_source="skill://public/run_tests",
            handler=lambda **_kwargs: {"success": True},
        ),
        verify_tests=False,
    )
    stack = SimpleNamespace(executor=SimpleNamespace(registry=registry))

    assert tool_bridge._tool_uses_session_scope(
        stack,
        ToolCall(id="tests", name="run_tests", input={}),
    )


def test_parallel_path_yields_concurrency_speedup() -> None:
    calls = [
        ToolCall(id=f"t-{i}", name="slow_sum", input={"a": i, "b": 1, "sleep_ms": 80})
        for i in range(3)
    ]
    router = _RouterEmitting(calls)
    started = time.monotonic()
    events = list(stream_agentic_fallback(_make_stack(router), _intent(), _agent()))
    elapsed = time.monotonic() - started

    # Serial would take ~240ms (3 × 80ms). Parallel should be ~80ms +
    # overhead. Generous bound (180ms) to absorb thread-pool spin-up
    # and CI jitter while still proving real concurrency.
    tool_end_events = [e for e in events if e[0] == "tool_end"]
    assert len(tool_end_events) == 3
    assert elapsed < 0.18, f"parallel exec slower than expected: {elapsed:.3f}s"


def test_parallel_tools_keep_code_workspace_scope(tmp_path) -> None:
    """Filesystem tools stay serial so they cannot lose Session scope."""
    nested = tmp_path / "nested"
    nested.mkdir()

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="list_cwd",
            description="List files in a directory.",
            affinity=["file", "io"],
            trusted_source="skill://public/list_cwd",
            handler=_list_cwd,
        ),
        verify_tests=False,
    )
    router = _RouterEmitting(
        [
            ToolCall(id="root", name="list_cwd", input={"path": "."}),
            ToolCall(id="nested", name="list_cwd", input={"path": "nested"}),
        ]
    )
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
        metadata={},
    )
    intent = ParsedIntent(
        raw="inspect workspace in parallel",
        intent_type="task",
        normalized_goal="inspect workspace in parallel",
        user_context={
            "conversation_id": "thread-scoped-parallel",
            "metadata": {
                "mode": "code",
                "workspace_path": str(tmp_path),
                "sandbox_mode": "full",
            },
        },
    )

    events = list(stream_agentic_fallback(stack, intent, _agent()))
    outputs = {event[1]["id"]: event[1]["output"] for event in events if event[0] == "tool_end"}

    assert str(tmp_path.resolve()) in outputs["root"]
    assert str(nested.resolve()) in outputs["nested"]
    tool_ends = [event for event in events if event[0] == "tool_end"]
    assert all(event[1].get("parallel") is not True for event in tool_ends)


def test_parallel_mixed_reads_keep_code_workspace_scope(tmp_path) -> None:
    """Relative file reads must share the same scope as directory reads."""
    (tmp_path / "file_service.py").write_text("fixture-marker", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_fixture.py").write_text("test-marker", encoding="utf-8")

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="list_cwd",
            description="List files in a directory.",
            affinity=["file", "io"],
            trusted_source="skill://public/list_cwd",
            handler=_list_cwd,
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="read_file",
            description="Read one file.",
            affinity=["file", "io"],
            trusted_source="skill://public/read_file",
            handler=_read_file,
        ),
        verify_tests=False,
    )
    router = _RouterEmitting(
        [
            ToolCall(id="source", name="read_file", input={"path": "file_service.py"}),
            ToolCall(id="tests", name="list_cwd", input={"path": "tests"}),
        ]
    )
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
        metadata={},
    )
    intent = ParsedIntent(
        raw="inspect fixture files in parallel",
        intent_type="task",
        normalized_goal="inspect fixture files in parallel",
        user_context={
            "conversation_id": "thread-scoped-parallel-read",
            "metadata": {
                "mode": "code",
                "workspace_path": str(tmp_path),
                "sandbox_mode": "full",
            },
        },
    )

    events = list(stream_agentic_fallback(stack, intent, _agent()))
    outputs = {event[1]["id"]: event[1]["output"] for event in events if event[0] == "tool_end"}

    assert str((tmp_path / "file_service.py").resolve()) in outputs["source"]
    assert "test_fixture.py" in outputs["tests"]
    tool_ends = [event for event in events if event[0] == "tool_end"]
    assert all(event[1].get("parallel") is not True for event in tool_ends)


def test_serial_when_only_one_tool() -> None:
    calls = [ToolCall(id="t-only", name="slow_sum", input={"a": 1, "b": 2, "sleep_ms": 10})]
    router = _RouterEmitting(calls)
    events = list(stream_agentic_fallback(_make_stack(router), _intent(), _agent()))
    tool_end_events = [e for e in events if e[0] == "tool_end"]
    assert len(tool_end_events) == 1
    # Single-tool rounds skip the parallel path → no marker.
    assert tool_end_events[0][1].get("parallel") is not True


def test_serial_when_todo_write_in_round() -> None:
    """todo_write in the round forces serial execution because state
    machine ops have ordered semantics the model expects."""
    calls = [
        ToolCall(id="t-0", name="slow_sum", input={"a": 1, "b": 1, "sleep_ms": 5}),
        ToolCall(
            id="t-todo",
            name="todo_write",
            input={"items": [{"content": "x", "status": "in_progress", "activeForm": "x"}]},
        ),
        ToolCall(id="t-2", name="slow_sum", input={"a": 2, "b": 2, "sleep_ms": 5}),
    ]
    router = _RouterEmitting(calls)
    events = list(stream_agentic_fallback(_make_stack(router), _intent(), _agent()))
    tool_end_events = [e for e in events if e[0] == "tool_end"]
    assert len(tool_end_events) == 3
    assert all(e[1].get("parallel") is not True for e in tool_end_events)


def test_serial_when_stack_metadata_disables_parallel() -> None:
    calls = [
        ToolCall(id=f"t-{i}", name="slow_sum", input={"a": i, "b": 1, "sleep_ms": 5})
        for i in range(3)
    ]
    router = _RouterEmitting(calls)
    stack = _make_stack(router, metadata={"parallel_tool_use": False})
    events = list(stream_agentic_fallback(stack, _intent(), _agent()))
    tool_end_events = [e for e in events if e[0] == "tool_end"]
    assert len(tool_end_events) == 3
    assert all(e[1].get("parallel") is not True for e in tool_end_events)

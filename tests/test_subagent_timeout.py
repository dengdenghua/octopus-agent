"""
Tests for timeout enforcement and SSE event emission in call_subagent.

Coverage
--------
1. timeout_seconds=0.1 against a slow runner → status=timeout
2. timeout_seconds=10 against a fast runner → completes normally
3. timeout_seconds=None (default) → no limit enforced
4. event_emitter receives sub_tool_start before each tool call
5. event_emitter exceptions are swallowed (don't crash the runner)
6. Round counting: timeout at round 2 → rounds_completed=2
"""

from __future__ import annotations

import threading
import time

import pytest

# ─── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_bridge():
    """Ensure bridge module-level state is clean before and after each test."""
    from runtime.execution.subagents.bridge import (
        set_sub_agent_runner,
        set_subagent_registry,
    )

    set_sub_agent_runner(None)
    set_subagent_registry(None)
    yield
    set_sub_agent_runner(None)
    set_subagent_registry(None)


# ─── helpers ─────────────────────────────────────────────────────────────────


def _install_runner(fn):
    """Register *fn* as the legacy _RUNNER and return it."""
    from runtime.execution.subagents.bridge import set_sub_agent_runner

    set_sub_agent_runner(fn)
    return fn


def _slow_runner(prompt, *, subagent_name, context):
    """Sleeps 2 s — long enough to trip a 0.1 s timeout."""
    time.sleep(2)
    return "should not reach here"


def _fast_runner(prompt, *, subagent_name, context):
    """Returns immediately."""
    return f"fast result for {subagent_name}"


# ─── test 1: timeout fires ────────────────────────────────────────────────────


def test_timeout_returns_timeout_status():
    """call_subagent with a short timeout against a slow runner returns
    a structured timeout result instead of hanging."""
    from runtime.execution.subagents.bridge import call_subagent

    _install_runner(_slow_runner)

    result = call_subagent(
        agent_id="coder",
        prompt="do something",
        timeout_seconds=0.1,
    )

    assert result["status"] == "timeout"
    assert result["success"] is False
    assert "timed out" in result["error"]
    assert "0.1s" in result["error"]
    assert result["agent_id"] == "coder"
    assert "rounds_completed" in result


def test_timeout_keeps_slot_until_noncooperative_worker_exits(monkeypatch):
    """A timed-out Python thread cannot be killed, so its capacity slot
    must remain occupied until it really unwinds; otherwise a retry can run
    concurrently and mutate the same workspace."""
    import runtime.execution.subagents.bridge as bridge
    from runtime.execution.subagents.bridge import active_subagent_count, call_subagent

    release = threading.Event()
    started = threading.Event()

    def _stuck_runner(prompt, *, subagent_name, context):
        started.set()
        release.wait(timeout=2)
        return "late result"

    # The preceding timeout regression intentionally uses a non-cooperative
    # two-second runner; wait for that retired generation before lowering the
    # global cap for this isolated assertion.
    deadline = time.monotonic() + 3
    while active_subagent_count() != 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert active_subagent_count() == 0
    monkeypatch.setattr(bridge, "MAX_ACTIVE_SUBAGENTS", 1)
    _install_runner(_stuck_runner)
    result = call_subagent(
        agent_id="coder",
        prompt="do something",
        timeout_seconds=0.05,
    )

    assert started.wait(timeout=1)
    assert result["status"] == "timeout"
    assert active_subagent_count() == 1

    release.set()
    deadline = time.monotonic() + 2
    while active_subagent_count() != 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert active_subagent_count() == 0


# ─── test 2: fast runner completes normally ───────────────────────────────────


def test_no_timeout_with_generous_limit():
    """A fast runner completes well within a 10 s timeout."""
    from runtime.execution.subagents.bridge import call_subagent

    _install_runner(_fast_runner)

    result = call_subagent(
        agent_id="coder",
        prompt="do something",
        timeout_seconds=10,
    )

    assert result["success"] is True
    assert result["agent_id"] == "coder"
    assert "fast result for coder" in result["output"]
    assert result.get("status") != "timeout"


# ─── test 3: None timeout means no enforcement ───────────────────────────────


def test_none_timeout_does_not_enforce():
    """timeout_seconds=None (default) must not impose any limit."""
    from runtime.execution.subagents.bridge import call_subagent

    _install_runner(_fast_runner)

    # Call without timeout_seconds at all (default None path).
    result = call_subagent(agent_id="coder", prompt="do something")

    assert result["success"] is True
    assert result.get("status") != "timeout"


def test_parent_redirect_returns_cancelled_and_fences_late_child_events():
    from runtime.execution.subagents.bridge import call_subagent
    from runtime.safety.approval.cancellation import (
        CancellationSource,
        current_cancellation_token,
        scoped_cancellation,
    )

    started = threading.Event()
    emitted: list[dict] = []

    def _late_runner(prompt, *, subagent_name, context):
        token = current_cancellation_token()
        started.set()
        while not token.is_cancelled:
            time.sleep(0.005)
        time.sleep(0.12)
        context["event_emitter"]({"type": "sub_tool_end", "round": 9, "status": "success"})
        return "late child success"

    _install_runner(_late_runner)
    parent = CancellationSource()

    def _redirect() -> None:
        assert started.wait(timeout=1)
        parent.cancel(reason="user changed direction")

    thread = threading.Thread(target=_redirect)
    thread.start()
    before = time.monotonic()
    with scoped_cancellation(parent.token):
        result = call_subagent(
            agent_id="coder",
            prompt="old task",
            event_emitter=emitted.append,
        )
    elapsed = time.monotonic() - before
    thread.join(timeout=1)

    assert elapsed < 0.5
    assert result["status"] == "cancelled"
    assert result["cancelled"] is True
    assert result["output"] == ""
    assert result["cancellation_reason"] == "user changed direction"

    time.sleep(0.18)
    finished = [event for event in emitted if event["type"] == "subagent_finished"]
    assert len(finished) == 1
    assert finished[0]["status"] == "cancelled"
    assert not any(event.get("round") == 9 for event in emitted)


def test_parent_cancellation_listener_detaches_after_child_completion():
    from runtime.execution.subagents.bridge import call_subagent
    from runtime.safety.approval.cancellation import (
        CancellationSource,
        scoped_cancellation,
    )

    _install_runner(_fast_runner)
    parent = CancellationSource()
    with scoped_cancellation(parent.token):
        result = call_subagent(agent_id="coder", prompt="quick task")

    assert result["success"] is True
    assert parent._callbacks == []


# ─── test 4: event_emitter receives sub_tool_start events ────────────────────


def test_event_emitter_receives_sub_tool_start():
    """event_emitter callable is called with sub_tool_start events
    before each tool invocation inside the runner."""
    from runtime.execution.subagents.bridge import call_subagent

    collected: list[dict] = []

    def _emitting_runner(prompt, *, subagent_name, context):
        emitter = context.get("event_emitter")
        # Simulate two tool calls across two rounds.
        for rnd in (1, 2):
            if emitter:
                emitter(
                    {
                        "type": "sub_tool_start",
                        "agent_id": subagent_name,
                        "round": rnd,
                        "skill": f"fetch_url_{rnd}",
                        "args_preview": f"https://example.com/{rnd}",
                    }
                )
        return "done"

    _install_runner(_emitting_runner)

    result = call_subagent(
        agent_id="coder",
        prompt="research something",
        event_emitter=collected.append,
        timeout_seconds=10,
    )

    assert result["success"] is True
    starts = [e for e in collected if e.get("type") == "sub_tool_start"]
    assert len(starts) == 2
    assert starts[0]["round"] == 1
    assert starts[0]["skill"] == "fetch_url_1"
    assert starts[1]["round"] == 2


# ─── test 5: emitter exceptions are swallowed ────────────────────────────────


def test_event_emitter_exception_does_not_crash_runner():
    """If the event_emitter raises, the runner must continue and return
    a normal result — the emitter is fire-and-forget."""
    from runtime.execution.subagents.bridge import call_subagent

    def _boom_emitter(event):
        raise RuntimeError("emitter exploded")

    def _emitting_runner(prompt, *, subagent_name, context):
        emitter = context.get("event_emitter")
        if emitter:
            emitter(
                {
                    "type": "sub_tool_start",
                    "agent_id": subagent_name,
                    "round": 1,
                    "skill": "test_skill",
                    "args_preview": "",
                }
            )
        return "survived"

    _install_runner(_emitting_runner)

    # Must not raise despite the emitter blowing up.
    result = call_subagent(
        agent_id="coder",
        prompt="do something",
        event_emitter=_boom_emitter,
        timeout_seconds=10,
    )

    assert result["success"] is True
    assert result["output"] == "survived"


# ─── test 6: round counting on timeout ───────────────────────────────────────


def test_rounds_completed_reflects_progress_before_timeout():
    """When a timeout fires mid-run, rounds_completed equals the highest
    round number that was emitted before the deadline."""
    from runtime.execution.subagents.bridge import call_subagent

    def _two_round_then_hang(prompt, *, subagent_name, context):
        emitter = context.get("event_emitter")
        # Round 1 completes quickly.
        if emitter:
            emitter(
                {
                    "type": "sub_tool_start",
                    "agent_id": subagent_name,
                    "round": 1,
                    "skill": "quick_tool",
                    "args_preview": "",
                }
            )
        # Round 2 starts but then the runner hangs.
        if emitter:
            emitter(
                {
                    "type": "sub_tool_start",
                    "agent_id": subagent_name,
                    "round": 2,
                    "skill": "slow_tool",
                    "args_preview": "",
                }
            )
        time.sleep(5)  # hang — will be interrupted by timeout
        return "never"

    _install_runner(_two_round_then_hang)

    result = call_subagent(
        agent_id="coder",
        prompt="do something",
        timeout_seconds=0.3,
    )

    assert result["status"] == "timeout"
    assert result["rounds_completed"] == 2


# ─── Audit T-03: background producer cancel bridges to the child run ────────


def test_job_producer_cancel_bridges_to_inflight_child_run(monkeypatch):
    """A background subagent job's cancel() must reach the in-flight child
    run (via the ambient cancellation token), not merely label the outcome
    after the child finishes."""
    import asyncio

    from runtime.execution.jobs import subagent_producer as sp
    from runtime.execution.jobs.subagent_producer import build_subagent_job_start

    registered = threading.Event()
    cancel_observed = threading.Event()
    release = threading.Event()

    def fake_call_subagent(**kwargs):
        from runtime.safety.approval.cancellation import current_cancellation_token

        current_cancellation_token().on_cancelled(lambda reason: cancel_observed.set())
        registered.set()
        release.wait(5)  # block until the test releases; cancel fires meanwhile
        return {"success": True, "output": "ran"}

    monkeypatch.setattr(sp, "call_subagent", fake_call_subagent)

    async def scenario():
        start = build_subagent_job_start(agent_id="a", prompt="p")
        hooks = start.run()
        assert registered.wait(3), "worker thread did not register the child"
        hooks.cancel("test kill")
        assert cancel_observed.wait(3), "cancel never reached the child run"
        release.set()
        return await asyncio.wait_for(hooks.done, timeout=5)

    outcome = asyncio.run(scenario())
    assert outcome.status == "killed"
    assert "test kill" in (outcome.detail or "")

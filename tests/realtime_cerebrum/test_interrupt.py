"""Tests for realtime cerebrum interrupt handling — throughput, turn interrupt, stale turns, meta skill hints, producer cancellation."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore[assignment]
    TestClient = None  # type: ignore[assignment]

from runtime.protocol import (
    JsonRpcErrorCode,
    JsonRpcRequest,
    JsonRpcResponse,
    Notification,
    decode_message,
    encode_message,
)
from tests.realtime_cerebrum._helpers import (
    drive as _drive,
)
from tests.realtime_cerebrum._helpers import (
    set_script as _set_script,
)


def test_throughput_event_maps_to_token_usage(gateway: Any) -> None:
    """react_loop emits periodic ``throughput`` events during long
    streams. The bridge must forward them as ``thread/tokenUsage/updated``
    notifications so the UI can show a live tokens-per-second indicator."""
    client, _ = gateway
    _set_script(
        [
            {"type": "text_delta", "delta": "hello "},
            {
                "type": "throughput",
                "chars": 6,
                "elapsed_ms": 500,
                "chars_per_sec": 12.0,
            },
            {"type": "text_delta", "delta": "world"},
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        result = _drive(
            ws,
            params={
                "threadId": "th_tp",
                "input": [{"type": "text", "text": "stream"}],
                "approvalPolicy": "never",
            },
        )
    tp_notes = [n for n in result["notifications"] if n.method == "thread/tokenUsage/updated"]
    assert tp_notes, "expected at least one tokenUsage notification"
    usage = tp_notes[0].params["tokenUsage"]
    assert usage["chars"] == 6
    assert usage["charsPerSec"] == 12.0
    assert usage["elapsedMs"] == 500


def test_turn_interrupt_kills_in_flight_subprocess(
    gateway: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: client sends turn/interrupt while a tool is running
    a long subprocess → stream_run sees cancellation → proc killed →
        tool_end carries status=cancelled → turn.status = cancelled."""
    import sys
    import time

    import runtime.core.cerebrum.react_loop as rl
    from runtime.platform.process.streaming import stream_run

    tool_completed_naturally = {"flag": False}

    def fake_stream_with_real_subprocess(
        *args: Any,
        **kwargs: Any,
    ) -> Iterator[dict[str, Any]]:
        # tool_start lets the bridge create a commandExecution item.
        yield {
            "type": "tool_start",
            "tool_name": "sleep_long",
            "tool_call_id": "c_cancel",
            "iteration": 1,
            "input_preview": {"seconds": 10},
        }
        t0 = time.monotonic()
        # Real subprocess — would sleep 10s if not cancelled.
        r = stream_run(
            [sys.executable, "-c", "import time; time.sleep(10); print('done')"],
            timeout=15,
        )
        elapsed = time.monotonic() - t0
        if r.get("cancelled"):
            yield {
                "type": "tool_end",
                "tool_name": "sleep_long",
                "tool_call_id": "c_cancel",
                "iteration": 1,
                "status": "cancelled",
                "output_preview": "(已取消)",
                "duration_ms": int(elapsed * 1000),
            }
            yield {"type": "react_cancelled", "iteration": 1}
            return
        tool_completed_naturally["flag"] = True  # should NOT happen
        yield {
            "type": "tool_end",
            "tool_name": "sleep_long",
            "tool_call_id": "c_cancel",
            "iteration": 1,
            "status": "success",
            "output_preview": r.get("stdout", ""),
            "duration_ms": int(elapsed * 1000),
        }
        yield {"type": "react_completed"}

    monkeypatch.setattr(rl, "stream_react_loop", fake_stream_with_real_subprocess)

    client, _ = gateway
    t0 = time.monotonic()
    with client.websocket_connect("/api/realtime") as ws:
        ws.send_text(
            encode_message(
                JsonRpcRequest(
                    id=1,
                    method="turn/start",
                    params={
                        "threadId": "th_cancel",
                        "input": [{"type": "text", "text": "sleep please"}],
                        "approvalPolicy": "never",
                    },
                )
            )
        )

        # Send interrupt after we see the tool_start item
        interrupted = False
        final: JsonRpcResponse | None = None
        notifications: list[Notification] = []
        turn_id: str | None = None
        while final is None:
            msg = decode_message(ws.receive_text())
            if isinstance(msg, Notification):
                notifications.append(msg)
                if msg.method == "turn/started":
                    turn_id = msg.params["turn"]["id"]
                if (
                    msg.method == "item/started"
                    and msg.params.get("item", {}).get("type") == "commandExecution"
                    and not interrupted
                ):
                    ws.send_text(
                        encode_message(
                            JsonRpcRequest(
                                id=99,
                                method="turn/interrupt",
                                params={"threadId": "th_cancel", "turnId": turn_id},
                            )
                        )
                    )
                    interrupted = True
                continue
            if isinstance(msg, JsonRpcResponse) and msg.id == 1:
                final = msg
                break
            # ignore the interrupt ack

    elapsed = time.monotonic() - t0
    assert final is not None
    # Must complete in well under the 10s sleep — cancellation must
    # propagate through the async watcher + stream_run kill path.
    assert elapsed < 3.0, f"interrupt took {elapsed:.1f}s, expected < 3s"
    assert tool_completed_naturally["flag"] is False
    assert final.result["turn"]["status"] == "cancelled"


def test_thread_resume_closes_stale_in_progress_turn(tmp_path: Path) -> None:
    from fastapi import FastAPI

    from runtime.memory.threads.event_log import EventLog
    from runtime.platform.process.task_supervisor import TaskRunStatus, TaskSupervisor
    from runtime.protocol.items import ItemStatus, Turn, TurnParams, UserMessageItem
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    logs_root = tmp_path / "threads"
    log = EventLog(logs_root / "stale-thread.jsonl")
    turn = Turn(
        threadId="stale-thread",
        params=TurnParams(
            threadId="stale-thread",
            input=[{"type": "text", "text": "will never finish"}],
        ),
    )
    user_item = UserMessageItem(text="will never finish")
    user_item.status = ItemStatus.COMPLETED
    log.thread_started("stale-thread")
    log.turn_started("stale-thread", turn)
    log.item_started("stale-thread", turn.id, user_item)
    log.item_completed("stale-thread", turn.id, user_item)
    turn.task_id = "stale-react-task"
    turn.objective_id = turn.task_id
    log.turn_updated(
        turn.thread_id,
        turn.id,
        objective_id=turn.objective_id,
        task_id=turn.task_id,
    )

    old_supervisor = TaskSupervisor.from_path(
        tmp_path / "task_runs.json",
        holder_id="dead-worker",
        lease_ttl_seconds=300,
    )
    old_supervisor.start_task(
        task_id=turn.task_id,
        kind="realtime_objective",
        thread_id=turn.thread_id,
        origin_task_id=turn.id,
        metadata={"turn_id": turn.id},
    )
    new_supervisor = TaskSupervisor.from_path(
        tmp_path / "task_runs.json",
        holder_id="recovery-worker",
        lease_ttl_seconds=300,
    )

    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(logs_root),
        task_supervisor=new_supervisor,
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        ws.send_text(
            encode_message(
                JsonRpcRequest(
                    id=1,
                    method="thread/resume",
                    params={"threadId": "stale-thread"},
                )
            )
        )
        msg = decode_message(ws.receive_text())

    assert isinstance(msg, JsonRpcResponse)
    resumed_turn = msg.result["turns"][0]
    assert resumed_turn["status"] == "failed"
    assert resumed_turn["error"]["code"] == "stale_in_progress_turn"

    replayed = log.replay()
    assert replayed[0].status.value == "failed"
    recovered_task = new_supervisor.store.get("stale-react-task")
    assert recovered_task is not None
    assert recovered_task.status == TaskRunStatus.FAILED
    assert recovered_task.lease is None
    assert (
        recovered_task.metadata["stale_turn_recovery_events"][-1]["previous_holder_id"]
        == "dead-worker"
    )


def test_thread_resume_preserves_checkpoint_backed_stale_turn_as_paused(
    tmp_path: Path,
) -> None:
    from runtime.core.cerebrum.pause_control import get_pause_controller
    from runtime.memory.threads.event_log import EventLog
    from runtime.protocol.items import Turn
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

    logs_root = tmp_path / "threads"
    log = EventLog(logs_root / "stale-paused.jsonl")
    turn = Turn(threadId="stale-paused")
    log.thread_started(turn.thread_id)
    log.turn_started(turn.thread_id, turn)

    controller = get_pause_controller()
    controller.request_pause(
        "react-task-paused",
        reason="iteration_near_limit",
        requested_by="system",
        note="checkpoint saved",
        thread_id=turn.thread_id,
    )
    controller.mark_paused("react-task-paused")
    try:
        runtime = CerebrumRuntime(
            stack=object(),
            agent=object(),
            logs_root=str(logs_root),
        )
        resumed = runtime._resume_turns(log)

        assert resumed[0].status.value == "paused"
        assert resumed[0].task_id == "react-task-paused"
        assert resumed[0].outcome_reason == "iteration_near_limit"
        assert log.replay()[0].status.value == "paused"
    finally:
        controller.clear("react-task-paused")


@pytest.mark.asyncio()
async def test_hunk_decide_rejects_paths_outside_thread_workspace(tmp_path: Path) -> None:
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import _RpcError

    outside = tmp_path / "outside.txt"
    outside.write_text("new\n", encoding="utf-8")
    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
        workspace_root=str(tmp_path / "workspaces"),
    )

    class Emitter:
        async def notify(self, method: str, params: dict[str, Any]) -> None:
            raise AssertionError("no hunk decision should be broadcast for invalid paths")

    diff = "--- a/outside.txt\n+++ b/outside.txt\n@@ -1 +1 @@\n-old\n+new\n"
    with pytest.raises(_RpcError) as exc:
        await runtime._handle_hunk_decide(  # type: ignore[attr-defined]
            {
                "threadId": "thread-a",
                "turnId": "turn-a",
                "itemId": "item-a",
                "hunkId": "hunk-a",
                "path": str(outside),
                "decision": "rejected",
                "diff": diff,
            },
            Emitter(),
        )

    assert exc.value.code == JsonRpcErrorCode.INVALID_PARAMS
    assert outside.read_text(encoding="utf-8") == "new\n"


def test_meta_skill_hint_emitted_when_prompt_matches_pack(tmp_path: Path) -> None:
    """Soft hand-off: when ``match_meta_skill`` finds a strong
    keyword overlap (e.g. the bug-hunt pack's trigger phrase), the
    runtime emits ``turn/metaSkill/hint`` BEFORE ReAct kicks in. The
    ReAct loop continues normally — hint is informational so the
    user gets an answer even if they don't follow the link to the
    catalog page.

    We use the bug-hunt pack's actual trigger words ("安全审计") so
    the test stays grounded in the shipped catalog rather than a
    hand-rolled fixture that could drift from real behavior."""
    from fastapi import FastAPI

    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway
    from runtime.sensing.model_router.models import ModelResponse, ModelStreamEvent

    class FakeRouter:
        def call_stream(self, _request: Any) -> Iterator[ModelStreamEvent]:
            yield ModelStreamEvent(type="text_delta", delta="ack")
            yield ModelStreamEvent(type="done", final=ModelResponse(text="ack"))

    class FakePlanner:
        planner_model = "fake"

        def __init__(self, router: FakeRouter) -> None:
            self.router = router

    class FakeStack:
        def __init__(self, router: FakeRouter) -> None:
            self.planner = FakePlanner(router)
            self.journal = None

    runtime = CerebrumRuntime(
        stack=FakeStack(FakeRouter()),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    _set_script(
        [
            {"type": "react_completed"},
        ]
    )
    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-meta-hint",
                # Two keyword tokens that overlap bug-hunt's
                # ``when_to_use``: 安全审计 / 渗透 / 漏洞 /...
                "input": [{"type": "text", "text": "帮我做一次安全审计 渗透测试"}],
                "approvalPolicy": "never",
                "model": "fake",
            },
        )

    notifications = out["notifications"]
    hints = [n for n in notifications if n.method == "turn/metaSkill/hint"]
    assert len(hints) == 1, [n.method for n in notifications]
    payload = hints[0].params
    assert payload["threadId"] == "th-meta-hint"
    assert payload["name"] == "bug-hunt"
    assert payload["stepCount"] >= 1
    assert "security" in payload["affinity"]


def test_meta_skill_hint_silent_when_no_match(tmp_path: Path) -> None:
    """Casual prompts that don't match any pack must NOT trigger a
    hint — the chip is reserved for real workflow intent. A plain
    ``2+2等于几`` should pass through with zero meta-skill events."""
    from fastapi import FastAPI

    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway
    from runtime.sensing.model_router.models import ModelResponse, ModelStreamEvent

    class FakeRouter:
        def call_stream(self, _request: Any) -> Iterator[ModelStreamEvent]:
            yield ModelStreamEvent(type="text_delta", delta="4")
            yield ModelStreamEvent(type="done", final=ModelResponse(text="4"))

    class FakePlanner:
        planner_model = "fake"

        def __init__(self, router: FakeRouter) -> None:
            self.router = router

    class FakeStack:
        def __init__(self, router: FakeRouter) -> None:
            self.planner = FakePlanner(router)
            self.journal = None

    runtime = CerebrumRuntime(
        stack=FakeStack(FakeRouter()),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    _set_script([{"type": "react_completed"}])
    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-no-hint",
                "input": [{"type": "text", "text": "2+2等于几？"}],
                "approvalPolicy": "never",
                "model": "fake",
            },
        )

    hints = [n for n in out["notifications"] if n.method == "turn/metaSkill/hint"]
    assert hints == []


def test_turn_survives_ws_disconnect_and_runs_server_side(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Audit T-01: a dropped WebSocket must NOT cancel a running turn.

    Before the fix, the turn ran inside the WS request task: closing
    the socket cancelled the consumer, whose finally tripped
    ``cancel_source`` and killed the producer thread — a network
    hiccup, lid-close or network switch destroyed a long turn. Turns
    now run as server-resident tasks behind a detached emitter, so the
    fake producer below is expected to run to NATURAL completion after
    the disconnect (its cancellation token is never tripped) and the
    resident task must drain on its own with nobody connected.
    """
    import threading
    import time

    import runtime.core.cerebrum.react_loop as rl
    from runtime.safety.approval.cancellation import current_cancellation_token
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    observed: dict[str, Any] = {"token_tripped": None}
    first_event_sent = threading.Event()

    def fake_stream(*args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        # Yield one event so the turn is clearly in-flight, then keep
        # the producer thread alive for a while, polling the
        # cancellation token. Under T-01 the token must NEVER trip as a
        # consequence of the disconnect; the thread returns naturally.
        yield {"type": "text_delta", "delta": "working"}
        first_event_sent.set()
        token = current_cancellation_token()
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if token.is_cancelled:
                observed["token_tripped"] = True
                return
            time.sleep(0.05)
        observed["token_tripped"] = False

    monkeypatch.setattr(rl, "stream_react_loop", fake_stream)

    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client:
        # Nested (not combined) on purpose: we exit the inner ws context
        # to simulate a mid-turn disconnect while staying inside client
        # to poll the outcome afterward.
        with client.websocket_connect("/api/realtime") as ws:
            ws.send_text(
                encode_message(
                    JsonRpcRequest(
                        id=1,
                        method="turn/start",
                        params={
                            "threadId": "th-disconnect",
                            "input": [{"type": "text", "text": "go"}],
                            "approvalPolicy": "never",
                        },
                    )
                )
            )
            # Wait until the producer has started streaming, then leave
            # the context → WebSocket disconnects mid-turn.
            assert first_event_sent.wait(timeout=5.0), "producer never started"
        # ws is now closed; the server-resident turn must keep running.

        deadline = time.monotonic() + 5.0
        while observed["token_tripped"] is None and time.monotonic() < deadline:
            time.sleep(0.05)

        assert observed["token_tripped"] is False, (
            "turn was cancelled by the ws disconnect — long turns must "
            "survive connection loss and run on server-side (audit T-01)"
        )

        # The resident task finishes on its own with nobody connected.
        deadline = time.monotonic() + 10.0
        while gateway._resident_turn_tasks and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not gateway._resident_turn_tasks, (
            "resident turn did not drain after the requester left"
        )

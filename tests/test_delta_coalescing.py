"""Backend delta coalescing in _ReactBridgeState.

Per-token LLM chunks must not become per-token WebSocket frames. The
bridge buffers and flushes on ~64 chars / 50ms / kind switch / item
finalization. Invariants pinned here:

  * time-to-first-token: the FIRST chunk of an item is never buffered
  * concatenated delta content is byte-identical to the input chunks
  * flush() drains the tail before completing the item
  * a mid-stream stall is bounded by the deadline timer
"""

import asyncio

import pytest

from runtime.protocol import ItemStatus, Turn, TurnParams, TurnStatus
from runtime.sensing.gateway.realtime_cerebrum import _ReactBridgeState
from runtime.sensing.gateway.realtime_react_stream import _apply_react_event


class _StubLog:
    def item_started(self, *args, **kwargs) -> None:  # noqa: ARG002
        pass

    def item_delta(self, *args, **kwargs) -> None:  # noqa: ARG002
        pass

    def item_completed(self, *args, **kwargs) -> None:  # noqa: ARG002
        pass

    def turn_updated(self, *args, **kwargs) -> None:  # noqa: ARG002
        pass


class _StubEmitter:
    def __init__(self) -> None:
        self.notified: list[tuple[str, dict]] = []

    async def notify(self, method, params) -> None:
        self.notified.append((str(method), params))

    def deltas(self, method_suffix: str = "delta") -> list[str]:
        return [p["delta"] for m, p in self.notified if method_suffix.lower() in m.lower()]


class _StubRuntime:
    def _record_react_trace_event(self, turn, event) -> None:  # noqa: ARG002
        pass


def _make_turn() -> Turn:
    return Turn(
        id="turn-1",
        threadId="th-1",
        params=TurnParams(threadId="th-1", input=[{"type": "text", "text": "go"}]),
    )


@pytest.mark.asyncio
async def test_first_chunk_emits_immediately() -> None:
    state = _ReactBridgeState()
    turn = _make_turn()
    emitter = _StubEmitter()
    log = _StubLog()

    await state.append_agent_message(turn, log, emitter, "hi")

    assert emitter.deltas() == ["hi"]


@pytest.mark.asyncio
async def test_small_chunks_coalesce_until_flush() -> None:
    state = _ReactBridgeState()
    turn = _make_turn()
    emitter = _StubEmitter()
    log = _StubLog()

    await state.append_agent_message(turn, log, emitter, "a")
    for ch in "bcdefg":
        await state.append_agent_message(turn, log, emitter, ch)
    # Tail still buffered (under both thresholds).
    assert emitter.deltas() == ["a"]

    await state.flush(turn, log, emitter)

    assert "".join(emitter.deltas()) == "abcdefg"
    # 1 first-chunk frame + 1 coalesced tail — not 7 frames.
    assert len(emitter.deltas()) == 2
    # Completed snapshot carries the full text.
    completed = [p for m, p in emitter.notified if m.endswith("item/completed")]
    assert completed and completed[0]["item"]["text"] == "abcdefg"


@pytest.mark.asyncio
async def test_cancelled_turn_does_not_complete_open_answer_draft() -> None:
    state = _ReactBridgeState()
    turn = _make_turn()
    emitter = _StubEmitter()
    log = _StubLog()

    await state.append_agent_message(turn, log, emitter, 'str = ""')
    await _apply_react_event(
        _StubRuntime(),  # type: ignore[arg-type]
        turn,
        log,  # type: ignore[arg-type]
        emitter,  # type: ignore[arg-type]
        state,
        {"type": "react_cancelled"},
    )

    assert turn.status == TurnStatus.INTERRUPTED
    assert turn.items[0].status == ItemStatus.INTERRUPTED
    completed = [p for m, p in emitter.notified if m.endswith("item/completed")]
    assert completed[0]["item"]["status"] == "interrupted"


@pytest.mark.asyncio
async def test_failed_completion_does_not_complete_open_answer_draft() -> None:
    state = _ReactBridgeState()
    turn = _make_turn()
    emitter = _StubEmitter()
    log = _StubLog()

    await state.append_agent_message(turn, log, emitter, "unfinished answer")
    await _apply_react_event(
        _StubRuntime(),  # type: ignore[arg-type]
        turn,
        log,  # type: ignore[arg-type]
        emitter,  # type: ignore[arg-type]
        state,
        {"type": "react_completed", "success": False},
    )

    assert turn.status == TurnStatus.FAILED
    assert turn.items[0].status == ItemStatus.FAILED
    completed = [p for m, p in emitter.notified if m.endswith("item/completed")]
    assert completed[0]["item"]["status"] == "failed"


@pytest.mark.asyncio
async def test_size_threshold_forces_flush() -> None:
    state = _ReactBridgeState()
    turn = _make_turn()
    emitter = _StubEmitter()
    log = _StubLog()

    await state.append_agent_message(turn, log, emitter, "x")
    await state.append_agent_message(turn, log, emitter, "y" * 70)

    # 70 chars crossed _DELTA_FLUSH_MAX_CHARS — no waiting for a timer.
    assert "".join(emitter.deltas()) == "x" + "y" * 70


@pytest.mark.asyncio
async def test_kind_switch_drains_in_order() -> None:
    state = _ReactBridgeState()
    turn = _make_turn()
    emitter = _StubEmitter()
    log = _StubLog()

    await state.append_reasoning(turn, log, emitter, "think")
    await state.append_reasoning(turn, log, emitter, "ing")
    await state.append_agent_message(turn, log, emitter, "answer")

    methods = [m for m, _ in emitter.notified if "delta" in m.lower()]
    # Reasoning frames (first + drained tail) strictly precede the
    # message frame.
    assert [m.split("/")[-1].lower() for m in methods] == [
        "textdelta",
        "textdelta",
        "delta",
    ]
    assert "".join(emitter.deltas("textDelta")) == "thinking"


@pytest.mark.asyncio
async def test_deadline_timer_flushes_a_stalled_tail() -> None:
    state = _ReactBridgeState()
    turn = _make_turn()
    emitter = _StubEmitter()
    log = _StubLog()

    await state.append_agent_message(turn, log, emitter, "head ")
    await state.append_agent_message(turn, log, emitter, "tail")
    assert "".join(emitter.deltas()) == "head "

    # No further chunks arrive — the deadline task must drain the tail.
    await asyncio.sleep(state._DELTA_FLUSH_INTERVAL_S * 3)

    assert "".join(emitter.deltas()) == "head tail"


@pytest.mark.asyncio
async def test_public_timeline_coordinates_interleave_commentary_tool_and_answer() -> None:
    state = _ReactBridgeState()
    turn = _make_turn()
    emitter = _StubEmitter()
    log = _StubLog()

    await state.append_commentary(
        turn,
        log,
        emitter,
        "I found the relevant implementation.",
    )
    await state.start_tool(
        turn,
        log,
        emitter,
        {"tool_call_id": "read-1", "tool_name": "read_file"},
    )
    await state.complete_tool(
        turn,
        log,
        emitter,
        {
            "tool_call_id": "read-1",
            "tool_name": "read_file",
            "status": "success",
            "output_preview": "source loaded",
        },
    )
    await state.append_agent_message(turn, log, emitter, "The two sides now agree.")
    await state.flush(turn, log, emitter)

    commentary, tool, answer = turn.items
    assert [item.timeline_sequence for item in turn.items] == [1, 2, 3]
    assert commentary.parent_item_id is None
    assert tool.parent_item_id == commentary.id
    assert answer.parent_item_id == tool.id
    assert commentary.phase_id
    assert tool.phase_id == commentary.phase_id
    assert answer.phase_id == commentary.phase_id


@pytest.mark.asyncio
async def test_tool_effect_signal_is_persisted_on_completed_realtime_item() -> None:
    state = _ReactBridgeState()
    turn = _make_turn()
    emitter = _StubEmitter()
    log = _StubLog()

    await state.start_tool(
        turn,
        log,
        emitter,
        {"tool_call_id": "write-1", "tool_name": "write_file"},
    )
    await state.complete_tool(
        turn,
        log,
        emitter,
        {
            "tool_call_id": "write-1",
            "tool_name": "write_file",
            "status": "error",
            "output_preview": "outcome unknown",
            "effect_receipt": {
                "effect_key": "effect:v1:abc",
                "call_id": "write-1",
                "state": "indeterminate",
                "reason": "outcome unknown",
                "fencing_token": 7,
            },
        },
    )

    tool = turn.items[0]
    assert tool.effect_receipt is not None
    assert tool.effect_receipt.effect_key == "effect:v1:abc"
    completed = [p for m, p in emitter.notified if m.endswith("item/completed")]
    assert completed[-1]["item"]["effectReceipt"] == {
        "effectKey": "effect:v1:abc",
        "callId": "write-1",
        "state": "indeterminate",
        "reason": "outcome unknown",
        "fencingToken": 7,
    }


@pytest.mark.asyncio
async def test_reasoning_duration_ms_filled_on_complete() -> None:
    """ReasoningItem.duration_ms is filled from first append_reasoning to flush."""
    state = _ReactBridgeState()
    turn = _make_turn()
    emitter = _StubEmitter()
    log = _StubLog()

    await state.append_reasoning(turn, log, emitter, "think")
    assert state.reasoning_started_monotonic is not None
    # Elapse a small amount of real time before finalizing.
    await asyncio.sleep(0.01)
    await state.flush(turn, log, emitter)

    completed = [p for m, p in emitter.notified if m.endswith("item/completed")]
    assert completed
    reasoning_item = completed[-1]["item"]
    assert reasoning_item["type"] == "reasoning"
    # duration_ms should be a non-negative int, roughly >= 10ms we slept.
    assert isinstance(reasoning_item["durationMs"], int)
    assert reasoning_item["durationMs"] >= 8
    # After completion, the bridge slot is cleared.
    assert state.reasoning is None
    assert state.reasoning_started_monotonic is None


@pytest.mark.asyncio
async def test_reasoning_duration_ms_none_when_no_reasoning_emitted() -> None:
    """No reasoning item → no duration_ms to fill; bridge stays clean."""
    state = _ReactBridgeState()
    turn = _make_turn()
    emitter = _StubEmitter()
    log = _StubLog()

    await state.append_agent_message(turn, log, emitter, "answer only")
    await state.flush(turn, log, emitter)

    completed = [p for m, p in emitter.notified if m.endswith("item/completed")]
    assert completed
    # No reasoning item was ever opened, so the slot is None throughout.
    assert state.reasoning is None
    assert state.reasoning_started_monotonic is None


def test_reasoning_item_duration_ms_default_is_none() -> None:
    """Legacy ReasoningItem without duration_ms must deserialize to None."""
    from runtime.protocol import ReasoningItem

    item = ReasoningItem(content="legacy")
    assert item.duration_ms is None
    # Alias round-trip for the wire format.
    dumped = item.model_dump(by_alias=True)
    assert dumped["durationMs"] is None


def test_reasoning_item_duration_ms_round_trip() -> None:
    """Explicit duration_ms survives serialization with the wire alias."""
    from runtime.protocol import ReasoningItem

    item = ReasoningItem(content="done", duration_ms=1234)
    dumped = item.model_dump(by_alias=True)
    assert dumped["durationMs"] == 1234
    # And a round-trip via model_validate on the aliased dict.
    restored = ReasoningItem.model_validate(dumped)
    assert restored.duration_ms == 1234

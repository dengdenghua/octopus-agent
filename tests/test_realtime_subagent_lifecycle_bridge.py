"""Tests for the realtime sub-agent lifecycle journal→WS bridge.

``run_orchestration`` sub-agents carry no in-memory event emitter (the
``event_emitter`` arg ``call_subagent`` accepts is never passed on that
path), so their spawn/finish lifecycle events only reach the genome
journal — and only when ``session.metadata["journal"]`` is injected.
These tests pin the bridge in ``_realtime_react_stream_drive`` that lifts
those journal events back onto the realtime WS as marker
``McpToolCallItem``s, which the frontend's ``mcpItemToLiveEvent`` renders
as workbench tiles.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from runtime.memory.journal import SubToolEndEvent, SubToolStartEvent
from runtime.memory.journal._journal_base import Journal
from runtime.platform.models import TaskId
from runtime.protocol import (
    ItemMarker,
    ItemStatus,
    McpToolCallItem,
    ServerMethod,
)
from runtime.sensing.gateway._realtime_react_stream_drive import (
    _emit_subagent_lifecycle_item,
    _parse_lifecycle_preview,
    _start_subagent_lifecycle_bridge,
    _subagent_lifecycle_item_from_journal,
    _subagent_lifecycle_matches,
)

SPAWN_MARKER = ItemMarker.SUBAGENT_SPAWNED.value
FINISH_MARKER = ItemMarker.SUBAGENT_FINISHED.value


def _spawn_event(
    task_id: UUID | None = None,
    *,
    preview: str | None = None,
    parent: str | None = "parent-1",
) -> SubToolStartEvent:
    task_id = task_id or uuid4()
    payload = {
        "agent_id": "researcher",
        "codename": "researcher",
        "avatar": "🕵️",
        "task": "find leaks",
    }
    return SubToolStartEvent(
        task_id=TaskId(task_id),
        role_id="researcher",
        tool_call_id="researcher",
        tool_name=SPAWN_MARKER,
        iteration=0,
        args_preview=preview if preview is not None else json.dumps(payload),
        parent_tool_use_id=parent,
    )


def _finish_event(
    task_id: UUID | None = None,
    *,
    preview: str | None = None,
    parent: str | None = "parent-1",
) -> SubToolEndEvent:
    task_id = task_id or uuid4()
    payload = {"ok": True, "summary": "found 2 leaks"}
    return SubToolEndEvent(
        task_id=TaskId(task_id),
        role_id="researcher",
        tool_call_id="researcher",
        tool_name=FINISH_MARKER,
        iteration=0,
        output_preview=preview if preview is not None else json.dumps(payload),
        parent_tool_use_id=parent,
    )


# ---------------------------------------------------------------------------
# _parse_lifecycle_preview
# ---------------------------------------------------------------------------


def test_parse_preview_roundtrip() -> None:
    payload = {"agent_id": "researcher", "nested": {"a": 1}}
    assert _parse_lifecycle_preview(json.dumps(payload)) == payload


def test_parse_preview_tolerates_junk() -> None:
    assert _parse_lifecycle_preview(None) == {}
    assert _parse_lifecycle_preview("") == {}
    assert _parse_lifecycle_preview("   ") == {}
    assert _parse_lifecycle_preview(42) == {}
    assert _parse_lifecycle_preview("{not json") == {}
    assert _parse_lifecycle_preview("[1, 2, 3]") == {}
    assert _parse_lifecycle_preview('"a string"') == {}


# ---------------------------------------------------------------------------
# _subagent_lifecycle_item_from_journal
# ---------------------------------------------------------------------------


def test_ignores_non_subtool_events() -> None:
    # A plain step/telemetry journal event must never be lifted onto the WS.
    event = SimpleNamespace(
        event_type="step",
        task_id=TaskId(uuid4()),
        tool_name="bash",
        args_preview=json.dumps({"cmd": "ls"}),
    )
    assert _subagent_lifecycle_item_from_journal(event) is None


def test_ignores_subtool_event_with_non_marker_tool() -> None:
    event = SubToolStartEvent(
        task_id=TaskId(uuid4()),
        tool_name="bash",
        args_preview=json.dumps({"cmd": "ls"}),
    )
    assert _subagent_lifecycle_item_from_journal(event) is None


def test_spawn_marker_synthesises_in_progress_item() -> None:
    task_id = uuid4()
    event = _spawn_event(task_id)
    item = _subagent_lifecycle_item_from_journal(event)
    assert item is not None
    assert item.server == "runtime"
    assert item.tool == SPAWN_MARKER
    assert item.status == ItemStatus.IN_PROGRESS
    assert item.id.startswith("subagent_spawn_")
    assert item.arguments["agent_id"] == "researcher"
    assert item.arguments["parent_tool_use_id"] == "parent-1"
    assert item.result is None


def test_spawn_marker_empty_preview_defaults_empty_args() -> None:
    event = _spawn_event(preview="", parent=None)
    item = _subagent_lifecycle_item_from_journal(event)
    assert item is not None
    assert item.arguments == {}
    assert "parent_tool_use_id" not in item.arguments


def test_finish_ok_marker_is_completed() -> None:
    task_id = uuid4()
    event = _finish_event(task_id)
    item = _subagent_lifecycle_item_from_journal(event)
    assert item is not None
    assert item.tool == FINISH_MARKER
    assert item.status == ItemStatus.COMPLETED
    # The bridge injects the parent ref into the parsed payload, so it rides
    # on the result dict as well as the arguments.
    assert item.result == {
        "ok": True,
        "summary": "found 2 leaks",
        "parent_tool_use_id": "parent-1",
    }
    assert item.arguments == {"parent_tool_use_id": "parent-1"}
    assert item.id.startswith("subagent_finish_")


def test_finish_ok_defaults_true_when_missing() -> None:
    event = _finish_event(preview=json.dumps({"summary": "done"}))
    item = _subagent_lifecycle_item_from_journal(event)
    assert item is not None
    assert item.status == ItemStatus.COMPLETED


def test_finish_error_marker_is_failed() -> None:
    event = _finish_event(preview=json.dumps({"ok": False, "error": "boom"}))
    item = _subagent_lifecycle_item_from_journal(event)
    assert item is not None
    assert item.status == ItemStatus.FAILED
    assert item.result == {
        "ok": False,
        "error": "boom",
        "parent_tool_use_id": "parent-1",
    }


def test_event_id_compacted_to_16_hex() -> None:
    task_id = uuid4()
    event = _spawn_event(task_id)
    item = _subagent_lifecycle_item_from_journal(event)
    assert item is not None
    # event_id is a full uuid4 str; the bridge strips dashes + truncates.
    assert item.id == f"subagent_spawn_{str(event.event_id).replace('-', '')[:16]}"
    assert len(item.id) == len("subagent_spawn_") + 16


# ---------------------------------------------------------------------------
# _subagent_lifecycle_matches
# ---------------------------------------------------------------------------


def test_lifecycle_matches() -> None:
    task_id = uuid4()
    event = _spawn_event(task_id)
    assert _subagent_lifecycle_matches(event, str(task_id)) is True
    assert _subagent_lifecycle_matches(event, str(uuid4())) is False
    assert _subagent_lifecycle_matches(event, "") is False


def test_lifecycle_matches_event_without_task_id() -> None:
    event = SubToolStartEvent(
        tool_name=SPAWN_MARKER,
        args_preview=json.dumps({"agent_id": "researcher"}),
    )
    assert _subagent_lifecycle_matches(event, str(uuid4())) is False


# ---------------------------------------------------------------------------
# _start_subagent_lifecycle_bridge — guard branches
# ---------------------------------------------------------------------------


def _fake_runtime(journal: Any) -> SimpleNamespace:
    return SimpleNamespace(_stack=SimpleNamespace(journal=journal))


def test_bridge_returns_none_when_no_journal() -> None:
    runtime = SimpleNamespace(_stack=SimpleNamespace(journal=None))
    assert (
        _start_subagent_lifecycle_bridge(
            runtime,
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            asyncio.new_event_loop(),
            str(uuid4()),
        )
        is None
    )


def test_bridge_returns_none_for_base_journal_subscribe() -> None:
    # A Journal subclass that doesn't override subscribe inherits the base
    # no-op — the bridge must not wire a subscription that never fires.
    class _NoOpJournal(Journal):
        pass

    runtime = _fake_runtime(_NoOpJournal())
    assert (
        _start_subagent_lifecycle_bridge(
            runtime,
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            asyncio.new_event_loop(),
            str(uuid4()),
        )
        is None
    )


def test_bridge_returns_none_when_journal_lacks_subscribe() -> None:
    runtime = _fake_runtime(SimpleNamespace(write=lambda event: None))
    assert (
        _start_subagent_lifecycle_bridge(
            runtime,
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            asyncio.new_event_loop(),
            str(uuid4()),
        )
        is None
    )


# ---------------------------------------------------------------------------
# _start_subagent_lifecycle_bridge — live subscription path
# ---------------------------------------------------------------------------


class _FakeStreamingJournal:
    """Stand-in for ``StreamingJournal``: real ``subscribe`` + fan-out."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[[Any], None]] = []

    def subscribe(self, callback: Callable[[Any], None]) -> Callable[[], None]:
        self._callbacks.append(callback)

        def _unsubscribe() -> None:
            self._callbacks.remove(callback)

        return _unsubscribe


def test_bridge_subscribes_and_filters_lifecycle_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _FakeStreamingJournal()
    runtime = _fake_runtime(journal)
    turn = SimpleNamespace(thread_id="t1", id="turn-1", items=[])
    log = SimpleNamespace()
    emitter = SimpleNamespace()

    scheduled: list[tuple[Any, bool]] = []

    def _capture(coro: Any, loop: Any) -> asyncio.Future:
        del loop
        scheduled.append(coro)
        coro.close()  # never awaited — drop it cleanly instead of GC-warn
        return None  # type: ignore[return-value]  # bridge ignores the future

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _capture)

    loop = asyncio.new_event_loop()
    task_id = uuid4()
    unsubscribe = _start_subagent_lifecycle_bridge(
        runtime,
        turn,
        log,
        emitter,
        loop,
        str(task_id),
    )
    assert unsubscribe is not None
    assert len(journal._callbacks) == 1
    callback = journal._callbacks[0]

    # Non-marker event for the same task: dropped.
    callback(
        SubToolStartEvent(
            task_id=TaskId(task_id),
            tool_name="bash",
            args_preview="{}",
        )
    )
    assert scheduled == []

    # Lifecycle event for a different task: dropped.
    callback(_spawn_event(uuid4()))
    assert scheduled == []

    # Lifecycle event for this task: scheduled on the driver's loop.
    callback(_spawn_event(task_id))
    assert len(scheduled) == 1
    coro = scheduled[0]
    assert asyncio.iscoroutine(coro)

    # Finish (terminal) event: scheduled with terminal=True.
    callback(_finish_event(task_id))
    assert len(scheduled) == 2

    # Unsubscribe stops the fan-out.
    unsubscribe()
    assert journal._callbacks == []


def test_bridge_schedules_on_provided_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _FakeStreamingJournal()
    runtime = _fake_runtime(journal)
    loop = asyncio.new_event_loop()

    captured: list[asyncio.AbstractEventLoop] = []

    def _capture(coro: Any, target_loop: Any) -> asyncio.Future:
        captured.append(target_loop)
        coro.close()  # never awaited — drop it cleanly instead of GC-warn
        return None  # type: ignore[return-value]  # bridge ignores the future

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _capture)
    task_id = uuid4()
    unsubscribe = _start_subagent_lifecycle_bridge(
        runtime,
        SimpleNamespace(thread_id="t1", id="turn-1", items=[]),
        SimpleNamespace(),
        SimpleNamespace(),
        loop,
        str(task_id),
    )
    assert unsubscribe is not None
    journal._callbacks[0](_spawn_event(task_id))
    assert captured == [loop]
    loop.close()


# ---------------------------------------------------------------------------
# _emit_subagent_lifecycle_item
# ---------------------------------------------------------------------------


class _FakeEventLog:
    def __init__(self) -> None:
        self.started: list[McpToolCallItem] = []
        self.completed: list[McpToolCallItem] = []

    def item_started(self, thread_id: str, turn_id: str, item: McpToolCallItem):
        del thread_id, turn_id
        self.started.append(item)
        return SimpleNamespace(event_id="log-1")

    def item_completed(self, thread_id: str, turn_id: str, item: McpToolCallItem):
        del thread_id, turn_id
        self.completed.append(item)
        return SimpleNamespace(event_id="log-2")


class _FakeEmitter:
    def __init__(self) -> None:
        self.notified: list[tuple[Any, dict[str, Any]]] = []

    async def notify(self, method: Any, payload: dict[str, Any]) -> None:
        self.notified.append((method, payload))


@pytest.mark.asyncio()
async def test_emit_appends_logs_and_notifies() -> None:
    turn = SimpleNamespace(thread_id="t1", id="turn-1", items=[])
    log = _FakeEventLog()
    emitter = _FakeEmitter()

    spawn_item = _subagent_lifecycle_item_from_journal(_spawn_event(uuid4()))
    assert spawn_item is not None
    await _emit_subagent_lifecycle_item(turn, log, emitter, spawn_item, terminal=False)

    assert turn.items == [spawn_item]
    assert log.started == [spawn_item]
    assert log.completed == []
    assert len(emitter.notified) == 1
    method, payload = emitter.notified[0]
    assert method is ServerMethod.ITEM_STARTED
    assert payload["threadId"] == "t1"
    assert payload["turnId"] == "turn-1"
    assert payload["eventId"] == "log-1"
    assert payload["item"]["id"] == spawn_item.id
    assert payload["item"]["tool"] == SPAWN_MARKER

    finish_item = _subagent_lifecycle_item_from_journal(_finish_event(uuid4()))
    assert finish_item is not None
    await _emit_subagent_lifecycle_item(turn, log, emitter, finish_item, terminal=True)
    assert log.completed == [finish_item]
    assert len(emitter.notified) == 2
    assert emitter.notified[1][0] is ServerMethod.ITEM_COMPLETED
    assert emitter.notified[1][1]["eventId"] == "log-2"


@pytest.mark.asyncio()
async def test_emit_tolerates_notify_failure() -> None:
    turn = SimpleNamespace(thread_id="t1", id="turn-1", items=[])
    log = _FakeEventLog()

    class _BoomEmitter:
        async def notify(self, method: Any, payload: dict[str, Any]) -> None:
            raise RuntimeError("socket closed")

    spawn_item = _subagent_lifecycle_item_from_journal(_spawn_event(uuid4()))
    assert spawn_item is not None
    # Must not raise: the item is already appended + logged.
    await _emit_subagent_lifecycle_item(
        turn,
        log,
        _BoomEmitter(),
        spawn_item,
        terminal=False,
    )
    assert turn.items == [spawn_item]
    assert log.started == [spawn_item]

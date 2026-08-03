"""Active-turn lease + steering management for the realtime runtime.

Split out of ``realtime_cerebrum.py``: the per-turn registry, the
on-disk active-turn lease files (used to detect a stale process reaping
in-progress turns) and the live steering queue that is the only
synchronization boundary between the asyncio RPC thread and the
native model/tool loop.

Every function takes the owning ``CerebrumRuntime`` as its first
argument; cross-method calls go through the runtime so subclass
overrides keep working.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import TYPE_CHECKING, Any

from runtime.memory.threads.event_log import EventLog
from runtime.protocol import ServerMethod, SteeringUserMessageItem, Turn
from runtime.sensing.gateway.realtime_gateway import EventEmitter

if TYPE_CHECKING:
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

_logger = logging.getLogger(__name__)


def _register_active_turn(runtime: CerebrumRuntime, turn: Turn, log: EventLog) -> None:
    runtime._active_turns[turn.id] = (turn, log)
    runtime._turn_steering[turn.id] = SimpleQueue()
    runtime._turn_steering_seen[turn.id] = {
        item.id for item in turn.items if isinstance(item, SteeringUserMessageItem)
    }
    runtime._turn_steering_notified[turn.id] = set(runtime._turn_steering_seen[turn.id])
    runtime._turn_steering_last_sync[turn.id] = 0.0
    try:
        runtime._turn_steering_log_offsets[turn.id] = log.path.stat().st_size
    except OSError:
        runtime._turn_steering_log_offsets[turn.id] = 0
    runtime._turn_steering_accepting[turn.id] = True
    previous = max(
        (item for item in turn.items if item.timeline_sequence is not None),
        key=lambda item: item.timeline_sequence or 0,
        default=None,
    )
    runtime._turn_timeline[turn.id] = (
        previous.timeline_sequence or 0 if previous is not None else 0,
        previous.id if previous is not None else None,
    )
    _write_active_turn_lease(runtime, turn)

    async def _refresh_lease() -> None:
        try:
            while turn.id in runtime._active_turns:
                await asyncio.sleep(2.0)
                _write_active_turn_lease(runtime, turn)
        except asyncio.CancelledError:
            return

    runtime._active_turn_lease_tasks[turn.id] = asyncio.create_task(_refresh_lease())


def _unregister_active_turn(runtime: CerebrumRuntime, turn_id: str) -> None:
    runtime._active_turns.pop(turn_id, None)
    runtime._turn_steering.pop(turn_id, None)
    runtime._turn_steering_seen.pop(turn_id, None)
    runtime._turn_steering_notified.pop(turn_id, None)
    runtime._turn_steering_last_sync.pop(turn_id, None)
    runtime._turn_steering_log_offsets.pop(turn_id, None)
    runtime._turn_steering_accepting.pop(turn_id, None)
    runtime._turn_timeline.pop(turn_id, None)
    task = runtime._active_turn_lease_tasks.pop(turn_id, None)
    if task is not None:
        task.cancel()
    _remove_active_turn_lease(runtime, turn_id)


def _active_turn_lease_path(runtime: CerebrumRuntime, turn_id: str) -> Path:
    digest = hashlib.sha256(turn_id.encode("utf-8")).hexdigest()
    return runtime._active_turn_lease_root / f"{digest}.json"


def _write_active_turn_lease(runtime: CerebrumRuntime, turn: Turn) -> None:
    path = _active_turn_lease_path(runtime, turn.id)
    payload = {
        "turnId": turn.id,
        "threadId": turn.thread_id,
        "instanceId": runtime._instance_id,
        "updatedAt": time.time(),
        "acceptingSteering": runtime._turn_steering_accepting.get(turn.id, False),
    }
    temporary = path.with_suffix(f".{runtime._instance_id}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        _logger.warning("failed to refresh active-turn lease %s", turn.id, exc_info=True)
        with contextlib.suppress(OSError):
            temporary.unlink()


def _has_fresh_active_turn_lease(
    runtime: CerebrumRuntime,
    thread_id: str,
    turn_id: str,
    *,
    require_accepting_steering: bool = False,
) -> bool:
    try:
        payload = json.loads(_active_turn_lease_path(runtime, turn_id).read_text(encoding="utf-8"))
        fresh = (
            payload.get("turnId") == turn_id
            and payload.get("threadId") == thread_id
            and time.time() - float(payload.get("updatedAt") or 0) <= 8.0
        )
        return fresh and (
            not require_accepting_steering or payload.get("acceptingSteering") is True
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _remove_active_turn_lease(runtime: CerebrumRuntime, turn_id: str) -> None:
    path = _active_turn_lease_path(runtime, turn_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("instanceId") != runtime._instance_id:
            return
        path.unlink()
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return


def _set_turn_steering_accepting(runtime: CerebrumRuntime, turn: Turn, accepting: bool) -> None:
    if turn.id not in runtime._active_turns:
        return
    runtime._turn_steering_accepting[turn.id] = accepting
    _write_active_turn_lease(runtime, turn)


def _bind_turn_timeline(
    runtime: CerebrumRuntime,
    turn_id: str,
    item: Any,
    *,
    phase_id: str | None = None,
) -> None:
    sequence, previous_id = runtime._turn_timeline.get(turn_id, (0, None))
    if getattr(item, "timeline_sequence", None) is None:
        active = runtime._active_turns.get(turn_id)
        sequence = (
            active[1].reserve_timeline_sequence(turn_id) if active is not None else sequence + 1
        )
        item.timeline_sequence = sequence
    else:
        sequence = max(sequence, int(item.timeline_sequence))
    if getattr(item, "parent_item_id", None) is None:
        item.parent_item_id = previous_id
    if getattr(item, "phase_id", None) is None:
        item.phase_id = phase_id
    runtime._turn_timeline[turn_id] = (sequence, item.id)


def _sync_persisted_turn_steering(
    runtime: CerebrumRuntime,
    turn_id: str,
    *,
    force: bool = False,
) -> list[SteeringUserMessageItem]:
    active = runtime._active_turns.get(turn_id)
    if active is None:
        return []
    turn, log = active
    now = time.monotonic()
    with runtime._turn_steering_lock:
        last_sync = runtime._turn_steering_last_sync.get(turn_id, 0.0)
        if not force and now - last_sync < 0.1:
            return []
        runtime._turn_steering_last_sync[turn_id] = now
    with runtime._turn_steering_lock:
        offset = runtime._turn_steering_log_offsets.get(turn_id, 0)
        events, next_offset = log.tail_events(offset)
        runtime._turn_steering_log_offsets[turn_id] = next_offset
    discovered: list[SteeringUserMessageItem] = []
    pending = runtime._turn_steering.get(turn_id)
    if pending is None:
        return []
    incoming: list[SteeringUserMessageItem] = []
    for event in events:
        if event.event != "item_completed" or event.turn_id != turn_id:
            continue
        raw_item = event.payload.get("item")
        if not isinstance(raw_item, dict) or raw_item.get("type") != "steeringUserMessage":
            continue
        try:
            incoming.append(SteeringUserMessageItem.model_validate(raw_item))
        except (TypeError, ValueError):
            continue
    with runtime._turn_steering_lock:
        seen = runtime._turn_steering_seen.setdefault(turn_id, set())
        live_indexes = {item.id: index for index, item in enumerate(turn.items)}
        for item in incoming:
            existing_index = live_indexes.get(item.id)
            if existing_index is None:
                turn.items.append(item)
                live_indexes[item.id] = len(turn.items) - 1
            else:
                turn.items[existing_index] = item
            if item.id in seen:
                continue
            seen.add(item.id)
            sequence = item.timeline_sequence
            if sequence is None:
                sequence = log.reserve_timeline_sequence(turn_id)
                item.timeline_sequence = sequence
            current_sequence, _ = runtime._turn_timeline.get(turn_id, (0, None))
            runtime._turn_timeline[turn_id] = (max(current_sequence, sequence), item.id)
            pending.put((item.id, item.text))
            discovered.append(item)
    return discovered


async def _publish_discovered_steering(
    runtime: CerebrumRuntime,
    turn: Turn,
    emitter: EventEmitter,
) -> None:
    _sync_persisted_turn_steering(runtime, turn.id)
    with runtime._turn_steering_lock:
        notified = runtime._turn_steering_notified.setdefault(turn.id, set())
        pending = [
            item
            for item in turn.items
            if isinstance(item, SteeringUserMessageItem) and item.id not in notified
        ]
        notified.update(item.id for item in pending)
    for item in pending:
        await emitter.notify(
            ServerMethod.ITEM_COMPLETED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )


def _drain_turn_steering(runtime: CerebrumRuntime, turn_id: str) -> list[str]:
    _sync_persisted_turn_steering(runtime, turn_id, force=True)
    pending = runtime._turn_steering.get(turn_id)
    if pending is None:
        return []
    messages: list[str] = []
    while True:
        try:
            _, text = pending.get_nowait()
        except Empty:
            break
        messages.append(text)
    return messages

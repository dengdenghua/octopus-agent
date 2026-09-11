"""Verified conversation-only forks, without live requests or native bindings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from runtime.memory.threads._event_log_helpers import thread_log_path
from runtime.memory.threads.event_log import EventLog, LoggedEvent
from runtime.memory.threads.store import ForkUnavailableError
from runtime.protocol.items import TurnStatus

from .realtime_thread_history import _flatten_turns_to_messages


def seed_history(logs_root: Path | str | None, parent_id: str, child: dict[str, Any]) -> None:
    if not logs_root:
        return
    parent_path = thread_log_path(logs_root, parent_id)
    if not parent_path.exists():
        return  # Legacy-only conversations have no native event history.
    expected = child.get("values", {}).get("messages", [])
    parent = EventLog(parent_path)
    captured = parent.snapshot()
    selected = []
    messages: list[dict[str, Any]] = []
    for turn in captured.replay():
        if len(messages) >= len(expected):
            break
        if turn.status in {TurnStatus.IN_PROGRESS, TurnStatus.PAUSED}:
            raise ForkUnavailableError("source turn is still active")
        selected.append(turn)
        batch, _, _ = _flatten_turns_to_messages([turn])
        messages.extend(batch)

    # The sidebar snapshot and durable history must agree on the exact prefix.
    def content(rows):
        return [(row.get("type"), row.get("content"), row.get("tool_calls")) for row in rows]

    if content(messages) != content(expected):
        raise ForkUnavailableError("source history changed; refresh before forking")
    child_id = child["thread_id"]
    events = [
        LoggedEvent(
            event="thread_started",
            threadId=child_id,
            payload={
                "streamId": f"stream_{uuid4().hex}",
                "forkedTurnIds": [turn.id for turn in selected],
                "historySourceThreadId": parent_id,
            },
        )
    ]
    for turn in selected:
        params = turn.params.model_dump(by_alias=True, mode="json") if turn.params else None
        if params is not None:
            params["threadId"] = child_id

        def event(kind, payload, ts=turn.started_at, turn_id=turn.id):
            return LoggedEvent(
                event=kind, threadId=child_id, turnId=turn_id, payload=payload, ts=ts
            )

        events.append(event("turn_started", {"params": params}))
        # Preserve historical evidence, but never copy pending dialogs, active
        # subscriptions, interrupt requests, leases or engine session IDs.
        for item in turn.items:
            if item.type == "approval":
                continue
            events.append(
                event("item_completed", {"item": item.model_dump(by_alias=True, mode="json")})
            )
        wire = turn.model_dump(by_alias=True, mode="json")
        events.append(
            event(
                "turn_updated",
                {
                    key: wire[key]
                    for key in ("execution", "executionModel", "grounding", "outcomeReason")
                    if wire.get(key) is not None
                },
            )
        )
        events.append(
            event(
                "turn_completed",
                {"status": turn.status.value, "error": turn.error},
                turn.completed_at or turn.started_at,
            )
        )
    after = parent.snapshot()
    if after.cursor != captured.cursor or after.events != captured.events:
        raise ForkUnavailableError("source history changed during fork")
    destination = thread_log_path(logs_root, child_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            for item in events:
                stream.write(
                    item.model_copy(update={"event_id": f"evt_{uuid4().hex}"}).model_dump_json(
                        by_alias=True
                    )
                    + "\n"
                )
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)

"""Bounded OpenCode SSE input and current-turn projection, independent of the UI."""

from __future__ import annotations

import asyncio
import json
import math
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx

_message_clock = 0


def reported_turn_cost(messages, user_message_id):
    """Sum explicit native costs only; an absent cost is not a free call."""
    costs = {}
    for message in messages:
        info = message.get("info") or {}
        if info.get("role") != "assistant" or info.get("parentID") != user_message_id:
            continue
        value = info.get("cost")
        if not info.get("id") or type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return None
        costs[info["id"]] = max(costs.get(info["id"], 0), value)
    return sum(costs.values()) if costs else None


def message_id() -> str:
    """Match native ascending ID ordering (48-bit clock, 14 random chars)."""
    global _message_clock
    _message_clock = max(_message_clock + 1, (time.time_ns() // 1_000_000) << 12)
    return f"msg_{_message_clock & ((1 << 48) - 1):012x}{secrets.token_hex(7)}"


async def receive_events(
    client: httpx.AsyncClient,
    queue: asyncio.Queue[dict[str, Any] | None],
    ready: asyncio.Event,
) -> None:
    """A gap ends streaming for this turn; snapshots then reconcile safely.

    Do not reconnect and append unsequenced deltas across a snapshot boundary:
    native events may overlap the snapshot and duplicate visible text.
    """
    seen: set[str] = set()
    recent: deque[str] = deque()
    try:
        async with client.stream(
            "GET",
            "/event",
            headers={"Accept": "text/event-stream"},
            timeout=httpx.Timeout(45, connect=2, pool=2),
        ) as response:
            response.raise_for_status()
            if "text/event-stream" not in response.headers.get("content-type", ""):
                return
            ready.set()
            data: list[str] = []
            size = 0
            async for line in response.aiter_lines():
                size += len(line)
                if size > 1_000_000:
                    return
                if line:
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip(" "))
                    continue
                if data:
                    event = json.loads("\n".join(data))
                    if not isinstance(event, dict):
                        return
                    event_id = event.get("id")
                    if not isinstance(event_id, str) or event_id not in seen:
                        await queue.put(event)
                        if isinstance(event_id, str):
                            seen.add(event_id)
                            recent.append(event_id)
                            if len(recent) > 256:
                                seen.discard(recent.popleft())
                data = []
                size = 0
    except (httpx.HTTPError, ValueError):
        pass  # The caller reconciles with native messages, never resends a prompt.
    finally:
        ready.set()
        # Cancellation is cleanup: never wait on a full queue at shutdown.
        task = asyncio.current_task()
        if task is not None and not task.cancelling():
            await queue.put(None)


@dataclass
class TurnEvents:
    session_id: str
    user_message_id: str
    reducer: Any
    assistants: set[str] = field(default_factory=set)
    parts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def snapshots(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        owned = []
        for message in messages:
            info = message.get("info", {})
            if info.get("role") != "assistant" or info.get("parentID") != self.user_message_id:
                continue
            self.assistants.add(info["id"])
            owned.append(message)
        return self.reducer.consume(owned)

    def consume(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        kind = event.get("type")
        props = event.get("properties", {})
        if not isinstance(props, dict):
            return []
        if kind == "message.updated":
            info = props.get("info", {})
            if (
                info.get("sessionID") == self.session_id
                and info.get("role") == "assistant"
                and info.get("parentID") == self.user_message_id
            ):
                self.assistants.add(info["id"])
            return []
        if kind == "message.part.updated":
            part = props.get("part", {})
            if (
                part.get("sessionID") != self.session_id
                or part.get("messageID") not in self.assistants
            ):
                return []
            part_id = part.get("id")
            if not isinstance(part_id, str):
                return []
            old = self.parts.get(part_id)
            # Snapshots can lag a delta already received on this connection.
            if (
                old
                and part.get("type") == "text"
                and str(old.get("text", "")).startswith(str(part.get("text", "")))
            ):
                return []
            self.parts[part_id] = dict(part)
        elif kind == "message.part.delta":
            if (
                props.get("sessionID") != self.session_id
                or props.get("messageID") not in self.assistants
                or props.get("field") != "text"
                or not isinstance(props.get("delta"), str)
            ):
                return []
            part = self.parts.get(props.get("partID"))
            # Unknown Part types may be reasoning, not public answer text.
            # Missing identities/content are repaired by the terminal snapshot.
            if not part or part.get("type") != "text":
                return []
            part["text"] = str(part.get("text") or "") + props["delta"]
        else:
            return []
        return self.reducer.consume(
            [{"info": {"id": part["messageID"], "role": "assistant"}, "parts": [part]}]
        )

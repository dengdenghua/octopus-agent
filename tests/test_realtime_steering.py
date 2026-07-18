from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.protocol import Turn
from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime


class _Emitter:
    actor_id = None

    def __init__(self) -> None:
        self.notifications: list[tuple[str, dict[str, Any]]] = []

    async def notify(self, method: Any, params: dict[str, Any]) -> None:
        self.notifications.append((str(method), params))


@pytest.mark.asyncio
async def test_turn_steer_is_persisted_and_queued_for_the_active_model(tmp_path: Path) -> None:
    runtime = CerebrumRuntime(stack=object(), logs_root=str(tmp_path / "threads"))
    emitter = _Emitter()
    log = await runtime._ensure_thread("thread-steer", emitter)
    turn = Turn(thread_id="thread-steer")
    runtime._active_turn_ids.add(turn.id)
    runtime._register_active_turn(turn, log)

    result = await runtime.handle_request(
        "turn/steer",
        {
            "threadId": "thread-steer",
            "turnId": turn.id,
            "itemId": "itm_client_1",
            "text": "先别改文件，先确认根因",
        },
        emitter,
    )

    assert result == {"turnId": turn.id, "itemId": "itm_client_1", "accepted": True}
    assert runtime._drain_turn_steering(turn.id) == ["先别改文件，先确认根因"]
    assert runtime._drain_turn_steering(turn.id) == []
    assert turn.items[0].type == "steeringUserMessage"
    assert turn.items[0].status == "completed"
    assert turn.items[0].timeline_sequence == 1
    assert [method for method, _ in emitter.notifications[-2:]] == [
        "item/started",
        "item/completed",
    ]


@pytest.mark.asyncio
async def test_turn_steer_rejects_a_finished_turn(tmp_path: Path) -> None:
    runtime = CerebrumRuntime(stack=object(), logs_root=str(tmp_path / "threads"))
    emitter = _Emitter()
    await runtime._ensure_thread("thread-finished", emitter)

    with pytest.raises(Exception, match="target turn is not active"):
        await runtime.handle_request(
            "turn/steer",
            {
                "threadId": "thread-finished",
                "turnId": "turn-finished",
                "text": "继续",
            },
            emitter,
        )

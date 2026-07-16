from __future__ import annotations

import json

import pytest
from websockets.asyncio.server import serve

from benchmarks.realtime_runner import RealtimeTrialRunner


@pytest.mark.asyncio
async def test_realtime_trial_runner_captures_turn_and_approval(tmp_path) -> None:
    received: dict[str, object] = {}

    async def handler(websocket) -> None:
        start = json.loads(await websocket.recv())
        received["start"] = start
        await websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "item/agentMessage/delta",
                    "params": {"delta": "hello"},
                }
            )
        )
        await websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "approval-1",
                    "method": "item/commandExecution/requestApproval",
                    "params": {"command": "safe-command"},
                }
            )
        )
        received["approval"] = json.loads(await websocket.recv())
        await websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "item/started",
                    "params": {
                        "item": {
                            "id": "cmd-1",
                            "type": "commandExecution",
                            "command": "safe-command",
                        }
                    },
                }
            )
        )
        await websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "item/completed",
                    "params": {
                        "item": {
                            "id": "cmd-1",
                            "type": "commandExecution",
                            "command": "safe-command",
                            "status": "declined",
                        }
                    },
                }
            )
        )
        await websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": start["id"],
                    "result": {
                        "turn": {
                            "status": "completed",
                            "items": [{"type": "agentMessage", "text": "hello"}],
                        }
                    },
                }
            )
        )

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        runner = RealtimeTrialRunner(
            url=f"ws://127.0.0.1:{port}/api/realtime",
            approval_action="decline",
            workspace=tmp_path,
            timeout_seconds=5,
        )
        events = await runner.run("run the fixture")

    start = received["start"]
    assert isinstance(start, dict)
    assert start["method"] == "turn/start"
    assert start["params"]["input"][0]["text"] == "run the fixture"
    assert start["params"]["input"][0]["metadata"]["isolatedTrial"] is True
    assert start["params"]["cwd"] == str(tmp_path.resolve())
    assert received["approval"] == {
        "jsonrpc": "2.0",
        "id": "approval-1",
        "result": {"action": "decline"},
    }
    assert [event for event in events if event["kind"] == "text_delta"] == [
        {"kind": "text_delta", "delta": "hello"}
    ]
    assert [event["kind"] for event in events if event["kind"].startswith("tool_")] == [
        "tool_start",
        "tool_end",
    ]
    assert events[-1]["kind"] == "turn_result"


@pytest.mark.asyncio
async def test_realtime_trial_runner_uses_final_text_when_delta_was_lost() -> None:
    async def handler(websocket) -> None:
        start = json.loads(await websocket.recv())
        await websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": start["id"],
                    "result": {
                        "turn": {
                            "status": "completed",
                            "items": [{"type": "agentMessage", "text": "recovered"}],
                        }
                    },
                }
            )
        )

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        events = await RealtimeTrialRunner(
            url=f"ws://127.0.0.1:{port}/api/realtime",
            timeout_seconds=5,
        ).run("recover")

    assert {"kind": "text_delta", "delta": "recovered"} in events

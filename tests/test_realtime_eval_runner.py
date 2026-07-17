from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from benchmarks.realtime_runner import RealtimeTrialRunner
from benchmarks.run_behavioral_suite import (
    _approval_behavior,
    _approval_responder,
    _context_overrides,
)


def test_behavioral_suite_accepts_normal_fixture_edits_only() -> None:
    assert _approval_behavior("coding.path-boundary") == ("never", "accept")
    assert _approval_behavior("security.untrusted-instructions") == ("never", "accept")
    assert _approval_behavior("security.denied-destructive-action") == (
        "on-request",
        "decline",
    )


def test_denied_action_responder_rejects_destructive_apply_but_accepts_safe_plan() -> None:
    responder = _approval_responder("security.denied-destructive-action")
    assert responder is not None
    assert responder(
        "item/commandExecution/requestApproval",
        {
            "tool": "exec_shell",
            "argsPreview": repr(
                {"command": "sqlite3 data.db < migration.sql", "cwd": "/tmp/trial"}
            ),
        },
    ) == {"action": "decline"}
    assert responder(
        "item/commandExecution/requestApproval",
        {
            "tool": "write_text_file",
            "argsPreview": repr(
                {"path": "/tmp/trial/safe_plan.json", "content": "approval_denied"}
            ),
        },
    ) == {"action": "accept"}
    assert _approval_responder("coding.path-boundary") is None


def test_browser_domain_selects_browser_work_surface() -> None:
    assert _context_overrides("browser_desktop_automation") == {
        "mode": "browser",
        "capability_mode": "browser",
        "browser_operation_mode": True,
        "browser_surface": "browser",
        "runtime_surfaces": ["browser"],
    }
    assert _context_overrides("production_coding") == {}


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
            topology_id="research_swarm_v1",
            timeout_seconds=5,
        )
        events = await runner.run("run the fixture")

    start = received["start"]
    assert isinstance(start, dict)
    assert start["method"] == "turn/start"
    assert start["params"]["input"][0]["text"] == "run the fixture"
    assert start["params"]["input"][0]["metadata"]["isolatedTrial"] is True
    assert start["params"]["input"][0]["metadata"]["context"] == {
        "mode": "code",
        "capability_mode": "code",
        "workspace_scope": "project",
        "workspace_path": str(tmp_path.resolve()),
    }
    assert start["params"]["cwd"] == str(tmp_path.resolve())
    assert start["params"]["topologyId"] == "research_swarm_v1"
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
async def test_realtime_trial_runner_applies_context_overrides_without_changing_workspace(
    tmp_path,
) -> None:
    received: dict[str, object] = {}

    async def handler(websocket) -> None:
        start = json.loads(await websocket.recv())
        received["start"] = start
        await websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": start["id"],
                    "result": {"turn": {"status": "completed", "items": []}},
                }
            )
        )

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        await RealtimeTrialRunner(
            url=f"ws://127.0.0.1:{port}/api/realtime",
            workspace=tmp_path,
            context_overrides={
                "mode": "browser",
                "capability_mode": "browser",
                "workspace_path": "/tmp/not-the-trial",
                "workspace_scope": "global",
            },
            timeout_seconds=5,
        ).run("use the browser UI")

    start = received["start"]
    context = start["params"]["input"][0]["metadata"]["context"]
    assert context == {
        "mode": "browser",
        "capability_mode": "browser",
        "workspace_scope": "project",
        "workspace_path": str(tmp_path.resolve()),
    }


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


@pytest.mark.asyncio
async def test_realtime_trial_runner_preserves_events_on_timeout() -> None:
    observed: list[dict[str, object]] = []

    async def handler(websocket) -> None:
        await websocket.recv()
        await websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "item/started",
                    "params": {"item": {"type": "commandExecution", "id": "cmd-1"}},
                }
            )
        )
        await asyncio.sleep(1)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        events = await RealtimeTrialRunner(
            url=f"ws://127.0.0.1:{port}/api/realtime",
            timeout_seconds=0.05,
            event_observer=observed.append,
        ).run("time out")

    assert events[0]["kind"] == "tool_start"
    assert events[-1]["kind"] == "error"
    assert events[-1]["error"]["type"] == "timeout"
    assert events[-1]["error"]["event_count_before_error"] == 1
    assert observed == events

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from runtime.sensing.gateway.subagents_router import create_subagents_router  # noqa: E402


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_subagents_router())
    return TestClient(app)


def test_dispatch_bounds_timeout_and_enforces_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_call_subagent(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append({"args": args, "kwargs": kwargs})
        return {
            "agent_id": args[0],
            "output": "ok",
            "success": True,
            "error": None,
        }

    monkeypatch.setattr(
        "runtime.execution.subagents.call_subagent",
        fake_call_subagent,
    )

    response = _client().post(
        "/api/subagents/dispatch",
        json={
            "subagent_type": "researcher",
            "prompt": "check",
            "timeout_s": 999999,
        },
    )

    assert response.status_code == 200
    assert calls[0]["kwargs"]["timeout_s"] == 900
    assert calls[0]["kwargs"]["timeout_seconds"] == 900.0


def test_dispatch_raises_tiny_timeout_to_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_call_subagent(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append({"args": args, "kwargs": kwargs})
        return {
            "agent_id": args[0],
            "output": "ok",
            "success": True,
            "error": None,
        }

    monkeypatch.setattr(
        "runtime.execution.subagents.call_subagent",
        fake_call_subagent,
    )

    response = _client().post(
        "/api/subagents/dispatch",
        json={
            "subagent_type": "researcher",
            "prompt": "check",
            "timeout_s": -10,
        },
    )

    assert response.status_code == 200
    assert calls[0]["kwargs"]["timeout_s"] == 1
    assert calls[0]["kwargs"]["timeout_seconds"] == 1.0


def test_dispatch_forwards_top_level_trace_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_call_subagent(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append({"args": args, "kwargs": kwargs})
        return {
            "agent_id": args[0],
            "output": "ok",
            "success": True,
            "error": None,
        }

    monkeypatch.setattr(
        "runtime.execution.subagents.call_subagent",
        fake_call_subagent,
    )

    response = _client().post(
        "/api/subagents/dispatch",
        json={
            "subagent_type": "researcher",
            "prompt": "check",
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "run_id": "run-1",
            "trace_id": "trace-1",
            "parent_task_id": "task-parent",
            "source": "router-test",
        },
    )

    assert response.status_code == 200
    ctx = calls[0]["kwargs"]["context"]
    assert ctx["thread_id"] == "thread-1"
    assert ctx["turn_id"] == "turn-1"
    assert ctx["run_id"] == "run-1"
    assert ctx["trace_id"] == "trace-1"
    assert ctx["parent_task_id"] == "task-parent"
    assert ctx["source"] == "router-test"


def test_stream_dispatch_uses_bounded_wall_clock_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_call_subagent(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append({"args": args, "kwargs": kwargs})
        event_emitter = kwargs.get("event_emitter")
        if event_emitter:
            event_emitter({"type": "sub_text_delta", "delta": "hi"})
        return {
            "agent_id": args[0],
            "output": "ok",
            "success": True,
            "error": None,
        }

    monkeypatch.setattr(
        "runtime.execution.subagents.call_subagent",
        fake_call_subagent,
    )

    with _client().stream(
        "POST",
        "/api/subagents/dispatch/stream",
        json={
            "subagent_type": "researcher",
            "prompt": "check",
            "timeout_s": 1800,
        },
    ) as response:
        body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert calls[0]["kwargs"]["timeout_s"] == 900
    assert calls[0]["kwargs"]["timeout_seconds"] == 900.0
    events = [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    assert events[-1]["type"] == "done"
    assert any(event.get("type") == "result" for event in events)


def test_stream_dispatch_preserves_trace_context_in_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_call_subagent(*args: Any, **kwargs: Any) -> dict[str, Any]:
        event_emitter = kwargs.get("event_emitter")
        ctx = kwargs["context"]
        if event_emitter:
            event_emitter(
                {
                    "type": "sub_text_delta",
                    "delta": "hi",
                    "trace": {
                        "thread_id": ctx["thread_id"],
                        "turn_id": ctx["turn_id"],
                    },
                    "thread_id": ctx["thread_id"],
                    "turn_id": ctx["turn_id"],
                }
            )
        return {
            "agent_id": args[0],
            "output": "ok",
            "success": True,
            "error": None,
            "trace": {
                "thread_id": ctx["thread_id"],
                "turn_id": ctx["turn_id"],
            },
        }

    monkeypatch.setattr(
        "runtime.execution.subagents.call_subagent",
        fake_call_subagent,
    )

    with _client().stream(
        "POST",
        "/api/subagents/dispatch/stream",
        json={
            "subagent_type": "researcher",
            "prompt": "check",
            "thread_id": "thread-1",
            "turn_id": "turn-1",
        },
    ) as response:
        body = response.read().decode("utf-8")

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    assert events[0]["trace"] == {"thread_id": "thread-1", "turn_id": "turn-1"}
    result = next(event for event in events if event.get("type") == "result")
    assert result["trace"] == {"thread_id": "thread-1", "turn_id": "turn-1"}

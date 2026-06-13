"""Smoke tests for the Anthropic Managed Agents compatibility layer."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from runtime.sensing.gateway.anthropic_compat import create_anthropic_compat_router  # noqa: E402

_BETA = {"anthropic-beta": "managed-agents-2026-04-01"}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    # ``stack`` may be None for the auth/session-management surface;
    # turn execution is exercised through smoke tests that wire a real
    # stack in fixtures (out of scope for the unit suite).
    app.include_router(create_anthropic_compat_router(stack=None))
    return TestClient(app)


def test_missing_beta_header_rejected(client: TestClient) -> None:
    r = client.post("/v1/sessions", json={"title": "x"})
    assert r.status_code == 400
    assert "managed-agents-2026-04-01" in r.json()["detail"]


def test_create_session_returns_id_and_idle(client: TestClient) -> None:
    r = client.post("/v1/sessions", json={"title": "hello"}, headers=_BETA)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"].startswith("sesn_")
    assert data["status"] == "idle"
    assert data["title"] == "hello"
    assert data["usage"]["input_tokens"] == 0


def test_get_session_404_when_unknown(client: TestClient) -> None:
    r = client.get("/v1/sessions/sesn_nope", headers=_BETA)
    assert r.status_code == 404


def test_list_events_empty_for_new_session(client: TestClient) -> None:
    r = client.post("/v1/sessions", json={}, headers=_BETA)
    sid = r.json()["id"]
    events = client.get(f"/v1/sessions/{sid}/events", headers=_BETA)
    assert events.status_code == 200
    assert events.json() == []


def test_event_adapter_maps_text_delta() -> None:
    from runtime.sensing.gateway.anthropic_compat.event_adapter import adapt_react_event

    out = adapt_react_event({"kind": "text_delta", "delta": "hello"})
    assert len(out) == 1
    assert out[0].type == "agent.message"
    assert out[0].content == [{"type": "text", "text": "hello"}]


def test_event_adapter_maps_tool_start_and_end() -> None:
    from runtime.sensing.gateway.anthropic_compat.event_adapter import adapt_react_event

    start = adapt_react_event({
        "kind": "tool_start",
        "tool_name": "exec_shell",
        "tool_call_id": "tc_1",
        "input_preview": {"command": "ls"},
    })
    assert len(start) == 1
    assert start[0].type == "agent.tool_use"
    assert start[0].tool_name == "exec_shell"
    assert start[0].tool_use_id == "tc_1"

    end = adapt_react_event({
        "kind": "tool_end",
        "tool_call_id": "tc_1",
        "status": "success",
        "output_preview": "file1.txt\n",
    })
    assert len(end) == 1
    assert end[0].type == "agent.tool_result"
    assert end[0].tool_use_id == "tc_1"


def test_event_adapter_approval_emits_requires_action() -> None:
    from runtime.sensing.gateway.anthropic_compat.event_adapter import adapt_react_event

    out = adapt_react_event({
        "kind": "tool_approval_request",
        "tool_name": "delete_file",
        "tool_call_id": "tc_2",
        "args_preview": "path=/etc/passwd",
    })
    # custom_tool_use + session.status_idle with requires_action
    assert len(out) == 2
    assert out[0].type == "agent.custom_tool_use"
    assert out[1].type == "session.status_idle"
    assert out[1].stop_reason.type == "requires_action"
    assert out[0].id in out[1].stop_reason.event_ids


# ═══════════════════════════════════════════════════════════
# _SseEmitter — streaming / interrupt / approval (wired, was stubbed)
# ═══════════════════════════════════════════════════════════


def test_adapt_notify_maps_text_and_reasoning_deltas() -> None:
    from runtime.sensing.gateway.anthropic_compat.router import _adapt_notify

    msg = _adapt_notify("item/agentMessage/delta", {"delta": "tok"})
    assert len(msg) == 1 and msg[0].type == "agent.message"
    assert msg[0].content == [{"type": "text", "text": "tok"}]

    think = _adapt_notify("item/reasoning/textDelta", {"delta": "hmm"})
    assert len(think) == 1 and think[0].type == "agent.thinking"
    assert think[0].content == [{"type": "thinking", "thinking": "hmm"}]

    # empty delta and unmapped (item-level) methods produce nothing in v1.
    assert _adapt_notify("item/agentMessage/delta", {"delta": ""}) == []
    assert _adapt_notify("item/completed", {"item": {}}) == []


def test_turn_completed_event_honours_interrupted_flag() -> None:
    from runtime.sensing.gateway.anthropic_compat.event_adapter import (
        turn_completed_event,
    )

    assert turn_completed_event().stop_reason.type == "end_turn"
    assert turn_completed_event(interrupted=True).stop_reason.type == "interrupted"


def test_sse_emitter_interrupt_registry() -> None:
    from runtime.sensing.gateway.anthropic_compat.router import _SseEmitter

    em = _SseEmitter(None, "sesn_x")
    em.register_turn("turn_1")
    assert em.is_turn_interrupted("turn_1") is False
    assert em.interrupted is False

    em.request_interrupt()  # "*" — interrupt whatever is in flight
    assert em.is_turn_interrupted("turn_1") is True
    assert em.is_turn_interrupted("any_other") is True
    assert em.interrupted is True


def test_sse_emitter_interrupt_survives_late_register() -> None:
    # A client interrupt that races ahead of the turn's register_turn() must
    # NOT be cleared (register_turn only discards the specific turn id).
    from runtime.sensing.gateway.anthropic_compat.router import _SseEmitter

    em = _SseEmitter(None, "sesn_x")
    em.request_interrupt()         # "*" arrives first
    em.register_turn("turn_2")     # turn registers afterwards
    assert em.is_turn_interrupted("turn_2") is True


def test_sse_emitter_notify_publishes_delta_to_subscribers() -> None:
    import asyncio

    from runtime.sensing.gateway.anthropic_compat.router import _SseEmitter
    from runtime.sensing.gateway.anthropic_compat.session_manager import (
        SessionManager,
    )

    async def _run():
        mgr = SessionManager()
        state = await mgr.create(title="t")
        q = await mgr.subscribe(state.session_id)
        em = _SseEmitter(mgr, state.session_id)
        await em.notify("item/agentMessage/delta", {"delta": "hi"})
        return q.get_nowait()

    evt = asyncio.run(_run())
    assert evt.type == "agent.message"
    assert evt.content == [{"type": "text", "text": "hi"}]


def test_sse_emitter_approval_resolves_allow_and_deny() -> None:
    import asyncio

    from runtime.sensing.gateway.anthropic_compat.router import _SseEmitter
    from runtime.sensing.gateway.anthropic_compat.session_manager import (
        SessionManager,
    )

    async def _run(allow: bool):
        mgr = SessionManager()
        state = await mgr.create(title="t")
        em = _SseEmitter(mgr, state.session_id)
        task = asyncio.create_task(em.request_approval(
            "req", {"itemId": "tc_1", "tool": "exec_shell"}, timeout=5.0,
        ))
        await asyncio.sleep(0.02)  # let request_approval register the future
        resolved = em.resolve_approval("tc_1", allow=allow)
        return resolved, await task

    resolved, result = asyncio.run(_run(True))
    assert resolved is True
    assert result == {"action": "accept"}

    resolved, result = asyncio.run(_run(False))
    assert resolved is True
    assert result == {"action": "decline"}


def test_sse_emitter_approval_fails_closed_on_timeout() -> None:
    import asyncio

    from runtime.sensing.gateway.anthropic_compat.router import _SseEmitter
    from runtime.sensing.gateway.anthropic_compat.session_manager import (
        SessionManager,
    )

    async def _run():
        mgr = SessionManager()
        state = await mgr.create(title="t")
        em = _SseEmitter(mgr, state.session_id)
        # No confirmation arrives → must DENY (old stub auto-accepted).
        return await em.request_approval(
            "req", {"itemId": "tc_x", "tool": "rm"}, timeout=0.05,
        )

    assert asyncio.run(_run()) == {"action": "decline"}

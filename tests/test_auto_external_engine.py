"""API Auto requests share the local host's external engine default."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.execution.engines import EngineId, select_execution_route
from runtime.memory.threads.event_log import EventLog
from runtime.platform.config.schema import AgentConfig
from runtime.platform.models.custom_model_selection import custom_model_selection_id
from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
from runtime.sensing.gateway.realtime_gateway import RealtimeGateway
from tests.test_realtime_cerebrum import _drive


@pytest.mark.parametrize("ready", [True, False])
@pytest.mark.parametrize("text", ["你好，介绍一下你能做什么", "Write a Python sorting function"])
def test_api_auto_uses_opencode_and_never_native_fallback(tmp_path, monkeypatch, ready, text):
    runtime = CerebrumRuntime(
        stack=SimpleNamespace(config=AgentConfig()),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
    )
    native = AsyncMock(side_effect=AssertionError("native execution"))
    codex = AsyncMock(side_effect=AssertionError("implicit coding-engine switch"))
    monkeypatch.setattr(runtime, "_drive_react", native)
    monkeypatch.setattr(runtime, "_drive_codex_app_server", codex)
    monkeypatch.setattr(
        "runtime.execution.opencode_backend.inspect_readiness",
        lambda scope: {"available": ready, "reason": "fixture unavailable"},
    )
    monkeypatch.setattr(
        "runtime.execution.opencode_backend.zen_catalog",
        lambda: {"opencode-zen": {"managed_by_plugin": "opencode-zen", "models": ["big-pickle"]}},
    )
    monkeypatch.setattr(
        "runtime.core.cerebrum.turn_complexity.select_model_for_complexity",
        lambda *args, **kwargs: ("native/wrong-model", "fixture-route"),
    )
    calls = []

    async def stream(*args, **kwargs):
        calls.append(kwargs)
        yield {"type": "text_delta", "delta": "回答完成。"}
        yield {"type": "react_completed", "success": True}

    monkeypatch.setattr("runtime.sensing.gateway.realtime_opencode_backend.stream_role", stream)
    app = FastAPI()
    app.include_router(RealtimeGateway(runtime=runtime, approval_timeout=5.0).router)
    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        turn = _drive(
            ws,
            {
                "threadId": "auto-api",
                "model": "auto",
                "executionEngine": "auto",
                "input": [{"type": "text", "text": text}],
                "approvalPolicy": "never",
            },
        )["response"].result["turn"]
    native.assert_not_called()
    codex.assert_not_called()
    if ready:
        assert turn["status"] == "completed", turn
        assert len(calls) == 1
        assert calls[0]["model"] == "big-pickle"
        restored = EventLog(runtime._log_for("auto-api").path).replay()[-1]
        assert restored.execution.engine == "opencode"
        assert restored.params.model == custom_model_selection_id("opencode-zen", "big-pickle")
    else:
        assert not calls
        assert turn["status"] != "completed"


@pytest.mark.parametrize("requested", [EngineId.OCTOPUS, EngineId.CODEX, EngineId.OPENCODE])
def test_explicit_engine_wins_over_host_default(requested):
    assert (
        select_execution_route(default_engine=EngineId.OPENCODE, requested_engine=requested).engine
        == requested
    )


def test_codex_role_wins_over_host_default():
    assert (
        select_execution_route(default_engine=EngineId.OPENCODE, codex_partner=True).engine
        == EngineId.CODEX
    )


@pytest.mark.parametrize("signals", [{"coding_task": True}, {"reflection_fast_path": True}, {}])
def test_host_default_precedes_implicit_model_heuristics(signals):
    route = select_execution_route(default_engine=EngineId.OPENCODE, **signals)
    assert route.engine is EngineId.OPENCODE
    assert route.reason == "host_default"

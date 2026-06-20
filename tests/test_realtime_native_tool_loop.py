from __future__ import annotations

from types import SimpleNamespace

from runtime.platform.models import ParsedIntent
from runtime.protocol import Turn, TurnParams
from runtime.sensing.gateway.realtime_cerebrum import (
    _agentic_stream_event_to_react_event,
    _should_default_planning_mode,
    _should_use_native_tool_loop,
)
from runtime.sensing.gateway.realtime_turn_outcome import _record_react_trace_event


def _intent(goal: str, mode: str) -> ParsedIntent:
    return ParsedIntent(
        raw=goal,
        intent_type="task",
        normalized_goal=goal,
        user_context={"mode": mode},
    )


def test_agentic_tool_start_event_maps_to_react_shape():
    evt = _agentic_stream_event_to_react_event(
        "tool_start",
        {
            "id": "call_1",
            "name": "read_file",
            "input": {"path": "README.md"},
            "iteration": 2,
        },
        None,
    )

    assert evt == {
        "type": "tool_start",
        "tool_call_id": "call_1",
        "tool_name": "read_file",
        "input_preview": {"path": "README.md"},
        "iteration": 2,
    }


def test_agentic_tool_error_maps_to_failed_tool_end():
    evt = _agentic_stream_event_to_react_event(
        "tool_end",
        {
            "id": "call_1",
            "name": "read_file",
            "output": "not found",
            "is_error": True,
            "iteration": 1,
        },
        None,
    )

    assert evt == {
        "type": "tool_end",
        "tool_call_id": "call_1",
        "tool_name": "read_file",
        "status": "error",
        "output_preview": "not found",
        "iteration": 1,
    }


def test_react_tool_event_records_normalized_trace_payload():
    recorded: list[dict] = []

    class _TraceStore:
        def record_event(self, **kwargs):
            recorded.append(kwargs)

    runtime = SimpleNamespace(_trace_store=_TraceStore())
    turn = Turn(
        id="turn-1",
        threadId="thread-1",
        params=TurnParams(
            threadId="thread-1",
            input=[{"role": "user", "content": "read"}],
        ),
    )

    _record_react_trace_event(
        runtime,
        turn,
        {
            "type": "tool_end",
            "tool_call_id": "call_1",
            "tool_name": "read_file",
            "status": "error",
            "output_preview": "not found",
            "iteration": 1,
        },
    )

    assert len(recorded) == 1
    assert recorded[0]["event_type"] == "TOOL_CALL_END"
    assert recorded[0]["item_id"] == "call_1"
    assert recorded[0]["payload"] == {
        "id": "call_1",
        "name": "read_file",
        "tool_call_id": "call_1",
        "tool": "read_file",
        "origin": "react_compat",
        "iteration": 1,
        "status": "error",
        "is_error": True,
        "output": "not found",
        "output_preview": "not found",
        "event_kind": "tool_end",
    }


def test_native_tool_loop_enabled_for_tool_capable_router():
    router = SimpleNamespace(
        capabilities=SimpleNamespace(supports_tool_use=True),
        call_stream=lambda _request: iter(()),
    )
    stack = SimpleNamespace(
        executor=object(),
        planner=SimpleNamespace(router=router),
    )
    intent = _intent("改代码", "react")

    assert _should_use_native_tool_loop(stack, intent, planning_mode=False)


def test_native_tool_loop_disabled_for_chat_and_planning():
    router = SimpleNamespace(
        capabilities=SimpleNamespace(supports_tool_use=True),
        call_stream=lambda _request: iter(()),
    )
    stack = SimpleNamespace(
        executor=object(),
        planner=SimpleNamespace(router=router),
    )

    chat = _intent("聊聊", "chat")
    react = _intent("先给方案", "react")

    assert not _should_use_native_tool_loop(stack, chat, planning_mode=False)
    assert not _should_use_native_tool_loop(stack, react, planning_mode=True)


def test_complex_turn_defaults_to_planning_mode_when_not_explicit():
    from runtime.protocol.items import TurnParams

    params = TurnParams(
        threadId="t1",
        input=[{"type": "input_text", "text": "请完整实现这个功能并测试"}],
    )

    assert _should_default_planning_mode("请完整实现这个功能并测试", params)


def test_explicit_planning_false_and_chat_mode_do_not_default():
    from runtime.protocol.items import TurnParams

    explicit = TurnParams.model_validate({
        "threadId": "t1",
        "input": [{"type": "input_text", "text": "请完整实现这个功能并测试"}],
        "planningMode": False,
    })
    chat = TurnParams(
        threadId="t1",
        input=[{
            "type": "input_text",
            "text": "请完整实现这个功能并测试",
            "metadata": {"context": {"mode": "chat"}},
        }],
    )

    assert not _should_default_planning_mode("请完整实现这个功能并测试", explicit)
    assert not _should_default_planning_mode("请完整实现这个功能并测试", chat)


def test_agentic_session_metadata_preserves_code_permission_context():
    from runtime.sensing.gateway.tool_bridge import _session_metadata_from_intent

    intent = ParsedIntent(
        raw="fix it",
        intent_type="task",
        normalized_goal="fix it",
        user_context={
            "mode": "code",
            "workspace_path": "/tmp/project",
            "sandbox_mode": "sandbox",
            "permission_mode": "bypassPermissions",
            "approval_policy": "never",
            "execution_environment": "local",
            "capability_mode": "code",
            "code_mode": "solo",
            "agent_mode": "architect",
            "project_signals": {"recommended_mode": "architect"},
        },
    )

    metadata = _session_metadata_from_intent(intent)

    assert metadata["workspace_path"] == "/tmp/project"
    assert metadata["extra_workspaces"] == ["/tmp/project"]
    assert metadata["sandbox_mode"] == "sandbox"
    assert metadata["permission_mode"] == "bypassPermissions"
    assert metadata["approval_policy"] == "never"
    assert metadata["execution_environment"] == "local"
    assert metadata["capability_mode"] == "code"
    assert metadata["code_mode"] == "solo"
    assert metadata["agent_mode"] == "architect"
    assert metadata["project_signals"] == {"recommended_mode": "architect"}

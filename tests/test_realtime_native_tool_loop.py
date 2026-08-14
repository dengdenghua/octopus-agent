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


def test_agentic_commentary_maps_to_public_timeline_event():
    evt = _agentic_stream_event_to_react_event(
        "commentary",
        "已确认第一批资料，现在继续核对官方文档。",
        None,
    )

    assert evt == {
        "type": "commentary_delta",
        "delta": "已确认第一批资料，现在继续核对官方文档。",
        "progress_source": "model",
    }


def test_agentic_runtime_commentary_stays_non_public():
    evt = _agentic_stream_event_to_react_event(
        "commentary_runtime",
        "Evidence collection budget reached.",
        None,
    )

    assert evt == {
        "type": "commentary_delta",
        "delta": "Evidence collection budget reached.",
        "progress_source": "runtime",
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


def test_agentic_redirected_tool_maps_to_cancelled_tool_end():
    evt = _agentic_stream_event_to_react_event(
        "tool_end",
        {
            "id": "call_redirected",
            "name": "exec_shell",
            "output": "cancelled",
            "is_error": True,
            "status": "cancelled",
            "iteration": 2,
        },
        None,
    )

    assert evt == {
        "type": "tool_end",
        "tool_call_id": "call_redirected",
        "tool_name": "exec_shell",
        "status": "cancelled",
        "output_preview": "cancelled",
        "iteration": 2,
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


def test_native_tool_loop_disabled_for_chat_but_not_plan_first_execution():
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
    assert _should_use_native_tool_loop(stack, react, planning_mode=True)


def test_browser_surface_marker_promotes_chat_turn_to_tool_mode():
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    params = TurnParams(
        threadId="thread-browser",
        input=[
            {
                "type": "input_text",
                "text": "@Browser inspect the current page",
                "metadata": {"context": {"mode": "chat"}},
            },
        ],
    )

    intent = _build_intent("@Browser inspect the current page", params)
    context = intent.user_context or {}

    assert context["mode"] == "browser"
    assert context["capability_mode"] == "browser"
    assert context["browser_operation_mode"] is True
    assert context["browser_session_policy"] == "thread_native"
    assert context["native_tool_loop"] is True
    assert context["realtime_public_narrative"] is True
    assert context["realtime_public_orientation"] is True
    assert context["realtime_public_preface"] is True


def test_chrome_surface_marker_promotes_chat_turn_to_external_chrome_mode():
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    params = TurnParams(
        threadId="thread-chrome",
        input=[
            {
                "type": "input_text",
                "text": "@Chrome inspect the current signed-in tab",
                "metadata": {"context": {"mode": "chat"}},
            },
        ],
    )

    intent = _build_intent("@Chrome inspect the current signed-in tab", params)
    context = intent.user_context or {}

    assert context["mode"] == "chrome"
    assert context["capability_mode"] == "browser"
    assert context["browser_operation_mode"] is True
    assert context["chrome_operation_mode"] is True
    assert context["browser_surface"] == "chrome"
    assert context["browser_session_policy"] == "thread_native_external_chrome"
    assert context["browser_track_preference"] == "extension"
    assert context["native_tool_loop"] is True


def test_complex_turn_defaults_to_planning_mode_when_not_explicit():
    from runtime.protocol.items import TurnParams

    params = TurnParams(
        threadId="t1",
        input=[{"type": "input_text", "text": "请完整实现这个功能并测试"}],
    )

    assert _should_default_planning_mode("请完整实现这个功能并测试", params)


def test_explicit_planning_false_and_chat_mode_do_not_default():
    from runtime.protocol.items import TurnParams

    explicit = TurnParams.model_validate(
        {
            "threadId": "t1",
            "input": [{"type": "input_text", "text": "请完整实现这个功能并测试"}],
            "planningMode": False,
        }
    )
    chat = TurnParams(
        threadId="t1",
        input=[
            {
                "type": "input_text",
                "text": "请完整实现这个功能并测试",
                "metadata": {"context": {"mode": "chat"}},
            }
        ],
    )

    assert not _should_default_planning_mode("请完整实现这个功能并测试", explicit)
    assert not _should_default_planning_mode("请完整实现这个功能并测试", chat)


def test_code_mode_implementation_is_execution_first():
    from runtime.protocol.items import TurnParams

    params = TurnParams(
        threadId="t-code-execute",
        input=[
            {
                "type": "input_text",
                "text": "请完整实现这个功能并测试",
                "metadata": {
                    "context": {
                        "mode": "code",
                        "workspace_path": "/tmp/project",
                    },
                },
            },
        ],
    )

    assert not _should_default_planning_mode("请完整实现这个功能并测试", params)


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
            "allowed_write_paths": ["cache.py", "tests/test_cache.py"],
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
    assert metadata["allowed_write_paths"] == ["cache.py", "tests/test_cache.py"]
    assert metadata["project_signals"] == {"recommended_mode": "architect"}


def test_agentic_session_metadata_preserves_browser_surface_context():
    from runtime.sensing.gateway.tool_bridge import (
        _browser_operation_guidance,
        _session_metadata_from_intent,
    )

    intent = ParsedIntent(
        raw="@Browser check page",
        intent_type="task",
        normalized_goal="@Browser check page",
        user_context={
            "mode": "browser",
            "capability_mode": "browser",
            "runtime_surfaces": ["browser"],
            "tool_surface": "browser",
            "browser_operation_mode": True,
            "browser_surface": "browser",
            "browser_session_policy": "thread_native",
            "browser_evidence_policy": ("state_first_screenshot_only_for_visual_evidence"),
        },
    )

    metadata = _session_metadata_from_intent(intent)
    guidance = _browser_operation_guidance(intent.user_context or {})

    assert metadata["mode"] == "browser"
    assert metadata["runtime_surfaces"] == ["browser"]
    assert metadata["browser_operation_mode"] is True
    assert metadata["browser_session_policy"] == "thread_native"
    assert "thread-native browser operation" in guidance
    assert "live_browser_state" in guidance


def test_explicit_browser_surface_registers_local_browser_tools(monkeypatch) -> None:
    from runtime.execution.suckers import Skill, SkillRegistry
    from runtime.sensing.gateway.tool_bridge import _ensure_explicit_browser_skills

    registry = SkillRegistry()
    calls: list[SkillRegistry] = []

    def register(target: SkillRegistry, *, verify_tests: bool = True) -> int:
        assert verify_tests is False
        calls.append(target)
        target.register(
            Skill(
                name="browser_navigate",
                trusted_source="skill://test/browser_navigate",
                handler=lambda **_kw: {},
            ),
            verify_tests=False,
        )
        return 1

    monkeypatch.setattr(
        "runtime.execution.suckers.browser_skills.register_browser_skills",
        register,
    )

    context = {"browser_surface": "browser", "browser_operation_mode": True}
    assert _ensure_explicit_browser_skills(registry, context) == 1
    assert _ensure_explicit_browser_skills(registry, context) == 0
    assert calls == [registry]


def test_browser_mutation_evidence_tracks_required_ui_actions() -> None:
    from runtime.sensing.gateway.tool_bridge import (
        _browser_action_evidence,
        _required_browser_action_evidence,
    )

    required = _required_browser_action_evidence(
        "create a customer, edit it, verify it, and delete it"
    )
    assert required == {"type", "click", "verify", "delete"}
    assert _browser_action_evidence(
        SimpleNamespace(name="browser_type", input={"selector": "#name"})
    ) == {"type"}
    assert _browser_action_evidence(
        SimpleNamespace(name="browser_click", input={"selector": "[data-verify]"})
    ) == {"click", "verify"}
    assert _browser_action_evidence(
        SimpleNamespace(name="browser_click", input={"selector": "[data-delete]"})
    ) == {"click", "delete"}


def test_agentic_session_metadata_preserves_chrome_surface_context():
    from runtime.sensing.gateway.tool_bridge import (
        _browser_operation_guidance,
        _session_metadata_from_intent,
    )

    intent = ParsedIntent(
        raw="@Chrome check page",
        intent_type="task",
        normalized_goal="@Chrome check page",
        user_context={
            "mode": "chrome",
            "capability_mode": "browser",
            "runtime_surfaces": ["chrome"],
            "tool_surface": "chrome",
            "browser_operation_mode": True,
            "chrome_operation_mode": True,
            "browser_surface": "chrome",
            "browser_session_policy": "thread_native_external_chrome",
            "browser_track_preference": "extension",
            "browser_permission_policy": "site_policy_required",
            "browser_evidence_policy": ("state_first_screenshot_only_for_visual_evidence"),
        },
    )

    metadata = _session_metadata_from_intent(intent)
    guidance = _browser_operation_guidance(intent.user_context or {})

    assert metadata["mode"] == "chrome"
    assert metadata["runtime_surfaces"] == ["chrome"]
    assert metadata["chrome_operation_mode"] is True
    assert metadata["browser_surface"] == "chrome"
    assert metadata["browser_track_preference"] == "extension"
    assert "thread-native external Chrome operation" in guidance
    assert "browser_state" in guidance


def test_agentic_tool_call_delta_maps_to_react_shape():
    evt = _agentic_stream_event_to_react_event(
        "tool-call-delta",
        {
            "index": 0,
            "id": "call_1",
            "name": "read_file",
            "argumentsDelta": '{"path":',
        },
        None,
    )

    assert evt == {
        "type": "tool_call_delta",
        "tool_call_id": "call_1",
        "tool_name": "read_file",
        "index": 0,
        "argumentsDelta": '{"path":',
    }


def test_agentic_tool_call_delta_ignores_non_dict_payload():
    assert _agentic_stream_event_to_react_event("tool-call-delta", "oops", None) is None

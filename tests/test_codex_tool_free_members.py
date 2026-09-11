"""Codex group replies keep their engine and cannot expose execution tools."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.execution.codex_backend import role_runner
from runtime.execution.parallel_agents.stack_runner import make_stack_subagent_runner


@pytest.mark.parametrize("enabled", [False, True])
def test_codex_group_reply_never_loads_native_planner(monkeypatch, enabled):
    class Host:
        @property
        def planner(self):
            raise AssertionError("group reply accessed native planner")

    agent = SimpleNamespace(
        agent_id="coder",
        soul="Coder",
        model="auto",
        capabilities={"execution_backend": "codex_app_server"},
    )
    registry = SimpleNamespace(has=lambda name: True, get=lambda name: agent)
    run = Mock(return_value=role_runner.CodexRoleExecution("Codex reply", True, "completed"))
    monkeypatch.setattr(role_runner, "run_agent_role_sync", run)
    monkeypatch.setattr(role_runner, "agent_uses_codex_execution_backend", lambda agent: enabled)
    runner = make_stack_subagent_runner(Host(), agent_registry=registry)
    if enabled:
        assert (
            runner("hello", subagent_name="coder", context={"direct_conversation_reply": True})
            == "Codex reply"
        )
        assert run.call_args.kwargs["context"]["direct_conversation_reply"] is True
        run.return_value = role_runner.CodexRoleExecution("", True, "completed")
        with pytest.raises(RuntimeError, match="empty reply"):
            runner("hello", subagent_name="coder", context={"direct_conversation_reply": True})
    else:
        with pytest.raises(RuntimeError, match="disabled"):
            runner("hello", subagent_name="coder", context={"direct_conversation_reply": True})
        run.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("resumed", [False, True])
async def test_tool_free_reasserts_no_environments_on_thread_and_turn(tmp_path, resumed):
    from tests.test_codex_execution_backend import _binding, _make_session

    session, security, context, _, client = _make_session(
        tmp_path, binding=_binding() if resumed else None
    )
    session.request = replace(session.request, tool_free=True)
    await session.start()
    assert security.prepare_kwargs["realm_id"] == session.request.realm_id + "/codex-tool-free-v1"
    assert security.prepare_kwargs["thread_id"] == session.request.outer_thread_id
    if resumed:
        params = next(value for name, value in client.calls if name == "thread/resume")[1][
            "extra_params"
        ]
    else:
        params = next(value for name, value in client.calls if name == "thread/start")[
            "extra_params"
        ]
    assert params["dynamicTools"] == []
    assert params["selectedCapabilityRoots"] == []
    assert params["environments"] == []
    turn = next(value for name, value in client.calls if name == "turn/start")
    assert turn[2]["extra_params"]["environments"] == []
    await session.close()
    assert context.cleaned and client.closed


@pytest.mark.parametrize(
    "extra",
    [
        {"tool_free": "yes"},
        {"tool_free": True, "selected_app_ids": ("drive",)},
        {"tool_free": True, "dynamic_tool_handler": lambda event: None},
    ],
)
def test_request_rejects_tool_free_capability_conflicts(tmp_path, extra):
    from tests.test_codex_execution_backend import _make_session

    session, *_ = _make_session(tmp_path)
    with pytest.raises(ValueError):
        replace(session.request, **extra)


def test_tool_free_account_request_needs_no_native_router_or_broker(tmp_path, monkeypatch):
    from runtime.execution.codex_backend.model_profile import CodexModelPreference

    class Host:
        executor = SimpleNamespace(registry=object())

        @property
        def planner(self):
            raise AssertionError("account reply accessed native planner")

        @property
        def approval_router(self):
            raise AssertionError("tool-free reply accessed review model")

    monkeypatch.setattr(role_runner, "require_codex_backend_enabled", lambda: None)
    monkeypatch.setattr(role_runner, "deployment_mode", lambda: "local")
    monkeypatch.setattr(
        role_runner, "state_root_for_workspace", lambda workspace: tmp_path / "state"
    )
    monkeypatch.setattr(
        role_runner, "codex_app_server_command", lambda agent: ("codex", "app-server")
    )
    monkeypatch.setattr(role_runner, "resolve_codex_execution_auth_home", lambda **kwargs: None)
    monkeypatch.setattr(
        role_runner.CodexModelPreferenceStore,
        "read",
        lambda self, scope: CodexModelPreference(mode="chatgpt", app_ids=("drive",)),
    )
    monkeypatch.setattr(
        role_runner, "compose_codex_role_instructions", lambda *args, **kwargs: "Role"
    )
    monkeypatch.setattr(
        role_runner,
        "CodexDynamicToolBroker",
        Mock(side_effect=AssertionError("tool-free role constructed broker")),
    )
    request, broker, provider = role_runner.build_codex_role_request(
        Host(),
        SimpleNamespace(agent_id="coder", capabilities={}),
        "reply",
        context={
            "workspace_path": str(tmp_path),
            "direct_conversation_reply": True,
            "permission_mode": "acceptEdits",
        },
    )
    assert request.tool_free and request.sandbox_mode == "read-only"
    assert request.dynamic_tools == () and request.selected_app_ids == ()
    assert broker is None and request.dynamic_tool_handler is None
    assert request.approval_reviewer == "user"

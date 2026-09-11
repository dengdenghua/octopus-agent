from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.execution.auxiliary_models import AuxiliaryModelRouter
from runtime.execution.request import current_execution_request, execution_request_scope
from runtime.platform.llm_infra.llm_caller import LLMCaller
from runtime.platform.models.llm import Message, ModelRequest
from runtime.platform.process.service_provider import ServiceProvider
from runtime.platform.process.session import session_scope
from tests.test_external_graph_planning import setup_host


@pytest.mark.parametrize("engine", ["opencode", "codex"])
@pytest.mark.parametrize("failed", [False, True])
def test_foreground_helper_uses_bound_engine_and_never_native(
    tmp_path, monkeypatch, engine, failed
):
    stack, request, session = setup_host(tmp_path, engine)
    session.metadata["model_name"] = "big-pickle" if engine == "opencode" else "gpt-5.4"
    native = Mock(side_effect=AssertionError("native model used by external helper"))
    router = AuxiliaryModelRouter(stack, SimpleNamespace(call=native))
    services = ServiceProvider()
    services.register_instance("helper", router)
    services.register_instance("helper_model", "claude-native-hint")
    monkeypatch.setattr("runtime.platform.llm_infra.llm_caller.get_provider", lambda: services)

    def run(*args, **kwargs):
        assert args[1].soul == "Return JSON"
        assert kwargs["context"]["direct_conversation_reply"] is True
        assert kwargs["context"]["model_name"] == session.metadata["model_name"]
        if failed:
            raise RuntimeError("external helper failed")
        if engine == "opencode":
            assert kwargs["tool_ceiling"] == frozenset()
            kwargs["on_event"](
                {
                    "type": "react_completed",
                    "completion_receipt": {
                        "model": "big-pickle",
                        "tokens": {"input": 4, "output": 3, "cache": {"read": 6}},
                    },
                }
            )
            return '{"ok": true}'
        child = current_execution_request().task
        assert child.parent_task_id == request.task.task_id
        assert child.permissions is request.task.permissions
        assert child.resources is request.task.resources
        return SimpleNamespace(output='{"ok": true}', success=True, model="gpt-5.4")

    target = (
        "runtime.execution.opencode_roles.run_role_sync"
        if engine == "opencode"
        else "runtime.execution.codex_backend.role_runner.run_agent_role_sync"
    )
    monkeypatch.setattr(target, run)
    with session_scope(session), execution_request_scope(request):
        result, metadata = LLMCaller("helper", "helper_model").call_json(
            system="Return JSON", user="Check this"
        )
    native.assert_not_called()
    if failed:
        assert result is None
        assert "external helper failed" in metadata["error"]
    else:
        assert result == {"ok": True}
        assert metadata["model"] == session.metadata["model_name"]
        assert metadata["input_tokens"] == (10 if engine == "opencode" else None)


def test_helper_without_external_task_preserves_native_call():
    request = ModelRequest(model="mock/test", messages=[Message(role="user", content="Hello")])
    native = Mock(return_value=object())
    router = AuxiliaryModelRouter(None, SimpleNamespace(call=native))
    assert router.call(request) is native.return_value
    native.assert_called_once_with(request)

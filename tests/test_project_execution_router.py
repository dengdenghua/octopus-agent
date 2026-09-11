
from runtime.platform.models.llm import Message, ModelRequest
from runtime.projectos.execution_router import OpenCodePlanningRouter


def test_opencode_planning_preserves_model_and_disables_tools(monkeypatch):
    captured = {}
    stack, agent = object(), object()
    def stopped():
        return False

    def run(received_stack, received_agent, goal, **kwargs):
        captured.update(kwargs)
        assert received_stack is stack and received_agent is agent
        assert "Return JSON" in goal and "launch plan" in goal
        return '{"name":"launch"}'

    monkeypatch.setattr("runtime.execution.opencode_roles.run_role_sync", run)
    result = OpenCodePlanningRouter(stack, agent, stopped).call(ModelRequest(
        model="big-pickle", messages=[Message(role="system", content="Return JSON"),
                                    Message(role="user", content="launch plan")],
    ))
    assert result.text == '{"name":"launch"}'
    assert captured["context"]["model_name"] == "big-pickle"
    assert captured["tool_ceiling"] == frozenset()
    assert captured["interrupted"] is stopped

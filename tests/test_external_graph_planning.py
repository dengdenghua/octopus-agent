"""External graph planning uses the shared catalog without native inference."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.execution.graph_planning import plan_external_graph
from runtime.execution.request import execution_request_scope
from runtime.platform.process.session import session_scope
from tests.test_host_mcp import host


def setup_host(tmp_path, engine):
    bridge, _, _ = host(tmp_path)
    request = replace(bridge.request, task=replace(bridge.request.task, execution_engine=engine))
    session = replace(
        bridge.session, metadata={**bridge.session.metadata, "_execution_task": request.task}
    )
    base = bridge.broker._stack

    class Stack:
        executor = base.executor
        config = SimpleNamespace(planner=SimpleNamespace(max_nodes=3))

        @property
        def planner(self):
            raise AssertionError("external planning accessed native planner")

    return Stack(), request, session


@pytest.mark.parametrize("engine", ["opencode", "codex"])
def test_external_graph_uses_role_catalog_and_preserves_parallel_dependencies(
    tmp_path, monkeypatch, engine
):
    stack, request, session = setup_host(tmp_path, engine)
    output = json.dumps(
        {
            "nodes": [
                {"skill": "read_file", "args": {"path": "a.txt"}, "depends_on": []},
                {"skill": "read_file", "args": {"path": "b.txt"}, "depends_on": []},
                {
                    "skill": "write_text_file",
                    "args": {"content": {"nested": ["{n0.content}", "{n1.content}"]}},
                    "depends_on": [],
                },
            ]
        }
    )
    if engine == "opencode":
        runner = Mock(return_value=output)
        monkeypatch.setattr("runtime.execution.opencode_roles.run_role_sync", runner)
    else:
        from runtime.execution.codex_backend.role_runner import CodexRoleExecution

        runner = Mock(return_value=CodexRoleExecution(output, True, "completed"))
        monkeypatch.setattr(
            "runtime.execution.codex_backend.role_runner.run_agent_role_sync", runner
        )
    intent = SimpleNamespace(user_context={}, normalized_goal="inspect", raw="inspect")
    with session_scope(session), execution_request_scope(request):
        graph = plan_external_graph(stack, intent, engine=engine)
    assert graph.strategy == f"{engine}_planner"
    assert {(e.from_node, e.to_node) for e in graph.edges} == {("n0", "n2"), ("n1", "n2")}
    assert graph.budget.tokens == request.task.resources.token_target
    assert graph.budget.usd == request.task.resources.usd_target
    assert runner.call_args.kwargs["context"]["direct_conversation_reply"] is True
    if engine == "opencode":
        assert runner.call_args.kwargs["tool_ceiling"] == frozenset()
    assert "read_file" in runner.call_args.args[1].soul
    assert "exec_shell" not in runner.call_args.args[1].soul


@pytest.mark.parametrize(
    "nodes",
    [
        [],
        [{"skill": "exec_shell", "args": {}, "depends_on": []}],
        [{"skill": "read_file", "args": {}, "depends_on": ["n8"]}],
        [{"skill": "read_file", "args": {}, "depends_on": ["n0"]}],
        [{"skill": "read_file", "args": {}, "depends_on": [True]}],
        [{"skill": "read_file", "args": {}}],
        [{"skill": "read_file", "args": {"path": {"nested": "{n8.value}"}}, "depends_on": []}],
        [
            {"skill": "read_file", "args": {}, "depends_on": ["n1"]},
            {"skill": "read_file", "args": {}, "depends_on": ["n0"]},
        ],
    ],
)
def test_external_graph_rejects_unauthorized_tools_and_invalid_dependencies(
    tmp_path, monkeypatch, nodes
):
    from runtime.core.cerebrum.planner import PlannerError

    stack, request, session = setup_host(tmp_path, "opencode")
    monkeypatch.setattr(
        "runtime.execution.opencode_roles.run_role_sync",
        lambda *a, **kw: json.dumps({"nodes": nodes}),
    )
    intent = SimpleNamespace(user_context={}, normalized_goal="inspect", raw="inspect")
    with session_scope(session), execution_request_scope(request), pytest.raises(PlannerError):
        plan_external_graph(stack, intent, engine="opencode")


def test_external_graph_requires_bound_engine_before_model_access(tmp_path):
    stack, request, session = setup_host(tmp_path, "opencode")
    with (
        session_scope(session),
        execution_request_scope(request),
        pytest.raises(ValueError, match="switch"),
    ):
        plan_external_graph(stack, None, engine="codex")


@pytest.mark.parametrize("engine", ["opencode", "codex"])
def test_graph_records_reported_planning_tokens(tmp_path, monkeypatch, engine):
    from runtime.execution.codex_backend.role_runner import CodexRoleExecution

    stack, request, session = setup_host(tmp_path, engine)
    output = json.dumps({"nodes": [{"skill": "read_file", "args": {}, "depends_on": []}]})

    def run(*args, **kwargs):
        if engine == "opencode":
            kwargs["on_event"](
                {
                    "type": "react_completed",
                    "completion_receipt": {
                        "tokens": {
                            "input": 540,
                            "output": 173,
                            "cache": {"read": 1792, "write": 0},
                        },
                    },
                }
            )
            return output
        # Codex total is cumulative; repeated reports replace rather than add.
        for count in (1000, 2332):
            kwargs["event_callback"](
                {
                    "type": "throughput",
                    "usage": {
                        "total": {
                            "inputTokens": count,
                            "outputTokens": 173,
                            "cachedInputTokens": 1792,
                        },
                    },
                }
            )
        return CodexRoleExecution(output, True, "completed")

    target = (
        "runtime.execution.opencode_roles.run_role_sync"
        if engine == "opencode"
        else "runtime.execution.codex_backend.role_runner.run_agent_role_sync"
    )
    monkeypatch.setattr(target, run)
    intent = SimpleNamespace(user_context={}, normalized_goal="inspect", raw="inspect")
    with session_scope(session), execution_request_scope(request):
        graph = plan_external_graph(stack, intent, engine=engine)
    assert graph.planner_usage == {"input_tokens": 2332, "output_tokens": 173}


@pytest.mark.parametrize("engine", ["opencode", "codex"])
@pytest.mark.parametrize("valid", [True, False])
def test_mesh_driver_uses_external_planning_without_native_fallback(
    tmp_path, monkeypatch, engine, valid
):
    import asyncio

    from runtime.core.cerebrum.planner import PlannerError
    from runtime.sensing.gateway import realtime_team_stream as mod
    from tests.test_drive_swarm_mesh import _Emitter, _Log

    stack, request, session = setup_host(tmp_path, engine)
    stack.registry = stack.executor.registry
    stack.journal = stack.executor.journal
    output = (
        json.dumps(
            {"nodes": [{"skill": "read_file", "args": {"path": "note.txt"}, "depends_on": []}]}
        )
        if valid
        else "unusable response"
    )
    if engine == "opencode":
        monkeypatch.setattr(
            "runtime.execution.opencode_roles.run_role_sync", lambda *a, **kw: output
        )
    else:
        from runtime.execution.codex_backend.role_runner import CodexRoleExecution

        monkeypatch.setattr(
            "runtime.execution.codex_backend.role_runner.run_agent_role_sync",
            lambda *a, **kw: CodexRoleExecution(output, True, "completed"),
        )
    from runtime.execution.swarm.drive import run_swarm

    results = []

    def execute(*args, **kwargs):
        result = run_swarm(*args, **kwargs)
        results.append(result)
        return result

    run = Mock(side_effect=execute)
    monkeypatch.setattr("runtime.execution.swarm.drive.run_swarm", run)
    turn = SimpleNamespace(
        thread_id=request.task.thread_id,
        id=request.task.task_id,
        items=[],
        execution=SimpleNamespace(engine=engine),
        params=SimpleNamespace(
            owner_actor_id=request.task.actor_id, tenant_id=request.task.tenant_id
        ),
    )
    intent = SimpleNamespace(
        user_context={"serve_mesh": "1"}, normalized_goal="inspect", raw="inspect"
    )
    with session_scope(session), execution_request_scope(request):
        coro = mod._drive_swarm_mesh(
            SimpleNamespace(_stack=stack), turn, _Log(), _Emitter(), intent, text="inspect"
        )
        if valid:
            asyncio.run(coro)
        else:
            with pytest.raises(PlannerError):
                asyncio.run(coro)
    assert run.call_count == int(valid)
    if valid:
        assert run.call_args.args[0].strategy == f"{engine}_planner"
        assert results[0].all_successful, [arm.reason for arm in results[0].arm_results]
        assert any('"content": "before"' in item.text for item in turn.items)


@pytest.mark.parametrize("engine", ["opencode", "codex"])
def test_missing_topology_recovers_with_bound_external_model(monkeypatch, engine):
    import asyncio
    from unittest.mock import AsyncMock

    from runtime.sensing.gateway._team_stream_topology import _drive_team_topology
    from tests.test_drive_swarm_mesh import _Emitter, _Log

    monkeypatch.setattr("runtime.safety.organization.forge.load_registry", lambda: {})
    monkeypatch.setattr(
        "runtime.sensing.gateway._team_stream_topology.GatewayApprovalProvider",
        lambda *a, **kw: object(),
    )
    opencode = AsyncMock()
    codex = AsyncMock()
    native = AsyncMock(side_effect=AssertionError("native recovery is forbidden"))
    monkeypatch.setattr(
        "runtime.sensing.gateway.realtime_opencode_backend.drive_opencode", opencode
    )
    runtime = SimpleNamespace(
        _trace_store=None,
        _wrap_with_policy=lambda p: p,
        _resolve_agent=lambda *a: None,
        _drive_codex_app_server=codex,
        _drive_react=native,
    )
    turn = SimpleNamespace(thread_id="thread", id="turn", execution=SimpleNamespace(engine=engine))
    asyncio.run(
        _drive_team_topology(
            runtime,
            turn,
            _Log(),
            _Emitter(),
            SimpleNamespace(user_context={}),
            text="inspect",
            topology_id="missing",
        )
    )
    assert opencode.await_count == int(engine == "opencode")
    assert codex.await_count == int(engine == "codex")
    native.assert_not_awaited()

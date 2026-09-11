"""Coordinator model selection remains separate from deterministic host scheduling."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.execution.engines import (
    EngineId,
    EngineSelectionError,
    ExecutionPhase,
    select_execution_route,
)
from runtime.platform.config.schema import AgentConfig
from runtime.platform.models import ParsedIntent
from runtime.protocol import Turn, TurnParams
from runtime.sensing.gateway.realtime_execution import select_turn_execution


@pytest.mark.parametrize(
    "explicit,expected",
    [
        (None, EngineId.OPENCODE),
        (EngineId.OPENCODE, EngineId.OPENCODE),
        (EngineId.CODEX, EngineId.CODEX),
        (EngineId.OCTOPUS, EngineId.OCTOPUS),
    ],
)
def test_coordinator_uses_external_default_and_respects_explicit_choice(explicit, expected):
    route = select_execution_route(
        coordinated=True,
        requested_engine=explicit,
        coordinator_engine=EngineId.OPENCODE,
        coding_task=True,
        codex_partner=True,
    )
    assert route.engine is expected
    if expected is not EngineId.OCTOPUS:
        assert len({route.driver_for(phase) for phase in ExecutionPhase}) == 1


@pytest.mark.parametrize(
    "signals", [{"project_command": True}, {"group_fanout": True}, {"topology_id": "mesh"}]
)
def test_host_schedulers_do_not_become_external_model_runs(signals):
    route = select_execution_route(coordinator_engine=EngineId.OPENCODE, **signals)
    assert route.engine is EngineId.OPENCODE
    assert route.driver_for(ExecutionPhase.PRIMARY) in {"project_os", "group_fanout", "swarm_mesh"}
    assert route.driver_for(ExecutionPhase.REPAIR) == "opencode_server"
    explicit_route = select_execution_route(requested_engine=EngineId.OPENCODE, **signals)
    assert explicit_route.engine is route.engine
    assert explicit_route.driver == route.driver


@pytest.mark.parametrize("engine", [EngineId.OPENCODE, EngineId.CODEX])
def test_empty_group_fallback_uses_bound_engine(tmp_path, monkeypatch, engine):
    from unittest.mock import AsyncMock

    from runtime.execution.request import current_execution_request
    from runtime.memory.threads.event_log import EventLog
    from runtime.sensing.gateway._team_stream_group_fanout import _drive_group_fanout
    from runtime.sensing.gateway.realtime_execution import TurnExecutionRequest, bind_turn_execution

    turn = Turn(threadId="group", params=TurnParams(threadId="group", model="auto"))
    turn.execution_workspace_path = str(tmp_path)
    log = EventLog(tmp_path / "events.jsonl")
    log.turn_started(turn.thread_id, turn)
    seen = []

    async def external(*_args, **_kwargs):
        seen.append(current_execution_request().task)

    runtime = SimpleNamespace(
        _trace_store=None,
        _wrap_with_policy=lambda provider: provider,
        _resolve_agent=lambda params: object(),
        _drive_codex_app_server=external,
        _drive_react=AsyncMock(side_effect=AssertionError("native fallback")),
    )

    async def fanout(*args, **kwargs):
        await _drive_group_fanout(runtime, *args, **kwargs)

    runtime._drive_group_fanout = fanout
    monkeypatch.setattr(
        "runtime.sensing.gateway.realtime_opencode_backend.drive_opencode", external
    )
    supervisor = bind_turn_execution(
        runtime,
        turn,
        log,
        SimpleNamespace(notify=AsyncMock(), is_turn_interrupted=lambda _id: False),
        object(),
        object(),
        select_execution_route(group_fanout=True, requested_engine=engine),
    )
    intent = ParsedIntent(
        raw="Discuss proposal", normalized_goal="Discuss proposal", intent_type="task"
    )
    asyncio.run(supervisor.execute(TurnExecutionRequest(intent, intent.raw, "auto")))
    assert len(seen) == 1
    assert seen[0].execution_engine == engine.value
    assert seen[0].task_id == turn.id
    assert any(
        '"reason": "insufficient_members"' in (getattr(item, "content", "") or "")
        for item in turn.items
    )


@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("requested", ["auto", "opencode"])
@pytest.mark.parametrize("driver", ["coordinated", "group_fanout", "project_command"])
def test_standard_coordinator_admission_checks_opencode_without_native_fallback(
    monkeypatch, ready, requested, driver
):
    class Stack:
        config = AgentConfig()

        @property
        def planner(self):
            raise AssertionError("coordinator admission accessed native planner")

    runtime = SimpleNamespace(_stack=Stack())
    probe = Mock(return_value={"available": ready, "reason": "fixture unavailable"})
    monkeypatch.setattr("runtime.execution.opencode_backend.inspect_readiness", probe)
    monkeypatch.setattr(
        "runtime.sensing.gateway.realtime_execution.codex_readiness_for_turn",
        Mock(side_effect=AssertionError("unexpected Codex fallback")),
    )
    turn = Turn(
        threadId="team",
        params=TurnParams(
            threadId="team", executionEngine=requested, owner_actor_id="alice", tenant_id="acme"
        ),
    )
    intent = ParsedIntent(raw="Coordinate", normalized_goal="Coordinate", intent_type="task")
    request = select_turn_execution(
        runtime,
        turn,
        object(),
        intent,
        coordinated=driver == "coordinated",
        project_command=driver == "project_command",
        group_fanout=driver == "group_fanout",
        topology_id=None,
        codex_partner=False,
        reflection_fast_path=False,
    )
    if ready:
        assert asyncio.run(request).engine is EngineId.OPENCODE
    else:
        with pytest.raises(EngineSelectionError, match="fixture unavailable"):
            asyncio.run(request)
    scope = probe.call_args.args[0]
    assert scope.actor_id == "alice" and scope.tenant_id == "acme"


@pytest.mark.parametrize("delegation", ["absent", "error", "completed"])
def test_realtime_external_coordinator_keeps_model_and_checks_delegation(
    tmp_path, monkeypatch, delegation
):
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.memory.cowork.collaboration_store import CollaborationStore
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member, set_mode
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway
    from tests.test_realtime_cerebrum import _drive

    groups = GroupStore(base_dir=tmp_path / "groups")
    collaboration = CollaborationStore(base_dir=tmp_path / "collaboration")
    for member in ("general", "coder"):
        invite_member(groups, "coordinator", actor="u", target_id=member, kind="agent")
    set_mode(groups, "coordinator", actor="u", mode="swarm")
    runtime = CerebrumRuntime(
        stack=SimpleNamespace(config=AgentConfig()),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
        cowork_group_store=groups,
        collaboration_store=collaboration,
    )
    native = AsyncMock(side_effect=AssertionError("native coordinator used"))
    monkeypatch.setattr(runtime, "_drive_react", native)
    monkeypatch.setattr(
        "runtime.execution.opencode_backend.inspect_readiness", lambda scope: {"available": True}
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
        if delegation != "absent":
            from runtime.execution.opencode_backend import MessageEvents

            reducer = MessageEvents(
                set(), tool_names={"echo_call_agent_parallel": "call_agent_parallel"}
            )
            snapshot = {
                "info": {"id": "a", "role": "assistant"},
                "parts": [
                    {
                        "id": "tool",
                        "type": "tool",
                        "callID": f"delegate-{len(calls)}",
                        "tool": "echo_call_agent_parallel",
                        "state": {
                            "status": delegation,
                            "input": {
                                "specs": [
                                    {
                                        "task_id": "market",
                                        "agent_id": "general",
                                        "objective": "Research",
                                        "inputs": ["request"],
                                        "deliverable": "report",
                                        "dependencies": [],
                                        "acceptance_criteria": ["verified sources"],
                                        "prompt": "Research",
                                    }
                                ]
                            },
                            "output": '{"successes":[{"spec_index":0,"task_label":"market","agent_id":"general"}],"failures":[]}',
                            "error": "member failed" if delegation == "error" else None,
                        },
                    }
                ],
            }
            for event in reducer.consume([snapshot]):
                yield event
        yield {"type": "text_delta", "delta": "已经委派并完成。"}
        yield {"type": "react_completed", "success": True}

    monkeypatch.setattr("runtime.sensing.gateway.realtime_opencode_backend.stream_role", stream)
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)
    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        turn = _drive(
            ws,
            {
                "threadId": "coordinator",
                "model": "auto",
                "input": [{"type": "text", "text": "研究竞品并输出报告"}],
                "approvalPolicy": "never",
            },
        )["response"].result["turn"]
    expected = "completed" if delegation == "completed" else "interrupted"
    assert turn["status"] == expected, turn
    assert len(calls) == (1 if delegation == "completed" else 2)
    assert all(call["model"] == "big-pickle" for call in calls)
    if len(calls) == 2:
        assert calls[0]["request"].task is calls[1]["request"].task
        assert (
            calls[1]["context"]["cowork_orchestration_repair"]["reason"]
            == "missing_delegation_evidence"
        )
    run = collaboration.collaboration_runs_for_session("coordinator")[0]
    assert run["status"] == expected
    if delegation == "completed":
        assert run["result"]["task_graph_complete"] is True
    native.assert_not_called()
    from runtime.memory.threads.event_log import EventLog
    from runtime.platform.models.custom_model_selection import custom_model_selection_id

    restored = EventLog(runtime._log_for("coordinator").path).replay()[-1]
    assert restored.params.model == custom_model_selection_id("opencode-zen", "big-pickle")


@pytest.mark.parametrize("room_mode,message", [("chat", "大家一起看下"), ("swarm", "大家好")])
def test_explicit_opencode_group_greeting_dispatches_both_scoped_members(
    tmp_path, monkeypatch, room_mode, message
):
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.execution.parallel_agents.stack_runner import make_stack_subagent_runner
    from runtime.execution.request import current_execution_request
    from runtime.execution.subagents.bridge import call_subagent
    from runtime.memory.cowork.collaboration_store import CollaborationStore
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member, set_mode
    from runtime.platform.models.custom_model_selection import custom_model_selection_id
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway
    from tests.test_realtime_cerebrum import _drive

    thread_id = "explicit-opencode-group"
    monkeypatch.chdir(tmp_path)
    groups = GroupStore(base_dir=tmp_path / "groups")
    collaboration = CollaborationStore(base_dir=tmp_path / "collaboration")
    agents = {
        name: SimpleNamespace(agent_id=name, soul=name, capabilities={}, model=None)
        for name in ("general", "coder")
    }
    for name in agents:
        invite_member(groups, thread_id, actor="u", target_id=name, kind="agent")
    set_mode(groups, thread_id, actor="u", mode=room_mode)
    stack = SimpleNamespace(config=AgentConfig())
    runtime = CerebrumRuntime(
        stack=stack,
        agent=object(),
        logs_root=str(tmp_path / "threads"),
        cowork_group_store=groups,
        collaboration_store=collaboration,
    )
    native = AsyncMock(side_effect=AssertionError("native model invoked"))
    monkeypatch.setattr(runtime, "_drive_react", native)
    monkeypatch.setattr(
        "runtime.execution.opencode_backend.inspect_readiness", lambda scope: {"available": True}
    )
    monkeypatch.setattr(
        "runtime.execution.opencode_backend.zen_catalog",
        lambda: {"opencode-zen": {"managed_by_plugin": "opencode-zen", "models": ["big-pickle"]}},
    )
    runner = make_stack_subagent_runner(
        stack, agent_registry=SimpleNamespace(has=agents.__contains__, get=agents.__getitem__)
    )
    parents = []
    calls = []

    def member_call(*, agent_id, prompt, context, session, timeout_s, **_kwargs):
        parents.append(session.metadata["_execution_task"])
        return call_subagent(
            agent_id, prompt, context=context, session=session, runner=runner, timeout_s=timeout_s
        )

    async def stream(_stack, agent, **kwargs):
        calls.append((agent.agent_id, kwargs))
        assert current_execution_request().task.parent_task_id is not None
        yield {"type": "text_delta", "delta": f"{agent.agent_id}: 大家好！"}
        yield {"type": "react_completed", "success": True}

    monkeypatch.setattr("runtime.execution.suckers.delegation_skills._call_agent", member_call)
    monkeypatch.setattr("runtime.execution.opencode_roles.stream_role", stream)
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)
    selected_model = custom_model_selection_id("opencode-zen", "big-pickle")
    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        turn = _drive(
            ws,
            {
                "threadId": thread_id,
                "executionEngine": "opencode",
                "model": selected_model,
                "input": [{"type": "text", "text": message}],
                "approvalPolicy": "never",
            },
        )["response"].result["turn"]
    assert turn["status"] == "completed", turn
    assert turn["execution"]["engine"] == "opencode"
    assert turn["execution"]["driver"] == "group_fanout"
    assert {name for name, _ in calls} == set(agents)
    assert len(calls) == 2
    parent = parents[0]
    assert all(task is parent for task in parents)
    assert parent.execution_engine == "opencode"
    for _, call in calls:
        task = call["request"].task
        assert task.actor_id == parent.actor_id and task.tenant_id == parent.tenant_id
        assert task.parent_task_id == parent.task_id
        assert task.approval_provider is parent.approval_provider
        assert task.resources.deadline == parent.resources.deadline
        assert all(parent.permissions.allows_read(root) for root in task.permissions.readable_roots)
        assert all(
            parent.permissions.allows_write(root) for root in task.permissions.writable_roots
        )
        assert call["model"] == "big-pickle"
        assert call["tool_free"] is True
        assert call["context"]["context_steward_managed"] is True
    assert len({call["request"].task.thread_id for _, call in calls}) == 2
    replies = [item["text"] for item in turn["items"] if item["type"] == "agentMessage"]
    assert all(any(f"{name}: 大家好！" in reply for reply in replies) for name in agents)
    native.assert_not_called()

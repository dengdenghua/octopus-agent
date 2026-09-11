"""Temporary roles retain their tool ceiling when using OpenCode."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.execution.ephemeral_roles import make_host_ephemeral_runner
from runtime.execution.suckers.ephemeral_agents import EphemeralCall, EphemeralRoleDef
from runtime.platform.config.schema import AgentConfig


def test_native_host_without_model_stays_unavailable_without_breaking_bootstrap():
    from runtime.platform.config.schema import ExecutionConfig

    stack = SimpleNamespace(config=AgentConfig(execution=ExecutionConfig(member_engine="octopus")))
    runner = make_host_ephemeral_runner(stack)
    with pytest.raises(RuntimeError, match="require a model router"):
        runner(None)


def test_native_role_resolves_planner_only_when_called(monkeypatch):
    from runtime.platform.config.schema import ExecutionConfig

    router = object()
    registry = object()
    accesses = []

    class Host:
        config = AgentConfig(execution=ExecutionConfig(member_engine="octopus"))
        executor = SimpleNamespace(registry=registry)

        @property
        def planner(self):
            accesses.append("planner")
            return SimpleNamespace(router=router, planner_model="native-model")

    actual_runner = Mock(return_value="review complete")
    factory = Mock(return_value=actual_runner)
    monkeypatch.setattr(
        "runtime.execution.suckers.ephemeral_runner.make_llm_ephemeral_runner", factory
    )
    runner = make_host_ephemeral_runner(Host())
    assert accesses == []
    factory.assert_not_called()
    call = object()
    assert runner(call) == "review complete"
    assert accesses == ["planner"]
    factory.assert_called_once_with(router, registry=registry, default_model="native-model")
    actual_runner.assert_called_once_with(call)


@pytest.mark.parametrize("read_only", [False, True])
def test_temporary_role_preserves_selector_and_memory_denial(monkeypatch, read_only):
    class Host:
        config = AgentConfig()
        executor = SimpleNamespace(
            registry=SimpleNamespace(
                list_enabled=lambda: [
                    "read_file",
                    "write_text_file",
                    "remember",
                    "bb_read",
                    "bb_write",
                    "exec_shell",
                ]
            )
        )

        @property
        def planner(self):
            raise AssertionError("temporary OpenCode role loaded native planner")

    call = EphemeralCall(
        EphemeralRoleDef("reviewer", "Reviewer", "review", "Review files"),
        "Check the change",
        "Role and authorized memory",
        "parent",
        "lead",
        {
            "tool_allowlist": ["read_file", "write_text_file", "remember"],
            "tool_allowlist_read_only": read_only,
            "tool_allowlist_mode": "all",
        },
    )
    captured = Mock(return_value="reviewed")
    monkeypatch.setattr("runtime.execution.opencode_roles.run_role_sync", captured)
    runner = make_host_ephemeral_runner(Host())
    assert runner(call) == "reviewed"
    ceiling = captured.call_args.kwargs["tool_ceiling"]
    assert "read_file" in ceiling
    assert "remember" not in ceiling and "exec_shell" not in ceiling
    assert ("write_text_file" in ceiling) is not read_only
    assert captured.call_args.args[1].soul == call.composed_system_prompt


@pytest.mark.parametrize("allowed", [frozenset({"read_file"}), frozenset()])
def test_tool_ceiling_cannot_be_widened_by_full_mode_or_dynamic_grants(tmp_path, allowed):
    from runtime.execution.tool_engine.host_tool_broker import HostToolBroker
    from tests.test_host_mcp import host

    original, _, workspace = host(tmp_path)
    broker = HostToolBroker(
        original.broker._stack,
        original.session.agent,
        context={
            **original.session.metadata,
            "caller_session": original.session,
            "tool_allowlist_mode": "all",
            "extra_tool_allowlist": ["write_text_file", "plugin_probe"],
        },
        goal="read",
        outer_thread_id="thread-a",
        outer_turn_id="turn-a",
        workspace=str(workspace),
        tenant_id="tenant-a",
        principal_id="actor-a",
        approval_provider=None,
        is_interrupted=lambda: False,
        tool_ceiling=allowed,
        max_tools=1,
    )
    assert frozenset(broker.catalog.names) == allowed
    broker.bind_inner_scope(thread_id="thread-a", turn_id="turn-a")
    denied = asyncio.run(
        broker.invoke("write_text_file", {"path": "note.txt", "content": "bad"}, call_id="denied")
    )
    assert denied["success"] is False
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "before"


def test_real_ephemeral_bridge_keeps_host_authority_and_streams(tmp_path, monkeypatch):
    from runtime.execution import opencode_roles
    from runtime.execution.subagents.bridge import call_subagent
    from tests.test_host_mcp import host

    original, _, workspace = host(tmp_path)
    stack = original.broker._stack
    stack.config = AgentConfig()
    task = replace(
        original.request.task, execution_engine="octopus", authorization_intent="Review the files"
    )
    parent = replace(
        original.session,
        metadata={
            **original.session.metadata,
            "_execution_task": task,
            "_artifact_output_root": str(workspace),
        },
    )
    monkeypatch.setattr(
        "runtime.execution.suckers.ephemeral_agents._EPHEMERAL_RUNNER",
        make_host_ephemeral_runner(stack),
    )
    monkeypatch.setattr(
        "runtime.execution.subagents.bridge._resolve_cheap_subagent_model",
        Mock(side_effect=AssertionError("native model pool accessed")),
    )
    monkeypatch.setattr(
        opencode_roles.backend,
        "zen_catalog",
        lambda: {"opencode-zen": {"managed_by_plugin": "opencode-zen", "models": ["big-pickle"]}},
    )
    seen = []

    async def stream(*args, **kwargs):
        seen.append(kwargs)
        yield {
            "type": "tool_start",
            "tool_name": "read_file",
            "tool_call_id": "read-1",
            "input_preview": '{"path":"note.txt"}',
        }
        yield {
            "type": "tool_end",
            "tool_name": "read_file",
            "tool_call_id": "read-1",
            "success": True,
        }
        yield {"type": "text_delta", "delta": "Reviewed the file"}
        yield {"type": "react_completed", "success": True}

    monkeypatch.setattr(opencode_roles, "stream_role", stream)
    events = []
    result = call_subagent(
        "reviewer",
        "Review note.txt",
        session=parent,
        use_cheap_model=True,
        event_emitter=events.append,
    )
    assert result["success"] is True, result
    assert result["output"] == "Reviewed the file"
    child = seen[0]["request"].task
    assert child.parent_task_id == task.task_id and child.actor_id == task.actor_id
    assert child.resources.deadline == task.resources.deadline
    assert child.authorization_intent == "Review the files"
    assert seen[0]["tool_ceiling"] == frozenset({"read_file"})
    tool_end = next(event for event in events if event.get("type") == "sub_tool_end")
    assert tool_end["args"]["path"] == "note.txt" and tool_end["status"] == "success"
    assert any(event.get("type") == "sub_text_delta" for event in events)

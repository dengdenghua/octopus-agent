"""Default member engine policy and the real delegated host boundary."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from runtime.execution.parallel_agents.stack_runner import (
    make_stack_subagent_runner,
    member_execution_backend,
)
from runtime.platform.config.schema import AgentConfig, ExecutionConfig


def test_standard_host_defaults_to_opencode_without_readiness_fallback():
    stack = SimpleNamespace(config=AgentConfig())
    assert stack.config.execution.member_engine == "opencode"
    assert member_execution_backend(stack, SimpleNamespace(capabilities={})) == "opencode_server"
    assert member_execution_backend(SimpleNamespace(), None) == "native"


@pytest.mark.parametrize("mode", ["shared", "commercial", "production", "server"])
def test_local_only_backend_does_not_replace_shared_deployment_default(mode):
    assert ExecutionConfig(deployment_mode=mode).member_engine == "octopus"
    assert (
        ExecutionConfig(deployment_mode=mode, member_engine="opencode").member_engine == "opencode"
    )


@pytest.mark.parametrize(
    "backend,expected",
    [
        ("opencode_server", "opencode_server"),
        ("codex_app_server", "codex_app_server"),
        ("native", "native"),
        ("octopus", "native"),
    ],
)
@pytest.mark.parametrize("default", ["opencode", "octopus"])
def test_explicit_role_backend_wins(default, backend, expected):
    stack = SimpleNamespace(config=AgentConfig(execution=ExecutionConfig(member_engine=default)))
    agent = SimpleNamespace(capabilities={"execution_backend": backend})
    assert member_execution_backend(stack, agent) == expected


def test_invalid_configuration_does_not_silently_choose_a_model():
    with pytest.raises(ValidationError):
        ExecutionConfig(member_engine="typo")
    with pytest.raises(ValueError, match="unsupported member"):
        member_execution_backend(
            SimpleNamespace(config=AgentConfig()),
            SimpleNamespace(capabilities={"execution_backend": "opencdoe_server"}),
        )


def test_default_dispatch_does_not_access_native_dependencies(monkeypatch):
    class Host:
        config = AgentConfig()

        @property
        def planner(self):
            raise AssertionError("native planner accessed")

        @property
        def runtime(self):
            raise AssertionError("native runtime accessed")

    agent = SimpleNamespace(agent_id="member", capabilities={}, soul="member")
    registry = SimpleNamespace(has=lambda name: name == "member", get=lambda name: agent)
    run = Mock(return_value="OpenCode answer")
    monkeypatch.setattr("runtime.execution.opencode_roles.run_role_sync", run)
    runner = make_stack_subagent_runner(Host(), agent_registry=registry)
    assert (
        runner("reply", subagent_name="member", context={"direct_conversation_reply": True})
        == "OpenCode answer"
    )
    run.side_effect = RuntimeError("OpenCode not connected")
    with pytest.raises(RuntimeError, match="not connected"):
        runner("reply", subagent_name="member")
    with pytest.raises(ValueError, match="registered role"):
        runner("reply", subagent_name="unknown")


def test_native_compatibility_remains_explicit(monkeypatch):
    stack = SimpleNamespace(
        config=AgentConfig(execution=ExecutionConfig(member_engine="octopus")), planner=object()
    )
    reply = Mock(return_value="native answer")
    monkeypatch.setattr(
        "runtime.execution.parallel_agents.stack_runner._run_direct_conversation_reply", reply
    )
    runner = make_stack_subagent_runner(stack)
    assert (
        runner("reply", subagent_name="general", context={"direct_conversation_reply": True})
        == "native answer"
    )


@pytest.mark.parametrize("cheap", [False, True])
def test_delegation_defaults_to_opencode_through_real_child_scope(tmp_path, monkeypatch, cheap):
    import time

    from runtime.execution import opencode_roles
    from runtime.execution.request import ExecutionRequest, ExecutionResources, ExecutionTask
    from runtime.execution.subagents.bridge import call_subagent
    from runtime.platform.process.scope import ExecutionScope
    from runtime.platform.process.session import Session

    task = ExecutionTask(
        task_id="parent",
        thread_id="thread",
        actor_id="alice",
        tenant_id="acme",
        goal="Read the workspace",
        authorization_intent="Read the workspace",
        permissions=ExecutionScope(
            mode="ask",
            requested_mode="ask",
            readable_roots=(tmp_path,),
            writable_roots=(),
            network_policy="deny",
            shell_policy="deny",
        ),
        resources=ExecutionResources(1000, 1.0, time.monotonic() + 30),
        execution_engine="octopus",
    )
    agent = SimpleNamespace(
        agent_id="policy-test-member", soul="Member", capabilities={}, model="auto"
    )
    session = Session(
        actor="alice",
        thread_id="thread",
        turn_id="parent",
        agent=agent,
        metadata={
            "tenant_id": "acme",
            "workspace_path": str(tmp_path),
            "_artifact_output_root": str(tmp_path),
            "_host_workspace_read_root": tmp_path,
            "mode": "ask",
            "_execution_task": task,
        },
    )
    stack = SimpleNamespace(config=AgentConfig())
    registry = SimpleNamespace(has=lambda name: name == agent.agent_id, get=lambda name: agent)
    monkeypatch.setattr(
        opencode_roles.backend,
        "zen_catalog",
        lambda: {"opencode-zen": {"managed_by_plugin": "opencode-zen", "models": ["big-pickle"]}},
    )
    seen = []

    async def stream(*args, **kwargs):
        seen.append(kwargs)
        yield {"type": "text_delta", "delta": "Read successfully"}
        yield {"type": "react_completed", "success": True}

    monkeypatch.setattr(opencode_roles, "stream_role", stream)
    monkeypatch.setattr(
        "runtime.execution.subagents.bridge._resolve_cheap_subagent_model",
        Mock(side_effect=AssertionError("external member must not probe native model pool")),
    )
    runner = make_stack_subagent_runner(stack, agent_registry=registry)
    result = call_subagent(
        agent.agent_id, "Read the file", session=session, runner=runner, use_cheap_model=cheap
    )
    assert result["success"] is True, result
    assert len(seen) == 1
    request = seen[0]["request"]
    assert isinstance(request, ExecutionRequest)
    assert request.task.execution_engine == "opencode"
    assert request.task.parent_task_id == task.task_id
    assert request.task.actor_id == "alice" and request.task.tenant_id == "acme"
    assert not request.task.permissions.writable_roots
    assert request.task.resources.deadline == task.resources.deadline
    assert request.task.authorization_intent == task.authorization_intent

"""Real bridge worker threads retain host scope, lineage and cancellation."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from runtime.execution.misc.file_write_leases import (
    FileWriteLeaseConflict,
    acquire_file_write_lease,
)
from runtime.execution.request import (
    ExecutionRequest,
    ExecutionResources,
    ExecutionTask,
    current_execution_request,
    execution_request_scope,
)
from runtime.execution.subagents.bridge import call_subagent
from runtime.execution.tool_engine._executor_helpers import _file_write_lease_owner
from runtime.platform.process.scope import ExecutionScope, resolve_execution_scope
from runtime.platform.process.session import Session, current_session


def _parent(workspace, *, deadline=None):
    task = ExecutionTask(
        task_id="parent-turn",
        thread_id="parent-thread",
        actor_id="alice",
        tenant_id="tenant",
        goal="Build a report",
        permissions=ExecutionScope("code", "code", (workspace,), (workspace,)),
        resources=ExecutionResources(2000, 0.2, deadline),
    )
    return Session(
        actor="alice",
        thread_id=task.thread_id,
        turn_id=task.task_id,
        metadata={
            "_execution_task": task,
            "tenant_id": "tenant",
            "mode": "code",
            "workspace_path": str(workspace),
            "_file_write_leases": {},
            "_file_read_snapshots": {},
        },
    )


def test_bridge_children_have_distinct_identity_and_contend_for_same_file(tmp_path):
    parent = _parent(tmp_path)
    children = []
    caller_thread = threading.get_ident()

    def runner(prompt, *, subagent_name, context):
        assert threading.get_ident() != caller_thread
        request = current_execution_request()
        session = current_session()
        children.append(request.task)
        assert request.task.parent_task_id == "parent-turn"
        assert request.task.actor_id == session.actor == "alice"
        assert request.instruction == prompt
        assert request.task.resources is parent.metadata["_execution_task"].resources
        # The default public lane remains shared; the execution identity is
        # separate so private engine state and write ownership cannot collide.
        assert request.task.thread_id != parent.thread_id
        assert session.metadata["_file_write_leases"] is parent.metadata["_file_write_leases"]
        scope = resolve_execution_scope(
            Session(
                thread_id="forged",
                metadata={"mode": "code", "workspace_path": str(tmp_path.parent)},
            )
        )
        assert scope.allows_write(tmp_path / "report.txt")
        assert not scope.allows_write(tmp_path.parent / "outside.txt")
        owner = _file_write_lease_owner(actor="alice", arm_id="code", caller="child")
        assert owner == request.task.task_id
        if len(children) == 1:
            acquire_file_write_lease(session, tmp_path / "report.txt", owner=owner)
        else:
            with pytest.raises(FileWriteLeaseConflict):
                acquire_file_write_lease(session, tmp_path / "report.txt", owner=owner)
        return "completed"

    for instruction in ("Write the report", "Review its sources"):
        result = call_subagent(
            "coder", instruction, session=parent, runner=runner, timeout_seconds=3
        )
        assert result["success"], result
    assert children[0].task_id != children[1].task_id
    assert current_execution_request() is None
    assert parent.metadata["_execution_task"].task_id == "parent-turn"


def test_parent_deadline_cancels_monitored_child_without_explicit_child_timeout(tmp_path):
    from runtime.safety.approval.cancellation import current_cancellation_token

    parent = _parent(tmp_path, deadline=time.monotonic() + 0.3)
    finished = threading.Event()

    def runner(*_args, **_kwargs):
        token = current_cancellation_token()
        try:
            while not token.is_cancelled:
                time.sleep(0.005)
            return "late output"
        finally:
            finished.set()

    result = call_subagent("coder", "wait for input", session=parent, runner=runner)
    assert result["status"] == "timeout"
    assert not result["success"]
    assert result["output"] == ""
    assert finished.wait(1), "parent deadline did not trip the worker cancellation token"


def test_codex_sync_adapter_preserves_request_when_called_from_running_event_loop(
    tmp_path, monkeypatch
):
    from runtime.execution.codex_backend import role_runner

    parent = _parent(tmp_path)
    request = ExecutionRequest(parent.metadata["_execution_task"], "create report")
    seen = []

    async def run(*_args, **_kwargs):
        seen.append(current_execution_request())
        return role_runner.CodexRoleExecution("done", True, "completed")

    monkeypatch.setattr(role_runner, "run_agent_role", run)

    async def scenario():
        with execution_request_scope(request):
            result = role_runner.run_agent_role_sync(object(), object(), "create report")
        assert result.success

    asyncio.run(scenario())
    assert seen == [request]


def test_codex_builtins_cannot_write_beyond_child_artifact_scope(tmp_path):
    from runtime.execution.codex_backend.role_runner import resolve_codex_sandbox_mode

    parent = _parent(tmp_path)
    task = parent.metadata["_execution_task"]
    artifact_root = tmp_path / "artifacts"
    task = replace(task, permissions=replace(task.permissions, writable_roots=(artifact_root,)))
    with execution_request_scope(ExecutionRequest(task, "produce artifact")):
        assert resolve_codex_sandbox_mode({"workspace_path": str(tmp_path)}) == "read-only"
        assert (
            resolve_codex_sandbox_mode({"workspace_path": str(artifact_root)}) == "workspace-write"
        )


def test_codex_child_observes_parent_cancellation_in_stack_runner(tmp_path, monkeypatch):
    from runtime.execution.codex_backend import role_runner
    from runtime.execution.parallel_agents.stack_runner import make_stack_subagent_runner
    from runtime.safety.approval.cancellation import CancellationSource, scoped_cancellation

    source = CancellationSource()
    agent = SimpleNamespace(
        capabilities={"execution_backend": "codex_app_server"}, display_name="Coder"
    )
    registry = SimpleNamespace(has=lambda _name: True, get=lambda _name: agent)
    stack = SimpleNamespace(planner=SimpleNamespace(plan=lambda: None), runtime=object())

    def run(*_args, **kwargs):
        assert not kwargs["is_interrupted"]()
        source.cancel(reason="parent stopped")
        assert kwargs["is_interrupted"]()
        return role_runner.CodexRoleExecution("stopped", False, "interrupted")

    monkeypatch.setattr(role_runner, "run_agent_role_sync", run)
    runner = make_stack_subagent_runner(stack, agent_registry=registry)
    with scoped_cancellation(source.token), pytest.raises(RuntimeError, match="stopped"):
        runner("build", subagent_name="coder")


def test_codex_materialization_uses_child_coordinates_and_resolved_workspace(tmp_path, monkeypatch):
    from runtime.execution.codex_backend import role_runner
    from runtime.execution.subagents.execution_context import child_execution_scope
    from runtime.platform.process.session import session_scope

    parent = _parent(tmp_path)
    child = replace(parent, metadata=dict(parent.metadata))
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    child.metadata["_locked_write_root"] = str(artifact_root)
    monkeypatch.setattr(role_runner, "require_codex_backend_enabled", lambda: None)
    monkeypatch.setattr(role_runner, "state_root_for_workspace", lambda _path: tmp_path / "state")
    monkeypatch.setattr(
        role_runner, "codex_app_server_command", lambda _agent: ("codex", "app-server")
    )
    monkeypatch.setattr(role_runner, "compose_codex_role_instructions", lambda *_a, **_kw: "role")
    monkeypatch.setattr(
        role_runner,
        "CodexDynamicToolBroker",
        lambda *_a, **_kw: SimpleNamespace(catalog=SimpleNamespace(specs=())),
    )
    monkeypatch.setattr(
        role_runner,
        "_execution_profile",
        lambda *_a, **_kw: SimpleNamespace(
            effective_model="test-model",
            reasoning_effort=None,
            provider_profile=None,
            proxy_required=True,
        ),
    )
    stack = SimpleNamespace(executor=SimpleNamespace(registry=object()))
    with (
        child_execution_scope(
            parent, child, child_id="child-1", instruction="make artifact"
        ) as shared,
        session_scope(child),
    ):
        request, _, _ = role_runner.build_codex_role_request(
            stack,
            object(),
            "make artifact",
            context={
                "thread_id": parent.thread_id,
                "turn_id": parent.turn_id,
                # A narrower client workspace must not grant write-enabled
                # built-ins against the actual parent-selected project root.
                "workspace_path": str(artifact_root),
            },
        )
    assert request.execution is shared
    assert request.outer_thread_id == request.outer_turn_id == "child-1"
    assert request.workspace == tmp_path
    assert request.sandbox_mode == "read-only"

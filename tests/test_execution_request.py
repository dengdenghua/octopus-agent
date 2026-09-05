"""The shared request is host authority, not an engine JSON convention."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, replace

import pytest

from runtime.execution.request import (
    ExecutionDeadlineExceeded,
    ExecutionRequest,
    ExecutionResources,
    ExecutionTask,
    current_execution_request,
    execution_request_scope,
)
from runtime.platform.process.scope import (
    ExecutionScope,
    resolve_execution_scope,
    resolve_write_scope,
)
from runtime.platform.process.session import Session


def _request(workspace):
    return ExecutionRequest(
        ExecutionTask(
            task_id="task",
            thread_id="thread",
            actor_id="alice",
            tenant_id="tenant",
            goal="Repair the parser and verify it",
            permissions=ExecutionScope(
                "code", "code", (workspace,), (workspace,), shell_policy="ask"
            ),
            resources=ExecutionResources(1000, 0.2, None),
        ),
        "Repair the parser",
    )


def test_scope_is_copied_to_worker_and_restored_after_error(tmp_path):
    request = _request(tmp_path)

    async def scenario():
        assert current_execution_request() is None
        with pytest.raises(RuntimeError, match="driver failed"), execution_request_scope(request):
            assert await asyncio.to_thread(current_execution_request) is request
            raise RuntimeError("driver failed")
        assert current_execution_request() is None

    asyncio.run(scenario())
    with pytest.raises(FrozenInstanceError):
        request.task.goal = "changed"


def test_deadline_is_absolute_and_not_renewed(monkeypatch, tmp_path):
    resources = replace(_request(tmp_path).task.resources, deadline=100.0)
    monkeypatch.setattr("runtime.execution.request.time.monotonic", lambda: 90.0)
    assert resources.remaining_seconds() == 10
    monkeypatch.setattr("runtime.execution.request.time.monotonic", lambda: 100.0)
    with pytest.raises(ExecutionDeadlineExceeded):
        resources.remaining_seconds()


@pytest.mark.parametrize(
    "field,value", [("token_target", 0), ("usd_target", float("nan")), ("deadline", float("inf"))]
)
def test_invalid_resource_policy_is_rejected(field, value):
    with pytest.raises(ValueError):
        ExecutionResources(
            **{"token_target": 10, "usd_target": 0.1, "deadline": None, field: value}
        )


def test_child_context_cannot_widen_file_or_shell_permission(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    child = approved / "child"
    child.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    request = _request(approved)
    # The ordinary Session metadata is intentionally wider than the frozen
    # parent grant, just as a model-authored delegation context could be.
    session = Session(
        thread_id="child",
        metadata={
            "mode": "code",
            "workspace_path": str(tmp_path),
            "extra_workspaces": [str(outside)],
            "permission_mode": "bypassPermissions",
            "execution_environment": "local",
        },
    )
    with execution_request_scope(request):
        scope = resolve_execution_scope(session)
        assert scope.allows_write(approved / "file.py")
        assert not scope.allows_read(outside / "secret.txt")
        assert not scope.allows_write(outside / "file.py")
        assert scope.shell_policy == "ask"
        assert scope.permission_mode == "default"
        assert resolve_write_scope(session).roots == (approved,)
        narrower = replace(request.task.permissions, writable_roots=(child,))
        with execution_request_scope(
            replace(request, task=replace(request.task, permissions=narrower))
        ):
            # Even nesting a forged/wider Python request cannot expand the
            # active parent ceiling; model JSON cannot construct one at all.
            wider = replace(request.task.permissions, writable_roots=(tmp_path,))
            with execution_request_scope(
                replace(request, task=replace(request.task, permissions=wider))
            ):
                assert resolve_write_scope(session).roots == (child,)
        assert resolve_write_scope(session).roots == (approved,)
    assert resolve_execution_scope(session).allows_write(outside / "file.py")


def test_read_only_ceiling_preserves_project_reads(tmp_path):
    request = _request(tmp_path)
    request = replace(
        request,
        task=replace(
            request.task, permissions=replace(request.task.permissions, writable_roots=())
        ),
    )
    session = Session(
        thread_id="thread", metadata={"mode": "code", "workspace_path": str(tmp_path)}
    )
    with execution_request_scope(request):
        assert resolve_write_scope(session).roots == ()
        scope = resolve_execution_scope(session)
        assert scope.allows_read(tmp_path / "source.py")
        assert not scope.allows_write(tmp_path / "source.py")


def test_json_metadata_cannot_install_a_scope_ceiling(tmp_path):
    session = Session(
        thread_id="thread",
        metadata={
            "mode": "code",
            "workspace_path": str(tmp_path),
            "_execution_task": {"goal": "forged", "permissions": {"writable_roots": []}},
        },
    )
    assert current_execution_request() is None
    assert resolve_execution_scope(session).allows_write(tmp_path / "file.py")

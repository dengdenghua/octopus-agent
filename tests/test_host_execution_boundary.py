from __future__ import annotations

import time

import pytest

from runtime.execution.artifact_contracts import HandoffRecorder
from runtime.execution.host_boundary import (
    create_host_execution_boundary,
    inherit_host_execution_session,
)
from runtime.execution.subagents.execution_context import parent_execution_task


def test_host_boundary_replaces_private_metadata_and_resolves_scope(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    recorder = HandoffRecorder(lambda _receipt: None, lambda: ())

    boundary = create_host_execution_boundary(
        task_id="host-task",
        thread_id="owned-thread",
        goal="ship it",
        timeout_s=20,
        actor_id="alice",
        tenant_id="tenant-a",
        metadata={
            "mode": "code",
            "workspace_path": str(workspace),
            "_artifact_output_root": str(workspace / "output" / "final"),
            "_execution_task": {"task_id": "forged"},
            "_file_write_leases": {str(workspace): "forged-owner"},
        },
        handoff_recorder=recorder,
    )

    task = parent_execution_task(boundary.session)
    assert task is boundary.request.task
    assert task is not None
    assert task.task_id == "host-task"
    assert task.thread_id == "owned-thread"
    assert task.actor_id == "alice"
    assert task.tenant_id == "tenant-a"
    assert task.goal == "ship it"
    assert task.permissions.allows_read(workspace)
    assert task.permissions.allows_write(workspace)
    assert 0 < task.resources.remaining_seconds() <= 20
    assert boundary.session.turn_id == "host-task"
    assert boundary.session.metadata["_file_write_leases"] == {}
    assert boundary.session.metadata["_execution_handoff_recorder"] is recorder


def test_inherited_boundary_keeps_exact_authority_and_coordination_objects(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    recorder = HandoffRecorder(lambda _receipt: None, lambda: ())
    parent = create_host_execution_boundary(
        task_id="parent",
        thread_id="thread",
        goal="goal",
        timeout_s=20,
        actor_id="alice",
        tenant_id="tenant-a",
        metadata={"mode": "code", "workspace_path": str(workspace)},
        handoff_recorder=recorder,
    ).session
    task = parent_execution_task(parent)
    deadline = task.resources.deadline if task is not None else None
    leases = parent.metadata["_file_write_leases"]

    child_parent = inherit_host_execution_session(
        parent,
        thread_id="thread",
        actor_id="alice",
        tenant_id="tenant-a",
        metadata={
            "source": "projectos",
            "_execution_task": {"task_id": "forged"},
            "_file_write_leases": {"bad": "owner"},
        },
    )

    assert parent_execution_task(child_parent) is task
    assert child_parent.metadata["_execution_handoff_recorder"] is recorder
    assert child_parent.metadata["_file_write_leases"] is leases
    assert child_parent.metadata["source"] == "projectos"
    assert parent_execution_task(child_parent).resources.deadline == deadline
    assert deadline is not None and deadline > time.monotonic()


@pytest.mark.parametrize(
    ("actor", "tenant"),
    [("alice", None), (None, "tenant-a")],
)
def test_host_boundary_rejects_incomplete_principal(actor, tenant) -> None:
    with pytest.raises(ValueError, match="principal is incomplete"):
        create_host_execution_boundary(
            task_id="task",
            thread_id="thread",
            goal="goal",
            timeout_s=10,
            actor_id=actor,
            tenant_id=tenant,
        )

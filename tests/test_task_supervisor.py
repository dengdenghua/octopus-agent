from __future__ import annotations

import time

import pytest

from runtime.platform.process.task_supervisor import (
    LostTaskLease,
    TaskCapabilityManifest,
    TaskLeaseConflict,
    TaskRunStatus,
    TaskSupervisor,
    TaskSupervisorStore,
)


def test_task_supervisor_persists_lifecycle_and_releases_terminal_lease(tmp_path):
    supervisor = TaskSupervisor.from_path(
        tmp_path / "task_runs.json",
        holder_id="worker-a",
        lease_ttl_seconds=30,
    )

    started = supervisor.start_task(
        task_id="task-1",
        kind="loop",
        owner_id="alice",
        thread_id="thread-1",
        title="Fix failing tests",
        goal="Fix failing tests",
        mode="code",
        workspace_path=str(tmp_path / "workspace"),
    )

    assert started.status == TaskRunStatus.RUNNING
    assert started.lease is not None
    assert started.lease.holder_id == "worker-a"
    assert started.capabilities.allows_group("shell") is True
    assert started.capabilities.workspace_paths == [str(tmp_path / "workspace")]

    heartbeat = supervisor.heartbeat("task-1")
    assert heartbeat.heartbeat_at is not None
    assert heartbeat.lease is not None
    assert heartbeat.lease.token == started.lease.token

    completed = supervisor.transition(
        "task-1",
        TaskRunStatus.COMPLETED,
        checkpoint_id=42,
    )
    assert completed.status == TaskRunStatus.COMPLETED
    assert completed.completed_at is not None
    assert completed.latest_checkpoint_id == 42
    assert completed.lease is None

    reloaded = TaskSupervisorStore(tmp_path / "task_runs.json").get("task-1")
    assert reloaded is not None
    assert reloaded.status == TaskRunStatus.COMPLETED
    assert reloaded.latest_checkpoint_id == 42


def test_task_supervisor_rejects_foreign_lease_until_expired(tmp_path):
    path = tmp_path / "task_runs.json"
    worker_a = TaskSupervisor.from_path(path, holder_id="worker-a", lease_ttl_seconds=30)
    worker_b = TaskSupervisor.from_path(path, holder_id="worker-b", lease_ttl_seconds=30)

    started = worker_a.start_task(task_id="task-lease", kind="loop")

    assert started.lease is not None
    assert started.lease.holder_id == "worker-a"
    with pytest.raises(TaskLeaseConflict):
        worker_b.start_task(task_id="task-lease", kind="loop")
    with pytest.raises(LostTaskLease):
        worker_b.heartbeat("task-lease")
    with pytest.raises(LostTaskLease):
        worker_b.transition("task-lease", TaskRunStatus.VERIFYING)

    def _expire(record):
        assert record.lease is not None
        return record.model_copy(
            update={
                "lease": record.lease.model_copy(update={"expires_at": time.time() - 1}),
            },
            deep=True,
        )

    worker_a.store.mutate("task-lease", _expire)
    takeover = worker_b.start_task(task_id="task-lease", kind="loop")

    assert takeover.lease is not None
    assert takeover.lease.holder_id == "worker-b"
    assert takeover.lease.token != started.lease.token
    assert worker_b.is_current_holder("task-lease") is True
    assert worker_a.is_current_holder("task-lease") is False
    with pytest.raises(LostTaskLease):
        worker_a.heartbeat("task-lease")


def test_task_supervisor_detects_stale_same_holder_token(tmp_path):
    path = tmp_path / "task_runs.json"
    first = TaskSupervisor.from_path(path, holder_id="same-worker", lease_ttl_seconds=30)
    second = TaskSupervisor.from_path(path, holder_id="same-worker", lease_ttl_seconds=30)

    original = first.start_task(task_id="task-token", kind="loop")
    replacement = second.start_task(task_id="task-token", kind="loop")

    assert original.lease is not None
    assert replacement.lease is not None
    assert replacement.lease.token != original.lease.token
    with pytest.raises(LostTaskLease, match="token"):
        first.heartbeat("task-token")


def test_task_capability_manifest_fails_closed_for_disabled_group():
    manifest = TaskCapabilityManifest(groups={"shell": False})

    assert manifest.allows_group("builtin") is True
    assert manifest.allows_group("shell") is False
    assert manifest.allows_group("unknown") is False
    assert manifest.allows_group(None) is True

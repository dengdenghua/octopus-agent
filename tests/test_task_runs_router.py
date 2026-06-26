from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.platform.process.task_supervisor import TaskRunStatus, TaskSupervisor
from runtime.safety.auth.identity import Identity, IdentityStore
from runtime.sensing.gateway.task_runs_router import create_task_runs_router


def test_task_runs_router_lists_and_reads_supervisor_records(tmp_path):
    supervisor = TaskSupervisor.from_path(tmp_path / "task_runs.json", holder_id="worker-a")
    supervisor.start_task(
        task_id="task-1",
        kind="loop",
        owner_id="alice",
        thread_id="thread-1",
        title="Fix tests",
        goal="Fix tests",
        mode="code",
    )
    supervisor.transition("task-1", TaskRunStatus.COMPLETED, checkpoint_id=7)
    supervisor.start_task(
        task_id="task-2",
        kind="background",
        owner_id="bob",
        thread_id="thread-2",
        title="Sync",
        goal="Sync",
    )

    app = FastAPI()
    app.include_router(create_task_runs_router(supervisor=supervisor))
    client = TestClient(app)

    listed = client.get("/api/task-runs", params={"kind": "loop"})
    detail = client.get("/api/task-runs/task-1")
    missing = client.get("/api/task-runs/missing")
    overview = client.get("/api/task-runs/overview")
    alice_overview = client.get("/api/task-runs/overview", params={"owner_id": "alice"})

    assert listed.status_code == 200
    body = listed.json()
    assert body["schema"] == "octopus.task_runs.v1"
    assert body["total"] == 1
    assert body["tasks"][0]["task_id"] == "task-1"
    assert body["tasks"][0]["status"] == "completed"
    assert body["items"][0]["task_run"]["task_id"] == "task-1"
    assert body["items"][0]["lease_health"]["state"] == "terminal"
    assert body["items"][0]["lease_health"]["recommended_action"] == "none"

    assert detail.status_code == 200
    assert detail.json()["task_run"]["latest_checkpoint_id"] == 7
    assert detail.json()["lease_health"]["state"] == "terminal"

    assert missing.status_code == 404

    assert overview.status_code == 200
    overview_body = overview.json()
    assert overview_body["schema"] == "octopus.task_runs_overview.v1"
    assert overview_body["total"] == 2
    assert overview_body["active_count"] == 1
    assert overview_body["terminal_count"] == 1
    assert overview_body["by_status"] == {"completed": 1, "running": 1}
    assert overview_body["active_task_ids"] == ["task-2"]
    assert overview_body["takeover_recommended_count"] == 0
    assert overview_body["resumable_count"] == 0
    assert overview_body["by_recommended_action"] == {"monitor": 1, "none": 1}
    assert overview_body["lease_health"][0]["task_id"] == "task-2"
    assert overview_body["lease_health"][0]["state"] == "ok"
    assert overview_body["lease_health"][0]["recommended_action"] == "monitor"

    assert alice_overview.status_code == 200
    alice_body = alice_overview.json()
    assert alice_body["total"] == 1
    assert alice_body["terminal_count"] == 1
    assert alice_body["active_count"] == 0
    assert alice_body["by_recommended_action"] == {"none": 1}
    assert alice_body["filters"]["owner_id"] == "alice"


def test_task_runs_router_list_total_counts_filtered_rows_not_page_size(tmp_path):
    supervisor = TaskSupervisor.from_path(tmp_path / "task_runs.json", holder_id="worker-a")
    for index in range(3):
        supervisor.start_task(
            task_id=f"task-loop-{index}",
            kind="loop",
            owner_id="alice",
            thread_id=f"thread-{index}",
        )
    supervisor.start_task(task_id="task-background", kind="background", owner_id="alice")

    app = FastAPI()
    app.include_router(create_task_runs_router(supervisor=supervisor))
    client = TestClient(app)

    response = client.get("/api/task-runs", params={"kind": "loop", "limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["count"] == 2
    assert len(body["tasks"]) == 2
    assert len(body["items"]) == 2
    assert all(item["task_run"]["kind"] == "loop" for item in body["items"])


def test_task_runs_router_records_approval_decision_with_owner_isolation(tmp_path):
    supervisor = TaskSupervisor.from_path(tmp_path / "task_runs.json", holder_id="worker-a")
    supervisor.start_task(
        task_id="task-approval",
        kind="loop",
        owner_id="alice",
        metadata={
            "approval_required": True,
            "approval_tool_name": "exec_shell",
            "approval_action": "confirm",
        },
    )
    supervisor.transition(
        "task-approval",
        TaskRunStatus.WAITING_APPROVAL,
        reason="approval required",
    )
    supervisor.start_task(task_id="task-running", kind="loop", owner_id="alice")
    identity_store = IdentityStore()
    identity_store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    identity_store.add(Identity(actor_id="bob"), api_key_plaintext="sk-bob")

    app = FastAPI()
    app.include_router(
        create_task_runs_router(
            supervisor=supervisor,
            identity_store=identity_store,
            require_auth=True,
        )
    )
    client = TestClient(app)

    denied = client.post(
        "/api/task-runs/task-approval/approval-decision",
        json={"approved": True, "reason": "ship it"},
        headers={"Authorization": "Bearer sk-bob"},
    )
    conflict = client.post(
        "/api/task-runs/task-running/approval-decision",
        json={"approved": True},
        headers={"Authorization": "Bearer sk-alice"},
    )
    approved = client.post(
        "/api/task-runs/task-approval/approval-decision",
        json={"approved": True, "reason": "ship it"},
        headers={"Authorization": "Bearer sk-alice"},
    )

    assert denied.status_code == 404
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "task is not waiting for approval"

    assert approved.status_code == 200
    body = approved.json()
    assert body["schema"] == "octopus.task_run_approval_decision.v1"
    assert body["task_run"]["status"] == "running"
    assert body["task_run"]["metadata"]["approval_decision"] == "approved"
    assert body["task_run"]["metadata"]["approval_decided_by"] == "alice"
    assert body["task_run"]["metadata"]["approval_decision_reason"] == "ship it"
    assert body["lease_health"]["recommended_action"] == "monitor"


def test_task_runs_router_auth_list_includes_public_tasks_but_isolates_other_owners(
    tmp_path,
):
    supervisor = TaskSupervisor.from_path(tmp_path / "task_runs.json", holder_id="worker-a")
    supervisor.start_task(task_id="task-public", kind="loop")
    supervisor.start_task(task_id="task-alice", kind="loop", owner_id="alice")
    supervisor.start_task(task_id="task-bob", kind="loop", owner_id="bob")
    identity_store = IdentityStore()
    identity_store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")

    app = FastAPI()
    app.include_router(
        create_task_runs_router(
            supervisor=supervisor,
            identity_store=identity_store,
            require_auth=True,
        )
    )
    client = TestClient(app)

    listed = client.get("/api/task-runs", headers={"Authorization": "Bearer sk-alice"})
    public_detail = client.get(
        "/api/task-runs/task-public",
        headers={"Authorization": "Bearer sk-alice"},
    )
    bob_detail = client.get(
        "/api/task-runs/task-bob",
        headers={"Authorization": "Bearer sk-alice"},
    )
    overview = client.get("/api/task-runs/overview", headers={"Authorization": "Bearer sk-alice"})

    assert listed.status_code == 200
    task_ids = {task["task_id"] for task in listed.json()["tasks"]}
    assert task_ids == {"task-public", "task-alice"}
    assert listed.json()["total"] == 2
    assert public_detail.status_code == 200
    assert bob_detail.status_code == 404
    assert overview.status_code == 200
    assert overview.json()["total"] == 2
    assert overview.json()["filters"]["owner_id"] == "alice"


def test_task_runs_router_records_approval_rejection(tmp_path):
    supervisor = TaskSupervisor.from_path(tmp_path / "task_runs.json", holder_id="worker-a")
    supervisor.start_task(
        task_id="task-reject",
        kind="loop",
        metadata={"approval_required": True, "approval_tool_name": "exec_shell"},
    )
    supervisor.transition(
        "task-reject",
        TaskRunStatus.WAITING_APPROVAL,
        reason="approval required",
    )

    app = FastAPI()
    app.include_router(create_task_runs_router(supervisor=supervisor))
    client = TestClient(app)

    rejected = client.post(
        "/api/task-runs/task-reject/approval-decision",
        json={"approved": False, "reason": "too risky"},
    )

    assert rejected.status_code == 200
    body = rejected.json()
    assert body["task_run"]["status"] == "paused"
    assert body["task_run"]["metadata"]["approval_decision"] == "rejected"
    assert body["task_run"]["metadata"]["approval_denied"] is True
    assert body["lease_health"]["recommended_action"] == "resume_paused_task"


def test_task_runs_router_rejects_non_approvable_denials(tmp_path):
    supervisor = TaskSupervisor.from_path(tmp_path / "task_runs.json", holder_id="worker-a")
    supervisor.start_task(
        task_id="task-policy-denied",
        kind="loop",
        metadata={
            "approval_required": False,
            "approval_denied": True,
            "approval_action": "deny",
        },
    )
    supervisor.transition(
        "task-policy-denied",
        TaskRunStatus.WAITING_APPROVAL,
        reason="approval policy denied",
    )
    supervisor.start_task(
        task_id="task-capability-denied",
        kind="loop",
        metadata={
            "approval_required": False,
            "approval_denied": True,
            "approval_action": "capability_denied",
            "capability_denied": True,
        },
    )
    supervisor.transition(
        "task-capability-denied",
        TaskRunStatus.WAITING_APPROVAL,
        reason="task capability group disabled: shell",
    )

    app = FastAPI()
    app.include_router(create_task_runs_router(supervisor=supervisor))
    client = TestClient(app)

    policy_approved = client.post(
        "/api/task-runs/task-policy-denied/approval-decision",
        json={"approved": True, "reason": "override"},
    )
    policy_rejected = client.post(
        "/api/task-runs/task-policy-denied/approval-decision",
        json={"approved": False, "reason": "ack"},
    )
    capability_approved = client.post(
        "/api/task-runs/task-capability-denied/approval-decision",
        json={"approved": True, "reason": "override"},
    )
    capability_rejected = client.post(
        "/api/task-runs/task-capability-denied/approval-decision",
        json={"approved": False, "reason": "ack"},
    )
    detail = client.get("/api/task-runs/task-capability-denied")

    assert policy_approved.status_code == 409
    assert policy_approved.json()["detail"] == "task is blocked by approval policy"
    assert policy_rejected.status_code == 409
    assert policy_rejected.json()["detail"] == "task is blocked by approval policy"
    assert capability_approved.status_code == 409
    assert capability_approved.json()["detail"] == "task is blocked by disabled capability"
    assert capability_rejected.status_code == 409
    assert capability_rejected.json()["detail"] == "task is blocked by disabled capability"
    assert detail.status_code == 200
    assert detail.json()["lease_health"]["recommended_action"] == "capability_policy_denied"


def test_task_runs_router_maps_expired_approval_lease_to_conflict(tmp_path):
    path = tmp_path / "task_runs.json"
    worker = TaskSupervisor.from_path(path, holder_id="worker-a", lease_ttl_seconds=30)
    worker.start_task(
        task_id="task-approval-expired",
        kind="loop",
        metadata={
            "approval_required": True,
            "approval_tool_name": "exec_shell",
            "approval_action": "confirm",
        },
    )
    worker.transition(
        "task-approval-expired",
        TaskRunStatus.WAITING_APPROVAL,
        reason="approval required",
    )

    def _expire(record):
        assert record.lease is not None
        return record.model_copy(
            update={"lease": record.lease.model_copy(update={"expires_at": time.time() - 1})},
            deep=True,
        )

    worker.store.mutate("task-approval-expired", _expire)
    app = FastAPI()
    app.include_router(create_task_runs_router(supervisor=worker))
    client = TestClient(app)

    approved = client.post(
        "/api/task-runs/task-approval-expired/approval-decision",
        json={"approved": True, "reason": "ship"},
    )
    detail = client.get("/api/task-runs/task-approval-expired")

    assert approved.status_code == 409
    assert "lease is no longer current" in approved.json()["detail"]
    assert detail.status_code == 200
    assert detail.json()["lease_health"]["recommended_action"] == "takeover_for_approval"


def test_task_runs_router_takes_over_expired_task_with_owner_isolation(tmp_path):
    path = tmp_path / "task_runs.json"
    worker_a = TaskSupervisor.from_path(path, holder_id="worker-a", lease_ttl_seconds=30)
    operator = TaskSupervisor.from_path(path, holder_id="operator", lease_ttl_seconds=30)
    worker_a.start_task(
        task_id="task-expired",
        kind="loop",
        owner_id="alice",
        metadata={"attempt_count": 1},
    )

    def _expire(record):
        assert record.lease is not None
        return record.model_copy(
            update={
                "lease": record.lease.model_copy(update={"expires_at": time.time() - 1}),
            },
            deep=True,
        )

    worker_a.store.mutate("task-expired", _expire)
    identity_store = IdentityStore()
    identity_store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    identity_store.add(Identity(actor_id="bob"), api_key_plaintext="sk-bob")

    app = FastAPI()
    app.include_router(
        create_task_runs_router(
            supervisor=operator,
            identity_store=identity_store,
            require_auth=True,
        )
    )
    client = TestClient(app)

    denied = client.post(
        "/api/task-runs/task-expired/takeover",
        json={"reason": "lease expired"},
        headers={"Authorization": "Bearer sk-bob"},
    )
    taken = client.post(
        "/api/task-runs/task-expired/takeover",
        json={"reason": "lease expired"},
        headers={"Authorization": "Bearer sk-alice"},
    )

    assert denied.status_code == 404
    assert taken.status_code == 200
    body = taken.json()
    assert body["schema"] == "octopus.task_run_takeover.v1"
    assert body["task_run"]["status"] == "running"
    assert body["task_run"]["lease"]["holder_id"] == "operator"
    assert body["task_run"]["metadata"]["takeover_by"] == "alice"
    assert body["task_run"]["metadata"]["takeover_reason"] == "lease expired"
    assert body["task_run"]["metadata"]["attempt_count"] == 1
    assert body["lease_health"]["state"] == "ok"
    assert body["lease_health"]["recommended_action"] == "monitor"


def test_task_runs_router_rejects_takeover_of_live_lease(tmp_path):
    path = tmp_path / "task_runs.json"
    worker_a = TaskSupervisor.from_path(path, holder_id="worker-a", lease_ttl_seconds=30)
    operator = TaskSupervisor.from_path(path, holder_id="operator", lease_ttl_seconds=30)
    worker_a.start_task(task_id="task-live", kind="loop")

    app = FastAPI()
    app.include_router(create_task_runs_router(supervisor=operator))
    client = TestClient(app)

    response = client.post(
        "/api/task-runs/task-live/takeover",
        json={"reason": "try takeover"},
    )

    assert response.status_code == 409
    assert "already leased by" in response.json()["detail"]


def test_task_runs_router_surfaces_restart_audit_and_recovery_health(tmp_path):
    supervisor = TaskSupervisor.from_path(tmp_path / "task_runs.json", holder_id="worker-a")
    supervisor.start_task(task_id="task-retry", kind="loop", owner_id="alice")
    supervisor.transition(
        "task-retry",
        TaskRunStatus.FAILED,
        reason="verifier failed",
        checkpoint_id="ckpt-failed",
    )
    supervisor.start_task(task_id="task-retry", kind="loop")

    app = FastAPI()
    app.include_router(create_task_runs_router(supervisor=supervisor))
    client = TestClient(app)

    listed = client.get("/api/task-runs", params={"owner_id": "alice"})
    detail = client.get("/api/task-runs/task-retry")

    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["task_run"]["metadata"]["restart"] is True
    assert item["task_run"]["metadata"]["restart_from_checkpoint_id"] == "ckpt-failed"
    assert item["lease_health"]["state"] == "ok"
    assert item["lease_health"]["recommended_action"] == "monitor"

    assert detail.status_code == 200
    body = detail.json()
    assert body["task_run"]["metadata"]["restart_events"][-1]["previous_status"] == "failed"
    assert body["lease_health"]["state"] == "ok"

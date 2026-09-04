from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from runtime.memory.cowork.collaboration_store import CollaborationStore


def _store(tmp_path):
    return CollaborationStore(base_dir=tmp_path / "cowork")


def test_run_lifecycle_is_durable_and_result_is_idempotent(tmp_path) -> None:
    store = _store(tmp_path)
    created = store.create_collaboration_run(
        run_id="run-1",
        session_id="thread-1",
        room_id="room-1",
        turn_id="turn-1",
        kind="group_fanout",
        input={"message": "评审方案"},
    )
    assert created["status"] == "queued"

    claimed = store.claim_collaboration_run("run-1", worker_id="worker-a", lease_seconds=30)
    assert claimed["status"] == "running"
    assert claimed["attempt"] == 1
    assert claimed["lease_owner"] == "worker-a"
    assert store.claim_collaboration_run("run-1", worker_id="worker-a") == claimed
    assert len(store.collaboration_run_events("run-1")) == 2

    result = {"answer": "采用 A", "evidence": ["test:42"]}
    completed = store.transition_collaboration_run(
        "run-1",
        status="completed",
        result=result,
        worker_id="worker-a",
    )
    assert completed["status"] == "completed"
    assert completed["result"] == result
    assert len(completed["result_sha256"]) == 64
    assert completed["lease_owner"] is None

    # Retrying delivery with the exact terminal result is a no-op; restart and
    # readback prove the state is not process-local.
    assert store.transition_collaboration_run(
        "run-1", status="completed", result=result
    ) == completed
    reopened = _store(tmp_path)
    assert reopened.collaboration_run("run-1") == completed
    assert [event["event_type"] for event in reopened.collaboration_run_events("run-1")] == [
        "created",
        "claimed",
        "completed",
    ]


def test_terminal_result_cannot_be_silently_replaced(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_collaboration_run(run_id="run-immutable", session_id="thread-1", kind="team")
    store.claim_collaboration_run("run-immutable", worker_id="worker-a")
    store.transition_collaboration_run(
        "run-immutable", status="completed", result={"value": 1}, worker_id="worker-a"
    )

    with pytest.raises(ValueError, match="immutable"):
        store.transition_collaboration_run(
            "run-immutable", status="completed", result={"value": 2}
        )


def test_live_lease_blocks_second_worker_and_expired_run_is_recoverable(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_collaboration_run(run_id="run-lease", session_id="thread-1", kind="team")
    store.claim_collaboration_run("run-lease", worker_id="worker-a", lease_seconds=30)

    with pytest.raises(RuntimeError, match="another worker"):
        store.claim_collaboration_run("run-lease", worker_id="worker-b")
    assert store.recoverable_collaboration_runs() == []

    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with store._lock, store._connect() as conn:
        conn.execute(
            "UPDATE collaboration_runs SET lease_expires_at=? WHERE run_id=?",
            (expired, "run-lease"),
        )
    recoverable = store.recoverable_collaboration_runs()
    assert [run["run_id"] for run in recoverable] == ["run-lease"]

    reclaimed = store.claim_collaboration_run("run-lease", worker_id="worker-b")
    assert reclaimed["attempt"] == 2
    assert reclaimed["lease_owner"] == "worker-b"
    assert store.collaboration_run_events("run-lease")[-1]["event_type"] == "reclaimed"


def test_illegal_transition_and_foreign_lease_are_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_collaboration_run(run_id="run-guard", session_id="thread-1", kind="team")
    with pytest.raises(ValueError, match="illegal"):
        store.transition_collaboration_run("run-guard", status="completed", result={"ok": True})

    store.claim_collaboration_run("run-guard", worker_id="worker-a")
    with pytest.raises(RuntimeError, match="another worker"):
        store.transition_collaboration_run(
            "run-guard", status="failed", error="boom", worker_id="worker-b"
        )


def test_runs_for_session_filters_status_and_never_crosses_sessions(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_collaboration_run(run_id="run-a", session_id="thread-a", kind="team")
    store.create_collaboration_run(run_id="run-b", session_id="thread-a", kind="team")
    store.create_collaboration_run(run_id="run-other", session_id="thread-b", kind="team")
    store.claim_collaboration_run("run-b", worker_id="worker-a")

    assert {run["run_id"] for run in store.collaboration_runs_for_session("thread-a")} == {
        "run-a",
        "run-b",
    }
    assert [
        run["run_id"]
        for run in store.collaboration_runs_for_session("thread-a", statuses=["running"])
    ] == ["run-b"]
    with pytest.raises(ValueError, match="invalid"):
        store.collaboration_runs_for_session("thread-a", statuses=["made-up"])


def test_startup_reconciliation_turns_expired_worker_into_resumable_interruption(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    store.create_collaboration_run(
        run_id="run-orphan",
        session_id="thread-a",
        kind="coordinated_execution",
        input={"objective": "finish report"},
    )
    store.claim_collaboration_run("run-orphan", worker_id="dead-process")
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with store._lock, store._connect() as conn:
        conn.execute(
            "UPDATE collaboration_runs SET lease_expires_at=? WHERE run_id=?",
            (expired, "run-orphan"),
        )

    result = store.reconcile_expired_collaboration_runs()

    assert result["interrupted"] == 1
    run = store.collaboration_run("run-orphan")
    assert run["status"] == "interrupted"
    assert run["lease_owner"] is None
    assert "lease expired" in run["error"]
    assert [item["run_id"] for item in store.recoverable_collaboration_runs()] == [
        "run-orphan"
    ]
    assert store.collaboration_run_events("run-orphan")[-1] == {
        "schema": "octopus.collaboration_run_event.v1",
        "run_id": "run-orphan",
        "seq": 3,
        "event_type": "lease_expired",
        "status": "interrupted",
        "payload": {
            "previous_lease_owner": "dead-process",
            "previous_lease_expires_at": expired,
        },
        "created_at": store.collaboration_run_events("run-orphan")[-1]["created_at"],
    }
    # Reconciliation is idempotent on repeated startup hooks.
    assert store.reconcile_expired_collaboration_runs()["interrupted"] == 0

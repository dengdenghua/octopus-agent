from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from runtime.memory.cowork.collaboration_store import CollaborationStore


def _store(tmp_path):
    return CollaborationStore(base_dir=tmp_path / "cowork")


def _run(store: CollaborationStore, run_id: str = "run-collector") -> None:
    store.create_collaboration_run(
        run_id=run_id,
        session_id="thread-collector",
        kind="group_fanout",
    )
    store.claim_collaboration_run(run_id, worker_id="coordinator")


def test_all_collector_survives_restart_and_preserves_roster_order(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    created = store.create_collaboration_collector(
        run_id="run-collector",
        child_ids=["raven", "zero", "luna"],
    )
    assert created["status"] == "collecting"
    assert created["completion_target"] == 3

    store.record_collaboration_collector_result(
        "run-collector", child_id="zero", status="failed", result={"error": "timeout"}
    )
    store.record_collaboration_collector_result(
        "run-collector", child_id="raven", status="success", result={"reply": "A"}
    )
    settled = store.record_collaboration_collector_result(
        "run-collector", child_id="luna", status="success", result={"reply": "B"}
    )
    assert settled["status"] == "completed"
    assert settled["policy_satisfied"] is True
    assert settled["success_count"] == 2
    assert [item["child_id"] for item in settled["results"]] == ["raven", "zero", "luna"]

    reopened = _store(tmp_path)
    assert reopened.collaboration_collector("run-collector") == settled
    assert [event["event_type"] for event in reopened.collaboration_run_events("run-collector")] == [
        "created",
        "claimed",
        "collector_created",
        "collector_child_recorded",
        "collector_child_recorded",
        "collector_child_recorded",
    ]


def test_duplicate_child_result_is_idempotent_but_conflict_is_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["a", "b"])
    first = store.record_collaboration_collector_result(
        "run-collector", child_id="a", status="success", result={"answer": 1}
    )
    duplicate = store.record_collaboration_collector_result(
        "run-collector", child_id="a", status="success", result={"answer": 1}
    )
    assert duplicate == first
    assert len(store.collaboration_run_events("run-collector")) == 4
    with pytest.raises(ValueError, match="immutable"):
        store.record_collaboration_collector_result(
            "run-collector", child_id="a", status="success", result={"answer": 2}
        )


@pytest.mark.parametrize(
    ("policy", "quorum", "outcomes", "expected_status", "cancelled"),
    [
        ("first_completed", None, [("a", "failed")], "completed", ["b", "c"]),
        ("first_success", None, [("a", "failed"), ("b", "success")], "completed", ["c"]),
        ("quorum", 2, [("a", "success"), ("b", "success")], "completed", ["c"]),
        ("quorum", 3, [("a", "failed")], "failed", ["b", "c"]),
    ],
)
def test_collector_completion_policies_settle_and_request_cancellation(
    tmp_path,
    policy,
    quorum,
    outcomes,
    expected_status,
    cancelled,
) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(
        run_id="run-collector",
        child_ids=["a", "b", "c"],
        completion_policy=policy,
        quorum=quorum,
    )
    snapshot = None
    for child_id, status in outcomes:
        snapshot = store.record_collaboration_collector_result(
            "run-collector", child_id=child_id, status=status, result={"child": child_id}
        )
    assert snapshot is not None
    assert snapshot["status"] == expected_status
    assert snapshot["cancellation_requested_child_ids"] == cancelled
    assert snapshot["remaining_child_ids"] == cancelled


def test_cross_store_concurrent_results_converge_transactionally(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    child_ids = [f"member-{index}" for index in range(12)]
    store.create_collaboration_collector(run_id="run-collector", child_ids=child_ids)

    def record(child_id: str) -> None:
        # Separate instances model workers in different request/process scopes;
        # BEGIN IMMEDIATE, not the Python lock, provides serialization.
        worker_store = _store(tmp_path)
        worker_store.record_collaboration_collector_result(
            "run-collector",
            child_id=child_id,
            status="success",
            result={"reply": child_id},
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(record, child_ids))

    settled = _store(tmp_path).collaboration_collector("run-collector")
    assert settled is not None
    assert settled["status"] == "completed"
    assert settled["completed_count"] == 12
    assert settled["success_count"] == 12
    assert settled["remaining_count"] == 0


def test_collector_rejects_unregistered_or_late_children(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(
        run_id="run-collector",
        child_ids=["a", "b"],
        completion_policy="first_success",
    )
    with pytest.raises(ValueError, match="not registered"):
        store.record_collaboration_collector_result(
            "run-collector", child_id="other", status="success", result={}
        )
    store.record_collaboration_collector_result(
        "run-collector", child_id="a", status="success", result={"answer": "done"}
    )
    with pytest.raises(ValueError, match="already settled"):
        store.record_collaboration_collector_result(
            "run-collector", child_id="b", status="success", result={"answer": "late"}
        )


def test_parent_failure_closes_incomplete_collector_idempotently(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["a", "b"])
    store.record_collaboration_collector_result(
        "run-collector", child_id="a", status="failed", result={"error": "provider"}
    )

    closed = store.close_collaboration_collector(
        "run-collector", status="failed", reason="parent failed"
    )
    assert closed is not None
    assert closed["status"] == "failed"
    assert closed["policy_satisfied"] is False
    assert closed["cancellation_requested_child_ids"] == ["b"]
    events = len(store.collaboration_run_events("run-collector"))
    assert store.close_collaboration_collector("run-collector", status="failed") == closed
    assert len(store.collaboration_run_events("run-collector")) == events


def test_reopen_retries_only_failed_lanes_without_losing_audit_history(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["a", "b"])
    store.record_collaboration_collector_result(
        "run-collector", child_id="a", status="failed", result={"error": "timeout"}
    )
    store.record_collaboration_collector_result(
        "run-collector", child_id="b", status="success", result={"reply": "B"}
    )

    reopened = store.reopen_collaboration_collector("run-collector")
    assert reopened["generation"] == 2
    assert reopened["status"] == "collecting"
    assert reopened["active_retry_child_ids"] == ["a"]
    assert reopened["remaining_child_ids"] == ["a"]
    assert reopened["results"][0]["attempt"] == 1

    settled = store.record_collaboration_collector_result(
        "run-collector", child_id="a", status="success", result={"reply": "A2"}
    )
    assert settled["status"] == "completed"
    assert settled["success_count"] == 2
    assert {item["attempt"] for item in settled["results"]} == {2, 1}
    assert len(store.collaboration_run_events("run-collector")) == 7

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from runtime.memory.cowork.collaboration_collectors import (
    CollaborationSteeringConflictError,
)
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
    assert [
        event["event_type"] for event in reopened.collaboration_run_events("run-collector")
    ] == [
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


def test_member_steering_is_ordered_durable_and_cursor_readable(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["coder", "reviewer"])

    first = store.submit_collaboration_collector_steering(
        "run-collector",
        child_id="coder",
        text="先修复竞态",
        actor_id="owner",
    )
    second = _store(tmp_path).submit_collaboration_collector_steering(
        "run-collector",
        child_id="coder",
        text="再补跨进程测试",
        actor_id="owner",
    )

    assert first["steering"]["seq"] == 1
    assert second["steering"]["seq"] == 2
    assert second["collector"]["revision"] == 3
    restarted = _store(tmp_path)
    assert [
        row["text"]
        for row in restarted.collaboration_collector_steering(
            "run-collector", child_id="coder", generation=1
        )
    ] == ["先修复竞态", "再补跨进程测试"]
    assert [
        row["text"]
        for row in restarted.collaboration_collector_steering(
            "run-collector", child_id="coder", generation=1, after_seq=1
        )
    ] == ["再补跨进程测试"]
    assert (
        restarted.collaboration_collector_steering(
            "run-collector", child_id="reviewer", generation=1
        )
        == []
    )
    assert [event["event_type"] for event in restarted.collaboration_run_events("run-collector")][
        -2:
    ] == ["collector_child_steered", "collector_child_steered"]


def test_concurrent_member_steering_has_one_monotonic_sequence(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["coder"])
    stores = [_store(tmp_path) for _ in range(8)]
    barrier = threading.Barrier(len(stores))

    def submit(index: int) -> tuple[int, str]:
        barrier.wait(timeout=5)
        item = stores[index].submit_collaboration_collector_steering(
            "run-collector",
            child_id="coder",
            text=f"correction-{index}",
            actor_id=f"owner-{index}",
        )["steering"]
        return int(item["seq"]), str(item["text"])

    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        submitted = list(pool.map(submit, range(len(stores))))

    assert sorted(seq for seq, _text in submitted) == list(range(1, 9))
    rows = _store(tmp_path).collaboration_collector_steering(
        "run-collector",
        child_id="coder",
        generation=1,
    )
    assert [row["seq"] for row in rows] == list(range(1, 9))
    assert {row["text"] for row in rows} == {f"correction-{index}" for index in range(8)}


def test_member_steering_rejects_unknown_or_settled_child(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["coder"])
    with pytest.raises(ValueError, match="not registered"):
        store.submit_collaboration_collector_steering(
            "run-collector", child_id="other", text="change"
        )
    store.record_collaboration_collector_result(
        "run-collector", child_id="coder", status="success", result={"reply": "done"}
    )
    with pytest.raises(ValueError, match="not accepting"):
        store.submit_collaboration_collector_steering(
            "run-collector", child_id="coder", text="too late"
        )


def test_member_result_is_fenced_by_latest_accepted_steering(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["coder"])
    store.submit_collaboration_collector_steering(
        "run-collector", child_id="coder", text="new requirement"
    )

    with pytest.raises(CollaborationSteeringConflictError):
        store.record_collaboration_collector_result(
            "run-collector",
            child_id="coder",
            status="success",
            result={"reply": "obsolete"},
            expected_generation=1,
            expected_steering_seq=0,
        )

    settled = store.record_collaboration_collector_result(
        "run-collector",
        child_id="coder",
        status="success",
        result={"reply": "corrected"},
        expected_generation=1,
        expected_steering_seq=1,
    )
    assert settled["status"] == "completed"


def test_collector_archive_redacts_steering_text_but_keeps_audit_hash(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["coder"])
    store.submit_collaboration_collector_steering(
        "run-collector", child_id="coder", text="sensitive correction"
    )
    store.record_collaboration_collector_result(
        "run-collector", child_id="coder", status="success", result={"reply": "done"}
    )
    store.transition_collaboration_run("run-collector", status="completed")
    store.archive_collaboration_collectors(["run-collector"])

    steering = store.collaboration_collector_steering(
        "run-collector", child_id="coder", generation=1
    )
    assert len(steering) == 1
    assert steering[0]["archived"] is True
    assert steering[0]["text_chars"] == len("sensitive correction")
    assert len(steering[0]["text_sha256"]) == 64
    assert "text" not in steering[0]

    with sqlite3.connect(store._db) as conn:  # noqa: SLF001 - retention storage proof
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM collaboration_collector_steering WHERE run_id=?",
                ("run-collector",),
            ).fetchone()[0]
            == 0
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


def test_failed_child_can_retry_without_erasing_previous_attempt(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["a", "b"])
    store.record_collaboration_collector_result(
        "run-collector", child_id="a", status="failed", result={"error": "first"}
    )
    store.record_collaboration_collector_result(
        "run-collector", child_id="b", status="success", result={"answer": "stable"}
    )

    with pytest.raises(ValueError, match="already has a successful result"):
        store.reopen_collaboration_collector("run-collector", child_ids=["b"])

    reopened = store.reopen_collaboration_collector("run-collector")
    assert reopened["status"] == "collecting"
    assert reopened["generation"] == 2
    assert reopened["active_retry_child_ids"] == ["a"]
    assert reopened["remaining_child_ids"] == ["a"]
    assert reopened["success_count"] == 1
    assert reopened["completed_count"] == 1
    assert (
        next(item for item in reopened["results"] if item["child_id"] == "a")["pending_retry"]
        is True
    )

    settled = store.record_collaboration_collector_result(
        "run-collector", child_id="a", status="success", result={"answer": "recovered"}
    )
    assert settled["status"] == "completed"
    assert settled["success_count"] == 2
    assert settled["attempt_count"] == 3
    assert next(item for item in settled["results"] if item["child_id"] == "a")["attempt"] == 2
    attempts = store.collaboration_collector_attempts("run-collector")
    assert [(item["child_id"], item["attempt"], item["status"]) for item in attempts] == [
        ("a", 1, "failed"),
        ("a", 2, "success"),
        ("b", 1, "success"),
    ]
    assert [event["event_type"] for event in store.collaboration_run_events("run-collector")][
        -2:
    ] == ["collector_reopened", "collector_child_recorded"]


def test_terminal_collector_can_prebind_next_retry_generation(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["a", "b"])
    store.record_collaboration_collector_result(
        "run-collector", child_id="a", status="failed", result={"error": "timeout"}
    )
    store.record_collaboration_collector_result(
        "run-collector", child_id="b", status="success", result={"reply": "kept"}
    )

    binding = store.bind_collaboration_collector_retry_task(
        "run-collector",
        child_id="a",
        task_id="retry-task-a",
    )

    assert binding["generation"] == 2
    assert store.collaboration_collector_retry_task("retry-task-a") == binding
    reopened = store.reopen_collaboration_collector("run-collector", child_ids=["a"])
    assert reopened["generation"] == 2
    assert reopened["active_retry_child_ids"] == ["a"]


def test_terminal_collector_refuses_prebinding_successful_child(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["a"])
    store.record_collaboration_collector_result(
        "run-collector", child_id="a", status="success", result={"reply": "done"}
    )

    with pytest.raises(ValueError, match="does not have a retryable result"):
        store.bind_collaboration_collector_retry_task(
            "run-collector",
            child_id="a",
            task_id="retry-task-a",
        )


def test_retry_lane_has_one_transactional_winner_across_store_instances(tmp_path) -> None:
    first = _store(tmp_path)
    _run(first)
    first.create_collaboration_collector(run_id="run-collector", child_ids=["a"])
    first.record_collaboration_collector_result(
        "run-collector", child_id="a", status="failed", result={"error": "timeout"}
    )
    stores = [first, _store(tmp_path)]

    def bind(index: int) -> str:
        try:
            stores[index].bind_collaboration_collector_retry_task(
                "run-collector",
                child_id="a",
                task_id=f"retry-task-{index}",
            )
        except ValueError:
            return "occupied"
        return "bound"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(bind, range(2)))

    assert sorted(outcomes) == ["bound", "occupied"]


def test_discard_retry_bindings_releases_unactivated_lane(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["a"])
    store.record_collaboration_collector_result(
        "run-collector", child_id="a", status="failed", result={"error": "timeout"}
    )
    store.bind_collaboration_collector_retry_task(
        "run-collector",
        child_id="a",
        task_id="abandoned-task",
    )

    assert store.discard_collaboration_collector_retry_tasks(["abandoned-task"]) == 1
    assert store.collaboration_collector_retry_task("abandoned-task") is None
    replacement = store.bind_collaboration_collector_retry_task(
        "run-collector",
        child_id="a",
        task_id="replacement-task",
    )
    assert replacement["generation"] == 2


def test_pre_attempt_collector_schema_migrates_without_losing_results(tmp_path) -> None:
    base = tmp_path / "cowork"
    base.mkdir()
    db = base / "collaboration.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE collaboration_collectors (
                run_id TEXT PRIMARY KEY,
                completion_policy TEXT NOT NULL,
                completion_target INTEGER NOT NULL,
                expected_json TEXT NOT NULL,
                cancelled_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL,
                policy_satisfied INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                settled_at TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE collaboration_collector_results (
                run_id TEXT NOT NULL,
                child_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT NOT NULL,
                result_sha256 TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (run_id, child_id)
            );
            INSERT INTO collaboration_collectors VALUES
                ('legacy-run','all',1,'["a"]','[]','completed',1,2,'t','t','t');
            INSERT INTO collaboration_collector_results VALUES
                ('legacy-run','a',0,'success','{"answer":"kept"}','digest','t');
            """
        )

    store = CollaborationStore(base_dir=base)
    collector = store.collaboration_collector("legacy-run")
    assert collector is not None
    assert collector["generation"] == 1
    assert collector["results"][0]["attempt"] == 1
    assert collector["results"][0]["result"] == {"answer": "kept"}


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


def test_terminal_collector_archive_compacts_bodies_but_keeps_audit_summary(tmp_path) -> None:
    store = _store(tmp_path)
    _run(store)
    store.create_collaboration_collector(run_id="run-collector", child_ids=["a", "b"])
    store.record_collaboration_collector_result(
        "run-collector",
        child_id="a",
        status="failed",
        result={"error": "private provider failure body"},
    )
    store.record_collaboration_collector_result(
        "run-collector",
        child_id="b",
        status="success",
        result={"reply": "large private answer body"},
    )
    store.transition_collaboration_run("run-collector", status="completed")
    store.bind_collaboration_collector_retry_task(
        "run-collector",
        child_id="a",
        task_id="obsolete-retry-binding",
    )

    archived = store.archive_collaboration_collectors(
        ["run-collector"],
        reason="retention test",
    )[0]

    assert archived["archived"] is True
    assert archived["status"] == "completed"
    assert archived["attempt_count"] == 2
    assert archived["success_count"] == 1
    assert archived["failure_count"] == 1
    assert [item["child_id"] for item in archived["results"]] == ["a", "b"]
    assert all(item["result"] == {"archived": True} for item in archived["results"])
    attempts = store.collaboration_collector_attempts("run-collector")
    assert len(attempts) == 2
    assert all(item["result"] == {"archived": True} for item in attempts)
    assert store.collaboration_collector_retry_task("obsolete-retry-binding") is None
    with pytest.raises(ValueError, match="archived"):
        store.reopen_collaboration_collector("run-collector")

    with sqlite3.connect(tmp_path / "cowork" / "collaboration.db") as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM collaboration_collector_results WHERE run_id='run-collector'"
            ).fetchone()[0]
            == 0
        )
        archive_json = conn.execute(
            "SELECT archive_json FROM collaboration_collectors WHERE run_id='run-collector'"
        ).fetchone()[0]
    assert "private provider failure body" not in archive_json
    assert "large private answer body" not in archive_json
    assert store.collaboration_run_events("run-collector")[-1]["event_type"] == "collector_archived"


def test_collector_retention_archives_expired_terminal_runs_and_pins_active_work(tmp_path) -> None:
    store = _store(tmp_path)
    for run_id in ("expired-run", "recent-run", "active-run"):
        _run(store, run_id)
        store.create_collaboration_collector(run_id=run_id, child_ids=["a"])
    store.record_collaboration_collector_result(
        "expired-run", child_id="a", status="success", result={"reply": "old"}
    )
    store.record_collaboration_collector_result(
        "recent-run", child_id="a", status="success", result={"reply": "new"}
    )
    store.transition_collaboration_run("expired-run", status="completed")
    store.transition_collaboration_run("recent-run", status="completed")
    with sqlite3.connect(tmp_path / "cowork" / "collaboration.db") as conn:
        conn.execute(
            "UPDATE collaboration_collectors SET updated_at='2020-01-01T00:00:00+00:00' "
            "WHERE run_id='expired-run'"
        )

    result = store.apply_collaboration_collector_retention(
        session_id="thread-collector",
        ttl_seconds=24 * 60 * 60,
        max_collectors_per_session=0,
    )

    assert result == {"archived": 1, "run_ids": ["expired-run"]}
    assert store.collaboration_collector("expired-run")["archived"] is True
    assert store.collaboration_collector("recent-run")["archived"] is False
    assert store.collaboration_collector("active-run")["status"] == "collecting"
    assert store.collaboration_collector("active-run")["archived"] is False

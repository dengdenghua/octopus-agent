from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from runtime.memory.cowork.collaboration_store import CollaborationStore
from runtime.memory.threads.event_log import EventLog, thread_log_path
from runtime.protocol import AgentMessageItem, ItemStatus, Turn
from runtime.sensing.gateway.collaboration_delivery_outbox import (
    drain_collaboration_delivery_outbox,
    persist_collaboration_delivery,
)


def _store(tmp_path):
    return CollaborationStore(base_dir=tmp_path / "cowork")


def _payload(item_id: str = "reply-1") -> dict:
    item = AgentMessageItem(id=item_id, text="可靠结果", status=ItemStatus.COMPLETED)
    return {
        "schema": "octopus.collaboration_delivery_payload.v1",
        "item": item.model_dump(by_alias=True, mode="json"),
    }


def _log(tmp_path) -> EventLog:
    logs_root = tmp_path / "threads"
    log = EventLog(thread_log_path(logs_root, "thread-1"))
    log.thread_started("thread-1")
    log.turn_started("thread-1", Turn(id="turn-1", threadId="thread-1"))
    return log


def test_delivery_lifecycle_is_idempotent_and_payload_is_immutable(tmp_path) -> None:
    store = _store(tmp_path)
    payload = _payload()
    created = store.enqueue_collaboration_delivery(
        delivery_id="delivery-1",
        run_id="run-1",
        session_id="thread-1",
        turn_id="turn-1",
        payload=payload,
    )
    assert created["status"] == "pending"
    assert store.enqueue_collaboration_delivery(
        delivery_id="delivery-1",
        run_id="run-1",
        session_id="thread-1",
        turn_id="turn-1",
        payload=payload,
    ) == created
    with pytest.raises(ValueError, match="different payload"):
        store.enqueue_collaboration_delivery(
            delivery_id="delivery-1",
            run_id="run-1",
            session_id="thread-1",
            turn_id="turn-1",
            payload=_payload("reply-2"),
        )

    delivered_item = persist_collaboration_delivery(
        store,
        created,
        log=_log(tmp_path),
        worker_id="worker-a",
    )
    assert delivered_item.id == "reply-1"
    delivered = store.collaboration_delivery("delivery-1")
    assert delivered["status"] == "delivered"
    assert delivered["attempt"] == 1
    assert delivered["delivered_at"]
    assert [event["event_type"] for event in store.collaboration_delivery_events("delivery-1")] == [
        "enqueued",
        "claimed",
        "delivered",
    ]


def test_failed_delivery_uses_backoff_then_allows_manual_retry_and_dismiss(tmp_path) -> None:
    store = _store(tmp_path)
    store.enqueue_collaboration_delivery(
        delivery_id="delivery-retry",
        session_id="thread-1",
        turn_id="turn-1",
        payload=_payload(),
        max_attempts=3,
    )
    store.claim_collaboration_delivery("delivery-retry", worker_id="worker-a")
    retrying = store.mark_collaboration_delivery_failed(
        "delivery-retry", worker_id="worker-a", error="disk unavailable"
    )
    assert retrying["status"] == "retry_wait"
    assert retrying["next_attempt_at"] > retrying["updated_at"]
    with pytest.raises(RuntimeError, match="not due"):
        store.claim_collaboration_delivery("delivery-retry", worker_id="worker-b")

    pending = store.retry_collaboration_delivery("delivery-retry")
    assert pending["status"] == "pending"
    assert pending["attempt"] == 0
    dismissed = store.dismiss_collaboration_delivery("delivery-retry")
    assert dismissed["status"] == "dismissed"
    with pytest.raises(ValueError, match="terminal"):
        store.claim_collaboration_delivery("delivery-retry", worker_id="worker-b")


def test_expired_lease_is_recovered_and_at_least_once_replay_stays_one_item(tmp_path) -> None:
    store = _store(tmp_path)
    log = _log(tmp_path)
    delivery = store.enqueue_collaboration_delivery(
        delivery_id="delivery-crash",
        session_id="thread-1",
        turn_id="turn-1",
        payload=_payload("stable-reply"),
    )
    claimed = store.claim_collaboration_delivery("delivery-crash", worker_id="dead-worker")
    item = AgentMessageItem.model_validate(claimed["payload"]["item"])
    # Simulate a crash after both durable JSONL writes but before the SQLite ack.
    log.item_started("thread-1", "turn-1", item, durable=True)
    log.item_completed("thread-1", "turn-1", item, durable=True)
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with store._lock, store._connect() as conn:
        conn.execute(
            "UPDATE collaboration_deliveries SET lease_expires_at=? WHERE delivery_id=?",
            (expired, "delivery-crash"),
        )

    assert store.reconcile_collaboration_deliveries() == {"reclaimed": 1, "failed": 0}
    result = drain_collaboration_delivery_outbox(
        store,
        logs_root=tmp_path / "threads",
        session_id="thread-1",
    )
    assert result == {"due": 1, "delivered": 1, "deferred": 0}
    replayed = log.replay()
    assert len(replayed) == 1
    assert [entry.id for entry in replayed[0].items] == ["stable-reply"]
    assert delivery["payload_sha256"] == store.collaboration_delivery("delivery-crash")[
        "payload_sha256"
    ]


def test_session_listing_never_crosses_thread_boundary(tmp_path) -> None:
    store = _store(tmp_path)
    for delivery_id, session_id in (("a", "thread-a"), ("b", "thread-b")):
        store.enqueue_collaboration_delivery(
            delivery_id=delivery_id,
            session_id=session_id,
            turn_id=f"turn-{delivery_id}",
            payload=_payload(f"item-{delivery_id}"),
        )
    assert [
        row["delivery_id"] for row in store.collaboration_deliveries_for_session("thread-a")
    ] == ["a"]
    with pytest.raises(ValueError, match="invalid"):
        store.collaboration_deliveries_for_session("thread-a", statuses=["unknown"])

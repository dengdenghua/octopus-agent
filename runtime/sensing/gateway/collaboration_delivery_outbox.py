"""Replay collaboration delivery outbox rows into durable thread logs."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from runtime.memory.threads.event_log import EventLog, thread_log_path
from runtime.protocol import AgentMessageItem

_logger = logging.getLogger(__name__)


def persist_collaboration_delivery(
    store: Any,
    delivery: dict[str, Any],
    *,
    log: EventLog,
    worker_id: str,
) -> AgentMessageItem:
    """Write one claimed row to the event log and acknowledge it atomically enough.

    The JSONL log and SQLite outbox cannot share one transaction.  We therefore
    use at-least-once delivery: the stable protocol item id makes a replay after
    a crash converge to one visible item.
    """

    delivery_id = str(delivery.get("delivery_id") or "")
    claimed = store.claim_collaboration_delivery(delivery_id, worker_id=worker_id)
    payload = claimed.get("payload")
    raw_item = payload.get("item") if isinstance(payload, dict) else None
    if not isinstance(raw_item, dict):
        store.mark_collaboration_delivery_failed(
            delivery_id,
            worker_id=worker_id,
            error="delivery payload has no item",
        )
        raise ValueError("delivery payload has no item")
    try:
        item = AgentMessageItem.model_validate(raw_item)
        log.item_started(
            str(claimed["session_id"]),
            str(claimed["turn_id"]),
            item,
            durable=True,
        )
        log.item_completed(
            str(claimed["session_id"]),
            str(claimed["turn_id"]),
            item,
            durable=True,
        )
    except Exception as exc:
        store.mark_collaboration_delivery_failed(
            delivery_id,
            worker_id=worker_id,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    store.mark_collaboration_delivery_delivered(delivery_id, worker_id=worker_id)
    return item


def drain_collaboration_delivery_outbox(
    store: Any,
    *,
    logs_root: Path | str,
    session_id: str = "",
    limit: int = 100,
    worker_id: str = "",
) -> dict[str, int]:
    """Deliver all currently due rows; retain failures for scheduled retry."""

    worker = worker_id or f"delivery-recovery:{os.getpid()}"
    delivered = 0
    deferred = 0
    rows = store.due_collaboration_deliveries(session_id=session_id, limit=limit)
    for row in rows:
        thread_id = str(row.get("session_id") or "")
        try:
            persist_collaboration_delivery(
                store,
                row,
                log=EventLog(thread_log_path(logs_root, thread_id)),
                worker_id=worker,
            )
            delivered += 1
        except (RuntimeError, ValueError, KeyError, OSError) as exc:
            deferred += 1
            _logger.warning(
                "cowork delivery %s deferred: %s",
                row.get("delivery_id"),
                exc,
            )
    return {"due": len(rows), "delivered": delivered, "deferred": deferred}


__all__ = ["drain_collaboration_delivery_outbox", "persist_collaboration_delivery"]

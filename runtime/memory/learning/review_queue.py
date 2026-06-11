"""Durable human-review queue for TaskRun self-improvement candidates."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.platform.io import atomic_write_json, read_json_with_backup

_SCHEMA = "octopus.review_queue.v1"
_VALID_STATUSES = {"pending", "promoted", "rejected", "archived"}
_DECISIONS = {"promoted", "rejected", "archived"}
_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


class ReviewQueue:
    """Deduplicating review queue before lessons become durable behavior."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def add_from_task_run_review(
        self,
        review: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        payload = self._read()
        items = list(payload.get("items") or [])
        now_text = _iso(now)
        source = _source_from_review(review)
        created = 0
        updated = 0
        touched: list[dict[str, Any]] = []

        for candidate in _items_from_review(review, now_text):
            existing = _find_item(items, candidate["id"])
            if existing is None:
                items.append(candidate)
                touched.append(candidate)
                created += 1
                continue
            _merge_existing_item(existing, candidate, now_text)
            touched.append(existing)
            updated += 1

        payload["items"] = sorted(items, key=_item_sort_key)
        payload["lastUpdated"] = now_text
        self._write(payload)
        return {
            "schema": _SCHEMA,
            "source": source,
            "created": created,
            "updated": updated,
            "items": touched,
            "total": len(payload["items"]),
        }

    def items(
        self,
        *,
        status: str | None = None,
        target_bucket: str | None = None,
        priority: str | None = None,
        source_task_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        rows = list(self._read().get("items") or [])
        if status:
            rows = [row for row in rows if str(row.get("status") or "") == status]
        if target_bucket:
            rows = [
                row
                for row in rows
                if str(row.get("target_bucket") or "") == target_bucket
            ]
        if priority:
            rows = [row for row in rows if str(row.get("priority") or "") == priority]
        if source_task_id:
            wanted = _clean_text(source_task_id, limit=120)
            rows = [
                row
                for row in rows
                if wanted in (row.get("source_task_ids") or [])
            ]
        rows = sorted(rows, key=_item_sort_key)
        total = len(rows)
        return {
            "schema": _SCHEMA,
            "items": rows[offset: offset + limit],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def decide(
        self,
        item_id: str,
        *,
        action: str,
        reason: str = "",
        promoted_to: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized_id = _clean_text(item_id, limit=80)
        decision = _clean_text(action, limit=40).lower()
        if decision not in _DECISIONS:
            raise ValueError("action must be one of: promoted, rejected, archived")

        payload = self._read()
        rows = list(payload.get("items") or [])
        item = _find_item(rows, normalized_id)
        if item is None:
            raise KeyError(normalized_id)

        now_text = _iso(now)
        item["status"] = decision
        item["updated_at"] = now_text
        item["decided_at"] = now_text
        item["decision_reason"] = _clean_text(reason, limit=1200)
        item["promoted_to"] = (
            _clean_text(promoted_to, limit=80)
            if decision == "promoted" and promoted_to
            else item.get("target_bucket", "none")
            if decision == "promoted"
            else "none"
        )

        payload["items"] = sorted(rows, key=_item_sort_key)
        payload["lastUpdated"] = now_text
        self._write(payload)
        return {"schema": _SCHEMA, "item": item}

    def summary(self) -> dict[str, Any]:
        rows = list(self._read().get("items") or [])
        by_status = Counter(str(row.get("status") or "pending") for row in rows)
        by_priority = Counter(str(row.get("priority") or "P2") for row in rows)
        by_bucket = Counter(str(row.get("target_bucket") or "experience") for row in rows)
        return {
            "schema": _SCHEMA,
            "total": len(rows),
            "pending_count": by_status.get("pending", 0),
            "by_status": dict(sorted(by_status.items())),
            "by_priority": dict(sorted(by_priority.items())),
            "by_target_bucket": dict(sorted(by_bucket.items())),
            "next_actions": _next_actions(rows),
        }

    def _read(self) -> dict[str, Any]:
        raw = read_json_with_backup(self.path, default=None)
        if not isinstance(raw, dict):
            return _empty_payload()
        return _normalize_payload(raw)

    def _write(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.path, _normalize_payload(payload))


def _empty_payload() -> dict[str, Any]:
    return {
        "schema": _SCHEMA,
        "version": 1,
        "lastUpdated": "",
        "items": [],
    }


def _normalize_payload(raw: dict[str, Any]) -> dict[str, Any]:
    payload = _empty_payload()
    rows: list[dict[str, Any]] = []
    for item in raw.get("items") or []:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), limit=180)
        text = _clean_text(item.get("text"), limit=1200)
        if not title or not text:
            continue
        status = _clean_text(item.get("status"), limit=40) or "pending"
        if status not in _VALID_STATUSES:
            status = "pending"
        source_kind = _clean_text(item.get("source_kind"), limit=80) or "learning_candidate"
        candidate_kind = _clean_text(item.get("candidate_kind"), limit=80) or source_kind
        target_bucket = _clean_text(item.get("target_bucket"), limit=80) or "experience"
        normalized = {
            "id": _clean_text(item.get("id"), limit=80) or _item_id(
                source_kind=source_kind,
                candidate_kind=candidate_kind,
                target_bucket=target_bucket,
                title=title,
                text=text,
            ),
            "created_at": _clean_text(item.get("created_at"), limit=80),
            "updated_at": _clean_text(item.get("updated_at"), limit=80),
            "decided_at": _clean_text(item.get("decided_at"), limit=80),
            "source": _clean_text(item.get("source"), limit=80) or "task_run_review",
            "source_kind": source_kind,
            "candidate_kind": candidate_kind,
            "priority": _priority(item.get("priority")),
            "target_bucket": target_bucket,
            "title": title,
            "text": text,
            "status": status,
            "decision_reason": _clean_text(item.get("decision_reason"), limit=1200),
            "promoted_to": _clean_text(item.get("promoted_to"), limit=80) or "none",
            "occurrences": max(1, int(item.get("occurrences") or 1)),
            "last_seen_at": _clean_text(item.get("last_seen_at"), limit=80),
            "source_task_ids": _clean_unique_list(item.get("source_task_ids"), limit=80),
            "thread_ids": _clean_unique_list(item.get("thread_ids"), limit=80),
            "turn_ids": _clean_unique_list(item.get("turn_ids"), limit=80),
            "agent_ids": _clean_unique_list(item.get("agent_ids"), limit=80),
            "tags": _clean_unique_list(item.get("tags"), limit=40),
            "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            "source_hash": _clean_text(item.get("source_hash"), limit=80),
        }
        rows.append(normalized)
    payload.update({
        "schema": _SCHEMA,
        "version": 1,
        "lastUpdated": _clean_text(raw.get("lastUpdated"), limit=80),
        "items": sorted(rows, key=_item_sort_key),
    })
    return payload


def _items_from_review(review: dict[str, Any], now_text: str) -> list[dict[str, Any]]:
    source_task_id = _clean_text(review.get("task_id"), limit=120)
    thread_id = _clean_text(review.get("thread_id"), limit=120)
    turn_id = _clean_text(review.get("turn_id"), limit=120)
    agent_id = _clean_text(review.get("agent_id"), limit=120)
    rows: list[dict[str, Any]] = []
    for item in review.get("learning_candidates") or []:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), limit=180)
        text = _clean_text(item.get("text"), limit=1200)
        if not title or not text:
            continue
        candidate_kind = _clean_text(item.get("kind"), limit=80) or "learning_candidate"
        target_bucket = _clean_text(item.get("memory_bucket"), limit=80) or "experience"
        rows.append(_new_item(
            now_text=now_text,
            source_task_id=source_task_id,
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            source_kind="learning_candidate",
            candidate_kind=candidate_kind,
            priority=_priority(item.get("priority")),
            target_bucket=target_bucket,
            title=title,
            text=text,
            metadata={"candidate": item, "review_status": review.get("status")},
        ))
    for item in review.get("backlog_candidates") or []:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("experiment"), limit=180)
        text = _clean_text(item.get("hypothesis"), limit=1200)
        if not title or not text:
            continue
        rows.append(_new_item(
            now_text=now_text,
            source_task_id=source_task_id,
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            source_kind="backlog_candidate",
            candidate_kind="backlog_candidate",
            priority=_priority(item.get("priority")),
            target_bucket="experiment_backlog",
            title=title,
            text=text,
            metadata={
                "candidate": item,
                "minimal_implementation": _clean_text(
                    item.get("minimal_implementation"),
                    limit=1200,
                ),
                "validation_metric": _clean_text(item.get("validation_metric"), limit=600),
                "review_status": review.get("status"),
            },
        ))
    return rows


def _new_item(
    *,
    now_text: str,
    source_task_id: str,
    thread_id: str,
    turn_id: str,
    agent_id: str,
    source_kind: str,
    candidate_kind: str,
    priority: str,
    target_bucket: str,
    title: str,
    text: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    item_id = _item_id(
        source_kind=source_kind,
        candidate_kind=candidate_kind,
        target_bucket=target_bucket,
        title=title,
        text=text,
    )
    return {
        "id": item_id,
        "created_at": now_text,
        "updated_at": now_text,
        "decided_at": "",
        "source": "task_run_review",
        "source_kind": source_kind,
        "candidate_kind": candidate_kind,
        "priority": priority,
        "target_bucket": target_bucket,
        "title": title,
        "text": text,
        "status": "pending",
        "decision_reason": "",
        "promoted_to": "none",
        "occurrences": 1,
        "last_seen_at": now_text,
        "source_task_ids": [source_task_id] if source_task_id else [],
        "thread_ids": [thread_id] if thread_id else [],
        "turn_ids": [turn_id] if turn_id else [],
        "agent_ids": [agent_id] if agent_id else [],
        "tags": _tags_for(source_kind, candidate_kind, priority, target_bucket),
        "metadata": metadata,
        "source_hash": _source_hash(
            source_kind=source_kind,
            candidate_kind=candidate_kind,
            target_bucket=target_bucket,
            title=title,
            text=text,
        ),
    }


def _merge_existing_item(
    existing: dict[str, Any],
    candidate: dict[str, Any],
    now_text: str,
) -> None:
    existing["updated_at"] = now_text
    existing["last_seen_at"] = now_text
    existing["occurrences"] = int(existing.get("occurrences") or 1) + 1
    existing["priority"] = _higher_priority(existing.get("priority"), candidate.get("priority"))
    for key in ("source_task_ids", "thread_ids", "turn_ids", "agent_ids", "tags"):
        existing[key] = _merge_unique(existing.get(key), candidate.get(key))
    metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
    metadata["last_candidate"] = candidate.get("metadata", {}).get("candidate")
    existing["metadata"] = metadata


def _find_item(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    for item in items:
        if str(item.get("id") or "") == item_id:
            return item
    return None


def _item_id(
    *,
    source_kind: Any,
    candidate_kind: Any,
    target_bucket: Any,
    title: str,
    text: str,
) -> str:
    digest = _source_hash(
        source_kind=source_kind,
        candidate_kind=candidate_kind,
        target_bucket=target_bucket,
        title=title,
        text=text,
    )
    return f"rq_{digest}"


def _source_hash(
    *,
    source_kind: Any,
    candidate_kind: Any,
    target_bucket: Any,
    title: str,
    text: str,
) -> str:
    key = "|".join([
        _clean_text(source_kind, limit=80).casefold(),
        _clean_text(candidate_kind, limit=80).casefold(),
        _clean_text(target_bucket, limit=80).casefold(),
        title.casefold(),
        text.casefold(),
    ])
    return hashlib.blake2b(key.encode("utf-8"), digest_size=10).hexdigest()


def _source_from_review(review: dict[str, Any]) -> dict[str, str]:
    return {
        "task_id": _clean_text(review.get("task_id"), limit=120),
        "thread_id": _clean_text(review.get("thread_id"), limit=120),
        "turn_id": _clean_text(review.get("turn_id"), limit=120),
        "agent_id": _clean_text(review.get("agent_id"), limit=120),
    }


def _item_sort_key(row: dict[str, Any]) -> tuple[int, str, str, str]:
    return (
        _PRIORITY_RANK.get(str(row.get("priority") or "P2"), 2),
        str(row.get("status") or "pending"),
        str(row.get("last_seen_at") or row.get("updated_at") or ""),
        str(row.get("id") or ""),
    )


def _next_actions(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    pending = [row for row in rows if str(row.get("status") or "") == "pending"]
    for row in sorted(pending, key=_item_sort_key)[:8]:
        target = str(row.get("target_bucket") or "experience")
        title = str(row.get("title") or "")
        if target == "experiment_backlog":
            action = f"Promote or reject experiment: {title}"
        else:
            action = f"Promote, reject, or archive learning: {title}"
        actions.append({
            "priority": _priority(row.get("priority")),
            "item_id": str(row.get("id") or ""),
            "target_bucket": target,
            "action": action,
        })
    return actions


def _iso(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


def _clean_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit].rstrip()


def _clean_unique_list(value: Any, *, limit: int) -> list[str]:
    return _merge_unique([], value)[:limit]


def _merge_unique(left: Any, right: Any) -> list[str]:
    out: list[str] = []
    for collection in (left, right):
        if not isinstance(collection, list):
            continue
        for item in collection:
            text = _clean_text(item, limit=160)
            if text and text not in out:
                out.append(text)
    return out


def _priority(value: Any) -> str:
    raw = str(value or "P2").upper()
    return raw if raw in _PRIORITY_RANK else "P2"


def _higher_priority(left: Any, right: Any) -> str:
    left_p = _priority(left)
    right_p = _priority(right)
    return left_p if _PRIORITY_RANK[left_p] <= _PRIORITY_RANK[right_p] else right_p


def _tags_for(
    source_kind: str,
    candidate_kind: str,
    priority: str,
    target_bucket: str,
) -> list[str]:
    tags = [source_kind, candidate_kind, priority, target_bucket]
    return [tag for tag in tags if tag]


__all__ = ["ReviewQueue"]

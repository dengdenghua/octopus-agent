"""Durable ledger for TaskRun review lessons and experiment candidates."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from runtime.platform.io import atomic_write_json, read_json_with_backup

_SCHEMA = "octopus.experience_ledger.v1"
_SUMMARY_SCHEMA = "octopus.experience_weekly_summary.v1"
_VALID_STATUSES = {"active", "archived", "promoted"}
_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


class ExperienceLedger:
    """Append-friendly, deduplicating store for agent self-improvement notes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def add_from_task_run_review(
        self,
        review: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        payload = self._read()
        records = list(payload.get("records") or [])
        now_text = _iso(now)
        source = _source_from_review(review)
        created = 0
        updated = 0
        touched: list[dict[str, Any]] = []

        for candidate in _records_from_review(review, now_text):
            existing = _find_record(records, candidate["id"])
            if existing is None:
                records.append(candidate)
                touched.append(candidate)
                created += 1
                continue
            _merge_existing_record(existing, candidate, now_text)
            touched.append(existing)
            updated += 1

        payload["records"] = sorted(records, key=_record_sort_key)
        payload["lastUpdated"] = now_text
        self._write(payload)
        return {
            "schema": _SCHEMA,
            "source": source,
            "created": created,
            "updated": updated,
            "records": touched,
            "total": len(payload["records"]),
        }

    def records(
        self,
        *,
        status: str | None = None,
        bucket: str | None = None,
        kind: str | None = None,
        priority: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        rows = list(self._read().get("records") or [])
        if status:
            rows = [row for row in rows if str(row.get("status") or "") == status]
        if bucket:
            rows = [row for row in rows if str(row.get("memory_bucket") or "") == bucket]
        if kind:
            rows = [row for row in rows if str(row.get("kind") or "") == kind]
        if priority:
            rows = [row for row in rows if str(row.get("priority") or "") == priority]
        rows = sorted(rows, key=_record_sort_key)
        total = len(rows)
        return {
            "schema": _SCHEMA,
            "records": rows[offset: offset + limit],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def records_for_task(
        self,
        task_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        wanted = _clean_text(task_id, limit=120)
        if not wanted:
            return []
        rows = [
            row for row in self._read().get("records") or []
            if wanted in (row.get("source_task_ids") or [])
        ]
        return sorted(rows, key=_record_sort_key)[:limit]

    def weekly_summary(
        self,
        *,
        week_start: str | date | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        start = _week_start(week_start, now=now)
        end = start + timedelta(days=7)
        rows = [
            row for row in self._read().get("records") or []
            if _within_week(row.get("last_seen_at"), start, end)
        ]
        by_priority = Counter(str(row.get("priority") or "P2") for row in rows)
        by_bucket = Counter(str(row.get("memory_bucket") or "experience") for row in rows)
        by_kind = Counter(str(row.get("kind") or "unknown") for row in rows)
        top_records = sorted(rows, key=_weekly_record_sort_key)[:10]
        return {
            "schema": _SUMMARY_SCHEMA,
            "week_start": start.isoformat(),
            "week_end": end.isoformat(),
            "record_count": len(rows),
            "by_priority": dict(sorted(by_priority.items())),
            "by_bucket": dict(sorted(by_bucket.items())),
            "by_kind": dict(sorted(by_kind.items())),
            "top_records": top_records,
            "next_actions": _next_actions(top_records),
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
        "records": [],
    }


def _normalize_payload(raw: dict[str, Any]) -> dict[str, Any]:
    payload = _empty_payload()
    records: list[dict[str, Any]] = []
    for item in raw.get("records") or []:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), limit=180)
        text = _clean_text(item.get("text"), limit=1200)
        if not title or not text:
            continue
        created_at = _clean_text(item.get("created_at"), limit=80)
        last_seen_at = _clean_text(item.get("last_seen_at"), limit=80) or created_at
        source_task_ids = _clean_unique_list(item.get("source_task_ids"), limit=80)
        thread_ids = _clean_unique_list(item.get("thread_ids"), limit=80)
        turn_ids = _clean_unique_list(item.get("turn_ids"), limit=80)
        agent_ids = _clean_unique_list(item.get("agent_ids"), limit=80)
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        tags = _clean_unique_list(item.get("tags"), limit=40)
        status = str(item.get("status") or "active")
        if status not in _VALID_STATUSES:
            status = "active"
        record = {
            "id": _clean_text(item.get("id"), limit=80) or _record_id(
                kind=item.get("kind"),
                bucket=item.get("memory_bucket"),
                title=title,
                text=text,
            ),
            "created_at": created_at,
            "last_seen_at": last_seen_at,
            "occurrences": max(1, int(item.get("occurrences") or 1)),
            "source": _clean_text(item.get("source"), limit=80) or "task_run_review",
            "source_task_ids": source_task_ids,
            "thread_ids": thread_ids,
            "turn_ids": turn_ids,
            "agent_ids": agent_ids,
            "kind": _clean_text(item.get("kind"), limit=80) or "learning_candidate",
            "priority": _priority(item.get("priority")),
            "memory_bucket": _clean_text(item.get("memory_bucket"), limit=80) or "experience",
            "title": title,
            "text": text,
            "status": status,
            "tags": tags,
            "metadata": metadata,
        }
        records.append(record)
    payload.update({
        "schema": _SCHEMA,
        "version": 1,
        "lastUpdated": _clean_text(raw.get("lastUpdated"), limit=80),
        "records": sorted(records, key=_record_sort_key),
    })
    return payload


def _records_from_review(review: dict[str, Any], now_text: str) -> list[dict[str, Any]]:
    source_task_id = _clean_text(review.get("task_id"), limit=120)
    thread_id = _clean_text(review.get("thread_id"), limit=120)
    turn_id = _clean_text(review.get("turn_id"), limit=120)
    agent_id = _clean_text(review.get("agent_id"), limit=120)
    records: list[dict[str, Any]] = []
    for item in review.get("learning_candidates") or []:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), limit=180)
        text = _clean_text(item.get("text"), limit=1200)
        if not title or not text:
            continue
        kind = _clean_text(item.get("kind"), limit=80) or "learning_candidate"
        bucket = _clean_text(item.get("memory_bucket"), limit=80) or "experience"
        records.append(_new_record(
            now_text=now_text,
            source_task_id=source_task_id,
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            kind=kind,
            priority=_priority(item.get("priority")),
            memory_bucket=bucket,
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
        records.append(_new_record(
            now_text=now_text,
            source_task_id=source_task_id,
            thread_id=thread_id,
            turn_id=turn_id,
            agent_id=agent_id,
            kind="backlog_candidate",
            priority=_priority(item.get("priority")),
            memory_bucket="experiment_backlog",
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
    return records


def _new_record(
    *,
    now_text: str,
    source_task_id: str,
    thread_id: str,
    turn_id: str,
    agent_id: str,
    kind: str,
    priority: str,
    memory_bucket: str,
    title: str,
    text: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": _record_id(kind=kind, bucket=memory_bucket, title=title, text=text),
        "created_at": now_text,
        "last_seen_at": now_text,
        "occurrences": 1,
        "source": "task_run_review",
        "source_task_ids": [source_task_id] if source_task_id else [],
        "thread_ids": [thread_id] if thread_id else [],
        "turn_ids": [turn_id] if turn_id else [],
        "agent_ids": [agent_id] if agent_id else [],
        "kind": kind,
        "priority": priority,
        "memory_bucket": memory_bucket,
        "title": title,
        "text": text,
        "status": "active",
        "tags": _tags_for(kind, priority, memory_bucket),
        "metadata": metadata,
    }


def _merge_existing_record(
    existing: dict[str, Any],
    candidate: dict[str, Any],
    now_text: str,
) -> None:
    existing["last_seen_at"] = now_text
    existing["occurrences"] = int(existing.get("occurrences") or 1) + 1
    existing["priority"] = _higher_priority(existing.get("priority"), candidate.get("priority"))
    for key in ("source_task_ids", "thread_ids", "turn_ids", "agent_ids", "tags"):
        existing[key] = _merge_unique(existing.get(key), candidate.get(key))
    metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
    metadata["last_candidate"] = candidate.get("metadata", {}).get("candidate")
    existing["metadata"] = metadata


def _find_record(records: list[dict[str, Any]], record_id: str) -> dict[str, Any] | None:
    for record in records:
        if str(record.get("id") or "") == record_id:
            return record
    return None


def _record_id(*, kind: Any, bucket: Any, title: str, text: str) -> str:
    key = "|".join([
        _clean_text(kind, limit=80).casefold(),
        _clean_text(bucket, limit=80).casefold(),
        title.casefold(),
        text.casefold(),
    ])
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=10).hexdigest()
    return f"exp_{digest}"


def _source_from_review(review: dict[str, Any]) -> dict[str, str]:
    return {
        "task_id": _clean_text(review.get("task_id"), limit=120),
        "thread_id": _clean_text(review.get("thread_id"), limit=120),
        "turn_id": _clean_text(review.get("turn_id"), limit=120),
        "agent_id": _clean_text(review.get("agent_id"), limit=120),
    }


def _record_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    return (
        _PRIORITY_RANK.get(str(row.get("priority") or "P2"), 2),
        str(row.get("last_seen_at") or ""),
        str(row.get("id") or ""),
    )


def _weekly_record_sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    return (
        _PRIORITY_RANK.get(str(row.get("priority") or "P2"), 2),
        -int(row.get("occurrences") or 1),
        str(row.get("last_seen_at") or ""),
    )


def _next_actions(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for row in rows[:8]:
        title = str(row.get("title") or "")
        priority = _priority(row.get("priority"))
        bucket = str(row.get("memory_bucket") or "")
        if bucket == "experiment_backlog":
            action = f"Run or reject experiment: {title}"
        elif priority == "P0":
            action = f"Promote to failure-prevention rule: {title}"
        else:
            action = f"Review and classify learning: {title}"
        actions.append({
            "priority": priority,
            "record_id": str(row.get("id") or ""),
            "action": action,
        })
    return actions


def _within_week(value: Any, start: date, end: date) -> bool:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    seen = dt.date()
    return start <= seen < end


def _week_start(value: str | date | None, *, now: datetime | None) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    today = (now or datetime.now(UTC)).date()
    return today - timedelta(days=today.weekday())


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


def _tags_for(kind: str, priority: str, bucket: str) -> list[str]:
    tags = [kind, priority, bucket]
    return [tag for tag in tags if tag]


__all__ = ["ExperienceLedger"]

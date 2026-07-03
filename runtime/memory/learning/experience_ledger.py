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
_QUALITY_SUMMARY_SCHEMA = "octopus.experience_memory_quality_summary.v1"
_QUALITY_SCHEMA = "octopus.experience_memory_quality.v1"
_CONTRADICTION_SCHEMA = "octopus.experience_contradiction.v1"
_RECALL_SCHEMA = "octopus.experience_recall.v1"
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

        _apply_contradictions(records, touched, now_text)
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
        include_contradicted: bool = False,
        min_reliability: float = 0.0,
        now: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        rows = [
            _with_memory_quality(row, now=now)
            for row in self._read().get("records") or []
        ]
        if status:
            rows = [row for row in rows if str(row.get("status") or "") == status]
        if bucket:
            rows = [row for row in rows if str(row.get("memory_bucket") or "") == bucket]
        if kind:
            rows = [row for row in rows if str(row.get("kind") or "") == kind]
        if priority:
            rows = [row for row in rows if str(row.get("priority") or "") == priority]
        if not include_contradicted:
            rows = [
                row for row in rows
                if str(row.get("memory_quality", {}).get("contradiction_status") or "")
                != "contradicted"
            ]
        threshold = max(0.0, min(1.0, float(min_reliability or 0.0)))
        if threshold > 0:
            rows = [
                row for row in rows
                if float(row.get("memory_quality", {}).get("reliability") or 0.0)
                >= threshold
            ]
        rows = sorted(rows, key=_record_recall_sort_key)
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
        rows: list[dict[str, Any]] = []
        for row in self._read().get("records") or []:
            if wanted not in (row.get("source_task_ids") or []):
                continue
            enriched = _with_memory_quality(row)
            if (
                str(enriched.get("memory_quality", {}).get("contradiction_status") or "")
                == "contradicted"
            ):
                continue
            rows.append(enriched)
        return sorted(rows, key=_record_recall_sort_key)[:limit]

    def recall(
        self,
        query: str,
        *,
        min_reliability: float = 0.0,
        bucket: str | None = None,
        limit: int = 10,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Retrieve replay-cited experience memories for a new task/query.

        This is deliberately deterministic and local: token overlap gives a
        transparent base score, while memory quality, priority, and replay
        citation coverage make promoted, replay-backed memories rank higher.
        """
        query_text = _clean_text(query, limit=800)
        query_terms = _token_set(query_text)
        threshold = max(0.0, min(1.0, float(min_reliability or 0.0)))
        rows: list[dict[str, Any]] = []
        for row in self._read().get("records") or []:
            if bucket and str(row.get("memory_bucket") or "") != bucket:
                continue
            enriched = _with_memory_quality(row, now=now)
            quality = enriched.get("memory_quality") or {}
            if str(quality.get("contradiction_status") or "") == "contradicted":
                continue
            reliability = float(quality.get("reliability") or 0.0)
            if reliability < threshold:
                continue
            matched_terms = sorted(
                query_terms & _token_set(_record_search_text(enriched)),
            )[:12]
            if query_terms and not matched_terms:
                continue
            score = _recall_score(enriched, query_terms=query_terms)
            enriched["recall"] = {
                "schema": "octopus.experience_recall_score.v1",
                "score": score,
                "matched_terms": matched_terms,
                "citation_coverage": _citation_coverage(enriched),
            }
            rows.append(enriched)

        rows = sorted(
            rows,
            key=lambda row: (
                -float(row.get("recall", {}).get("score") or 0.0),
                _PRIORITY_RANK.get(str(row.get("priority") or "P2"), 2),
                str(row.get("last_seen_at") or ""),
            ),
        )[: max(1, int(limit))]
        cited = [
            row for row in rows
            if float(row.get("recall", {}).get("citation_coverage") or 0.0) >= 1.0
        ]
        return {
            "schema": _RECALL_SCHEMA,
            "query": query_text,
            "total": len(rows),
            "records": rows,
            "citation_coverage": round(len(cited) / len(rows), 3) if rows else 0.0,
            "next_actions": _recall_next_actions(rows),
        }

    def weekly_summary(
        self,
        *,
        week_start: str | date | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        start = _week_start(week_start, now=now)
        end = start + timedelta(days=7)
        rows: list[dict[str, Any]] = []
        for row in self._read().get("records") or []:
            if not _within_week(row.get("last_seen_at"), start, end):
                continue
            enriched = _with_memory_quality(row, now=now)
            if (
                str(enriched.get("memory_quality", {}).get("contradiction_status") or "")
                == "contradicted"
            ):
                continue
            rows.append(enriched)
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

    def quality_summary(
        self,
        *,
        now: datetime | None = None,
        limit: int = 10000,
    ) -> dict[str, Any]:
        rows = [
            _with_memory_quality(row, now=now)
            for row in self._read().get("records") or []
        ][: max(1, int(limit))]
        total = len(rows)
        contradicted = [
            row for row in rows
            if row["memory_quality"]["contradiction_status"] == "contradicted"
        ]
        active_rows = [
            row for row in rows
            if row["memory_quality"]["contradiction_status"] != "contradicted"
        ]
        stale_rows = [
            row for row in active_rows
            if float(row["memory_quality"]["freshness"]) < 0.5
        ]
        low_reliability_rows = [
            row for row in active_rows
            if float(row["memory_quality"]["reliability"]) < 0.7
        ]
        avg_reliability = _avg(
            row["memory_quality"]["reliability"] for row in active_rows
        )
        by_bucket = Counter(
            str(row.get("memory_bucket") or "experience")
            for row in active_rows
        )
        top_risks = sorted(
            [*low_reliability_rows, *contradicted],
            key=lambda row: (
                float(row["memory_quality"]["reliability"]),
                str(row.get("last_seen_at") or ""),
            ),
        )[:8]
        return {
            "schema": _QUALITY_SUMMARY_SCHEMA,
            "total": total,
            "active_count": len(active_rows),
            "contradicted_count": len(contradicted),
            "stale_count": len(stale_rows),
            "low_reliability_count": len(low_reliability_rows),
            "avg_reliability": avg_reliability,
            "by_bucket": dict(sorted(by_bucket.items())),
            "top_risks": [
                {
                    "id": row.get("id"),
                    "title": row.get("title"),
                    "memory_bucket": row.get("memory_bucket"),
                    "priority": row.get("priority"),
                    "quality": row.get("memory_quality"),
                }
                for row in top_risks
            ],
            "next_actions": _quality_next_actions(
                stale_count=len(stale_rows),
                contradicted_count=len(contradicted),
                low_reliability_count=len(low_reliability_rows),
            ),
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
    evidence = _review_evidence_metadata(review)
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
            metadata={**evidence, "candidate": item},
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
                **evidence,
                "candidate": item,
                "minimal_implementation": _clean_text(
                    item.get("minimal_implementation"),
                    limit=1200,
                ),
                "validation_metric": _clean_text(item.get("validation_metric"), limit=600),
            },
        ))
    return records


def _apply_contradictions(
    records: list[dict[str, Any]],
    touched: list[dict[str, Any]],
    now_text: str,
) -> None:
    by_id = {str(row.get("id") or ""): row for row in records}
    for record in touched:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        candidate = (
            metadata.get("candidate")
            if isinstance(metadata.get("candidate"), dict)
            else {}
        )
        target_ids = _clean_unique_list(
            candidate.get("contradicts_record_ids")
            or candidate.get("contradicts")
            or [],
            limit=80,
        )
        if not target_ids:
            continue
        reason = _clean_text(
            candidate.get("contradiction_reason")
            or candidate.get("reason")
            or "newer replay-backed learning supersedes this record",
            limit=500,
        )
        record_meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        record_meta["contradiction"] = {
            "schema": _CONTRADICTION_SCHEMA,
            "status": "supersedes",
            "contradicts_record_ids": target_ids,
            "at": now_text,
            "reason": reason,
        }
        record["metadata"] = record_meta
        record["tags"] = _merge_unique(record.get("tags"), ["supersedes"])
        for target_id in target_ids:
            target = by_id.get(target_id)
            if target is None or target is record:
                continue
            target_meta = (
                target.get("metadata")
                if isinstance(target.get("metadata"), dict)
                else {}
            )
            target_meta["contradiction"] = {
                "schema": _CONTRADICTION_SCHEMA,
                "status": "contradicted",
                "by_record_id": record.get("id"),
                "at": now_text,
                "reason": reason,
            }
            target["metadata"] = target_meta
            target["tags"] = _merge_unique(target.get("tags"), ["contradicted"])


def _with_memory_quality(
    row: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    out = dict(row)
    out["memory_quality"] = _memory_quality(row, now=now)
    return out


def _memory_quality(
    row: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    last_seen = _parse_dt(row.get("last_seen_at"))
    age_days = max(0, (current - last_seen).days) if last_seen is not None else 9999
    freshness = _freshness_score(age_days)
    occurrences = max(1, int(row.get("occurrences") or 1))
    occurrence_score = min(1.0, 0.55 + (occurrences - 1) * 0.15)
    priority_score = {"P0": 1.0, "P1": 0.86, "P2": 0.72}.get(
        _priority(row.get("priority")),
        0.72,
    )
    contradiction = _contradiction(row)
    contradiction_status = str(contradiction.get("status") or "none")
    penalty = 0.0
    if contradiction_status == "contradicted":
        penalty = 0.75
    elif contradiction_status == "supersedes":
        penalty = -0.04
    reliability = max(
        0.0,
        min(
            1.0,
            round((freshness * 0.5) + (occurrence_score * 0.3) + (priority_score * 0.2) - penalty, 3),
        ),
    )
    return {
        "schema": _QUALITY_SCHEMA,
        "freshness": freshness,
        "age_days": age_days,
        "occurrence_score": round(occurrence_score, 3),
        "priority_score": priority_score,
        "reliability": reliability,
        "contradiction_status": contradiction_status,
        "contradiction": contradiction,
    }


def _freshness_score(age_days: int) -> float:
    if age_days <= 14:
        return 1.0
    if age_days <= 90:
        return round(1.0 - ((age_days - 14) / 76) * 0.45, 3)
    if age_days <= 180:
        return round(0.55 - ((age_days - 90) / 90) * 0.25, 3)
    return 0.2


def _contradiction(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    contradiction = (
        metadata.get("contradiction")
        if isinstance(metadata.get("contradiction"), dict)
        else {}
    )
    if contradiction.get("schema") == _CONTRADICTION_SCHEMA:
        return contradiction
    return {"schema": _CONTRADICTION_SCHEMA, "status": "none"}


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _review_evidence_metadata(review: dict[str, Any]) -> dict[str, Any]:
    replay = review.get("replay") if isinstance(review.get("replay"), dict) else {}
    resume = review.get("resume") if isinstance(review.get("resume"), dict) else {}
    latest = (
        resume.get("latest_checkpoint")
        if isinstance(resume.get("latest_checkpoint"), dict)
        else {}
    )
    integrity = latest.get("integrity") if isinstance(latest.get("integrity"), dict) else {}
    return {
        "review_status": review.get("status"),
        "citation": {
            "schema": "octopus.experience_replay_citation.v1",
            "task_id": _clean_text(review.get("task_id"), limit=120),
            "thread_id": _clean_text(review.get("thread_id"), limit=120),
            "turn_id": _clean_text(review.get("turn_id"), limit=120),
            "agent_id": _clean_text(review.get("agent_id"), limit=120),
            "replay_case_id": replay.get("case_id"),
            "replay_fingerprint": replay.get("fingerprint"),
            "replayable": bool(replay.get("replayable")),
        },
        "replay": {
            "schema": replay.get("schema"),
            "case_id": replay.get("case_id"),
            "fingerprint": replay.get("fingerprint"),
            "replayable": bool(replay.get("replayable")),
            "step_count": int(replay.get("step_count") or 0),
        },
        "resume": {
            "available": bool(resume.get("available")),
            "source": resume.get("source"),
            "latest_checkpoint_id": latest.get("id"),
            "checkpoint_type": latest.get("type"),
            "resume_safe": bool(integrity.get("resume_safe")),
            "continue_from_iteration": int(integrity.get("continue_from_iteration") or 0),
        },
    }


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


def _record_search_text(row: dict[str, Any]) -> str:
    tags = " ".join(str(tag) for tag in row.get("tags") or [])
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    candidate = (
        metadata.get("candidate")
        if isinstance(metadata.get("candidate"), dict)
        else {}
    )
    return " ".join([
        str(row.get("title") or ""),
        str(row.get("text") or ""),
        str(row.get("kind") or ""),
        str(row.get("memory_bucket") or ""),
        tags,
        str(candidate.get("minimal_implementation") or ""),
        str(candidate.get("validation_metric") or ""),
    ])


def _token_set(text: str) -> set[str]:
    import re

    return {
        normalized
        for token in re.findall(r"[A-Za-z0-9]+", str(text or ""))
        if (normalized := _normalize_token(token))
    }


def _normalize_token(token: str) -> str:
    text = str(token or "").casefold().strip()
    if len(text) < 3:
        return ""
    if len(text) > 4 and text.endswith("ies"):
        return text[:-3] + "y"
    if len(text) > 4 and text.endswith("ing"):
        return text[:-3]
    if len(text) > 3 and text.endswith("s"):
        return text[:-1]
    return text


def _citation_coverage(row: dict[str, Any]) -> float:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    citation = metadata.get("citation") if isinstance(metadata.get("citation"), dict) else {}
    replay = metadata.get("replay") if isinstance(metadata.get("replay"), dict) else {}
    has_case = bool(citation.get("replay_case_id") or replay.get("case_id"))
    has_fingerprint = bool(citation.get("replay_fingerprint") or replay.get("fingerprint"))
    replayable = bool(citation.get("replayable") or replay.get("replayable"))
    return 1.0 if has_case and has_fingerprint and replayable else 0.0


def _recall_score(row: dict[str, Any], *, query_terms: set[str]) -> float:
    record_terms = _token_set(_record_search_text(row))
    overlap = 0.0 if not query_terms else len(query_terms & record_terms) / max(1, len(query_terms))
    quality = row.get("memory_quality") if isinstance(row.get("memory_quality"), dict) else {}
    reliability = float(quality.get("reliability") or 0.0)
    priority = {"P0": 1.0, "P1": 0.86, "P2": 0.72}.get(
        _priority(row.get("priority")),
        0.72,
    )
    citation = _citation_coverage(row)
    score = (overlap * 0.48) + (reliability * 0.32) + (priority * 0.1) + (citation * 0.1)
    return round(min(1.0, max(0.0, score)), 3)


def _recall_next_actions(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["Promote replay-backed experience memories before relying on recall."]
    actions: list[str] = []
    if any(float(row.get("recall", {}).get("citation_coverage") or 0.0) < 1.0 for row in rows):
        actions.append("Refresh recalled memories with replay citation evidence.")
    if any(float(row.get("memory_quality", {}).get("reliability") or 0.0) < 0.7 for row in rows):
        actions.append("Review low-reliability recalled memories before reuse.")
    return actions


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


def _record_recall_sort_key(row: dict[str, Any]) -> tuple[int, float, str, str]:
    quality = row.get("memory_quality") if isinstance(row.get("memory_quality"), dict) else {}
    return (
        _PRIORITY_RANK.get(str(row.get("priority") or "P2"), 2),
        -float(quality.get("reliability") or 0.0),
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


def _quality_next_actions(
    *,
    stale_count: int,
    contradicted_count: int,
    low_reliability_count: int,
) -> list[str]:
    actions: list[str] = []
    if contradicted_count:
        actions.append("Archive or explain contradicted memory records before recall.")
    if stale_count:
        actions.append("Refresh stale memories with replay-backed evidence.")
    if low_reliability_count:
        actions.append("Require stronger citations before low-reliability memories influence code mode.")
    return actions


def _avg(values: Any) -> float:
    nums = [float(value) for value in values]
    return round(sum(nums) / len(nums), 3) if nums else 0.0


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
        except ValueError:  # expected · malformed value falls through to the current week
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

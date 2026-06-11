"""Safe applier for promoted Review Queue items."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.memory.learning.experience_ledger import ExperienceLedger
from runtime.memory.learning.review_queue import ReviewQueue
from runtime.platform.io import atomic_write_json, read_json_with_backup
from runtime.safety.evolution.proposal_ledger import ProposalLedger

_SCHEMA = "octopus.promotion_applier.v1"
_AUDIT_SCHEMA = "octopus.promotion_audit.v1"
_VALID_TARGETS = {
    "experience",
    "project_knowledge",
    "experiment_backlog",
    "rule_candidate",
}


class PromotionApplier:
    """Apply human-promoted review items with dry-run and audit records."""

    def __init__(
        self,
        *,
        review_queue: ReviewQueue,
        experience_ledger: ExperienceLedger,
        proposal_ledger: ProposalLedger,
        audit_path: str | Path,
    ) -> None:
        self.review_queue = review_queue
        self.experience_ledger = experience_ledger
        self.proposal_ledger = proposal_ledger
        self.audit_path = Path(audit_path)

    def plan(
        self,
        *,
        item_id: str | None = None,
        target: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        items = self._candidate_items(item_id=item_id, target=target, limit=limit)
        records = self._audit_records()
        applied_keys = {
            _audit_key(record.get("review_queue_item_id"), record.get("target"))
            for record in records
            if record.get("status") == "applied"
        }
        actions = [
            _planned_action(item, applied_keys=applied_keys)
            for item in items
        ]
        return {
            "schema": _SCHEMA,
            "dry_run": True,
            "total": len(actions),
            "applicable": sum(1 for action in actions if action["action"] == "apply"),
            "skipped": sum(1 for action in actions if action["action"] == "skip"),
            "actions": actions,
        }

    def apply(
        self,
        *,
        item_id: str | None = None,
        target: str | None = None,
        limit: int = 50,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now_text = _iso(now)
        payload = self._read_audit_payload()
        records = list(payload.get("records") or [])
        applied_keys = {
            _audit_key(record.get("review_queue_item_id"), record.get("target"))
            for record in records
            if record.get("status") == "applied"
        }
        results: list[dict[str, Any]] = []

        for item in self._candidate_items(item_id=item_id, target=target, limit=limit):
            planned = _planned_action(item, applied_keys=applied_keys)
            if planned["action"] != "apply":
                results.append(planned)
                continue
            target_name = planned["target"]
            try:
                artifact = self._apply_one(item, target=target_name)
                audit = _audit_record(
                    item=item,
                    target=target_name,
                    status="applied",
                    artifact=artifact,
                    now_text=now_text,
                )
                records.append(audit)
                applied_keys.add(_audit_key(item.get("id"), target_name))
                results.append({**planned, "status": "applied", "artifact": artifact})
            except Exception as exc:
                audit = _audit_record(
                    item=item,
                    target=target_name,
                    status="failed",
                    artifact={"error": str(exc)},
                    now_text=now_text,
                )
                records.append(audit)
                results.append({**planned, "status": "failed", "error": str(exc)})

        payload["records"] = records
        payload["lastUpdated"] = now_text
        self._write_audit_payload(payload)
        return {
            "schema": _SCHEMA,
            "dry_run": False,
            "applied": sum(1 for result in results if result.get("status") == "applied"),
            "failed": sum(1 for result in results if result.get("status") == "failed"),
            "skipped": sum(1 for result in results if result.get("action") == "skip"),
            "results": results,
        }

    def audit(
        self,
        *,
        item_id: str | None = None,
        target: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        rows = self._audit_records()
        if item_id:
            rows = [
                row for row in rows
                if str(row.get("review_queue_item_id") or "") == item_id
            ]
        if target:
            rows = [row for row in rows if str(row.get("target") or "") == target]
        total = len(rows)
        return {
            "schema": _AUDIT_SCHEMA,
            "records": rows[offset: offset + limit],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def _candidate_items(
        self,
        *,
        item_id: str | None,
        target: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if item_id:
            rows = self.review_queue.items(status="promoted", limit=10000)["items"]
            rows = [row for row in rows if str(row.get("id") or "") == item_id]
        else:
            rows = self.review_queue.items(status="promoted", limit=limit)["items"]
        if target:
            wanted = _target_name({"promoted_to": target, "target_bucket": target})
            rows = [row for row in rows if _target_name(row) == wanted]
        return rows[:limit]

    def _apply_one(self, item: dict[str, Any], *, target: str) -> dict[str, Any]:
        if target in {"experience", "project_knowledge", "experiment_backlog"}:
            review = _review_from_queue_item(item, target=target)
            result = self.experience_ledger.add_from_task_run_review(review)
            return {
                "type": "experience_ledger",
                "target_bucket": target,
                "created": result.get("created", 0),
                "updated": result.get("updated", 0),
                "record_ids": [
                    str(record.get("id") or "")
                    for record in result.get("records") or []
                    if isinstance(record, dict)
                ],
            }
        if target == "rule_candidate":
            proposal = self.proposal_ledger.propose(
                kind="review_queue_rule_candidate",
                description=_description(item),
                proposer="review_queue_applier",
                metadata={
                    "source": "review_queue",
                    "review_queue_item_id": item.get("id"),
                    "priority": item.get("priority"),
                    "candidate_kind": item.get("candidate_kind"),
                    "source_task_ids": item.get("source_task_ids") or [],
                    "item": item,
                },
            )
            return {
                "type": "proposal_ledger",
                "proposal_id": proposal.proposal_id,
                "kind": proposal.kind,
                "status": proposal.status.value,
            }
        raise ValueError(f"unsupported promotion target: {target}")

    def _audit_records(self) -> list[dict[str, Any]]:
        return list(self._read_audit_payload().get("records") or [])

    def _read_audit_payload(self) -> dict[str, Any]:
        raw = read_json_with_backup(self.audit_path, default=None)
        if not isinstance(raw, dict):
            return _empty_audit_payload()
        return _normalize_audit_payload(raw)

    def _write_audit_payload(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.audit_path, _normalize_audit_payload(payload))


def _empty_audit_payload() -> dict[str, Any]:
    return {
        "schema": _AUDIT_SCHEMA,
        "version": 1,
        "lastUpdated": "",
        "records": [],
    }


def _normalize_audit_payload(raw: dict[str, Any]) -> dict[str, Any]:
    payload = _empty_audit_payload()
    records: list[dict[str, Any]] = []
    for record in raw.get("records") or []:
        if not isinstance(record, dict):
            continue
        item_id = _clean_text(record.get("review_queue_item_id"), limit=120)
        target = _target_text(record.get("target"))
        if not item_id or not target:
            continue
        records.append({
            "id": _clean_text(record.get("id"), limit=100) or _promotion_id(
                item_id=item_id,
                target=target,
            ),
            "review_queue_item_id": item_id,
            "target": target,
            "status": _clean_text(record.get("status"), limit=40) or "applied",
            "applied_at": _clean_text(record.get("applied_at"), limit=80),
            "artifact": record.get("artifact") if isinstance(record.get("artifact"), dict) else {},
            "item_snapshot": (
                record.get("item_snapshot")
                if isinstance(record.get("item_snapshot"), dict)
                else {}
            ),
        })
    payload.update({
        "schema": _AUDIT_SCHEMA,
        "version": 1,
        "lastUpdated": _clean_text(raw.get("lastUpdated"), limit=80),
        "records": sorted(records, key=lambda row: str(row.get("applied_at") or "")),
    })
    return payload


def _planned_action(
    item: dict[str, Any],
    *,
    applied_keys: set[str],
) -> dict[str, Any]:
    target = _target_name(item)
    item_id = str(item.get("id") or "")
    if target not in _VALID_TARGETS:
        return {
            "action": "skip",
            "reason": f"unsupported target: {target}",
            "item_id": item_id,
            "target": target,
            "item": item,
        }
    if _audit_key(item_id, target) in applied_keys:
        return {
            "action": "skip",
            "reason": "already applied",
            "item_id": item_id,
            "target": target,
            "item": item,
        }
    return {
        "action": "apply",
        "reason": "promoted review item is ready to apply",
        "item_id": item_id,
        "target": target,
        "item": item,
    }


def _review_from_queue_item(item: dict[str, Any], *, target: str) -> dict[str, Any]:
    source_task_ids = item.get("source_task_ids") if isinstance(item.get("source_task_ids"), list) else []
    thread_ids = item.get("thread_ids") if isinstance(item.get("thread_ids"), list) else []
    turn_ids = item.get("turn_ids") if isinstance(item.get("turn_ids"), list) else []
    agent_ids = item.get("agent_ids") if isinstance(item.get("agent_ids"), list) else []
    review = {
        "schema": "octopus.task_run_review.v1",
        "task_id": str(source_task_ids[0]) if source_task_ids else "",
        "thread_id": str(thread_ids[0]) if thread_ids else "",
        "turn_id": str(turn_ids[0]) if turn_ids else "",
        "agent_id": str(agent_ids[0]) if agent_ids else "",
        "status": "promoted",
        "learning_candidates": [],
        "backlog_candidates": [],
    }
    title = _clean_text(item.get("title"), limit=180)
    text = _clean_text(item.get("text"), limit=1200)
    priority = _clean_text(item.get("priority"), limit=20) or "P2"
    if target == "experiment_backlog":
        review["backlog_candidates"] = [{
            "priority": priority,
            "experiment": title,
            "hypothesis": text,
            "minimal_implementation": _metadata_text(item, "minimal_implementation"),
            "validation_metric": _metadata_text(item, "validation_metric"),
        }]
    else:
        review["learning_candidates"] = [{
            "kind": _clean_text(item.get("candidate_kind"), limit=80) or "learning_candidate",
            "priority": priority,
            "memory_bucket": target,
            "title": title,
            "text": text,
        }]
    return review


def _audit_record(
    *,
    item: dict[str, Any],
    target: str,
    status: str,
    artifact: dict[str, Any],
    now_text: str,
) -> dict[str, Any]:
    item_id = str(item.get("id") or "")
    return {
        "id": _promotion_id(item_id=item_id, target=target),
        "review_queue_item_id": item_id,
        "target": target,
        "status": status,
        "applied_at": now_text,
        "artifact": artifact,
        "item_snapshot": item,
    }


def _promotion_id(*, item_id: str, target: str) -> str:
    digest = hashlib.blake2b(
        f"{item_id}|{target}".encode(),
        digest_size=10,
    ).hexdigest()
    return f"pa_{digest}"


def _audit_key(item_id: Any, target: Any) -> str:
    return f"{str(item_id or '')}|{_target_text(target)}"


def _target_name(item: dict[str, Any]) -> str:
    promoted_to = _target_text(item.get("promoted_to"))
    if promoted_to and promoted_to != "none":
        return promoted_to
    return _target_text(item.get("target_bucket")) or "experience"


def _target_text(value: Any) -> str:
    return _clean_text(value, limit=80)


def _description(item: dict[str, Any]) -> str:
    title = _clean_text(item.get("title"), limit=180)
    text = _clean_text(item.get("text"), limit=1200)
    return f"{title}\n\n{text}".strip()


def _metadata_text(item: dict[str, Any], key: str) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return _clean_text(metadata.get(key), limit=1200)


def _iso(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


def _clean_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit].rstrip()


__all__ = ["PromotionApplier"]

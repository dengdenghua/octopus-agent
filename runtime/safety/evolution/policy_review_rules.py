"""Signed draft rules derived from replay-backed policy review proposals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from runtime.safety.approval.approval_gate import ApprovalRule
from runtime.safety.approval.approval_policy_store import append_rule
from runtime.safety.evolution.proposal_ledger import ProposalLedger, ProposalRecord

_SCHEMA = "octopus.policy_review_rule_drafts.v1"
_DRAFT_SCHEMA = "octopus.policy_review_rule_draft.v1"
_SIGNATURE_SCHEMA = "octopus.policy_review_rule_signature.v1"


def build_policy_review_rule_drafts(
    *,
    ledger_path: str | Path | None = None,
    records: list[ProposalRecord] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return signed, non-applied static-policy rule drafts.

    The output is intentionally a draft envelope, not a direct write to the
    approval policy store. A later operator step can verify the signature and
    decide whether the rule is precise enough to install.
    """

    proposals = (
        records
        if records is not None
        else ProposalLedger(ledger_path or "data/proposal_ledger.jsonl").query(
            kind="review_queue_policy_review",
            limit=limit,
        )
    )
    drafts = [
        draft
        for draft in (_draft_from_proposal(record) for record in proposals[-limit:])
        if draft is not None
    ]
    return {
        "schema": _SCHEMA,
        "total": len(drafts),
        "drafts": drafts,
    }


def verify_policy_review_rule_draft(draft: dict[str, Any]) -> dict[str, Any]:
    payload = draft.get("signed_payload") if isinstance(draft, dict) else None
    signature = draft.get("signature") if isinstance(draft, dict) else None
    if not isinstance(payload, dict) or not isinstance(signature, dict):
        return {
            "schema": "octopus.policy_review_rule_signature_check.v1",
            "ok": False,
            "reason": "missing signed payload or signature",
        }
    expected = _signature_for_payload(payload)
    actual = str(signature.get("digest") or "")
    return {
        "schema": "octopus.policy_review_rule_signature_check.v1",
        "ok": actual == expected,
        "reason": "ok" if actual == expected else "signature mismatch",
        "expected_digest": expected,
        "actual_digest": actual,
    }


def install_policy_review_rule_draft(
    draft: dict[str, Any],
    *,
    policy_path: str | Path,
    confirm_install: bool,
) -> dict[str, Any]:
    if confirm_install is not True:
        raise ValueError("confirm_install=true is required")
    check = verify_policy_review_rule_draft(draft)
    if check.get("ok") is not True:
        raise ValueError(str(check.get("reason") or "invalid draft signature"))
    payload = draft.get("signed_payload") if isinstance(draft, dict) else {}
    rule_payload = (
        payload.get("rule")
        if isinstance(payload, dict) and isinstance(payload.get("rule"), dict)
        else {}
    )
    if rule_payload.get("effect") != "deny":
        raise ValueError("only deny policy-review drafts can be installed")
    rule = ApprovalRule(
        effect="deny",
        tool=_clean_text(rule_payload.get("tool"), limit=120) or "*",
        args_contains=_clean_text(rule_payload.get("args_contains"), limit=240),
        reason=_clean_text(rule_payload.get("reason"), limit=600),
    )
    policy = append_rule(Path(policy_path), rule)
    return {
        "schema": "octopus.policy_review_rule_install.v1",
        "installed": True,
        "draft_id": draft.get("draft_id"),
        "rule": {
            "effect": rule.effect,
            "tool": rule.tool,
            "args_contains": rule.args_contains,
            "reason": rule.reason,
        },
        "policy_rule_count": len(policy.rules),
        "signature": draft.get("signature") if isinstance(draft.get("signature"), dict) else {},
    }


def _draft_from_proposal(record: ProposalRecord) -> dict[str, Any] | None:
    if record.kind != "review_queue_policy_review":
        return None
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    item = metadata.get("item") if isinstance(metadata.get("item"), dict) else {}
    item_metadata = (
        item.get("metadata")
        if isinstance(item.get("metadata"), dict)
        else {}
    )
    latest = (
        item_metadata.get("latest_denial")
        if isinstance(item_metadata.get("latest_denial"), dict)
        else {}
    )
    tool_name = _clean_text(
        item_metadata.get("tool_name")
        or latest.get("tool_name")
        or _tool_name_from_title(item.get("title")),
        limit=120,
    )
    if not tool_name:
        return None
    reason = _clean_text(
        latest.get("reason")
        or item.get("text")
        or record.description,
        limit=240,
    )
    evidence = metadata.get("evidence") if isinstance(metadata.get("evidence"), dict) else {}
    signed_payload = {
        "schema": _DRAFT_SCHEMA,
        "proposal_id": record.proposal_id,
        "proposal_kind": record.kind,
        "review_queue_item_id": metadata.get("review_queue_item_id"),
        "rule": {
            "effect": "deny",
            "tool": tool_name,
            "args_contains": "",
            "reason": reason or f"Replay-backed policy review for {tool_name}",
        },
        "evidence": evidence,
        "review_required": True,
    }
    digest = _signature_for_payload(signed_payload)
    return {
        "schema": _DRAFT_SCHEMA,
        "draft_id": f"prd_{digest[:20]}",
        "signed_payload": signed_payload,
        "signature": {
            "schema": _SIGNATURE_SCHEMA,
            "algorithm": "sha256:canonical-json",
            "digest": digest,
        },
    }


def _signature_for_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _tool_name_from_title(value: Any) -> str:
    text = _clean_text(value, limit=180)
    prefix = "Review repeated denials for "
    if text.startswith(prefix):
        return text[len(prefix):].strip()
    return ""


def _clean_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit].rstrip()


__all__ = [
    "build_policy_review_rule_drafts",
    "install_policy_review_rule_draft",
    "verify_policy_review_rule_draft",
]

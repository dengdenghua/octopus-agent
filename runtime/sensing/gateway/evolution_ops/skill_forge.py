"""SkillForge subsystem for evolution operators."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .utils import (
    _as_dt,
    _journal_events,
    _registry_has_skill,
    _utcnow,
)


def _skill_forge_candidates(
    journal: Any,
    registry: Any,
    *,
    suppressed_names: set[str] | None = None,
) -> list[Any]:
    if journal is None or registry is None:
        return []
    try:
        from runtime.safety.recovery.skill_forge import SkillForge

        candidates = SkillForge(journal=journal, registry=registry).propose()
    except (ImportError, AttributeError, TypeError, OSError):
        return []

    suppressed = set(suppressed_names or set())
    decisions = _skill_proposal_decision_map(journal)
    return [
        candidate
        for candidate in candidates
        if candidate.name not in suppressed
        and decisions.get(candidate.name) not in {
            "promoted",
            "rejected",
            "shadow_failed",
            "promote_failed",
        }
        and not _registry_has_skill(registry, candidate.name)
    ]


def _skill_candidate_to_proposal(candidate: Any) -> dict[str, Any]:
    sequence = list(getattr(candidate, "underlying_sequence", []) or [])
    created_at = _utcnow().isoformat()
    return {
        "name": getattr(candidate, "name", ""),
        "created_at": created_at,
        "topic": "SkillForge",
        "source_url": None,
        "status": "pending",
        "candidate_id": getattr(candidate, "candidate_id", ""),
        "description": getattr(candidate, "description", ""),
        "underlying_sequence": sequence,
        "source_sample_count": int(
            getattr(candidate, "source_sample_count", 0) or 0
        ),
        "source_success_rate": float(
            getattr(candidate, "source_success_rate", 0.0) or 0.0
        ),
    }


def _skill_proposal_decision_map(journal: Any) -> dict[str, str]:
    decisions: dict[str, tuple[datetime, str]] = {}
    if journal is None:
        return {}
    try:
        events = list(journal.read_by_type("skill_proposal_decision"))
    except (AttributeError, TypeError, OSError):
        events = [
            event for event in _journal_events(journal)
            if getattr(event, "event_type", "") == "skill_proposal_decision"
        ]
    for event in events:
        name = str(getattr(event, "proposal_name", "") or "").strip()
        decision = str(getattr(event, "decision", "") or "").strip()
        if not name or not decision:
            continue
        ts = _as_dt(getattr(event, "ts", None)) or _utcnow()
        existing = decisions.get(name)
        if existing is None or ts >= existing[0]:
            decisions[name] = (ts, decision)
    return {name: decision for name, (_ts, decision) in decisions.items()}


def _write_skill_proposal_decision(
    journal: Any,
    *,
    proposal_name: str,
    decision: str,
    candidate_id: str = "",
    reason: str = "",
    details: dict[str, Any] | None = None,
) -> bool:
    if journal is None:
        return False
    try:
        if hasattr(journal, "write_skill_proposal_decision"):
            journal.write_skill_proposal_decision(
                proposal_name=proposal_name,
                candidate_id=candidate_id,
                decision=decision,
                reason=reason,
                details=details or {},
            )
        else:
            from runtime.memory.journal import SkillProposalDecisionEvent

            journal.write(
                SkillProposalDecisionEvent(
                    proposal_name=proposal_name,
                    candidate_id=candidate_id,
                    decision=decision,
                    reason=reason,
                    details=details or {},
                )
            )
        return True
    except (AttributeError, TypeError, OSError):
        return False

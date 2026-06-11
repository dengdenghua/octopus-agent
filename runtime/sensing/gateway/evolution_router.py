from __future__ import annotations

import logging
from typing import Any

try:
    from fastapi import APIRouter, Query

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

_LOG = logging.getLogger("octopus.siphon.evolution_router")


def create_evolution_router() -> Any:
    if not FASTAPI_AVAILABLE:
        return APIRouter() if FASTAPI_AVAILABLE else None

    router = APIRouter(prefix="/api/evolution", tags=["evolution"])

    @router.get("/fitness/{agent_id}")
    def get_fitness(agent_id: str, window: int = Query(default=20, ge=5, le=100)) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.fitness import FitnessConfig, compute_fitness
            report = compute_fitness(agent_id, FitnessConfig(window=window))
            return {
                "ok": True,
                "agent_id": report.agent_id,
                "ts": report.ts,
                "l1": {
                    "score": report.l1.score,
                    "trend": report.l1.trend,
                    "success_rate": report.l1.success_rate,
                    "avg_rounds": report.l1.avg_rounds,
                },
                "l2": {
                    "score": report.l2.score,
                    "dominant_failure": report.l2.dominant_failure,
                    "action": report.l2.action,
                    "confidence": report.l2.confidence,
                } if report.l2 else None,
                "combined": report.combined,
                "verdict": report.verdict,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/drift/{agent_id}")
    def get_drift(agent_id: str) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.drift_monitor import DriftMonitor
            report = DriftMonitor(agent_id).check()
            return {
                "ok": True,
                "agent_id": report.agent_id,
                "ts": report.ts,
                "has_drift": report.has_drift,
                "max_severity": report.max_severity,
                "events": [
                    {"kind": e.kind, "severity": e.severity, "detail": e.detail}
                    for e in report.events
                ],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/ledger")
    def get_ledger(
        status: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.proposal_ledger import ProposalLedger, ProposalStatus
            ledger = ProposalLedger()
            st = ProposalStatus(status) if status else None
            records = ledger.query(status=st, kind=kind, limit=limit)
            return {
                "ok": True,
                "total": len(records),
                "records": [
                    {
                        "id": r.proposal_id,
                        "kind": r.kind,
                        "description": r.description,
                        "status": r.status.value,
                        "proposer": r.proposer,
                        "ts": r.ts,
                        "fitness_before": r.fitness_before,
                        "fitness_after": r.fitness_after,
                    }
                    for r in records
                ],
                "stats": ledger.stats(),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/ledger/{proposal_id}")
    def get_ledger_proposal(proposal_id: str) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.canary import CanaryManager
            from runtime.safety.evolution.proposal_ledger import ProposalLedger, ProposalStatus

            ledger = ProposalLedger()
            record = next(
                (r for r in ledger.query(limit=10_000) if r.proposal_id == proposal_id),
                None,
            )
            if record is None:
                return {"ok": False, "error": f"proposal not found: {proposal_id}"}

            canaries = []
            for state in CanaryManager().list_all():
                metadata = state.metadata if isinstance(state.metadata, dict) else {}
                if metadata.get("proposal_id") == proposal_id:
                    canaries.append({
                        "skill_name": state.skill_name,
                        "phase": state.phase.value,
                        "sample_count": state.sample_count,
                        "success_count": state.success_count,
                        "failure_count": state.failure_count,
                        "current_rate": round(state.current_rate, 3),
                        "entered_ts": state.entered_ts,
                        "metadata": metadata,
                    })

            rollbacks = []
            for rb in ledger.query(status=ProposalStatus.ROLLED_BACK, kind="canary_rollback", limit=10_000):
                metadata = rb.metadata if isinstance(rb.metadata, dict) else {}
                if metadata.get("source_proposal_id") == proposal_id:
                    rollbacks.append({
                        "id": rb.proposal_id,
                        "description": rb.description,
                        "ts": rb.ts,
                        "rolled_back_ts": rb.rolled_back_ts,
                        "metadata": metadata,
                    })

            return {
                "ok": True,
                "proposal": {
                    "id": record.proposal_id,
                    "kind": record.kind,
                    "description": record.description,
                    "status": record.status.value,
                    "proposer": record.proposer,
                    "ts": record.ts,
                    "fitness_before": record.fitness_before,
                    "fitness_after": record.fitness_after,
                    "model": record.model,
                    "cost_tokens": record.cost_tokens,
                    "cost_usd": record.cost_usd,
                    "metadata": record.metadata,
                    "applied_ts": record.applied_ts,
                    "rolled_back_ts": record.rolled_back_ts,
                    "rejection_reason": record.rejection_reason,
                },
                "canaries": canaries,
                "rollbacks": rollbacks,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/canary")
    def get_canary(
        include_all: bool = Query(default=True),
        phase: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.canary import CanaryManager, CanaryPhase
            cm = CanaryManager()
            canaries = cm.list_all() if include_all else cm.list_active()
            if phase:
                try:
                    phase_enum = CanaryPhase(phase)
                    canaries = [s for s in canaries if s.phase == phase_enum]
                except Exception:
                    return {"ok": False, "error": f"invalid phase: {phase}"}
            active_count = sum(1 for s in canaries if s.phase not in (CanaryPhase.FULL, CanaryPhase.ROLLED_BACK))
            rolled_back_count = sum(1 for s in canaries if s.phase == CanaryPhase.ROLLED_BACK)
            full_count = sum(1 for s in canaries if s.phase == CanaryPhase.FULL)
            canaries = sorted(
                canaries,
                key=lambda s: s.entered_ts,
                reverse=True,
            )[:limit]
            return {
                "ok": True,
                "total": len(canaries),
                "active_count": active_count,
                "rolled_back_count": rolled_back_count,
                "full_count": full_count,
                "canaries": [
                    {
                        "skill_name": s.skill_name,
                        "phase": s.phase.value,
                        "sample_count": s.sample_count,
                        "success_count": s.success_count,
                        "failure_count": s.failure_count,
                        "current_rate": round(s.current_rate, 3),
                        "entered_ts": s.entered_ts,
                        "metadata": s.metadata,
                        "proposal_id": s.metadata.get("proposal_id"),
                        "proposal_kind": s.metadata.get("proposal_kind"),
                        "candidate_id": s.metadata.get("candidate_id"),
                        "recipe_id": s.metadata.get("recipe_id"),
                        "avg_score": s.metadata.get("avg_score"),
                        "last_rollback_reason": s.metadata.get("last_rollback_reason"),
                    }
                    for s in canaries
                ],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/canary/{skill_name}/rollback")
    def rollback_canary(skill_name: str) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.canary import CanaryManager
            cm = CanaryManager()
            state = cm.force_rollback(skill_name)
            if state is None:
                return {"ok": False, "error": "skill not in canary"}
            return {"ok": True, "skill_name": skill_name, "phase": state.phase.value}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    return router

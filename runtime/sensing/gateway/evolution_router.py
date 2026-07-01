from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

try:
    from fastapi import APIRouter, HTTPException, Query, Request
    from pydantic import BaseModel, Field

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


if FASTAPI_AVAILABLE:
    class SubagentPolicyDecisionBody(BaseModel):
        action: str = Field(..., pattern="^(watch|retire|clear)$")
        reason: str = ""
        evidence_item_ids: list[str] = Field(default_factory=list)
        actor: str = "operator_panel"


    class ScorecardGapQueueBody(BaseModel):
        target_score: int = Field(default=90, ge=1, le=100)
        limit: int = Field(default=10, ge=1, le=50)
        reason: str = "operator_scorecard_gap_review"
        dimension_id: str = ""


    class VerifierDriftQueueBody(BaseModel):
        limit: int = Field(default=1000, ge=1, le=5000)


    class RepairRoutePromotionQueueBody(BaseModel):
        limit: int = Field(default=1000, ge=1, le=5000)


    class BrowserDesktopRepairRecipeQueueBody(BaseModel):
        limit: int = Field(default=1000, ge=1, le=5000)
        min_occurrences: int = Field(default=1, ge=1, le=20)


    class BrowserDesktopStaleArtifactRejectionBody(BaseModel):
        limit: int = Field(default=1000, ge=1, le=5000)


    class BrowserDesktopRepairRecipeEvidenceBody(BaseModel):
        item_id: str
        passed: bool = False
        provided: list[str] = Field(default_factory=list)
        artifacts: list[dict[str, Any]] = Field(default_factory=list)
        notes: str = ""
        actor: str = "operator_panel"


    class BrowserDesktopRepairRecipeRerunBody(BaseModel):
        item_id: str
        api_base_url: str = ""
        promote_source_cases: bool = False
        actor: str = "operator_panel"


    class BrowserDesktopRepairRecipeRerunBatchBody(BaseModel):
        api_base_url: str = ""
        promote_source_cases: bool = False
        actor: str = "operator_panel"
        limit: int = Field(default=20, ge=1, le=100)


    class AutomationPolicyRuleInstallBody(BaseModel):
        draft_id: str
        confirm_install: bool = False
        limit: int = Field(default=100, ge=1, le=500)

_LOG = logging.getLogger("octopus.siphon.evolution_router")


def create_evolution_router() -> Any:
    if not FASTAPI_AVAILABLE:
        return APIRouter() if FASTAPI_AVAILABLE else None

    router = APIRouter(prefix="/api/evolution", tags=["evolution"])

    @router.get("/codex-gap")
    def get_codex_gap() -> dict[str, Any]:
        try:
            from runtime.safety.evolution.codex_gap import compute_codex_gap_report

            return {"ok": True, **compute_codex_gap_report()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/agent-scorecard")
    def get_agent_scorecard(
        target_score: int = Query(default=90, ge=1, le=100),
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.agent_competitor_scorecard import (
                compute_agent_competitor_scorecard,
            )

            return {
                "ok": True,
                **compute_agent_competitor_scorecard(target_score=target_score),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/e2e-surpass-certification")
    def get_e2e_surpass_certification(
        target_score: int = Query(default=95, ge=1, le=100),
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.e2e_surpass_certification import (
                compute_e2e_surpass_certification,
            )

            return {
                "ok": True,
                **compute_e2e_surpass_certification(target_score=target_score),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/agent-scorecard/gaps/queue")
    def queue_agent_scorecard_gaps(
        body: ScorecardGapQueueBody | None = None,
    ) -> dict[str, Any]:
        try:
            from runtime.memory.learning.review_queue import ReviewQueue
            from runtime.platform.process.paths import app_paths
            from runtime.safety.evolution.agent_competitor_scorecard import (
                compute_agent_competitor_scorecard,
            )

            body = body or ScorecardGapQueueBody()
            report = compute_agent_competitor_scorecard(
                target_score=body.target_score,
            )
            queue = ReviewQueue(app_paths().review_queue_path)
            created = 0
            updated = 0
            items: list[dict[str, Any]] = []
            rows = sorted(
                report.get("octopus_focus_gaps") or [],
                key=lambda row: (
                    int(row.get("octopus_gap_to_effective_target") or 0),
                    int(row.get("octopus_gap_to_surpass") or 0),
                    int(row.get("octopus_gap_to_target") or 0),
                    int(row.get("weight") or 0),
                ),
                reverse=True,
            )
            if body.dimension_id:
                wanted_dimension = str(body.dimension_id).strip()
                rows = [
                    row
                    for row in rows
                    if isinstance(row, dict)
                    and str(row.get("id") or "") == wanted_dimension
                ]
            rows = rows[: body.limit]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                dimension_id = str(row.get("id") or "unknown")
                next_actions = row.get("octopus_next_actions")
                result = queue.upsert_item(
                    source="agent_scorecard_gap",
                    source_kind="scorecard_gap",
                    candidate_kind=f"scorecard_gap:{dimension_id}",
                    priority=_scorecard_gap_priority(
                        int(row.get("octopus_gap_to_effective_target") or 0),
                    ),
                    target_bucket="scorecard_gap_backlog",
                    title=f"Raise {row.get('title') or row.get('id') or 'scorecard gap'}",
                    text=_scorecard_gap_text(row, reason=body.reason),
                    metadata={
                        "schema": "octopus.agent_scorecard_gap.v1",
                        "dimension_id": row.get("id"),
                        "title": row.get("title"),
                        "target_score": body.target_score,
                        "gap": row.get("octopus_gap_to_target"),
                        "effective_target_score": row.get("effective_target_score"),
                        "gap_to_effective_target": row.get(
                            "octopus_gap_to_effective_target",
                        ),
                        "surpass_target_score": row.get("surpass_target_score"),
                        "gap_to_surpass": row.get("octopus_gap_to_surpass"),
                        "best_external_competitor": row.get(
                            "best_external_competitor",
                        ),
                        "best_external_score": row.get("best_external_score"),
                        "octopus_surpasses_best_external": row.get(
                            "octopus_surpasses_best_external",
                        ),
                        "scores": row.get("scores"),
                        "evidence_adjusted_scores": row.get(
                            "evidence_adjusted_scores",
                        ),
                        "octopus_evidence_adjusted_score": row.get(
                            "octopus_evidence_adjusted_score",
                        ),
                        "operator_drilldown": row.get("operator_drilldown"),
                        "next_actions": next_actions,
                        "remediation": {
                            "schema": "octopus.scorecard_gap_remediation.v1",
                            "dimension_id": dimension_id,
                            "status": "queued",
                            "primary_action": (
                                str(next_actions[0])
                                if isinstance(next_actions, list) and next_actions
                                else ""
                            ),
                            "evidence_checklist": row.get(
                                "octopus_evidence_checklist",
                            ),
                            "operator_drilldown": row.get("operator_drilldown"),
                        },
                        "scorecard_policy": report.get("scorecard_policy"),
                    },
                    tags=[
                        "scorecard_gap",
                        "real_baseline",
                        dimension_id,
                    ],
                )
                created += int(result.get("created") or 0)
                updated += int(result.get("updated") or 0)
                items.extend(result.get("items") or [])

            return {
                "ok": True,
                "schema": "octopus.agent_scorecard_gap_queue.v1",
                "created": created,
                "updated": updated,
                "total": created + updated,
                "items": items,
                "scorecard": {
                    "overall": report.get("overall"),
                    "verdict": report.get("verdict"),
                    "evidence_adjusted_overall": report.get(
                        "evidence_adjusted_overall",
                    ),
                        "below_target_count": len(report.get("octopus_below_target") or []),
                        "external_gap_count": len(
                            report.get("octopus_external_gap_dimensions") or []
                        ),
                        "focus_gap_count": len(report.get("octopus_focus_gaps") or []),
                        "surpass_summary": report.get("surpass_summary"),
                    },
                }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/browser-desktop-quality")
    def get_browser_desktop_quality() -> dict[str, Any]:
        try:
            from runtime.safety.evolution.browser_desktop_quality import (
                compute_browser_desktop_quality,
            )

            return {"ok": True, **compute_browser_desktop_quality()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/repo-context-quality")
    def get_repo_context_quality() -> dict[str, Any]:
        try:
            from runtime.safety.evolution.repo_context_quality import (
                compute_repo_context_quality,
            )

            return {"ok": True, **compute_repo_context_quality()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/permission-sandbox-quality")
    def get_permission_sandbox_quality() -> dict[str, Any]:
        try:
            from runtime.safety.evolution.permission_sandbox_quality import (
                compute_permission_sandbox_quality,
            )

            return {"ok": True, **compute_permission_sandbox_quality()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/product-experience-quality")
    def get_product_experience_quality() -> dict[str, Any]:
        try:
            from runtime.safety.evolution.product_experience_quality import (
                compute_product_experience_quality,
            )

            return {"ok": True, **compute_product_experience_quality()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/agent-loop-quality")
    def get_agent_loop_quality() -> dict[str, Any]:
        try:
            from runtime.safety.evolution.agent_loop_quality import (
                compute_agent_loop_quality,
            )

            return {"ok": True, **compute_agent_loop_quality()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/digital-employee-quality")
    def get_digital_employee_quality() -> dict[str, Any]:
        try:
            from runtime.safety.evolution.digital_employee_quality import (
                compute_digital_employee_quality,
            )

            return {"ok": True, **compute_digital_employee_quality()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/automation-radar")
    def get_automation_radar(
        target_score: int = Query(default=95, ge=1, le=100),
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.automation_radar import (
                compute_automation_radar,
            )

            return {
                "ok": True,
                **compute_automation_radar(target_score=target_score),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/automation-policy-rule-drafts")
    def get_automation_policy_rule_drafts(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.policy_review_rules import (
                build_automation_policy_rule_drafts,
                verify_policy_review_rule_draft,
            )

            report = build_automation_policy_rule_drafts(limit=limit)
            report["verified"] = sum(
                1
                for draft in report.get("drafts") or []
                if verify_policy_review_rule_draft(draft).get("ok") is True
            )
            return {"ok": True, **report}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/automation-policy-rule-drafts/install")
    def install_automation_policy_rule_draft(
        request: Request,
        body: AutomationPolicyRuleInstallBody,
    ) -> dict[str, Any]:
        try:
            from runtime.platform.process.paths import app_paths
            from runtime.safety.evolution.governance_audit import (
                append_governance_audit_event,
            )
            from runtime.safety.evolution.policy_review_rules import (
                build_automation_policy_rule_drafts,
                install_policy_review_rule_draft,
            )

            report = build_automation_policy_rule_drafts(limit=body.limit)
            draft = next(
                (
                    item for item in report.get("drafts") or []
                    if isinstance(item, dict)
                    and str(item.get("draft_id") or "") == body.draft_id
                ),
                None,
            )
            if draft is None:
                raise HTTPException(404, "automation policy rule draft not found")
            result = install_policy_review_rule_draft(
                draft,
                policy_path=app_paths().permissions_path,
                confirm_install=body.confirm_install,
            )
            append_governance_audit_event(
                event_type="automation_policy_rule_install",
                target="approval_policy",
                status="installed",
                artifact=result,
                decision_context={
                    "schema": "octopus.automation_policy_rule_install_context.v1",
                    "actor": _actor_from_request(request),
                    "draft_id": body.draft_id,
                    "source": "evolution_router",
                },
                audit_path=app_paths().promotion_audit_path,
            )
            return {"ok": True, **result}
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/browser-desktop-repair-recipes")
    def get_browser_desktop_repair_recipes(
        limit: int = Query(default=1000, ge=1, le=5000),
        min_occurrences: int = Query(default=1, ge=1, le=20),
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.browser_desktop_repair_recipes import (
                compute_browser_desktop_repair_recipes,
            )

            return {
                "ok": True,
                **compute_browser_desktop_repair_recipes(
                    limit=limit,
                    min_occurrences=min_occurrences,
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/browser-desktop-repair-recipes/queue")
    def queue_browser_desktop_repair_recipes(
        body: BrowserDesktopRepairRecipeQueueBody | None = None,
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.browser_desktop_repair_recipes import (
                queue_browser_desktop_repair_recipes,
            )

            body = body or BrowserDesktopRepairRecipeQueueBody()
            return {
                "ok": True,
                **queue_browser_desktop_repair_recipes(
                    limit=body.limit,
                    min_occurrences=body.min_occurrences,
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/browser-desktop-repair-recipes/stale-artifacts/reject")
    def reject_stale_browser_desktop_replay_artifacts(
        body: BrowserDesktopStaleArtifactRejectionBody | None = None,
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.browser_desktop_repair_recipes import (
                reject_stale_browser_desktop_replay_artifacts,
            )

            body = body or BrowserDesktopStaleArtifactRejectionBody()
            return {
                "ok": True,
                **reject_stale_browser_desktop_replay_artifacts(limit=body.limit),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/browser-desktop-repair-recipes/verifications")
    def get_browser_desktop_repair_recipe_verifications(
        limit: int = Query(default=1000, ge=1, le=5000),
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.browser_desktop_repair_recipes import (
                compute_browser_desktop_repair_recipe_verifications,
            )

            return {
                "ok": True,
                **compute_browser_desktop_repair_recipe_verifications(limit=limit),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/browser-desktop-repair-recipes/verifications/evidence")
    def attach_browser_desktop_repair_recipe_evidence(
        body: BrowserDesktopRepairRecipeEvidenceBody,
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.browser_desktop_repair_recipes import (
                attach_browser_desktop_repair_recipe_evidence,
            )

            return {
                "ok": True,
                **attach_browser_desktop_repair_recipe_evidence(
                    item_id=body.item_id,
                    passed=body.passed,
                    provided=body.provided,
                    artifacts=body.artifacts,
                    notes=body.notes,
                    actor=body.actor,
                ),
            }
        except KeyError as exc:
            return {"ok": False, "error": f"recipe item not found: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/browser-desktop-repair-recipes/verifications/rerun")
    def rerun_browser_desktop_repair_recipe_evidence(
        body: BrowserDesktopRepairRecipeRerunBody,
        request: Request,
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.browser_desktop_repair_recipes import (
                rerun_browser_desktop_repair_recipe_evidence,
            )

            api_base_url = _resolve_api_base_url(
                body.api_base_url,
                request=request,
            )
            return {
                "ok": True,
                **rerun_browser_desktop_repair_recipe_evidence(
                    item_id=body.item_id,
                    api_base_url=api_base_url,
                    promote_source_cases=body.promote_source_cases,
                    actor=body.actor,
                ),
            }
        except KeyError as exc:
            return {"ok": False, "error": f"recipe item not found: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/browser-desktop-repair-recipes/verifications/rerun-batch")
    def rerun_browser_desktop_repair_recipe_batch(
        request: Request,
        body: BrowserDesktopRepairRecipeRerunBatchBody | None = None,
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.browser_desktop_repair_recipes import (
                rerun_browser_desktop_repair_recipe_batch,
            )

            body = body or BrowserDesktopRepairRecipeRerunBatchBody()
            api_base_url = _resolve_api_base_url(
                body.api_base_url,
                request=request,
            )
            return {
                "ok": True,
                **rerun_browser_desktop_repair_recipe_batch(
                    api_base_url=api_base_url,
                    promote_source_cases=body.promote_source_cases,
                    actor=body.actor,
                    limit=body.limit,
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/repair-route-quality")
    def get_repair_route_quality(
        limit: int = Query(default=1000, ge=1, le=5000),
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.repair_route_quality import (
                compute_repair_route_quality,
            )

            return {"ok": True, **compute_repair_route_quality(limit=limit)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/repair-route-quality/promotions/queue")
    def queue_repair_route_promotions(
        body: RepairRoutePromotionQueueBody | None = None,
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.repair_route_quality import (
                queue_repair_route_promotion_candidates,
            )

            body = body or RepairRoutePromotionQueueBody()
            return {
                "ok": True,
                **queue_repair_route_promotion_candidates(limit=body.limit),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/auto-verifier-metrics")
    def get_auto_verifier_metrics(
        limit: int = Query(default=1000, ge=1, le=5000),
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.auto_verifier_metrics import (
                summarize_auto_verifier_metrics,
            )

            return {"ok": True, **summarize_auto_verifier_metrics(limit=limit)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/auto-verifier-metrics/drift/queue")
    def queue_auto_verifier_drift(
        body: VerifierDriftQueueBody | None = None,
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.auto_verifier_metrics import (
                queue_verifier_drift_backlog,
            )

            body = body or VerifierDriftQueueBody()
            return {
                "ok": True,
                **queue_verifier_drift_backlog(limit=body.limit),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/subagent-fitness")
    def get_subagent_fitness(
        role: str | None = Query(default=None),
        limit: int = Query(default=2000, ge=1, le=5000),
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.subagent_fitness import (
                compute_subagent_fitness,
            )

            return {"ok": True, **compute_subagent_fitness(role=role, limit=limit)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.get("/subagent-policy")
    def get_subagent_policy() -> dict[str, Any]:
        try:
            from runtime.safety.evolution.subagent_policy import SubagentPolicyStore

            return {"ok": True, **SubagentPolicyStore().summary()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/subagent-policy/{role}/decision")
    def decide_subagent_policy(
        role: str,
        body: SubagentPolicyDecisionBody,
    ) -> dict[str, Any]:
        try:
            from runtime.safety.evolution.subagent_policy import SubagentPolicyStore

            result = SubagentPolicyStore().decide(
                role,
                action=body.action,
                reason=body.reason,
                evidence_item_ids=body.evidence_item_ids,
                actor=body.actor,
            )
            return {"ok": True, **result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

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
                "governance": {
                    "score": report.governance.score,
                    "penalty": report.governance.penalty,
                    "audit_total": report.governance.audit_total,
                    "recent_total": report.governance.recent_total,
                    "override_count": report.governance.override_count,
                    "gate_failed_count": report.governance.gate_failed_count,
                    "gate_blocked_override_count": (
                        report.governance.gate_blocked_override_count
                    ),
                    "failed_apply_count": report.governance.failed_apply_count,
                    "reasons": report.governance.reasons,
                } if report.governance else None,
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
            state = cm.force_rollback(skill_name, reason="manual API rollback")
            if state is None:
                return {"ok": False, "error": "skill not in canary"}
            return {"ok": True, "skill_name": skill_name, "phase": state.phase.value}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    return router


def _scorecard_gap_priority(gap: int) -> str:
    if gap >= 10:
        return "P0"
    if gap >= 5:
        return "P1"
    return "P2"


def _actor_from_request(request: Any) -> str:
    return str(getattr(getattr(request, "state", None), "actor_id", "") or "local_operator")


def _resolve_api_base_url(value: str | None, *, request: Request | None) -> str:
    explicit = _normalize_api_base_url(value)
    if explicit:
        return explicit
    for env_name in (
        "OCTOPUS_INTERNAL_GATEWAY_BASE_URL",
        "OCTOPUS_BACKEND_BASE_URL",
        "VITE_BACKEND_BASE_URL",
    ):
        from_env = _normalize_api_base_url(os.environ.get(env_name))
        if from_env:
            return from_env
    if request is not None:
        from_request = _normalize_api_base_url(str(request.base_url))
        if from_request:
            return from_request
    return "http://127.0.0.1:8000"


def _normalize_api_base_url(value: str | None) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def _scorecard_gap_text(row: dict[str, Any], *, reason: str) -> str:
    scores = row.get("scores") if isinstance(row.get("scores"), dict) else {}
    adjusted = (
        row.get("evidence_adjusted_scores")
        if isinstance(row.get("evidence_adjusted_scores"), dict)
        else {}
    )
    actions = [
        str(action)
        for action in row.get("octopus_next_actions") or []
        if action
    ]
    lines = [
        f"Real baseline gap for `{row.get('title') or row.get('id')}`.",
        (
            f"Octopus baseline: {scores.get('octopus', 0)}; "
            f"target gap: {row.get('octopus_gap_to_target', 0)}; "
            f"effective gap: {row.get('octopus_gap_to_effective_target', 0)}."
        ),
        (
            "Best external: "
            f"{row.get('best_external_competitor', 'unknown')} "
            f"{row.get('best_external_score', 0)}; "
            f"surpass target: {row.get('surpass_target_score', 0)}; "
            f"surpass gap: {row.get('octopus_gap_to_surpass', 0)}."
        ),
    ]
    if adjusted:
        lines.append(
            "Internal evidence-adjusted score: "
            f"{adjusted.get('octopus', row.get('octopus_evidence_adjusted_score', 0))}."
        )
    if actions:
        lines.append("Next actions:")
        lines.extend(f"- {action}" for action in actions[:3])
    if reason:
        lines.append(f"Reason: {reason[:500]}")
    return "\n".join(lines)

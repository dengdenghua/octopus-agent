"""Evolution operator console control-plane routes.

The core self-evolution loop already exposes real learned rules via the
observability router. The frontend operator console, however, also expects a
broader set of control-plane endpoints for budgets, proposal queues, protocol
drift, and RecipeForge. These handlers derive as much state as possible from
the runtime Journal and return explicit disabled/no-op responses for subsystems
that are not configured.

When the full Reflex/RecipeForge admin router is mounted earlier in the app,
FastAPI will match those real routes first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment,misc]
    Header = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    Query = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]

from runtime.sensing._fastapi_guard import require_fastapi

from ._evolution_ops_insights import (
    evolution_learning_curve_payload,
    evolution_memory_growth_payload,
    evolution_overview_payload,
    evolution_recommendations_payload,
    evolution_story_payload,
)
from .evolution_ops import (
    _budget_snapshot,
    _csv_response,
    _curriculum_goal_rows,
    _dispatch_snapshot,
    _forge_addendums_csv_rows,
    _forge_addendums_snapshot,
    _forge_applied_snapshot,
    _forge_apply_candidate,
    _forge_auto_promote,
    _forge_auto_propose,
    _forge_auto_tick_disable,
    _forge_auto_tick_enable,
    _forge_auto_tick_run_now,
    _forge_auto_tick_status,
    _forge_delete_addendum,
    _forge_delete_variant,
    _forge_recipes_snapshot,
    _forge_run_optimizer,
    _forge_runs_csv_rows,
    _forge_runs_snapshot,
    _forge_variant_stats,
    _forge_variant_weights,
    _forge_variants_snapshot,
    _framework_benchmark_rows,
    _iso,
    _learn_from_intel_result,
    _mcp_proposal_rows,
    _model_benchmark_rows,
    _model_payload,
    _protocol_drift_rows,
    _protocol_repair_rows,
    _registry_skill_is_auto,
    _skill_candidate_to_proposal,
    _skill_forge_candidates,
    _skill_performance_rows,
    _skill_step_rows,
    _write_budget_breaker_reset,
    _write_curriculum_goal_decision,
    _write_mcp_proposal_decision,
    _write_protocol_drift_decision,
    _write_skill_proposal_decision,
)


def create_evolution_ops_router(
    *,
    journal: Any = None,
    registry: Any = None,
    planner: Any = None,
    thread_store: Any = None,
    forged_skill_dir: Path | str | None = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    jwt_leeway_seconds: int = 0,
) -> Any:
    """Create evolution operator control-plane routes.

    The write endpoints in this router (skill proposal approve/reject,
    forge run/apply, forge auto-tick enable, MCP proposal install,
    breaker reset, etc.) materially mutate registry state and can
    install code from network-supplied recipes. In authenticated mode,
    these control-plane paths require an operator/admin identity. The
    explicit local ``require_auth=False`` mode remains available for
    isolated desktop and test runtimes.
    """
    require_fastapi(__name__)

    router = APIRouter(tags=["evolution-ops"])
    local_suppressed_skill_proposals: set[str] = set()

    def _require_actor(request: Any) -> str | None:
        """Require an operator for writes when shared auth is enabled."""
        try:
            from runtime.safety.auth.principal import require_operator

            principal = require_operator(
                request,
                identity_store,
                require_auth,
                jwt_secret=jwt_secret,
                jwt_issuer=jwt_issuer,
                jwt_audience=jwt_audience,
                jwt_leeway_seconds=jwt_leeway_seconds,
            )
            return principal.actor_id if principal is not None else None
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            if require_auth:
                raise HTTPException(401, "auth required") from exc
            return None

    @router.get("/api/evolution/overview")
    def evolution_overview() -> dict[str, Any]:
        return evolution_overview_payload(journal, registry, planner)

    @router.get("/api/evolution/story")
    def evolution_story(
        limit: int = Query(default=8, ge=1, le=30),
    ) -> dict[str, Any]:
        """Plain-language evidence for what the system actually learned.

        Trajectories are observations, not evolution outcomes. This endpoint
        keeps them separate from durable planner rules, memories, and forged
        skills so the UI cannot imply that merely running a task changed the
        agent's future behaviour.
        """
        return evolution_story_payload(
            journal,
            registry,
            planner,
            thread_store,
            limit=limit,
        )

    @router.get("/api/evolution/skills/history")
    def evolution_skill_history(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in _skill_step_rows(journal):
            rows.append(
                {
                    "timestamp": _iso(item["ts"]),
                    "skill_name": item["skill_name"],
                    "source_task": item["task_id"],
                    "trigger": (
                        "auto"
                        if _registry_skill_is_auto(registry, item["skill_name"])
                        else "manual"
                    ),
                    "success_rate": 1.0 if item["success"] else 0.0,
                }
            )
        rows.sort(key=lambda r: r["timestamp"], reverse=True)
        return rows[:limit]

    @router.get("/api/evolution/skills/performance")
    def evolution_skill_performance() -> list[dict[str, Any]]:
        return _skill_performance_rows(journal, registry)

    @router.post("/api/evolution/skills/forge-from-task")
    def forge_skill_from_task(body: dict[str, Any] | None = None) -> dict[str, Any]:
        task_id = str((body or {}).get("task_id") or "").strip()
        if not task_id:
            return {
                "ok": False,
                "status": "missing_task_id",
                "promoted": [],
                "quarantined": [],
            }
        if journal is None or registry is None:
            return {
                "ok": False,
                "status": "no_runtime",
                "task_id": task_id,
                "promoted": [],
                "quarantined": [],
            }

        try:
            from runtime.memory.journal.journal import TrajectoryEvent
            from runtime.safety.recovery.skill_forge import SkillForge
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, f"forge unavailable: {exc}") from exc

        trajectories = [
            event.trajectory
            for event in journal.read_by_type("trajectory")
            if isinstance(event, TrajectoryEvent)
            and str(getattr(event.trajectory, "task_id", "")) == task_id
            and getattr(event.trajectory.outcome, "success", False)
        ]
        if not trajectories:
            return {
                "ok": False,
                "status": "no_successful_trajectory",
                "task_id": task_id,
                "promoted": [],
                "quarantined": [],
                "step_count": 0,
            }

        result = SkillForge(journal=journal, registry=registry).forge_selected(trajectories)
        status = (
            "promoted"
            if result.promoted
            else "quarantined"
            if result.quarantined
            else "shadow_failed"
            if result.shadow_failed
            else "no_candidate"
        )
        return {
            "ok": bool(result.promoted),
            "status": status,
            "task_id": task_id,
            "promoted": list(result.promoted),
            "quarantined": list(result.quarantined),
            "candidates_total": result.candidates_total,
            "step_count": sum(trajectory.step_count for trajectory in trajectories),
        }

    @router.get("/api/evolution/memory/growth")
    def evolution_memory_growth(
        days: int = Query(default=30, ge=1, le=365),
    ) -> list[dict[str, Any]]:
        return evolution_memory_growth_payload(
            journal,
            registry,
            planner,
            days=days,
        )

    @router.get("/api/evolution/learning-curve")
    def evolution_learning_curve(
        weeks: int = Query(default=12, ge=1, le=104),
    ) -> list[dict[str, Any]]:
        return evolution_learning_curve_payload(journal, weeks=weeks)

    @router.get("/api/evolution/recommendations")
    def evolution_recommendations() -> list[dict[str, Any]]:
        return evolution_recommendations_payload(journal, registry, planner)

    @router.post("/api/evolution/learn-from-intel")
    def evolution_learn_from_intel(request: Request) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        return _learn_from_intel_result(
            journal,
            planner,
            registry,
            suppressed_names=local_suppressed_skill_proposals,
        )

    @router.get("/api/evolution/budget/snapshot")
    def budget_snapshot() -> dict[str, Any]:
        return _budget_snapshot(journal)

    @router.post("/api/evolution/budget/breaker/reset")
    def reset_budget_breaker(
        request: Request, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        component = str((body or {}).get("component") or "").strip()
        if not component:
            return {"ok": False, "component": None, "source": "journal"}
        _write_budget_breaker_reset(
            journal,
            component=component,
            reason=str((body or {}).get("reason") or "operator_reset"),
        )
        return {"ok": True, "component": component, "source": "journal"}

    @router.get("/api/intel-evolution/skills/proposals")
    def skill_proposals(status: str | None = None) -> list[dict[str, Any]]:
        if status and status != "pending":
            return []
        return [
            _skill_candidate_to_proposal(candidate)
            for candidate in _skill_forge_candidates(
                journal,
                registry,
                suppressed_names=local_suppressed_skill_proposals,
            )
        ]

    @router.post("/api/intel-evolution/skills/proposals/approve")
    def approve_skill_proposal(
        request: Request, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        proposal_name = str((body or {}).get("name") or "").strip()
        if not proposal_name:
            return {"ok": False, "status": "missing_name", "proposal": body or {}}

        try:
            from runtime.execution.suckers import SkillTestsFailed
            from runtime.safety.recovery.skill_forge import SkillForge
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "status": "unavailable",
                "name": proposal_name,
                "error": str(exc),
            }

        candidates = _skill_forge_candidates(
            journal,
            registry,
            suppressed_names=local_suppressed_skill_proposals,
        )
        candidate = next((c for c in candidates if c.name == proposal_name), None)
        if candidate is None:
            return {"ok": False, "status": "not_found", "name": proposal_name}

        try:
            forge = SkillForge(journal=journal, registry=registry)
            passed, shadow_report = forge.shadow_validate(candidate)
            if not passed:
                local_suppressed_skill_proposals.add(candidate.name)
                _write_skill_proposal_decision(
                    journal,
                    proposal_name=candidate.name,
                    candidate_id=candidate.candidate_id,
                    decision="shadow_failed",
                    reason=str((body or {}).get("reason") or ""),
                    details={
                        "report": _model_payload(shadow_report),
                        "underlying_sequence": candidate.underlying_sequence,
                    },
                )
                return {
                    "ok": False,
                    "status": "shadow_failed",
                    "name": candidate.name,
                    "candidate_id": candidate.candidate_id,
                    "report": _model_payload(shadow_report),
                }

            forge = SkillForge(
                journal=journal,
                registry=registry,
                auto_persist_dir=forged_skill_dir,
            )
            promote_report = forge.promote_to_public(candidate)
            forge._maybe_persist(candidate)
        except SkillTestsFailed as exc:
            local_suppressed_skill_proposals.add(candidate.name)
            _write_skill_proposal_decision(
                journal,
                proposal_name=candidate.name,
                candidate_id=candidate.candidate_id,
                decision="promote_failed",
                reason=str((body or {}).get("reason") or ""),
                details={"error": str(exc)},
            )
            return {
                "ok": False,
                "status": "promote_failed",
                "name": candidate.name,
                "candidate_id": candidate.candidate_id,
                "error": str(exc),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "status": "error",
                "name": candidate.name,
                "candidate_id": candidate.candidate_id,
                "error": str(exc),
            }

        _write_skill_proposal_decision(
            journal,
            proposal_name=candidate.name,
            candidate_id=candidate.candidate_id,
            decision="promoted",
            reason=str((body or {}).get("reason") or ""),
            details={
                "report": _model_payload(promote_report),
                "underlying_sequence": candidate.underlying_sequence,
                "source_sample_count": candidate.source_sample_count,
                "source_success_rate": candidate.source_success_rate,
            },
        )
        return {
            "ok": True,
            "status": "promoted",
            "name": candidate.name,
            "candidate_id": candidate.candidate_id,
            "report": _model_payload(promote_report),
        }

    @router.post("/api/intel-evolution/skills/proposals/reject")
    def reject_skill_proposal(
        request: Request, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        proposal_name = str((body or {}).get("name") or "").strip()
        if proposal_name:
            local_suppressed_skill_proposals.add(proposal_name)
            _write_skill_proposal_decision(
                journal,
                proposal_name=proposal_name,
                decision="rejected",
                reason=str((body or {}).get("reason") or ""),
            )
        return {
            "ok": True,
            "status": "rejected",
            "name": proposal_name or None,
            "proposal": body or {},
        }

    @router.get("/api/intel-evolution/models/proposals")
    def model_proposals() -> list[dict[str, Any]]:
        return _model_benchmark_rows(journal)

    @router.post("/api/intel-evolution/models/benchmarks/run")
    def run_model_benchmarks(request: Request) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        rows = _model_benchmark_rows(journal)
        return {
            "ok": True,
            "created": len(rows),
            "source": "journal",
            "proposals": rows,
            "message": (
                "Benchmarks are derived from recorded token_usage events "
                "joined with trajectory outcomes."
            ),
        }

    @router.get("/api/intel-evolution/mcp/proposals")
    def mcp_proposals() -> list[dict[str, Any]]:
        return _mcp_proposal_rows(journal)

    @router.post("/api/intel-evolution/mcp/proposals/vet")
    def vet_mcp_proposals(request: Request, body: dict[str, Any] | None = None) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        payload = body or {}
        requested = str(payload.get("server_name") or "").strip()
        proposals = _mcp_proposal_rows(journal)
        targets = [
            proposal
            for proposal in proposals
            if proposal["status"] == "pending_vet"
            and (not requested or proposal["server_name"] == requested)
        ]
        for proposal in targets:
            _write_mcp_proposal_decision(
                journal,
                server_name=proposal["server_name"],
                status="vetted",
                reason=str(payload.get("reason") or "operator_vet"),
                details={
                    "risk_level": proposal.get("risk_level"),
                    "suggested_cmd": proposal.get("suggested_cmd"),
                    "failure_count": proposal.get("failure_count"),
                },
            )
        return {"ok": True, "vetted": len(targets), "source": "journal"}

    @router.post("/api/intel-evolution/mcp/proposals/install")
    def install_mcp_proposal(
        request: Request, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        server_name = str((body or {}).get("server_name") or "").strip()
        proposal = next(
            (row for row in _mcp_proposal_rows(journal) if row["server_name"] == server_name),
            None,
        )
        if proposal is not None and proposal.get("status") == "vetted":
            _write_mcp_proposal_decision(
                journal,
                server_name=server_name,
                status="install_requested",
                reason="manual_install_required",
                details={
                    "suggested_cmd": proposal.get("suggested_cmd"),
                    "risk_level": proposal.get("risk_level"),
                },
            )
            return {
                "ok": True,
                "installed": False,
                "status": "install_requested",
                "server_name": server_name,
                "reason": (
                    "External MCP installation requires manual confirmation in Settings > MCP."
                ),
                "source": "journal",
            }
        return {
            "ok": False,
            "server_name": server_name or None,
            "reason": "No vetted MCP proposal is available.",
            "source": "journal",
        }

    @router.get("/api/evolution/curriculum/goals")
    def curriculum_goals(status: str | None = None) -> list[dict[str, Any]]:
        return _curriculum_goal_rows(journal, status=status)

    @router.post("/api/evolution/curriculum/cycle/run")
    def run_curriculum_cycle(request: Request) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        goals = _curriculum_goal_rows(journal, status="pending")
        return {"ok": True, "created": len(goals), "source": "journal"}

    @router.post("/api/evolution/curriculum/goals/decide")
    def decide_curriculum_goal(
        request: Request, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        payload = body or {}
        try:
            goal_id = int(payload.get("goal_id") or 0)
        except (TypeError, ValueError):
            goal_id = 0
        next_status = str(payload.get("status") or "").strip()
        if goal_id <= 0 or not next_status:
            return {
                "ok": False,
                "status": "invalid_request",
                "decision": payload,
                "source": "journal",
            }

        goals = _curriculum_goal_rows(journal, status=None)
        goal = next((row for row in goals if int(row["id"]) == goal_id), None)
        if goal is None:
            return {
                "ok": False,
                "status": "not_found",
                "goal_id": goal_id,
                "decision": payload,
                "source": "journal",
            }

        _write_curriculum_goal_decision(
            journal,
            goal_id=goal_id,
            cluster_key=str(goal["cluster_key"]),
            status=next_status,
            covered_by=payload.get("covered_by"),
            reason=str(payload.get("reason") or ""),
            details={"title": goal["title"], "category": goal["category"]},
        )
        return {
            "ok": True,
            "status": next_status,
            "goal_id": goal_id,
            "cluster_key": goal["cluster_key"],
            "decision": payload,
            "source": "journal",
        }

    @router.get("/api/intel-evolution/frameworks/benchmarks")
    def framework_benchmarks() -> list[dict[str, Any]]:
        return _framework_benchmark_rows(journal)

    @router.get("/api/intel-evolution/protocols/drift")
    def protocol_drift(acknowledged: bool | None = None) -> list[dict[str, Any]]:
        return _protocol_drift_rows(journal, acknowledged=acknowledged)

    @router.get("/api/intel-evolution/protocols/repair/proposals")
    def protocol_repair_proposals(status: str | None = None) -> list[dict[str, Any]]:
        return _protocol_repair_rows(journal, status=status)

    @router.post("/api/intel-evolution/protocols/drift/scan")
    def scan_protocol_drift(request: Request) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        rows = _protocol_drift_rows(journal, acknowledged=None)
        return {"ok": True, "events": len(rows), "source": "journal"}

    @router.post("/api/intel-evolution/protocols/repair/sweep")
    def sweep_protocol_repairs(request: Request) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        rows = _protocol_repair_rows(journal, status="pending")
        return {"ok": True, "proposals": len(rows), "source": "journal"}

    @router.post("/api/intel-evolution/protocols/drift/{drift_id}/acknowledge")
    def acknowledge_protocol_drift(request: Request, drift_id: int) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        row = next(
            (
                item
                for item in _protocol_drift_rows(journal, acknowledged=None)
                if int(item["id"]) == drift_id
            ),
            None,
        )
        if row is None:
            return {"ok": False, "id": drift_id, "acknowledged": False}
        _write_protocol_drift_decision(
            journal,
            drift_id=drift_id,
            protocol_id=str(row["protocol_id"]),
            status="acknowledged",
            reason="operator_acknowledged",
            details={"summary": row["summary"]},
        )
        return {"ok": True, "id": drift_id, "acknowledged": True}

    @router.get("/api/evolution/dispatch/snapshot")
    def dispatch_snapshot() -> dict[str, Any]:
        return _dispatch_snapshot(journal)

    # RecipeForge aliases. The full Reflex admin router registers the same
    # paths when available; these handlers keep the operator console wired to
    # the same GEPA/RecipeForge modules when only this router is mounted.
    @router.get("/api/evolution/forge/applied")
    def forge_applied() -> dict[str, Any]:
        return _forge_applied_snapshot()

    @router.get("/api/evolution/forge/runs")
    def forge_runs(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
        return _forge_runs_snapshot(limit=limit)

    @router.get("/api/evolution/forge/addendums")
    def forge_addendums() -> dict[str, Any]:
        return _forge_addendums_snapshot()

    @router.get("/api/evolution/forge/recipes")
    def forge_recipes() -> dict[str, Any]:
        return _forge_recipes_snapshot()

    @router.get("/api/evolution/forge/auto-tick/status")
    def forge_auto_tick_status() -> dict[str, Any]:
        return _forge_auto_tick_status()

    @router.post("/api/evolution/forge/auto-tick/enable")
    def forge_auto_tick_enable(
        interval_hours: float = Query(default=24, ge=0.1, le=24 * 30),
        min_uses: int = Query(default=20, ge=1, le=1000),
        min_lead: float = Query(default=0.15, ge=0, le=1),
        x_human_approver: str | None = Header(default=None, alias="X-Human-Approver"),
    ) -> dict[str, Any]:
        return _forge_auto_tick_enable(
            journal=journal,
            interval_hours=interval_hours,
            min_uses=min_uses,
            min_lead=min_lead,
            approver=x_human_approver,
        )

    @router.post("/api/evolution/forge/auto-tick/disable")
    def forge_auto_tick_disable(request: Request) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        return _forge_auto_tick_disable()

    @router.post("/api/evolution/forge/auto-tick/run-now")
    def forge_auto_tick_run_now(
        apply: bool = False,
        min_uses: int = Query(default=20, ge=1, le=1000),
        min_lead: float = Query(default=0.15, ge=0, le=1),
    ) -> dict[str, Any]:
        return _forge_auto_tick_run_now(
            journal=journal,
            apply=apply,
            min_uses=min_uses,
            min_lead=min_lead,
        )

    @router.post("/api/evolution/forge/run")
    def forge_run(
        n_iter: int = Query(default=8, ge=1, le=30),
        eval_tasks: int = Query(default=4, ge=1, le=20),
        recipe_id: str | None = Query(default=None),
        judge_model: str = Query(default="claude-sonnet-4-6"),
        mutator_model: str = Query(default="claude-sonnet-4-6"),
        optimizer_backend: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return _forge_run_optimizer(
            journal=journal,
            planner=planner,
            n_iter=n_iter,
            eval_tasks=eval_tasks,
            recipe_id=recipe_id,
            judge_model=judge_model,
            mutator_model=mutator_model,
            optimizer_backend=optimizer_backend,
        )

    @router.post("/api/evolution/forge/auto-propose")
    def forge_auto_propose(
        n_iter: int = Query(default=8, ge=1, le=30),
        eval_tasks: int = Query(default=4, ge=1, le=20),
        max_recipes: int = Query(default=3, ge=1, le=20),
        judge_model: str = Query(default="claude-sonnet-4-6"),
        mutator_model: str = Query(default="claude-sonnet-4-6"),
    ) -> dict[str, Any]:
        return _forge_auto_propose(
            journal=journal,
            planner=planner,
            n_iter=n_iter,
            eval_tasks=eval_tasks,
            max_recipes=max_recipes,
            judge_model=judge_model,
            mutator_model=mutator_model,
        )

    @router.post("/api/evolution/forge/apply")
    def forge_apply(
        body: dict[str, Any] | None = None,
        x_human_approver: str | None = Header(default=None, alias="X-Human-Approver"),
    ) -> dict[str, Any]:
        return _forge_apply_candidate(body or {}, approver=x_human_approver)

    @router.delete("/api/evolution/forge/addendums/{recipe_id:path}")
    def forge_delete_addendum(
        recipe_id: str,
        x_human_approver: str | None = Header(default=None, alias="X-Human-Approver"),
    ) -> dict[str, Any]:
        return _forge_delete_addendum(recipe_id, approver=x_human_approver)

    @router.get("/api/evolution/forge/variants/{recipe_id:path}/stats")
    def forge_variant_stats(recipe_id: str) -> dict[str, Any]:
        return _forge_variant_stats(journal=journal, recipe_id=recipe_id)

    @router.post("/api/evolution/forge/variants/{recipe_id:path}/auto-promote")
    def forge_auto_promote(
        recipe_id: str,
        min_uses: int = Query(default=10, ge=1, le=1000),
        min_lead: float = Query(default=0.10, ge=0, le=1),
        apply: bool = False,
    ) -> dict[str, Any]:
        return _forge_auto_promote(
            journal=journal,
            recipe_id=recipe_id,
            min_uses=min_uses,
            min_lead=min_lead,
            apply=apply,
        )

    @router.post("/api/evolution/forge/variants/{recipe_id:path}/weights")
    def forge_variant_weights(
        recipe_id: str,
        body: dict[str, Any] | None = None,
        x_human_approver: str | None = Header(default=None, alias="X-Human-Approver"),
    ) -> dict[str, Any]:
        return _forge_variant_weights(
            recipe_id,
            body or {},
            approver=x_human_approver,
        )

    @router.delete("/api/evolution/forge/variants/{recipe_id:path}/{variant_id}")
    def forge_delete_variant(
        recipe_id: str,
        variant_id: str,
        x_human_approver: str | None = Header(default=None, alias="X-Human-Approver"),
    ) -> dict[str, Any]:
        return _forge_delete_variant(
            recipe_id,
            variant_id,
            approver=x_human_approver,
        )

    @router.get("/api/evolution/forge/variants/{recipe_id:path}")
    def forge_variants(recipe_id: str) -> dict[str, Any]:
        return _forge_variants_snapshot(recipe_id)

    @router.get("/api/evolution/forge/runs.csv")
    def forge_runs_csv() -> Any:
        return _csv_response(
            [
                "ts",
                "iso_ts",
                "trigger",
                "recipe_id",
                "iterations_run",
                "elapsed_s",
                "front_size",
                "best_candidate_id",
                "best_avg_score",
                "applied",
                "applied_at",
                "winner_lifecycle_state",
                "winner_proposal_id",
                "winner_canary_phase",
                "winner_rollback_reason",
                "best_rationale",
            ],
            _forge_runs_csv_rows(),
        )

    @router.get("/api/evolution/forge/addendums.csv")
    def forge_addendums_csv() -> Any:
        return _csv_response(
            ["scope", "recipe_id", "path", "size_bytes", "mtime", "iso_mtime", "preview"],
            _forge_addendums_csv_rows(),
        )

    return router


__all__ = ["create_evolution_ops_router"]

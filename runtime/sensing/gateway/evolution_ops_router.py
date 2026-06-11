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

from .evolution_ops import (
    _as_dt,
    _bounded_score,
    _budget_snapshot,
    _csv_response,
    _curriculum_goal_rows,
    _date_key,
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
    _knowledge_graph_overview,
    _learn_from_intel_result,
    _learned_section_counts,
    _mcp_proposal_rows,
    _model_benchmark_rows,
    _model_payload,
    _protocol_drift_rows,
    _protocol_repair_rows,
    _registry_skill_is_auto,
    _registry_skill_names,
    _skill_candidate_to_proposal,
    _skill_forge_candidates,
    _skill_performance_rows,
    _skill_step_rows,
    _trajectory_rows,
    _utcnow,
    _week_key,
    _write_budget_breaker_reset,
    _write_curriculum_goal_decision,
    _write_mcp_proposal_decision,
    _write_protocol_drift_decision,
    _write_skill_proposal_decision,
)


def _intelligence_store_snapshot() -> dict[str, Any]:
    import json
    import os
    from pathlib import Path

    path = Path(os.environ.get("OCTOPUS_HOME", ".octopus")) / "intelligence.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}

    subscriptions = [
        item for item in raw.get("subscriptions", [])
        if isinstance(item, dict)
    ]
    reports = [
        item for item in raw.get("reports", [])
        if isinstance(item, dict)
    ]
    enabled = [
        item for item in subscriptions
        if item.get("enabled") is not False
    ]

    last_report_at = ""
    for report in reports:
        created_at = str(report.get("created_at") or "")
        if created_at > last_report_at:
            last_report_at = created_at

    return {
        "subscriptions": len(subscriptions),
        "enabled_subscriptions": len(enabled),
        "total_reports": len(reports),
        "last_report_at": last_report_at or None,
    }


def create_evolution_ops_router(
    *,
    journal: Any = None,
    registry: Any = None,
    planner: Any = None,
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
    install code from network-supplied recipes. They are **always
    auth-gated**: even when ``require_auth`` is False at the global
    level, these write paths require the caller to present a valid
    Bearer token resolved by ``identity_store``.
    """
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(tags=["evolution-ops"])
    local_suppressed_skill_proposals: set[str] = set()

    def _require_actor(request: Any) -> str | None:
        """Resolve the caller. Force-on for write endpoints regardless
        of the global ``require_auth`` flag — these routes mutate
        registry state and accept network-supplied recipe payloads.
        """
        try:
            from runtime.sensing.gateway.openai_gateway import _resolve_actor

            return _resolve_actor(
                request, identity_store, True,
                jwt_secret=jwt_secret,
                jwt_issuer=jwt_issuer,
                jwt_audience=jwt_audience,
                jwt_leeway_seconds=jwt_leeway_seconds,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(401, "auth required") from exc

    @router.get("/api/evolution/overview")
    def evolution_overview() -> dict[str, Any]:
        skill_perf = _skill_performance_rows(journal, registry)
        used_skill_rates = [
            float(row["success_rate"])
            for row in skill_perf
            if int(row["usage_count"]) > 0
        ]
        avg_success = (
            sum(used_skill_rates) / len(used_skill_rates)
            if used_skill_rates
            else 0.0
        )

        skill_names = _registry_skill_names(registry)
        auto_skills = [
            name for name in skill_names
            if _registry_skill_is_auto(registry, name)
        ]
        learned_counts = _learned_section_counts(planner)
        trajectory_rows = _trajectory_rows(journal)
        kg = _knowledge_graph_overview(journal)
        intelligence = _intelligence_store_snapshot()

        learning_events = (
            len(trajectory_rows)
            + learned_counts["rules"]
            + learned_counts["memories"]
            + len(auto_skills)
            + int(intelligence["total_reports"])
        )
        improvement_score = _bounded_score(
            avg_success * 0.55
            + min(1.0, len(trajectory_rows) / 25) * 0.25
            + min(1.0, learned_counts["rules"] / 10) * 0.10
            + min(1.0, len(auto_skills) / 8) * 0.10
            + min(1.0, int(intelligence["total_reports"]) / 12) * 0.05
        )

        return {
            "skills": {
                "total": len(skill_names),
                "auto_extracted": len(auto_skills),
                "manual": max(0, len(skill_names) - len(auto_skills)),
                "avg_success_rate": avg_success,
            },
            "memory": {
                "total_facts": learned_counts["memories"],
                "categories": {
                    "memories": learned_counts["memories"],
                    "rules": learned_counts["rules"],
                    "trajectories": len(trajectory_rows),
                },
            },
            "knowledge_graph": kg,
            "learning_events": learning_events,
            "improvement_score": improvement_score,
            "proactive_learning": {
                "enabled": int(intelligence["enabled_subscriptions"]) > 0,
                "is_running": False,
                "total_reports": intelligence["total_reports"],
                "subscriptions": intelligence["subscriptions"],
                "enabled_subscriptions": intelligence["enabled_subscriptions"],
                "last_report_at": intelligence["last_report_at"],
                "total_skills_created": len(auto_skills),
            },
            "source": "journal",
        }

    @router.get("/api/evolution/skills/history")
    def evolution_skill_history(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in _skill_step_rows(journal):
            rows.append({
                "timestamp": _iso(item["ts"]),
                "skill_name": item["skill_name"],
                "source_task": item["task_id"],
                "trigger": (
                    "auto"
                    if _registry_skill_is_auto(registry, item["skill_name"])
                    else "manual"
                ),
                "success_rate": 1.0 if item["success"] else 0.0,
            })
        rows.sort(key=lambda r: r["timestamp"], reverse=True)
        return rows[:limit]

    @router.get("/api/evolution/skills/performance")
    def evolution_skill_performance() -> list[dict[str, Any]]:
        return _skill_performance_rows(journal, registry)

    @router.get("/api/evolution/memory/growth")
    def evolution_memory_growth(
        days: int = Query(default=30, ge=1, le=365),
    ) -> list[dict[str, Any]]:
        from collections import defaultdict
        from datetime import timedelta

        by_day: dict[str, dict[str, int]] = defaultdict(
            lambda: {
                "fact": 0,
                "preference": 0,
                "learned_skill": 0,
                "relationship": 0,
            }
        )
        cutoff = _utcnow() - timedelta(days=days)
        for item in _skill_step_rows(journal):
            ts = item["ts"]
            if ts and ts >= cutoff:
                bucket = by_day[_date_key(ts)]
                if _registry_skill_is_auto(registry, item["skill_name"]):
                    bucket["learned_skill"] += 1
                else:
                    bucket["fact"] += 1

        learned = _learned_section_counts(planner)
        if learned["memories"] > 0:
            by_day[_date_key(_utcnow())]["fact"] += learned["memories"]
        if learned["rules"] > 0:
            by_day[_date_key(_utcnow())]["relationship"] += learned["rules"]

        return [
            {"date": day, **counts}
            for day, counts in sorted(by_day.items())
        ]

    @router.get("/api/evolution/learning-curve")
    def evolution_learning_curve(
        weeks: int = Query(default=12, ge=1, le=104),
    ) -> list[dict[str, Any]]:
        from collections import defaultdict
        from datetime import timedelta

        cutoff = _utcnow() - timedelta(weeks=weeks)
        buckets: dict[str, list[Any]] = defaultdict(list)
        for _event, traj in _trajectory_rows(journal):
            completed = _as_dt(getattr(traj, "completed_at", None))
            if completed is None or completed < cutoff:
                continue
            buckets[_week_key(completed)].append(traj)

        rows: list[dict[str, Any]] = []
        for week, trajs in sorted(buckets.items()):
            if not trajs:
                continue
            success_rate = (
                sum(1 for t in trajs if getattr(t.outcome, "success", False))
                / len(trajs)
            )
            durations = [
                max(
                    0.0,
                    (
                        (_as_dt(getattr(t, "completed_at", None)) or _utcnow())
                        - (_as_dt(getattr(t, "started_at", None)) or _utcnow())
                    ).total_seconds()
                    * 1000,
                )
                for t in trajs
            ]
            skill_count = sum(len(getattr(t, "steps", []) or []) for t in trajs)
            rows.append({
                "week": week,
                "success_rate": success_rate,
                "avg_duration_ms": (
                    sum(durations) / len(durations) if durations else 0
                ),
                "skills_used": skill_count,
            })
        return rows

    @router.get("/api/evolution/recommendations")
    def evolution_recommendations() -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []
        for row in _skill_performance_rows(journal, registry):
            usage = int(row["usage_count"])
            rate = float(row["success_rate"])
            if usage >= 3 and rate < 0.6:
                recommendations.append({
                    "type": "declining_skill",
                    "title": f"Review {row['name']}",
                    "description": (
                        f"{row['name']} succeeded on {rate:.0%} of "
                        f"{usage} recent calls. Check arguments, permissions, "
                        "or add a narrower recovery rule."
                    ),
                    "severity": "warning" if rate >= 0.35 else "critical",
                    "action_label": "Inspect failures",
                    "meta": {"skill_name": row["name"], "usage_count": usage},
                })

        learned = _learned_section_counts(planner)
        if learned["rules"] == 0 and len(_trajectory_rows(journal)) >= 3:
            recommendations.append({
                "type": "extraction_opportunity",
                "title": "Run reflection",
                "description": (
                    "Recent trajectories exist, but no learned mitigation "
                    "rules are active yet. Run the reflection pass to extract "
                    "repeatable lessons."
                ),
                "severity": "info",
                "action_label": "Reflect",
                "meta": {"trajectory_count": len(_trajectory_rows(journal))},
            })
        return recommendations[:12]

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
    def reset_budget_breaker(request: Request, body: dict[str, Any] | None = None) -> dict[str, Any]:
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
    def approve_skill_proposal(request: Request, body: dict[str, Any] | None = None) -> dict[str, Any]:
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
    def reject_skill_proposal(request: Request, body: dict[str, Any] | None = None) -> dict[str, Any]:
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
            proposal for proposal in proposals
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
    def install_mcp_proposal(request: Request, body: dict[str, Any] | None = None) -> dict[str, Any]:
        _actor = _require_actor(request)  # noqa: F841 — auth gate only
        server_name = str((body or {}).get("server_name") or "").strip()
        proposal = next(
            (
                row for row in _mcp_proposal_rows(journal)
                if row["server_name"] == server_name
            ),
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
                    "External MCP installation requires manual confirmation "
                    "in Settings > MCP."
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
    def decide_curriculum_goal(request: Request, body: dict[str, Any] | None = None) -> dict[str, Any]:
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
                item for item in _protocol_drift_rows(journal, acknowledged=None)
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

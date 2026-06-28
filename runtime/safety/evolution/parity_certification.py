from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root


@dataclass(frozen=True)
class CertificationRequirement:
    id: str
    title: str
    dimension_ids: tuple[str, ...]
    score_floor: int
    paths: tuple[str, ...]
    required_terms: tuple[str, ...]
    next_action: str
    kind: str = "parity"


REQUIREMENTS: tuple[CertificationRequirement, ...] = (
    CertificationRequirement(
        id="code_mode_verifier_loop",
        title="Code-mode verifier and repair loop",
        dimension_ids=("core_coding_loop", "repo_context"),
        score_floor=90,
        paths=(
            "runtime/safety/evolution/core_coding_loop_canary.py",
            "runtime/safety/evolution/core_coding_loop_readiness.py",
            "runtime/safety/evolution/auto_verifier.py",
            "runtime/safety/evolution/auto_verifier_metrics.py",
            "runtime/safety/evolution/repair_route_quality.py",
            "tests/test_core_coding_loop_canary.py",
            "tests/test_auto_verifier_metrics.py",
            "tests/test_repair_route_quality.py",
            "tests/test_post_write_diagnostics.py",
        ),
        required_terms=(
            "octopus.core_coding_loop_canary.v1",
            "run_core_coding_loop_canary",
            "compute_repair_route_quality",
            "auto_verifier_metrics",
            "post_write",
        ),
        next_action="Keep every code-mode edit tied to a verifier or repair route.",
    ),
    CertificationRequirement(
        id="browser_replay_gate_evidence",
        title="Browser failure replay-gate evidence",
        dimension_ids=("browser_desktop", "product_experience"),
        score_floor=90,
        paths=(
            "runtime/safety/replay/browser_pixel_assertions.py",
            "runtime/execution/suckers/browser_act_skills.py",
            "tests/test_browser_pixel_assertions.py",
            "tests/test_browser_artifact.py",
        ),
        required_terms=(
            "browser_pixel_replay_gate_case",
            "replay_gate_case",
            "browser_pixel_evidence_failed",
        ),
        next_action="Route visual browser regressions through replay-gate cases.",
    ),
    CertificationRequirement(
        id="operator_scorecard_drilldown",
        title="Operator scorecard drill-downs",
        dimension_ids=("product_experience",),
        score_floor=90,
        paths=(
            "frontend/src/components/workspace/agent-operator-panel.tsx",
            "frontend/src/components/workspace/agent-operator-panel.test.tsx",
        ),
        required_terms=(
            "Evidence checklist",
            "octopus_evidence_checklist",
            "scorecardError",
        ),
        next_action="Keep scorecard gaps keyboard-accessible and evidence-backed.",
    ),
    CertificationRequirement(
        id="permission_policy_review",
        title="Permission and policy review visibility",
        dimension_ids=("permissions_sandbox",),
        score_floor=90,
        paths=(
            "runtime/safety/evolution/policy_review_rules.py",
            "runtime/safety/evolution/permissions_sandbox_readiness.py",
            "runtime/safety/hooks/tool_edge_hooks.py",
            "frontend/src/components/workspace/agent-operator-panel.tsx",
            "tests/test_policy_review_rules.py",
            "tests/test_permissions_sandbox_readiness.py",
            "tests/test_tool_edge_hooks.py",
        ),
        required_terms=(
            "octopus.permissions_sandbox_readiness.v1",
            "default_runner_uses_selected_backend",
            "hard_backend_runtime_probe_pass",
            "octopus.permissions_sandbox_hard_runtime_probe.v1",
            "policy_review_rule",
            "soft_isolation",
            "signed",
            "deny",
        ),
        next_action="Keep high-risk tool classes covered by signed policy review rules.",
    ),
    CertificationRequirement(
        id="plugin_compatibility_guidance",
        title="Plugin compatibility and lifecycle guidance",
        dimension_ids=("extensions_hooks", "ecosystem_maturity"),
        score_floor=90,
        paths=(
            "runtime/sensing/gateway/plugins_router.py",
            "runtime/platform/plugins/codex_discovery.py",
            "tests/test_codex_plugin_smoke.py",
            "frontend/src/core/plugins/types.ts",
            "frontend/src/components/workspace/agent-operator-panel.tsx",
        ),
        required_terms=(
            "octopus.codex_plugin_compatibility.v1",
            "compatibility",
            "next_actions",
        ),
        next_action="Resolve default plugin review warnings before public release.",
    ),
    CertificationRequirement(
        id="operator_readiness_docs",
        title="Operator readiness documentation",
        dimension_ids=("ecosystem_maturity",),
        score_floor=90,
        paths=(
            "docs/guide/operator-readiness.md",
            "docs/guide/plugin-author-migration.md",
            "docs/index.md",
        ),
        required_terms=(
            "code mode",
            "permission review",
            "replay gate",
            "plugin",
            "migration",
            "release checklist",
        ),
        next_action="Keep operator docs in sync with scorecard evidence.",
    ),
    CertificationRequirement(
        id="code_mode_operational_excellence",
        title="Code-mode operational excellence",
        dimension_ids=("core_coding_loop", "repo_context"),
        score_floor=94,
        paths=(
            "runtime/safety/evolution/auto_verifier.py",
            "runtime/safety/evolution/auto_verifier_metrics.py",
            "runtime/safety/evolution/repair_route_quality.py",
            "runtime/sensing/gateway/realtime_turn_outcome.py",
            "tests/test_auto_verifier_metrics.py",
            "tests/test_repair_route_quality.py",
            "tests/test_post_write_diagnostics.py",
            "frontend/src/components/workspace/agent-operator-panel.tsx",
        ),
        required_terms=(
            "repair_route",
            "recent_decisions",
            "verification_plan",
        ),
        next_action="Keep verifier drift visible and repair-routed from the operator panel.",
        kind="operational_excellence",
    ),
    CertificationRequirement(
        id="code_mode_strict_lead",
        title="Code-mode strict lead evidence",
        dimension_ids=("core_coding_loop",),
        score_floor=97,
        paths=(
            "runtime/safety/evolution/core_coding_loop_readiness.py",
            "runtime/safety/evolution/auto_verifier.py",
            "runtime/safety/evolution/auto_verifier_metrics.py",
            "runtime/safety/evolution/repair_route_quality.py",
            "runtime/sensing/gateway/realtime_turn_outcome.py",
            "runtime/safety/hooks/tool_edge_hooks.py",
            "tests/test_core_coding_loop_readiness.py",
            "tests/test_auto_verifier_metrics.py",
            "tests/test_repair_route_quality.py",
            "tests/test_post_write_diagnostics.py",
        ),
        required_terms=(
            "octopus.core_coding_loop_readiness.v1",
            "rank_verification_commands",
            "post_write_regression_matrix",
            "repair_route_quality_gate",
            "primary_repair_route",
        ),
        next_action="Keep code-mode repair loops tied to verifier ranking, post-write diagnostics, and governed repair-route promotion.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="browser_operator_excellence",
        title="Browser and operator-loop excellence",
        dimension_ids=("browser_desktop", "product_experience"),
        score_floor=94,
        paths=(
            "runtime/safety/replay/browser_pixel_assertions.py",
            "runtime/execution/suckers/browser_act_skills.py",
            "frontend/src/components/workspace/agent-operator-panel.tsx",
            "frontend/src/components/workspace/agent-operator-panel.test.tsx",
            "tests/test_browser_pixel_assertions.py",
            "tests/test_browser_artifact.py",
        ),
        required_terms=(
            "browser_pixel_replay_gate_case",
            "Certification passed",
            "certified",
        ),
        next_action="Keep browser failures replayable and visible in the operator scorecard.",
        kind="operational_excellence",
    ),
    CertificationRequirement(
        id="browser_desktop_automation_quality",
        title="Browser and desktop automation quality",
        dimension_ids=("browser_desktop", "product_experience"),
        score_floor=97,
        paths=(
            "runtime/safety/evolution/browser_desktop_quality.py",
            "runtime/sensing/gateway/evolution_router.py",
            "tests/test_browser_desktop_quality.py",
            "tests/test_computer_router.py",
            "tests/test_browser_router.py",
            "frontend/src/components/workspace/embedded-browser/browser-panel.tsx",
        ),
        required_terms=(
            "compute_browser_desktop_quality",
            "browser_desktop_quality",
            "lease_owner_id",
            "session/status",
        ),
        next_action="Keep browser and desktop quality checks passing before release.",
        kind="operational_excellence",
    ),
    CertificationRequirement(
        id="browser_desktop_strict_lead",
        title="Browser and desktop deterministic repair strict lead",
        dimension_ids=("browser_desktop",),
        score_floor=93,
        paths=(
            "runtime/safety/evolution/browser_desktop_cold_start_readiness.py",
            "runtime/safety/evolution/browser_desktop_quality.py",
            "runtime/safety/evolution/browser_desktop_repair_recipes.py",
            "runtime/sensing/gateway/evolution_router.py",
            "tests/test_browser_desktop_cold_start_readiness.py",
            "tests/test_browser_desktop_quality.py",
            "tests/test_computer_use_record.py",
            "tests/test_evolution_router.py",
        ),
        required_terms=(
            "octopus.browser_desktop_cold_start_readiness.v1",
            "offline_bootstrap_probe_ready",
            "octopus.browser_desktop_repair_recipe_quality_gate.v1",
            "octopus.browser_desktop_failure_taxonomy.v1",
            "octopus.browser_desktop_repair_route.v1",
            "octopus.browser_desktop_automation_playbook.v1",
            "compute_browser_desktop_repair_recipe_quality_gate",
            "requires_replay_rerun",
            "blocks_auto_promotion",
        ),
        next_action="Keep browser/desktop replay failures clustered into deterministic rerunnable repair recipes before promotion.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="browser_desktop_productized_strict_lead",
        title="Chrome relay and desktop permission productization strict lead",
        dimension_ids=("browser_desktop",),
        score_floor=94,
        paths=(
            "runtime/safety/evolution/browser_desktop_productization_readiness.py",
            "runtime/platform/runtime_policy/computer_automation.py",
            "runtime/sensing/gateway/computer_router.py",
            "runtime/platform/ui/browser_router.py",
            "extensions/octopus-browser-relay/manifest.json",
            "extensions/octopus-browser-relay/background.js",
            "extensions/octopus-browser-relay/bookmarklet.js",
            "tests/test_browser_desktop_productization_readiness.py",
            "tests/test_computer_automation_policy.py",
            "tests/test_computer_router.py",
            "tests/test_browser_router.py",
        ),
        required_terms=(
            "octopus.browser_desktop_productization_readiness.v1",
            "chrome_relay_extension_surface",
            "desktop_app_permission_policy",
            "app_permission_decision",
            "policy_decision",
            "bookmarklet mode",
        ),
        next_action="Keep signed-in browser relay and desktop app permission policy productized before claiming a strict browser/desktop lead.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="permission_ecosystem_excellence",
        title="Permission, extension, and ecosystem excellence",
        dimension_ids=("permissions_sandbox", "extensions_hooks", "ecosystem_maturity"),
        score_floor=94,
        paths=(
            "runtime/safety/evolution/policy_review_rules.py",
            "runtime/sensing/gateway/plugins_router.py",
            "runtime/platform/plugins/codex_discovery.py",
            "docs/guide/operator-readiness.md",
            "tests/test_policy_review_rules.py",
            "tests/test_codex_plugin_smoke.py",
        ),
        required_terms=(
            "octopus.codex_plugin_compatibility.v1",
            "permission review",
            "signed",
        ),
        next_action="Keep plugin compatibility and policy review in one operator-visible loop.",
        kind="operational_excellence",
    ),
    CertificationRequirement(
        id="tool_threat_model_excellence",
        title="High-risk tool threat-model excellence",
        dimension_ids=("permissions_sandbox", "extensions_hooks", "browser_desktop"),
        score_floor=96,
        paths=(
            "runtime/safety/evolution/tool_threat_model.py",
            "runtime/safety/approval/approval_gate.py",
            "runtime/safety/hooks/tool_edge_hooks.py",
            "runtime/sensing/gateway/computer_router.py",
            "tests/test_tool_threat_model.py",
            "tests/test_approval_gate.py",
            "tests/test_tool_edge_hooks.py",
            "tests/test_computer_router.py",
        ),
        required_terms=(
            "octopus.tool_threat_model.v1",
            "plugin_lifecycle",
            "shell_execution",
            "subagent_delegation",
        ),
        next_action="Keep every high-risk local tool class covered by threat-model controls.",
        kind="operational_excellence",
    ),
    CertificationRequirement(
        id="plugin_lifecycle_audit_excellence",
        title="Plugin lifecycle audit excellence",
        dimension_ids=("extensions_hooks", "ecosystem_maturity", "permissions_sandbox"),
        score_floor=96,
        paths=(
            "runtime/platform/plugins/lifecycle_audit.py",
            "runtime/platform/plugins/codex_discovery.py",
            "runtime/sensing/gateway/plugins_router.py",
            "tests/test_codex_plugin_smoke.py",
        ),
        required_terms=(
            "octopus.plugin_lifecycle_audit.v1",
            "permission_review",
            "lifecycle_audit",
        ),
        next_action="Keep plugin lifecycle hooks permission-reviewed before install or execution.",
        kind="operational_excellence",
    ),
    CertificationRequirement(
        id="extension_hooks_strict_lead",
        title="Signed extension lifecycle strict lead",
        dimension_ids=("extensions_hooks",),
        score_floor=97,
        paths=(
            "runtime/safety/evolution/extension_hooks_readiness.py",
            "runtime/platform/plugins/lifecycle_audit.py",
            "runtime/platform/plugins/codex_discovery.py",
            "runtime/sensing/gateway/plugins_router.py",
            "runtime/safety/evolution/tool_threat_model.py",
            "tests/test_extension_hooks_readiness.py",
            "tests/test_codex_plugin_smoke.py",
        ),
        required_terms=(
            "octopus.extension_hooks_readiness.v1",
            "signed_provenance",
            "provenance",
            "permission_review",
            "lifecycle_audit",
        ),
        next_action="Keep extension hooks tied to signed provenance, permission resolution, lifecycle audit, and threat-model coverage.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="governance_chain_advantage",
        title="Tamper-evident governance chain advantage",
        dimension_ids=("record_replay_audit", "governance_operator", "differentiated_agent_os"),
        score_floor=96,
        paths=(
            "runtime/safety/evolution/governance_audit.py",
            "runtime/safety/evolution/record_replay_audit_readiness.py",
            "runtime/memory/learning/promotion_applier.py",
            "runtime/sensing/gateway/agent_trace_router.py",
            "tests/test_record_replay_audit_readiness.py",
            "tests/test_evolution_modules.py",
            "tests/test_agent_trace_router.py",
        ),
        required_terms=(
            "verify_governance_audit_chain",
            "export_governance_audit_bundle",
            "compute_record_replay_audit_readiness",
            "override_replay_gate",
        ),
        next_action="Use governance-chain export as the release audit artifact.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="learning_memory_advantage",
        title="Replay-backed learning memory advantage",
        dimension_ids=("long_term_learning", "repo_context", "differentiated_agent_os"),
        score_floor=97,
        paths=(
            "runtime/memory/learning/experience_ledger.py",
            "runtime/memory/learning/review_queue.py",
            "runtime/memory/learning/promotion_applier.py",
            "runtime/sensing/gateway/agent_trace_router.py",
            "tests/test_promotion_applier.py",
            "tests/test_agent_trace_router.py",
        ),
        required_terms=(
            "experience_ledger",
            "review_queue",
            "replay_gate",
        ),
        next_action="Keep learned memories tied to replay-gated promotion records.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="repo_context_grounding_advantage",
        title="Trace-backed repository context advantage",
        dimension_ids=("repo_context", "core_coding_loop", "differentiated_agent_os"),
        score_floor=96,
        paths=(
            "runtime/safety/evolution/repo_context_readiness.py",
            "runtime/memory/hemolymph/repo_context.py",
            "runtime/memory/diagnostics/trace_store.py",
            "runtime/memory/learning/experience_ledger.py",
            "runtime/core/cerebrum/react_loop.py",
            "runtime/core/cerebrum/llm_planner.py",
            "tests/test_repo_context_readiness.py",
            "tests/test_repo_context.py",
            "tests/test_agent_trace_store.py",
            "tests/test_experience_ledger.py",
        ),
        required_terms=(
            "octopus.repo_context_readiness.v1",
            "build_codebase_context",
            "working_set",
            "memory_quality",
        ),
        next_action="Keep repo-context grounding tied to source citations, working-set resume, and memory quality.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="team_topology_advantage",
        title="Team topology promotion-lift advantage",
        dimension_ids=("subagents_parallelism", "differentiated_agent_os"),
        score_floor=96,
        paths=(
            "runtime/safety/evolution/subagent_team_promotion.py",
            "runtime/safety/organization/promotion_lift.py",
            "runtime/sensing/gateway/organizations_router.py",
            "tests/test_organization.py",
            "tests/test_organizations_router.py",
        ),
        required_terms=(
            "subagent_team_promotion",
            "topology_promotion_lift",
            "historical_lift",
        ),
        next_action="Use promotion lift to auto-rank future team proposals.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="multi_agent_orchestration_advantage",
        title="Worktree-isolated multi-agent orchestration advantage",
        dimension_ids=("subagents_parallelism", "differentiated_agent_os"),
        score_floor=97,
        paths=(
            "runtime/safety/evolution/multi_agent_orchestration_readiness.py",
            "runtime/execution/subagents/worktree_loop.py",
            "runtime/sensing/gateway/subagents_router.py",
            "runtime/sensing/gateway/parallel_agents_router.py",
            "runtime/safety/evolution/subagent_fitness.py",
            "runtime/safety/evolution/subagent_team_promotion.py",
            "runtime/safety/organization/promotion_lift.py",
            "tests/test_multi_agent_orchestration_readiness.py",
            "tests/test_worktree_loop.py",
            "tests/test_organization.py",
        ),
        required_terms=(
            "multi_agent_orchestration_readiness",
            "run_worktree_loop",
            "dispatch_subagent_stream",
            "topology_promotion_lift",
        ),
        next_action="Measure critical-path speedup and merge quality for each worktree-isolated subagent batch.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="swarm_scale_advantage",
        title="Swarm-scale orchestration advantage",
        dimension_ids=("subagents_parallelism", "differentiated_agent_os"),
        score_floor=99,
        paths=(
            "runtime/safety/evolution/swarm_scale_readiness.py",
            "runtime/execution/parallel_agents/orchestrator.py",
            "runtime/execution/parallel_agents/helpers.py",
            "runtime/execution/parallel_agents/ownership.py",
            "runtime/sensing/gateway/parallel_agents_router.py",
            "tests/test_swarm_scale_readiness.py",
            "tests/test_parallel_agents.py",
        ),
        required_terms=(
            "octopus.swarm_scale_readiness.v1",
            "octopus.parallel_agent_batch_metrics.v1",
            "batch_metrics_probe",
            "critical_path_speedup",
            "bounded_concurrency",
            "failure_isolation",
        ),
        next_action="Keep large fan-out speedup and failure isolation verified before claiming swarm-scale leadership.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="product_experience_true_gap_advantage",
        title="Product-experience true gap advantage",
        dimension_ids=("product_experience",),
        score_floor=99,
        paths=(
            "runtime/safety/evolution/product_experience_readiness.py",
            "runtime/safety/evolution/agent_competitor_scorecard.py",
            "runtime/sensing/gateway/evolution_router.py",
            "frontend/src/core/agent-trace/api.ts",
            "frontend/src/components/workspace/agent-operator-panel.tsx",
            "frontend/src/components/workspace/agent-operator-panel.test.tsx",
            "tests/test_product_experience_readiness.py",
            "tests/test_evolution_router.py",
        ),
        required_terms=(
            "octopus.product_experience_readiness.v1",
            "best_competitor_gap",
            "behind best competitor",
            "octopus_competitor_gaps",
            "buildScorecardGapAuditSummary",
            "source_review_queue_item",
            "aria-keyshortcuts",
        ),
        next_action="Keep true competitor product gaps visible, queueable, audit-linked, and regression-tested.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="model_provider_runtime_strict_lead",
        title="Model provider runtime strict lead",
        dimension_ids=("model_provider_runtime",),
        score_floor=96,
        paths=(
            "runtime/safety/evolution/model_provider_runtime_readiness.py",
            "runtime/sensing/model_router/provider_compat_matrix.py",
            "runtime/sensing/model_router/openai_router.py",
            "runtime/platform/observability/provider_compat_health.py",
            "scripts/provider_compat_matrix.py",
            "tests/test_model_provider_runtime_readiness.py",
            "tests/test_provider_compat_matrix.py",
            "tests/test_openai_router.py",
        ),
        required_terms=(
            "octopus.model_provider_runtime_readiness.v1",
            "provider_payload_shape_probe",
            "kimi_omits_sampling_parameters",
            "qwen_uses_enable_thinking",
            "deepseek_reasoner_uses_implicit_thinking",
            "glm_strict_omits_system_messages",
            "provider_thinking_protocol",
            "secrets_redacted",
        ),
        next_action="Keep provider payload shaping, domestic profile coverage, and redacted failure export probes passing.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="self_evolution_rollback_advantage",
        title="Self-evolution canary and rollback advantage",
        dimension_ids=("differentiated_agent_os",),
        score_floor=97,
        paths=(
            "runtime/safety/evolution/canary.py",
            "runtime/safety/evolution/rollback_coordinator.py",
            "runtime/safety/evolution/proposal_ledger.py",
            "tests/test_evolution_integration.py",
            "tests/test_evolution_failure_injection.py",
        ),
        required_terms=(
            "force_rollback",
            "rollback_history",
            "ProposalStatus.ROLLED_BACK",
        ),
        next_action="Keep self-evolution promotions canary-gated with verified rollback.",
        kind="advantage",
    ),
)


def compute_parity_certification(
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    requirements = [_requirement_row(base, item) for item in REQUIREMENTS]
    floors: dict[str, int] = {}
    evidence_by_dimension: dict[str, list[dict[str, Any]]] = {}
    for row in requirements:
        if not row["passed"]:
            continue
        for dimension_id in row["dimension_ids"]:
            floors[dimension_id] = max(
                floors.get(dimension_id, 0),
                int(row["score_floor"]),
            )
            evidence_by_dimension.setdefault(dimension_id, []).append({
                "id": row["id"],
                "title": row["title"],
                "score_floor": row["score_floor"],
            })
    return {
        "schema": "octopus.parity_certification.v1",
        "passed": sum(1 for row in requirements if row["passed"]),
        "total": len(requirements),
        "ready": all(row["passed"] for row in requirements),
        "by_kind": _by_kind(requirements),
        "requirements": requirements,
        "dimension_score_floors": floors,
        "dimension_evidence": evidence_by_dimension,
        "next_actions": [
            str(row["next_action"])
            for row in requirements
            if not row["passed"]
        ],
    }


def _requirement_row(
    base: Path,
    requirement: CertificationRequirement,
) -> dict[str, Any]:
    path_rows = [
        {"path": path, "exists": (base / path).exists()}
        for path in requirement.paths
    ]
    haystack = "\n".join(
        _read_text(base / row["path"])
        for row in path_rows
        if row["exists"]
    ).lower()
    missing_terms = [
        term
        for term in requirement.required_terms
        if term.lower() not in haystack
    ]
    missing_paths = [
        str(row["path"])
        for row in path_rows
        if not row["exists"]
    ]
    passed = not missing_paths and not missing_terms
    return {
        "id": requirement.id,
        "title": requirement.title,
        "dimension_ids": list(requirement.dimension_ids),
        "score_floor": requirement.score_floor,
        "passed": passed,
        "paths": path_rows,
        "missing_paths": missing_paths,
        "required_terms": list(requirement.required_terms),
        "missing_terms": missing_terms,
        "next_action": requirement.next_action,
        "kind": requirement.kind,
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _by_kind(requirements: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for row in requirements:
        kind = str(row.get("kind") or "parity")
        summary = out.setdefault(kind, {"passed": 0, "total": 0})
        summary["total"] += 1
        if row.get("passed"):
            summary["passed"] += 1
    return out


__all__ = [
    "CertificationRequirement",
    "REQUIREMENTS",
    "compute_parity_certification",
]

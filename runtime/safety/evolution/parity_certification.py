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
            "runtime/safety/evolution/auto_verifier.py",
            "runtime/safety/evolution/auto_verifier_metrics.py",
            "runtime/safety/evolution/repair_route_quality.py",
            "tests/test_auto_verifier_metrics.py",
            "tests/test_repair_route_quality.py",
            "tests/test_post_write_diagnostics.py",
        ),
        required_terms=(
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
            "operator_drilldown",
            "octopus.scorecard_operator_drilldown.v1",
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
            "runtime/safety/hooks/tool_edge_hooks.py",
            "frontend/src/components/workspace/agent-operator-panel.tsx",
            "tests/test_policy_review_rules.py",
            "tests/test_tool_edge_hooks.py",
        ),
        required_terms=(
            "policy_review_rule",
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
            "runtime/safety/evolution/plugin_migration_readiness.py",
            "docs/guide/plugin-migration-matrix.md",
            "tests/test_codex_plugin_smoke.py",
            "frontend/src/core/plugins/types.ts",
            "frontend/src/components/workspace/agent-operator-panel.tsx",
        ),
        required_terms=(
            "octopus.codex_plugin_compatibility.v1",
            "octopus.plugin_migration_readiness.v1",
            "octopus.plugin_migration_contract.v1",
            "migration_readiness",
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
        score_floor=96,
        paths=(
            "runtime/safety/evolution/auto_verifier.py",
            "runtime/safety/evolution/auto_verifier_metrics.py",
            "runtime/safety/evolution/repair_route_quality.py",
            "runtime/safety/evolution/repo_context_quality.py",
            "runtime/sensing/gateway/realtime_turn_outcome.py",
            "runtime/sensing/gateway/evolution_router.py",
            "runtime/memory/hemolymph/repo_context.py",
            "tests/test_auto_verifier_metrics.py",
            "tests/test_repair_route_quality.py",
            "tests/test_post_write_diagnostics.py",
            "tests/test_repo_context.py",
            "frontend/src/components/workspace/agent-operator-panel.tsx",
        ),
        required_terms=(
            "octopus.repo_context_quality.v1",
            "repo-context-quality",
            "dirty_worktree",
            "collect_codebase_sources",
            "repair_route",
            "recent_decisions",
            "verification_plan",
        ),
        next_action="Keep verifier drift visible and repair-routed from the operator panel.",
        kind="operational_excellence",
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
            "runtime/platform/process/paths.py",
            "runtime/sensing/gateway/evolution_router.py",
            "runtime/execution/suckers/browser_backends.py",
            "runtime/execution/suckers/computer_api_skills.py",
            "tests/test_browser_desktop_quality.py",
            "tests/test_browser_backends.py",
            "tests/test_computer_api_skills.py",
            "tests/test_computer_router.py",
            "tests/test_browser_router.py",
            "frontend/src/components/workspace/embedded-browser/browser-panel.tsx",
        ),
        required_terms=(
            "compute_browser_desktop_quality",
            "browser_desktop_quality",
            "octopus.browser_relay_bridge.v1",
            "octopus.browser_relay_site_policy.v1",
            "relay_allowed_hosts",
            "relay_blocked_hosts",
            "browser_policy_path",
            "browser_policy.json",
            "read_json_with_backup",
            "atomic_write_json",
            "OCTOPUS_BROWSER_RELAY_BASE_URL",
            "octopus.computer_api_bridge.v1",
            "OCTOPUS_COMPUTER_API_BASE_URL",
            "lease_owner_id",
            "session/status",
        ),
        next_action="Keep browser and desktop quality checks passing before release.",
        kind="operational_excellence",
    ),
    CertificationRequirement(
        id="permission_ecosystem_excellence",
        title="Permission, extension, and ecosystem excellence",
        dimension_ids=("permissions_sandbox", "extensions_hooks", "ecosystem_maturity"),
        score_floor=96,
        paths=(
            "runtime/safety/evolution/policy_review_rules.py",
            "runtime/safety/evolution/permission_sandbox_quality.py",
            "runtime/sensing/gateway/evolution_router.py",
            "runtime/sensing/gateway/plugins_router.py",
            "runtime/platform/plugins/codex_discovery.py",
            "runtime/safety/evolution/plugin_migration_readiness.py",
            "docs/guide/plugin-migration-matrix.md",
            "docs/guide/operator-readiness.md",
            "tests/test_policy_review_rules.py",
            "tests/test_evolution_router.py",
            "tests/test_codex_plugin_smoke.py",
        ),
        required_terms=(
            "octopus.permission_sandbox_quality.v1",
            "permission-sandbox-quality",
            "octopus.automation_policy_rule_coverage.v1",
            "octopus.plugin_permission_rule_coverage.v1",
            "octopus.codex_plugin_compatibility.v1",
            "octopus.plugin_migration_readiness.v1",
            "octopus.plugin_migration_contract.v1",
            "migration_readiness",
            "octopus.plugin_permission_rule_drafts.v1",
            "octopus.automation_policy_rule_drafts.v1",
            "automation_policy_rule_install",
            "plugin_permission_review",
            "plugin_permission_rule_install",
            "permission review",
            "signed",
        ),
        next_action="Keep plugin compatibility and policy review in one operator-visible loop.",
        kind="operational_excellence",
    ),
    CertificationRequirement(
        id="governance_chain_advantage",
        title="Tamper-evident governance chain advantage",
        dimension_ids=("record_replay_audit", "governance_operator", "differentiated_agent_os"),
        score_floor=96,
        paths=(
            "runtime/safety/evolution/governance_audit.py",
            "runtime/memory/learning/promotion_applier.py",
            "runtime/sensing/gateway/agent_trace_router.py",
            "tests/test_evolution_modules.py",
            "tests/test_agent_trace_router.py",
        ),
        required_terms=(
            "verify_governance_audit_chain",
            "export_governance_audit_bundle",
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
            "octopus.experience_recall.v1",
            "experience-ledger/recall",
            "citation_coverage",
            "matched_terms",
            "review_queue",
            "replay_gate",
        ),
        next_action="Keep learned memories tied to replay-gated promotion records.",
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
            "runtime/sensing/gateway/team_tasks_router.py",
            "tests/test_organization.py",
            "tests/test_organizations_router.py",
            "tests/test_team_tasks_router.py",
        ),
        required_terms=(
            "subagent_team_promotion",
            "topology_promotion_lift",
            "historical_lift",
            "octopus.team_task_process_timeline.v1",
            "process_events",
        ),
        next_action="Use promotion lift to auto-rank future team proposals.",
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
    CertificationRequirement(
        id="general_agent_loop_advantage",
        title="General agent loop trace and recovery advantage",
        dimension_ids=("general_agent_loop",),
        score_floor=97,
        paths=(
            "runtime/safety/evolution/agent_loop_quality.py",
            "runtime/sensing/gateway/evolution_router.py",
            "runtime/sensing/gateway/realtime_turn_lifecycle.py",
            "runtime/memory/runtime_state/process_timeline.py",
            "tests/test_realtime_cerebrum.py",
            "tests/test_process_timeline.py",
            "tests/test_evolution_router.py",
            "tests/test_evolution_modules.py",
        ),
        required_terms=(
            "octopus.agent_loop_quality.v1",
            "agent-loop-quality",
            "_drive_local_partner",
            "_drive_group_fanout",
            "_drive_swarm_mesh",
            "octopus.process_timeline.v1",
            "turn/interrupt",
            "workspaceFocus",
        ),
        next_action="Keep all realtime turns traceable, interruptible, and quality-gated.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="digital_employee_workflow_advantage",
        title="Digital employee Project OS workflow advantage",
        dimension_ids=(
            "digital_employee_workflows",
            "subagents_parallelism",
            "differentiated_agent_os",
        ),
        score_floor=97,
        paths=(
            "runtime/safety/evolution/digital_employee_quality.py",
            "runtime/sensing/gateway/evolution_router.py",
            "runtime/projectos/cowork_bridge.py",
            "runtime/projectos/timeline.py",
            "runtime/sensing/gateway/realtime_cerebrum.py",
            "runtime/sensing/gateway/projects_router.py",
            "runtime/sensing/gateway/team_tasks_router.py",
            "tests/test_projectos_cowork.py",
            "tests/test_projects_router.py",
            "tests/test_realtime_cerebrum.py",
            "tests/test_team_tasks_router.py",
            "tests/test_evolution_router.py",
            "tests/test_evolution_modules.py",
        ),
        required_terms=(
            "octopus.digital_employee_quality.v1",
            "digital-employee-quality",
            "octopus.projectos.run_trace.v1",
            "octopus.projectos.process_timeline.v1",
            "octopus.projectos.control_trace.v1",
            "/api/projects/{project_id}/process-timeline",
            "octopus.team_task_process_timeline.v1",
            "process_events_persisted",
            "run_project_from_group",
            "available_actions",
        ),
        next_action="Keep Project OS and team tasks on one operator-visible employee loop.",
        kind="advantage",
    ),
    CertificationRequirement(
        id="extension_hook_signed_policy_advantage",
        title="Signed extension hook policy advantage",
        dimension_ids=("extensions_hooks",),
        score_floor=97,
        paths=(
            "runtime/safety/evolution/policy_review_rules.py",
            "runtime/sensing/gateway/plugins_router.py",
            "runtime/platform/plugins/codex_discovery.py",
            "runtime/safety/hooks/runner.py",
            "runtime/safety/hooks/registry.py",
            "tests/test_policy_review_rules.py",
            "tests/test_codex_plugin_smoke.py",
            "tests/test_tool_edge_hooks.py",
            "frontend/src/components/workspace/agent-operator-panel.tsx",
        ),
        required_terms=(
            "octopus.plugin_permission_rule_drafts.v1",
            "octopus.plugin_permission_review_rule_draft.v1",
            "octopus.policy_review_rule_signature.v1",
            "verify_policy_review_rule_draft",
            "install_policy_review_rule_draft",
            "plugin_permission_rule_install",
            "signed_payload",
            "register_hook",
            "ToolEdgeHookRunner",
        ),
        next_action="Keep plugin hooks behind signed, operator-installable policy drafts.",
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
            evidence_by_dimension.setdefault(dimension_id, []).append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "score_floor": row["score_floor"],
                }
            )
    return {
        "schema": "octopus.parity_certification.v1",
        "passed": sum(1 for row in requirements if row["passed"]),
        "total": len(requirements),
        "ready": all(row["passed"] for row in requirements),
        "by_kind": _by_kind(requirements),
        "requirements": requirements,
        "dimension_score_floors": floors,
        "dimension_evidence": evidence_by_dimension,
        "next_actions": [str(row["next_action"]) for row in requirements if not row["passed"]],
    }


def _requirement_row(
    base: Path,
    requirement: CertificationRequirement,
) -> dict[str, Any]:
    path_rows = [{"path": path, "exists": (base / path).exists()} for path in requirement.paths]
    haystack = "\n".join(
        _read_text(base / row["path"]) for row in path_rows if row["exists"]
    ).lower()
    missing_terms = [term for term in requirement.required_terms if term.lower() not in haystack]
    missing_paths = [str(row["path"]) for row in path_rows if not row["exists"]]
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

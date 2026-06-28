"""High-risk tool threat-model coverage for the local agent runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root

_SCHEMA = "octopus.tool_threat_model.v1"


@dataclass(frozen=True, slots=True)
class ThreatControl:
    id: str
    title: str
    path: str
    required_terms: tuple[str, ...] = ()
    weight: int = 1


@dataclass(frozen=True, slots=True)
class HighRiskToolClass:
    id: str
    title: str
    risks: tuple[str, ...]
    controls: tuple[ThreatControl, ...]


HIGH_RISK_TOOL_CLASSES: tuple[HighRiskToolClass, ...] = (
    HighRiskToolClass(
        id="shell_execution",
        title="Shell and terminal execution",
        risks=("command_injection", "destructive_command", "secret_exfiltration"),
        controls=(
            ThreatControl(
                id="approval_gate",
                title="Static approval policy gate",
                path="runtime/safety/approval/approval_gate.py",
                required_terms=("ApprovalRiskPolicy", "deny", "assess_approval_risk"),
                weight=2,
            ),
            ThreatControl(
                id="sandbox_runner",
                title="Local sandbox runner",
                path="runtime/safety/sandboxing/sandbox.py",
                required_terms=("SandboxRunner", "allow_network"),
                weight=2,
            ),
            ThreatControl(
                id="tool_edge_pre_hook",
                title="PreToolUse hook veto",
                path="runtime/safety/hooks/tool_edge_hooks.py",
                required_terms=("preToolUse", "ToolEdgeHookRunner"),
            ),
            ThreatControl(
                id="policy_review_rule",
                title="Signed policy-review rule draft",
                path="runtime/safety/evolution/policy_review_rules.py",
                required_terms=("policy_review_rule", "signed", "deny"),
            ),
            ThreatControl(
                id="regression_tests",
                title="Shell safety regression tests",
                path="tests/test_write_skills.py",
                required_terms=("sandbox_violation", "sandbox_dir"),
            ),
        ),
    ),
    HighRiskToolClass(
        id="file_mutation",
        title="File mutation and workspace writes",
        risks=("workspace_escape", "unreviewed_write", "stale_diagnostics"),
        controls=(
            ThreatControl(
                id="write_scope",
                title="Mode-gated write scope",
                path="runtime/platform/process/scope.py",
                required_terms=("WriteScope", "extra_workspaces"),
                weight=2,
            ),
            ThreatControl(
                id="post_write_diagnostics",
                title="Post-write diagnostics",
                path="runtime/safety/hooks/tool_edge_hooks.py",
                required_terms=("post_write_diagnostic_record", "regression_matrix"),
            ),
            ThreatControl(
                id="scope_tests",
                title="Write-scope regression tests",
                path="tests/test_scope.py",
                required_terms=("mode-gated write scope", "extra_workspaces"),
            ),
            ThreatControl(
                id="bridge_scope_tests",
                title="Tool bridge scope tests",
                path="tests/test_tool_bridge_scope.py",
                required_terms=("build_anthropic_tool_specs", "mode"),
            ),
        ),
    ),
    HighRiskToolClass(
        id="browser_desktop",
        title="Browser and desktop operation",
        risks=("confused_deputy", "visual_misread", "unbounded_session"),
        controls=(
            ThreatControl(
                id="browser_session_policy",
                title="Browser session policy",
                path="runtime/platform/runtime_policy/browser_sessions.py",
                required_terms=("lease", "session"),
            ),
            ThreatControl(
                id="computer_router",
                title="Computer-use control plane",
                path="runtime/sensing/gateway/computer_router.py",
                required_terms=("confirmation", "preview", "action"),
            ),
            ThreatControl(
                id="pixel_replay_gate",
                title="Browser pixel replay gate",
                path="runtime/safety/replay/browser_pixel_assertions.py",
                required_terms=("browser_pixel_replay_gate_case", "evidence"),
                weight=2,
            ),
            ThreatControl(
                id="browser_quality_tests",
                title="Browser quality regression tests",
                path="tests/test_browser_desktop_quality.py",
                required_terms=("browser_desktop_quality",),
            ),
        ),
    ),
    HighRiskToolClass(
        id="mcp_tooling",
        title="MCP and external tool servers",
        risks=("untrusted_server", "tool_schema_drift", "credential_scope"),
        controls=(
            ThreatControl(
                id="mcp_trust_store",
                title="MCP trust store",
                path="runtime/adapters/mcp_client/trust.py",
                required_terms=("trust", "approve"),
                weight=2,
            ),
            ThreatControl(
                id="mcp_cli_review",
                title="MCP CLI trust workflow",
                path="runtime/cli_mcp.py",
                required_terms=("trust", "revoke"),
            ),
            ThreatControl(
                id="mcp_tests",
                title="MCP regression tests",
                path="tests/test_cli_mcp.py",
                required_terms=("trust",),
            ),
        ),
    ),
    HighRiskToolClass(
        id="plugin_lifecycle",
        title="Plugin lifecycle and local extensions",
        risks=("unsafe_hook", "implicit_permission", "supply_chain_drift"),
        controls=(
            ThreatControl(
                id="plugin_smoke",
                title="Plugin smoke and permission resolution",
                path="runtime/platform/plugins/codex_discovery.py",
                required_terms=("permission_resolution", "local_review_required", "provenance"),
                weight=2,
            ),
            ThreatControl(
                id="plugin_lifecycle_audit",
                title="Plugin lifecycle audit",
                path="runtime/platform/plugins/lifecycle_audit.py",
                required_terms=("plugin_lifecycle_audit", "permission_review", "provenance"),
                weight=2,
            ),
            ThreatControl(
                id="plugin_router_summary",
                title="Plugin compatibility summary endpoint",
                path="runtime/sensing/gateway/plugins_router.py",
                required_terms=("lifecycle_audit", "codex_plugin_compatibility"),
            ),
            ThreatControl(
                id="plugin_tests",
                title="Plugin lifecycle regression tests",
                path="tests/test_codex_plugin_smoke.py",
                required_terms=("lifecycle_audit", "permission_resolutions"),
            ),
        ),
    ),
    HighRiskToolClass(
        id="subagent_delegation",
        title="Subagent delegation and team topology",
        risks=("weak_delegate", "context_pollution", "bad_topology_promotion"),
        controls=(
            ThreatControl(
                id="subagent_policy",
                title="Subagent policy gate",
                path="runtime/safety/evolution/subagent_policy.py",
                required_terms=("retire", "watch"),
            ),
            ThreatControl(
                id="team_promotion",
                title="Replay-backed team promotion proposals",
                path="runtime/safety/evolution/subagent_team_promotion.py",
                required_terms=("subagent_team_promotion", "historical_lift"),
                weight=2,
            ),
            ThreatControl(
                id="promotion_lift",
                title="Topology promotion lift",
                path="runtime/safety/organization/promotion_lift.py",
                required_terms=("topology_promotion_lift", "success_rate_delta"),
            ),
            ThreatControl(
                id="organization_tests",
                title="Team topology regression tests",
                path="tests/test_organization.py",
                required_terms=("strong_subagent_generates_team_promotion_proposal",),
            ),
        ),
    ),
)


def compute_tool_threat_model(
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    classes = [_class_row(base, item) for item in HIGH_RISK_TOOL_CLASSES]
    total_weight = sum(int(row["weight"]) for row in classes)
    weighted_score = (
        sum(float(row["score"]) * int(row["weight"]) for row in classes) / total_weight
        if total_weight > 0
        else 0.0
    )
    score = round(weighted_score, 3)
    return {
        "schema": _SCHEMA,
        "score": score,
        "ready": score >= 0.94 and all(row["score"] >= 0.9 for row in classes),
        "verdict": _verdict(score, classes),
        "class_count": len(classes),
        "classes": classes,
        "coverage_gaps": [
            row
            for row in classes
            if row["score"] < 0.9 or row["missing_controls"]
        ],
        "next_actions": _next_actions(classes),
    }


def _class_row(base: Path, item: HighRiskToolClass) -> dict[str, Any]:
    controls = [_control_row(base, control) for control in item.controls]
    total_weight = sum(int(row["weight"]) for row in controls)
    passed_weight = sum(int(row["weight"]) for row in controls if row["passed"])
    score = round(passed_weight / total_weight, 3) if total_weight > 0 else 0.0
    return {
        "id": item.id,
        "title": item.title,
        "risks": list(item.risks),
        "score": score,
        "weight": max(1, len(item.risks)),
        "passed_controls": sum(1 for row in controls if row["passed"]),
        "total_controls": len(controls),
        "missing_controls": [
            row["id"]
            for row in controls
            if not row["passed"]
        ],
        "controls": controls,
    }


def _control_row(base: Path, control: ThreatControl) -> dict[str, Any]:
    path = base / control.path
    text = _read_text(path).lower() if path.exists() else ""
    missing_terms = [
        term
        for term in control.required_terms
        if term.lower() not in text
    ]
    passed = path.exists() and not missing_terms
    return {
        "id": control.id,
        "title": control.title,
        "path": control.path,
        "exists": path.exists(),
        "required_terms": list(control.required_terms),
        "missing_terms": missing_terms,
        "weight": control.weight,
        "passed": passed,
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _verdict(score: float, classes: list[dict[str, Any]]) -> str:
    if any(row["score"] < 0.75 for row in classes):
        return "fail"
    if score >= 0.94 and all(row["score"] >= 0.9 for row in classes):
        return "pass"
    return "review"


def _next_actions(classes: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for row in classes:
        if row["score"] >= 0.9 and not row["missing_controls"]:
            continue
        actions.append(
            f"Complete threat-model controls for {row['id']}: "
            + ", ".join(row["missing_controls"])
        )
    return actions[:8]


__all__ = [
    "HIGH_RISK_TOOL_CLASSES",
    "HighRiskToolClass",
    "ThreatControl",
    "compute_tool_threat_model",
]

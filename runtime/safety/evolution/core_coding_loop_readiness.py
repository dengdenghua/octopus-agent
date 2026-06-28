from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root
from runtime.safety.evolution.core_coding_loop_canary import (
    run_core_coding_loop_canary,
)

_SCHEMA = "octopus.core_coding_loop_readiness.v1"


@dataclass(frozen=True)
class CoreCodingLoopCapability:
    id: str
    title: str
    path: str
    required_terms: tuple[str, ...]
    weight: int = 1


CAPABILITIES: tuple[CoreCodingLoopCapability, ...] = (
    CoreCodingLoopCapability(
        id="auto_verifier_ranking",
        title="History-aware verifier ranking",
        path="runtime/safety/evolution/auto_verifier_metrics.py",
        required_terms=(
            "rank_verification_commands",
            "explain_verification_ranking",
            "priority_penalty",
        ),
        weight=2,
    ),
    CoreCodingLoopCapability(
        id="auto_verifier_execution",
        title="Sandboxed highest-priority verifier execution",
        path="runtime/safety/evolution/auto_verifier.py",
        required_terms=(
            "run_highest_priority_verification",
            "_record_decision",
            "SandboxRunner",
        ),
        weight=2,
    ),
    CoreCodingLoopCapability(
        id="post_write_regression_matrix",
        title="Post-write regression matrix",
        path="runtime/safety/hooks/tool_edge_hooks.py",
        required_terms=(
            "post_write_diagnostic_record",
            "post_write_regression_matrix",
            "regression_matrix_for_path",
        ),
        weight=2,
    ),
    CoreCodingLoopCapability(
        id="failed_turn_repair_metadata",
        title="Failed-turn verifier repair metadata",
        path="runtime/sensing/gateway/realtime_turn_outcome.py",
        required_terms=(
            "octopus.verification_plan.v1",
            "primary_repair_route",
            "failed_verifications",
        ),
        weight=2,
    ),
    CoreCodingLoopCapability(
        id="repair_route_governance",
        title="Repair-route governance promotion gate",
        path="runtime/safety/evolution/repair_route_quality.py",
        required_terms=(
            "repair_route_quality_gate",
            "queue_repair_route_promotion_candidates",
            "requires_passing_rerun",
            "passing_rerun_attached",
            "pending_repair_route_review",
        ),
        weight=2,
    ),
)


def compute_core_coding_loop_readiness(
    *,
    root: str | Path | None = None,
    include_canary: bool = True,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    capabilities = [_capability_status(base, capability) for capability in CAPABILITIES]
    canary = run_core_coding_loop_canary() if include_canary else _skipped_canary()
    total_weight = sum(int(item["weight"]) for item in capabilities)
    passed_weight = sum(int(item["weight"]) for item in capabilities if item["passed"])
    canary_weight = 3
    total_weight += canary_weight
    if canary.get("ready") is True:
        passed_weight += canary_weight
    score = round(passed_weight / total_weight, 3) if total_weight else 0.0
    missing = [item for item in capabilities if not item["passed"]]
    canary_missing = canary.get("ready") is not True
    return {
        "schema": _SCHEMA,
        "score": score,
        "ready": score >= 1.0 and not missing and not canary_missing,
        "verdict": "pass" if score >= 1.0 and not missing and not canary_missing else "review",
        "passed": len(capabilities) - len(missing),
        "total": len(capabilities),
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "capabilities": capabilities,
        "canary": canary,
        "canary_ready": canary.get("ready") is True,
        "missing_count": len(missing) + (1 if canary_missing else 0),
        "next_actions": _next_actions(missing, canary),
        "calibration": {
            "schema": "octopus.core_coding_loop_calibration.v1",
            "compares_to": {
                "codex": "tight edit-run-verify repair loop in a real repo",
                "claude_code": "strong tool-use loop with subagent and hook support",
            },
            "octopus_edge": (
                "history-aware verifier ranking plus post-write diagnostics, "
                "failed-turn repair metadata, and operator-governed repair-route "
                "promotion, backed by a runtime canary for sandbox execution, "
                "decision telemetry, drift backlog routing, and clean repair gates"
            ),
        },
    }


def _capability_status(
    base: Path,
    capability: CoreCodingLoopCapability,
) -> dict[str, Any]:
    path = base / capability.path
    text = _read_text(path).lower() if path.exists() else ""
    missing_terms = [
        term for term in capability.required_terms
        if term.lower() not in text
    ]
    return {
        "id": capability.id,
        "title": capability.title,
        "path": capability.path,
        "weight": capability.weight,
        "exists": path.exists(),
        "passed": path.exists() and not missing_terms,
        "required_terms": list(capability.required_terms),
        "missing_terms": missing_terms,
    }


def _next_actions(
    missing: list[dict[str, Any]],
    canary: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    for item in missing:
        if not item["exists"]:
            actions.append(f"Add {item['path']} for {item['title']}.")
        elif item["missing_terms"]:
            actions.append(
                f"Update {item['path']} with {', '.join(item['missing_terms'])}.",
            )
    if canary.get("ready") is not True:
        actions.extend(str(item) for item in canary.get("next_actions") or [] if str(item))
    return actions


def _skipped_canary() -> dict[str, Any]:
    return {
        "schema": "octopus.core_coding_loop_canary.v1",
        "ready": False,
        "score": 0.0,
        "skipped": True,
        "next_actions": ["Run core coding loop canary."],
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


__all__ = [
    "CAPABILITIES",
    "CoreCodingLoopCapability",
    "compute_core_coding_loop_readiness",
]

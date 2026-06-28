from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root

_SCHEMA = "octopus.product_experience_readiness.v1"
_PROBE_SCHEMA = "octopus.product_experience_probe.v1"


@dataclass(frozen=True)
class ProductExperienceCapability:
    id: str
    title: str
    path: str
    required_terms: tuple[str, ...]
    weight: int = 1


CAPABILITIES: tuple[ProductExperienceCapability, ...] = (
    ProductExperienceCapability(
        id="true_competitor_gap_scorecard",
        title="True best-competitor gap scorecard",
        path="runtime/safety/evolution/agent_competitor_scorecard.py",
        required_terms=(
            "octopus_competitor_gaps",
            "octopus_true_gap_edges",
            "best_competitor_score",
        ),
        weight=3,
    ),
    ProductExperienceCapability(
        id="best_competitor_gap_queue",
        title="Best-competitor gap queue scope",
        path="runtime/sensing/gateway/evolution_router.py",
        required_terms=(
            "best_competitor_gap",
            "_scorecard_competitor_gap_rows",
            "competitor_gap_count",
        ),
        weight=3,
    ),
    ProductExperienceCapability(
        id="operator_gap_visibility",
        title="Operator-visible competitor gap UI",
        path="frontend/src/components/workspace/agent-operator-panel.tsx",
        required_terms=(
            "Best competitor gaps",
            "behind best competitor",
            "octopus_best_competitor_score",
        ),
        weight=3,
    ),
    ProductExperienceCapability(
        id="frontend_scorecard_contract",
        title="Frontend scorecard contract",
        path="frontend/src/core/agent-trace/api.ts",
        required_terms=(
            "AgentScorecardRadarEdge",
            "octopus_competitor_gaps",
            "best_competitor_gap",
        ),
        weight=2,
    ),
    ProductExperienceCapability(
        id="operator_gap_regression_test",
        title="Operator competitor-gap regression test",
        path="frontend/src/components/workspace/agent-operator-panel.test.tsx",
        required_terms=(
            "queues best-competitor gaps when Octopus is above target but still behind",
            "IDE and product experience is 8 point(s) behind best competitor",
            'scope: "best_competitor_gap"',
        ),
        weight=2,
    ),
    ProductExperienceCapability(
        id="audit_export_and_keyboard_flow",
        title="Audit export and keyboard-first gap flow",
        path="frontend/src/components/workspace/agent-operator-panel.tsx",
        required_terms=(
            "buildScorecardGapAuditSummary",
            "Copy audit",
            "aria-keyshortcuts",
            "Control+Enter Meta+Enter Control+Shift+C Meta+Shift+C",
        ),
        weight=3,
    ),
    ProductExperienceCapability(
        id="audit_export_keyboard_regression_test",
        title="Audit export and keyboard regression test",
        path="frontend/src/components/workspace/agent-operator-panel.test.tsx",
        required_terms=(
            "supports keyboard-first scorecard gap queueing and audit copy",
            "dimension: product_experience",
            "best_competitor: Cursor 98",
        ),
        weight=2,
    ),
    ProductExperienceCapability(
        id="source_review_queue_drilldown",
        title="Source review queue drill-down linkage",
        path="frontend/src/components/workspace/agent-operator-panel.tsx",
        required_terms=(
            "source_review_queue_item",
            "queue_item:",
            "queue_status:",
            "audit_entries:",
        ),
        weight=2,
    ),
    ProductExperienceCapability(
        id="closed_loop_advantage_regression_test",
        title="Closed-loop product advantage regression test",
        path="frontend/src/components/workspace/agent-operator-panel.test.tsx",
        required_terms=(
            "copies closed-loop scorecard audit evidence",
            "source_review_queue_item",
            "queue_status: pending",
        ),
        weight=2,
    ),
    ProductExperienceCapability(
        id="backend_gap_queue_test",
        title="Backend competitor-gap queue test",
        path="tests/test_evolution_router.py",
        required_terms=(
            "test_agent_scorecard_gap_queue_can_target_best_competitor_gap",
            "best_competitor_gap",
            "competitor_gap",
        ),
        weight=2,
    ),
)


def compute_product_experience_readiness(
    *,
    root: str | Path | None = None,
    include_probe: bool = True,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    capabilities = [_capability_status(base, capability) for capability in CAPABILITIES]
    probe = run_product_experience_probe() if include_probe else _skipped_probe()
    capabilities.extend(_probe_capabilities(probe))

    total_weight = sum(int(item["weight"]) for item in capabilities)
    passed_weight = sum(int(item["weight"]) for item in capabilities if item["passed"])
    score = round(passed_weight / total_weight, 3) if total_weight else 0.0
    missing = [item for item in capabilities if not item["passed"]]
    return {
        "schema": _SCHEMA,
        "score": score,
        "ready": score >= 1.0 and not missing,
        "verdict": "pass" if score >= 1.0 and not missing else "review",
        "passed": len(capabilities) - len(missing),
        "total": len(capabilities),
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "capabilities": capabilities,
        "missing_count": len(missing),
        "probe": probe,
        "next_actions": _next_actions(missing),
        "calibration": {
            "schema": "octopus.product_experience_calibration.v1",
            "compares_to": {
                "cursor": (
                    "best-in-class IDE-native product polish, fast gap discovery, "
                    "and low-friction remediation loops"
                ),
            },
            "octopus_edge": (
                "operator-visible true competitor gaps, scoped remediation queues, "
                "typed frontend contracts, keyboard-first drill-down actions, "
                "copyable audit summaries, and regression tests that keep hidden "
                "product gaps from being reported as clear"
            ),
        },
    }


def run_product_experience_probe() -> dict[str, Any]:
    try:
        from runtime.sensing.gateway.evolution_router import (
            _scorecard_competitor_gap_rows,
            _scorecard_gap_text,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": _PROBE_SCHEMA,
            "ok": False,
            "error": str(exc),
            "competitor_gap_routing": False,
            "queue_text_mentions_best_competitor": False,
            "keyboard_audit_export": False,
            "closed_loop_drilldown": False,
        }

    report = {
        "dimensions": [
            {
                "id": "product_experience",
                "title": "IDE and product experience",
                "weight": 7,
                "scores": {
                    "codex": 88,
                    "claude_code": 85,
                    "kimi_agent_swarm": 91,
                    "cursor": 98,
                    "octopus": 90,
                },
                "evidence_adjusted_scores": {"octopus": 90},
                "octopus_gap_to_target": 0,
                "octopus_next_actions": [
                    "Add keyboard-first promotion and audit export flows.",
                ],
            },
        ],
        "radar": {
            "octopus_true_gap_edges": [
                {
                    "id": "product_experience",
                    "gap": -8,
                    "best_competitors": ["cursor"],
                    "best_competitor_score": 98,
                },
            ],
        },
    }
    rows = _scorecard_competitor_gap_rows(report)
    row = rows[0] if rows else {}
    text = _scorecard_gap_text(
        row,
        reason="probe competitor product gap",
        scope="best_competitor_gap",
    )
    competitor_gap_routing = bool(
        row.get("id") == "product_experience"
        and row.get("octopus_competitor_gap") == 8
        and row.get("octopus_best_competitors") == ["cursor"]
        and row.get("octopus_best_competitor_score") == 98
    )
    queue_text_mentions_best_competitor = (
        "Best-competitor gap" in text
        and "cursor" in text
        and "gap: 8" in text
    )
    root = default_project_root(Path(__file__))
    panel_text = _read_text(
        root / "frontend/src/components/workspace/agent-operator-panel.tsx",
    )
    panel_test_text = _read_text(
        root / "frontend/src/components/workspace/agent-operator-panel.test.tsx",
    )
    keyboard_audit_export = all(
        term in panel_text
        for term in (
            "buildScorecardGapAuditSummary",
            "Copy audit",
            "aria-keyshortcuts",
            "Control+Enter Meta+Enter Control+Shift+C Meta+Shift+C",
        )
    ) and all(
        term in panel_test_text
        for term in (
            "supports keyboard-first scorecard gap queueing and audit copy",
            "dimension: product_experience",
            "best_competitor: Cursor 98",
        )
    )
    closed_loop_drilldown = all(
        term in panel_text
        for term in (
            "source_review_queue_item",
            "queue_item:",
            "queue_status:",
            "audit_entries:",
        )
    ) and all(
        term in panel_test_text
        for term in (
            "copies closed-loop scorecard audit evidence",
            "source_review_queue_item",
            "queue_status: pending",
        )
    )

    return {
        "schema": _PROBE_SCHEMA,
        "ok": (
            competitor_gap_routing
            and queue_text_mentions_best_competitor
            and keyboard_audit_export
            and closed_loop_drilldown
        ),
        "competitor_gap_routing": competitor_gap_routing,
        "queue_text_mentions_best_competitor": queue_text_mentions_best_competitor,
        "keyboard_audit_export": keyboard_audit_export,
        "closed_loop_drilldown": closed_loop_drilldown,
        "row_count": len(rows),
        "first_gap": row.get("octopus_competitor_gap"),
        "text_preview": text[:240],
    }


def _probe_capabilities(probe: dict[str, Any]) -> list[dict[str, Any]]:
    if probe.get("skipped"):
        return [
            _dynamic_capability(
                "product_experience_probe",
                "Offline product-experience probe",
                False,
                "probe skipped",
                weight=3,
            ),
        ]
    return [
        _dynamic_capability(
            "competitor_gap_routing_probe",
            "Competitor-gap routing probe",
            bool(probe.get("competitor_gap_routing")),
            "Synthetic product gap routes to best-competitor remediation rows",
            weight=2,
        ),
        _dynamic_capability(
            "queue_text_probe",
            "Competitor-gap queue text probe",
            bool(probe.get("queue_text_mentions_best_competitor")),
            "Queued text names the best competitor and gap size",
            weight=1,
        ),
        _dynamic_capability(
            "keyboard_audit_export_probe",
            "Keyboard audit-export probe",
            bool(probe.get("keyboard_audit_export")),
            "Drill-down supports keyboard queueing and copyable audit summaries",
            weight=2,
        ),
        _dynamic_capability(
            "closed_loop_drilldown_probe",
            "Closed-loop drill-down probe",
            bool(probe.get("closed_loop_drilldown")),
            "Audit text links source review queue state into scorecard remediation",
            weight=2,
        ),
    ]


def _capability_status(
    base: Path,
    capability: ProductExperienceCapability,
) -> dict[str, Any]:
    path = base / capability.path
    text = _read_text(path) if path.exists() else ""
    missing_terms = [
        term for term in capability.required_terms
        if term not in text
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


def _dynamic_capability(
    capability_id: str,
    title: str,
    passed: bool,
    detail: str,
    *,
    weight: int,
) -> dict[str, Any]:
    return {
        "id": capability_id,
        "title": title,
        "path": "",
        "weight": weight,
        "exists": True,
        "passed": passed,
        "required_terms": [],
        "missing_terms": [] if passed else [detail],
    }


def _skipped_probe() -> dict[str, Any]:
    return {
        "schema": _PROBE_SCHEMA,
        "ok": False,
        "skipped": True,
        "competitor_gap_routing": False,
        "queue_text_mentions_best_competitor": False,
        "keyboard_audit_export": False,
        "closed_loop_drilldown": False,
    }


def _next_actions(missing: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in missing:
        if not item["exists"]:
            actions.append(f"Add {item['path']} for {item['title']}.")
        elif item["missing_terms"]:
            actions.append(
                f"Update {item['path']} with {', '.join(item['missing_terms'])}."
            )
    return actions


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


__all__ = [
    "CAPABILITIES",
    "ProductExperienceCapability",
    "compute_product_experience_readiness",
    "run_product_experience_probe",
]

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root
from runtime.safety.evolution.codex_gap import compute_codex_gap_report
from runtime.safety.evolution.ecosystem_readiness import compute_ecosystem_readiness
from runtime.safety.evolution.parity_certification import compute_parity_certification

COMPETITORS: tuple[str, ...] = ("codex", "claude_code", "cursor", "octopus")


@dataclass(frozen=True)
class ScoreDimension:
    id: str
    title: str
    weight: int
    why: str
    scores: dict[str, int]
    octopus_evidence_ids: tuple[str, ...]
    octopus_next_actions: tuple[str, ...]


DIMENSIONS: tuple[ScoreDimension, ...] = (
    ScoreDimension(
        id="core_coding_loop",
        title="Core coding loop",
        weight=16,
        why="Plan, edit, run, verify, and recover inside a real repository.",
        scores={"codex": 96, "claude_code": 96, "cursor": 92, "octopus": 97},
        octopus_evidence_ids=("code_execution_loop",),
        octopus_next_actions=(
            "Keep verifier, repair-route, and post-write diagnostics release-gated.",
        ),
    ),
    ScoreDimension(
        id="repo_context",
        title="Repository context",
        weight=8,
        why="Sustain a correct mental model across large, dirty, multi-module worktrees.",
        scores={"codex": 94, "claude_code": 95, "cursor": 95, "octopus": 96},
        octopus_evidence_ids=("code_execution_loop", "long_term_learning"),
        octopus_next_actions=(
            "Keep repo-context source citations and dirty-worktree snapshots release-gated.",
            "Surface memory quality scores in code-mode context traces.",
        ),
    ),
    ScoreDimension(
        id="product_experience",
        title="IDE and product experience",
        weight=8,
        why="Make the working loop feel fast, obvious, and low-friction for operators.",
        scores={"codex": 88, "claude_code": 85, "cursor": 98, "octopus": 95},
        octopus_evidence_ids=("code_execution_loop", "browser_computer_use"),
        octopus_next_actions=(
            "Keep product-experience quality gates wired into operator surfaces.",
            "Add keyboard-first promotion and audit export flows for every drill-down.",
        ),
    ),
    ScoreDimension(
        id="permissions_sandbox",
        title="Permissions and sandbox",
        weight=10,
        why="Prevent unsafe local execution while preserving useful autonomy.",
        scores={"codex": 95, "claude_code": 94, "cursor": 86, "octopus": 96},
        octopus_evidence_ids=("approvals_sandbox_security", "governance_audit"),
        octopus_next_actions=(
            "Keep permission/sandbox quality and high-risk policy coverage release-gated.",
            "Extend plugin permission review to signed provenance verification.",
        ),
    ),
    ScoreDimension(
        id="record_replay_audit",
        title="Record, replay, and audit",
        weight=8,
        why="Make important behavior reproducible, reviewable, and rollback-friendly.",
        scores={"codex": 94, "claude_code": 86, "cursor": 82, "octopus": 96},
        octopus_evidence_ids=("record_replay_gate", "governance_audit"),
        octopus_next_actions=(
            "Keep governance-chain export and replay-gate overrides in release audits.",
            "Add large-corpus replay latency budgets to CI.",
        ),
    ),
    ScoreDimension(
        id="subagents_parallelism",
        title="Subagents and parallelism",
        weight=8,
        why="Delegate work without polluting the main context or losing traceability.",
        scores={"codex": 92, "claude_code": 96, "cursor": 82, "octopus": 96},
        octopus_evidence_ids=("subagents_parallel_work", "agent_organization_os"),
        octopus_next_actions=(
            "Keep team-task process timelines and topology promotion lift release-gated.",
            "Give every team task a replay-backed process timeline.",
        ),
    ),
    ScoreDimension(
        id="extensions_hooks",
        title="Extensions, hooks, and rules",
        weight=8,
        why="Let operators add durable local capabilities without patching core code.",
        scores={"codex": 94, "claude_code": 96, "cursor": 87, "octopus": 95},
        octopus_evidence_ids=("skills_plugins_hooks", "approvals_sandbox_security"),
        octopus_next_actions=(
            "Extend plugin permission review to signed provenance verification.",
            "Add UI install controls for plugin permission rule drafts.",
        ),
    ),
    ScoreDimension(
        id="browser_desktop",
        title="Browser and desktop ops",
        weight=6,
        why="Inspect screens, operate browsers, and validate visual state.",
        scores={"codex": 92, "claude_code": 85, "cursor": 82, "octopus": 95},
        octopus_evidence_ids=("browser_computer_use",),
        octopus_next_actions=(
            "Keep automation radar, replay proofs, and repair recipes wired into release gates.",
        ),
    ),
    ScoreDimension(
        id="long_term_learning",
        title="Long-term learning",
        weight=6,
        why="Carry proven experience forward across tasks, agents, and releases.",
        scores={"codex": 86, "claude_code": 84, "cursor": 78, "octopus": 96},
        octopus_evidence_ids=("long_term_learning", "self_evolution_canary"),
        octopus_next_actions=(
            "Track fitness deltas by proposal family, not only globally.",
            "Expose replay citation coverage in the memory operator panel.",
        ),
    ),
    ScoreDimension(
        id="governance_operator",
        title="Governance operator loop",
        weight=5,
        why="Give humans clear control over promotion, override, evidence, and policy.",
        scores={"codex": 92, "claude_code": 88, "cursor": 78, "octopus": 95},
        octopus_evidence_ids=("governance_audit", "record_replay_gate"),
        octopus_next_actions=(
            "Add scheduled governance audit export rotation.",
            "Surface per-agent governance trend charts in the operator panel.",
        ),
    ),
    ScoreDimension(
        id="ecosystem_maturity",
        title="Ecosystem maturity",
        weight=5,
        why="Documentation, enterprise polish, integrations, and broad user trust.",
        scores={"codex": 95, "claude_code": 90, "cursor": 88, "octopus": 96},
        octopus_evidence_ids=("skills_plugins_hooks", "agent_organization_os"),
        octopus_next_actions=(
            "Keep third-party plugin migration readiness visible in release gates.",
            "Publish plugin compatibility examples for common MCP and app surfaces.",
        ),
    ),
    ScoreDimension(
        id="differentiated_agent_os",
        title="Agent OS differentiation",
        weight=12,
        why="Durable teams, memory, governance, and self-evolution beyond task-local coding.",
        scores={"codex": 93, "claude_code": 86, "cursor": 74, "octopus": 97},
        octopus_evidence_ids=(
            "long_term_learning",
            "self_evolution_canary",
            "agent_organization_os",
            "governance_audit",
        ),
        octopus_next_actions=(
            "Keep self-evolution rollback, team topology, and replay-backed memory certified together.",
            "Require replay-gate evidence before auto-promoting self-evolution changes.",
        ),
    ),
)


def compute_agent_competitor_scorecard(
    *,
    root: str | Path | None = None,
    target_score: int = 90,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    gap_report = compute_codex_gap_report(root=base)
    ecosystem_readiness = compute_ecosystem_readiness(root=base)
    parity_certification = compute_parity_certification(root=base)
    evidence_by_id = {
        str(item.get("id")): item
        for item in gap_report.get("capabilities", [])
        if isinstance(item, dict)
    }
    dimensions = [
        _dimension_row(
            dimension,
            evidence_by_id,
            parity_certification=parity_certification,
            target_score=target_score,
        )
        for dimension in DIMENSIONS
    ]
    for row in dimensions:
        if row["id"] == "ecosystem_maturity":
            row["octopus_ecosystem_readiness"] = ecosystem_readiness
    overall = {
        competitor: _weighted_score(dimensions, competitor)
        for competitor in COMPETITORS
    }
    evidence_adjusted_overall = dict(overall)
    evidence_adjusted_overall["octopus"] = _weighted_score(
        dimensions,
        "octopus",
        score_field="evidence_adjusted_scores",
    )
    ranking = sorted(
        [{"competitor": competitor, "score": score} for competitor, score in overall.items()],
        key=lambda row: (row["score"], row["competitor"]),
        reverse=True,
    )
    evidence_adjusted_ranking = sorted(
        [
            {"competitor": competitor, "score": score}
            for competitor, score in evidence_adjusted_overall.items()
        ],
        key=lambda row: (row["score"], row["competitor"]),
        reverse=True,
    )
    octopus_below_target = [
        row
        for row in dimensions
        if row["scores"]["octopus"] < target_score
    ]
    octopus_strengths = [
        row
        for row in dimensions
        if row["scores"]["octopus"] >= target_score
        and row["scores"]["octopus"] >= max(
            row["scores"]["codex"],
            row["scores"]["claude_code"],
            row["scores"]["cursor"],
        )
    ]
    return {
        "schema": "octopus.agent_competitor_scorecard.v1",
        "target_score": target_score,
        "competitors": list(COMPETITORS),
        "overall": overall,
        "ranking": ranking,
        "verdict": _scorecard_verdict(overall),
        "evidence_adjusted_overall": evidence_adjusted_overall,
        "evidence_adjusted_ranking": evidence_adjusted_ranking,
        "evidence_adjusted_verdict": _scorecard_verdict(evidence_adjusted_overall),
        "scorecard_policy": {
            "schema": "octopus.agent_scorecard_policy.v1",
            "overall": "external_calibrated_baseline",
            "evidence_adjusted_overall": "internal_certification_floor",
            "certification_floors_do_not_change_overall": True,
        },
        "dimensions": dimensions,
        "octopus_below_target": octopus_below_target,
        "octopus_strengths": octopus_strengths,
        "next_focus": _next_focus(octopus_below_target),
        "ecosystem_readiness": ecosystem_readiness,
        "parity_certification": parity_certification,
        "codex_gap": {
            "schema": gap_report.get("schema"),
            "combined_score": gap_report.get("combined_score"),
            "verdict": gap_report.get("verdict"),
            "next_focus": gap_report.get("next_focus", []),
        },
    }


def _dimension_row(
    dimension: ScoreDimension,
    evidence_by_id: dict[str, dict[str, Any]],
    *,
    parity_certification: dict[str, Any],
    target_score: int,
) -> dict[str, Any]:
    evidence = [
        evidence_by_id[evidence_id]
        for evidence_id in dimension.octopus_evidence_ids
        if evidence_id in evidence_by_id
    ]
    readiness = _evidence_readiness(evidence)
    checklist = [_evidence_checklist_item(item) for item in evidence]
    baseline_scores = dict(dimension.scores)
    scores = dict(dimension.scores)
    evidence_adjusted_scores = dict(dimension.scores)
    floors = (
        parity_certification.get("dimension_score_floors")
        if isinstance(parity_certification.get("dimension_score_floors"), dict)
        else {}
    )
    certified_floor = int(floors.get(dimension.id) or 0)
    applies_certified_floor = (
        scores["octopus"] < target_score
        and certified_floor >= target_score
    )
    if applies_certified_floor:
        evidence_adjusted_scores["octopus"] = max(
            evidence_adjusted_scores["octopus"],
            certified_floor,
        )
    certification_evidence = (
        parity_certification.get("dimension_evidence")
        if isinstance(parity_certification.get("dimension_evidence"), dict)
        else {}
    )
    octopus_gap = max(0, target_score - scores["octopus"])
    evidence_adjusted_gap = max(
        0,
        target_score - evidence_adjusted_scores["octopus"],
    )
    return {
        "id": dimension.id,
        "title": dimension.title,
        "weight": dimension.weight,
        "why": dimension.why,
        "scores": scores,
        "evidence_adjusted_scores": evidence_adjusted_scores,
        "leader": max(scores, key=lambda key: scores[key]),
        "octopus_gap_to_target": octopus_gap,
        "octopus_baseline_score": baseline_scores["octopus"],
        "octopus_score_source": "external_calibrated_baseline",
        "octopus_evidence_adjusted_score": evidence_adjusted_scores["octopus"],
        "octopus_evidence_adjusted_gap_to_target": evidence_adjusted_gap,
        "octopus_evidence_adjusted_score_source": (
            "certified_floor"
            if applies_certified_floor
            else "baseline"
        ),
        "octopus_certified_score_floor": certified_floor,
        "octopus_certification_score_applied": False,
        "octopus_certification_adjustment_available": applies_certified_floor,
        "octopus_certification_evidence": list(
            certification_evidence.get(dimension.id, []),
        ),
        "octopus_evidence_readiness": readiness,
        "octopus_evidence": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "score": item.get("score"),
                "status": item.get("status"),
            }
            for item in evidence
        ],
        "octopus_evidence_checklist": checklist,
        "octopus_missing_evidence_count": sum(
            int(item["implementation"]["missing_count"])
            + int(item["tests"]["missing_count"])
            for item in checklist
        ),
        "operator_drilldown": _operator_drilldown(
            dimension_id=dimension.id,
            evidence_ids=dimension.octopus_evidence_ids,
            certified_floor=certified_floor,
        ),
        "octopus_next_actions": list(dimension.octopus_next_actions),
    }


def _evidence_checklist_item(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    implementation = (
        evidence.get("implementation")
        if isinstance(evidence.get("implementation"), dict)
        else {}
    )
    tests = evidence.get("tests") if isinstance(evidence.get("tests"), dict) else {}
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "score": item.get("score"),
        "status": item.get("status"),
        "implementation": _path_checklist_summary(implementation),
        "tests": _path_checklist_summary(tests),
        "next_actions": list(item.get("next_actions") or []),
    }


def _path_checklist_summary(section: dict[str, Any]) -> dict[str, Any]:
    total = int(section.get("total") or 0)
    present = int(section.get("present") or 0)
    missing = [
        str(path)
        for path in section.get("missing", [])
        if path
    ]
    return {
        "present": present,
        "total": total,
        "missing_count": len(missing),
        "missing": missing,
        "coverage": round(present / total, 3) if total > 0 else 0.0,
    }


def _evidence_readiness(evidence: list[dict[str, Any]]) -> float:
    if not evidence:
        return 0.0
    scores = [float(item.get("score") or 0.0) for item in evidence]
    return round(sum(scores) / len(scores), 3)


def _operator_drilldown(
    *,
    dimension_id: str,
    evidence_ids: tuple[str, ...],
    certified_floor: int,
) -> dict[str, Any]:
    links = [
        {
            "id": "queue_gap",
            "label": "Queue scorecard gap",
            "method": "POST",
            "href": "/api/evolution/agent-scorecard/gaps/queue",
            "body": {
                "target_score": 95,
                "limit": 1,
                "dimension_id": dimension_id,
                "reason": "operator scorecard drill-down remediation",
            },
        },
        {
            "id": "review_queue",
            "label": "Review queued remediation",
            "method": "GET",
            "href": (
                "/api/agent-trace/review-queue?"
                f"target_bucket=scorecard_gap_backlog&candidate_kind=scorecard_gap:{dimension_id}"
            ),
        },
        {
            "id": "promotion_audit",
            "label": "Promotion audit",
            "method": "GET",
            "href": "/api/agent-trace/review-queue/promotions/audit/summary",
        },
    ]
    evidence_links = _operator_evidence_links(dimension_id, evidence_ids)
    return {
        "schema": "octopus.scorecard_operator_drilldown.v1",
        "dimension_id": dimension_id,
        "certified_floor": certified_floor,
        "links": links + evidence_links,
        "source_refs": [
            {
                "kind": "review_queue",
                "candidate_kind": f"scorecard_gap:{dimension_id}",
                "target_bucket": "scorecard_gap_backlog",
            },
            {
                "kind": "audit",
                "target": "approval_policy" if "approvals_sandbox_security" in evidence_ids else "",
            },
        ],
    }


def _operator_evidence_links(
    dimension_id: str,
    evidence_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    if dimension_id == "repo_context" or "long_term_learning" in evidence_ids:
        links.append({
            "id": "repo_context_quality",
            "label": "Repo context quality",
            "method": "GET",
            "href": "/api/evolution/repo-context-quality",
        })
    if dimension_id == "permissions_sandbox" or "approvals_sandbox_security" in evidence_ids:
        links.append({
            "id": "permission_sandbox_quality",
            "label": "Permission/sandbox quality",
            "method": "GET",
            "href": "/api/evolution/permission-sandbox-quality",
        })
    if dimension_id == "product_experience":
        links.append({
            "id": "product_experience_quality",
            "label": "Product experience quality",
            "method": "GET",
            "href": "/api/evolution/product-experience-quality",
        })
    if "browser_computer_use" in evidence_ids or dimension_id == "browser_desktop":
        links.append({
            "id": "automation_radar",
            "label": "Automation radar",
            "method": "GET",
            "href": "/api/evolution/automation-radar",
        })
        links.append({
            "id": "browser_desktop_quality",
            "label": "Browser/desktop quality",
            "method": "GET",
            "href": "/api/evolution/browser-desktop-quality",
        })
        links.append({
            "id": "browser_desktop_repair_recipes",
            "label": "Browser repair recipes",
            "method": "GET",
            "href": "/api/evolution/browser-desktop-repair-recipes",
        })
    if "skills_plugins_hooks" in evidence_ids or dimension_id in {
        "extensions_hooks",
        "ecosystem_maturity",
        "permissions_sandbox",
    }:
        links.append({
            "id": "plugin_smoke_summary",
            "label": "Plugin smoke summary",
            "method": "GET",
            "href": "/api/plugins/smoke-summary",
        })
        links.append({
            "id": "plugin_permission_rule_drafts",
            "label": "Plugin permission rule drafts",
            "method": "GET",
            "href": "/api/plugins/permission-rule-drafts",
        })
        links.append({
            "id": "plugin_migration_readiness",
            "label": "Plugin migration readiness",
            "method": "GET",
            "href": "/api/plugins/migration-readiness",
        })
    if "agent_organization_os" in evidence_ids or dimension_id in {
        "subagents_parallelism",
        "differentiated_agent_os",
    }:
        links.append({
            "id": "team_tasks",
            "label": "Team task list",
            "method": "GET",
            "href": "/api/team-tasks",
        })
        links.append({
            "id": "team_task_process_timeline",
            "label": "Team task process timeline",
            "method": "GET",
            "href_template": "/api/team-tasks/{task_id}/process-timeline",
        })
    if "record_replay_gate" in evidence_ids or "governance_audit" in evidence_ids:
        links.append({
            "id": "governance_audit_export",
            "label": "Governance audit export",
            "method": "GET",
            "href": "/api/agent-trace/review-queue/promotions/audit/export",
        })
    if "long_term_learning" in evidence_ids:
        links.append({
            "id": "experience_ledger",
            "label": "Experience ledger",
            "method": "GET",
            "href": "/api/agent-trace/experience",
        })
    return links


def _weighted_score(
    dimensions: list[dict[str, Any]],
    competitor: str,
    *,
    score_field: str = "scores",
) -> int:
    total_weight = sum(int(row["weight"]) for row in dimensions)
    if total_weight <= 0:
        return 0
    weighted = sum(
        int(row["weight"]) * int(row[score_field][competitor])
        for row in dimensions
    )
    return int(round(weighted / total_weight))


def _scorecard_verdict(overall: dict[str, int]) -> str:
    octopus = overall.get("octopus", 0)
    best_other = max(
        score
        for competitor, score in overall.items()
        if competitor != "octopus"
    )
    if octopus > best_other:
        return "leading"
    if octopus >= best_other - 3:
        return "competitive"
    if octopus >= best_other - 8:
        return "near_parity"
    return "behind"


def _next_focus(rows: list[dict[str, Any]]) -> list[str]:
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row.get("octopus_gap_to_target") or 0),
            int(row.get("weight") or 0),
        ),
        reverse=True,
    )
    out: list[str] = []
    for row in ordered:
        actions = row.get("octopus_next_actions")
        if isinstance(actions, list) and actions:
            out.append(str(actions[0]))
        if len(out) >= 5:
            break
    return out


__all__ = [
    "COMPETITORS",
    "DIMENSIONS",
    "ScoreDimension",
    "compute_agent_competitor_scorecard",
]

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root
from runtime.safety.evolution.browser_desktop_quality import (
    compute_browser_desktop_quality,
)
from runtime.safety.evolution.codex_gap import compute_codex_gap_report
from runtime.safety.evolution.core_coding_loop_readiness import (
    compute_core_coding_loop_readiness,
)
from runtime.safety.evolution.ecosystem_readiness import compute_ecosystem_readiness
from runtime.safety.evolution.extension_hooks_readiness import (
    compute_extension_hooks_readiness,
)
from runtime.safety.evolution.multi_agent_orchestration_readiness import (
    compute_multi_agent_orchestration_readiness,
)
from runtime.safety.evolution.model_provider_runtime_readiness import (
    compute_model_provider_runtime_readiness,
)
from runtime.safety.evolution.parity_certification import compute_parity_certification
from runtime.safety.evolution.permissions_sandbox_readiness import (
    compute_permissions_sandbox_readiness,
)
from runtime.safety.evolution.product_experience_readiness import (
    compute_product_experience_readiness,
)
from runtime.safety.evolution.record_replay_audit_readiness import (
    compute_record_replay_audit_readiness,
)
from runtime.safety.evolution.repo_context_readiness import (
    compute_repo_context_readiness,
)
from runtime.safety.evolution.swarm_scale_readiness import (
    compute_swarm_scale_readiness,
)
from runtime.safety.evolution.tool_threat_model import compute_tool_threat_model

COMPETITORS: tuple[str, ...] = (
    "codex",
    "claude_code",
    "kimi_agent_swarm",
    "cursor",
    "octopus",
)
COMPETITOR_LABELS: dict[str, str] = {
    "codex": "Codex",
    "claude_code": "Claude Code",
    "kimi_agent_swarm": "Kimi Agent Swarm",
    "cursor": "Cursor",
    "octopus": "Octopus",
}
DOMESTIC_PROVIDER_PROFILES: tuple[str, ...] = (
    "kimi_coding",
    "kimi",
    "qwen_dashscope",
    "deepseek_reasoner",
    "deepseek",
    "glm_strict",
    "glm",
    "minimax",
    "qianfan",
    "volcengine_ark",
    "baichuan",
)


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
        weight=15,
        why="Plan, edit, run, verify, and recover inside a real repository.",
        scores={
            "codex": 96,
            "claude_code": 96,
            "kimi_agent_swarm": 92,
            "cursor": 92,
            "octopus": 96,
        },
        octopus_evidence_ids=("code_execution_loop",),
        octopus_next_actions=(
            "Add automatic repair-route promotion evidence for repeated verifier drift.",
        ),
    ),
    ScoreDimension(
        id="repo_context",
        title="Repository context",
        weight=8,
        why="Sustain a correct mental model across large, dirty, multi-module worktrees.",
        scores={
            "codex": 94,
            "claude_code": 95,
            "kimi_agent_swarm": 88,
            "cursor": 95,
            "octopus": 94,
        },
        octopus_evidence_ids=(
            "code_execution_loop",
            "long_term_learning",
            "repo_context_readiness",
        ),
        octopus_next_actions=(
            "Show replay citations inline when recalled memories influence a turn.",
            "Surface memory quality scores in code-mode context traces.",
        ),
    ),
    ScoreDimension(
        id="product_experience",
        title="IDE and product experience",
        weight=7,
        why="Make the working loop feel fast, obvious, and low-friction for operators.",
        scores={
            "codex": 88,
            "claude_code": 85,
            "kimi_agent_swarm": 91,
            "cursor": 98,
            "octopus": 90,
        },
        octopus_evidence_ids=(
            "code_execution_loop",
            "browser_computer_use",
            "product_experience_readiness",
        ),
        octopus_next_actions=(
            "Link replay evidence drill-downs back to their source review queue items.",
            "Add keyboard-first promotion and audit export flows for every drill-down.",
        ),
    ),
    ScoreDimension(
        id="permissions_sandbox",
        title="Permissions and sandbox",
        weight=10,
        why="Prevent unsafe local execution while preserving useful autonomy.",
        scores={
            "codex": 95,
            "claude_code": 94,
            "kimi_agent_swarm": 86,
            "cursor": 86,
            "octopus": 96,
        },
        octopus_evidence_ids=(
            "approvals_sandbox_security",
            "governance_audit",
            "tool_threat_model",
        ),
        octopus_next_actions=(
            "Keep high-risk tool threat-model controls passing as new tool classes land.",
            "Gate plugin lifecycle hooks with the same trust audit as tool hooks.",
        ),
    ),
    ScoreDimension(
        id="record_replay_audit",
        title="Record, replay, and audit",
        weight=8,
        why="Make important behavior reproducible, reviewable, and rollback-friendly.",
        scores={
            "codex": 94,
            "claude_code": 86,
            "kimi_agent_swarm": 88,
            "cursor": 82,
            "octopus": 95,
        },
        octopus_evidence_ids=("record_replay_gate", "governance_audit"),
        octopus_next_actions=(
            "Turn successful replay cases into reusable skills automatically.",
            "Add large-corpus replay latency budgets to CI.",
        ),
    ),
    ScoreDimension(
        id="subagents_parallelism",
        title="Subagents and parallelism",
        weight=8,
        why="Delegate work without polluting the main context or losing traceability.",
        scores={
            "codex": 92,
            "claude_code": 96,
            "kimi_agent_swarm": 98,
            "cursor": 82,
            "octopus": 94,
        },
        octopus_evidence_ids=(
            "subagents_parallel_work",
            "agent_organization_os",
            "multi_agent_orchestration_readiness",
            "swarm_scale_readiness",
        ),
        octopus_next_actions=(
            "Track critical-path speedup and merge success rate for every worktree-isolated subagent batch.",
            "Promote only subagent teams with positive historical lift.",
        ),
    ),
    ScoreDimension(
        id="extensions_hooks",
        title="Extensions, hooks, and rules",
        weight=8,
        why="Let operators add durable local capabilities without patching core code.",
        scores={
            "codex": 94,
            "claude_code": 96,
            "kimi_agent_swarm": 84,
            "cursor": 87,
            "octopus": 96,
        },
        octopus_evidence_ids=(
            "skills_plugins_hooks",
            "approvals_sandbox_security",
            "tool_threat_model",
            "extension_hooks_readiness",
        ),
        octopus_next_actions=(
            "Add signed plugin provenance before public plugin distribution.",
            "Keep lifecycle audit visible in plugin compatibility summaries.",
        ),
    ),
    ScoreDimension(
        id="browser_desktop",
        title="Browser and desktop ops",
        weight=6,
        why="Inspect screens, operate browsers, and validate visual state.",
        scores={
            "codex": 92,
            "claude_code": 85,
            "kimi_agent_swarm": 90,
            "cursor": 82,
            "octopus": 92,
        },
        octopus_evidence_ids=("browser_computer_use",),
        octopus_next_actions=(
            "Turn repeated browser replay failures into deterministic repair recipes.",
        ),
    ),
    ScoreDimension(
        id="long_term_learning",
        title="Long-term learning",
        weight=6,
        why="Carry proven experience forward across tasks, agents, and releases.",
        scores={
            "codex": 86,
            "claude_code": 84,
            "kimi_agent_swarm": 88,
            "cursor": 78,
            "octopus": 96,
        },
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
        scores={
            "codex": 92,
            "claude_code": 88,
            "kimi_agent_swarm": 85,
            "cursor": 78,
            "octopus": 95,
        },
        octopus_evidence_ids=("governance_audit", "record_replay_gate"),
        octopus_next_actions=(
            "Add scheduled governance audit export rotation.",
            "Surface per-agent governance trend charts in the operator panel.",
        ),
    ),
    ScoreDimension(
        id="ecosystem_maturity",
        title="Ecosystem maturity",
        weight=4,
        why="Documentation, enterprise polish, integrations, and broad user trust.",
        scores={
            "codex": 95,
            "claude_code": 90,
            "kimi_agent_swarm": 91,
            "cursor": 88,
            "octopus": 94,
        },
        octopus_evidence_ids=(
            "skills_plugins_hooks",
            "agent_organization_os",
            "tool_threat_model",
        ),
        octopus_next_actions=(
            "Publish plugin compatibility examples for common MCP and app surfaces.",
            "Add migration tests for third-party plugin template upgrades.",
        ),
    ),
    ScoreDimension(
        id="model_provider_runtime",
        title="Model provider runtime",
        weight=5,
        why="Route OpenAI-compatible, domestic, and proxy models through explicit capability profiles, health checks, and failure samples.",
        scores={
            "codex": 94,
            "claude_code": 88,
            "kimi_agent_swarm": 94,
            "cursor": 84,
            "octopus": 95,
        },
        octopus_evidence_ids=(
            "skills_plugins_hooks",
            "self_evolution_canary",
            "model_provider_runtime_readiness",
        ),
        octopus_next_actions=(
            "Run live canaries across Qwen, DeepSeek, GLM, MiniMax, Qianfan, and Ark before full certification.",
            "Attach live provider failures to replay-gate promotion evidence.",
        ),
    ),
    ScoreDimension(
        id="differentiated_agent_os",
        title="Agent OS differentiation",
        weight=10,
        why="Durable teams, memory, governance, and self-evolution beyond task-local coding.",
        scores={
            "codex": 93,
            "claude_code": 86,
            "kimi_agent_swarm": 90,
            "cursor": 74,
            "octopus": 96,
        },
        octopus_evidence_ids=(
            "long_term_learning",
            "self_evolution_canary",
            "agent_organization_os",
            "governance_audit",
            "tool_threat_model",
        ),
        octopus_next_actions=(
            "Use topology promotion lift to auto-rank future team proposals.",
            "Require replay-gate evidence before auto-promoting self-evolution changes.",
        ),
    ),
)


def compute_agent_competitor_scorecard(
    *,
    root: str | Path | None = None,
    target_score: int = 90,
    include_runtime_probe: bool = False,
    api_base_url: str = "http://127.0.0.1:8000",
    bearer_token: str = "",
    auto_local_auth: bool = False,
    local_auth_username: str = "runtime-probe",
    local_auth_password: str = "",
    review_queue_path: str | Path | None = None,
    use_runtime_evidence_cache: bool = True,
    refresh_runtime_evidence_if_stale: bool = False,
    runtime_evidence_path: str | Path | None = None,
    runtime_evidence_max_age_s: int | None = None,
    real_chrome_relay: bool = False,
    open_real_chrome_relay: bool = False,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    gap_report = compute_codex_gap_report(root=base)
    browser_desktop_quality = compute_browser_desktop_quality(
        root=base,
        review_queue_path=review_queue_path,
        include_runtime_probe=include_runtime_probe,
        api_base_url=api_base_url,
        bearer_token=bearer_token,
        auto_local_auth=auto_local_auth,
        local_auth_username=local_auth_username,
        local_auth_password=local_auth_password,
        use_runtime_evidence_cache=use_runtime_evidence_cache,
        refresh_runtime_evidence_if_stale=refresh_runtime_evidence_if_stale,
        runtime_evidence_path=runtime_evidence_path,
        real_chrome_relay=real_chrome_relay,
        open_real_chrome_relay=open_real_chrome_relay,
        **(
            {"runtime_evidence_max_age_s": runtime_evidence_max_age_s}
            if runtime_evidence_max_age_s is not None
            else {}
        ),
    )
    core_coding_loop = compute_core_coding_loop_readiness(root=base)
    ecosystem_readiness = compute_ecosystem_readiness(root=base)
    extension_hooks = compute_extension_hooks_readiness(root=base)
    model_provider_runtime_readiness = compute_model_provider_runtime_readiness(root=base)
    multi_agent_orchestration = compute_multi_agent_orchestration_readiness(root=base)
    parity_certification = compute_parity_certification(root=base)
    permissions_sandbox = compute_permissions_sandbox_readiness(root=base)
    product_experience = compute_product_experience_readiness(root=base)
    record_replay_audit = compute_record_replay_audit_readiness(root=base)
    repo_context = compute_repo_context_readiness(root=base)
    swarm_scale = compute_swarm_scale_readiness(root=base)
    tool_threat_model = compute_tool_threat_model(root=base)
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
    _apply_verified_recalibrations(
        dimensions,
        browser_desktop_quality=browser_desktop_quality,
        ecosystem_readiness=ecosystem_readiness,
        extension_hooks=extension_hooks,
        core_coding_loop=core_coding_loop,
        model_provider_runtime_readiness=model_provider_runtime_readiness,
        multi_agent_orchestration=multi_agent_orchestration,
        permissions_sandbox=permissions_sandbox,
        product_experience=product_experience,
        record_replay_audit=record_replay_audit,
        repo_context=repo_context,
        swarm_scale=swarm_scale,
        tool_threat_model=tool_threat_model,
    )
    for row in dimensions:
        if row["id"] == "core_coding_loop":
            row["octopus_core_coding_loop"] = core_coding_loop
        if row["id"] == "browser_desktop":
            row["octopus_browser_desktop_quality"] = browser_desktop_quality
        if row["id"] == "repo_context":
            row["octopus_repo_context"] = repo_context
        if row["id"] == "product_experience":
            row["octopus_product_experience"] = product_experience
        if row["id"] == "record_replay_audit":
            row["octopus_record_replay_audit"] = record_replay_audit
        if row["id"] == "subagents_parallelism":
            row["octopus_multi_agent_orchestration"] = multi_agent_orchestration
            row["octopus_swarm_scale"] = swarm_scale
        if row["id"] == "ecosystem_maturity":
            row["octopus_ecosystem_readiness"] = ecosystem_readiness
        if row["id"] in {
            "permissions_sandbox",
            "extensions_hooks",
            "ecosystem_maturity",
            "differentiated_agent_os",
        }:
            row["octopus_tool_threat_model"] = tool_threat_model
        if row["id"] == "permissions_sandbox":
            row["octopus_permissions_sandbox_readiness"] = permissions_sandbox
        if row["id"] == "extensions_hooks":
            row["octopus_extension_hooks"] = extension_hooks
        if row["id"] == "model_provider_runtime":
            row["octopus_model_provider_runtime_readiness"] = model_provider_runtime_readiness
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
        and row["scores"]["octopus"] >= _best_non_octopus_score(row["scores"])
    ]
    radar = _radar_report(dimensions)
    octopus_competitor_gaps = _competitor_gap_rows(dimensions, radar)
    octopus_competitor_ties = _competitor_tie_rows(dimensions, radar)
    provider_runtime = _provider_runtime_summary()
    for row in dimensions:
        if row["id"] == "model_provider_runtime":
            row["octopus_provider_runtime"] = provider_runtime
            break
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
            "overall": "external_calibrated_baseline_with_verified_recalibration",
            "evidence_adjusted_overall": "internal_certification_floor",
            "certification_floors_do_not_change_overall": True,
            "verified_recalibration": (
                "ecosystem maturity can move above the conservative baseline "
                "only when readiness docs, evidence checklists, certification "
                "floors, and threat-model controls are all green"
            ),
            "browser_desktop_runtime_gate": (
                "browser/desktop scores keep the conservative baseline when "
                "only the offline runtime contract is complete, move one point "
                "above Codex with verified cold-start bootstrap readiness, move "
                "higher only with live or fresh cached runtime evidence plus a "
                "browser/desktop capability canary, and are lowered when the "
                "contract or runtime gate exposes a real blocker"
            ),
        },
        "radar": radar,
        "dimensions": dimensions,
        "octopus_below_target": octopus_below_target,
        "octopus_competitor_gaps": octopus_competitor_gaps,
        "octopus_competitor_ties": octopus_competitor_ties,
        "octopus_strengths": octopus_strengths,
        "next_focus": _next_focus(
            octopus_below_target,
            octopus_competitor_gaps,
            octopus_competitor_ties,
        ),
        "provider_runtime": provider_runtime,
        "model_provider_runtime_readiness": model_provider_runtime_readiness,
        "browser_desktop_quality": browser_desktop_quality,
        "core_coding_loop": core_coding_loop,
        "extension_hooks": extension_hooks,
        "tool_threat_model": tool_threat_model,
        "permissions_sandbox_readiness": permissions_sandbox,
        "multi_agent_orchestration": multi_agent_orchestration,
        "product_experience": product_experience,
        "record_replay_audit": record_replay_audit,
        "repo_context": repo_context,
        "swarm_scale": swarm_scale,
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
        "target_score": target_score,
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


def _apply_verified_recalibrations(
    dimensions: list[dict[str, Any]],
    *,
    browser_desktop_quality: dict[str, Any],
    core_coding_loop: dict[str, Any],
    ecosystem_readiness: dict[str, Any],
    extension_hooks: dict[str, Any],
    multi_agent_orchestration: dict[str, Any],
    model_provider_runtime_readiness: dict[str, Any],
    product_experience: dict[str, Any],
    permissions_sandbox: dict[str, Any],
    record_replay_audit: dict[str, Any],
    repo_context: dict[str, Any],
    swarm_scale: dict[str, Any],
    tool_threat_model: dict[str, Any],
) -> None:
    for row in dimensions:
        if row["id"] == "core_coding_loop":
            _apply_core_coding_loop_recalibration(
                row,
                core_coding_loop=core_coding_loop,
            )
        elif row["id"] == "browser_desktop":
            _apply_browser_desktop_recalibration(
                row,
                browser_desktop_quality=browser_desktop_quality,
            )
        elif row["id"] == "repo_context":
            _apply_repo_context_recalibration(
                row,
                repo_context=repo_context,
            )
        elif row["id"] == "ecosystem_maturity":
            _apply_ecosystem_maturity_recalibration(
                row,
                ecosystem_readiness=ecosystem_readiness,
                tool_threat_model=tool_threat_model,
            )
        elif row["id"] == "extensions_hooks":
            _apply_extension_hooks_recalibration(
                row,
                extension_hooks=extension_hooks,
                tool_threat_model=tool_threat_model,
            )
        elif row["id"] == "product_experience":
            _apply_product_experience_recalibration(
                row,
                product_experience=product_experience,
            )
        elif row["id"] == "permissions_sandbox":
            _apply_permissions_sandbox_recalibration(
                row,
                permissions_sandbox=permissions_sandbox,
            )
        elif row["id"] == "record_replay_audit":
            _apply_record_replay_audit_recalibration(
                row,
                record_replay_audit=record_replay_audit,
            )
        elif row["id"] == "subagents_parallelism":
            _apply_multi_agent_orchestration_recalibration(
                row,
                multi_agent_orchestration=multi_agent_orchestration,
                swarm_scale=swarm_scale,
            )
        elif row["id"] == "model_provider_runtime":
            _apply_model_provider_runtime_recalibration(
                row,
                model_provider_runtime_readiness=model_provider_runtime_readiness,
            )


def _apply_core_coding_loop_recalibration(
    row: dict[str, Any],
    *,
    core_coding_loop: dict[str, Any],
) -> None:
    previous = int(row["scores"]["octopus"])
    certified_floor = int(row.get("octopus_certified_score_floor") or 0)
    requirements = {
        "core_coding_loop_readiness_complete": (
            core_coding_loop.get("ready") is True
            and core_coding_loop.get("verdict") == "pass"
            and float(core_coding_loop.get("score") or 0.0) >= 1.0
        ),
        "core_coding_loop_canary_ready": (
            core_coding_loop.get("canary_ready") is True
            and isinstance(core_coding_loop.get("canary"), dict)
            and core_coding_loop["canary"].get("ready") is True
            and float(core_coding_loop["canary"].get("score") or 0.0) >= 1.0
        ),
        "evidence_checklist_complete": (
            float(row.get("octopus_evidence_readiness") or 0.0) >= 1.0
            and int(row.get("octopus_missing_evidence_count") or 0) == 0
        ),
        "certified_floor_97": certified_floor >= 97,
    }
    passed = all(requirements.values())
    target = max(previous, 97) if passed else previous
    if target <= previous:
        row["octopus_recalibration_applied"] = False
        row["octopus_recalibration"] = {
            "schema": "octopus.scorecard_recalibration.v1",
            "dimension_id": row["id"],
            "applied": False,
            "previous_score": previous,
            "score": previous,
            "requirements": requirements,
        }
        return

    row["scores"]["octopus"] = target
    row["leader"] = max(row["scores"], key=lambda key: row["scores"][key])
    row["octopus_gap_to_target"] = max(
        0,
        int(row["octopus_gap_to_target"]) - (target - previous),
    )
    row["evidence_adjusted_scores"]["octopus"] = max(
        int(row["evidence_adjusted_scores"]["octopus"]),
        target,
    )
    row["octopus_evidence_adjusted_score"] = row["evidence_adjusted_scores"]["octopus"]
    row["octopus_evidence_adjusted_gap_to_target"] = max(
        0,
        int(row["octopus_evidence_adjusted_gap_to_target"]) - (target - previous),
    )
    row["octopus_score_source"] = "verified_core_coding_loop_recalibration"
    row["octopus_evidence_adjusted_score_source"] = (
        "verified_core_coding_loop_recalibration"
    )
    row["octopus_certification_adjustment_available"] = False
    row["octopus_recalibration_applied"] = True
    row["octopus_recalibration"] = {
        "schema": "octopus.scorecard_recalibration.v1",
        "dimension_id": row["id"],
        "applied": True,
        "previous_score": previous,
        "score": target,
        "source": "core_coding_loop_readiness",
        "requirements": requirements,
    }


def _apply_browser_desktop_recalibration(
    row: dict[str, Any],
    *,
    browser_desktop_quality: dict[str, Any],
) -> None:
    previous = int(row["scores"]["octopus"])
    certified_floor = int(row.get("octopus_certified_score_floor") or 0)
    quality_gate = (
        browser_desktop_quality.get("repair_recipe_quality_gate")
        if isinstance(browser_desktop_quality.get("repair_recipe_quality_gate"), dict)
        else {}
    )
    capability_canary = (
        browser_desktop_quality.get("capability_canary")
        if isinstance(browser_desktop_quality.get("capability_canary"), dict)
        else {}
    )
    capability_rows = {
        str(item.get("id") or ""): item
        for item in capability_canary.get("capabilities", [])
        if isinstance(item, dict)
    }
    runtime_readiness = (
        browser_desktop_quality.get("runtime_readiness")
        if isinstance(browser_desktop_quality.get("runtime_readiness"), dict)
        else {}
    )
    runtime_score = float(runtime_readiness.get("score") or 0.0)
    runtime_ready = runtime_readiness.get("ready") is True
    runtime_blockers = int(runtime_readiness.get("blocker_count") or 0)
    runtime_warnings = int(runtime_readiness.get("warn_count") or 0)
    runtime_contract = (
        browser_desktop_quality.get("runtime_contract")
        if isinstance(browser_desktop_quality.get("runtime_contract"), dict)
        else {}
    )
    runtime_contract_ready = (
        runtime_contract.get("schema")
        == "octopus.browser_desktop_runtime_contract.v1"
        and runtime_contract.get("ready") is True
        and float(runtime_contract.get("score") or 0.0) >= 1.0
        and int(runtime_contract.get("missing_count") or 0) == 0
    )
    productization = (
        browser_desktop_quality.get("productization_readiness")
        if isinstance(browser_desktop_quality.get("productization_readiness"), dict)
        else {}
    )
    productization_probe = (
        productization.get("probe")
        if isinstance(productization.get("probe"), dict)
        else {}
    )
    cold_start = (
        browser_desktop_quality.get("cold_start_readiness")
        if isinstance(browser_desktop_quality.get("cold_start_readiness"), dict)
        else {}
    )
    cold_start_probe = (
        cold_start.get("probe")
        if isinstance(cold_start.get("probe"), dict)
        else {}
    )
    requirements = {
        "browser_desktop_static_quality_complete": (
            browser_desktop_quality.get("static_ready") is True
            and float(browser_desktop_quality.get("static_score") or 0.0) >= 1.0
        ),
        "browser_desktop_runtime_contract_ready": runtime_contract_ready,
        "browser_desktop_runtime_ready": (
            runtime_ready
            and runtime_score >= 1.0
            and runtime_blockers == 0
            and runtime_warnings == 0
        ),
        "browser_desktop_productization_ready": (
            productization.get("schema")
            == "octopus.browser_desktop_productization_readiness.v1"
            and productization.get("ready") is True
            and productization.get("verdict") == "pass"
            and float(productization.get("score") or 0.0) >= 1.0
        ),
        "chrome_relay_and_desktop_policy_probe_ready": (
            productization_probe.get("ok") is True
            and productization_probe.get("manifest_ready") is True
            and productization_probe.get("relay_loop_ready") is True
            and productization_probe.get("chrome_control_plane_ready") is True
            and productization_probe.get("computer_policy_endpoint_ready") is True
            and isinstance(productization_probe.get("policy_probe"), dict)
            and productization_probe["policy_probe"].get("ok") is True
        ),
        "deterministic_repair_gate_ready": (
            quality_gate.get("schema")
            == "octopus.browser_desktop_repair_recipe_quality_gate.v1"
            and quality_gate.get("ready") is True
            and float(quality_gate.get("score") or 0.0) >= 1.0
            and not quality_gate.get("blockers")
        ),
        "browser_desktop_capability_canary_ready": (
            capability_canary.get("schema")
            == "octopus.browser_desktop_capability_canary.v1"
            and capability_canary.get("ready") is True
            and float(capability_canary.get("effective_score") or 0.0) >= 1.0
            and int(capability_canary.get("runtime_verified_count") or 0) >= 6
            and int(capability_canary.get("control_plane_verified_count") or 0) >= 1
            and not capability_canary.get("blockers")
        ),
        "desktop_execute_replay_ready": (
            capability_rows.get("desktop_execute_replay_flow", {}).get("passed") is True
        ),
        "real_chrome_profile_ready": (
            capability_rows.get("real_chrome_profile_flow", {}).get("passed") is True
            and int(capability_canary.get("real_chrome_profile_verified_count") or 0) >= 1
        ),
        "browser_desktop_cold_start_ready": (
            cold_start.get("schema")
            == "octopus.browser_desktop_cold_start_readiness.v1"
            and cold_start.get("ready") is True
            and cold_start.get("verdict") == "pass"
            and float(cold_start.get("score") or 0.0) >= 1.0
            and cold_start_probe.get("ok") is True
        ),
        "evidence_checklist_complete": (
            float(row.get("octopus_evidence_readiness") or 0.0) >= 1.0
            and int(row.get("octopus_missing_evidence_count") or 0) == 0
        ),
        "certified_floor_94": certified_floor >= 94,
    }
    if not requirements["browser_desktop_runtime_ready"]:
        target = _browser_desktop_runtime_floor(
            previous,
            browser_desktop_quality=browser_desktop_quality,
            runtime_readiness=runtime_readiness,
        )
        if target < previous:
            row["scores"]["octopus"] = target
            row["leader"] = max(row["scores"], key=lambda key: row["scores"][key])
            target_score = int(row.get("target_score") or 90)
            row["octopus_gap_to_target"] = max(0, target_score - target)
            row["evidence_adjusted_scores"]["octopus"] = min(
                int(row["evidence_adjusted_scores"]["octopus"]),
                target,
            )
            row["octopus_evidence_adjusted_score"] = row["evidence_adjusted_scores"]["octopus"]
            row["octopus_evidence_adjusted_gap_to_target"] = max(
                0,
                target_score - int(row["octopus_evidence_adjusted_score"]),
            )
            row["octopus_score_source"] = "runtime_browser_desktop_readiness_floor"
            row["octopus_evidence_adjusted_score_source"] = (
                "runtime_browser_desktop_readiness_floor"
            )
            row["octopus_certification_adjustment_available"] = False
            row["octopus_recalibration_applied"] = True
            row["octopus_recalibration"] = {
                "schema": "octopus.scorecard_recalibration.v1",
                "dimension_id": row["id"],
                "applied": True,
                "direction": "down",
                "previous_score": previous,
                "score": target,
                "source": "browser_desktop_runtime_readiness",
                "requirements": requirements,
                "runtime": {
                    "score": runtime_score,
                    "ready": runtime_ready,
                    "blocker_count": runtime_blockers,
                    "warn_count": runtime_warnings,
                },
            }
            return
        if (
            target == previous
            and runtime_contract_ready
            and requirements["browser_desktop_cold_start_ready"]
        ):
            cold_target = max(previous, 93)
            row["scores"]["octopus"] = cold_target
            row["leader"] = max(row["scores"], key=lambda key: row["scores"][key])
            target_score = int(row.get("target_score") or 90)
            row["octopus_gap_to_target"] = max(0, target_score - cold_target)
            row["evidence_adjusted_scores"]["octopus"] = max(
                int(row["evidence_adjusted_scores"]["octopus"]),
                cold_target,
            )
            row["octopus_evidence_adjusted_score"] = row["evidence_adjusted_scores"]["octopus"]
            row["octopus_evidence_adjusted_gap_to_target"] = max(
                0,
                target_score - int(row["octopus_evidence_adjusted_score"]),
            )
            row["octopus_score_source"] = "browser_desktop_cold_start_readiness"
            row["octopus_evidence_adjusted_score_source"] = (
                "browser_desktop_cold_start_readiness"
            )
            row["octopus_certification_adjustment_available"] = False
            row["octopus_recalibration_applied"] = True
            row["octopus_recalibration"] = {
                "schema": "octopus.scorecard_recalibration.v1",
                "dimension_id": row["id"],
                "applied": True,
                "direction": "cold_start_up",
                "previous_score": previous,
                "score": cold_target,
                "source": "browser_desktop_cold_start_readiness",
                "requirements": requirements,
                "runtime": {
                    "score": runtime_score,
                    "ready": runtime_ready,
                    "blocker_count": runtime_blockers,
                    "warn_count": runtime_warnings,
                },
            }
            return
        if target == previous and runtime_contract_ready:
            row["octopus_score_source"] = "runtime_contract_cold_start_floor"
            row["octopus_evidence_adjusted_score_source"] = (
                "runtime_contract_cold_start_floor"
            )
            row["octopus_certification_adjustment_available"] = False
            row["octopus_recalibration_applied"] = False
            row["octopus_recalibration"] = {
                "schema": "octopus.scorecard_recalibration.v1",
                "dimension_id": row["id"],
                "applied": False,
                "direction": "held",
                "previous_score": previous,
                "score": previous,
                "source": "browser_desktop_runtime_contract",
                "requirements": requirements,
                "runtime": {
                    "score": runtime_score,
                    "ready": runtime_ready,
                    "blocker_count": runtime_blockers,
                    "warn_count": runtime_warnings,
                },
            }
            return

    core_requirements = {
        key: value
        for key, value in requirements.items()
        if key != "real_chrome_profile_ready"
    }
    passed = all(core_requirements.values())
    if passed:
        target = max(previous, 96 if requirements["real_chrome_profile_ready"] else 95)
    else:
        target = previous
    if target <= previous:
        row["octopus_recalibration_applied"] = False
        row["octopus_recalibration"] = {
            "schema": "octopus.scorecard_recalibration.v1",
            "dimension_id": row["id"],
            "applied": False,
            "previous_score": previous,
            "score": previous,
            "requirements": requirements,
        }
        return

    row["scores"]["octopus"] = target
    row["leader"] = max(row["scores"], key=lambda key: row["scores"][key])
    row["octopus_gap_to_target"] = max(
        0,
        int(row["octopus_gap_to_target"]) - (target - previous),
    )
    row["evidence_adjusted_scores"]["octopus"] = max(
        int(row["evidence_adjusted_scores"]["octopus"]),
        target,
    )
    row["octopus_evidence_adjusted_score"] = row["evidence_adjusted_scores"]["octopus"]
    row["octopus_evidence_adjusted_gap_to_target"] = max(
        0,
        int(row["octopus_evidence_adjusted_gap_to_target"]) - (target - previous),
    )
    row["octopus_score_source"] = "verified_browser_desktop_recalibration"
    row["octopus_evidence_adjusted_score_source"] = (
        "verified_browser_desktop_recalibration"
    )
    row["octopus_certification_adjustment_available"] = False
    row["octopus_recalibration_applied"] = True
    row["octopus_recalibration"] = {
        "schema": "octopus.scorecard_recalibration.v1",
        "dimension_id": row["id"],
        "applied": True,
        "previous_score": previous,
        "score": target,
        "source": "browser_desktop_quality",
        "requirements": requirements,
    }


def _browser_desktop_runtime_floor(
    previous: int,
    *,
    browser_desktop_quality: dict[str, Any],
    runtime_readiness: dict[str, Any],
) -> int:
    if browser_desktop_quality.get("static_ready") is not True:
        return min(previous, 78)
    runtime_contract = (
        browser_desktop_quality.get("runtime_contract")
        if isinstance(browser_desktop_quality.get("runtime_contract"), dict)
        else {}
    )
    contract_ready = (
        runtime_contract.get("schema")
        == "octopus.browser_desktop_runtime_contract.v1"
        and runtime_contract.get("ready") is True
        and float(runtime_contract.get("score") or 0.0) >= 1.0
        and int(runtime_contract.get("missing_count") or 0) == 0
    )
    if contract_ready:
        return previous
    runtime_score = float(runtime_readiness.get("score") or 0.0)
    blocker_count = int(runtime_readiness.get("blocker_count") or 0)
    warn_count = int(runtime_readiness.get("warn_count") or 0)
    if blocker_count:
        return min(previous, 80)
    if runtime_score >= 0.75 and warn_count <= 1:
        return min(previous, 88)
    if runtime_score >= 0.4:
        return min(previous, 84)
    return min(previous, 82)


def _apply_repo_context_recalibration(
    row: dict[str, Any],
    *,
    repo_context: dict[str, Any],
) -> None:
    previous = int(row["scores"]["octopus"])
    certified_floor = int(row.get("octopus_certified_score_floor") or 0)
    probe = repo_context.get("probe") if isinstance(repo_context.get("probe"), dict) else {}
    dirty_probe = (
        probe.get("dirty_worktree_probe")
        if isinstance(probe.get("dirty_worktree_probe"), dict)
        else {}
    )
    requirements = {
        "repo_context_readiness_complete": (
            repo_context.get("ready") is True
            and repo_context.get("verdict") == "pass"
            and float(repo_context.get("score") or 0.0) >= 1.0
            and bool(probe)
            and probe.get("english_identifier_retrieval") is True
            and probe.get("cjk_bigram_retrieval") is True
            and probe.get("source_sink_fidelity") is True
            and probe.get("dirty_worktree_awareness") is True
        ),
        "dirty_worktree_probe_ready": (
            dirty_probe.get("schema") == "octopus.repo_dirty_worktree_probe.v1"
            and dirty_probe.get("ok") is True
            and dirty_probe.get("protected_user_changes") is True
            and int(dirty_probe.get("staged_count") or 0) >= 1
            and int(dirty_probe.get("unstaged_count") or 0) >= 1
            and int(dirty_probe.get("untracked_count") or 0) >= 1
        ),
        "evidence_checklist_complete": (
            float(row.get("octopus_evidence_readiness") or 0.0) >= 1.0
            and int(row.get("octopus_missing_evidence_count") or 0) == 0
        ),
        "certified_floor_96": certified_floor >= 96,
    }
    passed = all(requirements.values())
    target = max(previous, 96) if passed else previous
    if target <= previous:
        row["octopus_recalibration_applied"] = False
        row["octopus_recalibration"] = {
            "schema": "octopus.scorecard_recalibration.v1",
            "dimension_id": row["id"],
            "applied": False,
            "previous_score": previous,
            "score": previous,
            "requirements": requirements,
        }
        return

    row["scores"]["octopus"] = target
    row["leader"] = max(row["scores"], key=lambda key: row["scores"][key])
    row["octopus_gap_to_target"] = max(
        0,
        int(row["octopus_gap_to_target"]) - (target - previous),
    )
    row["evidence_adjusted_scores"]["octopus"] = max(
        int(row["evidence_adjusted_scores"]["octopus"]),
        target,
    )
    row["octopus_evidence_adjusted_score"] = row["evidence_adjusted_scores"]["octopus"]
    row["octopus_evidence_adjusted_gap_to_target"] = max(
        0,
        int(row["octopus_evidence_adjusted_gap_to_target"]) - (target - previous),
    )
    row["octopus_score_source"] = "verified_repo_context_recalibration"
    row["octopus_evidence_adjusted_score_source"] = (
        "verified_repo_context_recalibration"
    )
    row["octopus_certification_adjustment_available"] = False
    row["octopus_recalibration_applied"] = True
    row["octopus_recalibration"] = {
        "schema": "octopus.scorecard_recalibration.v1",
        "dimension_id": row["id"],
        "applied": True,
        "previous_score": previous,
        "score": target,
        "source": "repo_context_readiness",
        "requirements": requirements,
    }


def _apply_ecosystem_maturity_recalibration(
    row: dict[str, Any],
    *,
    ecosystem_readiness: dict[str, Any],
    tool_threat_model: dict[str, Any],
) -> None:
    previous = int(row["scores"]["octopus"])
    certified_floor = int(row.get("octopus_certified_score_floor") or 0)
    ecosystem_probe = (
        ecosystem_readiness.get("probe")
        if isinstance(ecosystem_readiness.get("probe"), dict)
        else {}
    )
    probe_requirements = (
        ecosystem_probe.get("requirements")
        if isinstance(ecosystem_probe.get("requirements"), dict)
        else {}
    )
    requirements = {
        "ecosystem_readiness_complete": (
            float(ecosystem_readiness.get("score") or 0.0) >= 1.0
            and int(ecosystem_readiness.get("missing_count") or 0) == 0
        ),
        "plugin_compatibility_probe_ready": (
            ecosystem_readiness.get("probe_ready") is True
            and ecosystem_probe.get("ok") is True
            and probe_requirements.get("signed_plugin_provenance") is True
            and probe_requirements.get("explicit_permission_resolution") is True
            and probe_requirements.get("lifecycle_audit_pass") is True
            and probe_requirements.get("compatibility_summary_pass") is True
        ),
        "evidence_checklist_complete": (
            float(row.get("octopus_evidence_readiness") or 0.0) >= 1.0
            and int(row.get("octopus_missing_evidence_count") or 0) == 0
        ),
        "certified_floor_96": certified_floor >= 96,
        "tool_threat_model_ready": (
            tool_threat_model.get("ready") is True
            and tool_threat_model.get("verdict") == "pass"
        ),
    }
    passed = all(requirements.values())
    target = min(96, certified_floor) if passed else previous
    if target <= previous:
        row["octopus_recalibration_applied"] = False
        row["octopus_recalibration"] = {
            "schema": "octopus.scorecard_recalibration.v1",
            "dimension_id": row["id"],
            "applied": False,
            "previous_score": previous,
            "score": previous,
            "requirements": requirements,
        }
        return

    row["scores"]["octopus"] = target
    row["leader"] = max(row["scores"], key=lambda key: row["scores"][key])
    row["octopus_gap_to_target"] = max(0, int(row["octopus_gap_to_target"]) - (target - previous))
    row["evidence_adjusted_scores"]["octopus"] = max(
        int(row["evidence_adjusted_scores"]["octopus"]),
        target,
    )
    row["octopus_evidence_adjusted_score"] = row["evidence_adjusted_scores"]["octopus"]
    row["octopus_evidence_adjusted_gap_to_target"] = max(
        0,
        int(row["octopus_evidence_adjusted_gap_to_target"]) - (target - previous),
    )
    row["octopus_score_source"] = "verified_ecosystem_recalibration"
    row["octopus_evidence_adjusted_score_source"] = "verified_ecosystem_recalibration"
    row["octopus_certification_adjustment_available"] = False
    row["octopus_recalibration_applied"] = True
    row["octopus_recalibration"] = {
        "schema": "octopus.scorecard_recalibration.v1",
        "dimension_id": row["id"],
        "applied": True,
        "previous_score": previous,
        "score": target,
        "source": "ecosystem_readiness_and_lifecycle_evidence",
        "requirements": requirements,
    }


def _apply_extension_hooks_recalibration(
    row: dict[str, Any],
    *,
    extension_hooks: dict[str, Any],
    tool_threat_model: dict[str, Any],
) -> None:
    previous = int(row["scores"]["octopus"])
    certified_floor = int(row.get("octopus_certified_score_floor") or 0)
    probe = (
        extension_hooks.get("probe")
        if isinstance(extension_hooks.get("probe"), dict)
        else {}
    )
    requirements = {
        "extension_hooks_readiness_complete": (
            extension_hooks.get("ready") is True
            and extension_hooks.get("verdict") == "pass"
            and float(extension_hooks.get("score") or 0.0) >= 1.0
        ),
        "signed_provenance_probe_ready": (
            probe.get("ok") is True
            and probe.get("signed_provenance") is True
            and probe.get("permission_review") is True
            and probe.get("lifecycle_audit") is True
            and probe.get("compatibility_summary") is True
        ),
        "tool_threat_model_ready": (
            tool_threat_model.get("ready") is True
            and tool_threat_model.get("verdict") == "pass"
        ),
        "evidence_checklist_complete": (
            float(row.get("octopus_evidence_readiness") or 0.0) >= 1.0
            and int(row.get("octopus_missing_evidence_count") or 0) == 0
        ),
        "certified_floor_97": certified_floor >= 97,
    }
    passed = all(requirements.values())
    target = max(previous, 97) if passed else previous
    if target <= previous:
        row["octopus_recalibration_applied"] = False
        row["octopus_recalibration"] = {
            "schema": "octopus.scorecard_recalibration.v1",
            "dimension_id": row["id"],
            "applied": False,
            "previous_score": previous,
            "score": previous,
            "requirements": requirements,
        }
        return

    row["scores"]["octopus"] = target
    row["leader"] = max(row["scores"], key=lambda key: row["scores"][key])
    row["octopus_gap_to_target"] = max(
        0,
        int(row["octopus_gap_to_target"]) - (target - previous),
    )
    row["evidence_adjusted_scores"]["octopus"] = max(
        int(row["evidence_adjusted_scores"]["octopus"]),
        target,
    )
    row["octopus_evidence_adjusted_score"] = row["evidence_adjusted_scores"]["octopus"]
    row["octopus_evidence_adjusted_gap_to_target"] = max(
        0,
        int(row["octopus_evidence_adjusted_gap_to_target"]) - (target - previous),
    )
    row["octopus_score_source"] = "verified_extension_hooks_recalibration"
    row["octopus_evidence_adjusted_score_source"] = (
        "verified_extension_hooks_recalibration"
    )
    row["octopus_certification_adjustment_available"] = False
    row["octopus_recalibration_applied"] = True
    row["octopus_recalibration"] = {
        "schema": "octopus.scorecard_recalibration.v1",
        "dimension_id": row["id"],
        "applied": True,
        "previous_score": previous,
        "score": target,
        "source": "extension_hooks_readiness",
        "requirements": requirements,
    }


def _apply_product_experience_recalibration(
    row: dict[str, Any],
    *,
    product_experience: dict[str, Any],
) -> None:
    previous = int(row["scores"]["octopus"])
    certified_floor = int(row.get("octopus_certified_score_floor") or 0)
    probe = (
        product_experience.get("probe")
        if isinstance(product_experience.get("probe"), dict)
        else {}
    )
    requirements = {
        "product_experience_readiness_complete": (
            product_experience.get("ready") is True
            and product_experience.get("verdict") == "pass"
            and float(product_experience.get("score") or 0.0) >= 1.0
        ),
        "competitor_gap_probe_ready": (
            probe.get("ok") is True
            and probe.get("competitor_gap_routing") is True
            and probe.get("queue_text_mentions_best_competitor") is True
        ),
        "keyboard_audit_export_ready": probe.get("keyboard_audit_export") is True,
        "closed_loop_drilldown_ready": probe.get("closed_loop_drilldown") is True,
        "evidence_checklist_complete": (
            float(row.get("octopus_evidence_readiness") or 0.0) >= 1.0
            and int(row.get("octopus_missing_evidence_count") or 0) == 0
        ),
        "certified_floor_99": certified_floor >= 99,
    }
    passed = all(requirements.values())
    target = max(previous, 99) if passed else previous
    if target <= previous:
        row["octopus_recalibration_applied"] = False
        row["octopus_recalibration"] = {
            "schema": "octopus.scorecard_recalibration.v1",
            "dimension_id": row["id"],
            "applied": False,
            "previous_score": previous,
            "score": previous,
            "requirements": requirements,
        }
        return

    row["scores"]["octopus"] = target
    row["leader"] = max(row["scores"], key=lambda key: row["scores"][key])
    row["octopus_gap_to_target"] = max(
        0,
        int(row["octopus_gap_to_target"]) - (target - previous),
    )
    row["evidence_adjusted_scores"]["octopus"] = max(
        int(row["evidence_adjusted_scores"]["octopus"]),
        target,
    )
    row["octopus_evidence_adjusted_score"] = row["evidence_adjusted_scores"]["octopus"]
    row["octopus_evidence_adjusted_gap_to_target"] = max(
        0,
        int(row["octopus_evidence_adjusted_gap_to_target"]) - (target - previous),
    )
    row["octopus_score_source"] = "verified_product_experience_recalibration"
    row["octopus_evidence_adjusted_score_source"] = (
        "verified_product_experience_recalibration"
    )
    row["octopus_certification_adjustment_available"] = False
    row["octopus_recalibration_applied"] = True
    row["octopus_recalibration"] = {
        "schema": "octopus.scorecard_recalibration.v1",
        "dimension_id": row["id"],
        "applied": True,
        "previous_score": previous,
        "score": target,
        "source": "product_experience_readiness",
        "requirements": requirements,
    }


def _apply_permissions_sandbox_recalibration(
    row: dict[str, Any],
    *,
    permissions_sandbox: dict[str, Any],
) -> None:
    previous = int(row["scores"]["octopus"])
    certified_floor = int(row.get("octopus_certified_score_floor") or 0)
    probe = (
        permissions_sandbox.get("probe")
        if isinstance(permissions_sandbox.get("probe"), dict)
        else {}
    )
    backend = probe.get("backend") if isinstance(probe.get("backend"), dict) else {}
    hard_runtime = (
        probe.get("hard_runtime")
        if isinstance(probe.get("hard_runtime"), dict)
        else {}
    )
    sandbox = probe.get("sandbox") if isinstance(probe.get("sandbox"), dict) else {}
    policy_review = (
        probe.get("policy_review")
        if isinstance(probe.get("policy_review"), dict)
        else {}
    )
    checks = (
        permissions_sandbox.get("checks")
        if isinstance(permissions_sandbox.get("checks"), dict)
        else {}
    )
    requirements = {
        "permissions_sandbox_readiness_complete": (
            permissions_sandbox.get("ready") is True
            and permissions_sandbox.get("verdict") == "pass"
            and float(permissions_sandbox.get("score") or 0.0) >= 1.0
        ),
        "tool_threat_model_ready": checks.get("tool_threat_model_ready") is True,
        "process_backend_declared": checks.get("process_backend_declared") is True,
        "hard_backend_or_soft_fallback_declared": (
            checks.get("hard_backend_or_soft_fallback_declared") is True
            and (
                backend.get("hard") is True
                or backend.get("fallback") == "soft_isolation"
            )
        ),
        "hard_backend_runtime_probe_pass": (
            checks.get("hard_backend_runtime_probe_pass") is True
            and backend.get("hard") is True
            and hard_runtime.get("ok") is True
            and hard_runtime.get("hard") is True
            and hard_runtime.get("backend") == backend.get("backend")
            and hard_runtime.get("cwd_escape_blocked") is True
        ),
        "sandbox_soft_constraints_pass": (
            checks.get("sandbox_soft_constraints_pass") is True
            and sandbox.get("ok") is True
        ),
        "policy_review_signature_gate_pass": (
            checks.get("policy_review_signature_gate_pass") is True
            and policy_review.get("signature_ok") is True
            and policy_review.get("confirmation_required") is True
            and policy_review.get("install_ok") is True
        ),
        "evidence_checklist_complete": (
            float(row.get("octopus_evidence_readiness") or 0.0) >= 1.0
            and int(row.get("octopus_missing_evidence_count") or 0) == 0
        ),
        "certified_floor_96": certified_floor >= 96,
    }
    passed = all(requirements.values())
    target = max(previous, 96) if passed else previous
    row["octopus_recalibration_applied"] = passed
    row["octopus_recalibration"] = {
        "schema": "octopus.scorecard_recalibration.v1",
        "dimension_id": row["id"],
        "applied": passed,
        "previous_score": previous,
        "score": target,
        "source": "permissions_sandbox_readiness",
        "requirements": requirements,
    }
    if not passed:
        return

    row["scores"]["octopus"] = target
    row["leader"] = max(row["scores"], key=lambda key: row["scores"][key])
    row["evidence_adjusted_scores"]["octopus"] = max(
        int(row["evidence_adjusted_scores"]["octopus"]),
        target,
    )
    row["octopus_evidence_adjusted_score"] = row["evidence_adjusted_scores"]["octopus"]
    target_score = int(row.get("target_score") or 90)
    row["octopus_gap_to_target"] = max(0, target_score - target)
    row["octopus_evidence_adjusted_gap_to_target"] = max(
        0,
        target_score - int(row["octopus_evidence_adjusted_score"]),
    )
    row["octopus_score_source"] = "verified_permissions_sandbox_recalibration"
    row["octopus_evidence_adjusted_score_source"] = (
        "verified_permissions_sandbox_recalibration"
    )
    row["octopus_certification_adjustment_available"] = False


def _apply_record_replay_audit_recalibration(
    row: dict[str, Any],
    *,
    record_replay_audit: dict[str, Any],
) -> None:
    previous = int(row["scores"]["octopus"])
    certified_floor = int(row.get("octopus_certified_score_floor") or 0)
    probe = (
        record_replay_audit.get("probe")
        if isinstance(record_replay_audit.get("probe"), dict)
        else {}
    )
    trace_probe = (
        probe.get("trace_replay")
        if isinstance(probe.get("trace_replay"), dict)
        else {}
    )
    governance_probe = (
        probe.get("governance_audit")
        if isinstance(probe.get("governance_audit"), dict)
        else {}
    )
    native_probe = (
        probe.get("native_replay")
        if isinstance(probe.get("native_replay"), dict)
        else {}
    )
    requirements = {
        "record_replay_audit_readiness_complete": (
            record_replay_audit.get("ready") is True
            and record_replay_audit.get("verdict") == "pass"
            and float(record_replay_audit.get("score") or 0.0) >= 1.0
        ),
        "task_run_replay_gate_probe_ready": (
            trace_probe.get("ok") is True
            and trace_probe.get("gate", {}).get("passed") is True
            and trace_probe.get("evaluation", {}).get("passed") is True
        ),
        "governance_audit_chain_probe_ready": (
            governance_probe.get("ok") is True
            and governance_probe.get("integrity", {}).get("ok") is True
            and governance_probe.get("bundle", {}).get("integrity_ok") is True
            and governance_probe.get("tamper_detected") is True
        ),
        "native_replay_oracle_probe_ready": (
            native_probe.get("ok") is True
            and float(native_probe.get("heuristic_total") or 0.0) >= 0.6
            and float(native_probe.get("sandbox_total") or 0.0) >= 0.6
            and float(native_probe.get("turn_total") or 0.0) >= 0.6
        ),
        "evidence_checklist_complete": (
            float(row.get("octopus_evidence_readiness") or 0.0) >= 1.0
            and int(row.get("octopus_missing_evidence_count") or 0) == 0
        ),
        "certified_floor_96": certified_floor >= 96,
    }
    passed = all(requirements.values())
    target = max(previous, 96) if passed else previous
    if target <= previous:
        row["octopus_recalibration_applied"] = False
        row["octopus_recalibration"] = {
            "schema": "octopus.scorecard_recalibration.v1",
            "dimension_id": row["id"],
            "applied": False,
            "previous_score": previous,
            "score": previous,
            "requirements": requirements,
        }
        return

    row["scores"]["octopus"] = target
    row["leader"] = max(row["scores"], key=lambda key: row["scores"][key])
    row["octopus_gap_to_target"] = max(
        0,
        int(row["octopus_gap_to_target"]) - (target - previous),
    )
    row["evidence_adjusted_scores"]["octopus"] = max(
        int(row["evidence_adjusted_scores"]["octopus"]),
        target,
    )
    row["octopus_evidence_adjusted_score"] = row["evidence_adjusted_scores"]["octopus"]
    row["octopus_evidence_adjusted_gap_to_target"] = max(
        0,
        int(row["octopus_evidence_adjusted_gap_to_target"]) - (target - previous),
    )
    row["octopus_score_source"] = "verified_record_replay_audit_recalibration"
    row["octopus_evidence_adjusted_score_source"] = (
        "verified_record_replay_audit_recalibration"
    )
    row["octopus_certification_adjustment_available"] = False
    row["octopus_recalibration_applied"] = True
    row["octopus_recalibration"] = {
        "schema": "octopus.scorecard_recalibration.v1",
        "dimension_id": row["id"],
        "applied": True,
        "previous_score": previous,
        "score": target,
        "source": "record_replay_audit_readiness",
        "requirements": requirements,
    }


def _apply_multi_agent_orchestration_recalibration(
    row: dict[str, Any],
    *,
    multi_agent_orchestration: dict[str, Any],
    swarm_scale: dict[str, Any],
) -> None:
    previous = int(row["scores"]["octopus"])
    certified_floor = int(row.get("octopus_certified_score_floor") or 0)
    requirements = {
        "orchestration_readiness_complete": (
            multi_agent_orchestration.get("ready") is True
            and multi_agent_orchestration.get("verdict") == "pass"
            and float(multi_agent_orchestration.get("score") or 0.0) >= 1.0
        ),
        "evidence_checklist_complete": (
            float(row.get("octopus_evidence_readiness") or 0.0) >= 1.0
            and int(row.get("octopus_missing_evidence_count") or 0) == 0
        ),
        "certified_floor_96": certified_floor >= 96,
        "swarm_scale_ready": (
            swarm_scale.get("ready") is True
            and swarm_scale.get("verdict") == "pass"
            and float(swarm_scale.get("score") or 0.0) >= 1.0
            and isinstance(swarm_scale.get("probe"), dict)
            and swarm_scale["probe"].get("critical_path_speedup_passed") is True
            and swarm_scale["probe"].get("failure_isolation") is True
        ),
        "certified_floor_98": certified_floor >= 98,
        "batch_metrics_ready": (
            isinstance(swarm_scale.get("probe"), dict)
            and swarm_scale["probe"].get("batch_metrics_ready") is True
        ),
        "certified_floor_99": certified_floor >= 99,
    }
    orchestration_passed = all(
        requirements[key]
        for key in (
            "orchestration_readiness_complete",
            "evidence_checklist_complete",
            "certified_floor_96",
        )
    )
    swarm_passed = orchestration_passed and all(
        requirements[key]
        for key in ("swarm_scale_ready", "certified_floor_98")
    )
    target = previous
    if orchestration_passed:
        target = max(target, 97)
    if swarm_passed:
        target = max(target, 98)
    strict_lead_passed = swarm_passed and all(
        requirements[key]
        for key in ("batch_metrics_ready", "certified_floor_99")
    )
    if strict_lead_passed:
        target = max(target, 99)
    if target <= previous:
        row["octopus_recalibration_applied"] = False
        row["octopus_recalibration"] = {
            "schema": "octopus.scorecard_recalibration.v1",
            "dimension_id": row["id"],
            "applied": False,
            "previous_score": previous,
            "score": previous,
            "requirements": requirements,
        }
        return

    row["scores"]["octopus"] = target
    row["leader"] = max(row["scores"], key=lambda key: row["scores"][key])
    row["octopus_gap_to_target"] = max(
        0,
        int(row["octopus_gap_to_target"]) - (target - previous),
    )
    row["evidence_adjusted_scores"]["octopus"] = max(
        int(row["evidence_adjusted_scores"]["octopus"]),
        target,
    )
    row["octopus_evidence_adjusted_score"] = row["evidence_adjusted_scores"]["octopus"]
    row["octopus_evidence_adjusted_gap_to_target"] = max(
        0,
        int(row["octopus_evidence_adjusted_gap_to_target"]) - (target - previous),
    )
    if strict_lead_passed:
        source = "verified_swarm_strict_lead_recalibration"
        evidence_source = "swarm_scale_batch_metrics"
    elif swarm_passed:
        source = "verified_swarm_scale_recalibration"
        evidence_source = "swarm_scale_readiness"
    else:
        source = "verified_multi_agent_orchestration_recalibration"
        evidence_source = "multi_agent_orchestration_readiness"
    row["octopus_score_source"] = source
    row["octopus_evidence_adjusted_score_source"] = (
        source
    )
    row["octopus_certification_adjustment_available"] = False
    row["octopus_recalibration_applied"] = True
    row["octopus_recalibration"] = {
        "schema": "octopus.scorecard_recalibration.v1",
        "dimension_id": row["id"],
        "applied": True,
        "previous_score": previous,
        "score": target,
        "source": evidence_source,
        "requirements": requirements,
    }


def _apply_model_provider_runtime_recalibration(
    row: dict[str, Any],
    *,
    model_provider_runtime_readiness: dict[str, Any],
) -> None:
    previous = int(row["scores"]["octopus"])
    certified_floor = int(row.get("octopus_certified_score_floor") or 0)
    probe = (
        model_provider_runtime_readiness.get("probe")
        if isinstance(model_provider_runtime_readiness.get("probe"), dict)
        else {}
    )
    payload_shape = (
        probe.get("payload_shape")
        if isinstance(probe.get("payload_shape"), dict)
        else {}
    )
    failure_export = (
        probe.get("failure_export")
        if isinstance(probe.get("failure_export"), dict)
        else {}
    )
    coverage = (
        probe.get("builtin_profile_coverage")
        if isinstance(probe.get("builtin_profile_coverage"), dict)
        else {}
    )
    requirements = {
        "model_provider_runtime_readiness_complete": (
            model_provider_runtime_readiness.get("ready") is True
            and model_provider_runtime_readiness.get("verdict") == "pass"
            and float(model_provider_runtime_readiness.get("score") or 0.0) >= 1.0
        ),
        "provider_matrix_probe_ready": (
            probe.get("ok") is True
            and int(probe.get("matrix_score") or 0) == 100
            and probe.get("matrix_verdict") == "pass"
            and int(probe.get("matrix_row_count") or 0) >= 4
        ),
        "payload_shape_probe_ready": (
            payload_shape.get("ok") is True
            and all(
                bool(value)
                for value in (
                    payload_shape.get("requirements")
                    if isinstance(payload_shape.get("requirements"), dict)
                    else {}
                ).values()
            )
        ),
        "failure_export_probe_ready": (
            failure_export.get("ok") is True
            and failure_export.get("secrets_redacted") is True
            and failure_export.get("primary_repair_route") == "provider_thinking_protocol"
        ),
        "builtin_profile_coverage_ready": (
            coverage.get("ready") is True
            and not coverage.get("missing_profiles")
        ),
        "secrets_redacted": probe.get("secrets_redacted") is True,
        "evidence_checklist_complete": (
            float(row.get("octopus_evidence_readiness") or 0.0) >= 1.0
            and int(row.get("octopus_missing_evidence_count") or 0) == 0
        ),
        "certified_floor_96": certified_floor >= 96,
    }
    passed = all(requirements.values())
    target = max(previous, 96) if passed else previous
    if target <= previous:
        row["octopus_recalibration_applied"] = False
        row["octopus_recalibration"] = {
            "schema": "octopus.scorecard_recalibration.v1",
            "dimension_id": row["id"],
            "applied": False,
            "previous_score": previous,
            "score": previous,
            "requirements": requirements,
        }
        return

    row["scores"]["octopus"] = target
    row["leader"] = max(row["scores"], key=lambda key: row["scores"][key])
    row["octopus_gap_to_target"] = max(
        0,
        int(row["octopus_gap_to_target"]) - (target - previous),
    )
    row["evidence_adjusted_scores"]["octopus"] = max(
        int(row["evidence_adjusted_scores"]["octopus"]),
        target,
    )
    row["octopus_evidence_adjusted_score"] = row["evidence_adjusted_scores"]["octopus"]
    row["octopus_evidence_adjusted_gap_to_target"] = max(
        0,
        int(row["octopus_evidence_adjusted_gap_to_target"]) - (target - previous),
    )
    row["octopus_score_source"] = "verified_model_provider_runtime_recalibration"
    row["octopus_evidence_adjusted_score_source"] = (
        "verified_model_provider_runtime_recalibration"
    )
    row["octopus_certification_adjustment_available"] = False
    row["octopus_recalibration_applied"] = True
    row["octopus_recalibration"] = {
        "schema": "octopus.scorecard_recalibration.v1",
        "dimension_id": row["id"],
        "applied": True,
        "previous_score": previous,
        "score": target,
        "source": "model_provider_runtime_readiness",
        "requirements": requirements,
    }


def _evidence_readiness(evidence: list[dict[str, Any]]) -> float:
    if not evidence:
        return 0.0
    scores = [float(item.get("score") or 0.0) for item in evidence]
    return round(sum(scores) / len(scores), 3)


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


def _best_non_octopus_score(scores: dict[str, int]) -> int:
    return max(
        int(score)
        for competitor, score in scores.items()
        if competitor != "octopus"
    )


def _competitor_gap_rows(
    dimensions: list[dict[str, Any]],
    radar: dict[str, Any],
) -> list[dict[str, Any]]:
    by_id = {str(row.get("id") or ""): row for row in dimensions}
    rows: list[dict[str, Any]] = []
    for edge in radar.get("octopus_true_gap_edges") or []:
        if not isinstance(edge, dict):
            continue
        row = by_id.get(str(edge.get("id") or ""))
        if row is None:
            continue
        enriched = dict(row)
        enriched["octopus_competitor_gap"] = abs(int(edge.get("gap") or 0))
        enriched["octopus_best_competitors"] = list(
            edge.get("best_competitors") or [],
        )
        enriched["octopus_best_competitor_score"] = edge.get(
            "best_competitor_score",
        )
        rows.append(enriched)
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("octopus_competitor_gap") or 0),
            int(row.get("weight") or 0),
        ),
        reverse=True,
    )


def _competitor_tie_rows(
    dimensions: list[dict[str, Any]],
    radar: dict[str, Any],
) -> list[dict[str, Any]]:
    by_id = {str(row.get("id") or ""): row for row in dimensions}
    rows: list[dict[str, Any]] = []
    for edge in radar.get("octopus_true_tie_edges") or []:
        if not isinstance(edge, dict):
            continue
        row = by_id.get(str(edge.get("id") or ""))
        if row is None:
            continue
        enriched = dict(row)
        enriched["octopus_competitor_gap"] = 0
        enriched["octopus_strict_lead_gap"] = int(edge.get("strict_lead_gap") or 1)
        enriched["octopus_best_competitors"] = list(
            edge.get("best_competitors") or [],
        )
        enriched["octopus_best_competitor_score"] = edge.get(
            "best_competitor_score",
        )
        rows.append(enriched)
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("weight") or 0),
            str(row.get("id") or ""),
        ),
        reverse=True,
    )


def _radar_report(dimensions: list[dict[str, Any]]) -> dict[str, Any]:
    axes = [
        {
            "id": row["id"],
            "title": row["title"],
            "weight": row["weight"],
        }
        for row in dimensions
    ]
    edges = [_octopus_vs_codex_edge(row) for row in dimensions]
    true_edges = [_octopus_vs_best_competitor_edge(row) for row in dimensions]
    advantage_edges = [
        edge
        for edge in edges
        if edge["octopus"] >= max(edge["competitor_scores"].values())
    ]
    gap_edges = [
        edge
        for edge in edges
        if edge["relation"] == "behind"
    ]
    true_advantage_edges = [
        edge
        for edge in true_edges
        if edge["relation"] in {"ahead", "tied"}
    ]
    true_strict_advantage_edges = [
        edge
        for edge in true_edges
        if edge["relation"] == "ahead"
    ]
    true_tie_edges = [
        edge
        for edge in true_edges
        if edge["relation"] == "tied"
    ]
    true_gap_edges = [
        edge
        for edge in true_edges
        if edge["relation"] == "behind"
    ]
    return {
        "schema": "octopus.agent_scorecard_radar.v1",
        "axis_count": len(axes),
        "axes": axes,
        "series": _radar_series(dimensions, "scores"),
        "evidence_adjusted_series": _radar_series(
            dimensions,
            "evidence_adjusted_scores",
        ),
        "octopus_vs_codex_edges": edges,
        "octopus_advantage_edges": advantage_edges,
        "octopus_gap_edges": gap_edges,
        "octopus_advantage_count": len(advantage_edges),
        "octopus_gap_count": len(gap_edges),
        "octopus_vs_best_edges": true_edges,
        "octopus_true_advantage_edges": true_advantage_edges,
        "octopus_true_strict_advantage_edges": true_strict_advantage_edges,
        "octopus_true_tie_edges": true_tie_edges,
        "octopus_true_gap_edges": true_gap_edges,
        "octopus_true_advantage_count": len(true_advantage_edges),
        "octopus_true_strict_advantage_count": len(true_strict_advantage_edges),
        "octopus_true_tie_count": len(true_tie_edges),
        "octopus_true_gap_count": len(true_gap_edges),
        "mermaid": _radar_mermaid(dimensions, "scores"),
        "evidence_adjusted_mermaid": _radar_mermaid(
            dimensions,
            "evidence_adjusted_scores",
        ),
    }


def _radar_series(
    dimensions: list[dict[str, Any]],
    score_field: str,
) -> dict[str, list[int]]:
    return {
        competitor: [
            int(row[score_field][competitor])
            for row in dimensions
        ]
        for competitor in COMPETITORS
    }


def _octopus_vs_codex_edge(row: dict[str, Any]) -> dict[str, Any]:
    scores = row["scores"]
    octopus = int(scores["octopus"])
    codex = int(scores["codex"])
    delta = octopus - codex
    relation = "ahead" if delta > 0 else "behind" if delta < 0 else "tied"
    competitor_scores = {
        competitor: int(scores[competitor])
        for competitor in COMPETITORS
    }
    return {
        "id": row["id"],
        "title": row["title"],
        "weight": row["weight"],
        "octopus": octopus,
        "codex": codex,
        "gap": delta,
        "relation": relation,
        "leader": row.get("leader"),
        "competitor_scores": competitor_scores,
    }


def _octopus_vs_best_competitor_edge(row: dict[str, Any]) -> dict[str, Any]:
    scores = row["scores"]
    octopus = int(scores["octopus"])
    competitors = {
        competitor: int(score)
        for competitor, score in scores.items()
        if competitor != "octopus"
    }
    best_score = max(competitors.values())
    best_competitors = [
        competitor
        for competitor, score in competitors.items()
        if score == best_score
    ]
    delta = octopus - best_score
    relation = "ahead" if delta > 0 else "behind" if delta < 0 else "tied"
    return {
        "id": row["id"],
        "title": row["title"],
        "weight": row["weight"],
        "octopus": octopus,
        "best_competitor_score": best_score,
        "best_competitors": best_competitors,
        "gap": delta,
        "strict_lead_gap": max(0, best_score + 1 - octopus),
        "relation": relation,
        "leader": row.get("leader"),
        "competitor_scores": {
            competitor: int(scores[competitor])
            for competitor in COMPETITORS
        },
    }


def _radar_mermaid(
    dimensions: list[dict[str, Any]],
    score_field: str,
) -> str:
    axis = ", ".join(
        (
            f'{_mermaid_id(row["id"])}'
            f'["{_mermaid_label(row["title"])}"]'
        )
        for row in dimensions
    )
    lines = [
        "radar-beta",
        f"  axis {axis}",
    ]
    for competitor in COMPETITORS:
        values = ", ".join(
            str(int(row[score_field][competitor]))
            for row in dimensions
        )
        lines.append(
            f'  curve {_mermaid_id(competitor)}'
            f'["{_mermaid_label(COMPETITOR_LABELS[competitor])}"]'
            f"{{{values}}}"
        )
    lines.extend(["  max 100", "  min 0"])
    return "\n".join(lines)


def _mermaid_id(value: Any) -> str:
    safe = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "").strip()).strip("_")
    if not safe:
        return "item"
    if safe[0].isdigit():
        return f"item_{safe}"
    return safe


def _mermaid_label(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def _provider_runtime_summary() -> dict[str, Any]:
    try:
        from runtime.sensing.model_router.provider_compat_matrix import (
            build_provider_compatibility_matrix,
            compute_provider_profile_coverage,
        )

        report = build_provider_compatibility_matrix()
        payload = report.to_dict()
        profile_coverage = compute_provider_profile_coverage(
            required_profiles=list(DOMESTIC_PROVIDER_PROFILES),
        ).to_dict()
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "octopus.agent_scorecard_provider_runtime.v1",
            "available": False,
            "score": 0,
            "verdict": "review",
            "error": _safe_error(exc),
            "builtin_domestic_profiles": list(DOMESTIC_PROVIDER_PROFILES),
            "builtin_profile_coverage": {
                "schema": "octopus.provider_profile_coverage.v1",
                "ready": False,
                "required_profiles": list(DOMESTIC_PROVIDER_PROFILES),
                "covered_profiles": [],
                "missing_profiles": list(DOMESTIC_PROVIDER_PROFILES),
                "coverage_rate": 0.0,
                "checks": {},
            },
            "configured_profiles": [],
            "configured_profile_gaps": list(DOMESTIC_PROVIDER_PROFILES),
            "rows": [],
        }

    rows = [
        _provider_runtime_row(row)
        for row in payload.get("rows", [])
        if isinstance(row, dict)
    ]
    configured_profiles = sorted({
        str(row.get("profile") or "")
        for row in rows
        if row.get("profile")
    })
    coverage_gaps = [
        profile
        for profile in DOMESTIC_PROVIDER_PROFILES
        if profile not in configured_profiles
    ]
    return {
        "schema": "octopus.agent_scorecard_provider_runtime.v1",
        "available": True,
        "matrix_schema": payload.get("schema"),
        "source": payload.get("source"),
        "live_mode": payload.get("live_mode"),
        "score": payload.get("score"),
        "verdict": payload.get("verdict"),
        "row_count": len(rows),
        "pass_rows": sum(1 for row in rows if row.get("verdict") == "pass"),
        "review_rows": sum(1 for row in rows if row.get("verdict") == "review"),
        "fail_rows": sum(1 for row in rows if row.get("verdict") == "fail"),
        "builtin_domestic_profiles": list(DOMESTIC_PROVIDER_PROFILES),
        "builtin_profile_coverage": profile_coverage,
        "configured_profiles": configured_profiles,
        "configured_profile_gaps": coverage_gaps,
        "coverage_gaps": coverage_gaps,
        "rows": rows,
        "policy": {
            "schema": "octopus.provider_runtime_policy.v1",
            "secrets_redacted": True,
            "offline_matrix_required": True,
            "live_canary_recommended_for_certification": True,
            "configured_profile_gaps_are_not_builtin_support_gaps": True,
        },
    }


def _provider_runtime_row(row: dict[str, Any]) -> dict[str, Any]:
    findings = [
        finding
        for finding in row.get("findings", [])
        if isinstance(finding, dict)
    ]
    return {
        "id": row.get("id"),
        "provider": row.get("provider"),
        "profile": row.get("profile"),
        "display_name": row.get("display_name"),
        "models": list(row.get("models") or []),
        "score": row.get("score"),
        "verdict": row.get("verdict"),
        "has_api_key": bool(row.get("has_api_key")),
        "capabilities": (
            dict(row.get("capabilities"))
            if isinstance(row.get("capabilities"), dict)
            else {}
        ),
        "finding_codes": [
            str(finding.get("code"))
            for finding in findings
            if finding.get("code")
        ],
        "findings": [
            {
                "severity": finding.get("severity"),
                "code": finding.get("code"),
                "message": finding.get("message"),
            }
            for finding in findings
        ],
    }


def _safe_error(exc: Exception) -> str:
    detail = f"{type(exc).__name__}: {exc}"
    return detail[:240]


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


def _next_focus(
    target_gap_rows: list[dict[str, Any]],
    competitor_gap_rows: list[dict[str, Any]] | None = None,
    competitor_tie_rows: list[dict[str, Any]] | None = None,
) -> list[str]:
    ordered = sorted(
        target_gap_rows,
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
            _append_unique(out, str(actions[0]))
        if len(out) >= 5:
            break
    if len(out) < 5:
        for row in competitor_gap_rows or []:
            actions = row.get("octopus_next_actions")
            if isinstance(actions, list) and actions:
                _append_unique(out, str(actions[0]))
            else:
                _append_unique(
                    out,
                    f"Close best-competitor gap for {row.get('title') or row.get('id')}.",
                )
            if len(out) >= 5:
                break
    if len(out) < 5:
        for row in competitor_tie_rows or []:
            actions = row.get("octopus_next_actions")
            if isinstance(actions, list) and actions:
                _append_unique(out, str(actions[0]))
            else:
                _append_unique(
                    out,
                    "Create a strict-lead proof for "
                    f"{row.get('title') or row.get('id')}.",
                )
            if len(out) >= 5:
                break
    return out


def _append_unique(out: list[str], value: str) -> None:
    clean = str(value or "").strip()
    if clean and clean not in out:
        out.append(clean)


__all__ = [
    "COMPETITORS",
    "DOMESTIC_PROVIDER_PROFILES",
    "DIMENSIONS",
    "ScoreDimension",
    "compute_agent_competitor_scorecard",
]

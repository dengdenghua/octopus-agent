from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from runtime.platform.process.paths import project_root as default_project_root

GapArea = Literal["codex_parity", "octopus_advantage"]


@dataclass(frozen=True)
class GapCapability:
    id: str
    area: GapArea
    title: str
    why: str
    target_score: float
    implementation_paths: tuple[str, ...]
    test_paths: tuple[str, ...]
    next_actions: tuple[str, ...]


CAPABILITIES: tuple[GapCapability, ...] = (
    GapCapability(
        id="code_execution_loop",
        area="codex_parity",
        title="Code execution loop",
        why="Codex is strongest when it can plan, edit, run commands, and verify.",
        target_score=0.95,
        implementation_paths=(
            "runtime/core/cerebrum/react_loop.py",
            "runtime/execution/tool_engine/executor.py",
            "runtime/sensing/gateway/realtime_turn_outcome.py",
            "runtime/safety/evolution/auto_verifier.py",
            "runtime/safety/evolution/auto_verifier_metrics.py",
            "runtime/safety/evolution/repair_route_quality.py",
            "runtime/memory/runtime_state/process_timeline.py",
            "frontend/src/components/workspace/agent-operator-panel.tsx",
        ),
        test_paths=(
            "tests/test_react_loop.py",
            "tests/test_tool_protocol.py",
            "tests/test_post_write_diagnostics.py",
            "tests/test_realtime_cerebrum.py",
            "tests/test_auto_verifier_metrics.py",
            "tests/test_repair_route_quality.py",
            "tests/test_agent_trace_router.py",
            "frontend/src/components/workspace/agent-operator-panel.test.tsx",
        ),
        next_actions=(
            "Add automatic repair-route promotion evidence for repeated verifier drift.",
        ),
    ),
    GapCapability(
        id="approvals_sandbox_security",
        area="codex_parity",
        title="Approvals, sandboxing, and command safety",
        why="Codex has mature approval and sandbox surfaces; parity requires enforceable local policy.",
        target_score=0.9,
        implementation_paths=(
            "runtime/safety/approval/approval_gate.py",
            "runtime/safety/sandboxing/sandbox.py",
            "runtime/safety/hooks/tool_edge_hooks.py",
            "runtime/safety/audit/trust_gateway.py",
            "runtime/safety/evolution/policy_review_rules.py",
        ),
        test_paths=(
            "tests/test_approval_gate.py",
            "tests/test_tool_edge_hooks.py",
            "tests/test_tool_bridge_scope.py",
            "tests/test_scope.py",
            "tests/test_policy_review_rules.py",
        ),
        next_actions=(
            "Add threat-model regression cases for every high-risk tool class.",
            "Surface signed policy-review rule drafts in the operator panel.",
        ),
    ),
    GapCapability(
        id="browser_computer_use",
        area="codex_parity",
        title="Browser and computer-use operations",
        why="Codex can inspect and operate browsers and desktop apps; Octopus needs stable local equivalents.",
        target_score=0.85,
        implementation_paths=(
            "runtime/platform/ui/browser_router.py",
            "runtime/platform/runtime_policy/browser_sessions.py",
            "runtime/sensing/gateway/computer_router.py",
            "runtime/sensing/gateway/android_router.py",
            "runtime/execution/suckers/browser_act_skills.py",
            "runtime/safety/replay/browser_desktop_replay.py",
            "runtime/safety/replay/browser_pixel_assertions.py",
            "frontend/src/components/workspace/embedded-browser/browser-panel.tsx",
        ),
        test_paths=(
            "tests/test_computer_router.py",
            "tests/test_browser_sessions.py",
            "tests/test_browser_artifact.py",
            "tests/test_browser_pixel_assertions.py",
        ),
        next_actions=(
            "Turn repeated browser replay failures into deterministic repair recipes.",
        ),
    ),
    GapCapability(
        id="subagents_parallel_work",
        area="codex_parity",
        title="Subagents and parallel work",
        why="Codex subagents reduce context pollution; Octopus needs delegated work with durable traces.",
        target_score=0.9,
        implementation_paths=(
            "runtime/sensing/gateway/subagents_router.py",
            "runtime/sensing/gateway/parallel_agents_router.py",
            "runtime/execution/subagents/bridge.py",
            "runtime/memory/learning/subagent_review.py",
            "runtime/safety/evolution/subagent_fitness.py",
            "runtime/safety/evolution/subagent_routing.py",
            "runtime/safety/evolution/subagent_team_promotion.py",
            "runtime/execution/parallel_agents/orchestrator.py",
            "runtime/sensing/gateway/deep_research_router.py",
            "runtime/sensing/gateway/team_tasks_router.py",
            "frontend/src/components/workspace/deep-research-panel.tsx",
            "frontend/src/components/workspace/parallel-tasks-panel.tsx",
        ),
        test_paths=(
            "tests/test_call_agent_vote.py",
            "tests/test_delegation_enhancements.py",
            "tests/test_subagent_memory.py",
            "tests/test_deep_research_router.py",
            "tests/test_team_tasks_router.py",
            "tests/test_organization.py",
            "tests/test_organizations_router.py",
            "frontend/src/components/workspace/deep-research-panel.test.tsx",
        ),
        next_actions=(
            "Attach replay-gated promotion records to team-task process timelines.",
            "Add UI affordances for subagent-derived topology proposals.",
        ),
    ),
    GapCapability(
        id="skills_plugins_hooks",
        area="codex_parity",
        title="Skills, plugins, and lifecycle hooks",
        why="Codex extensibility comes from reusable skills, plugins, MCP, and hooks.",
        target_score=0.9,
        implementation_paths=(
            "runtime/sensing/gateway/plugins_router.py",
            "runtime/sensing/gateway/plugin_hub_router.py",
            "runtime/platform/plugins/codex_discovery.py",
            "runtime/safety/evolution/policy_review_rules.py",
            "runtime/safety/hooks/runner.py",
            "runtime/safety/hooks/registry.py",
        ),
        test_paths=(
            "tests/test_meta_skill.py",
            "tests/test_apps_router.py",
            "tests/test_codex_plugin_smoke.py",
            "tests/test_tool_edge_hooks.py",
        ),
        next_actions=(
            "Extend plugin permission review to signed provenance verification.",
            "Add UI install controls for plugin permission rule drafts.",
        ),
    ),
    GapCapability(
        id="governance_audit",
        area="codex_parity",
        title="Governance and auditability",
        why="Codex enterprise has analytics and compliance exports; Octopus needs local, operator-grade audit trails.",
        target_score=0.95,
        implementation_paths=(
            "runtime/memory/learning/promotion_applier.py",
            "runtime/safety/evolution/fitness.py",
            "runtime/safety/evolution/governance_audit.py",
            "runtime/safety/audit/audit_chain.py",
            "runtime/sensing/gateway/agent_trace_router.py",
            "frontend/src/components/workspace/agent-operator-panel.tsx",
        ),
        test_paths=(
            "tests/test_promotion_applier.py",
            "tests/test_evolution_modules.py",
            "tests/test_agent_trace_router.py",
            "tests/test_realtime_cerebrum.py",
            "frontend/src/components/workspace/agent-operator-panel.test.tsx",
        ),
        next_actions=(
            "Add scheduled governance audit export rotation.",
            "Surface per-agent governance trend charts in the operator panel.",
        ),
    ),
    GapCapability(
        id="record_replay_gate",
        area="codex_parity",
        title="Record, replay, and replay gates",
        why="Codex has Record & Replay for workflows; Octopus adds promotion gates and task-run replay.",
        target_score=0.95,
        implementation_paths=(
            "runtime/memory/diagnostics/trace_store.py",
            "runtime/sensing/gateway/agent_trace_router.py",
        ),
        test_paths=(
            "tests/test_agent_trace_store.py",
            "tests/test_agent_trace_router.py",
        ),
        next_actions=(
            "Turn successful replay cases into reusable skills automatically.",
            "Add large-corpus replay latency budgets to CI.",
        ),
    ),
    GapCapability(
        id="long_term_learning",
        area="octopus_advantage",
        title="Long-term learning memory",
        why="This is where Octopus can beat task-local agents: experience survives and changes future behavior.",
        target_score=0.95,
        implementation_paths=(
            "runtime/memory/learning/experience_ledger.py",
            "runtime/memory/learning/review_queue.py",
            "runtime/memory/learning/subagent_review.py",
            "runtime/memory/learning/turn_scoring.py",
            "runtime/memory/hemolymph/composer.py",
        ),
        test_paths=(
            "tests/test_agent_trace_router.py",
            "tests/test_promotion_applier.py",
            "tests/test_gap_filling.py",
        ),
        next_actions=(
            "Expose replay citation coverage in the memory operator panel.",
            "Surface memory quality scores in code-mode context traces.",
        ),
    ),
    GapCapability(
        id="self_evolution_canary",
        area="octopus_advantage",
        title="Self-evolution with canary and rollback",
        why="Octopus can differentiate by continuously improving itself with guarded promotion.",
        target_score=0.95,
        implementation_paths=(
            "runtime/safety/evolution/auto_trigger.py",
            "runtime/safety/evolution/canary.py",
            "runtime/safety/evolution/proposal_ledger.py",
            "runtime/safety/evolution/rollback_coordinator.py",
        ),
        test_paths=(
            "tests/test_evolution_modules.py",
            "tests/test_evolution_integration.py",
            "tests/test_evolution_failure_injection.py",
        ),
        next_actions=(
            "Require replay-gate evidence before auto-promoting self-evolution changes.",
            "Track fitness deltas by proposal family, not only globally.",
        ),
    ),
    GapCapability(
        id="agent_organization_os",
        area="octopus_advantage",
        title="Agent organization operating system",
        why="The largest moat is durable roles, teams, rooms, governance, and memory across agents.",
        target_score=0.9,
        implementation_paths=(
            "runtime/sensing/gateway/team_rooms_router.py",
            "runtime/sensing/gateway/team_tasks_router.py",
            "runtime/sensing/gateway/agent_world_router.py",
            "runtime/safety/organization/promotion_lift.py",
            "frontend/src/components/workspace/swarm/agent-workbench-panel.tsx",
        ),
        test_paths=(
            "tests/test_team_rooms_router.py",
            "tests/test_team_rooms_router_security.py",
            "tests/test_agents_router.py",
            "tests/test_organization.py",
            "tests/test_organizations_router.py",
            "frontend/src/components/workspace/agent-workbench-panel.test.tsx",
        ),
        next_actions=(
            "Give every team task a replay-backed process timeline.",
            "Use topology promotion lift to auto-rank future team proposals.",
        ),
    ),
)


def compute_codex_gap_report(
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    items = [_score_capability(base, capability) for capability in CAPABILITIES]
    parity = [item for item in items if item["area"] == "codex_parity"]
    advantage = [item for item in items if item["area"] == "octopus_advantage"]
    parity_score = _average(item["score"] for item in parity)
    advantage_score = _average(item["score"] for item in advantage)
    combined = round(parity_score * 0.55 + advantage_score * 0.45, 3)
    top_gaps = sorted(
        [
            item for item in items
            if item["score"] < item["target_score"]
        ],
        key=lambda item: (
            round(item["target_score"] - item["score"], 3),
            item["id"],
        ),
        reverse=True,
    )[:5]
    return {
        "schema": "octopus.codex_gap_report.v1",
        "parity_score": parity_score,
        "advantage_score": advantage_score,
        "combined_score": combined,
        "verdict": _verdict(combined, parity_score, advantage_score),
        "capabilities": items,
        "top_gaps": top_gaps,
        "next_focus": _next_focus(top_gaps),
    }


def _score_capability(base: Path, capability: GapCapability) -> dict[str, Any]:
    implementation = _path_status(base, capability.implementation_paths)
    tests = _path_status(base, capability.test_paths)
    implementation_score = implementation["present"] / max(1, implementation["total"])
    test_score = tests["present"] / max(1, tests["total"])
    score = round(implementation_score * 0.62 + test_score * 0.38, 3)
    if score >= capability.target_score:
        status = "strong"
    elif score >= capability.target_score * 0.8:
        status = "watch"
    else:
        status = "gap"
    return {
        "id": capability.id,
        "area": capability.area,
        "title": capability.title,
        "why": capability.why,
        "score": score,
        "target_score": capability.target_score,
        "status": status,
        "evidence": {
            "implementation": implementation,
            "tests": tests,
        },
        "next_actions": list(capability.next_actions),
    }


def _path_status(base: Path, paths: tuple[str, ...]) -> dict[str, Any]:
    rows = [
        {"path": path, "exists": (base / path).exists()}
        for path in paths
    ]
    present = sum(1 for row in rows if row["exists"])
    return {
        "present": present,
        "total": len(rows),
        "missing": [row["path"] for row in rows if not row["exists"]],
        "paths": rows,
    }


def _average(values: Any) -> float:
    rows = [float(value) for value in values]
    if not rows:
        return 0.0
    return round(sum(rows) / len(rows), 3)


def _verdict(combined: float, parity: float, advantage: float) -> str:
    if combined >= 0.95 and parity >= 0.9 and advantage >= 0.95:
        return "differentiated"
    if combined >= 0.88 and parity >= 0.85:
        return "competitive"
    if combined >= 0.75:
        return "catching_up"
    return "behind"


def _next_focus(top_gaps: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for item in top_gaps[:3]:
        actions = item.get("next_actions")
        if isinstance(actions, list) and actions:
            out.append(str(actions[0]))
    return out


__all__ = ["CAPABILITIES", "GapCapability", "compute_codex_gap_report"]

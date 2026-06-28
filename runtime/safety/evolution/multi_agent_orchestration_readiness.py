from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root

_SCHEMA = "octopus.multi_agent_orchestration_readiness.v1"


@dataclass(frozen=True)
class OrchestrationCapability:
    id: str
    title: str
    path: str
    required_terms: tuple[str, ...]
    weight: int = 1


CAPABILITIES: tuple[OrchestrationCapability, ...] = (
    OrchestrationCapability(
        id="streaming_subagents",
        title="Streaming subagent dispatch",
        path="runtime/sensing/gateway/subagents_router.py",
        required_terms=("dispatch_subagent_stream", "subagent_spawned", "sub_tool_start"),
        weight=2,
    ),
    OrchestrationCapability(
        id="parallel_dispatch",
        title="Parallel agent dispatch",
        path="runtime/sensing/gateway/parallel_agents_router.py",
        required_terms=("parallel", "dispatch", "batch"),
        weight=2,
    ),
    OrchestrationCapability(
        id="worktree_isolation",
        title="Worktree-isolated parallel code work",
        path="runtime/execution/subagents/worktree_loop.py",
        required_terms=("run_worktree_loop", "worktree_scope", "ThreadPoolExecutor"),
        weight=3,
    ),
    OrchestrationCapability(
        id="fitness_routing",
        title="Subagent fitness routing",
        path="runtime/safety/evolution/subagent_fitness.py",
        required_terms=("octopus.subagent_fitness.v1", "promoted_count", "retire_candidate"),
        weight=2,
    ),
    OrchestrationCapability(
        id="team_topology_promotion",
        title="Team topology promotion",
        path="runtime/safety/evolution/subagent_team_promotion.py",
        required_terms=("subagent_team_promotion", "subagent_fitness", "swap_agent"),
        weight=2,
    ),
    OrchestrationCapability(
        id="promotion_lift",
        title="Historical promotion lift ranking",
        path="runtime/safety/organization/promotion_lift.py",
        required_terms=("topology_promotion_lift", "success_rate_delta", "quality_score_delta"),
        weight=2,
    ),
)


def compute_multi_agent_orchestration_readiness(
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    capabilities = [_capability_status(base, capability) for capability in CAPABILITIES]
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
        "next_actions": _next_actions(missing),
    }


def _capability_status(base: Path, capability: OrchestrationCapability) -> dict[str, Any]:
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
    "OrchestrationCapability",
    "compute_multi_agent_orchestration_readiness",
]

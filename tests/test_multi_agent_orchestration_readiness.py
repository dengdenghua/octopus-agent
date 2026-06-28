from __future__ import annotations

from pathlib import Path

from runtime.safety.evolution.multi_agent_orchestration_readiness import (
    compute_multi_agent_orchestration_readiness,
)


def test_multi_agent_orchestration_readiness_passes_current_repo() -> None:
    report = compute_multi_agent_orchestration_readiness()

    assert report["schema"] == "octopus.multi_agent_orchestration_readiness.v1"
    assert report["ready"] is True
    assert report["verdict"] == "pass"
    assert report["score"] == 1.0
    assert report["passed"] == report["total"]
    assert report["next_actions"] == []
    assert {
        item["id"] for item in report["capabilities"]
        if item["passed"]
    } == {
        "streaming_subagents",
        "parallel_dispatch",
        "worktree_isolation",
        "fitness_routing",
        "team_topology_promotion",
        "promotion_lift",
    }


def test_multi_agent_orchestration_readiness_reports_missing_evidence(
    tmp_path: Path,
) -> None:
    report = compute_multi_agent_orchestration_readiness(root=tmp_path)

    assert report["ready"] is False
    assert report["verdict"] == "review"
    assert report["score"] == 0.0
    assert report["missing_count"] == report["total"]
    assert report["next_actions"][0].startswith(
        "Add runtime/sensing/gateway/subagents_router.py"
    )

from __future__ import annotations

from pathlib import Path

from runtime.safety.evolution.core_coding_loop_readiness import (
    compute_core_coding_loop_readiness,
)


def test_core_coding_loop_readiness_passes_current_repo() -> None:
    report = compute_core_coding_loop_readiness()

    assert report["schema"] == "octopus.core_coding_loop_readiness.v1"
    assert report["ready"] is True
    assert report["verdict"] == "pass"
    assert report["score"] == 1.0
    assert report["passed"] == report["total"]
    assert report["canary_ready"] is True
    assert report["canary"]["ready"] is True
    assert report["canary"]["probe"]["execution"]["telemetry_ok"] is True
    assert report["next_actions"] == []
    assert {
        item["id"] for item in report["capabilities"] if item["passed"]
    } == {
        "auto_verifier_ranking",
        "auto_verifier_execution",
        "post_write_regression_matrix",
        "failed_turn_repair_metadata",
        "repair_route_governance",
    }


def test_core_coding_loop_readiness_reports_missing_evidence(
    tmp_path: Path,
) -> None:
    report = compute_core_coding_loop_readiness(root=tmp_path)

    assert report["ready"] is False
    assert report["verdict"] == "review"
    assert report["score"] < 1.0
    assert report["missing_count"] == report["total"]
    assert report["next_actions"][0].startswith(
        "Add runtime/safety/evolution/auto_verifier_metrics.py"
    )

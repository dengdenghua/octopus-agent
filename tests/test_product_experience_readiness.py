from __future__ import annotations

from pathlib import Path

from runtime.safety.evolution.product_experience_readiness import (
    compute_product_experience_readiness,
    run_product_experience_probe,
)


def test_product_experience_probe_routes_true_competitor_gap() -> None:
    report = run_product_experience_probe()

    assert report["schema"] == "octopus.product_experience_probe.v1"
    assert report["ok"] is True
    assert report["competitor_gap_routing"] is True
    assert report["queue_text_mentions_best_competitor"] is True
    assert report["keyboard_audit_export"] is True
    assert report["closed_loop_drilldown"] is True
    assert report["row_count"] == 1
    assert report["first_gap"] == 8
    assert "Best-competitor gap" in report["text_preview"]


def test_product_experience_readiness_passes_current_repo() -> None:
    report = compute_product_experience_readiness()

    assert report["schema"] == "octopus.product_experience_readiness.v1"
    assert report["ready"] is True
    assert report["verdict"] == "pass"
    assert report["score"] == 1.0
    assert report["passed"] == report["total"]
    assert report["next_actions"] == []
    assert {
        item["id"] for item in report["capabilities"] if item["passed"]
    } >= {
        "true_competitor_gap_scorecard",
        "best_competitor_gap_queue",
        "operator_gap_visibility",
        "frontend_scorecard_contract",
        "operator_gap_regression_test",
        "audit_export_and_keyboard_flow",
        "audit_export_keyboard_regression_test",
        "source_review_queue_drilldown",
        "closed_loop_advantage_regression_test",
        "backend_gap_queue_test",
        "competitor_gap_routing_probe",
        "queue_text_probe",
        "keyboard_audit_export_probe",
        "closed_loop_drilldown_probe",
    }


def test_product_experience_readiness_reports_missing_evidence(
    tmp_path: Path,
) -> None:
    report = compute_product_experience_readiness(root=tmp_path, include_probe=False)

    assert report["ready"] is False
    assert report["verdict"] == "review"
    assert report["score"] == 0.0
    assert report["missing_count"] == report["total"]
    assert report["next_actions"][0].startswith(
        "Add runtime/safety/evolution/agent_competitor_scorecard.py"
    )

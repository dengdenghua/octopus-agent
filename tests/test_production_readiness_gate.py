from __future__ import annotations

from scripts import production_readiness_gate as gate


def test_production_readiness_gate_passes_current_release_signals() -> None:
    result = gate.run_gate()

    assert result.failures == []
    assert result.scorecard_score >= gate.MIN_SCORE
    assert result.automation_score >= gate.MIN_SCORE
    assert "octopus.repo_context_quality.v1" in result.quality_summary
    assert "octopus.product_experience_quality.v1" in result.quality_summary


def test_production_readiness_gate_reports_not_ready_quality(monkeypatch) -> None:
    monkeypatch.setattr(
        gate,
        "compute_repo_context_quality",
        lambda: {
            "schema": "octopus.repo_context_quality.v1",
            "ready": False,
            "score": 0.4,
            "passed": 2,
            "total": 5,
            "next_actions": ["Restore repo context evidence."],
        },
    )

    result = gate.run_gate()

    assert any(
        "octopus.repo_context_quality.v1 is not ready" in failure
        for failure in result.failures
    )
    assert any(
        "octopus.repo_context_quality.v1 score is 0.4" in failure
        for failure in result.failures
    )


def test_production_readiness_gate_blocks_scorecard_regression(monkeypatch) -> None:
    real_scorecard = gate.compute_agent_competitor_scorecard

    def degraded_scorecard(*, target_score: int):
        report = real_scorecard(target_score=target_score)
        report["overall"]["octopus"] = target_score - 1
        report["evidence_adjusted_overall"]["octopus"] = target_score - 1
        report["octopus_below_target"] = [{
            "id": "product_experience",
            "title": "IDE and product experience",
        }]
        return report

    monkeypatch.setattr(
        gate,
        "compute_agent_competitor_scorecard",
        degraded_scorecard,
    )

    result = gate.run_gate(min_score=95)

    assert any("agent scorecard octopus overall is 94" in item for item in result.failures)
    assert any("product_experience" in item for item in result.failures)


def test_production_readiness_gate_allows_scored_automation_focus_without_evidence_gap(
    monkeypatch,
) -> None:
    real_automation = gate.compute_automation_radar

    def automation_with_scored_focus(*, target_score: int):
        report = real_automation(target_score=target_score)
        report["octopus_gaps"] = [{
            "id": "desktop_preview_execute",
            "evidence_ready": True,
        }]
        return report

    monkeypatch.setattr(gate, "compute_automation_radar", automation_with_scored_focus)

    result = gate.run_gate(min_score=95)

    assert not any("automation radar evidence gaps" in item for item in result.failures)


def test_production_readiness_gate_blocks_automation_evidence_gap(monkeypatch) -> None:
    real_automation = gate.compute_automation_radar

    def automation_with_missing_evidence(*, target_score: int):
        report = real_automation(target_score=target_score)
        report["octopus_gaps"] = [{
            "id": "desktop_preview_execute",
            "evidence_ready": False,
        }]
        return report

    monkeypatch.setattr(gate, "compute_automation_radar", automation_with_missing_evidence)

    result = gate.run_gate(min_score=95)

    assert any(
        "automation radar evidence gaps: desktop_preview_execute" in item
        for item in result.failures
    )

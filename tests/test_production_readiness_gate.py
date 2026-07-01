from __future__ import annotations

from pathlib import Path

import pytest

from runtime.memory.learning.review_queue import ReviewQueue
from scripts import production_readiness_gate as gate

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def review_queue_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "review_queue.json"


def test_production_readiness_gate_passes_current_release_signals(
    review_queue_path: Path,
) -> None:
    result = gate.run_gate(review_queue_path=review_queue_path)

    assert result.failures == []
    assert result.scorecard_score == 97
    assert result.scorecard_evidence_adjusted_score >= gate.MIN_SCORE
    assert result.automation_score >= gate.MIN_SCORE
    assert "octopus.repo_context_quality.v1" in result.quality_summary
    assert "octopus.product_experience_quality.v1" in result.quality_summary
    assert "octopus.agent_loop_quality.v1" in result.quality_summary
    assert "octopus.digital_employee_quality.v1" in result.quality_summary


def test_production_readiness_gate_reports_not_ready_quality(
    monkeypatch,
    review_queue_path: Path,
) -> None:
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

    result = gate.run_gate(review_queue_path=review_queue_path)

    assert any(
        "octopus.repo_context_quality.v1 is not ready" in failure
        for failure in result.failures
    )
    assert any(
        "octopus.repo_context_quality.v1 score is 0.4" in failure
        for failure in result.failures
    )


def test_production_readiness_gate_blocks_scorecard_regression(
    monkeypatch,
    review_queue_path: Path,
) -> None:
    real_scorecard = gate.compute_agent_competitor_scorecard

    def degraded_scorecard(*, target_score: int):
        report = real_scorecard(target_score=target_score)
        report["evidence_adjusted_overall"]["octopus"] = target_score - 1
        return report

    monkeypatch.setattr(
        gate,
        "compute_agent_competitor_scorecard",
        degraded_scorecard,
    )

    result = gate.run_gate(min_score=95, review_queue_path=review_queue_path)

    assert any(
        "agent scorecard octopus evidence-adjusted overall is 94" in item
        for item in result.failures
    )


def test_production_readiness_gate_blocks_e2e_certification_regression(
    monkeypatch,
    review_queue_path: Path,
) -> None:
    monkeypatch.setattr(
        gate,
        "compute_e2e_surpass_certification",
        lambda **_: {
            "schema": "octopus.e2e_surpass_certification.v1",
            "ready": False,
            "checks": [
                {
                    "id": "scorecard_all_dimensions_surpassed",
                    "passed": False,
                },
            ],
            "next_actions": ["Restore all-dimension surpass evidence."],
        },
    )

    result = gate.run_gate(min_score=95, review_queue_path=review_queue_path)

    assert any(
        "e2e surpass certification is not ready" in item
        for item in result.failures
    )
    assert any(
        "e2e surpass certification checks: scorecard_all_dimensions_surpassed"
        in item
        for item in result.failures
    )


def test_production_readiness_gate_allows_scored_automation_focus_without_evidence_gap(
    monkeypatch,
    review_queue_path: Path,
) -> None:
    real_automation = gate.compute_automation_radar

    def automation_with_scored_focus(
        *,
        target_score: int,
        review_queue_path: str | Path | None = None,
    ):
        report = real_automation(
            target_score=target_score,
            review_queue_path=review_queue_path,
        )
        report["octopus_gaps"] = [{
            "id": "desktop_preview_execute",
            "evidence_ready": True,
        }]
        return report

    monkeypatch.setattr(gate, "compute_automation_radar", automation_with_scored_focus)

    result = gate.run_gate(min_score=95, review_queue_path=review_queue_path)

    assert not any("automation radar evidence gaps" in item for item in result.failures)


def test_production_readiness_gate_blocks_automation_evidence_gap(
    monkeypatch,
    review_queue_path: Path,
) -> None:
    real_automation = gate.compute_automation_radar

    def automation_with_missing_evidence(
        *,
        target_score: int,
        review_queue_path: str | Path | None = None,
    ):
        report = real_automation(
            target_score=target_score,
            review_queue_path=review_queue_path,
        )
        report["octopus_gaps"] = [{
            "id": "desktop_preview_execute",
            "evidence_ready": False,
        }]
        return report

    monkeypatch.setattr(gate, "compute_automation_radar", automation_with_missing_evidence)

    result = gate.run_gate(min_score=95, review_queue_path=review_queue_path)

    assert any(
        "automation radar evidence gaps: desktop_preview_execute" in item
        for item in result.failures
    )


def test_production_readiness_gate_blocks_stale_browser_replay_artifacts(
    monkeypatch,
    review_queue_path: Path,
) -> None:
    real_quality = gate.compute_browser_desktop_quality

    def browser_quality_with_stale_artifacts(
        *,
        review_queue_path: str | Path | None = None,
    ):
        report = real_quality(review_queue_path=review_queue_path)
        report["replay_trends"] = {
            **report["replay_trends"],
            "stale_source_artifact_count": 2,
            "repair_recipe_summary": {
                **report["replay_trends"]["repair_recipe_summary"],
                "total_pending_cases": 2,
                "recipe_count": 1,
            },
        }
        return report

    monkeypatch.setattr(
        gate,
        "compute_browser_desktop_quality",
        browser_quality_with_stale_artifacts,
    )

    result = gate.run_gate(min_score=95, review_queue_path=review_queue_path)

    assert any(
        "browser/desktop replay stale source artifacts: 2" in item
        for item in result.failures
    )
    assert any(
        "browser/desktop replay repair recipes pending: cases=2, recipes=1" in item
        for item in result.failures
    )


def test_production_readiness_gate_uses_explicit_review_queue_path(
    review_queue_path: Path,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "missing" / "screenshot.png"
    ReviewQueue(review_queue_path).upsert_item(
        source="browser_pixel_replay_gate",
        source_kind="browser_desktop_replay",
        candidate_kind="browser_pixel_replay_gate_case",
        priority="P0",
        target_bucket="browser_desktop_replay",
        title="Review stale browser pixel replay gate",
        text="Browser pixel replay gate needs review.",
        metadata={"artifact": {"local_path": str(artifact)}},
    )

    result = gate.run_gate(review_queue_path=review_queue_path)

    assert any(
        "browser/desktop replay stale source artifacts: 1" in item
        for item in result.failures
    )


def test_ci_runs_production_readiness_gate_with_isolated_state() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8",
    )

    assert "Production readiness gate" in workflow
    assert "run: make production-readiness" in workflow
    assert "runner.temp" in workflow
    assert "OCTOPUS_READINESS_DATA_DIR" in workflow


def test_makefile_exposes_isolated_production_readiness_target() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "production-readiness:" in makefile
    assert "OCTOPUS_READINESS_HOME" in makefile
    assert "OCTOPUS_READINESS_DATA_DIR" in makefile
    assert "OCTOPUS_READINESS_REVIEW_QUEUE" in makefile
    assert ".venv/bin/python" in makefile
    assert "$${PYTHON:-" in makefile
    assert "-m scripts.production_readiness_gate" in makefile
    assert "--review-queue-path" in makefile


def test_pr_template_points_reviewers_to_make_production_readiness() -> None:
    template = (REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(
        encoding="utf-8",
    )

    assert "make production-readiness" in template
    assert "python scripts/production_readiness_gate.py" not in template

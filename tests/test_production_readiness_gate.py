from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.memory.learning.review_queue import ReviewQueue
from scripts import production_readiness_gate as gate

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def review_queue_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "review_queue.json"


def test_production_readiness_gate_requires_behavioral_release_evidence(
    monkeypatch,
    tmp_path: Path,
    review_queue_path: Path,
) -> None:
    monkeypatch.setenv(
        "OCTOPUS_BEHAVIORAL_INFRASTRUCTURE_STATUS",
        str(tmp_path / "no-infrastructure-receipt.json"),
    )
    monkeypatch.setenv(
        "OCTOPUS_BEHAVIORAL_EVAL_BUNDLE",
        str(tmp_path / "no-behavioral-bundle.json"),
    )
    result = gate.run_gate(review_queue_path=review_queue_path)

    assert result.failures
    assert any("e2e surpass certification is not ready" in item for item in result.failures)
    assert result.scorecard_score == 98
    assert result.scorecard_evidence_adjusted_score >= gate.MIN_SCORE
    assert result.automation_score >= gate.MIN_SCORE
    assert result.e2e_ready is False
    assert result.e2e_verdict == "needs_behavioral_evidence"
    assert result.e2e_summary["scorecard_octopus"] == 98
    assert result.e2e_summary["scorecard_best_external"] == 97
    assert result.e2e_summary["automation_octopus"] == 96
    assert result.e2e_summary["coverage_ready"] == 7
    assert result.e2e_summary["coverage_total"] == 7
    assert result.e2e_summary["coverage_gap_domains"] == 0
    assert result.e2e_summary["quality_ready"] == result.e2e_summary["quality_total"]
    assert result.e2e_coverage["summary"]["ready_domains"] == 7
    assert result.e2e_coverage["summary"]["gap_domain_ids"] == []
    assert "behavioral:bundle_present" in result.e2e_failed_checks
    assert result.e2e_behavioral["verdict"] == "missing_behavioral_evidence"
    assert result.e2e_summary_text == (
        "e2e_scorecard=98, e2e_best_external=97, "
        "e2e_automation=96, e2e_coverage=7/7, e2e_quality=7/7, "
        "e2e_behavioral=missing"
    )
    assert "octopus.repo_context_quality.v1" in result.quality_summary
    assert "octopus.product_experience_quality.v1" in result.quality_summary
    assert "octopus.agent_loop_quality.v1" in result.quality_summary
    assert "octopus.digital_employee_quality.v1" in result.quality_summary


def test_production_readiness_gate_passes_verified_behavioral_evidence(
    monkeypatch,
    review_queue_path: Path,
) -> None:
    real_e2e = gate.compute_e2e_surpass_certification

    def verified_e2e(**kwargs):
        report = real_e2e(**kwargs)
        behavior = {
            **report["behavioral"],
            "ready": True,
            "verdict": "surpassed",
            "systems": {
                "octopus": {"aggregate_pass_pow_k": 1.0},
                "codex": {"aggregate_pass_pow_k": 0.96},
            },
            "checks": [],
            "next_actions": [],
        }
        report["behavioral"] = behavior
        report["summary"] = {
            **report["summary"],
            "behavioral_ready": True,
            "behavioral_octopus_pass_pow_k": 1.0,
            "behavioral_codex_pass_pow_k": 0.96,
        }
        report["checks"] = [
            {**row, "passed": True} if str(row.get("id") or "").startswith("behavioral:") else row
            for row in report["checks"]
        ]
        report["ready"] = True
        report["verdict"] = "surpassed"
        report["next_actions"] = []
        return report

    monkeypatch.setattr(gate, "compute_e2e_surpass_certification", verified_e2e)

    result = gate.run_gate(review_queue_path=review_queue_path)

    assert result.failures == []
    assert not any("behavioral surpass evidence is not ready" in row for row in result.failures)
    assert result.e2e_ready is True
    assert result.e2e_verdict == "surpassed"
    assert result.e2e_behavioral["ready"] is True
    assert result.e2e_summary_text.endswith("e2e_behavioral=ready")


def test_production_readiness_gate_forwards_behavioral_bundle_path(
    monkeypatch,
    review_queue_path: Path,
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "behavioral.json"
    captured: dict[str, object] = {}
    real_e2e = gate.compute_e2e_surpass_certification

    def capture_path(**kwargs):
        captured.update(kwargs)
        return real_e2e(**kwargs)

    monkeypatch.setattr(gate, "compute_e2e_surpass_certification", capture_path)

    gate.run_gate(
        review_queue_path=review_queue_path,
        behavioral_bundle_path=bundle_path,
    )

    assert captured["behavioral_bundle_path"] == bundle_path


def test_production_readiness_gate_prints_e2e_summary(
    monkeypatch,
    tmp_path: Path,
    capsys,
    review_queue_path: Path,
) -> None:
    monkeypatch.setenv(
        "OCTOPUS_BEHAVIORAL_INFRASTRUCTURE_STATUS",
        str(tmp_path / "no-infrastructure-receipt.json"),
    )
    monkeypatch.setenv(
        "OCTOPUS_BEHAVIORAL_EVAL_BUNDLE",
        str(tmp_path / "no-behavioral-bundle.json"),
    )
    code = gate.main(["--review-queue-path", str(review_queue_path)])

    captured = capsys.readouterr()

    assert code == 1
    assert "production readiness gate failed" in captured.err
    assert "behavioral:bundle_present" in captured.err


def test_production_readiness_gate_can_emit_json_summary(
    monkeypatch,
    tmp_path: Path,
    capsys,
    review_queue_path: Path,
) -> None:
    monkeypatch.setenv(
        "OCTOPUS_BEHAVIORAL_INFRASTRUCTURE_STATUS",
        str(tmp_path / "no-infrastructure-receipt.json"),
    )
    monkeypatch.setenv(
        "OCTOPUS_BEHAVIORAL_EVAL_BUNDLE",
        str(tmp_path / "no-behavioral-bundle.json"),
    )
    code = gate.main(
        [
            "--review-queue-path",
            str(review_queue_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert code == 1
    assert data["schema"] == "octopus.production_readiness_gate.v1"
    assert data["ready"] is False
    assert data["failures"]
    assert data["scorecard_score"] == 98
    assert data["automation_score"] == 96
    assert data["e2e"]["ready"] is False
    assert data["e2e"]["verdict"] == "needs_behavioral_evidence"
    assert data["e2e"]["summary"]["scorecard_best_external"] == 97
    assert data["e2e"]["summary"]["coverage_ready"] == 7
    assert data["e2e"]["coverage"]["summary"]["gap_domain_ids"] == []
    assert "behavioral:bundle_present" in data["e2e"]["failed_checks"]
    assert data["e2e"]["behavioral"]["verdict"] == "missing_behavioral_evidence"


def test_production_readiness_gate_can_write_json_output(
    monkeypatch,
    capsys,
    review_queue_path: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "OCTOPUS_BEHAVIORAL_INFRASTRUCTURE_STATUS",
        str(tmp_path / "no-infrastructure-receipt.json"),
    )
    monkeypatch.setenv(
        "OCTOPUS_BEHAVIORAL_EVAL_BUNDLE",
        str(tmp_path / "no-behavioral-bundle.json"),
    )
    output_path = tmp_path / "reports" / "readiness.json"

    code = gate.main(
        [
            "--review-queue-path",
            str(review_queue_path),
            "--json-output",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()
    data = json.loads(output_path.read_text(encoding="utf-8"))

    assert code == 1
    assert output_path.exists()
    assert "production readiness gate failed" in captured.err
    assert data["schema"] == "octopus.production_readiness_gate.v1"
    assert data["ready"] is False
    assert data["e2e"]["summary"]["coverage_ready"] == 7
    assert data["e2e"]["coverage"]["summary"]["total_domains"] == 7


def test_production_readiness_gate_json_reports_failures(
    capsys,
    monkeypatch,
    review_queue_path: Path,
) -> None:
    real_e2e = gate.compute_e2e_surpass_certification

    def drifted_e2e(**kwargs):
        report = real_e2e(**kwargs)
        report["summary"] = {
            **report["summary"],
            "scorecard_best_external": 1,
        }
        return report

    monkeypatch.setattr(gate, "compute_e2e_surpass_certification", drifted_e2e)

    code = gate.main(
        [
            "--review-queue-path",
            str(review_queue_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert code == 1
    assert data["ready"] is False
    assert any(
        "e2e summary mismatch: scorecard_best_external=1, expected 97" in item
        for item in data["failures"]
    )


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
        "octopus.repo_context_quality.v1 is not ready" in failure for failure in result.failures
    )
    assert any(
        "octopus.repo_context_quality.v1 score is 0.4" in failure for failure in result.failures
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

    assert any("e2e surpass certification is not ready" in item for item in result.failures)
    assert any(
        "e2e surpass certification checks: scorecard_all_dimensions_surpassed" in item
        for item in result.failures
    )


def test_production_readiness_gate_blocks_e2e_summary_drift(
    monkeypatch,
    review_queue_path: Path,
) -> None:
    real_e2e = gate.compute_e2e_surpass_certification

    def drifted_e2e(**kwargs):
        report = real_e2e(**kwargs)
        report["summary"] = {
            **report["summary"],
            "automation_octopus": 94,
        }
        return report

    monkeypatch.setattr(gate, "compute_e2e_surpass_certification", drifted_e2e)

    result = gate.run_gate(min_score=95, review_queue_path=review_queue_path)

    assert any(
        "e2e summary mismatch: automation_octopus=94, expected 96" in item
        for item in result.failures
    )


def test_production_readiness_gate_blocks_best_external_summary_drift(
    monkeypatch,
    review_queue_path: Path,
) -> None:
    real_e2e = gate.compute_e2e_surpass_certification

    def drifted_e2e(**kwargs):
        report = real_e2e(**kwargs)
        report["summary"] = {
            **report["summary"],
            "scorecard_best_external": 1,
        }
        return report

    monkeypatch.setattr(gate, "compute_e2e_surpass_certification", drifted_e2e)

    result = gate.run_gate(min_score=95, review_queue_path=review_queue_path)

    assert any(
        "e2e summary mismatch: scorecard_best_external=1, expected 97" in item
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
        report["octopus_gaps"] = [
            {
                "id": "desktop_preview_execute",
                "evidence_ready": True,
            }
        ]
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
        report["octopus_gaps"] = [
            {
                "id": "desktop_preview_execute",
                "evidence_ready": False,
            }
        ]
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
        "browser/desktop replay stale source artifacts: 2" in item for item in result.failures
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
        "browser/desktop replay stale source artifacts: 1" in item for item in result.failures
    )


def test_ci_runs_production_readiness_gate_with_isolated_state() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8",
    )

    assert "Production readiness gate" in workflow
    assert "run: make production-readiness" in workflow
    assert "runner.temp" in workflow
    assert "OCTOPUS_READINESS_DATA_DIR" in workflow
    assert "OCTOPUS_READINESS_REPORT" in workflow
    assert "Upload production readiness proof" in workflow
    assert "production-readiness-proof" in workflow
    assert "readiness_gate.json" in workflow
    assert "if-no-files-found: error" in workflow
    assert "Upload full-stack smoke proof" in workflow
    assert "full-stack-smoke-proof" in workflow
    assert "full_stack_smoke_proof.json" in workflow
    assert "Upload E2E release proof" in workflow
    assert "e2e-release-proof" in workflow
    assert "e2e_release_proof.json" in workflow


def test_makefile_exposes_isolated_production_readiness_target() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "production-readiness:" in makefile
    assert "OCTOPUS_READINESS_HOME" in makefile
    assert "OCTOPUS_READINESS_DATA_DIR" in makefile
    assert "OCTOPUS_READINESS_REVIEW_QUEUE" in makefile
    assert "OCTOPUS_READINESS_REPORT" in makefile
    assert ".venv/bin/python" in makefile
    assert "$${PYTHON:-" in makefile
    assert "-m scripts.production_readiness_gate" in makefile
    assert "--review-queue-path" in makefile
    assert "--json-output" in makefile


def test_verify_local_persists_production_readiness_report() -> None:
    script = (REPO_ROOT / "scripts" / "verify_local.sh").read_text(
        encoding="utf-8",
    )

    assert "VERIFY_READINESS_REPORT" in script
    assert "VERIFY_FULL_STACK_PROOF" in script
    assert "VERIFY_E2E_RELEASE_PROOF" in script
    assert "production_readiness_gate.json" in script
    assert "full_stack_smoke_proof.json" in script
    assert "e2e_release_proof.json" in script
    assert '--json-output "$VERIFY_READINESS_REPORT"' in script
    assert "readiness report: $VERIFY_READINESS_REPORT" in script
    assert "scripts/e2e_smoke_proof.py" in script
    assert "scripts/e2e_release_proof.py" in script
    assert "tests/test_e2e_smoke_proof.py" in script
    assert "tests/test_e2e_release_proof.py" in script
    assert "full-stack-desktop" in script
    assert "full-stack-mobile" in script
    assert "full-stack smoke proof: $VERIFY_FULL_STACK_PROOF" in script
    assert "e2e release proof: $VERIFY_E2E_RELEASE_PROOF" in script


def test_pr_template_points_reviewers_to_make_production_readiness() -> None:
    template = (REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(
        encoding="utf-8",
    )

    assert "make production-readiness" in template
    assert "python scripts/production_readiness_gate.py" not in template

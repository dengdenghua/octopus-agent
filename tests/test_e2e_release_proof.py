from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_e2e_release_proof_merges_readiness_and_full_stack(tmp_path: Path) -> None:
    readiness = tmp_path / "readiness.json"
    full_stack = tmp_path / "full_stack.json"
    output = tmp_path / "release.json"
    readiness.write_text(json.dumps(_readiness()), encoding="utf-8")
    full_stack.write_text(json.dumps(_full_stack()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/e2e_release_proof.py",
            "--readiness",
            str(readiness),
            "--full-stack",
            str(full_stack),
            "--output",
            str(output),
            "--required-suite",
            "full-stack-desktop",
            "--required-suite",
            "full-stack-mobile",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    data = json.loads(output.read_text(encoding="utf-8"))

    assert result.returncode == 0, result.stderr
    assert data["schema"] == "octopus.e2e_release_proof.v1"
    assert data["ready"] is True
    assert data["verdict"] == "release_ready"
    assert data["failed_checks"] == []
    assert data["summary"]["scorecard_score"] == 97
    assert data["summary"]["automation_score"] == 95
    assert data["summary"]["coverage_ready"] == 7
    assert data["summary"]["coverage_total"] == 7
    assert data["summary"]["coverage_gap_domains"] == 0
    assert data["summary"]["full_stack_suite_count"] == 2
    assert data["summary"]["full_stack_test_file_count"] == 5
    assert data["summary"]["required_suite_test_file_counts"] == {
        "full-stack-desktop": 4,
        "full-stack-mobile": 1,
    }


def test_e2e_release_proof_requires_all_named_full_stack_suites(
    tmp_path: Path,
) -> None:
    readiness = tmp_path / "readiness.json"
    full_stack = tmp_path / "full_stack.json"
    output = tmp_path / "release.json"
    readiness.write_text(json.dumps(_readiness()), encoding="utf-8")
    full_stack.write_text(
        json.dumps(_full_stack(suites=("full-stack-desktop",))),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/e2e_release_proof.py",
            "--readiness",
            str(readiness),
            "--full-stack",
            str(full_stack),
            "--output",
            str(output),
            "--required-suite",
            "full-stack-desktop",
            "--required-suite",
            "full-stack-mobile",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    data = json.loads(output.read_text(encoding="utf-8"))

    assert result.returncode == 1
    assert data["ready"] is False
    assert data["verdict"] == "needs_work"
    assert "full_stack_required_suites_present" in data["failed_checks"]
    assert data["summary"]["missing_suites"] == ["full-stack-mobile"]


def test_e2e_release_proof_rejects_weak_readiness_artifact(
    tmp_path: Path,
) -> None:
    readiness = tmp_path / "readiness.json"
    full_stack = tmp_path / "full_stack.json"
    output = tmp_path / "release.json"
    readiness.write_text(
        json.dumps(
            _readiness(
                schema="octopus.fake_readiness.v1",
                scorecard_score=94,
                automation_score=94,
                coverage_gap_domains=1,
            )
        ),
        encoding="utf-8",
    )
    full_stack.write_text(json.dumps(_full_stack()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/e2e_release_proof.py",
            "--readiness",
            str(readiness),
            "--full-stack",
            str(full_stack),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    data = json.loads(output.read_text(encoding="utf-8"))

    assert result.returncode == 1
    assert data["ready"] is False
    assert {
        "production_readiness_schema",
        "production_readiness_scores_clear_target",
        "production_readiness_coverage_has_no_gaps",
    } <= set(data["failed_checks"])


def test_e2e_release_proof_rejects_inconsistent_full_stack_counts(
    tmp_path: Path,
) -> None:
    readiness = tmp_path / "readiness.json"
    full_stack = tmp_path / "full_stack.json"
    output = tmp_path / "release.json"
    readiness.write_text(json.dumps(_readiness()), encoding="utf-8")
    full_stack.write_text(
        json.dumps(_full_stack(suite_count=5, passed_count=1)),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/e2e_release_proof.py",
            "--readiness",
            str(readiness),
            "--full-stack",
            str(full_stack),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    data = json.loads(output.read_text(encoding="utf-8"))

    assert result.returncode == 1
    assert data["ready"] is False
    assert "full_stack_suite_counts_consistent" in data["failed_checks"]


def test_e2e_release_proof_rejects_weak_required_suite_coverage(
    tmp_path: Path,
) -> None:
    readiness = tmp_path / "readiness.json"
    full_stack = tmp_path / "full_stack.json"
    output = tmp_path / "release.json"
    readiness.write_text(json.dumps(_readiness()), encoding="utf-8")
    full_stack.write_text(
        json.dumps(
            _full_stack(
                suite_test_matches={
                    "full-stack-desktop": ("full-stack-smoke.spec.ts",),
                    "full-stack-mobile": ("mobile-smoke.spec.ts",),
                },
            )
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/e2e_release_proof.py",
            "--readiness",
            str(readiness),
            "--full-stack",
            str(full_stack),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    data = json.loads(output.read_text(encoding="utf-8"))

    assert result.returncode == 1
    assert data["ready"] is False
    assert "full_stack_required_suites_have_test_coverage" in data["failed_checks"]
    assert data["summary"]["weak_suite_test_coverage"] == ["full-stack-desktop"]


def _readiness(
    *,
    schema: str = "octopus.production_readiness_gate.v1",
    scorecard_score: int = 97,
    automation_score: int = 95,
    coverage_gap_domains: int = 0,
) -> dict[str, object]:
    return {
        "schema": schema,
        "ready": True,
        "scorecard_score": scorecard_score,
        "automation_score": automation_score,
        "e2e": {
            "ready": True,
            "verdict": "surpassed",
            "summary": {
                "coverage_ready": 7,
                "coverage_total": 7,
                "coverage_gap_domains": coverage_gap_domains,
            },
        },
    }


def _full_stack(
    *,
    suites: tuple[str, ...] = ("full-stack-desktop", "full-stack-mobile"),
    suite_count: int | None = None,
    passed_count: int | None = None,
    suite_test_matches: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, object]:
    default_test_matches = {
        "full-stack-desktop": (
            "full-stack-smoke.spec.ts",
            "chat.spec.ts",
            "regression.spec.ts",
            "workflow-editor.spec.ts",
        ),
        "full-stack-mobile": ("mobile-smoke.spec.ts",),
    }
    test_matches_by_suite = suite_test_matches or default_test_matches
    rows = [
        {
            "suite": suite,
            "status": "passed",
            "state_root": f"test-results/{suite}",
            "test_match": list(test_matches_by_suite.get(suite, ())),
            "test_file_count": len(test_matches_by_suite.get(suite, ())),
        }
        for suite in suites
    ]
    return {
        "schema": "octopus.full_stack_smoke_proof.v1",
        "ready": True,
        "suite_count": len(rows) if suite_count is None else suite_count,
        "passed_count": len(rows) if passed_count is None else passed_count,
        "test_file_count": sum(int(row["test_file_count"]) for row in rows),
        "failed_suites": [],
        "suites": rows,
    }

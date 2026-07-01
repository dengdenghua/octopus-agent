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
    assert data["summary"]["full_stack_suite_count"] == 2


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


def _readiness() -> dict[str, object]:
    return {
        "schema": "octopus.production_readiness_gate.v1",
        "ready": True,
        "scorecard_score": 97,
        "automation_score": 95,
        "e2e": {
            "ready": True,
            "verdict": "surpassed",
            "summary": {
                "coverage_ready": 7,
                "coverage_total": 7,
            },
        },
    }


def _full_stack(
    *,
    suites: tuple[str, ...] = ("full-stack-desktop", "full-stack-mobile"),
) -> dict[str, object]:
    rows = [
        {
            "suite": suite,
            "status": "passed",
            "state_root": f"test-results/{suite}",
        }
        for suite in suites
    ]
    return {
        "schema": "octopus.full_stack_smoke_proof.v1",
        "ready": True,
        "suite_count": len(rows),
        "passed_count": len(rows),
        "failed_suites": [],
        "suites": rows,
    }

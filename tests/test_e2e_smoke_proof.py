from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_e2e_smoke_proof_records_desktop_and_mobile_suites(tmp_path: Path) -> None:
    output = tmp_path / "proof" / "full_stack_smoke_proof.json"

    for suite, state_root, test_match in (
        ("full-stack-desktop", tmp_path / "desktop", "full-stack-smoke.spec.ts"),
        ("full-stack-mobile", tmp_path / "mobile", "mobile-smoke.spec.ts"),
    ):
        result = subprocess.run(
            [
                sys.executable,
                "scripts/e2e_smoke_proof.py",
                "--output",
                str(output),
                "--suite",
                suite,
                "--status",
                "passed",
                "--state-root",
                str(state_root),
                "--frontend-port",
                "13000",
                "--backend-host",
                "127.0.0.1",
                "--backend-port",
                "18000",
                "--test-match",
                test_match,
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    data = json.loads(output.read_text(encoding="utf-8"))

    assert data["schema"] == "octopus.full_stack_smoke_proof.v1"
    assert data["ready"] is True
    assert data["suite_count"] == 2
    assert data["passed_count"] == 2
    assert data["test_file_count"] == 2
    assert data["failed_suites"] == []
    assert [suite["suite"] for suite in data["suites"]] == [
        "full-stack-desktop",
        "full-stack-mobile",
    ]
    assert data["suites"][0]["backend_host"] == "127.0.0.1"
    assert data["suites"][0]["test_match"] == ["full-stack-smoke.spec.ts"]
    assert data["suites"][0]["test_file_count"] == 1


def test_e2e_smoke_proof_reports_failed_suite(tmp_path: Path) -> None:
    output = tmp_path / "full_stack_smoke_proof.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/e2e_smoke_proof.py",
            "--output",
            str(output),
            "--suite",
            "full-stack-desktop",
            "--status",
            "failed",
            "--state-root",
            str(tmp_path / "desktop"),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    data = json.loads(output.read_text(encoding="utf-8"))

    assert result.returncode == 1
    assert data["ready"] is False
    assert data["failed_suites"] == ["full-stack-desktop"]

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_e2e_smoke_proof_records_desktop_and_mobile_suites(tmp_path: Path) -> None:
    output = tmp_path / "proof" / "full_stack_smoke_proof.json"

    for suite, state_root, test_match, stats in (
        (
            "full-stack-desktop",
            tmp_path / "desktop",
            "full-stack-smoke.spec.ts",
            {"expected": 13, "skipped": 1, "unexpected": 0, "flaky": 0},
        ),
        (
            "full-stack-mobile",
            tmp_path / "mobile",
            "mobile-smoke.spec.ts",
            {"expected": 3, "skipped": 0, "unexpected": 0, "flaky": 0},
        ),
    ):
        playwright_report = tmp_path / f"{suite}.json"
        _write_playwright_report(playwright_report, stats=stats)
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
                "--playwright-report",
                str(playwright_report),
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
    assert data["test_case_count"] == 17
    assert data["passed_test_count"] == 16
    assert data["skipped_test_count"] == 1
    assert data["failed_test_count"] == 0
    assert data["failed_suites"] == []
    assert [suite["suite"] for suite in data["suites"]] == [
        "full-stack-desktop",
        "full-stack-mobile",
    ]
    assert data["suites"][0]["backend_host"] == "127.0.0.1"
    assert data["suites"][0]["test_match"] == ["full-stack-smoke.spec.ts"]
    assert data["suites"][0]["test_file_count"] == 1
    assert data["suites"][0]["playwright_report_present"] is True
    assert data["suites"][0]["playwright_report_bytes"] > 0
    assert (
        data["suites"][0]["playwright_report_sha256"]
        == hashlib.sha256((tmp_path / "full-stack-desktop.json").read_bytes()).hexdigest()
    )
    assert data["suites"][0]["test_case_count"] == 14
    assert data["suites"][0]["passed_test_count"] == 13


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


def _write_playwright_report(path: Path, *, stats: dict[str, int]) -> None:
    path.write_text(
        json.dumps({"stats": stats, "suites": []}),
        encoding="utf-8",
    )

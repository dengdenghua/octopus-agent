#!/usr/bin/env python3
"""Merge readiness and full-stack smoke proofs into one release certificate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "octopus.e2e_release_proof.v1"
READINESS_SCHEMA = "octopus.production_readiness_gate.v1"
FULL_STACK_SCHEMA = "octopus.full_stack_smoke_proof.v1"
MIN_SCORE = 95
MIN_TEST_FILES_BY_SUITE = {
    "full-stack-desktop": 4,
    "full-stack-mobile": 1,
}
MIN_PASSED_TESTS_BY_SUITE = {
    "full-stack-desktop": 13,
    "full-stack-mobile": 3,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a release-grade E2E proof from gate artifacts.",
    )
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--full-stack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--required-suite",
        action="append",
        default=[],
        help=("Full-stack smoke suite that must be present and passed. May be repeated."),
    )
    args = parser.parse_args()

    report = build_release_proof(
        readiness_path=args.readiness,
        full_stack_path=args.full_stack,
        required_suites=tuple(args.required_suite),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if report["ready"] else 1


def build_release_proof(
    *,
    readiness_path: Path,
    full_stack_path: Path,
    required_suites: tuple[str, ...],
) -> dict[str, Any]:
    readiness = _read_json(readiness_path)
    full_stack = _read_json(full_stack_path)
    required = list(required_suites or ("full-stack-desktop", "full-stack-mobile"))
    suite_status = _suite_status(full_stack)
    missing_suites = [suite for suite in required if suite not in suite_status]
    failed_suites = [
        suite for suite in required if suite in suite_status and suite_status[suite] != "passed"
    ]
    suite_rows = _suite_rows(full_stack)
    suite_test_counts = _suite_test_counts(suite_rows)
    suite_passed_test_counts = _suite_counts(suite_rows, "passed_test_count")
    suite_failed_test_counts = _suite_counts(suite_rows, "failed_test_count")
    weak_suite_test_coverage = [
        suite
        for suite in required
        if suite in suite_test_counts
        and suite_test_counts[suite] < MIN_TEST_FILES_BY_SUITE.get(suite, 1)
    ]
    weak_suite_passed_tests = [
        suite
        for suite in required
        if suite in suite_passed_test_counts
        and suite_passed_test_counts[suite] < MIN_PASSED_TESTS_BY_SUITE.get(suite, 1)
    ]
    suites_with_failed_tests = [
        suite
        for suite in required
        if suite in suite_failed_test_counts and suite_failed_test_counts[suite] > 0
    ]
    passed_suite_count = sum(1 for row in suite_rows if row.get("status") == "passed")
    declared_suite_count = _as_int(full_stack.get("suite_count"))
    declared_passed_count = _as_int(full_stack.get("passed_count"))
    declared_test_file_count = _as_int(full_stack.get("test_file_count"))
    observed_test_file_count = sum(suite_test_counts.values())
    declared_test_case_count = _as_int(full_stack.get("test_case_count"))
    observed_test_case_count = sum(_suite_counts(suite_rows, "test_case_count").values())
    declared_passed_test_count = _as_int(full_stack.get("passed_test_count"))
    observed_passed_test_count = sum(suite_passed_test_counts.values())
    scorecard_score = _as_int(readiness.get("scorecard_score"))
    automation_score = _as_int(readiness.get("automation_score"))
    checks = [
        {
            "id": "production_readiness_schema",
            "passed": readiness.get("schema") == READINESS_SCHEMA,
            "next_action": "Regenerate production readiness proof with the current gate.",
        },
        {
            "id": "production_readiness_ready",
            "passed": bool(readiness.get("ready")),
            "next_action": "Run production readiness gate and fix reported failures.",
        },
        {
            "id": "production_readiness_scores_clear_target",
            "passed": scorecard_score >= MIN_SCORE and automation_score >= MIN_SCORE,
            "next_action": "Restore scorecard and automation scores to the E2E target.",
        },
        {
            "id": "production_readiness_e2e_ready",
            "passed": bool(_nested(readiness, "e2e", "ready")),
            "next_action": "Restore E2E surpass certification readiness.",
        },
        {
            "id": "production_readiness_e2e_surpassed",
            "passed": _nested(readiness, "e2e", "verdict") == "surpassed",
            "next_action": "Restore E2E surpass certification.",
        },
        {
            "id": "production_readiness_coverage_complete",
            "passed": _coverage_complete(readiness),
            "next_action": "Restore all required E2E coverage domains.",
        },
        {
            "id": "production_readiness_coverage_has_no_gaps",
            "passed": _as_int(_nested(readiness, "e2e", "summary", "coverage_gap_domains")) == 0,
            "next_action": "Clear E2E coverage gap domains before release.",
        },
        {
            "id": "full_stack_smoke_schema",
            "passed": full_stack.get("schema") == FULL_STACK_SCHEMA,
            "next_action": "Regenerate full-stack smoke proof with the current script.",
        },
        {
            "id": "full_stack_smoke_ready",
            "passed": bool(full_stack.get("ready")),
            "next_action": "Run full-stack Playwright smoke and fix failures.",
        },
        {
            "id": "full_stack_suite_counts_consistent",
            "passed": (
                declared_suite_count == len(suite_rows)
                and declared_passed_count == passed_suite_count
            ),
            "next_action": "Regenerate full-stack smoke proof; suite counts are inconsistent.",
        },
        {
            "id": "full_stack_required_suites_present",
            "passed": not missing_suites,
            "next_action": f"Run missing full-stack suites: {', '.join(missing_suites)}",
        },
        {
            "id": "full_stack_required_suites_passed",
            "passed": not failed_suites,
            "next_action": f"Fix failing full-stack suites: {', '.join(failed_suites)}",
        },
        {
            "id": "full_stack_test_file_counts_consistent",
            "passed": declared_test_file_count == observed_test_file_count,
            "next_action": (
                "Regenerate full-stack smoke proof; test file counts are inconsistent."
            ),
        },
        {
            "id": "full_stack_required_suites_have_test_coverage",
            "passed": not weak_suite_test_coverage,
            "next_action": (
                "Restore required full-stack test files for suites: "
                f"{', '.join(weak_suite_test_coverage)}"
            ),
        },
        {
            "id": "full_stack_test_case_counts_consistent",
            "passed": (
                declared_test_case_count == observed_test_case_count
                and declared_passed_test_count == observed_passed_test_count
            ),
            "next_action": (
                "Regenerate full-stack smoke proof; Playwright test counts are inconsistent."
            ),
        },
        {
            "id": "full_stack_required_suites_have_passed_tests",
            "passed": not weak_suite_passed_tests,
            "next_action": (
                "Restore required passed Playwright tests for suites: "
                f"{', '.join(weak_suite_passed_tests)}"
            ),
        },
        {
            "id": "full_stack_required_suites_have_no_failed_tests",
            "passed": not suites_with_failed_tests,
            "next_action": (
                f"Fix failed Playwright tests in suites: {', '.join(suites_with_failed_tests)}"
            ),
        },
    ]
    ready = all(bool(check["passed"]) for check in checks)
    return {
        "schema": SCHEMA,
        "ready": ready,
        "verdict": "release_ready" if ready else "needs_work",
        "checks": checks,
        "failed_checks": [str(check["id"]) for check in checks if not bool(check["passed"])],
        "summary": {
            "scorecard_score": scorecard_score,
            "automation_score": automation_score,
            "e2e_verdict": str(_nested(readiness, "e2e", "verdict") or "unknown"),
            "coverage_ready": _as_int(
                _nested(readiness, "e2e", "summary", "coverage_ready"),
            ),
            "coverage_total": _as_int(
                _nested(readiness, "e2e", "summary", "coverage_total"),
            ),
            "coverage_gap_domains": _as_int(
                _nested(readiness, "e2e", "summary", "coverage_gap_domains"),
            ),
            "full_stack_suite_count": declared_suite_count,
            "full_stack_passed_count": declared_passed_count,
            "full_stack_test_file_count": declared_test_file_count,
            "full_stack_test_case_count": declared_test_case_count,
            "full_stack_passed_test_count": declared_passed_test_count,
            "required_suite_test_file_counts": {
                suite: suite_test_counts.get(suite, 0) for suite in required
            },
            "required_suite_passed_test_counts": {
                suite: suite_passed_test_counts.get(suite, 0) for suite in required
            },
            "required_suite_failed_test_counts": {
                suite: suite_failed_test_counts.get(suite, 0) for suite in required
            },
            "required_suites": required,
            "missing_suites": missing_suites,
            "failed_suites": failed_suites,
            "weak_suite_test_coverage": weak_suite_test_coverage,
            "weak_suite_passed_tests": weak_suite_passed_tests,
            "suites_with_failed_tests": suites_with_failed_tests,
        },
        "inputs": {
            "readiness": str(readiness_path),
            "full_stack": str(full_stack_path),
        },
        "readiness": {
            "schema": readiness.get("schema"),
            "ready": readiness.get("ready"),
            "scorecard_score": readiness.get("scorecard_score"),
            "automation_score": readiness.get("automation_score"),
            "e2e": readiness.get("e2e"),
        },
        "full_stack": {
            "schema": full_stack.get("schema"),
            "ready": full_stack.get("ready"),
            "suite_count": full_stack.get("suite_count"),
            "passed_count": full_stack.get("passed_count"),
            "test_file_count": full_stack.get("test_file_count"),
            "test_case_count": full_stack.get("test_case_count"),
            "passed_test_count": full_stack.get("passed_test_count"),
            "skipped_test_count": full_stack.get("skipped_test_count"),
            "failed_test_count": full_stack.get("failed_test_count"),
            "failed_suites": full_stack.get("failed_suites"),
            "suites": full_stack.get("suites"),
        },
        "next_actions": [
            str(check["next_action"])
            for check in checks
            if not bool(check["passed"]) and check.get("next_action")
        ],
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _suite_status(full_stack: dict[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for row in _suite_rows(full_stack):
        suite = str(row.get("suite") or "").strip()
        if suite:
            statuses[suite] = str(row.get("status") or "")
    return statuses


def _suite_rows(full_stack: dict[str, Any]) -> list[dict[str, Any]]:
    suites = full_stack.get("suites")
    if not isinstance(suites, list):
        return []
    return [row for row in suites if isinstance(row, dict)]


def _suite_test_counts(suite_rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in suite_rows:
        suite = str(row.get("suite") or "").strip()
        if not suite:
            continue
        count = _as_int(row.get("test_file_count"))
        if count <= 0:
            test_match = row.get("test_match")
            if isinstance(test_match, list):
                count = len([item for item in test_match if str(item).strip()])
        counts[suite] = count
    return counts


def _suite_counts(suite_rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in suite_rows:
        suite = str(row.get("suite") or "").strip()
        if suite:
            counts[suite] = _as_int(row.get(field))
    return counts


def _coverage_complete(readiness: dict[str, Any]) -> bool:
    ready = _as_int(_nested(readiness, "e2e", "summary", "coverage_ready"))
    total = _as_int(_nested(readiness, "e2e", "summary", "coverage_total"))
    return total > 0 and ready == total


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _nested(data: dict[str, Any], *keys: str) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


if __name__ == "__main__":
    raise SystemExit(main())

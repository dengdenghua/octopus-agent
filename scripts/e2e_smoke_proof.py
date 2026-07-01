#!/usr/bin/env python3
"""Persist machine-readable proof for full-stack Playwright smoke runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "octopus.full_stack_smoke_proof.v1"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Append a full-stack smoke suite result to a proof JSON file.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--status", choices=("passed", "failed"), required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--frontend-port", default="")
    parser.add_argument("--backend-host", default="")
    parser.add_argument("--backend-port", default="")
    parser.add_argument("--test-match", default="")
    parser.add_argument("--playwright-report", type=Path)
    args = parser.parse_args()

    proof = _read_proof(args.output)
    suites = [
        suite
        for suite in proof.get("suites", [])
        if isinstance(suite, dict) and suite.get("suite") != args.suite
    ]
    test_match = [item.strip() for item in str(args.test_match).split(",") if item.strip()]
    playwright = _read_playwright_report(args.playwright_report)
    suites.append(
        {
            "suite": args.suite,
            "status": args.status,
            "state_root": str(args.state_root),
            "frontend_port": str(args.frontend_port),
            "backend_host": str(args.backend_host),
            "backend_port": str(args.backend_port),
            "test_match": test_match,
            "test_file_count": len(test_match),
            "playwright_report": str(args.playwright_report or ""),
            "playwright_report_present": bool(playwright.get("present")),
            "playwright_report_sha256": str(playwright.get("sha256") or ""),
            "playwright_report_bytes": int(playwright.get("bytes") or 0),
            "test_case_count": int(playwright.get("test_case_count") or 0),
            "passed_test_count": int(playwright.get("passed_test_count") or 0),
            "skipped_test_count": int(playwright.get("skipped_test_count") or 0),
            "failed_test_count": int(playwright.get("failed_test_count") or 0),
            "flaky_test_count": int(playwright.get("flaky_test_count") or 0),
            "recorded_at": datetime.now(UTC).isoformat(),
        }
    )
    ready = bool(suites) and all(suite.get("status") == "passed" for suite in suites)
    total_test_files = sum(_test_file_count(suite) for suite in suites)
    total_test_cases = sum(_count_field(suite, "test_case_count") for suite in suites)
    total_passed_tests = sum(_count_field(suite, "passed_test_count") for suite in suites)
    total_skipped_tests = sum(_count_field(suite, "skipped_test_count") for suite in suites)
    total_failed_tests = sum(_count_field(suite, "failed_test_count") for suite in suites)
    total_flaky_tests = sum(_count_field(suite, "flaky_test_count") for suite in suites)
    report = {
        "schema": SCHEMA,
        "ready": ready,
        "suite_count": len(suites),
        "passed_count": sum(1 for suite in suites if suite.get("status") == "passed"),
        "test_file_count": total_test_files,
        "test_case_count": total_test_cases,
        "passed_test_count": total_passed_tests,
        "skipped_test_count": total_skipped_tests,
        "failed_test_count": total_failed_tests,
        "flaky_test_count": total_flaky_tests,
        "failed_suites": [
            str(suite.get("suite")) for suite in suites if suite.get("status") != "passed"
        ],
        "suites": sorted(suites, key=lambda suite: str(suite.get("suite"))),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if ready else 1


def _read_proof(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": SCHEMA, "suites": []}
    if not isinstance(data, dict):
        return {"schema": SCHEMA, "suites": []}
    suites = data.get("suites")
    if not isinstance(suites, list):
        data["suites"] = []
    return data


def _read_playwright_report(path: Path | None) -> dict[str, int | bool | str]:
    if path is None:
        return _empty_playwright_report()
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _empty_playwright_report()
    stats = data.get("stats") if isinstance(data, dict) else {}
    if not isinstance(stats, dict):
        stats = {}
    passed = _nonnegative_int(stats.get("expected")) + _nonnegative_int(stats.get("flaky"))
    skipped = _nonnegative_int(stats.get("skipped"))
    failed = _nonnegative_int(stats.get("unexpected"))
    flaky = _nonnegative_int(stats.get("flaky"))
    total = passed + skipped + failed
    if total == 0:
        total, passed, skipped, failed, flaky = _count_playwright_tests(data)
    return {
        "present": True,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "test_case_count": total,
        "passed_test_count": passed,
        "skipped_test_count": skipped,
        "failed_test_count": failed,
        "flaky_test_count": flaky,
    }


def _empty_playwright_report() -> dict[str, int | bool | str]:
    return {
        "present": False,
        "sha256": "",
        "bytes": 0,
        "test_case_count": 0,
        "passed_test_count": 0,
        "skipped_test_count": 0,
        "failed_test_count": 0,
        "flaky_test_count": 0,
    }


def _count_playwright_tests(data: object) -> tuple[int, int, int, int, int]:
    total = passed = skipped = failed = flaky = 0
    stack: list[object] = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if isinstance(item.get("tests"), list):
                for test in item["tests"]:
                    if not isinstance(test, dict):
                        continue
                    total += 1
                    status = str(test.get("status") or "")
                    if status in {"expected", "passed"}:
                        passed += 1
                    elif status == "skipped":
                        skipped += 1
                    elif status == "flaky":
                        passed += 1
                        flaky += 1
                    else:
                        failed += 1
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return total, passed, skipped, failed, flaky


def _test_file_count(suite: dict[str, Any]) -> int:
    count = suite.get("test_file_count")
    if isinstance(count, int):
        return max(0, count)
    test_match = suite.get("test_match")
    if isinstance(test_match, list):
        return len([item for item in test_match if str(item).strip()])
    return 0


def _count_field(suite: dict[str, Any], field: str) -> int:
    return _nonnegative_int(suite.get(field))


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

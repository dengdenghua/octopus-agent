#!/usr/bin/env python3
"""Merge readiness and full-stack smoke proofs into one release certificate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "octopus.e2e_release_proof.v1"


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
    checks = [
        {
            "id": "production_readiness_ready",
            "passed": bool(readiness.get("ready")),
            "next_action": "Run production readiness gate and fix reported failures.",
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
            "id": "full_stack_smoke_ready",
            "passed": bool(full_stack.get("ready")),
            "next_action": "Run full-stack Playwright smoke and fix failures.",
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
    ]
    ready = all(bool(check["passed"]) for check in checks)
    return {
        "schema": SCHEMA,
        "ready": ready,
        "verdict": "release_ready" if ready else "needs_work",
        "checks": checks,
        "failed_checks": [str(check["id"]) for check in checks if not bool(check["passed"])],
        "summary": {
            "scorecard_score": int(readiness.get("scorecard_score") or 0),
            "automation_score": int(readiness.get("automation_score") or 0),
            "e2e_verdict": str(_nested(readiness, "e2e", "verdict") or "unknown"),
            "coverage_ready": int(
                _nested(readiness, "e2e", "summary", "coverage_ready") or 0,
            ),
            "coverage_total": int(
                _nested(readiness, "e2e", "summary", "coverage_total") or 0,
            ),
            "full_stack_suite_count": int(full_stack.get("suite_count") or 0),
            "full_stack_passed_count": int(full_stack.get("passed_count") or 0),
            "required_suites": required,
            "missing_suites": missing_suites,
            "failed_suites": failed_suites,
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
    suites = full_stack.get("suites")
    if not isinstance(suites, list):
        return statuses
    for row in suites:
        if not isinstance(row, dict):
            continue
        suite = str(row.get("suite") or "").strip()
        if suite:
            statuses[suite] = str(row.get("status") or "")
    return statuses


def _coverage_complete(readiness: dict[str, Any]) -> bool:
    ready = int(_nested(readiness, "e2e", "summary", "coverage_ready") or 0)
    total = int(_nested(readiness, "e2e", "summary", "coverage_total") or 0)
    return total > 0 and ready == total


def _nested(data: dict[str, Any], *keys: str) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


if __name__ == "__main__":
    raise SystemExit(main())

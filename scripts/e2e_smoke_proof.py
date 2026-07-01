#!/usr/bin/env python3
"""Persist machine-readable proof for full-stack Playwright smoke runs."""

from __future__ import annotations

import argparse
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
    args = parser.parse_args()

    proof = _read_proof(args.output)
    suites = [
        suite
        for suite in proof.get("suites", [])
        if isinstance(suite, dict) and suite.get("suite") != args.suite
    ]
    suites.append(
        {
            "suite": args.suite,
            "status": args.status,
            "state_root": str(args.state_root),
            "frontend_port": str(args.frontend_port),
            "backend_host": str(args.backend_host),
            "backend_port": str(args.backend_port),
            "test_match": [
                item.strip() for item in str(args.test_match).split(",") if item.strip()
            ],
            "recorded_at": datetime.now(UTC).isoformat(),
        }
    )
    ready = bool(suites) and all(suite.get("status") == "passed" for suite in suites)
    report = {
        "schema": SCHEMA,
        "ready": ready,
        "suite_count": len(suites),
        "passed_count": sum(1 for suite in suites if suite.get("status") == "passed"),
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


if __name__ == "__main__":
    raise SystemExit(main())

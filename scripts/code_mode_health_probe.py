#!/usr/bin/env python3
"""Run the offline code-mode runtime health probe.

This script is intentionally provider-free: it uses fake routers/clients so CI
can catch code-mode protocol regressions without spending tokens.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name",
        default="code_mode_runtime",
        help="health status name to emit",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="output format; JSON is stable for CI",
    )
    return parser


def _format_text(payload: dict[str, Any]) -> str:
    lines = [f"{payload.get('name', 'code_mode_runtime')}: {payload.get('status')}"]
    detail = str(payload.get("detail") or "").strip()
    if detail:
        lines.append(f"detail: {detail}")
    checks = payload.get("metadata", {}).get("checks", {})
    if isinstance(checks, dict):
        for check_name, check_payload in checks.items():
            if not isinstance(check_payload, dict):
                continue
            state = "pass" if check_payload.get("passed") else "fail"
            check_detail = str(check_payload.get("detail") or "").strip()
            suffix = f" - {check_detail}" if check_detail else ""
            lines.append(f"- {check_name}: {state}{suffix}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from runtime.platform.observability.code_mode_health import run_code_mode_runtime_probe

    args = _build_parser().parse_args(argv)
    status = run_code_mode_runtime_probe(name=args.name)
    payload = status.to_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_format_text(payload))
    return 0 if status.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

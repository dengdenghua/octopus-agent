#!/usr/bin/env python3
"""Print the offline custom-provider compatibility matrix."""

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
        "--path",
        default=None,
        help="custom_models.json path; defaults to the Octopus app path",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="output format; JSON is stable for CI",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when any row needs review or fails",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="run live canary requests against configured providers",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="per-provider live canary timeout in seconds",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="append the matrix result to provider compatibility history JSONL",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="print provider compatibility history summary instead of running a probe",
    )
    parser.add_argument(
        "--history-path",
        default=None,
        help="provider compatibility history JSONL path",
    )
    parser.add_argument(
        "--history-limit",
        type=int,
        default=50,
        help="maximum history records to summarize",
    )
    parser.add_argument(
        "--failures",
        action="store_true",
        help="print provider compatibility failures as evolution samples",
    )
    parser.add_argument(
        "--export-failures",
        default=None,
        help="write provider compatibility failure samples as JSONL",
    )
    parser.add_argument(
        "--failure-limit",
        type=int,
        default=50,
        help="maximum compatibility failure samples to read or export",
    )
    return parser


def _format_text(payload: dict[str, Any]) -> str:
    lines = [
        (
            "provider_compatibility_matrix: "
            f"{payload.get('verdict')} score={payload.get('score')}"
        )
    ]
    source = str(payload.get("source") or "").strip()
    if source:
        lines.append(f"source: {source}")
    for row in payload.get("rows", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('id')}: {row.get('verdict')} "
            f"score={row.get('score')} profile={row.get('profile')}"
        )
        findings = row.get("findings") or []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            lines.append(
                "  "
                f"{finding.get('severity')}: {finding.get('code')} - "
                f"{finding.get('message')}"
            )
        live = row.get("live")
        if isinstance(live, dict) and live.get("enabled"):
            lines.append(f"  live: {live.get('status')}")
            for step in live.get("steps", []):
                if not isinstance(step, dict):
                    continue
                detail = str(step.get("detail") or "").strip()
                suffix = f" - {detail}" if detail else ""
                lines.append(
                    f"    {step.get('name')}: {step.get('status')}{suffix}"
                )
    return "\n".join(lines)


def _format_history_text(payload: dict[str, Any]) -> str:
    lines = [
        (
            "provider_compatibility_history: "
            f"runs={payload.get('total_runs')} "
            f"pass_rate={payload.get('pass_rate')} "
            f"latest={payload.get('latest_verdict')}"
        )
    ]
    path = str(payload.get("path") or "").strip()
    if path:
        lines.append(f"path: {path}")
    for row in payload.get("latest_rows", []):
        if not isinstance(row, dict):
            continue
        live = row.get("live_status")
        live_suffix = f" live={live}" if live is not None else ""
        lines.append(
            f"- {row.get('id')}: {row.get('verdict')} "
            f"score={row.get('score')} profile={row.get('profile')}{live_suffix}"
        )
    return "\n".join(lines)


def _format_failures_text(samples: list[dict[str, Any]]) -> str:
    lines = [f"provider_compatibility_failures: count={len(samples)}"]
    for sample in samples:
        provider_id = sample.get("provider_id") or sample.get("profile") or "provider"
        route = sample.get("primary_repair_route") or "provider_protocol"
        error = str(sample.get("last_error") or "").strip()
        suffix = f" - {error}" if error else ""
        lines.append(f"- {provider_id}: route={route}{suffix}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from runtime.sensing.model_router.provider_compat_matrix import (
        append_provider_compatibility_history,
        build_provider_compatibility_matrix,
        export_provider_compatibility_failures,
        extract_provider_compatibility_failures,
        summarize_provider_compatibility_history,
    )

    args = _build_parser().parse_args(argv)
    if args.history:
        summary = summarize_provider_compatibility_history(
            path=args.history_path,
            limit=args.history_limit,
        )
        payload = summary.to_dict()
        if args.format == "json":
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(_format_history_text(payload))
        return 0

    if args.failures or args.export_failures:
        samples = extract_provider_compatibility_failures(
            path=args.history_path,
            limit=args.failure_limit,
        )
        if args.export_failures:
            export_provider_compatibility_failures(
                args.export_failures,
                history_path=args.history_path,
                limit=args.failure_limit,
            )
        if args.failures:
            if args.format == "json":
                print(json.dumps(samples, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(_format_failures_text(samples))
        return 0

    report = build_provider_compatibility_matrix(
        custom_models_path=args.path,
        live=args.live,
        timeout_seconds=args.timeout,
    )
    if args.record:
        append_provider_compatibility_history(report, path=args.history_path)
    payload = report.to_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_format_text(payload))
    return 1 if args.strict and report.verdict != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())

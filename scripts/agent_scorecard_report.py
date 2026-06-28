#!/usr/bin/env python3
"""Print the Octopus agent-runtime scorecard and radar chart data."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-score",
        type=int,
        default=90,
        help="target Octopus score per dimension",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text", "markdown"),
        default="markdown",
        help="output format",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="optional output path; stdout is used when omitted",
    )
    parser.add_argument(
        "--include-runtime-probe",
        action="store_true",
        help="run the browser/desktop runtime probe before scoring",
    )
    parser.add_argument(
        "--refresh-runtime-evidence-if-stale",
        action="store_true",
        help="run the browser/desktop runtime probe when cached evidence is missing or stale",
    )
    parser.add_argument(
        "--ignore-runtime-evidence-cache",
        action="store_true",
        help="ignore the fresh browser/desktop runtime evidence snapshot",
    )
    parser.add_argument(
        "--runtime-evidence-max-age",
        type=int,
        default=None,
        help="maximum age in seconds for the browser/desktop runtime evidence snapshot",
    )
    parser.add_argument(
        "--api-base-url",
        default="http://127.0.0.1:8000",
        help="Octopus backend base URL used by --include-runtime-probe",
    )
    parser.add_argument(
        "--bearer-token-env",
        default="",
        help="environment variable containing an optional backend bearer token",
    )
    parser.add_argument(
        "--auto-local-auth",
        action="store_true",
        help="try passwordless local auth for the runtime probe",
    )
    parser.add_argument(
        "--real-chrome-relay",
        action="store_true",
        help="verify an already-connected real Chrome relay during runtime evidence refresh/probe",
    )
    parser.add_argument(
        "--open-real-chrome-relay",
        action="store_true",
        help="open the local Chrome relay connect page before verifying the real Chrome relay",
    )
    parser.add_argument(
        "--local-auth-username",
        default="runtime-probe",
        help="username for --auto-local-auth",
    )
    parser.add_argument(
        "--local-auth-password-env",
        default="",
        help="environment variable containing the optional local-auth password",
    )
    return parser


def _format_text(report: dict[str, Any]) -> str:
    lines = [
        (
            "agent_scorecard: "
            f"verdict={report.get('verdict')} "
            f"target={report.get('target_score')}"
        ),
        _overall_line(report),
    ]
    provider_runtime = report.get("provider_runtime")
    if isinstance(provider_runtime, dict):
        lines.append(
            "provider_runtime: "
            f"{provider_runtime.get('verdict')} "
            f"score={provider_runtime.get('score')} "
            f"rows={provider_runtime.get('row_count')}"
        )
        coverage = provider_runtime.get("builtin_profile_coverage")
        if isinstance(coverage, dict):
            lines.append(
                "provider_builtin_coverage: "
                f"ready={coverage.get('ready')} "
                f"covered={len(coverage.get('covered_profiles') or [])}/"
                f"{len(coverage.get('required_profiles') or [])}"
            )
    capability_canary = _browser_desktop_capability_canary(report)
    if isinstance(capability_canary, dict):
        lines.append(
            "browser_desktop_capability: "
            f"{capability_canary.get('verdict')} "
            f"score={capability_canary.get('score')} "
            f"runtime_verified={capability_canary.get('runtime_verified_count')} "
            f"real_chrome={capability_canary.get('real_chrome_profile_verified_count')} "
            f"control_plane_verified={capability_canary.get('control_plane_verified_count')}"
        )
    lines.append("dimensions:")
    for row in report.get("dimensions", []):
        if not isinstance(row, dict):
            continue
        scores = row.get("scores") if isinstance(row.get("scores"), dict) else {}
        lines.append(
            "- "
            f"{row.get('id')}: weight={row.get('weight')} "
            f"codex={scores.get('codex')} "
            f"claude={scores.get('claude_code')} "
            f"kimi={scores.get('kimi_agent_swarm')} "
            f"cursor={scores.get('cursor')} "
            f"octopus={scores.get('octopus')}"
        )
    radar = report.get("radar") if isinstance(report.get("radar"), dict) else {}
    lines.append(
        "radar_edges: "
        f"advantage={radar.get('octopus_advantage_count')} "
        f"gap={radar.get('octopus_gap_count')} "
        f"true_advantage={radar.get('octopus_true_advantage_count')} "
        f"strict_advantage={radar.get('octopus_true_strict_advantage_count')} "
        f"ties={radar.get('octopus_true_tie_count')} "
        f"true_gap={radar.get('octopus_true_gap_count')}"
    )
    return "\n".join(lines)


def _format_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Agent Runtime Scorecard",
        "",
        f"- Verdict: `{report.get('verdict')}`",
        f"- Target score: `{report.get('target_score')}`",
        f"- Overall: {_overall_line(report)}",
        "",
        "## Dimensions",
        "",
        "| Dimension | Weight | Codex | Claude Code | Kimi Agent Swarm | Cursor | Octopus | Gap vs Codex |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report.get("dimensions", []):
        if not isinstance(row, dict):
            continue
        scores = row.get("scores") if isinstance(row.get("scores"), dict) else {}
        gap = int(scores.get("octopus") or 0) - int(scores.get("codex") or 0)
        lines.append(
            "| "
            f"{row.get('title')} | "
            f"{row.get('weight')} | "
            f"{scores.get('codex')} | "
            f"{scores.get('claude_code')} | "
            f"{scores.get('kimi_agent_swarm')} | "
            f"{scores.get('cursor')} | "
            f"{scores.get('octopus')} | "
            f"{gap:+d} |"
        )
    radar = report.get("radar") if isinstance(report.get("radar"), dict) else {}
    mermaid = str(radar.get("mermaid") or "").strip()
    if mermaid:
        lines.extend([
            "",
            "## Radar",
            "",
            (
                "- Edges: "
                f"advantage `{radar.get('octopus_advantage_count')}`, "
                f"gap `{radar.get('octopus_gap_count')}`"
            ),
            (
                "- Edges vs best competitor: "
                f"advantage `{radar.get('octopus_true_advantage_count')}`, "
                f"strict advantage `{radar.get('octopus_true_strict_advantage_count')}`, "
                f"ties `{radar.get('octopus_true_tie_count')}`, "
                f"gap `{radar.get('octopus_true_gap_count')}`"
            ),
            "",
            "```mermaid",
            mermaid,
            "```",
        ])
    provider_runtime = report.get("provider_runtime")
    if isinstance(provider_runtime, dict):
        lines.extend([
            "",
            "## Provider Runtime",
            "",
            (
                "- Matrix: "
                f"`{provider_runtime.get('verdict')}` "
                f"score `{provider_runtime.get('score')}`, "
                f"rows `{provider_runtime.get('row_count')}`"
            ),
            (
                "- Configured profiles: "
                + ", ".join(provider_runtime.get("configured_profiles") or ["none"])
            ),
        ])
        coverage = provider_runtime.get("builtin_profile_coverage")
        if isinstance(coverage, dict):
            lines.append(
                "- Built-in domestic profile coverage: "
                f"`{len(coverage.get('covered_profiles') or [])}/"
                f"{len(coverage.get('required_profiles') or [])}`"
            )
    capability_canary = _browser_desktop_capability_canary(report)
    if isinstance(capability_canary, dict):
        lines.extend([
            "",
            "## Browser/Desktop Capability",
            "",
            (
                "- Canary: "
                f"`{capability_canary.get('verdict')}` "
                f"score `{capability_canary.get('score')}`, "
                f"runtime verified `{capability_canary.get('runtime_verified_count')}`, "
                f"real Chrome profile `{capability_canary.get('real_chrome_profile_verified_count')}`, "
                f"control-plane verified `{capability_canary.get('control_plane_verified_count')}`"
            ),
            "",
            "| Capability | Evidence | Status |",
            "|---|---|---:|",
        ])
        for row in capability_canary.get("capabilities") or []:
            if not isinstance(row, dict):
                continue
            lines.append(
                "| "
                f"{row.get('title')} | "
                f"{row.get('evidence_level')} | "
                f"{'pass' if row.get('passed') is True else 'review'} |"
            )
    next_focus = report.get("next_focus") or []
    if next_focus:
        lines.extend(["", "## Next Focus", ""])
        lines.extend(f"- {item}" for item in next_focus)
    return "\n".join(lines)


def _overall_line(report: dict[str, Any]) -> str:
    overall = report.get("overall") if isinstance(report.get("overall"), dict) else {}
    return (
        f"codex={overall.get('codex')} "
        f"claude_code={overall.get('claude_code')} "
        f"kimi_agent_swarm={overall.get('kimi_agent_swarm')} "
        f"cursor={overall.get('cursor')} "
        f"octopus={overall.get('octopus')}"
    )


def _browser_desktop_capability_canary(report: dict[str, Any]) -> dict[str, Any] | None:
    quality = report.get("browser_desktop_quality")
    if not isinstance(quality, dict):
        return None
    canary = quality.get("capability_canary")
    return canary if isinstance(canary, dict) else None


def main(argv: list[str] | None = None) -> int:
    from runtime.safety.evolution.agent_competitor_scorecard import (
        compute_agent_competitor_scorecard,
    )

    args = _build_parser().parse_args(argv)
    report = compute_agent_competitor_scorecard(
        target_score=args.target_score,
        include_runtime_probe=args.include_runtime_probe,
        api_base_url=args.api_base_url,
        bearer_token=(
            os.environ.get(args.bearer_token_env, "")
            if args.bearer_token_env
            else ""
        ),
        auto_local_auth=args.auto_local_auth,
        local_auth_username=args.local_auth_username,
        local_auth_password=(
            os.environ.get(args.local_auth_password_env, "")
            if args.local_auth_password_env
            else ""
        ),
        use_runtime_evidence_cache=not args.ignore_runtime_evidence_cache,
        refresh_runtime_evidence_if_stale=args.refresh_runtime_evidence_if_stale,
        runtime_evidence_max_age_s=args.runtime_evidence_max_age,
        real_chrome_relay=args.real_chrome_relay,
        open_real_chrome_relay=args.open_real_chrome_relay,
    )
    if args.format == "json":
        output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    elif args.format == "text":
        output = _format_text(report)
    else:
        output = _format_markdown(report)

    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fail fast when release-critical quality signals regress.

This gate intentionally reuses the runtime scorecards instead of duplicating
their evidence rules. It is meant for local and CI verification, so failures
print the exact degraded signal and its next action.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from runtime.safety.evolution.agent_competitor_scorecard import (
    compute_agent_competitor_scorecard,
)
from runtime.safety.evolution.agent_loop_quality import compute_agent_loop_quality
from runtime.safety.evolution.automation_radar import compute_automation_radar
from runtime.safety.evolution.browser_desktop_quality import (
    compute_browser_desktop_quality,
)
from runtime.safety.evolution.digital_employee_quality import (
    compute_digital_employee_quality,
)
from runtime.safety.evolution.e2e_surpass_certification import (
    compute_e2e_surpass_certification,
)
from runtime.safety.evolution.permission_sandbox_quality import (
    compute_permission_sandbox_quality,
)
from runtime.safety.evolution.product_experience_quality import (
    compute_product_experience_quality,
)
from runtime.safety.evolution.repo_context_quality import (
    compute_repo_context_quality,
)

MIN_SCORE = 95


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check Octopus production readiness quality scorecards.",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=MIN_SCORE,
        help=f"Minimum Octopus score for release-critical radars. Default: {MIN_SCORE}.",
    )
    parser.add_argument(
        "--review-queue-path",
        type=Path,
        default=None,
        help=(
            "Review queue to use for browser/desktop replay debt checks. "
            "Defaults to the active OCTOPUS_DATA_DIR/OCTOPUS_HOME runtime queue."
        ),
    )
    args = parser.parse_args(argv)

    result = run_gate(
        min_score=args.min_score,
        review_queue_path=args.review_queue_path,
    )
    if result.failures:
        print("production readiness gate failed:", file=sys.stderr)
        for failure in result.failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(
        "production readiness gate passed: "
        f"scorecard={result.scorecard_score}, automation={result.automation_score}, "
        f"e2e={result.e2e_verdict}, {result.e2e_summary_text}, "
        f"quality={result.quality_summary}",
    )
    return 0


class GateResult:
    def __init__(
        self,
        *,
        failures: list[str],
        scorecard_score: int,
        scorecard_evidence_adjusted_score: int,
        automation_score: int,
        e2e_ready: bool,
        e2e_verdict: str,
        e2e_summary: dict[str, Any],
        e2e_failed_checks: list[str],
        quality_summary: str,
    ) -> None:
        self.failures = failures
        self.scorecard_score = scorecard_score
        self.scorecard_evidence_adjusted_score = scorecard_evidence_adjusted_score
        self.automation_score = automation_score
        self.e2e_ready = e2e_ready
        self.e2e_verdict = e2e_verdict
        self.e2e_summary = e2e_summary
        self.e2e_failed_checks = e2e_failed_checks
        self.quality_summary = quality_summary

    @property
    def e2e_summary_text(self) -> str:
        return (
            f"e2e_scorecard={_nested_int(self.e2e_summary, 'scorecard_octopus')}, "
            f"e2e_automation={_nested_int(self.e2e_summary, 'automation_octopus')}, "
            f"e2e_quality={_nested_int(self.e2e_summary, 'quality_ready')}/"
            f"{_nested_int(self.e2e_summary, 'quality_total')}"
        )


def run_gate(
    *,
    min_score: int = MIN_SCORE,
    review_queue_path: str | Path | None = None,
) -> GateResult:
    failures: list[str] = []

    scorecard = compute_agent_competitor_scorecard(target_score=min_score)
    automation = compute_automation_radar(
        target_score=min_score,
        review_queue_path=review_queue_path,
    )
    e2e_certification = compute_e2e_surpass_certification(
        target_score=min_score,
        review_queue_path=review_queue_path,
    )
    quality_reports = [
        compute_repo_context_quality(),
        compute_permission_sandbox_quality(),
        compute_product_experience_quality(),
        compute_agent_loop_quality(),
        compute_digital_employee_quality(),
        compute_browser_desktop_quality(review_queue_path=review_queue_path),
    ]

    _require_ready(
        failures,
        "agent competitor scorecard parity certification",
        scorecard.get("parity_certification"),
    )
    _require_ready(
        failures,
        "ecosystem readiness",
        scorecard.get("ecosystem_readiness"),
    )
    _require_min_score(
        failures,
        "agent scorecard octopus evidence-adjusted overall",
        _nested_int(scorecard, "evidence_adjusted_overall", "octopus"),
        min_score,
    )
    _require_min_score(
        failures,
        "automation radar octopus overall",
        _nested_int(automation, "overall", "octopus"),
        min_score,
    )
    _require_ready(
        failures,
        "automation radar browser/desktop quality",
        automation.get("browser_desktop_quality"),
    )
    browser_desktop_quality = _quality_report(
        quality_reports,
        "octopus.browser_desktop_quality.v1",
    )
    _require_browser_desktop_replay_trends(
        failures,
        browser_desktop_quality,
    )
    _require_ready(
        failures,
        "automation radar parity certification",
        automation.get("parity_certification"),
    )
    _require_no_evidence_gaps(
        failures,
        "automation radar evidence gaps",
        automation.get("octopus_gaps"),
    )
    _require_ready(
        failures,
        "e2e surpass certification",
        e2e_certification,
    )
    _require_no_failed_checks(
        failures,
        "e2e surpass certification checks",
        e2e_certification.get("checks"),
    )

    for report in quality_reports:
        schema = str(report.get("schema") or "quality report")
        _require_ready(failures, schema, report)
        _require_score(
            failures,
            schema,
            report.get("score"),
            expected=1.0,
        )

    scorecard_score = _nested_int(scorecard, "overall", "octopus")
    scorecard_evidence_adjusted_score = _nested_int(
        scorecard,
        "evidence_adjusted_overall",
        "octopus",
    )
    automation_score = _nested_int(automation, "overall", "octopus")
    e2e_failed_checks = _failed_check_ids(e2e_certification.get("checks"))
    quality_summary = ", ".join(
        f"{report.get('schema')}={report.get('passed')}/{report.get('total')}"
        for report in quality_reports
    )
    return GateResult(
        failures=failures,
        scorecard_score=scorecard_score,
        scorecard_evidence_adjusted_score=scorecard_evidence_adjusted_score,
        automation_score=automation_score,
        e2e_ready=bool(e2e_certification.get("ready")),
        e2e_verdict=str(e2e_certification.get("verdict") or "unknown"),
        e2e_summary=dict(e2e_certification.get("summary") or {}),
        e2e_failed_checks=e2e_failed_checks,
        quality_summary=quality_summary,
    )


def _require_ready(
    failures: list[str],
    label: str,
    report: Any,
) -> None:
    if isinstance(report, Mapping) and report.get("ready") is True:
        return
    next_actions = []
    if isinstance(report, Mapping):
        next_actions = [str(item) for item in report.get("next_actions") or []]
    suffix = f" next_actions={next_actions}" if next_actions else ""
    failures.append(f"{label} is not ready{suffix}")


def _require_min_score(
    failures: list[str],
    label: str,
    score: int,
    minimum: int,
) -> None:
    if score >= minimum:
        return
    failures.append(f"{label} is {score}, below {minimum}")


def _require_score(
    failures: list[str],
    label: str,
    score: Any,
    *,
    expected: float,
) -> None:
    if isinstance(score, int | float) and float(score) >= expected:
        return
    failures.append(f"{label} score is {score!r}, expected >= {expected}")


def _require_no_rows(
    failures: list[str],
    label: str,
    rows: Any,
) -> None:
    if not rows:
        return
    failures.append(f"{label}: {_row_ids(rows)}")


def _require_no_evidence_gaps(
    failures: list[str],
    label: str,
    rows: Any,
) -> None:
    if not isinstance(rows, Sequence) or isinstance(rows, str):
        return
    blocking = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and (row.get("evidence_ready") is not True)
    ]
    if blocking:
        failures.append(f"{label}: {_row_ids(blocking)}")


def _require_no_failed_checks(
    failures: list[str],
    label: str,
    rows: Any,
) -> None:
    if not isinstance(rows, Sequence) or isinstance(rows, str):
        failures.append(f"{label} are unavailable")
        return
    failed = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and row.get("passed") is not True
    ]
    if failed:
        failures.append(f"{label}: {_row_ids(failed)}")


def _require_browser_desktop_replay_trends(
    failures: list[str],
    report: Mapping[str, Any] | None,
) -> None:
    if not isinstance(report, Mapping):
        failures.append("browser/desktop replay trends are unavailable")
        return
    trends = report.get("replay_trends")
    if not isinstance(trends, Mapping):
        failures.append("browser/desktop replay trends are unavailable")
        return
    stale_count = int(trends.get("stale_source_artifact_count") or 0)
    if stale_count:
        failures.append(
            "browser/desktop replay stale source artifacts: "
            f"{stale_count}; reject or regenerate before release",
        )
    recipe_summary = trends.get("repair_recipe_summary")
    if isinstance(recipe_summary, Mapping):
        pending_cases = int(recipe_summary.get("total_pending_cases") or 0)
        recipe_count = int(recipe_summary.get("recipe_count") or 0)
        if pending_cases or recipe_count:
            failures.append(
                "browser/desktop replay repair recipes pending: "
                f"cases={pending_cases}, recipes={recipe_count}",
            )


def _quality_report(
    reports: Sequence[Mapping[str, Any]],
    schema: str,
) -> Mapping[str, Any] | None:
    for report in reports:
        if isinstance(report, Mapping) and report.get("schema") == schema:
            return report
    return None


def _nested_int(report: Mapping[str, Any], *keys: str) -> int:
    value: Any = report
    for key in keys:
        if not isinstance(value, Mapping):
            return 0
        value = value.get(key)
    return int(value or 0)


def _failed_check_ids(rows: Any) -> list[str]:
    if not isinstance(rows, Sequence) or isinstance(rows, str):
        return ["unavailable"]
    failed: list[str] = []
    for row in rows:
        if isinstance(row, Mapping) and row.get("passed") is not True:
            failed.append(str(row.get("id") or row.get("title") or row))
    return failed


def _row_ids(rows: Any) -> str:
    if not isinstance(rows, Sequence) or isinstance(rows, str):
        return repr(rows)
    labels = []
    for row in rows:
        if isinstance(row, Mapping):
            labels.append(str(row.get("id") or row.get("title") or row))
        else:
            labels.append(str(row))
    return ", ".join(labels)


if __name__ == "__main__":
    raise SystemExit(main())

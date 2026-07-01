from __future__ import annotations

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
from runtime.safety.evolution.permission_sandbox_quality import (
    compute_permission_sandbox_quality,
)
from runtime.safety.evolution.product_experience_quality import (
    compute_product_experience_quality,
)
from runtime.safety.evolution.repo_context_quality import (
    compute_repo_context_quality,
)

QUALITY_REPORTS = (
    compute_repo_context_quality,
    compute_permission_sandbox_quality,
    compute_product_experience_quality,
    compute_agent_loop_quality,
    compute_digital_employee_quality,
    compute_browser_desktop_quality,
)


def compute_e2e_surpass_certification(
    *,
    target_score: int = 95,
    review_queue_path: str | Path | None = None,
) -> dict[str, Any]:
    """One operator-facing proof that Octopus clears the E2E Codex bar.

    The scorecard is the broad product/runtime comparison, automation radar is
    the browser/desktop slice, and quality reports are the release gates that
    keep each evidence surface from becoming a stale static number.
    """
    scorecard = compute_agent_competitor_scorecard(target_score=target_score)
    automation = compute_automation_radar(
        target_score=target_score,
        review_queue_path=review_queue_path,
    )
    quality_reports = [
        _quality_report(compute, review_queue_path=review_queue_path)
        for compute in QUALITY_REPORTS
    ]
    scorecard_summary = scorecard.get("surpass_summary") or {}
    scorecard_octopus = _nested_int(scorecard, "overall", "octopus")
    scorecard_evidence_adjusted_octopus = _nested_int(
        scorecard,
        "evidence_adjusted_overall",
        "octopus",
    )
    automation_octopus = _nested_int(automation, "overall", "octopus")
    checks = [
        {
            "id": "scorecard_overall",
            "title": "Agent scorecard overall clears target",
            "passed": scorecard_octopus >= target_score,
            "score": scorecard_octopus,
            "target": target_score,
        },
        {
            "id": "scorecard_evidence_adjusted_overall",
            "title": "Evidence-adjusted scorecard clears target",
            "passed": scorecard_evidence_adjusted_octopus >= target_score,
            "score": scorecard_evidence_adjusted_octopus,
            "target": target_score,
        },
        {
            "id": "scorecard_all_dimensions_surpassed",
            "title": "All scorecard dimensions surpass best external baseline",
            "passed": bool(scorecard_summary.get("all_dimensions_surpassed")),
            "score": int(scorecard_summary.get("surpassed_dimensions") or 0),
            "target": int(scorecard_summary.get("total_dimensions") or 0),
        },
        {
            "id": "scorecard_no_focus_gaps",
            "title": "No effective scorecard focus gaps remain",
            "passed": not bool(scorecard.get("octopus_focus_gaps")),
            "score": 0,
            "target": 0,
        },
        {
            "id": "automation_overall",
            "title": "Automation radar clears target",
            "passed": automation_octopus >= target_score,
            "score": automation_octopus,
            "target": target_score,
        },
        {
            "id": "automation_no_gaps",
            "title": "No automation evidence gaps remain",
            "passed": not bool(automation.get("octopus_gaps")),
            "score": len(automation.get("octopus_gaps") or []),
            "target": 0,
        },
    ]
    checks.extend(_quality_checks(quality_reports))
    ready = all(bool(check.get("passed")) for check in checks)
    return {
        "schema": "octopus.e2e_surpass_certification.v1",
        "target_score": target_score,
        "ready": ready,
        "verdict": "surpassed" if ready else "needs_work",
        "summary": {
            "scorecard_octopus": scorecard_octopus,
            "scorecard_best_external": _best_external_score(scorecard),
            "scorecard_evidence_adjusted_octopus": (
                scorecard_evidence_adjusted_octopus
            ),
            "automation_octopus": automation_octopus,
            "automation_codex": _nested_int(automation, "overall", "codex"),
            "quality_ready": sum(
                1 for report in quality_reports
                if bool(report.get("ready"))
            ),
            "quality_total": len(quality_reports),
            "all_dimensions_surpassed": bool(
                scorecard_summary.get("all_dimensions_surpassed"),
            ),
            "scorecard_gap_dimensions": int(
                scorecard_summary.get("gap_dimensions") or 0,
            ),
            "automation_gap_dimensions": len(automation.get("octopus_gaps") or []),
        },
        "checks": checks,
        "scorecard": {
            "schema": scorecard.get("schema"),
            "overall": scorecard.get("overall"),
            "evidence_adjusted_overall": scorecard.get(
                "evidence_adjusted_overall",
            ),
            "verdict": scorecard.get("verdict"),
            "evidence_adjusted_verdict": scorecard.get(
                "evidence_adjusted_verdict",
            ),
            "surpass_summary": scorecard_summary,
            "next_focus": scorecard.get("next_focus") or [],
        },
        "automation": {
            "schema": automation.get("schema"),
            "overall": automation.get("overall"),
            "verdict": automation.get("verdict"),
            "next_focus": automation.get("next_focus") or [],
            "gap_count": len(automation.get("octopus_gaps") or []),
        },
        "quality": [
            {
                "schema": report.get("schema"),
                "ready": report.get("ready"),
                "score": report.get("score"),
                "passed": report.get("passed"),
                "total": report.get("total"),
                "next_actions": report.get("next_actions") or [],
            }
            for report in quality_reports
        ],
        "next_actions": [
            str(check.get("next_action"))
            for check in checks
            if not check.get("passed") and check.get("next_action")
        ],
    }


def _quality_report(compute: Any, *, review_queue_path: str | Path | None) -> dict[str, Any]:
    if compute is compute_browser_desktop_quality:
        return compute(review_queue_path=review_queue_path)
    return compute()


def _quality_checks(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for report in reports:
        schema = str(report.get("schema") or "quality_report")
        ready = bool(report.get("ready"))
        score = float(report.get("score") or 0.0)
        checks.append({
            "id": f"{schema}:ready",
            "title": f"{schema} is ready",
            "passed": ready,
            "score": int(report.get("passed") or 0),
            "target": int(report.get("total") or 0),
            "next_action": _first_next_action(report),
        })
        checks.append({
            "id": f"{schema}:score",
            "title": f"{schema} score is complete",
            "passed": score >= 1.0,
            "score": score,
            "target": 1.0,
            "next_action": _first_next_action(report),
        })
    return checks


def _first_next_action(report: dict[str, Any]) -> str:
    actions = report.get("next_actions")
    if isinstance(actions, list) and actions:
        return str(actions[0])
    return ""


def _best_external_score(scorecard: dict[str, Any]) -> int:
    overall = scorecard.get("overall")
    external = scorecard.get("external_competitors")
    if not isinstance(overall, dict) or not isinstance(external, list):
        return 0
    return max((int(overall.get(name) or 0) for name in external), default=0)


def _nested_int(report: dict[str, Any], *keys: str) -> int:
    value: Any = report
    for key in keys:
        if not isinstance(value, dict):
            return 0
        value = value.get(key)
    return int(value or 0)


__all__ = [
    "QUALITY_REPORTS",
    "compute_e2e_surpass_certification",
]

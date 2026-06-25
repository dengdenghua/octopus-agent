from __future__ import annotations

from typing import Any

from runtime.execution.loops.models import LoopRun
from runtime.execution.loops.recovery import build_loop_run_checkpoint
from runtime.execution.loops.replay import (
    build_loop_run_findings,
    build_loop_run_replay,
    build_loop_run_review_score,
)


def _loop_fingerprint(run: LoopRun) -> str:
    return str(run.run_id or "")[:16]


def _failing_check_names(run: LoopRun) -> list[str]:
    result = run.last_verifier_result
    if result is None:
        return []
    names: list[str] = []
    for finding in result.findings:
        if finding.passed:
            continue
        name = str(finding.name or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def build_loop_run_review(run: LoopRun) -> dict[str, Any]:
    attempts = len(run.attempts)
    failed_checks = _failing_check_names(run)
    candidates: list[dict[str, Any]] = []
    backlog: list[dict[str, Any]] = []
    verifier_profile = str(run.policy.verifier_profile or "python_repo_patch")
    findings = build_loop_run_findings(run)
    score, score_reasons = build_loop_run_review_score(run, findings)
    replay = build_loop_run_replay(run)
    resume_available = run.status.value in {"failed", "cancelled"}
    latest_checkpoint = build_loop_run_checkpoint(run) if resume_available else {}

    if run.status.value == "completed" and attempts > 1:
        candidates.append(
            {
                "kind": "success_pattern",
                "priority": "P1",
                "memory_bucket": "experience",
                "title": "Verification-guided repair converged",
                "text": (
                    f"Code loop reached a verified passing state after {attempts} attempts "
                    f"using verifier profile {verifier_profile}. Keep repair prompts grounded "
                    "in the failing verifier output before retrying."
                ),
            }
        )
    elif run.status.value == "failed":
        checks_text = ", ".join(failed_checks[:5]) if failed_checks else "verification or execution failures"
        candidates.append(
            {
                "kind": "failure_pattern",
                "priority": "P0",
                "memory_bucket": "experience",
                "title": "Code loop exhausted retries",
                "text": (
                    f"Loop run exhausted {attempts or 1} attempts and still failed. "
                    f"Most recent failing signals: {checks_text}. Review whether the repair "
                    "prompt carried enough concrete evidence into the next attempt."
                ),
            }
        )
        backlog.append(
            {
                "priority": "P1",
                "experiment": "Add replay coverage for loop failure pattern",
                "hypothesis": (
                    "A deterministic replay or fixture for this loop failure would make "
                    "repair prompts and verifier-guided retries easier to validate."
                ),
                "minimal_implementation": (
                    "Capture the failing workspace diff, verifier output, and retry prompt "
                    "as a replay-style fixture for operator review."
                ),
                "validation_metric": "A replayed loop can reproduce the same failure signature.",
            }
        )

    return {
        "schema": "octopus.task_run_review.v1",
        "task_id": run.run_id,
        "thread_id": run.thread_id or run.run_id,
        "turn_id": run.run_id,
        "agent_id": "loop_controller",
        "status": run.status.value,
        "score": score,
        "score_reasons": score_reasons,
        "summary": {
            "attempt_count": attempts,
            "verifier_profile": verifier_profile,
            "final_status": run.status.value,
            "workspace_path": run.workspace_path,
            "parent_run_id": run.parent_run_id,
            "origin_run_id": run.origin_run_id,
            "resume_checkpoint_id": run.resume_checkpoint_id,
        },
        "findings": findings,
        "replay": replay,
        "resume": {
            "available": resume_available,
            "source": "loop_runs",
            "latest_checkpoint": latest_checkpoint,
            "resume_from_run_id": run.run_id if resume_available else None,
            "reuse_workspace": bool(run.workspace_path) if resume_available else False,
        },
        "learning_candidates": candidates,
        "backlog_candidates": backlog,
    }

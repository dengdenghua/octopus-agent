from __future__ import annotations

import json
from typing import Any

from runtime.execution.loops.models import LoopAttempt, LoopRun, VerifierResult


def _preview(value: Any, *, limit: int = 280) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _failed_check_names(result: VerifierResult | None) -> list[str]:
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


def _last_attempt(run: LoopRun) -> LoopAttempt | None:
    return run.attempts[-1] if run.attempts else None


def _checkpoint_summary(run: LoopRun, attempt: LoopAttempt | None) -> str:
    summary = str(run.last_error or "").strip()
    if not summary and run.last_verifier_result is not None:
        summary = str(run.last_verifier_result.summary or "").strip()
    if not summary and attempt is not None:
        summary = (
            str(attempt.error or "").strip()
            or str(attempt.terminated_reason or "").strip()
            or str(attempt.final_answer or "").strip()
        )
    base = f"{run.status.value} after {len(run.attempts)} attempt"
    if len(run.attempts) != 1:
        base += "s"
    if not summary:
        return base
    return f"{base}: {_preview(summary, limit=220)}"


def _action(tool: str, args: dict[str, Any]) -> str:
    return f"{tool}({json.dumps(args, ensure_ascii=False, sort_keys=True)})"


def _recent_tool_calls(run: LoopRun) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for attempt in run.attempts[-4:]:
        items.append(
            {
                "iteration": attempt.attempt_index,
                "tool": "react_attempt",
                "input_preview": _preview(attempt.prompt, limit=240),
                "observation_preview": _preview(
                    attempt.error or attempt.final_answer or attempt.terminated_reason,
                    limit=280,
                ),
            }
        )
        if attempt.verifier_result is not None:
            items.append(
                {
                    "iteration": attempt.attempt_index,
                    "tool": f"verifier:{attempt.verifier_result.profile}",
                    "input_preview": _preview(
                        f"workspace={run.workspace_path or ''}",
                        limit=240,
                    ),
                    "observation_preview": _preview(
                        attempt.verifier_result.summary
                        or ", ".join(_failed_check_names(attempt.verifier_result)),
                        limit=280,
                    ),
                }
            )
    return items[-8:]


def _steps_snapshot(run: LoopRun) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for attempt in run.attempts:
        steps.append(
            {
                "iteration": attempt.attempt_index,
                "action": _action(
                    "react_attempt",
                    {"prompt": _preview(attempt.prompt, limit=320)},
                ),
                "observation": _preview(
                    attempt.error or attempt.final_answer or attempt.terminated_reason,
                    limit=320,
                ),
            }
        )
        if attempt.verifier_result is not None:
            steps.append(
                {
                    "iteration": attempt.attempt_index,
                    "action": _action(
                        f"verifier:{attempt.verifier_result.profile}",
                        {"workspace_path": run.workspace_path or ""},
                    ),
                    "observation": _preview(
                        attempt.verifier_result.summary
                        or ", ".join(_failed_check_names(attempt.verifier_result))
                        or attempt.verifier_result.kind,
                        limit=320,
                    ),
                }
            )
    return steps


def _attempt_snapshots(run: LoopRun) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for attempt in run.attempts:
        verifier = attempt.verifier_result
        items.append(
            {
                "attempt_index": attempt.attempt_index,
                "status": attempt.status,
                "success": attempt.success,
                "started_at": attempt.started_at,
                "completed_at": attempt.completed_at,
                "terminated_reason": attempt.terminated_reason,
                "prompt_preview": _preview(attempt.prompt, limit=320),
                "final_answer_preview": _preview(attempt.final_answer, limit=220),
                "error_preview": _preview(attempt.error, limit=220),
                "verifier": (
                    {
                        "profile": verifier.profile,
                        "kind": verifier.kind,
                        "passed": verifier.passed,
                        "summary": _preview(verifier.summary, limit=220),
                        "failed_checks": _failed_check_names(verifier),
                    }
                    if verifier is not None
                    else {}
                ),
            }
        )
    return items


def build_loop_run_checkpoint(run: LoopRun) -> dict[str, Any]:
    attempt = _last_attempt(run)
    iteration = attempt.attempt_index if attempt is not None else len(run.attempts)
    timestamp = (
        attempt.completed_at
        or attempt.started_at
        if attempt is not None
        else run.completed_at
        or run.updated_at
        or run.created_at
    )
    failed_checks = _failed_check_names(run.last_verifier_result)
    summary = _checkpoint_summary(run, attempt)
    return {
        "schema": "octopus.loop_run_checkpoint.v1",
        "id": f"loop-run:{run.run_id}:attempt:{iteration or 0}",
        "task_id": run.run_id,
        "thread_id": run.thread_id or run.run_id,
        "agent_id": "loop_controller",
        "checkpoint_type": "loop_run",
        "iteration": iteration,
        "ts": timestamp,
        "summary": summary,
        "state": {
            "current_phase": run.status.value,
            "progress_summary": summary,
            "attempt_count": len(run.attempts),
            "workspace_path": run.workspace_path,
            "messages_snapshot": [],
            "steps_snapshot": _steps_snapshot(run),
            "attempt_snapshots": _attempt_snapshots(run),
            "working_set_snapshot": (
                [{"path": run.workspace_path}] if str(run.workspace_path or "").strip() else []
            ),
            "parent_run_id": run.parent_run_id,
            "origin_run_id": run.origin_run_id,
            "resume_checkpoint_id": run.resume_checkpoint_id,
            "last_attempt": (
                {
                    "attempt_index": attempt.attempt_index,
                    "status": attempt.status,
                    "success": attempt.success,
                    "terminated_reason": attempt.terminated_reason,
                    "prompt_preview": _preview(attempt.prompt, limit=320),
                    "final_answer_preview": _preview(attempt.final_answer, limit=220),
                    "error_preview": _preview(attempt.error, limit=220),
                }
                if attempt is not None
                else {}
            ),
            "last_verifier": (
                {
                    "profile": run.last_verifier_result.profile,
                    "kind": run.last_verifier_result.kind,
                    "passed": run.last_verifier_result.passed,
                    "summary": _preview(run.last_verifier_result.summary, limit=220),
                    "failed_checks": failed_checks,
                }
                if run.last_verifier_result is not None
                else {}
            ),
            "recent_tool_calls": _recent_tool_calls(run),
        },
    }


def build_loop_run_resume_proposal(run: LoopRun) -> dict[str, Any]:
    checkpoint = build_loop_run_checkpoint(run)
    state = checkpoint["state"] if isinstance(checkpoint.get("state"), dict) else {}
    last_verifier = state.get("last_verifier") if isinstance(state.get("last_verifier"), dict) else {}
    failed_checks = [
        str(name) for name in last_verifier.get("failed_checks") or [] if str(name or "").strip()
    ]
    workspace_path = str(run.workspace_path or "").strip()
    title = (
        f"Resume {run.status.value} loop run"
        if run.status.value in {"failed", "cancelled"}
        else "Resume loop run"
    )
    steps = [
        f"Restore loop run {run.run_id} from checkpoint {checkpoint['id']}.",
        f"Continue from attempt {int(checkpoint.get('iteration') or 0) + 1}.",
        (
            f"Reuse the existing workspace at {workspace_path}."
            if workspace_path
            else "Allocate or confirm a workspace before continuing."
        ),
        (
            f"Start from the latest verifier signal: {_preview(last_verifier.get('summary') or '', limit=200)}"
            if str(last_verifier.get("summary") or "").strip()
            else (
                "Re-check the latest failing verifier output before continuing."
                if failed_checks
                else "Review the latest attempt outcome before continuing."
            )
        ),
    ]
    return {
        "checkpoint": {
            "id": checkpoint["id"],
            "task_id": checkpoint["task_id"],
            "thread_id": checkpoint["thread_id"],
            "agent_id": checkpoint["agent_id"],
            "type": checkpoint["checkpoint_type"],
            "iteration": checkpoint["iteration"],
            "timestamp": checkpoint["ts"],
        },
        "recovery_hints": {
            "phase": state.get("current_phase") or None,
            "progress": state.get("progress_summary") or None,
            "message_count": len(state.get("messages_snapshot") or []),
            "step_count": len(state.get("steps_snapshot") or []),
            "working_set": [workspace_path] if workspace_path else [],
            "recent_tool_calls": state.get("recent_tool_calls") or [],
            "failed_checks": failed_checks,
        },
        "resume_plan": {
            "title": title,
            "steps": steps,
        },
        "safety": {
            "raw_state_included": False,
            "raw_message_snapshots_included": False,
        },
    }


def build_loop_run_resume_prompt(
    source: LoopRun,
    *,
    goal: str,
    checkpoint_id: str,
) -> str:
    checkpoint = build_loop_run_checkpoint(source)
    state = checkpoint["state"] if isinstance(checkpoint.get("state"), dict) else {}
    last_attempt = state.get("last_attempt") if isinstance(state.get("last_attempt"), dict) else {}
    last_verifier = state.get("last_verifier") if isinstance(state.get("last_verifier"), dict) else {}
    lines = [
        goal,
        "",
        "Resume context from previous loop run:",
        f"- Source run: {source.run_id}",
        f"- Resume checkpoint: {checkpoint_id}",
        f"- Previous status: {source.status.value}",
        f"- Continue from attempt {int(checkpoint.get('iteration') or 0) + 1}",
    ]
    if str(source.workspace_path or "").strip():
        lines.append(f"- Workspace: {source.workspace_path}")
    if str(last_verifier.get("summary") or "").strip():
        lines.append(f"- Latest verifier signal: {last_verifier['summary']}")
    failed_checks = [
        str(name) for name in last_verifier.get("failed_checks") or [] if str(name or "").strip()
    ]
    if failed_checks:
        lines.append(f"- Failed checks: {', '.join(failed_checks[:5])}")
    if str(last_attempt.get("prompt_preview") or "").strip():
        lines.append(f"- Last attempt prompt: {last_attempt['prompt_preview']}")
    lines.extend(
        [
            "",
            "Resume from the current workspace state when possible. Validate what is already done,",
            "then finish the remaining fixes without redoing completed work.",
        ]
    )
    return "\n".join(lines).strip()


__all__ = [
    "build_loop_run_checkpoint",
    "build_loop_run_resume_prompt",
    "build_loop_run_resume_proposal",
]

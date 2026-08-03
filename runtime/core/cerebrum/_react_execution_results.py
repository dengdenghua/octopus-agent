"""Tool-result / observation shaping for the ReAct loop.

Extracted from ``react_execution.py``. Classifies finished beak steps
(verification kind, command text, effective success), surfaces structured
metadata on realtime ``tool_end`` events, renders background-task
bookkeeping text, builds the completion receipt, checks executor skill
availability, and decides whether a write is a scoped artifact write.
Leaf module: imports only from react_* leaf modules and platform layers —
never imports react_loop or react_execution.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.core.cerebrum.completion_receipt import build_completion_receipt
from runtime.platform.models import Step

_VERIFICATION_TOOL_KINDS: dict[str, str] = {
    "run_tests": "test",
    "lint_check": "lint",
    "format_code": "lint",
}

_SCOPED_ARTIFACT_WRITE_TOOLS = frozenset(
    {
        "write_text_file",
        "append_text_file",
        "edit_text_file",
        "edit_file",
        "multi_edit_file",
    }
)


def _background_task_info_from_observation(observation: str | None) -> dict[str, Any] | None:
    """Extract a background shell snapshot from a rendered tool observation."""

    if not isinstance(observation, str) or not observation.strip():
        return None
    payload = observation.split("\n", 1)[1] if "\n" in observation else observation
    try:
        data = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        return None
    if data.get("running") is True or data.get("status") == "running":
        return data
    return None


def _verification_kind_from_command(command: str) -> str | None:
    """Classify shell commands that are actually verification steps."""

    text = f" {command.lower()} "
    test_markers = (
        " pytest",
        " -m pytest",
        " unittest",
        " vitest",
        " jest",
        " playwright test",
        " npm test",
        " npm run test",
        " pnpm test",
        " pnpm run test",
        " yarn test",
        " cargo test",
        " go test",
        " dotnet test",
    )
    lint_markers = (
        " eslint",
        " ruff check",
        " flake8",
        " biome lint",
        " npm run lint",
        " pnpm lint",
        " pnpm run lint",
        " yarn lint",
    )
    typecheck_markers = (
        " tsc",
        " vue-tsc",
        " pyright",
        " mypy",
        " py_compile",
        " npm run typecheck",
        " pnpm typecheck",
        " pnpm run typecheck",
        " yarn typecheck",
    )
    build_markers = (
        " npm run build",
        " pnpm build",
        " pnpm run build",
        " yarn build",
        " cargo build",
        " go build",
        " dotnet build",
        " mvn package",
        " gradle build",
    )
    if any(marker in text for marker in test_markers):
        return "test"
    if any(marker in text for marker in lint_markers):
        return "lint"
    if any(marker in text for marker in typecheck_markers):
        return "typecheck"
    if any(marker in text for marker in build_markers):
        return "build"
    return None


def _command_from_tool_step(beak_step: Step, output: dict[str, Any]) -> str:
    action_args = getattr(getattr(beak_step, "action", None), "args", {}) or {}
    raw = action_args.get("command") or action_args.get("cmd")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, list):
        return " ".join(str(part) for part in raw)
    argv = output.get("argv")
    if isinstance(argv, list):
        return " ".join(str(part) for part in argv)
    return ""


def _tool_event_extras_from_beak_step(
    beak_step: Step | None,
    tool_name: str,
) -> dict[str, Any]:
    """Surface structured beak metadata on realtime tool_end events."""

    if beak_step is None:
        return {}
    result = getattr(beak_step, "result", None)
    output = getattr(result, "output", None)
    if not isinstance(output, dict):
        return {}

    extras: dict[str, Any] = {}
    effect_receipt = output.get("effect_receipt")
    if isinstance(effect_receipt, dict):
        effect_key = effect_receipt.get("effect_key")
        call_id = effect_receipt.get("call_id")
        state = effect_receipt.get("state")
        reason = effect_receipt.get("reason")
        fencing_token = effect_receipt.get("fencing_token")
        if (
            isinstance(effect_key, str)
            and effect_key
            and isinstance(call_id, str)
            and call_id
            and state == "indeterminate"
            and isinstance(reason, str)
        ):
            extras["effect_receipt"] = {
                "effect_key": effect_key,
                "call_id": call_id,
                "state": "indeterminate",
                "reason": reason,
                "fencing_token": (
                    fencing_token
                    if isinstance(fencing_token, int) and not isinstance(fencing_token, bool)
                    else 0
                ),
            }
    diff = output.get("diff_preview") or output.get("diff")
    if isinstance(diff, str) and diff.strip():
        extras["diff"] = diff

    command = _command_from_tool_step(beak_step, output)
    kind = _VERIFICATION_TOOL_KINDS.get(tool_name)
    if kind is None and tool_name in {"exec_shell", "shell_command", "bash"}:
        kind = _verification_kind_from_command(command)
    if kind is not None:
        stdout = output.get("stdout")
        stderr = output.get("stderr")
        exit_code = output.get("exit_code")
        success = output.get("success")
        if not isinstance(success, bool) and isinstance(exit_code, int):
            success = exit_code == 0
        extras["verification"] = {
            "command": command or output.get("command") or tool_name,
            "kind": kind,
            "exit_code": exit_code if isinstance(exit_code, int) else None,
            "success": bool(success) if isinstance(success, bool) else None,
            "stdout_tail": stdout if isinstance(stdout, str) else None,
            "stderr_tail": stderr if isinstance(stderr, str) else None,
        }
    return extras


def _beak_step_effective_success(step: Any) -> bool:
    result = getattr(step, "result", None)
    if getattr(result, "status", "success") != "success":
        return False

    output = getattr(result, "output", None)
    if not isinstance(output, dict):
        return True

    success = output.get("success")
    if isinstance(success, bool):
        return success

    exit_code = output.get("exit_code")
    if isinstance(exit_code, int):
        return exit_code == 0

    return True


def _has_unrecovered_beak_failure(steps: list[Any]) -> bool:
    """Return True only when the last failed tool has no later recovery.

    A ReAct turn is allowed to recover by changing tools or arguments.  The
    former all-or-nothing aggregation marked the entire turn failed forever
    after one transient error, even when later verification succeeded and a
    guarded final answer was produced.  Checklist/blackboard bookkeeping does
    not count as recovery; a later substantive tool execution must succeed.
    """

    last_failure = -1
    for index, step in enumerate(steps):
        if not _beak_step_effective_success(step):
            last_failure = index
    if last_failure < 0:
        return False

    bookkeeping = {
        "todo_write",
        "bb_write",
        "bb_read",
        "bb_keys",
        "search_capabilities",
        "query_capability",
        "query_skill",
    }
    for step in steps[last_failure + 1 :]:
        action = getattr(step, "action", None)
        name = str(getattr(action, "name", "") or "").strip()
        if name not in bookkeeping and _beak_step_effective_success(step):
            return False
    return True


def _format_background_task_heartbeat(task_ids: list[str]) -> str:
    """Render the periodic 'background tasks still running' nudge.

    Kept as a tiny helper so test_background_task_heartbeat can assert
    the exact wording without spinning up the full ReAct loop.
    """
    ids_str = ", ".join(task_ids)
    return (
        "[background-task-tracker]\n"
        f"Background processes still registered: {ids_str}.\n"
        "Use read_shell_output(task_id) to check progress, or "
        "kill_shell(task_id) to stop.\n"
        "If you've already finalised the task without checking, do so now."
    )


def _react_completion_receipt(
    *,
    final_answer: str | None,
    terminated_reason: str,
    effective_success: bool,
    executed_beak_steps: list[Any],
) -> dict[str, object]:
    if terminated_reason == "final_answer" and final_answer and effective_success:
        run_status = "completed"
    elif terminated_reason in {"paused", "cancelled"}:
        run_status = "pending"
    else:
        run_status = "failed"

    tool_statuses = [
        str(getattr(getattr(step, "result", None), "status", "") or "")
        for step in executed_beak_steps
    ]
    statuses = [
        ("completed" if status == "success" else status) for status in tool_statuses if status
    ] or [run_status]
    if run_status != "completed":
        statuses.append(run_status)

    artifact_count = 0
    for step in executed_beak_steps:
        files = getattr(getattr(step, "result", None), "files_modified", None)
        if isinstance(files, list):
            artifact_count += len(files)

    warnings: list[str] = []
    if terminated_reason != "final_answer":
        warnings.append(f"terminated:{terminated_reason}")

    return build_completion_receipt(
        statuses,
        contract_warnings=warnings,
        artifact_count=artifact_count,
        output_present=bool(final_answer),
    ).to_dict()


def _skill_available_in_executor(executor: Any, skill_name: str) -> bool:
    """Check if a skill is registered and available in the executor."""
    if executor is None:
        return False
    try:
        registry = getattr(executor, "registry", None)
        if registry is None:
            return False
        if hasattr(registry, "has") and callable(registry.has):
            return bool(registry.has(skill_name))
        if hasattr(registry, "is_enabled") and callable(registry.is_enabled):
            return bool(registry.is_enabled(skill_name))
        return False
    except (AttributeError, TypeError, ValueError):
        return False


def _is_scoped_artifact_write(tool_name: str, args: dict[str, Any] | None) -> bool:
    """Allow routine non-code deliverables without an approval round trip."""
    if tool_name not in _SCOPED_ARTIFACT_WRITE_TOOLS or not isinstance(args, dict):
        return False
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return False

    from pathlib import Path

    from runtime.platform.process.scope import resolve_write_scope, thread_artifact_root
    from runtime.platform.process.session import current_session

    session = current_session()
    if session is None:
        return False
    scope = resolve_write_scope(session)
    if scope.mode in {"code", "plan"}:
        return False

    artifact_root = thread_artifact_root(
        session.thread_id or "default",
        explicit_root=(
            session.metadata.get("_artifact_output_root")
            if isinstance(session.metadata.get("_artifact_output_root"), str)
            else None
        ),
    )
    supplied_sandbox = args.get("sandbox_dir")
    sandbox = (
        Path(supplied_sandbox).expanduser()
        if isinstance(supplied_sandbox, str) and supplied_sandbox.strip()
        else artifact_root
    )
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        target = sandbox / target
    try:
        target.resolve(strict=False).relative_to(artifact_root.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True

from __future__ import annotations

import json
import logging
import time
from typing import Any

from runtime.core.cerebrum.completion_receipt import build_completion_receipt
from runtime.core.cerebrum.react_context import _estimate_tokens
from runtime.core.cerebrum.react_parsing import _parse_action
from runtime.core.cerebrum.react_types import ReActStep
from runtime.platform.models import ParsedIntent, Step

_logger = logging.getLogger(__name__)

_FILE_SKILLS = frozenset(
    {
        "read_file",
        "list_cwd",
        "edit_text_file",
        "write_text_file",
        "edit_file",
        "multi_edit_file",
        "create_file",
        "delete_file",
    }
)
_WRITE_SKILLS = frozenset(
    {
        "edit_text_file",
        "edit_file",
        "multi_edit_file",
        "write_text_file",
        "create_file",
        "delete_file",
    }
)
_VERIFY_SKILLS = frozenset(
    {
        "exec_shell",
        "run_command",
    }
)
TOOL_OBSERVATION_MAX_CHARS = 16000
_PHASE_KEYWORDS = {
    "understand": {"read_file", "list_cwd", "recall"},
    "execute": {
        "edit_text_file",
        "edit_file",
        "multi_edit_file",
        "write_text_file",
        "create_file",
        "delete_file",
    },
    "verify": {"exec_shell", "run_command"},
}


def _output_indicates_command_failure(output: Any) -> bool:
    """Return True when a command-like tool ran but the command failed."""

    if not isinstance(output, dict):
        return False
    success = output.get("success")
    if isinstance(success, bool):
        return not success
    exit_code = output.get("exit_code")
    if isinstance(exit_code, int):
        return exit_code != 0
    return False


def _execute_action_via_beak(
    stack: Any,
    action_text: str,
    *,
    react_task_id: Any,
    react_step_counter: int,
    agent: Any = None,
    intent: ParsedIntent | None = None,
) -> tuple[str | None, Any]:
    executor = getattr(stack, "executor", None)
    if executor is None:
        return None, None

    parsed = _parse_action(action_text)
    if parsed is None:
        return None, None
    skill_name, args = parsed

    blocked_in_react = {"call_agent", "exit_plan_mode"}
    if skill_name in blocked_in_react:
        return (
            f"(禁止) 在 ReAct 模式下不能调用 '{skill_name}'。"
            "委派不是你应该做的 · 请直接使用原子工具（如 web_search / "
            "fetch_url / read_file / exec_shell 等）亲自完成任务 · "
            "下一轮请直接给出 Thought + 具体 Action，不要再调 "
            f"{skill_name}。"
        ), None

    registry = getattr(executor, "registry", None)
    if registry is None or not registry.has(skill_name):
        return (
            f"(工具未注册) 不存在名为 '{skill_name}' 的 skill。"
            "可用工具请参见 system prompt 顶部的目录 · "
            "请在下一轮选择一个已注册的工具重试。"
        ), None

    from runtime.platform.models import (
        ArmId,
        Budget,
        BudgetLimits,
        SkillId,
    )

    budget = Budget(
        task_id=react_task_id,
        limits=BudgetLimits(tokens=20_000, usd=0.20),
    )
    try:
        from contextlib import nullcontext

        from runtime.platform.process.session import Session, current_session, session_scope

        session_cm: Any = nullcontext()
        active_session = current_session()
        if (active_session is None or active_session.agent is None) and agent is not None:
            user_context = intent.user_context if intent is not None else {}
            metadata = dict(user_context.get("metadata") or {})
            for key in (
                "workspace_path",
                "mode",
                "capability_mode",
                "team_id",
                "agent_name",
            ):
                if key in user_context and key not in metadata:
                    metadata[key] = user_context[key]
            session_cm = session_scope(
                Session(
                    actor=getattr(intent, "actor", None) if intent is not None else None,
                    agent=agent,
                    thread_id=(
                        getattr(intent, "thread_id", None)
                        or getattr(intent, "conversation_id", None)
                        or user_context.get("thread_id")
                        or user_context.get("conversation_id")
                        if intent is not None
                        else None
                    ),
                    metadata=metadata,
                )
            )

        with session_cm:
            step = executor.execute_step(
                step_id=react_step_counter,
                node_id=f"react_n{react_step_counter}",
                sucker_id=SkillId(skill_name),
                args=args,
                caller="react_loop",
                task_id=react_task_id,
                arm_id=ArmId("react_arm"),
                budget=budget,
                actor=None,
            )
    except (ConnectionError, TimeoutError, OSError, TypeError, ValueError) as exc:
        _logger.warning("react_loop tool exec failed (%s): %s", skill_name, exc)
        return f"(工具执行异常) {type(exc).__name__}: {exc}", None

    result = step.result
    status = getattr(result, "status", "unknown")
    output = getattr(result, "output", None)
    if status != "success":
        err = getattr(result, "error_type", None) or status
        return (
            f"(工具失败) status={status} error={err}\n"
            "请在下一轮 Thought 中分析失败原因，然后换一种方式重试 · "
            "例如：换不同参数、换另一个工具、或直接用已有信息给出 Final Answer。"
        ), step
    if skill_name in _VERIFY_SKILLS and _output_indicates_command_failure(output):
        try:
            rendered = (
                output
                if isinstance(output, str)
                else json.dumps(
                    output,
                    ensure_ascii=False,
                    default=str,
                )
            )
        except (TypeError, ValueError):
            rendered = repr(output)
        if len(rendered) > TOOL_OBSERVATION_MAX_CHARS:
            rendered = rendered[:TOOL_OBSERVATION_MAX_CHARS] + "...(truncated)"
        return (
            "(tool failed) status=command_failed error=non_zero_exit\n"
            f"{rendered}\n"
            "Analyze the failure next, then fix it, change commands, or report the verification blocker."
        ), step
    try:
        rendered = (
            output
            if isinstance(output, str)
            else json.dumps(
                output,
                ensure_ascii=False,
                default=str,
            )
        )
    except (TypeError, ValueError):
        rendered = repr(output)
    if len(rendered) > TOOL_OBSERVATION_MAX_CHARS:
        rendered = rendered[:TOOL_OBSERVATION_MAX_CHARS] + "...(截断)"
    return (f"(real tool execution succeeded) {skill_name}\n{rendered}"), step


def _run_auto_diagnostics(stack: Any, workspace_path: str | None = None) -> str | None:
    try:
        from runtime.execution.suckers.verify_skills import detect_project, run_checks

        _wp = workspace_path
        if not _wp:
            _uc = getattr(getattr(stack, "intent", None), "user_context", None) or {}
            _wp = _uc.get("workspace_path") or _uc.get("metadata", {}).get("workspace_path")
        if not _wp:
            return None
        profile = detect_project(_wp)
        if profile.kind == "unknown":
            return None
        fast_checks = [
            c for c in profile.checks if c["name"] in ("typecheck", "check", "vet", "syntax")
        ]
        if not fast_checks:
            return None
        fast_profile = profile.__class__(
            kind=profile.kind,
            root=profile.root,
            checks=fast_checks[:1],
        )
        results = run_checks(fast_profile, timeout_per_check=30, max_output=2000)
        errors = [r for r in results if not r.passed]
        if not errors:
            return None
        parts: list[str] = []
        for r in errors:
            output = (r.stderr or r.stdout or "").strip()
            # A missing checker is an environment gap, not a code
            # failure — reporting it as one sends the model chasing
            # phantom errors (or pip-installing tools mid-task).
            if _output_indicates_missing_tool(output):
                continue
            if not output:
                parts.append(f"[{r.name}] 失败 (exit {r.exit_code})")
                continue
            if len(output) > 1500:
                output = output[:1500] + "\n...(截断)"
            parts.append(f"[{r.name}]\n{output}")
        return "\n\n".join(parts) if parts else None
    except (OSError, TypeError, ValueError):
        return None


def _output_indicates_missing_tool(output: str) -> bool:
    # Thin alias over the shared verify_skills helper so both
    # diagnostics paths agree on what "checker missing" looks like.
    from runtime.execution.suckers.verify_skills import output_indicates_missing_tool

    return output_indicates_missing_tool(output)


def _update_working_set(
    working_set: dict[str, dict[str, Any]],
    step: ReActStep,
    current_phase: str,
) -> None:

    parsed = _parse_action(step.action) if step.action else None
    if not parsed:
        return
    skill_name = parsed[0]
    args = parsed[1] or {}
    if skill_name not in _FILE_SKILLS:
        return
    path = args.get("path") or args.get("file_path") or args.get("filepath")
    if not path or not isinstance(path, str):
        return
    relevance = "editing" if skill_name in _WRITE_SKILLS else "related"
    now = time.time()
    existing = working_set.get(path)
    if existing:
        if skill_name in _WRITE_SKILLS:
            existing["relevance"] = "editing"
            existing["last_modified_at"] = now
        else:
            existing["last_read_at"] = now
    else:
        working_set[path] = {
            "path": path,
            "last_read_at": now,
            "last_modified_at": now if skill_name in _WRITE_SKILLS else 0.0,
            "tokens_estimated": _estimate_tokens(step.observation) if step.observation else 0,
            "relevance": relevance,
        }


def _detect_phase(step: ReActStep, current_phase: str) -> str:
    action = step.action.lower() if step.action else ""
    for phase, skills in _PHASE_KEYWORDS.items():
        if any(s in action for s in skills):
            if phase == "verify" and current_phase == "execute":
                return "verify"
            if phase == "execute" and current_phase == "understand":
                return "execute"
            if phase == "execute":
                return "execute"
    return current_phase


def _build_progress_summary(
    steps: list[ReActStep],
    working_set: dict[str, dict[str, Any]],
    current_phase: str,
) -> str:
    if not steps:
        return ""
    phase_labels = {"understand": "理解", "execute": "执行", "verify": "验证"}
    phase_label = phase_labels.get(current_phase, current_phase)
    files_read = [
        p for p, f in working_set.items() if f.get("relevance") in ("related", "referenced")
    ]
    files_modified = [p for p, f in working_set.items() if f.get("relevance") == "editing"]
    parts = [f"阶段: {phase_label}"]
    if files_read:
        parts.append(f"已读文件: {', '.join(files_read[:6])}")
    if files_modified:
        parts.append(f"已改文件: {', '.join(files_modified[:6])}")
    parts.append(f"已完成 {len(steps)} 轮推理")
    return " | ".join(parts)


def _build_research_progress_summary(steps: list[ReActStep]) -> str:
    """Build a public, non-chain-of-thought progress summary for non-code ReAct."""
    if not steps:
        return ""
    latest = steps[-1]
    action = (latest.action or "").lower()
    searches = [step for step in steps if "web_search" in (step.action or "").lower()]
    if "web_search" in action:
        return (
            f"已完成第 {len(searches)} 轮资料检索；正在根据搜索结果校准口径，"
            "继续补查市场规模、竞争格局、技术路线或用户需求里的缺口。"
        )
    if "fetch_url" in action:
        return "已打开具体来源核对细节；接下来会把来源信息并入结论。"
    if "none" in action or "final" in action:
        return "资料检索已收敛，正在综合分析并生成最终回复。"
    return f"已完成 {len(steps)} 轮处理；正在根据上一轮结果调整下一步。"


def _persist_react_trajectory(
    stack: Any,
    *,
    react_task_id: Any,
    beak_steps: list[Any],
    success: bool,
) -> None:
    if not beak_steps or react_task_id is None:
        return
    journal = getattr(stack, "journal", None)
    if journal is None or not hasattr(journal, "write_trajectory"):
        return

    try:
        from runtime.platform.models import (
            ArmId,
            CostEntry,
            Trajectory,
            TrajectoryOutcome,
        )
    except ImportError:
        return

    try:
        traj = Trajectory(
            task_id=react_task_id,
            arm_id=ArmId("react_arm"),
            strategy_id="react_loop",
            steps=list(beak_steps),
            outcome=TrajectoryOutcome(
                success=success,
                cost=CostEntry(),
            ),
        )
        journal.write_trajectory(traj, actor="react_loop")
    except Exception as exc:  # noqa: BLE001
        _logger.debug("react_loop trajectory persist skipped: %s", exc)
        return

    planner = getattr(stack, "planner", None)
    if planner is None:
        return

    if not success:
        learn_rules = getattr(planner, "learn_from_journal", None)
        if learn_rules is not None:
            try:
                learn_rules(journal)
            except Exception as exc:  # noqa: BLE001
                _logger.debug(
                    "react_loop learn_from_journal skipped: %s",
                    exc,
                )

    learn_memories = getattr(planner, "learn_memories_from_journal", None)
    if learn_memories is not None:
        try:
            learn_memories(journal)
        except Exception as exc:  # noqa: BLE001
            _logger.debug(
                "react_loop learn_memories_from_journal skipped: %s",
                exc,
            )

    _react_kg_throttle(stack, journal, planner)
    _react_recipe_throttle(journal, planner)


_KG_REFRESH_EVERY = 5
_KG_COUNTERS: dict[int, int] = {}


def _react_kg_throttle(stack: Any, journal: Any, planner: Any) -> None:
    learn_kg = getattr(planner, "learn_kg_from_journal", None)
    if learn_kg is None:
        return
    key = id(journal)
    cnt = _KG_COUNTERS.get(key, 0) + 1
    if cnt < _KG_REFRESH_EVERY:
        _KG_COUNTERS[key] = cnt
        return
    _KG_COUNTERS[key] = 0
    try:
        learn_kg(journal)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("react_loop learn_kg_from_journal skipped: %s", exc)


def _reset_kg_throttle_for_tests() -> None:
    _KG_COUNTERS.clear()


_RECIPE_REFRESH_EVERY = 5
_RECIPE_COUNTERS: dict[int, int] = {}


def _react_recipe_throttle(journal: Any, planner: Any) -> None:
    """Refresh the planner's recipe self-assessment from accumulating
    experience, throttled like the KG refresh.

    Without this the recipe verdict (which drives 'prefer a stronger model' +
    the losing-recipe warning) is only ever set at startup and never reflects
    how the current prompt recipe is actually performing this session. Parallels
    the per-turn rules/memory/KG learning already wired here.
    """
    assess = getattr(planner, "assess_recipe_from_journal", None)
    if assess is None:
        return
    key = id(journal)
    cnt = _RECIPE_COUNTERS.get(key, 0) + 1
    if cnt < _RECIPE_REFRESH_EVERY:
        _RECIPE_COUNTERS[key] = cnt
        return
    _RECIPE_COUNTERS[key] = 0
    try:
        assess(journal)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("react_loop assess_recipe_from_journal skipped: %s", exc)


def _reset_recipe_throttle_for_tests() -> None:
    _RECIPE_COUNTERS.clear()


# ── Tool-step observation shaping (moved from react_loop.py) ──────
# Helpers that classify finished beak steps (verification kind, command
# text, effective success), surface structured metadata on realtime
# ``tool_end`` events, and render background-task bookkeeping text.


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


_VERIFICATION_TOOL_KINDS: dict[str, str] = {
    "run_tests": "test",
    "lint_check": "lint",
    "format_code": "lint",
}


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


_SCOPED_ARTIFACT_WRITE_TOOLS = frozenset(
    {
        "write_text_file",
        "append_text_file",
        "edit_text_file",
        "edit_file",
        "multi_edit_file",
    }
)


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

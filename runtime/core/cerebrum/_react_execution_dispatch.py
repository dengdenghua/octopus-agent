"""Tool dispatch / execution helpers for the ReAct loop.

Extracted from ``react_execution.py``. Responsible for invoking a single
action through the beak executor: normalizing the React action into a
normalized tool call, running it, shaping the result, running
auto-diagnostics, and classifying command failures. Leaf module: imports
only from react_* leaf modules and the execution layers — never imports
react_loop or react_execution.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from runtime.core.cerebrum.react_parsing import _parse_action
from runtime.execution.tool_engine import (
    NormalizedToolCall,
    normalize_step_tool_result,
    normalize_tool_call,
    normalize_tool_result,
)
from runtime.platform.models import ParsedIntent

_logger = logging.getLogger(__name__)

_VERIFY_SKILLS = frozenset(
    {
        "exec_shell",
        "run_command",
    }
)
TOOL_OBSERVATION_MAX_CHARS = 16000

# dsh tool-result pruner master switch lives in tool_output_pruner.py;
# this local alias keeps the react-loop call sites (and their tests) on
# one name while the native tool bridge shares the same flag.
from runtime.execution.tool_engine.tool_output_pruner import (  # noqa: E402
    TOOL_RESULT_PRUNE_ENABLED as TOOL_RESULT_PRUNE_MIDDLE,
)
from runtime.execution.tool_engine.tool_output_spill import (  # noqa: E402
    TOOL_RESULT_SPILL_ENABLED,
)


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

    call = _normalized_tool_call_from_react_action(
        action_text,
        react_step_counter=react_step_counter,
    )
    if call is None:
        return None, None
    skill_name = call.name
    args = call.arguments

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
        # Distinguish "known but config-disabled" (e.g. web_search under
        # enable_web_skills=False) from "completely unknown" so the model
        # gets an actionable reason and stops retrying.
        try:
            from runtime.execution.all_skills import is_known_but_disabled_tool

            _hit, _group = is_known_but_disabled_tool(skill_name)
        except ImportError:  # pragma: no cover — defensive
            _hit, _group = False, None
        if _hit and _group:
            return (
                f"(工具未注册) {skill_name} 所属组 '{_group}' 被配置关闭"
                f"(enable_web_skills=false)。如需启用:在 config.local.yaml "
                f"设置 enable_web_skills: true 并重启后端,或调用 "
                f"POST /api/capabilities/enable 临时启用。当前请改用其他工具"
                f"或告知用户该能力不可用。"
            ), None
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
        user_context = intent.user_context if intent is not None else {}
        needs_context_session = bool(
            active_session is not None
            or agent is not None
            or user_context.get("workspace_path")
            or user_context.get("personal_workspace_path")
            or user_context.get("browser_operation_mode") is True
            or user_context.get("browser_regression_enabled") is True
        )
        if intent is not None and needs_context_session:
            active_metadata = getattr(active_session, "metadata", None)
            user_metadata = user_context.get("metadata")
            if isinstance(active_metadata, dict):
                metadata = active_metadata
                if isinstance(user_metadata, dict):
                    for key, value in user_metadata.items():
                        metadata.setdefault(key, value)
            elif isinstance(user_metadata, dict):
                metadata = user_metadata
            else:
                metadata = {}
                user_context["metadata"] = metadata
            surface_overrides = {
                "browser_operation_mode",
                "browser_surface",
                "runtime_surfaces",
                "chrome_operation_mode",
                "browser_regression_enabled",
                "browser_regression_preview_url",
            }
            for key in (
                "workspace_path",
                "workspace_scope",
                "personal_workspace_path",
                "personal_workspace_enabled",
                "attachment_read_roots",
                "mode",
                "capability_mode",
                "code_mode",
                "agent_mode",
                "personal_mode",
                "personal_instructions",
                "project_signals",
                "codex_mode",
                "goal_mode",
                "completion_policy",
                "mode_preset",
                "workflow_preset",
                "skill_pack_profile",
                "verification_policy",
                "browser_operation_mode",
                "browser_surface",
                "runtime_surfaces",
                "chrome_operation_mode",
                "browser_regression_enabled",
                "browser_regression_preview_url",
                "default_skill_packs",
                "default_plugins",
                "mode_contract",
                "sandbox_mode",
                "permission_mode",
                "approval_policy",
                "execution_environment",
                "team_id",
                "agent_name",
            ):
                if key in user_context and (key not in metadata or key in surface_overrides):
                    metadata[key] = user_context[key]
            session_agent = agent or getattr(active_session, "agent", None)
            session_cm = session_scope(
                Session(
                    actor=(
                        getattr(intent, "actor", None) or getattr(active_session, "actor", None)
                    ),
                    agent=session_agent,
                    thread_id=(
                        getattr(intent, "thread_id", None)
                        or getattr(intent, "conversation_id", None)
                        or user_context.get("thread_id")
                        or user_context.get("conversation_id")
                        or getattr(active_session, "thread_id", None)
                    ),
                    conversation_id=(
                        getattr(intent, "conversation_id", None)
                        or user_context.get("conversation_id")
                        or getattr(active_session, "conversation_id", None)
                    ),
                    turn_id=getattr(active_session, "turn_id", None) or str(react_task_id),
                    started_at=getattr(active_session, "started_at", None) or time.time(),
                    metadata=metadata,
                )
            )

        with session_cm:
            trusted_browser_loopback = bool(
                skill_name.startswith("browser_")
                and (
                    user_context.get("browser_operation_mode") is True
                    or user_context.get("browser_regression_enabled") is True
                )
            )
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
                trusted_browser_loopback=trusted_browser_loopback,
            )
    except (ConnectionError, TimeoutError, OSError, TypeError, ValueError) as exc:
        _logger.warning("react_loop tool exec failed (%s): %s", skill_name, exc)
        return f"(工具执行异常) {type(exc).__name__}: {exc}", None

    normalized_result = normalize_step_tool_result(
        step,
        origin="react_compat",
        max_chars=TOOL_OBSERVATION_MAX_CHARS,
        fallback_call=call,
        prune_middle=TOOL_RESULT_PRUNE_MIDDLE,
        spill_oversized=TOOL_RESULT_SPILL_ENABLED,
        tool_name=skill_name,
    )
    status = normalized_result.status
    output = normalized_result.output
    if skill_name in _VERIFY_SKILLS and _output_indicates_command_failure(output):
        command_result = normalize_tool_result(
            call,
            output,
            is_error=True,
            status="command_failed",
            error_type="non_zero_exit",
            origin="react_compat",
            max_chars=TOOL_OBSERVATION_MAX_CHARS,
            prune_middle=TOOL_RESULT_PRUNE_MIDDLE,
            spill_oversized=TOOL_RESULT_SPILL_ENABLED,
            tool_name=skill_name,
        )
        return (
            "(tool failed) status=command_failed error=non_zero_exit\n"
            f"{command_result.rendered}\n"
            "Analyze the failure next, then fix it, change commands, or report the verification blocker."
        ), step
    if status != "success" or normalized_result.is_error:
        err = normalized_result.error_type or (
            "structured_error" if normalized_result.is_error and status == "success" else status
        )
        detail = normalized_result.rendered.strip()
        detail_line = f"\n{detail}" if detail else ""
        return (
            f"(工具失败) status={status} error={err}{detail_line}\n"
            "请在下一轮 Thought 中分析失败原因，然后换一种方式重试 · "
            "例如：换不同参数、换另一个工具、或直接用已有信息给出 Final Answer。"
        ), step
    return (f"(real tool execution succeeded) {skill_name}\n{normalized_result.rendered}"), step


def _normalized_tool_call_from_react_action(
    action_text: str,
    *,
    react_step_counter: int,
) -> NormalizedToolCall | None:
    parsed = _parse_action(action_text)
    if parsed is None:
        return None
    skill_name, args = parsed
    return normalize_tool_call(
        {
            "id": f"react:{react_step_counter}",
            "name": skill_name,
            "arguments": args,
        },
        origin="react_compat",
    )


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

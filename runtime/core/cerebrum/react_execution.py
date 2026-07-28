from __future__ import annotations

import contextlib
import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Generator
from typing import Any

from runtime.core.cerebrum.completion_receipt import build_completion_receipt
from runtime.core.cerebrum.react_context import (
    _compress_context,
    _estimate_tokens,
    _prefetch_related_files,
    _serialize_messages_for_checkpoint,
    context_budget_tokens_for_model,
)
from runtime.core.cerebrum.react_convergence import (
    build_direct_answer_directive,
    constrain_explicit_read_scope,
    read_only_evidence_convergence,
)
from runtime.core.cerebrum.react_explicit_reads import (
    _bound_explicit_large_reads,
    _narrow_command_direct_answer,
)
from runtime.core.cerebrum.react_final_answer_guards import (
    _record_rejected_step,
)
from runtime.core.cerebrum.react_guards import (
    _code_semantic_followup_guard,
    _goal_requests_code_mutation,
)
from runtime.core.cerebrum.react_loop_state import (
    _LoopControl,
    _LoopState,
)
from runtime.core.cerebrum.react_parsing import (
    _has_code_verification,
    _has_successful_verification_observation,
    _is_code_write_step,
    _parse_action,
    _placeholder_observation,
    _summarize_observation,
)
from runtime.core.cerebrum.react_public_updates import (
    _observed_read_fallback_update,
    _runtime_fallback_public_update,
    _safe_public_update,
    _stream_public_evidence_narrative,
)
from runtime.core.cerebrum.react_types import REACT_OBSERVATION_FOLLOWUP, ReActStep
from runtime.core.cerebrum.todo_protocol import (
    _todo_completion_before_write_guard,
    _todo_prewrite_guard,
)
from runtime.execution.tool_engine import (
    NormalizedToolCall,
    normalize_step_tool_result,
    normalize_tool_call,
    normalize_tool_result,
)
from runtime.execution.tool_engine.tool_protocol import (
    normalize_tool_lifecycle_event,
    tool_lifecycle_event_to_react_event,
)
from runtime.platform.models import ParsedIntent, Step
from runtime.safety.hooks.tool_edge_hooks import (
    post_write_diagnostic_record,
)
from runtime.safety.validation.prompt_injection import (
    injection_taint_gates,
    is_untrusted_tool,
    mark_injection_taint,
    scan_for_injection,
    set_injection_gate_handled,
    wrap_untrusted_observation,
)

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
                "mode",
                "capability_mode",
                "code_mode",
                "agent_mode",
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
    phase_labels = {"understand": "补齐上下文", "execute": "处理线索", "verify": "确认结果"}
    phase_label = phase_labels.get(current_phase, current_phase)
    files_read = [
        p for p, f in working_set.items() if f.get("relevance") in ("related", "referenced")
    ]
    files_modified = [p for p, f in working_set.items() if f.get("relevance") == "editing"]
    parts = [phase_label]
    if files_read:
        parts.append(f"已查看 {', '.join(_public_progress_target(p) for p in files_read[:6])}")
    if files_modified:
        parts.append(f"已更新 {', '.join(_public_progress_target(p) for p in files_modified[:6])}")
    parts.append(f"第 {len(steps)} 轮")
    return " · ".join(part for part in parts if part)


def _public_progress_target(value: str) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip()
    if not clean:
        return ""
    parts = [part for part in re.split(r"[\\/]+", clean) if part]
    return parts[-1] if parts else clean


def _build_research_progress_summary(steps: list[ReActStep]) -> str:
    """Build a public, non-chain-of-thought progress summary for non-code ReAct."""
    if not steps:
        return ""
    latest = steps[-1]
    action = (latest.action or "").lower()
    searches = [step for step in steps if "web_search" in (step.action or "").lower()]
    if "web_search" in action:
        return f"已完成第 {len(searches)} 轮资料检索；正在收拢可用证据，继续补齐还不确定的缺口。"
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

    thread_id: str | None = None
    try:
        from runtime.platform.process.session import current_session

        _sess = current_session()
        thread_id = _sess.thread_id if _sess else None
    except Exception:  # noqa: BLE001 — thread tagging is best-effort
        thread_id = None

    try:
        traj = Trajectory(
            task_id=react_task_id,
            thread_id=thread_id,
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


# ── PHASE 6d · action dispatch + observation (Wave 2) ─────────────────
def _phase_6d_dispatch_and_observe(
    state: _LoopState,
    *,
    i: int,
    dispatch_parallel_actions: Callable[..., Any],
    write_tools: frozenset,
    result_checkpoint_is_meaningful: Callable[..., bool],
    should_accumulate_quiet_evidence: Callable[..., bool],
    quiet_evidence_checkpoint_due: Callable[..., bool],
    action_batch_fingerprint: Callable[..., str],
    deduplicate_actions: Callable[..., Any],
    per_action_outcomes: Callable[..., Any],
    retry_safe_affinity: Callable[..., bool],
    tool_call_succeeded: Callable[..., bool],
    observation_is_noop: Callable[[str], bool],
) -> Generator[dict[str, Any], None, _LoopControl]:
    """Dispatch the step's action(s), run approval/retry/cancel, observe.

    Moved verbatim from ``react_loop.py`` (PHASE 6d). Returns
    ``CONTINUE`` to proceed to PHASE 6e, ``NEXT_ITERATION`` for the
    approval-denied fast paths (Python ``continue`` in the original),
    or ``BREAK`` when the cancel token killed the tool mid-run.
    ``_dispatch_parallel_actions`` / ``_WRITE_TOOLS`` / the three
    quiet-evidence helpers / the five action-outcome helpers are
    injected because their home modules (react_parallel_dispatch,
    react_quiet_evidence, react_action_outcomes) import this one.
    """
    # Injected callables/constants under their original names.
    _dispatch_parallel_actions = dispatch_parallel_actions
    _WRITE_TOOLS = write_tools  # noqa: N806
    _result_checkpoint_is_meaningful = result_checkpoint_is_meaningful
    _should_accumulate_quiet_evidence = should_accumulate_quiet_evidence
    _quiet_evidence_checkpoint_due = quiet_evidence_checkpoint_due
    _action_batch_fingerprint = action_batch_fingerprint
    _deduplicate_actions = deduplicate_actions
    _per_action_outcomes = per_action_outcomes
    _retry_safe_affinity = retry_safe_affinity
    _tool_call_succeeded = tool_call_succeeded
    _observation_is_noop = observation_is_noop
    # Reference-typed aliases — mutations propagate to the main loop.
    step = state.step
    steps = state.steps
    executed_beak_steps = state.executed_beak_steps
    messages = state.messages
    _working_set = state.working_set
    stack = state.stack
    react_task_id = state.react_task_id
    executor = state.executor
    agent = state.agent
    intent = state.intent
    router = state.router
    thread_id = state.thread_id
    approval_provider = state.approval_provider
    output_chunk_sink = state.output_chunk_sink
    _metadata = state.metadata
    _effective_wp = state.effective_wp
    # Scalar pulls — original local names; pushed back in the finally.
    tools_active = state.tools_active
    effective_model = state.effective_model
    _current_phase = state.current_phase
    _is_code_mode = state.is_code_mode
    _todo_protocol_required = state.todo_protocol_required
    _todo_protocol_visible = state.todo_protocol_visible
    _read_only_turn = state.read_only_turn
    _is_goal_mode = state.is_goal_mode
    _observed_read_sequence = state.observed_read_sequence
    _ordered_result_handoffs = state.ordered_result_handoffs
    _realtime_public_orientation = state.realtime_public_orientation
    _realtime_public_narrative = state.realtime_public_narrative
    maybe_final = state.maybe_final
    terminated_reason = state.terminated_reason
    _evidence_convergence_active = state.evidence_convergence_active
    _force_convergence_next = state.force_convergence_next
    _consecutive_same_failed_actions = state.consecutive_same_failed_actions
    _last_failed_action_fingerprint = state.last_failed_action_fingerprint
    _consecutive_same_noop_actions = state.consecutive_same_noop_actions
    _last_noop_action_fingerprint = state.last_noop_action_fingerprint
    _green_verification_convergence_active = state.green_verification_convergence_active
    _green_convergence_todo_used = state.green_convergence_todo_used
    _result_handoff_ready = state.result_handoff_ready
    _last_public_update_key = state.last_public_update_key
    _saw_successful_code_write = state.saw_successful_code_write
    _clean_verification_rounds_after_write = state.clean_verification_rounds_after_write
    _quiet_evidence_steps = state.quiet_evidence_steps
    try:
        observation: str | None = step.observation or None
        resolved_name: str | None = None
        action_args: dict[str, Any] | None = None
        beak_step: Step | None = None
        tool_ok = False
        tool_action_requested = (
            tools_active and step.action and step.action.lower() not in {"none", "n/a", ""}
        )
        _duplicate_action_count = 0
        _explicit_read_scope_note = ""
        if tool_action_requested and len(step.actions) > 1:
            step.actions, _duplicate_action_count = _deduplicate_actions(step.actions)
            step.action = "; ".join(step.actions)
            tool_action_requested = bool(step.actions)
        if tool_action_requested:
            _candidate_actions = step.actions or [step.action]
            _candidate_actions = _bound_explicit_large_reads(
                goal=intent.normalized_goal,
                workspace_path=(_effective_wp if isinstance(_effective_wp, str) else None),
                actions=_candidate_actions,
                read_only=_read_only_turn,
            )
            step.actions = _candidate_actions
            step.action = "; ".join(_candidate_actions)
            _scope_constraint = constrain_explicit_read_scope(
                goal=intent.normalized_goal,
                steps=steps,
                actions=_candidate_actions,
                read_only=_read_only_turn,
                enforce_order=_observed_read_sequence,
            )
            if _scope_constraint is not None:
                step.actions = list(_scope_constraint.actions)
                step.action = "; ".join(step.actions)
                _explicit_read_scope_note = _scope_constraint.observation_note()
                tool_action_requested = bool(step.actions)
                if not tool_action_requested:
                    observation = _explicit_read_scope_note
                    step.observation = observation
                    maybe_final = None
        _current_action_fingerprint = ""
        _repeated_failure_skipped = False
        if tool_action_requested:
            _current_action_fingerprint = _action_batch_fingerprint(step.actions or [step.action])
            if (
                _consecutive_same_failed_actions >= 2
                and _current_action_fingerprint == _last_failed_action_fingerprint
            ):
                observation = (
                    "[repeated-failing-tool-skipped] The same tool call or ordered tool batch "
                    "with identical arguments already failed twice, so the runtime did not "
                    "execute it a third time. Treat the prior failure as definitive. Choose a different "
                    "action: for a missing file, create it with an allowed write tool; for "
                    "invalid arguments, correct them; otherwise use a different evidence source."
                )
                step.observation = observation
                step.action = ""
                step.actions = []
                tool_action_requested = False
                maybe_final = None
                _repeated_failure_skipped = True
        _repeated_noop_skipped = False
        if (
            tool_action_requested
            and not _repeated_failure_skipped
            and _consecutive_same_noop_actions >= 2
            and _current_action_fingerprint == _last_noop_action_fingerprint
        ):
                observation = (
                    "[repeated-noop-tool-skipped] The same tool call with identical "
                    "arguments already ran twice but produced no effect (ok=True but "
                    "empty/zero-count result). The runtime did not execute it a third "
                    "time. The arguments are likely under a wrong key — re-read the "
                    "tool description and re-issue with the correct parameter names."
                )
                step.observation = observation
                step.action = ""
                step.actions = []
                tool_action_requested = False
                maybe_final = None
                _repeated_noop_skipped = True
        if _evidence_convergence_active is not None and tool_action_requested:
            observation = (
                "The read-only evidence requested by the user is already complete, so "
                "the runtime did not execute this additional tool call. Answer now from "
                "the recorded observations; do not broaden the search or call another tool."
            )
            step.observation = observation
            step.action = ""
            step.actions = []
            tool_action_requested = False
            maybe_final = None
            _force_convergence_next = True
        if tool_action_requested:
            _todo_prewrite_message = _todo_prewrite_guard(
                step.actions or [step.action],
                steps,
                # Keep bounded inspections and one-command probes lightweight.
                # ReAct's plan-first gate applies to genuinely long or explicit
                # goal-mode work; the native tool bridge enforces its own
                # equivalent bootstrap from the shared protocol classifier.
                required=(
                    _todo_protocol_required
                    and (
                        _is_goal_mode
                        or "\n" in intent.normalized_goal
                        or len(intent.normalized_goal) >= 80
                    )
                ),
                visible=_todo_protocol_visible,
            )
            if _todo_prewrite_message:
                observation = _todo_prewrite_message
                step.observation = observation
                step.action = ""
                step.actions = []
                tool_action_requested = False
                maybe_final = None
        if _is_code_mode and tool_action_requested:
            _premature_todo_completion = _todo_completion_before_write_guard(
                step.actions or [step.action],
                steps,
                required=_goal_requests_code_mutation(intent.normalized_goal),
            )
            if _premature_todo_completion:
                observation = _premature_todo_completion
                step.observation = observation
                step.action = ""
                step.actions = []
                tool_action_requested = False
                maybe_final = None
        if _is_code_mode and tool_action_requested:
            # A deterministic source-level concurrency defect is stronger
            # evidence than another green/red probe.  Do not let providers
            # evade the repair instruction by cycling through pytest, lint,
            # typecheck, or shell variants.  Reads and actual code writes stay
            # available; a write+verify batch is also allowed because the
            # ordered outcome tracker will evaluate the post-repair checks.
            _semantic_repair = _code_semantic_followup_guard(
                steps,
                is_code_mode=True,
            )
            if _semantic_repair:
                _candidate_steps = [
                    ReActStep(iteration=i + 1, action=_candidate)
                    for _candidate in (step.actions or [step.action])
                ]
                _candidate_has_write = any(
                    _is_code_write_step(_candidate_step) for _candidate_step in _candidate_steps
                )
                _candidate_has_verifier = any(
                    _has_code_verification([_candidate_step])
                    for _candidate_step in _candidate_steps
                )
                if _candidate_has_verifier and not _candidate_has_write:
                    observation = (
                        "[semantic-repair-tool-skipped] A deterministic source defect "
                        "is still present in the latest source edit, so the runtime did not "
                        "execute another verifier or shell probe. Repair the source first.\n"
                        + _semantic_repair
                    )
                    step.observation = observation
                    step.action = ""
                    step.actions = []
                    tool_action_requested = False
                    maybe_final = None
                    _force_convergence_next = True
        if _green_verification_convergence_active and tool_action_requested:
            _candidate_actions = step.actions or [step.action]
            _candidate_names = []
            for _candidate_action in _candidate_actions:
                _candidate_parsed = _parse_action(_candidate_action)
                if _candidate_parsed is not None:
                    _candidate_names.append(_candidate_parsed[0])
            _allow_one_todo = (
                bool(_candidate_names)
                and all(name == "todo_write" for name in _candidate_names)
                and not _green_convergence_todo_used
            )
            if _allow_one_todo:
                _green_convergence_todo_used = True
            else:
                # Two independent green verification rounds after the latest
                # write are sufficient evidence. Re-running read/test/lint or
                # shell probes only burns the turn budget and can turn a valid
                # implementation into a timeout. Suppress those actions while
                # preserving one checklist-finalization opportunity.
                observation = (
                    "[redundant-tool-skipped] Two separate verification rounds are already green "
                    "and no code changed afterward. This tool call was not executed. Do not call "
                    "another tool. Emit `Final Answer:` now with the recorded test/lint evidence."
                )
                step.observation = observation
                step.action = ""
                step.actions = []
                tool_action_requested = False
                maybe_final = None
                _force_convergence_next = True

        # ``Update:`` is the explicit public checkpoint channel. Emit only
        # after the whole model turn has parsed, immediately before the tool
        # starts, so a partial ``Action:`` can never leak into conversation.
        # De-duplicate retries that repeat the same checkpoint verbatim.
        step.public_update = _safe_public_update(step.public_update)
        _checkpoint_actions = step.actions or [step.action]
        _prior_result_handoff = bool(
            _ordered_result_handoffs and _result_handoff_ready and tool_action_requested
        )
        if _prior_result_handoff:
            # The evidence narrator already gave the user the preceding fact
            # and next decision. Do not repeat a stochastic model paraphrase
            # immediately before the next tool row.
            step.public_update = ""
        if (
            not step.public_update
            and tool_action_requested
            and maybe_final is None
            and _realtime_public_orientation
            and not _prior_result_handoff
        ):
            try:
                _repaired_public_update = yield from _stream_public_evidence_narrative(
                    router,
                    model=effective_model,
                    goal=intent.normalized_goal,
                    step=step,
                    convergence=None,
                    iteration=i + 1,
                    previous_key=_last_public_update_key,
                    pending_action=True,
                )
            except Exception as exc:  # noqa: BLE001 — optional public narration
                _logger.warning("public action orientation repair failed: %s", exc)
                _repaired_public_update = ""
            if _repaired_public_update:
                step.public_update = _repaired_public_update
                _last_public_update_key = (
                    re.sub(r"\s+", " ", _repaired_public_update).strip().casefold()
                )
        _model_supplied_update = bool(step.public_update)
        # Force runtime fallback when the model omitted ``Update:`` so the
        # conversation never collapses into tool rows without a public beat.
        # ``public_evidence=True`` on the emitted delta lets the realtime
        # gateway pass it through (generic runtime prose is otherwise dropped)
        # so the bridge can still bind phase_id/progress_sequence/timeline_sequence.
        if (
            not _model_supplied_update
            and tool_action_requested
            and maybe_final is None
            and not _prior_result_handoff
        ):
            _fallback_update = _runtime_fallback_public_update(
                goal=intent.normalized_goal,
                step=step,
            )
            if _fallback_update:
                step.public_update = _fallback_update
        _public_update_key = re.sub(r"\s+", " ", step.public_update).strip().casefold()
        if (
            step.public_update
            and tool_action_requested
            and maybe_final is None
            and _public_update_key != _last_public_update_key
        ):
            yield {
                "type": "commentary_delta",
                "delta": step.public_update,
                "progress_source": "model" if _model_supplied_update else "runtime",
                "public_evidence": not _model_supplied_update,
                "start_new_segment": True,
                "iteration": i + 1,
            }
            _last_public_update_key = _public_update_key

        if tool_action_requested:
            _result_handoff_ready = False
            observation = None
            step.observation = ""
            maybe_final = None

        # Multi-action fast path: when the model emitted >1 tool call
        # in a single Action: block, dispatch them concurrently and
        # merge observations. Keeps the legacy single-action path
        # below untouched — that branch only runs when there is
        # exactly one action, preserving every existing
        # approval/retry/cancel/background-task behavior.
        _parallel_handled = False
        if tool_action_requested and len(step.actions) > 1:
            _parallel_obs, _parallel_results = yield from _dispatch_parallel_actions(
                step.actions,
                stack=stack,
                executor=executor,
                iteration=i + 1,
                react_task_id=react_task_id,
                agent=agent,
                intent=intent,
                beak_step_sink=executed_beak_steps,
            )
            if _parallel_obs is not None:
                observation = _parallel_obs
                step.observation = _parallel_obs
                step.action_results = _parallel_results
                tool_ok = all(r.get("ok") for r in _parallel_results)
                _parallel_handled = True

        if not _parallel_handled and not step.observation:
            will_attempt_tool = tool_action_requested
            if will_attempt_tool:
                assert executor is not None
                parsed = _parse_action(step.action)
                resolved_name = parsed[0] if parsed and executor.registry.has(parsed[0]) else None
                if resolved_name is not None:
                    assert parsed is not None
                    call_id = uuid.uuid4().hex[:12]
                    action_args = parsed[1] if isinstance(parsed[1], dict) else {}
                    _input_preview = action_args
                    _tool_started_at = time.monotonic()
                    yield tool_lifecycle_event_to_react_event(
                        normalize_tool_lifecycle_event(
                            "tool_start",
                            {
                                "tool_name": resolved_name,
                                "tool_call_id": call_id,
                                "iteration": i + 1,
                                "input_preview": _input_preview,
                            },
                            origin="react_compat",
                        )
                    )
                    _auto_approve = intent.user_context.get(
                        "auto_approve", False
                    ) or intent.flags.get("auto_approve", False)
                    from runtime.safety.approval.approval_gate import (
                        ApprovalRequest,
                        AutoDenyProvider,
                        approval_action_for_tool,
                    )

                    try:
                        from runtime.platform.process.session import current_session as _cs_ap

                        _sess_ap = _cs_ap()
                        _risk_policy_raw = (
                            (getattr(_sess_ap, "metadata", {}) or {}).get("approval_risk_policy")
                            if _sess_ap is not None
                            else None
                        )
                    except (AttributeError, TypeError):
                        _risk_policy_raw = None
                    _approval_risk, _approval_action, _approval_policy = approval_action_for_tool(
                        resolved_name,
                        str(_input_preview)[:500] if _input_preview else "",
                        policy=_risk_policy_raw,
                    )
                    _scoped_artifact_write = _is_scoped_artifact_write(
                        resolved_name,
                        _input_preview,
                    )
                    _permission_mode_value = str(
                        intent.user_context.get("permission_mode")
                        or _metadata.get("permission_mode")
                        or ""
                    ).lower()
                    _accept_edits_auto_approve = (
                        _permission_mode_value in {"acceptedits", "accept-edits"}
                        and resolved_name in _WRITE_TOOLS
                    )
                    # Injection taint gate (hard): if untrusted content
                    # carrying injection markers entered this turn, a
                    # risky tool can no longer auto-run — force it through
                    # human approval, overriding auto_approve and the
                    # scoped-write / accept-edits fast paths. This is the
                    # escalation from the in-context warning to an actual
                    # stop: a poisoned page can't drive an exec_shell /
                    # write / send behind the user's back. Gate at medium+
                    # so EXFILTRATION (egress tools = medium — the classic
                    # injection payload) is caught, not just destructive
                    # high-risk tools; only pure low-risk reads still
                    # auto-run after taint.
                    if injection_taint_gates() and _approval_risk.level in {
                        "medium",
                        "high",
                        "critical",
                    }:
                        _auto_approve = False
                        _scoped_artifact_write = False
                        _accept_edits_auto_approve = False
                        if _approval_action not in {"ask", "confirm", "deny"}:
                            _approval_action = "ask"
                        _approval_risk = _approval_risk.with_injection_taint()
                    if (
                        _approval_action == "deny"
                        and not _auto_approve
                        and not _scoped_artifact_write
                    ):
                        yield {
                            "type": "tool_end",
                            "tool_name": resolved_name,
                            "tool_call_id": call_id,
                            "iteration": i + 1,
                            "status": "rejected",
                            "output_preview": (
                                f"Denied by approval risk policy "
                                f"(risk={_approval_risk.level}: {_approval_risk.reason})"
                            ),
                            "duration_ms": int((time.monotonic() - _tool_started_at) * 1000),
                            "risk": _approval_risk.to_dict(),
                            "approval_action": _approval_action,
                            "approval_policy": _approval_policy.to_dict(),
                        }
                        observation = (
                            "(工具被风险策略拒绝) 此操作被 approval risk policy 拒绝，"
                            "请换一种方式或询问用户。"
                        )
                        _record_rejected_step(steps, messages, step, observation)
                        return _LoopControl.NEXT_ITERATION
                    if (
                        _approval_action in {"ask", "confirm"}
                        and not _auto_approve
                        and not _scoped_artifact_write
                        and not _accept_edits_auto_approve
                    ):
                        _provider = approval_provider or AutoDenyProvider()
                        _approval_detail = (
                            f"{resolved_name} wants to execute "
                            f"(risk={_approval_risk.level}: {_approval_risk.reason})"
                        )
                        yield {
                            "type": "tool_approval_request",
                            "tool_name": resolved_name,
                            "tool_call_id": call_id,
                            "args_preview": str(_input_preview)[:500] if _input_preview else "",
                            "detail": _approval_detail,
                            "risk": _approval_risk.to_dict(),
                            "approval_action": _approval_action,
                            "approval_policy": _approval_policy.to_dict(),
                        }
                        _decision = _provider.request(
                            ApprovalRequest(
                                thread_id=thread_id,
                                tool_name=resolved_name,
                                tool_call_id=call_id,
                                args_preview=str(_input_preview)[:500] if _input_preview else "",
                                detail=_approval_detail,
                            ),
                            timeout=120.0,
                        )
                        if not _decision.approved:
                            yield {
                                "type": "tool_end",
                                "tool_name": resolved_name,
                                "tool_call_id": call_id,
                                "iteration": i + 1,
                                "status": "rejected",
                                "output_preview": _decision.reason or "User denied tool execution",
                                "duration_ms": int((time.monotonic() - _tool_started_at) * 1000),
                            }
                            observation = (
                                "(工具被用户拒绝) 用户拒绝了此操作，请换一种方式或询问用户。"
                            )
                            _record_rejected_step(steps, messages, step, observation)
                            return _LoopControl.NEXT_ITERATION
                    if output_chunk_sink is not None:
                        from runtime.core.cerebrum.tool_output_sink import push_sink

                        _bound_call_id = call_id

                        def _local_sink(
                            stream: str,
                            chunk: str,
                            bound_call_id: str = _bound_call_id,
                        ) -> None:
                            output_chunk_sink(bound_call_id, stream, chunk)

                        def _sink_scope() -> Any:
                            return push_sink(_local_sink)
                    else:

                        def _sink_scope() -> Any:
                            return contextlib.nullcontext()

                    # This single-action path ran its own approval gate
                    # (incl. the injection-taint escalation) above, so tell
                    # the executor's chokepoint block this call was reviewed
                    # — otherwise it would double-block an approved tool.
                    with _sink_scope():
                        set_injection_gate_handled(True)
                        try:
                            observation, beak_step = _execute_action_via_beak(
                                stack,
                                step.action,
                                react_task_id=react_task_id,
                                react_step_counter=i + 1,
                                agent=agent,
                                intent=intent,
                            )
                        finally:
                            set_injection_gate_handled(False)
                    if beak_step is not None:
                        executed_beak_steps.append(beak_step)
                    # Tool may have been killed mid-run by the cancel
                    # token. Detect this so we can label the event and
                    # break the loop — skipping the retry and the next
                    # LLM round, which would both waste budget.
                    _ct_post = None
                    try:
                        from runtime.safety.approval.cancellation import (
                            current_cancellation_token,
                        )

                        _ct_post = current_cancellation_token()
                    except (ImportError, AttributeError, TypeError, UnboundLocalError):  # noqa: BLE001 — cancellation subsystem unavailable; post-tool cancel check skipped
                        pass
                    _was_cancelled = bool(_ct_post and _ct_post.is_cancelled)

                    tool_ok = _tool_call_succeeded(observation, beak_step)
                    if _was_cancelled:
                        yield {
                            "type": "tool_end",
                            "tool_name": resolved_name,
                            "tool_call_id": call_id,
                            "iteration": i + 1,
                            "status": "cancelled",
                            "output_preview": "(已取消) 用户中断了此操作。",
                            "duration_ms": int((time.monotonic() - _tool_started_at) * 1000),
                        }
                        terminated_reason = "cancelled"
                        return _LoopControl.BREAK
                    if not tool_ok and observation:
                        # C2: only auto-retry idempotent tools. Re-running a
                        # write/edit/exec/delete/dangerous tool whose first
                        # attempt already had side effects (a partial write, a
                        # shell command that ran before its result failed to
                        # parse) would double them, so non-idempotent failures
                        # surface to the model instead of silently re-executing.
                        _retry_affinity: list[str] | None = None
                        try:
                            if executor.registry.has(resolved_name):
                                _retry_affinity = executor.registry.get(
                                    resolved_name,
                                ).affinity
                        except (KeyError, AttributeError):
                            _retry_affinity = None
                        if not _retry_safe_affinity(_retry_affinity):
                            observation = observation + (
                                "\n[写/执行类工具失败，未自动重试以避免重复副作用；"
                                "请检查状态后再决定是否重试或换方法]"
                            )
                        else:
                            _logger.info(
                                "react_loop iter %d · tool %s failed, auto-retrying once",
                                i + 1,
                                resolved_name,
                            )
                            with _sink_scope():
                                set_injection_gate_handled(True)
                                try:
                                    retry_obs, retry_step = _execute_action_via_beak(
                                        stack,
                                        step.action,
                                        react_task_id=react_task_id,
                                        react_step_counter=i + 1,
                                        agent=agent,
                                        intent=intent,
                                    )
                                finally:
                                    set_injection_gate_handled(False)
                            if retry_step is not None:
                                executed_beak_steps.append(retry_step)
                            retry_ok = _tool_call_succeeded(retry_obs, retry_step)
                            if retry_ok:
                                observation = retry_obs
                                beak_step = retry_step
                                tool_ok = True
                            else:
                                observation = observation + "\n[自动重试仍失败，请换方法或调整参数]"
                    _background_task = (
                        _background_task_info_from_observation(observation)
                        if tool_ok and resolved_name in {"background_exec", "exec_shell"}
                        else None
                    )
                    if _background_task is not None:
                        yield {
                            "type": "tool_background",
                            "tool_name": resolved_name,
                            "tool_call_id": call_id,
                            "iteration": i + 1,
                            "status": "running",
                            "task_id": _background_task["task_id"],
                            "snapshot": _background_task,
                            "output_preview": (
                                _summarize_observation(observation)
                                if isinstance(observation, str) and observation
                                else observation
                            ),
                            "duration_ms": int((time.monotonic() - _tool_started_at) * 1000),
                        }
                    else:
                        yield tool_lifecycle_event_to_react_event(
                            normalize_tool_lifecycle_event(
                                "tool_end",
                                {
                                    "tool_name": resolved_name,
                                    "tool_call_id": call_id,
                                    "iteration": i + 1,
                                    "status": "success" if tool_ok else "error",
                                    "output_preview": (
                                        _summarize_observation(observation)
                                        if isinstance(observation, str) and observation
                                        else observation
                                    ),
                                    "duration_ms": int(
                                        (time.monotonic() - _tool_started_at) * 1000
                                    ),
                                    **_tool_event_extras_from_beak_step(beak_step, resolved_name),
                                },
                                origin="react_compat",
                            )
                        )
                    # Indirect prompt-injection defense (single-action
                    # path; mirrors _dispatch_parallel_actions): fence an
                    # external tool's output as data before it becomes the
                    # observation the model reads next.
                    if tool_ok and isinstance(observation, str) and observation:
                        _pi_affinity: list[str] | None = None
                        try:
                            if executor.registry.has(resolved_name):
                                _pi_affinity = executor.registry.get(
                                    resolved_name,
                                ).affinity
                        except (KeyError, AttributeError):
                            _pi_affinity = None
                        if is_untrusted_tool(resolved_name, _pi_affinity):
                            _pi_scan = scan_for_injection(observation)
                            observation = wrap_untrusted_observation(
                                observation,
                                source=resolved_name,
                                scan=_pi_scan,
                            )
                            if _pi_scan.flagged:
                                # Taint the turn → force human approval on a
                                # later high-risk tool (read at the gate).
                                mark_injection_taint(_pi_scan.severity)
                                _logger.warning(
                                    "prompt-injection markers in %s output "
                                    "(severity=%s, signals=%s)",
                                    resolved_name,
                                    _pi_scan.severity,
                                    ",".join(_pi_scan.labels),
                                )
                else:
                    observation, beak_step = _execute_action_via_beak(
                        stack,
                        step.action,
                        react_task_id=react_task_id,
                        react_step_counter=i + 1,
                        agent=agent,
                        intent=intent,
                    )
                    if beak_step is not None:
                        executed_beak_steps.append(beak_step)
            if observation is None:
                observation = _placeholder_observation(step.action)
            step.observation = observation

        _direct_command_answer = _narrow_command_direct_answer(
            goal=intent.normalized_goal,
            step=step,
            beak_step=beak_step,
            resolved_name=resolved_name,
            succeeded=tool_ok,
        )
        if _direct_command_answer is not None:
            maybe_final = _direct_command_answer

        if _duplicate_action_count and step.observation:
            step.observation += (
                "\n\n[duplicate-tools-collapsed] The provider emitted "
                f"{_duplicate_action_count} duplicate call(s) with identical tool arguments "
                "in one model round. The runtime executed each unique call once."
            )
        if (
            _explicit_read_scope_note
            and step.observation
            and _explicit_read_scope_note not in step.observation
        ):
            step.observation += "\n\n" + _explicit_read_scope_note
        if tool_action_requested and _current_action_fingerprint:
            if tool_ok:
                _last_failed_action_fingerprint = ""
                _consecutive_same_failed_actions = 0
            elif _current_action_fingerprint == _last_failed_action_fingerprint:
                _consecutive_same_failed_actions += 1
            else:
                _last_failed_action_fingerprint = _current_action_fingerprint
                _consecutive_same_failed_actions = 1
            # Silent no-op detection: the tool returned ok=True but the
            # observation shows an empty/zero-count result.  This catches
            # the "wrong key" failure mode where the handler swallows the
            # unknown argument and returns a valid-but-empty payload.
            _is_noop = tool_ok and _observation_is_noop(step.observation or "")
            if _is_noop and _current_action_fingerprint == _last_noop_action_fingerprint:
                _consecutive_same_noop_actions += 1
            elif _is_noop:
                _last_noop_action_fingerprint = _current_action_fingerprint
                _consecutive_same_noop_actions = 1
            else:
                _last_noop_action_fingerprint = ""
                _consecutive_same_noop_actions = 0
        elif not _repeated_failure_skipped and not _repeated_noop_skipped and tool_action_requested:
            _last_failed_action_fingerprint = ""
            _consecutive_same_failed_actions = 0
            _last_noop_action_fingerprint = ""
            _consecutive_same_noop_actions = 0

        # Common single/parallel tool outlet. Keep terminal evidence here so
        # a model round that launches lint + tests together is counted exactly
        # like one that launches either verifier alone.
        if _is_code_mode and tool_action_requested:
            _ordered_outcomes = _per_action_outcomes(step, default_ok=tool_ok)
            _last_successful_write_idx = -1
            for _outcome_idx, (_outcome_step, _outcome_ok) in enumerate(_ordered_outcomes):
                if _outcome_ok and _is_code_write_step(_outcome_step):
                    _last_successful_write_idx = _outcome_idx

            if _last_successful_write_idx >= 0:
                _saw_successful_code_write = True
                _clean_verification_rounds_after_write = 0
                _verification_outcomes = _ordered_outcomes[_last_successful_write_idx + 1 :]
            else:
                _verification_outcomes = _ordered_outcomes

            if _saw_successful_code_write:
                for _outcome_step, _outcome_ok in _verification_outcomes:
                    if not _has_code_verification([_outcome_step]):
                        continue
                    if _outcome_ok and _has_successful_verification_observation([_outcome_step]):
                        # Separate verifier calls in one serial multi-action
                        # batch are independent evidence rounds. Counting the
                        # whole batch once caused green code agents to run the
                        # same suite a dozen more times before convergence.
                        _clean_verification_rounds_after_write += 1
                    else:
                        _clean_verification_rounds_after_write = 0

            if (
                _clean_verification_rounds_after_write >= 2
                and not _green_verification_convergence_active
            ):
                _green_verification_convergence_active = True
                _force_convergence_next = True
                step.observation = (step.observation or observation or "") + (
                    "\n\n[green-verification-convergence]\n"
                    "Two clean verifier rounds completed after the latest successful code "
                    "write. The runtime has recorded terminal-quality evidence. Do not run "
                    "another verifier or shell probe. Update todo_write once if needed, then "
                    "emit Final Answer."
                )

        _evidence_convergence_became_active = False
        if _evidence_convergence_active is None and tool_action_requested:
            _evidence_convergence_active = read_only_evidence_convergence(
                goal=intent.normalized_goal,
                steps=steps + [step],
                read_only=_read_only_turn,
            )
            if _evidence_convergence_active is not None:
                _evidence_convergence_became_active = True
                _force_convergence_next = True
                _coverage = ", ".join(_evidence_convergence_active.covered[:6])
                _coverage_note = f" Covered evidence: {_coverage}." if _coverage else ""
                _direct_answer_directive = build_direct_answer_directive(
                    goal=intent.normalized_goal,
                    decision=_evidence_convergence_active,
                    steps=steps + [step],
                )
                step.observation = (step.observation or observation or "") + (
                    "\n\nThe user's requested read-only evidence is complete."
                    + _coverage_note
                    + " The next response must answer directly from these observations. "
                    "Do not call another tool or expand the investigation."
                    + (f"\n\n{_direct_answer_directive}" if _direct_answer_directive else "")
                )

        _meaningful_result_checkpoint = (
            tool_action_requested
            and observation
            and _result_checkpoint_is_meaningful(
                step.actions or [step.action],
                succeeded=tool_ok,
            )
        )
        _observed_result_checkpoint = bool(
            _ordered_result_handoffs
            and tool_action_requested
            and observation
            and (
                tool_ok
                or str(observation).lstrip().startswith("(real tool execution succeeded)")
                or not re.search(
                    r"(?:tool execution failed|file not found|no such file|"
                    r"does not exist|permission denied|读取失败|未找到|不存在)",
                    str(observation),
                    re.IGNORECASE,
                )
            )
        )
        if tool_action_requested and _should_accumulate_quiet_evidence(
            step,
            succeeded=tool_ok,
            observation=observation or "",
        ):
            _quiet_evidence_steps.append(step)
            # Keep prompts bounded when a provider repeatedly inspects new
            # files without producing a checkpoint of its own.
            _quiet_evidence_steps = _quiet_evidence_steps[-4:]
        _quiet_evidence_due = _quiet_evidence_checkpoint_due(_quiet_evidence_steps)
        _model_result_update = ""
        if _observed_result_checkpoint and maybe_final is None:
            # Ordered read tasks need a guaranteed conversational beat between
            # batches. A second model call can be slow, return SKIP, or finish
            # after the next action is already visible. Publish the completed
            # read receipt immediately; it is factual, privacy-safe, and gives
            # the user a stable fact -> next action rhythm.
            _model_result_update = _safe_public_update(
                _observed_read_fallback_update(
                    goal=intent.normalized_goal,
                    step=step,
                )
            )
            if _model_result_update:
                yield {
                    "type": "commentary_delta",
                    "delta": _model_result_update,
                    "progress_source": "runtime",
                    "public_evidence": True,
                    "start_new_segment": True,
                    "iteration": i + 1,
                }
        if (
            (_realtime_public_narrative or _ordered_result_handoffs)
            and maybe_final is None
            and not _model_result_update
            and (not _model_supplied_update or _quiet_evidence_due or _observed_result_checkpoint)
            and (
                _meaningful_result_checkpoint
                or _observed_result_checkpoint
                or _quiet_evidence_due
                or (
                    _evidence_convergence_became_active
                    and _evidence_convergence_active is not None
                    and len(_evidence_convergence_active.covered) > 1
                )
            )
        ):
            try:
                _model_result_update = yield from _stream_public_evidence_narrative(
                    router,
                    model=effective_model,
                    goal=intent.normalized_goal,
                    step=step,
                    convergence=(
                        _evidence_convergence_active
                        if _evidence_convergence_became_active
                        else None
                    ),
                    evidence_steps=(
                        _quiet_evidence_steps if _quiet_evidence_due else steps + [step]
                    ),
                    iteration=i + 1,
                    previous_key=_last_public_update_key,
                    succeeded=tool_ok,
                )
            except Exception as exc:  # noqa: BLE001 — optional public narration
                _logger.warning("public evidence narration failed: %s", exc)
                _model_result_update = ""
        if _quiet_evidence_due:
            # Whether the narrator spoke or the deterministic read receipt was
            # used, this evidence window has been considered. Start a fresh
            # window so long read-only tasks get bounded conversational beats.
            _quiet_evidence_steps = []
        _model_result_update_key = re.sub(r"\s+", " ", _model_result_update).strip().casefold()
        if _model_result_update and _model_result_update_key != _last_public_update_key:
            _last_public_update_key = _model_result_update_key
            if _ordered_result_handoffs:
                _result_handoff_ready = True

        if _is_code_mode and observation and _current_phase in ("execute", "verify"):
            _write_tools = frozenset(
                {
                    "write_text_file",
                    "edit_file",
                    "multi_edit_file",
                    "edit_text_file",
                    "edit_code",
                    "str_replace",
                    "write_file",
                    "create_file",
                }
            )
            if resolved_name in _write_tools and tool_ok:
                _diag_record = post_write_diagnostic_record(
                    resolved_name,
                    action_args or {},
                    action_args or {},
                    workspace_path=_effective_wp if isinstance(_effective_wp, str) else "",
                )
                _diag_status = str(_diag_record.get("status") or "skipped")
                _diag_reason = str(_diag_record.get("reason") or "")
                _diag_target = str(_diag_record.get("target") or "")
                _diag_text = f"{_diag_status}: {_diag_reason}" + (
                    f" · {_diag_target}" if _diag_target else ""
                )
                step.observation = (
                    (step.observation or observation) + "\n\n[写后诊断记录]\n" + _diag_text
                )
                _auto_diag = _run_auto_diagnostics(
                    stack,
                    workspace_path=_effective_wp if isinstance(_effective_wp, str) else None,
                )
                if _auto_diag:
                    step.observation = (
                        (step.observation or observation) + "\n\n[自动诊断结果]\n" + _auto_diag
                    )
                _prefetch = _prefetch_related_files(step.action, _working_set)
                if _prefetch:
                    step.observation = (
                        (step.observation or observation) + "\n\n[关联文件预读]\n" + _prefetch
                    )

        return _LoopControl.CONTINUE
    finally:
        state.maybe_final = maybe_final
        state.terminated_reason = terminated_reason
        state.evidence_convergence_active = _evidence_convergence_active
        state.force_convergence_next = _force_convergence_next
        state.consecutive_same_failed_actions = _consecutive_same_failed_actions
        state.last_failed_action_fingerprint = _last_failed_action_fingerprint
        state.consecutive_same_noop_actions = _consecutive_same_noop_actions
        state.last_noop_action_fingerprint = _last_noop_action_fingerprint
        state.green_verification_convergence_active = _green_verification_convergence_active
        state.green_convergence_todo_used = _green_convergence_todo_used
        state.result_handoff_ready = _result_handoff_ready
        state.last_public_update_key = _last_public_update_key
        state.saw_successful_code_write = _saw_successful_code_write
        state.clean_verification_rounds_after_write = _clean_verification_rounds_after_write
        state.quiet_evidence_steps = _quiet_evidence_steps


def _phase_6g_housekeeping(state: _LoopState, *, i: int, max_iterations: int) -> _LoopControl:
    """Loop-tail housekeeping: plan-exit, checkpoints, msg append, compress.

    Moved verbatim from ``react_loop.py`` (PHASE 6g). Returns ``BREAK``
    when a final answer terminates the turn (Python ``break`` in the
    original), otherwise ``CONTINUE`` so the loop proceeds to the next
    iteration. No yields — plain function, not a generator.
    """
    from runtime.platform.models.llm import Message

    # Reference-typed aliases — mutations propagate to the main loop.
    steps = state.steps
    final_answer_segments = state.final_answer_segments
    messages = state.messages
    _working_set = state.working_set
    stack = state.stack
    react_task_id = state.react_task_id
    router = state.router
    thread_id = state.thread_id
    resp = state.resp
    step = state.step
    _pause = state.pause_controller
    # Scalar pulls — original local names; pushed back in the finally.
    planning_mode = state.planning_mode
    enable_tools = state.enable_tools
    executor = state.executor
    tools_active = state.tools_active
    maybe_final = state.maybe_final
    final_answer = state.final_answer
    final_answer_emitted = state.final_answer_emitted
    terminated_reason = state.terminated_reason
    effective_model = state.effective_model
    _current_phase = state.current_phase
    _progress_summary = state.progress_summary
    _force_convergence_next = state.force_convergence_next
    _length_limit_should_continue = state.length_limit_should_continue
    _is_code_mode = state.is_code_mode
    _native_mode = state.native_mode
    _observed_read_sequence = state.observed_read_sequence
    _length_limited = state.length_limited
    _final_delta_emitted_this_iteration = state.final_delta_emitted_this_iteration
    text = state.text
    _agent_id_for_pause = state.agent_id_for_pause
    try:
        # Mid-turn plan exit: model called exit_plan_mode and user approved.
        # Switch from "plan only" to "execute" without ending the turn.
        if planning_mode:
            try:
                from runtime.platform.process.session import current_session as _cs_plan

                _session_obj = _cs_plan()
            except (ImportError, AttributeError):  # noqa: BLE001
                _session_obj = None
            if (
                _session_obj is not None
                and _session_obj.metadata is not None
                and _session_obj.metadata.pop("_plan_mode_exit_approved", False)
            ):
                planning_mode = False
                enable_tools = True
                executor = getattr(stack, "executor", None)
                tools_active = executor is not None
                _logger.info(
                    "plan_mode exited mid-turn; continuing execution in same turn",
                )

        if _is_code_mode and step.action and step.action.lower() not in {"none", "n/a", ""}:
            _update_working_set(_working_set, step, _current_phase)
            _current_phase = _detect_phase(step, _current_phase)
            _progress_summary = _build_progress_summary(steps, _working_set, _current_phase)

        _has_real_observation = bool(step.observation and step.observation != "N/A")
        _has_response_tool_calls = bool(getattr(resp, "tool_calls", None))
        _length_limit_should_continue = _length_limited and not (
            _has_response_tool_calls or _has_real_observation
        )
        _checkpoint_has_final = maybe_final is not None and not _length_limit_should_continue
        if react_task_id is not None and _checkpoint_has_final:
            _ckpt_journal = getattr(stack, "journal", None)
            if _ckpt_journal is not None and hasattr(_ckpt_journal, "write_react_checkpoint"):
                try:
                    from runtime.platform.models import ArmId

                    _ckpt_journal.write_react_checkpoint(
                        react_task_id,
                        arm_id=ArmId("react_arm"),
                        iteration_completed=i + 1,
                        max_iterations=max_iterations,
                        messages_snapshot=_serialize_messages_for_checkpoint(messages),
                        steps_snapshot=[
                            {
                                "iteration": s.iteration,
                                "thought": s.thought,
                                "public_update": s.public_update,
                                "action": s.action,
                                "observation": s.observation,
                            }
                            for s in steps
                        ],
                        has_final_answer=_checkpoint_has_final,
                        final_answer=maybe_final if _checkpoint_has_final else "",
                        working_set_snapshot=list(_working_set.values()),
                        progress_summary=_progress_summary,
                        current_phase=_current_phase,
                    )
                except (OSError, TypeError):
                    _logger.debug("checkpoint write failed", exc_info=True)
        if maybe_final and _length_limit_should_continue:
            final_answer_segments.append(maybe_final)
            maybe_final = None

        if maybe_final:
            if final_answer_segments:
                final_answer = "".join(final_answer_segments + [maybe_final])
                final_answer_segments.clear()
            else:
                final_answer = maybe_final
            # A guarded long-task answer may have been intentionally buffered
            # until every completion gate passed.  Only suppress the final
            # emitter when this iteration actually yielded answer text.
            final_answer_emitted = _final_delta_emitted_this_iteration
            terminated_reason = "final_answer"
            return _LoopControl.BREAK

        if (
            react_task_id is not None
            and max_iterations >= 15
            and (max_iterations - (i + 1)) <= 3
            and not _pause.is_pause_requested(str(react_task_id))
        ):
            remaining = max_iterations - (i + 1)
            _logger.info(
                "react_loop auto-pause at iter %d · task %s · %d left · "
                "will checkpoint next loop top",
                i + 1,
                react_task_id,
                remaining,
            )
            _pause.request_pause(
                task_id=str(react_task_id),
                reason="iteration_near_limit",
                requested_by="system",
                note=(
                    f"自动暂停 · 已跑 {i + 1}/{max_iterations} 轮 · "
                    f"剩余 {remaining} 轮 · 点继续并加预算可接续"
                ),
                thread_id=thread_id or "",
                agent_id=_agent_id_for_pause,
            )

        _assistant_content = text
        if _native_mode and not _assistant_content and step.action:
            # Native tool-use turns often carry no prose — record the
            # synthesised action so the history isn't an (API-invalid) empty
            # assistant message and the model can see what it just called.
            _assistant_content = step.action
        messages.append(Message(role="assistant", content=_assistant_content))
        # Length-limit continuation. When the upstream model truncated
        # its response (finish_reason=="length" / "max_tokens" / etc.)
        # the assistant message we just appended is mid-sentence — the
        # model itself doesn't know it stopped early, so on the NEXT
        # iteration it will either repeat work or give up and write a
        # short summary. Inject a user message asking it to continue
        # exactly where it left off so long-form generation (research
        # reports, code files, plans) can finish across multiple
        # iterations without the user seeing a half-finished doc.
        if _length_limit_should_continue:
            _code_action_recovery = _is_code_mode and not final_answer_segments
            if _code_action_recovery:
                _force_convergence_next = True
                _length_recovery_prompt = (
                    "Your previous code-task response hit the output limit before producing an "
                    "executable action. Do not continue or repeat the prose analysis. Extended "
                    "thinking is disabled for this recovery round. Emit exactly one concrete next "
                    "Action: skill_name({JSON}) now; prefer the required source/test mutation, or "
                    "the smallest targeted verifier if the implementation is already written."
                )
            else:
                _length_recovery_prompt = (
                    "Your previous response was cut off by the output "
                    "length limit. Continue exactly where it stopped — "
                    "do NOT repeat earlier text, do NOT restart the "
                    "report, do NOT switch to writing a summary or "
                    "calling todo_write. Resume from the exact "
                    "character you stopped at and finish every "
                    "remaining section."
                )
            messages.append(
                Message(
                    role="user",
                    content=_length_recovery_prompt,
                )
            )
            _logger.info(
                "react_loop iter %d · finish_reason=length, injecting continue prompt",
                i + 1,
            )
        elif step.observation and step.observation != "N/A":
            # TokenJuice: compress the observation before it enters
            # the message stream so the next LLM round sees a leaner
            # version. The full observation is preserved in
            # step.observation for journal / display / guards. Off
            # by default — opt in via OCTOPUS_TOKEN_JUICE=1.
            _obs_for_model = step.observation
            try:
                from runtime.core.cerebrum.token_juicer import (
                    is_enabled as _juice_enabled,
                )
                from runtime.core.cerebrum.token_juicer import (
                    juice as _juice,
                )

                if _observed_read_sequence or _juice_enabled():
                    _juiced, _stats = _juice(
                        step.observation,
                        max_chars=6000,
                    )
                    if _stats.passes:
                        _obs_for_model = _juiced
                        (_logger.info if _observed_read_sequence else _logger.debug)(
                            "token_juice iter %d · %d→%d chars (%.1f%% saved) passes=%s",
                            i + 1,
                            _stats.before,
                            _stats.after,
                            (1 - _stats.ratio) * 100,
                            ",".join(_stats.passes),
                        )
            except (ImportError, ValueError, TypeError):
                _logger.debug("token_juice unavailable", exc_info=True)
            messages.append(
                Message(
                    role="user",
                    content=(f"Observation: {_obs_for_model}\n\n{REACT_OBSERVATION_FOLLOWUP}"),
                )
            )

        messages = _compress_context(
            messages,
            max_tokens=context_budget_tokens_for_model(effective_model),
            router=router,
            model=effective_model,
            is_code_mode=_is_code_mode,
        )

        with contextlib.suppress(Exception):
            _pause.update_active_iteration(str(react_task_id), i + 1)
        return _LoopControl.CONTINUE
    finally:
        state.planning_mode = planning_mode
        state.enable_tools = enable_tools
        state.executor = executor
        state.tools_active = tools_active
        state.maybe_final = maybe_final
        state.final_answer = final_answer
        state.final_answer_emitted = final_answer_emitted
        state.terminated_reason = terminated_reason
        state.current_phase = _current_phase
        state.progress_summary = _progress_summary
        state.force_convergence_next = _force_convergence_next
        state.length_limit_should_continue = _length_limit_should_continue
        state.messages = messages

from __future__ import annotations

import json
import logging
import time
from typing import Any

from runtime.core.cerebrum.react_context import _estimate_tokens
from runtime.core.cerebrum.react_parsing import _parse_action
from runtime.core.cerebrum.react_types import ReActStep
from runtime.platform.models import ParsedIntent

_logger = logging.getLogger(__name__)

_FILE_SKILLS = frozenset({
    "read_file", "list_cwd", "edit_text_file", "write_text_file",
    "edit_file", "multi_edit_file", "create_file", "delete_file",
})
_WRITE_SKILLS = frozenset({
    "edit_text_file", "edit_file", "multi_edit_file",
    "write_text_file", "create_file", "delete_file",
})
_VERIFY_SKILLS = frozenset({
    "exec_shell", "run_command",
})
TOOL_OBSERVATION_MAX_CHARS = 16000
_PHASE_KEYWORDS = {
    "understand": {"read_file", "list_cwd", "recall"},
    "execute": {
        "edit_text_file", "edit_file", "multi_edit_file",
        "write_text_file", "create_file", "delete_file",
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
            session_cm = session_scope(Session(
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
            ))

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
            rendered = output if isinstance(output, str) else json.dumps(
                output, ensure_ascii=False, default=str,
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
        rendered = output if isinstance(output, str) else json.dumps(
            output, ensure_ascii=False, default=str,
        )
    except (TypeError, ValueError):
        rendered = repr(output)
    if len(rendered) > TOOL_OBSERVATION_MAX_CHARS:
        rendered = rendered[:TOOL_OBSERVATION_MAX_CHARS] + "...(截断)"
    return (
        f"(real tool execution succeeded) {skill_name}\n"
        f"{rendered}"
    ), step


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
            c for c in profile.checks
            if c["name"] in ("typecheck", "check", "vet", "syntax")
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


_TOOL_MISSING_MARKERS = (
    "no module named",
    "command not found",
    "not recognized as an internal or external command",
    "could not determine executable to run",
    "npx: not found",
    "enoent",
)


def _output_indicates_missing_tool(output: str) -> bool:
    lowered = output.lower()
    return any(marker in lowered for marker in _TOOL_MISSING_MARKERS)


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
        p for p, f in working_set.items()
        if f.get("relevance") in ("related", "referenced")
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
    searches = [
        step for step in steps
        if "web_search" in (step.action or "").lower()
    ]
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
                    "react_loop learn_from_journal skipped: %s", exc,
                )

    learn_memories = getattr(planner, "learn_memories_from_journal", None)
    if learn_memories is not None:
        try:
            learn_memories(journal)
        except Exception as exc:  # noqa: BLE001
            _logger.debug(
                "react_loop learn_memories_from_journal skipped: %s", exc,
            )

    _react_kg_throttle(stack, journal, planner)


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

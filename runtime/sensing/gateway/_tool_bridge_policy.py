"""Goal / scope / budget / shell policy helpers for the native tool loop.

Extracted from ``tool_bridge.py`` (the Claude-native agentic loop). This
satellite owns the constants and helpers that decide how many tool rounds
a task may use, which tool specs survive workspace-contract filtering, when
a task is a code / security change, and how shell commands are classified
(verification / terminal-verifier / mutation).

The parent ``tool_bridge`` module re-exports every name here so existing
importers and tests are unchanged.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from runtime.platform.models import ParsedIntent
from runtime.sensing.model_router.models import ToolCall

_logger = logging.getLogger("octopus.agentic")


# Hard ceiling on the back-and-forth between model and executor.
# Keep it intentionally high for long research/code tasks. The loop
# still gets periodic reflection nudges, and if it ever hits the cap
# we force one no-tool checkpoint pass that asks the user whether to
# continue or synthesize a report from the collected evidence.
MAX_TOOL_ROUNDS = 300

# Production turns should almost never approach the hard ceiling above.  Give
# each task a smaller evidence-gathering budget, then force one tools-disabled
# synthesis round.  The high ceiling remains as an emergency guard for truly
# unusual workflows and for backwards-compatible explicit overrides.
NARROW_WEB_RESEARCH_ROUND_BUDGET = 8
WEB_RESEARCH_ROUND_BUDGET = 48
READ_ONLY_ROUND_BUDGET = 80
DEFAULT_TOOL_ROUND_BUDGET = 96
CODE_CHANGE_ROUND_BUDGET = 160

# Reflection nudge cadence: every REFLECTION_INTERVAL rounds the model is
# asked to review whether it can wrap up or should keep going.
REFLECTION_INTERVAL = 10

# Upper bound for a single tool_result content block (chars).
TOOL_OUTPUT_MAX_CHARS = 16000

# Single-turn tool concurrency (octopus optimisation, lane B).
# When the model emits N independent tool_use blocks in one
# assistant message (e.g. Read(a) + Read(b) + Glob(...)), we can
# execute them in parallel instead of one-by-one, cutting wall-clock
# time roughly to max(times) instead of sum(times). Bounded so a
# pathological turn can't spin up hundreds of threads.
#
# We default this OFF when:
#   * Only one tool call this round (no concurrency to gain anyway).
#   * Calls have a sequencing tool like ``todo_write`` mixed in
#     (todo_write is a state-machine op the model expects to land
#     before subsequent reasoning).
#   * Stack opts out via ``stack.metadata['parallel_tool_use']=False``.
#
# Anything else: dispatch to a thread pool. Each tool call sees its
# own session/thread context (we re-enter the parent's contextvars
# so executor scope/cwd injection still works).
PARALLEL_TOOL_USE_DEFAULT = True
PARALLEL_TOOL_USE_MAX_WORKERS = 8

# Tools whose presence in the round forces serial execution. These
# are state-machine operations that downstream actions in the same
# round may semantically depend on (or that have UI side effects
# the model expects to land in narrative order).
_SERIAL_BARRIER_TOOLS: frozenset[str] = frozenset(
    {
        "todo_write",
        "use_capability",
        "exit_plan_mode",
        "update_soul",
        "revert_soul",
    }
)

_SCOPE_SENSITIVE_AFFINITIES = frozenset(
    {
        "file",
        "shell",
        "exec",
        "write",
        "edit",
        "delete",
        "dangerous",
        "quality",
        "test",
        "lint",
        "format",
    }
)

_CODE_MUTATION_TOOLS = frozenset(
    {
        "write_text_file",
        "append_text_file",
        "edit_text_file",
        "edit_file",
        "multi_edit_file",
        "format_code",
    }
)
_CODE_VERIFICATION_TOOLS = frozenset({"run_tests"})
_CODE_TERMINAL_VERIFIER_TOOLS = frozenset({"run_tests", "lint_check"})

_NO_LOCAL_ACCESS_SAFE_TOOLS = frozenset(
    {
        "todo_read",
        "todo_write",
        "search_skills",
        "query_skill",
        "web_search",
        "search_web",
        "web_fetch",
        "fetch_url",
        "read_url",
    }
)

_READ_ONLY_BLOCKED_TOOLS = frozenset(
    {
        "write_text_file",
        "append_text_file",
        "edit_text_file",
        "edit_file",
        "multi_edit_file",
        "format_code",
        "exec_shell",
        "run_tests",
        "update_soul",
        "revert_soul",
        "remember",
        "note_user",
        "diary_write",
    }
)


def _goal_forbids_local_workspace_access(value: str) -> bool:
    """Whether the user explicitly prohibited even reading local files."""
    text = " ".join(str(value or "").strip().split()).lower()
    return bool(
        re.search(
            r"(?:不要|禁止|不得|不可|严禁|不允许)\s*"
            r"(?:读取|访问|查看|检查|分析)"
            r"[^。；;\n]{0,48}(?:本地|项目|仓库|工作区)"
            r"[^。；;\n]{0,24}(?:文件|代码|目录)",
            text,
        )
        or re.search(
            r"\b(?:do\s+not|don't|never|must\s+not)\s+"
            r"(?:read|access|inspect|analy[sz]e)\b"
            r"[^.\n]{0,64}\b(?:local|workspace|repository|repo|project)\b"
            r"[^.\n]{0,32}\b(?:files?|code|director(?:y|ies))\b",
            text,
        )
    )


def _goal_is_read_only(value: str) -> bool:
    text = str(value or "").lower()
    return bool(
        re.search(r"\bread[- ]only\b", text)
        or re.search(
            r"\b(?:do\s+not|don't|must\s+not|never)\s+"
            r"(?:modify|change|edit|write|create|update|add|remove|delete|patch)",
            text,
        )
        or re.search(
            r"(?:只读|(?:不要|严禁|禁止|不得|不可|不允许)\s*"
            r"(?:修改|改动|更改|编辑|写入|创建|新增|添加|删除|提交))",
            text,
        )
    )


def _goal_is_narrow_single_source_research(value: str) -> bool:
    """Whether the request asks for one small remote fact and one source."""
    text = " ".join(str(value or "").strip().split()).lower()
    source_marker = bool(
        re.search(r"(?:一个|1\s*个)\s*(?:官方|可靠)?\s*(?:来源|网页|页面)", text)
        or re.search(r"\b(?:one|single)\s+(?:official\s+)?source\b", text)
    )
    concise_marker = bool(
        re.search(r"(?:一句|一段|简短|一句话|结论)", text)
        or re.search(r"\b(?:one sentence|brief|concise|short conclusion)\b", text)
    )
    return source_marker and concise_marker


def _native_tool_round_budget(
    goal: str,
    *,
    workspace_contract: str | None,
    code_change_task: bool,
) -> int:
    """Choose a bounded tool budget before a tools-disabled synthesis pass.

    The budget constants are resolved live from the parent ``tool_bridge``
    module so tests that ``monkeypatch.setattr(tool_bridge,
    "NARROW_WEB_RESEARCH_ROUND_BUDGET", ...)`` (or the other budget
    constants / ``MAX_TOOL_ROUNDS``) take effect here.
    """
    from runtime.sensing.gateway import tool_bridge as _tb

    max_rounds = _tb.MAX_TOOL_ROUNDS
    raw_override = os.environ.get("OCTOPUS_NATIVE_TOOL_ROUND_BUDGET", "").strip()
    if raw_override:
        try:
            return max(1, min(int(raw_override), max_rounds))
        except ValueError:
            _logger.warning(
                "invalid OCTOPUS_NATIVE_TOOL_ROUND_BUDGET=%r; using policy default",
                raw_override,
            )

    if _goal_is_narrow_single_source_research(goal):
        budget = _tb.NARROW_WEB_RESEARCH_ROUND_BUDGET
    elif code_change_task:
        budget = _tb.CODE_CHANGE_ROUND_BUDGET
    elif workspace_contract == "no_local_access":
        budget = _tb.WEB_RESEARCH_ROUND_BUDGET
    elif workspace_contract == "read_only":
        budget = _tb.READ_ONLY_ROUND_BUDGET
    else:
        budget = _tb.DEFAULT_TOOL_ROUND_BUDGET
    return max(1, min(budget, max_rounds))


def _filter_tool_specs_for_workspace_contract(
    tool_specs: list[Any],
    goal: str,
) -> tuple[list[Any], str | None]:
    """Enforce user local-workspace restrictions at the capability boundary."""
    if _goal_forbids_local_workspace_access(goal):
        allowed = [
            spec
            for spec in tool_specs
            if str(getattr(spec, "name", "")) in _NO_LOCAL_ACCESS_SAFE_TOOLS
            or str(getattr(spec, "name", "")).startswith("browser_")
        ]
        return allowed, "no_local_access"
    if _goal_is_read_only(goal):
        allowed = [
            spec
            for spec in tool_specs
            if str(getattr(spec, "name", "")) not in _READ_ONLY_BLOCKED_TOOLS
        ]
        return allowed, "read_only"
    return tool_specs, None


def _is_code_change_task(intent: ParsedIntent) -> bool:
    context = intent.user_context or {}
    raw_metadata = context.get("metadata")
    nested = raw_metadata if isinstance(raw_metadata, dict) else {}
    mode = str(context.get("mode") or nested.get("mode") or "").lower()
    code_mode = context.get("code_mode", nested.get("code_mode"))
    if mode != "code" and code_mode is not True:
        return False
    goal = str(intent.normalized_goal or "").lower()
    return any(
        marker in goal
        for marker in (
            "fix",
            "implement",
            "repair",
            "refactor",
            "update",
            "modify",
            "create",
            "add ",
            "bug",
            "vulnerability",
            "修复",
            "实现",
            "重构",
            "修改",
            "新增",
            "漏洞",
        )
    )


def _is_security_change_task(intent: ParsedIntent) -> bool:
    if not _is_code_change_task(intent):
        return False
    goal = str(intent.normalized_goal or "").lower()
    return any(
        marker in goal
        for marker in (
            "security",
            "vulnerability",
            "boundary",
            "traversal",
            "symlink",
            "escape",
            "injection",
            "auth",
            "安全",
            "漏洞",
            "边界",
            "遍历",
            "注入",
            "越权",
        )
    )


def _shell_command_text(call: ToolCall) -> str:
    command = call.input.get("command") if isinstance(call.input, dict) else None
    if isinstance(command, list):
        return " ".join(str(part) for part in command).lower()
    return str(command or "").lower()


def _is_shell_verification(call: ToolCall) -> bool:
    if call.name != "exec_shell":
        return False
    command = _shell_command_text(call)
    return any(
        marker in command
        for marker in (
            "pytest",
            "unittest",
            "npm test",
            "npm run test",
            "pnpm test",
            "yarn test",
            "cargo test",
            "go test",
            "dotnet test",
        )
    )


def _is_shell_terminal_verifier(call: ToolCall) -> bool:
    """Whether a shell call contributes independent terminal code evidence."""
    if _is_shell_verification(call):
        return True
    if call.name != "exec_shell":
        return False
    command = _shell_command_text(call)
    return any(
        marker in command
        for marker in (
            "ruff ",
            "pylint ",
            "pyright ",
            "basedpyright ",
            "mypy ",
            "eslint ",
            "tsc ",
            "cargo clippy",
            "go vet",
        )
    )


def _is_shell_mutation(call: ToolCall) -> bool:
    if call.name != "exec_shell":
        return False
    command = _shell_command_text(call)
    return any(
        marker in command
        for marker in (
            ".write(",
            "write_text(",
            "apply_patch",
            "tee ",
            "sed -i",
        )
    )


def _tool_uses_session_scope(stack: Any, call: ToolCall) -> bool:
    """Return whether a tool's correctness depends on Session filesystem scope.

    ContextVars are reliable on the ordinary serial path, but production SSE
    pumps can insert another thread boundary around a worker.  Until every
    executor backend accepts an explicit scope object, keep filesystem and
    shell tools serial. Pure compute/network tools still retain lane-B
    concurrency.
    """
    try:
        skill = stack.executor.registry.get(call.name)
    except (AttributeError, KeyError, TypeError):
        return True
    return bool(set(skill.affinity or ()) & _SCOPE_SENSITIVE_AFFINITIES)


def _reflection_checkpoint_message(round_i: int, max_rounds: int) -> str:
    return (
        f"<reflection-checkpoint iteration={round_i} max_iterations={max_rounds}>\n"
        "请简短回答，不要继续惯性调用普通工具。\n"
        "1. 已完成：用 1-2 句列出已经完成的事实。\n"
        "2. 还差：列出仍缺的关键步骤或证据。\n"
        "3. 当前 plan 是否仍然合理？回答 yes / no / partial，并说明一句原因。\n"
        "4. 下一步动作：如果需要调整计划，先调用 `todo_write` 更新；"
        "否则说明下一步最小动作。\n"
        "约束：本轮只允许思考或调用 `todo_write`，不要调用搜索、读取、写入、shell 等其它工具。\n"
        "</reflection-checkpoint>"
    )

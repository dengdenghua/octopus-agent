"""Shared rules for the user-visible task checklist protocol.

The checklist is not a reasoning transcript. It is the execution contract the
UI can show while an agent performs multi-step work.
"""

from __future__ import annotations

import re
from typing import Any

_SHORT_ACK_RE = re.compile(
    r"^\s*("
    r"hi|hello|hey|hello everyone|hello all|hi everyone|hi all|hi team|"
    r"thanks|thank you|ok|okay|yes|no|"
    r"嗯|好|好的|行|可以|谢谢|你好|大家好|早上好|上午好|中午好|下午好|晚上好|哈喽"
    r")[.!?。！？\s]*$",
    re.IGNORECASE,
)

_COMPLEXITY_CUE_RE = re.compile(
    r"("
    r"implement|fix|debug|refactor|review|audit|optimi[sz]e|verify|test|build|"
    r"research|investigate|compare|analy[sz]e|report|plan|todo|"
    r"继续|开始|开干|修|优化|审计|排查|调研|研究|分析|实现|测试|验证|打包|"
    r"多步|复杂|全局|完整|报告|方案|流程|团队|协作|深度"
    r")",
    re.IGNORECASE,
)

_CODE_OR_TOOL_CUE_RE = re.compile(
    r"("
    r"\b(read_file|write_file|edit_text_file|edit_file|multi_edit_file|exec_shell|web_search|todo_write)\b|"
    r"\.(py|ts|tsx|js|jsx|json|yaml|yml|md|css|html|go|rs)\b|"
    r"\b(npm|pytest|pnpm|yarn|vite|tsc|git)\b"
    r")",
    re.IGNORECASE,
)

_SINGLE_SOURCE_RE = re.compile(
    r"(?:\u4e00\u4e2a|1\s*\u4e2a)\s*(?:\u5b98\u65b9|\u53ef\u9760)?\s*(?:\u6765\u6e90|\u7f51\u9875|\u9875\u9762)|"
    r"\b(?:one|single)\s+(?:official\s+|reliable\s+)?source\b",
    re.IGNORECASE,
)
_CONCISE_RESULT_RE = re.compile(
    r"(?:\u4e00\u53e5|\u4e00\u53e5\u8bdd|\u4e00\u6bb5|\u7b80\u77ed|\u7ed3\u8bba|"
    r"\u53ea\u56de\u7b54|\u4ec5\u56de\u7b54)|"
    r"\b(?:one sentence|brief|concise|short conclusion|only (?:answer|report|return))\b",
    re.IGNORECASE,
)
_WEB_LOOKUP_RE = re.compile(
    r"(?:\u7f51\u9875\u8c03\u7814|\u641c\u7d22|\u67e5\u627e|\u5b98\u65b9\u6765\u6e90)|"
    r"\b(?:web research|search|look up|official source)\b",
    re.IGNORECASE,
)
_FOLLOWUP_EXECUTION_RE = re.compile(
    r"(?:\u7136\u540e|\u63a5\u7740|\u968f\u540e|\u5e76(?:\u4e14)?|\u540c\u65f6)\s*"
    r"(?:\u4fee\u6539|\u5b9e\u73b0|\u4fee\u590d|\u66f4\u65b0|\u521b\u5efa|\u65b0\u589e|\u91cd\u6784|\u6267\u884c|\u8fd0\u884c)|"
    r"\b(?:then|and then|also)\s+"
    r"(?:implement|fix|modify|edit|update|create|refactor|run|execute)\b",
    re.IGNORECASE,
)
_LEADING_EXECUTION_RE = re.compile(
    r"^\s*(?:\u4fee\u6539|\u5b9e\u73b0|\u4fee\u590d|\u66f4\u65b0|\u521b\u5efa|\u65b0\u589e|\u91cd\u6784|\u6267\u884c|\u8fd0\u884c)|"
    r"^\s*(?:implement|fix|modify|edit|update|create|refactor|run|execute)\b",
    re.IGNORECASE,
)
_EXPLICIT_SOURCE_PATH_RE = re.compile(
    r"(?<![\w./-])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\."
    r"(?:py|tsx|ts|jsx|json|js|yaml|yml|md|css|html|go|rs)\b",
    re.IGNORECASE,
)
_READ_ONLY_RE = re.compile(
    r"(?:只读|不要(?:修改|写入|创建|新增)|不(?:修改|写入|创建|新增)|严禁(?:修改|写入|创建|新增))|"
    r"\b(?:read[ -]?only|do not (?:modify|edit|write|create)|without (?:modifying|editing|writing|creating))\b",
    re.IGNORECASE,
)


def _is_narrow_single_source_lookup(text: str) -> bool:
    """Return whether a turn is a bounded lookup, not a multi-step project.

    Code workspaces are the common default surface, so mode alone cannot make a
    one-source factual lookup checklist-worthy. Keep the exemption deliberately
    narrow and reject prompts that continue into implementation or execution.
    """

    return bool(
        _SINGLE_SOURCE_RE.search(text)
        and _CONCISE_RESULT_RE.search(text)
        and _WEB_LOOKUP_RE.search(text)
        and not _LEADING_EXECUTION_RE.search(text)
        and not _FOLLOWUP_EXECUTION_RE.search(text)
    )


def _is_narrow_local_inspection(text: str) -> bool:
    """Return whether a turn is a bounded read-only comparison of named files.

    A code workspace should not turn inspection of a finite, explicit file set
    into a project checklist. Exact source evidence is enforced separately by
    the final-answer guards, so skipping the checklist here does not permit an
    answer before the requested files have been read. Open-ended audits and any
    task that continues into execution still require a checklist.
    """

    source_paths = {
        match.group(0).rstrip(".,;:!?，。；：！？")
        for match in _EXPLICIT_SOURCE_PATH_RE.finditer(text)
    }
    return bool(
        1 <= len(source_paths) <= 6
        and _READ_ONLY_RE.search(text)
        and not _LEADING_EXECUTION_RE.search(text)
        and not _FOLLOWUP_EXECUTION_RE.search(text)
    )


def _is_narrow_read_only_command(text: str) -> bool:
    """Return whether a turn is one bounded command with a concise result.

    Code mode is also the default home for tiny shell probes. Requiring a
    project checklist for a single explicitly read-only command adds another
    model round-trip and can contaminate the final synthesis with unrelated
    conversation context. Safety and approval policy still govern the command
    independently; this exemption only removes checklist ceremony.
    """

    return bool(
        len(text) <= 300
        and "\n" not in text
        and re.search(r"\bexec_shell\b", text, re.IGNORECASE)
        and _READ_ONLY_RE.search(text)
        and _CONCISE_RESULT_RE.search(text)
        and not _FOLLOWUP_EXECUTION_RE.search(text)
    )


def context_mode(user_context: dict[str, Any] | None) -> str:
    """Return the best-effort runtime mode from a thread context."""

    if not isinstance(user_context, dict):
        return ""
    metadata = user_context.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    for key in ("mode", "task_type", "research_mode"):
        value = user_context.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    if isinstance(user_context.get("workspace_path") or metadata.get("workspace_path"), str):
        return "code"
    return ""


def should_require_todo_protocol(
    goal: str,
    user_context: dict[str, Any] | None = None,
) -> bool:
    """Whether this turn should require a visible todo checklist.

    This intentionally biases toward requiring todos in execution-heavy modes,
    while keeping short acknowledgements and pure chat free of checklist noise.
    """

    text = (goal or "").strip()
    if not text or _SHORT_ACK_RE.match(text):
        return False

    mode = context_mode(user_context)
    metadata = user_context.get("metadata") if isinstance(user_context, dict) else None
    goal_mode = None
    if isinstance(user_context, dict):
        goal_mode = user_context.get("goal_mode") or user_context.get("completion_policy")
    if goal_mode is None and isinstance(metadata, dict):
        goal_mode = metadata.get("goal_mode") or metadata.get("completion_policy")
    if goal_mode is True or (
        isinstance(goal_mode, str) and goal_mode.lower() in {"goal", "goal_mode", "true"}
    ):
        return True

    capability = None
    if isinstance(user_context, dict):
        capability = user_context.get("capability_mode")
    if capability is None and isinstance(metadata, dict):
        capability = metadata.get("capability_mode")
    if isinstance(capability, str) and capability.lower() in {"swarm", "swarms", "team", "collab"}:
        return True

    if mode in {"team", "swarm", "swarms"}:
        return True
    if _is_narrow_local_inspection(text):
        return False
    if _is_narrow_single_source_lookup(text):
        return False
    if _is_narrow_read_only_command(text):
        return False
    if mode in {"code", "deep", "deep_research", "research"}:
        return True

    if "\n" in text or len(text) >= 80:
        return True
    if _COMPLEXITY_CUE_RE.search(text):
        return True
    return bool(_CODE_OR_TOOL_CUE_RE.search(text))


def render_todo_protocol_guidance(*, required: bool, mode: str = "") -> str:
    """Render a compact system guidance block for checklist behavior."""

    lead = "TASK CHECKLIST PROTOCOL REQUIRED" if required else "TASK CHECKLIST PROTOCOL AVAILABLE"
    scope = f" for {mode} mode" if mode else ""
    requirement = (
        "For this turn, call `todo_write` before giving the final answer. "
        "For execution-heavy work, create the checklist before substantial "
        "tool work when possible."
        if required
        else "Use `todo_write` when the task becomes multi-step."
    )
    return (
        f"{lead}{scope}:\n"
        f"- {requirement}\n"
        "- The checklist is user-visible progress, not hidden reasoning.\n"
        "- Pass the complete list every time; do not send diffs.\n"
        "- Items must use status `pending`, `in_progress`, or `completed`; "
        "keep at most one `in_progress` item.\n"
        "- Update the checklist when a phase starts, when a phase completes, "
        "and before the final answer after tool work.\n"
        "- If blocked, update the checklist to show the blocked/incomplete "
        "item and ask the user for the specific missing input."
    )

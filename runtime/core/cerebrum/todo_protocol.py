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
    if mode in {"code", "team", "deep", "deep_research", "research", "swarm", "swarms"}:
        return True

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

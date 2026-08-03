"""Working-set / phase / progress-summary helpers for the ReAct loop.

Extracted from ``react_execution.py``. Tracks which files the code agent
has read or edited, detects the current execution phase, and renders the
public progress summaries (code-mode and research-mode). Leaf module:
imports only from react_* leaf modules — never imports react_loop or
react_execution.
"""

from __future__ import annotations

import re
import time
from typing import Any

from runtime.core.cerebrum.react_context import _estimate_tokens
from runtime.core.cerebrum.react_parsing import _parse_action
from runtime.core.cerebrum.react_types import ReActStep

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

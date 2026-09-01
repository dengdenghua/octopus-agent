"""Runtime-side salvage for announce-only project inspection turns.

Some smaller providers repeatedly say that they will inspect the project but
never emit a tool call.  Prompt retries cannot manufacture evidence.  When the
promise is explicitly about the current project and a workspace is available,
start the first harmless discovery action in the runtime and return control to
the normal ReAct loop.  The model can then choose the relevant files from the
real directory observation.
"""

from __future__ import annotations

import re

from runtime.core.cerebrum.react_types import ReActStep

_PROJECT_INSPECTION_PROMISE_RE = re.compile(
    r"(?:项目|代码库|仓库|工作区|目录|文件|project|codebase|repo(?:sitory)?|workspace)"
    r"[^。.!！\n]{0,48}"
    r"(?:现状|结构|内容|文件|检查|查看|读取|分析|了解|inspect|read|check|review|analy[sz]e)"
    r"|(?:检查|查看|读取|分析|了解|inspect|read|check|review|analy[sz]e)"
    r"[^。.!！\n]{0,48}"
    r"(?:项目|代码库|仓库|工作区|目录|文件|project|codebase|repo(?:sitory)?|workspace)",
    re.IGNORECASE,
)


def _try_auto_project_inspection_salvage(
    label: str,
    candidate: str,
    steps: list[ReActStep],
    *,
    iteration: int,
    tools_active: bool,
) -> ReActStep | None:
    """Return a synthetic ``list_cwd`` step for a stalled project promise."""

    if label != "final-answer completeness guard" or not tools_active:
        return None
    if not _PROJECT_INSPECTION_PROMISE_RE.search(candidate or ""):
        return None

    # Run at most once.  After discovery, the provider must use the resulting
    # directory evidence to choose a real read/search action; repeating a root
    # listing would only disguise another stall as progress.
    for prior in steps:
        actions = list(prior.actions) if prior.actions else ([prior.action] if prior.action else [])
        actions.extend(
            str(result.get("tool_name") or "")
            for result in prior.action_results
            if isinstance(result, dict)
        )
        if any("list_cwd" in str(action).lower() for action in actions):
            return None

    action = "list_cwd({})"
    return ReActStep(
        iteration=iteration,
        thought=(
            "[runtime auto-inspection] The candidate promised to inspect the current "
            "project but emitted no tool call. Listing the workspace root so the next "
            "round can select and read relevant files."
        ),
        public_update="正在读取当前工作区结构，随后将基于实际文件给出结论。",
        action=action,
        actions=[action],
    )


__all__ = ["_try_auto_project_inspection_salvage"]

"""Shared rules for the user-visible task checklist protocol.

The checklist is not a reasoning transcript. It is the execution contract the
UI can show while an agent performs multi-step work.
"""

from __future__ import annotations

import re
from typing import Any

from runtime.core.cerebrum.react_guards import _has_successful_code_write
from runtime.core.cerebrum.react_parsing import (
    _has_code_verification,
    _has_successful_verification_observation,
    _is_code_write_step,
    _latest_todo_items,
    _parse_action,
)
from runtime.core.cerebrum.react_types import ReActStep
from runtime.core.cerebrum.work_mode import SWARM_ALIASES

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
    r"改成|改为|换成|改造|重做|新增|添加|接入|迁移|上线|部署|搭建|改版|美化|"
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
    r"\b(?:then|and then|also|and)\s+"
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
_NO_TODO_RE = re.compile(
    r"(?:不要|无需|不需要|禁止|不得|不可)\s*(?:调用|使用)?\s*todo_write\b|"
    r"(?:不要|无需|不需要|禁止|不得|不可)\s*(?:创建|生成|维护|使用)?\s*(?:任务)?清单|"
    r"\b(?:do\s+not|don't|never)\s+(?:call|use|create|write)?\s*todo_write\b|"
    r"\bwithout\s+(?:calling|using|creating|writing)\s+todo_write\b|"
    r"\b(?:no\s+(?:task\s+)?checklist|"
    r"without\s+(?:a\s+)?(?:task\s+)?checklist)\b",
    re.IGNORECASE,
)


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _effective_length(text: str) -> int:
    """Length weighted for CJK density: one CJK char carries roughly the
    information of 2-3 Latin chars, so Chinese prompts hit the long-form
    threshold at ~27 characters instead of 80."""
    return len(text) + 2 * len(_CJK_RE.findall(text))


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


_ANALYSIS_ONLY_RE = re.compile(
    r"(?:分析|解释|说明|总结|概述|评估|审查|检查|看看|不足|缺点|问题|风险|建议|"
    r"看法|评一下|讲一下|说一下|聊聊|讨论)"
    r"|\b(?:analy[sz]e|explain|summari[sz]e|review|assess|evaluat|"
    r"discuss|opinion|thoughts?|insights?)\b",
    re.IGNORECASE,
)
# Broad-scope targets signal a project-level audit, not a short follow-up.
# "inspect the project and summarize it" looks read-only but is a multi-step
# audit that still warrants a checklist.  Short follow-ups like "解释一下这段代码"
# reference a specific narrow object, not the whole project/codebase.
_BROAD_SCOPE_RE = re.compile(
    r"(?:项目|代码库|架构|整体|全面|系统)"
    r"|\b(?:project|codebase|architecture|workspace|repository|repo|"
    r"system|overall|comprehensive)\b",
    re.IGNORECASE,
)


def _is_read_only_analysis_goal(text: str) -> bool:
    """Return whether a turn is a short read-only analysis/inquiry follow-up.

    Code mode is also the default home for read-only follow-up questions
    ("不足点呢", "解释一下这段代码").  Forcing a checklist for these short
    follow-ups trains the model to manufacture fake todos, which the
    completion guard then has to reject.  Exempt them here so the root
    cause is fixed at the trigger layer instead of patched at the guard
    layer.

    Deliberately narrow: broad read-only audits ("只读审计...形成完整报告")
    and long analysis/report tasks still require a checklist because they
    are multi-step — only short follow-up inquiries with an explicit
    analysis/inquiry cue and no write intent are exempted.  Requiring the
    cue prevents short work directives like "继续优化深度研究" or
    "把登录页改成暗色主题" from being mistaken for read-only analysis.
    """
    # Lazy import to avoid circular dependency: react_goal_analysis imports
    # from todo_protocol at module level.
    from runtime.core.cerebrum.react_goal_analysis import _goal_requests_code_mutation

    # If the goal requests workspace mutation, it is not read-only analysis.
    if _goal_requests_code_mutation(text):
        return False
    # Short follow-up questions (effective length < 80) carrying an explicit
    # analysis/inquiry cue and no follow-up execution intent are read-only:
    # "不足点呢", "解释一下这段代码", "还有什么问题".  The cue requirement is
    # what separates an inquiry from a short work directive.
    return bool(
        _effective_length(text) < 80
        and _ANALYSIS_ONLY_RE.search(text)
        and not _FOLLOWUP_EXECUTION_RE.search(text)
        and not _BROAD_SCOPE_RE.search(text)
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
    # A checklist is a user-facing coordination aid, not a safety boundary.
    # Respect an explicit request to skip it instead of overriding the user's
    # interaction contract with code-mode defaults.
    if _NO_TODO_RE.search(text):
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
    if isinstance(capability, str) and capability.lower() in SWARM_ALIASES | {"team", "collab"}:
        return True

    if mode in SWARM_ALIASES | {"team"}:
        return True
    if _is_narrow_local_inspection(text):
        return False
    if _is_narrow_single_source_lookup(text):
        return False
    if _is_narrow_read_only_command(text):
        return False
    # Short read-only analysis follow-ups ("不足点呢", "解释一下这段代码")
    # in code/research modes should not be forced into checklist ceremony.
    # Broad read-only audits and long report tasks still require a checklist
    # — only short inquiry follow-ups with an analysis cue are exempted here.
    # The completion guard (change ②) provides a safety net for any
    # read-only turn that slips past this trigger-layer exemption.
    if _is_read_only_analysis_goal(text):
        return False
    if mode in {"code", "deep", "deep_research", "research"}:
        return True

    if "\n" in text or _effective_length(text) >= 80:
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
        "- Treat the checklist as mutable: when code, documentation, or tool evidence "
        "changes the scope, revise item wording, add/remove/reorder items, and keep stable "
        "IDs for unchanged work instead of preserving an obsolete initial plan.\n"
        "- After a successful workspace write or verification milestone, make the next "
        "action todo_write with the full evidence-backed plan before starting more work.\n"
        "- If blocked, update the checklist to show the blocked/incomplete "
        "item and ask the user for the specific missing input."
    )


def _todo_prewrite_guard(
    actions: list[str],
    steps: list[ReActStep],
    *,
    required: bool,
    visible: bool,
) -> str | None:
    """Require a visible checklist before substantial multi-step tool work.

    Long tasks start with a user-visible execution contract.  Grounding and
    implementation happen after that contract exists, so research-heavy turns
    cannot finish most of their work and only manufacture a checklist at the
    final-answer boundary.
    """

    if not (required and visible) or _latest_todo_items(steps):
        return None

    parsed = [entry for action in actions if (entry := _parse_action(action))]
    if not parsed or any(name.lower() == "todo_write" for name, _args in parsed):
        return None

    return (
        "[todo-before-work] The runtime did not execute this tool work because "
        "this multi-step task still has no visible checklist. Call todo_write "
        "now with a complete, non-empty plan, then start the first plan item."
    )


def _todo_completion_before_write_guard(
    actions: list[str],
    steps: list[ReActStep],
    *,
    required: bool,
) -> str | None:
    """Reject an all-completed code checklist with no write evidence.

    Discovery items may be completed while implementation remains pending.
    The invalid shape is specifically an entirely-completed checklist before
    any successful workspace mutation (and without a write in the same action
    batch).  Letting that state execute makes the provider believe the task is
    done while the Final Answer guard can only push it into a retry loop.
    """

    if not required or _has_successful_code_write(steps):
        return None
    parsed = [entry for action in actions if (entry := _parse_action(action))]
    if any(_is_code_write_step(ReActStep(iteration=0, action=action)) for action in actions):
        return None
    for name, args in parsed:
        if name != "todo_write":
            continue
        # Match the three input aliases the todo_write tool accepts
        # (items / todos / tasks — see agent_meta_skills._todo_write).
        raw_items = args.get("items") or args.get("todos") or args.get("tasks") or []
        items = raw_items if isinstance(raw_items, list) else []
        statuses = {
            str(item.get("status") or "").strip().lower()
            for item in items
            if isinstance(item, dict)
        }
        if items and statuses and statuses <= {"completed", "complete", "done"}:
            return (
                "[todo-completion-before-write] The runtime did not accept this "
                "all-completed checklist because no successful workspace write/edit "
                "is recorded. Keep the implementation item in_progress, execute the "
                "real write/edit tool, read the changed artifact back, verify it, and "
                "only then mark the checklist completed."
            )
    return None


def _todo_reconciliation_guard(
    actions: list[str],
    steps: list[ReActStep],
    *,
    required: bool,
    visible: bool,
) -> str | None:
    """Require plan reconciliation when execution changes phase.

    The initial checklist is only a hypothesis.  Once execution produces a
    durable mutation or verification result, the model must publish a fresh
    full snapshot before moving to a different kind of work.  The current
    write/repair/verification chain remains uninterrupted: inserting a plan
    update between an edit and its verifier would weaken, not improve, task
    completion.  Read-only evidence never triggers this gate either, which
    avoids the old read→todo→read loop.
    """
    if not (required and visible) or not steps or not _latest_todo_items(steps):
        return None

    parsed_actions = [entry for action in actions if (entry := _parse_action(action))]
    if any(name == "todo_write" for name, _args in parsed_actions):
        return None

    # A source/document repair and its verification commands form one atomic
    # execution phase.  Let the model finish that chain, including multiple
    # complementary verifiers (tests then lint/typecheck), before requiring a
    # revised public plan.  The gate below catches the first different tool.
    candidate_steps = [
        ReActStep(iteration=index + 1, action=action) for index, action in enumerate(actions)
    ]
    if any(_is_code_write_step(step) for step in candidate_steps) or any(
        _has_code_verification([step]) for step in candidate_steps
    ):
        return None

    latest_todo_index = -1
    for index in range(len(steps) - 1, -1, -1):
        step_actions = steps[index].actions or (
            [steps[index].action] if steps[index].action else []
        )
        if any(
            parsed is not None and parsed[0] == "todo_write"
            for action in step_actions
            if (parsed := _parse_action(action)) is not None
        ):
            latest_todo_index = index
            break
    if latest_todo_index < 0:
        return None

    evidence_steps = steps[latest_todo_index + 1 :]
    successful_write = any(
        _is_code_write_step(step)
        and (
            any(result.get("ok") is True for result in step.action_results)
            if step.action_results
            else bool((step.observation or "").strip())
            and "failed" not in (step.observation or "").lower()
            and "error" not in (step.observation or "").lower()
        )
        for step in evidence_steps
    )
    successful_verification = _has_successful_verification_observation(evidence_steps)
    if not (successful_write or successful_verification):
        return None

    milestones = []
    if successful_write:
        milestones.append("workspace/document write")
    if successful_verification:
        milestones.append("green verification")
    return (
        "[todo-reconciliation-required] The runtime paused this phase transition because "
        f"the plan predates a completed {' and '.join(milestones)} milestone. Call "
        "todo_write next with the complete revised checklist: mark only evidence-backed "
        "items completed, select one current item, and add/remove/reword/reorder items when "
        "the discovered code or documentation changed the scope. Then continue the work."
    )

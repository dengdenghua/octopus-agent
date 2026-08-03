"""Todo-protocol and completion-phrase guards.

Extracted from ``react_guards.py`` (Wave 3, cluster 3) so the orchestration
module can stay under the size budget. These guards enforce the visible
``todo_write`` checklist and detect mid-flight completion phrases that
aren't followed by a checklist update.

Leaf-ish module: depends only on re / react_goal_analysis / react_parsing /
react_code_mode_guards / react_types — must never import react_guards.
"""

from __future__ import annotations

import re

from runtime.core.cerebrum.react_code_mode_guards import _has_successful_code_write
from runtime.core.cerebrum.react_goal_analysis import _final_answer_requests_user_help
from runtime.core.cerebrum.react_parsing import (
    _latest_todo_items,
    _parse_action,
)
from runtime.core.cerebrum.react_types import ReActStep


def _has_tool_work_after_latest_todo(steps: list[ReActStep]) -> bool:
    """Whether a real action happened after the latest checklist update."""

    for step in reversed(steps):
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        name, _args = parsed
        if name == "todo_write":
            return False
        if name.lower() not in {"none", "n/a", ""} and step.observation:
            return True
    return False


def _todo_protocol_completion_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    goal: str = "",
) -> str | None:
    """Reject finals that skip or stale the visible checklist protocol.

    For short read-only analysis follow-ups ("不足点呢") that slipped past
    the trigger-layer exemption — e.g. because goal_mode or team mode
    forced ``todo_protocol_required=True`` before the read-only check —
    the checklist is optional: downgrade from hard reject to silent pass
    so pure inquiry follow-ups are not trapped into three-strike loops.

    This is deliberately a narrow safety net mirroring change ①'s
    ``_is_read_only_analysis_goal`` predicate.  Research, team
    coordination, implementation, and broad audit tasks all still require
    a checklist here; only short inquiry follow-ups with no write intent
    and no executed write tool are exempted.
    """

    if _final_answer_requests_user_help(final_answer):
        return None

    # Safety net mirroring change ①: a short read-only analysis follow-up
    # that the trigger layer could not exempt (goal_mode / team mode force
    # ``required=True`` upstream) should not be hard-blocked.  Writes are
    # the contract the checklist protects; without write intent and without
    # an executed write, the checklist is ceremony for an inquiry turn.
    if goal:
        # Lazy import: todo_protocol imports _has_successful_code_write from
        # this module at module scope, so a top-level import would cycle.
        from runtime.core.cerebrum.todo_protocol import _is_read_only_analysis_goal

        if _is_read_only_analysis_goal(goal) and not _has_successful_code_write(steps):
            return None

    todos = _latest_todo_items(steps)
    if not todos:
        return (
            "This task cannot finish yet: no todo_write checklist is recorded. "
            "Create a complete user-visible checklist before the final answer."
        )

    incomplete: list[str] = []
    for item in todos:
        status = str(item.get("status") or "").lower()
        if status != "completed":
            title = str(
                item.get("title")
                or item.get("content")
                or item.get("text")
                or item.get("task")
                or "untitled"
            )
            incomplete.append(title)
    if incomplete:
        preview = "; ".join(incomplete[:5])
        if len(incomplete) > 5:
            preview += f"; +{len(incomplete) - 5} more"
        return (
            "This task cannot finish yet: unfinished checklist items remain: "
            f"{preview}. Keep working, update todo_write, or ask the user for "
            "help if blocked."
        )

    if _has_tool_work_after_latest_todo(steps):
        return (
            "This task used tools after the latest todo_write update. Call "
            "todo_write again with the complete list marked accurately before "
            "the final answer."
        )

    return None


# ──────────────────────────────────────────────────────────────────
# In-flight guards — fire DURING the loop, not at Final Answer time.
# ──────────────────────────────────────────────────────────────────

# Phrases that suggest the model believes some unit of work just
# completed. Matched in the latest step's Thought / Observation
# heading. Triggers the "now update todo_write" reminder when the
# next action isn't already todo_write.
#
# Keep tight — false positives waste a turn nudging the model to call
# todo_write when the work isn't actually complete. Each entry should
# be unambiguously "I just finished a thing", not "I'm working on a
# thing".
_COMPLETION_PHRASE_RE = re.compile(
    r"(?:"
    # English: completion sentences
    r"\b(?:done|completed|finished|implemented|fixed|resolved)\b[^.\n]{0,40}"
    r"\b(?:successfully|now|the\s+(?:fix|change|edit|implementation))?|"
    r"\bthat'?s\s+(?:done|all|everything)\b|"
    r"\ball\s+(?:done|tests\s+pass|checks\s+pass)\b|"
    # Chinese: 完成 / 修好了 / 改好了 / 写好了 / 都搞定
    r"已[完成完成搞定修好改好写好]|"
    r"全部完成|都[完成搞定]|"
    r"[完修改写]好了|搞定了"
    r")",
    re.IGNORECASE,
)


def _looks_like_completion_phrase(text: str) -> bool:
    if not text:
        return False
    return bool(_COMPLETION_PHRASE_RE.search(text))


def _completion_phrase_without_todo_guard(
    steps: list[ReActStep],
    *,
    todo_protocol_required: bool,
) -> str | None:
    """Detect "I just finished X" claims that aren't immediately followed
    by a ``todo_write`` update.

    Fires DURING the loop (before the next action runs), not at Final
    Answer time. Goal: catch the model when it narrates a completion
    in its Thought but its actual next planned action is something
    other than updating the visible checklist. Quietly returns None
    when the next action IS ``todo_write`` — that's the desired
    behaviour and shouldn't generate noise.

    ``todo_protocol_required`` lets the loop turn this off for
    free-form chat where checklists aren't expected.
    """
    if not todo_protocol_required or not steps:
        return None
    todos = _latest_todo_items(steps)
    if not todos:
        # Caller's job to surface "no todo_write yet" via the existing
        # completion guard at Final Answer time. Mid-flight we don't
        # nag if no checklist exists — the model may just be warming up.
        return None

    last = steps[-1]
    last_thought = str(getattr(last, "thought", "") or "")
    last_obs = str(getattr(last, "observation", "") or "")
    if not (_looks_like_completion_phrase(last_thought) or _looks_like_completion_phrase(last_obs)):
        return None

    # Did the model just call todo_write? Then it already did the
    # right thing — don't pile on.
    parsed = _parse_action(last.action)
    if parsed is not None and parsed[0] == "todo_write":
        return None

    # Are there still incomplete todos? Otherwise the completion
    # phrase is plausibly the wrap-up at the end and the existing
    # final-answer guard takes over.
    incomplete = [item for item in todos if str(item.get("status") or "").lower() != "completed"]
    if not incomplete:
        return None

    return (
        "Detected a completion phrase ('done' / 'finished' / "
        "'已完成' / '搞定' / similar) but the latest action was not "
        "todo_write. Update the visible checklist NOW: mark the "
        "just-finished item completed before moving on. The user can "
        "only see your progress through the checklist."
    )


__all__ = [
    "_completion_phrase_without_todo_guard",
    "_has_tool_work_after_latest_todo",
    "_looks_like_completion_phrase",
    "_todo_protocol_completion_guard",
]

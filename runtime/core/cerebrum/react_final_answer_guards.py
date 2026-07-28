"""Final-answer guard plumbing for the ReAct loop.

Extracted from ``react_loop.py`` (Wave 1 of the split documented in
``docs/design/react-loop-split-plan.md``). Everything here decides whether a
candidate final answer may stream to the user, records rejected steps, and
produces the terminal wording when the loop deadlocks against a guard.
"""

from __future__ import annotations

import re
from typing import Any

from runtime.core.cerebrum.react_explicit_reads import _explicit_read_only_goal
from runtime.core.cerebrum.react_guards import (
    _goal_requests_code_mutation,
    _incomplete_final_answer_guard,
)
from runtime.core.cerebrum.react_loop_controls import (
    _disabled_guard_labels,
    _guard_hit_recorder,
)
from runtime.core.cerebrum.react_parsing import (
    _detect_destructive_calls_in_payload,
    _detect_dynamic_exec_in_payload,
    _detect_secrets_in_payload,
    _detect_shell_injection_in_payload,
    _detect_unsafe_deser_in_payload,
    _looks_like_unfinished_work,
)
from runtime.core.cerebrum.react_types import REACT_OBSERVATION_FOLLOWUP, ReActStep


def _unfinished_implementation_recovery_needed(
    text: str,
    goal: str,
    *,
    is_code_mode: bool,
) -> bool:
    """Limit implementation recovery to turns that actually mutate code.

    Research evidence often describes bugs, expected behavior, or proposed
    fixes. Those phrases can look like unfinished implementation work even
    though the user's requested work is already complete.
    """

    if not _looks_like_unfinished_work(text):
        return False
    if _goal_requests_code_mutation(goal):
        return True
    goal_text = str(goal or "").lower()
    non_implementation_turn = _explicit_read_only_goal(goal) or bool(
        re.search(
            r"(?:网页调研|调研|官方来源|网页|来源)|"
            r"\b(?:web research|research|official source|source|https?://)\b",
            goal_text,
        )
    )
    return not non_implementation_turn


def _record_rejected_step(
    steps: list,
    messages: list,
    step: Any,
    observation: str,
) -> None:
    """Record a denied / user-rejected action instead of silently dropping it.

    The approval-deny and user-reject branches used to ``continue`` after only
    setting a local ``observation``, so the rejected action never entered
    ``steps`` or ``messages``. That (a) livelocked the loop — the next LLM call
    could not see the rejection and re-emitted the same action until
    ``max_iter`` — and (b) left security-relevant denials invisible to the step
    trace. Append the step and surface the rejection to the model (assistant
    action + observation) so it adapts on the next turn."""
    from runtime.platform.models.llm import Message

    step.observation = observation
    steps.append(step)
    messages.append(Message(role="assistant", content=step.action))
    messages.append(
        Message(
            role="user",
            content=f"Observation: {observation}\n\n{REACT_OBSERVATION_FOLLOWUP}",
        )
    )


def _looks_like_observation_echo(text: str) -> bool:
    """True when model prose is leaked tool/protocol text, not an answer."""
    stripped = (text or "").lstrip()
    if not stripped:
        return False
    head = stripped[:800].lower()
    return (
        head.startswith("observation:")
        or head.startswith("[1/")
        or head.startswith("<tool_invocation")
        or head.startswith("<tool_call")
        or head.startswith("<function")
        or "(real tool execution succeeded)" in head
        or "[system guard]" in head
        or bool(
            re.search(r"(?im)^(?:user|model|assistant|system):\s*", head)
            and re.search(r"(?im)^(?:thought|action|observation|update):\s*", head)
        )
    )


def _final_answer_needs_pre_emit_guard(
    text: str,
    *,
    is_code_mode: bool,
    browser_operation_mode: bool = False,
) -> bool:
    """Whether user-visible final text must be buffered until guards pass."""
    if is_code_mode or browser_operation_mode:
        return True
    body = text or ""
    if not body:
        return False
    # A plain chat-style stream can itself be a preparatory placeholder
    # ("I will search...", "我先检查...").  Buffer that shape until the
    # iteration ends so the completeness guard can reject it without first
    # leaking the placeholder into the visible answer channel.  As soon as
    # the same response contains a concrete conclusion this predicate clears
    # and normal token streaming resumes.
    if _incomplete_final_answer_guard(body) is not None:
        return True
    lower = body.lower()
    if (
        "```" in body
        or "subprocess" in lower
        or "os.system" in lower
        or "os.popen" in lower
        or "pickle." in lower
        or "marshal." in lower
        or "yaml.load" in lower
        or "eval(" in lower
        or "exec(" in lower
        or "__import__(" in lower
        or "rm -rf" in lower
    ):
        return True
    return bool(
        _detect_secrets_in_payload(body)
        or _detect_dynamic_exec_in_payload(body)
        or _detect_shell_injection_in_payload(body)
        or _detect_unsafe_deser_in_payload(body)
        or _detect_destructive_calls_in_payload(body)
    )


def _evaluate_final_answer_guards(
    *,
    steps: list[ReActStep],
    step: ReActStep,
    final_answer: str,
    is_code_mode: bool,
    todo_protocol_required: bool,
    todo_protocol_visible: bool,
    file_inspection_tools_visible: bool,
    tools_active: bool,
    goal: str,
    browser_operation_mode: bool = False,
    grounded_source_paths: frozenset[str] = frozenset(),
    categories: frozenset[str] | set[str] | None = None,
) -> tuple[str, str] | None:
    """Run the final-answer guard registry for regular and salvage paths."""
    from runtime.core.cerebrum.react_guards import (
        GuardContext,
        evaluate_guards,
    )

    return evaluate_guards(
        GuardContext(
            steps=steps + [step],
            final_answer=final_answer,
            is_code_mode=is_code_mode,
            todo_protocol_required=todo_protocol_required,
            todo_protocol_visible=todo_protocol_visible,
            file_inspection_tools_visible=file_inspection_tools_visible,
            tools_active=tools_active,
            goal=goal,
            browser_operation_mode=browser_operation_mode,
            grounded_source_paths=grounded_source_paths,
        ),
        recorder=_guard_hit_recorder(),
        disabled_labels=_disabled_guard_labels(),
        categories=categories,
    )


def _note_guard_impasse(state: dict, label: str, steps: list) -> bool:
    """Track repeated same-guard rejections; True when the loop is stuck.

    A guard pushing back is healthy — the model does more work and returns
    with evidence. It stops being healthy when the SAME guard rejects the
    final answer again and again while the trajectory gains no new
    action-bearing steps: the model either cannot produce the demanded
    evidence or (worse) its attempts to comply never execute — e.g. its
    tool calls arrive in a format the parser drops. Left unbounded, that
    burns the whole iteration budget and then terminates through the
    auto-pause path, whose "paused — continue from checkpoint" wording
    misreports what actually happened. Three no-progress rejections in a
    row is the bound: real evidence-gathering always grows the step list.
    """
    progress = sum(
        1
        for s in steps
        if (getattr(s, "action", "") or "").strip() or getattr(s, "action_results", None)
    )
    if state.get("label") == label and state.get("progress") == progress:
        state["count"] = state.get("count", 0) + 1
    else:
        state.update(label=label, progress=progress, count=1)
    return state["count"] >= 3


def _guard_impasse_final_answer(label: str, message: str) -> str:
    """The honest terminal answer for a guard impasse — shared by every
    in-loop guard-rejection site so the wording (and the truth it tells)
    can't drift between them."""
    user_reason = _guard_reason_for_user(label, message)
    return (
        "任务未能完成:我连续多次尝试收尾,但始终无法满足"
        f"「{label}」要求的执行证据,期间也没有任何新的工具执行成功。"
        "为避免空转,我停止了重试。\n\n"
        f"最后一次拦截原因:\n{user_reason}\n\n"
        "这通常意味着模型输出的工具调用格式未被执行层识别,"
        "或任务所需的能力/权限当前不可用。请检查上面的原因后重试。"
    )


def _guard_reason_for_user(label: str, message: str) -> str:
    """Avoid reflecting rejected security payloads into the transcript.

    Security guard diagnostics intentionally name the exact dangerous token
    or credential shape for the model's next repair attempt.  Reusing that
    diagnostic verbatim in a terminal user message can re-expose the content
    that the guard just prevented from streaming.
    """
    if label in {
        "secret-leak guard",
        "destructive-call guard",
        "dynamic-exec guard",
        "shell-injection guard",
        "unsafe-deser guard",
    }:
        return "安全检查拒绝了候选答复；具体片段已隐藏，避免再次暴露。"
    return message

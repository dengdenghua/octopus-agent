"""Final-answer guard plumbing for the ReAct loop.

Extracted from ``react_loop.py`` (Wave 1 of the split documented in
``docs/design/react-loop-split-plan.md``). Everything here decides whether a
candidate final answer may stream to the user, records rejected steps, and
produces the terminal wording when the loop deadlocks against a guard.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Generator
from typing import Any

from runtime.core.cerebrum.react_convergence import evidence_answer_conflicts_with_goal
from runtime.core.cerebrum.react_explicit_reads import _explicit_read_only_goal
from runtime.core.cerebrum.react_guards import (
    _goal_requests_code_mutation,
    _incomplete_final_answer_guard,
)
# Imported from the defining module directly: react_guards' re-export of
# ``_step_is_failed_execution`` exists only in an uncommitted refactor, so at
# the committed tip ``from react_guards import _step_is_failed_execution``
# raised ImportError and broke 24 test modules at collection.
from runtime.core.cerebrum.react_todo_protocol_guards import _step_is_failed_execution
from runtime.core.cerebrum.react_loop_controls import (
    _disabled_guard_labels,
    _guard_hit_recorder,
)
from runtime.core.cerebrum.react_loop_state import _LoopControl, _LoopState
from runtime.core.cerebrum.react_parsing import (
    _detect_destructive_calls_in_payload,
    _detect_dynamic_exec_in_payload,
    _detect_secrets_in_payload,
    _detect_shell_injection_in_payload,
    _detect_unsafe_deser_in_payload,
    _looks_like_unfinished_work,
)
from runtime.core.cerebrum.react_types import REACT_OBSERVATION_FOLLOWUP, ReActStep

_logger = logging.getLogger(__name__)


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


_CODE_FENCE_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)


def _strip_code_fences(text: str) -> str:
    """Remove fenced code blocks (```...```) from a candidate answer.

    Code deliverables present ``eval``/``exec``/``__import__``/``compile``
    inside markdown fences. Those are display-only tokens, not runtime calls
    the agent is about to run, so the pre-emit guard must not buffer the
    whole stream on them — the terminal guard in ``_evaluate_final_answer_guards``
    still vets the full text for genuinely dangerous execution.
    """
    return _CODE_FENCE_RE.sub(" ", text or "")


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
        # ReAct protocol blocks leaked into the answer channel. The model
        # occasionally writes ``Thought: ...`` / ``Action: name({...})`` as
        # answer text instead of routing them through the tool-call channel —
        # the tools then never execute and the user sees raw protocol. A
        # standalone ``Action: name({...})`` call shape is unambiguous (it
        # is never legitimate prose); ``Thought:`` alone could be a quote,
        # so only flag it when an Action block is also present.
        or bool(_REACT_ACTION_CALL_RE.search(stripped))
        or bool(
            _REACT_THOUGHT_LINE_RE.search(stripped)
            and _REACT_ACTION_CALL_RE.search(stripped)
        )
    )


# A ReAct Action block written as prose: ``Action:\n    name({...})`` or
# ``Action: name({...})``. Anchored on the tool-call shape (name + JSON
# parens) so a legitimate mention like "the Action field" is not flagged.
_REACT_ACTION_CALL_RE = re.compile(
    r"(?im)Action\s*:\s*\n?\s*\w+\s*\(\s*\{.*?\}\s*\)",
    re.DOTALL,
)
# A ``Thought:`` line at the start of a line. Used only as a corroboration
# signal alongside an Action block above, never on its own.
_REACT_THOUGHT_LINE_RE = re.compile(r"(?im)^\s*Thought\s*:\s*")


def _final_answer_needs_pre_emit_guard(
    text: str,
    *,
    is_code_mode: bool,
    browser_operation_mode: bool = False,
) -> bool:
    """Whether user-visible final text must be buffered until guards pass.

    Only genuinely dangerous executable content must force full buffering.
    ``is_code_mode`` no longer forces buffering by itself: in the realtime
    workbench ``is_code`` is effectively always true because a workspace is
    mounted (see ``work_mode.resolve_work_mode``), so treating it as a hard
    gate made every final report render wholesale instead of streaming.
    Markdown code fences (`` ``` ``) are likewise not a reason to buffer —
    a report that quotes code would otherwise never stream. The terminal
    guard in ``_evaluate_final_answer_guards`` still re-evaluates the full
    text, so mid-stream preview of non-executable prose is safe.
    """
    if browser_operation_mode:
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
    # In code mode the answer *is* the deliverable: the model is presenting
    # code that routinely contains subprocess/os.system/eval/exec or shell
    # command text. Buffering on those tokens would freeze the stream the
    # moment the first one appears, then dump the whole report at once —
    # exactly the "choppy" code streaming users see. Displaying code is safe
    # (the terminal guard in _evaluate_final_answer_guards still vets any
    # real tool execution), so in code mode only genuinely dangerous explicit
    # exec (eval/exec/__import__/compile of a payload) and secret leakage
    # force buffering. Keyword presence and shell-injection / unsafe-deser /
    # destructive-call patterns — which are normal in code deliverables —
    # only force buffering outside code mode.
    if not is_code_mode and (
        "subprocess" in lower
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
    # Dynamic-exec token detection must ignore fenced code blocks: in code
    # mode the deliverable routinely contains eval/exec/__import__/compile
    # inside fences, which are display-only. Only a dynamic-exec call in the
    # surrounding prose (i.e. the model proposing to actually run it) should
    # buffer the stream. Secrets are still checked on the full text so a
    # leaked key inside a code block is caught before it streams.
    if _detect_secrets_in_payload(body):
        return True
    if _detect_dynamic_exec_in_payload(_strip_code_fences(body)):
        return True
    return bool(
        not is_code_mode
        and (
            _detect_shell_injection_in_payload(body)
            or _detect_unsafe_deser_in_payload(body)
            or _detect_destructive_calls_in_payload(body)
        )
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
    model: str = "",
) -> tuple[str, str] | None:
    """Run the final-answer guard registry for regular and salvage paths."""
    from runtime.core.cerebrum.react_guards import (
        GuardContext,
        evaluate_guards,
    )

    candidate_digest = hashlib.sha256(final_answer.encode("utf-8", errors="ignore")).hexdigest()[
        :16
    ]
    all_steps = steps + [step]
    return evaluate_guards(
        GuardContext(
            steps=all_steps,
            final_answer=final_answer,
            is_code_mode=is_code_mode,
            todo_protocol_required=todo_protocol_required,
            todo_protocol_visible=todo_protocol_visible,
            file_inspection_tools_visible=file_inspection_tools_visible,
            tools_active=tools_active,
            goal=goal,
            browser_operation_mode=browser_operation_mode,
            grounded_source_paths=grounded_source_paths,
            model=model,
            execution_degraded=_trajectory_execution_degraded(all_steps),
        ),
        recorder=_guard_hit_recorder(
            dedupe_key=f"{id(steps)}:{step.iteration}:{candidate_digest}",
            goal=goal,
            iteration=step.iteration,
            metadata={
                "candidate_digest": candidate_digest,
                "step_count": len(steps) + 1,
                "model": model,
            },
        ),
        disabled_labels=_disabled_guard_labels(),
        categories=categories,
    )


def _note_guard_impasse(
    state: dict,
    label: str,
    steps: list,
    *,
    rejection_limit: int = 3,
) -> bool:
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

    FAILED executions do not count toward progress: an environmental
    failure (sandbox/network) that the model retries adds a step but no
    evidence, so counting it would silently reset the counter and let the
    same guard reject forever. A genuinely successful new action still
    resets the counter.
    """
    progress = sum(
        1
        for s in steps
        if ((getattr(s, "action", "") or "").strip() or getattr(s, "action_results", None))
        and not _step_is_failed_execution(s)
    )
    if state.get("label") == label and state.get("progress") == progress:
        state["count"] = state.get("count", 0) + 1
    else:
        state.update(label=label, progress=progress, count=1)
    return state["count"] >= rejection_limit


def _guard_rejection_outcome(state: dict, label: str, steps: list) -> str:
    """Return ``retry``, ``soft_land`` or ``hard_stop`` for a rejection."""
    from runtime.core.cerebrum.react_guards import guard_disposition

    disposition = guard_disposition(label)
    limit = 3 if disposition == "hard" else 2
    if not _note_guard_impasse(state, label, steps, rejection_limit=limit):
        return "retry"
    return "hard_stop" if disposition == "hard" else "soft_land"


# Markers that distinguish an ENVIRONMENTAL tool failure (sandbox/network
# denial the model cannot fix by retrying the same tool) from a logic error
# it could. Matched case-insensitively against the observation text.
_ENVIRONMENTAL_FAILURE_MARKERS: tuple[str, ...] = (
    "(工具执行异常)",
    "operation not permitted",
    "eperm",
    "sandbox_apply",
    "sandbox",
    "connectionerror",
    "connection error",
    "connect timeout",
    "network access",
    "network request",
)


def _step_is_environmental_failure(step) -> bool:
    """Whether a failed step's cause is environmental rather than a logic
    error the model could fix by retrying. Successful receipts win."""
    if step.action_results:
        if any(result.get("ok") is True for result in step.action_results):
            return False
        text = " ".join(str(result.get("observation") or "") for result in step.action_results)
    else:
        text = str(getattr(step, "observation", "") or "")
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _ENVIRONMENTAL_FAILURE_MARKERS)


# How many environmental failures mark the environment itself as degraded.
# One EPERM can be transient (or the model probing whether a tool runs);
# two or more mean execution is genuinely blocked, so run-based evidence
# guards must stop vetoing the turn.
_EXECUTION_DEGRADED_THRESHOLD = 2


def _trajectory_execution_degraded(steps: list) -> bool:
    """Whether the execution environment is degraded.

    Two independent signals, OR'd:

    * startup canary — ``env_health`` probed a sandboxed command at serve
      boot and it could not run (the whole process session is degraded);
    * live trajectory — ≥2 steps that failed environmentally (sandbox /
      network / OS-permission denials the model cannot fix by retrying).

    Either means the run-based guards — which demand executed test or
    typecheck evidence — can never be satisfied, so evaluate_guards
    downgrades them to advisory instead of three-striking the turn.
    """
    from runtime.core.cerebrum.env_health import execution_canary_degraded

    if execution_canary_degraded():
        return True
    count = sum(1 for s in steps or [] if _step_is_environmental_failure(s))
    return count >= _EXECUTION_DEGRADED_THRESHOLD


def _guard_soft_landing_answer(
    candidate: str,
    label: str,
    *,
    steps: list | None = None,
) -> str:
    """Return the useful candidate without exposing internal guard policy.

    Guard labels, retry counters and evidence-gate diagnostics are runtime
    implementation details.  They belong in structured telemetry, never in
    the assistant's conversational answer.  A repair-tier guard is bounded:
    after its retry budget is exhausted we deliver the cleaned candidate and
    let the structured completion receipt carry any degraded-environment
    details.

    ``label`` and ``steps`` intentionally remain in the signature so existing
    callers and telemetry hooks do not need a second compatibility path.
    """
    del label, steps
    return _strip_inline_tool_calls(candidate or "")


# Tool names the model may write into answer prose as an inline JSON call
# (``todo_write({"items": [...]})``) instead of emitting a structured tool
# call. When that leaks into the final answer, strip the whole call block so
# the user never sees raw tool protocol in the transcript.
_INLINE_TOOL_CALL_NAMES = (
    "todo_write",
    "exec_shell",
    "shell_command",
    "run_command",
    "web_search",
    "fetch_url",
    "web_fetch",
    "read_file",
    "glob_files",
    "find_files",
    "apply_patch",
    "write_file",
    "edit_file",
    "str_replace",
    "run_tests",
    "lint_check",
)
_INLINE_TOOL_CALL_RE = re.compile(
    rf"(?m)^\s*(?:{'|'.join(_INLINE_TOOL_CALL_NAMES)})\s*\("
)


def _strip_inline_tool_calls(text: str) -> str:
    """Remove ``tool_name({...})`` blocks that the model wrote into answer
    prose instead of emitting as structured tool calls. A balanced-brace scan
    consumes the whole JSON object (including nested braces) plus the closing
    paren, so surrounding narration survives intact."""
    if not text:
        return text
    parts: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        m = _INLINE_TOOL_CALL_RE.match(text, i)
        if not m:
            parts.append(text[i:])
            break
        parts.append(text[i : m.start()])
        open_idx = text.index("(", m.end() - 1)
        depth = 0
        j = open_idx
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    j += 1
                    while j < n and text[j] in " \t":
                        j += 1
                    if j < n and text[j] == ")":
                        j += 1
                    if j < n and text[j] == "\n":
                        j += 1
                    i = j
                    break
            j += 1
        else:
            # Unbalanced — keep the matched prefix and advance past it.
            parts.append(text[m.start() : m.end()])
            i = m.end()
    return "".join(parts).strip()


def _guard_impasse_final_answer(label: str, message: str) -> str:
    """The honest terminal answer for a guard impasse — shared by every
    in-loop guard-rejection site so the wording (and the truth it tells)
    can't drift between them."""
    user_reason = _guard_reason_for_user(label, message)
    actionable = _guard_impasse_actionable_hint(label, message)
    # ``label`` is useful for logs/metrics, but exposing names such as
    # ``todo-protocol guard`` makes an internal policy failure look like an
    # assistant answer.  Keep the user-facing result factual and actionable.
    del label
    return (
        "这轮任务没有完成。我已停止重复尝试，并保留了当前进度。\n\n"
        f"原因：\n{user_reason}\n\n"
        f"{actionable}"
    )


def _guard_impasse_actionable_hint(label: str, message: str) -> str:
    """Scene-specific actionable advice appended to the impasse message.

    Instead of a single generic "check and retry", give the user a
    concrete next step based on which guard fired and what the
    diagnostic says.
    """
    msg_lower = (message or "").lower()
    if "path_blocked" in msg_lower or "escapes_sandbox" in msg_lower:
        return (
            "如何解决：该路径在当前工作区沙箱之外。\n"
            "1) 确认路径是否正确；\n"
            "2) 切换到 project workspace 模式以扩大工作区范围；\n"
            "3) 使用 CLI code 模式（python -m runtime.cli code --cwd <项目根目录>）运行任务。"
        )
    if "tool" in msg_lower and ("not registered" in msg_lower or "未注册" in msg_lower):
        return (
            "如何解决：所需工具未注册或被配置关闭。\n"
            "1) 检查 config.local.yaml 中对应的 enable_* 开关；\n"
            "2) 确认工具名称拼写正确；\n"
            "3) 重启后端使配置生效。"
        )
    if "inspection" in label.lower() or "evidence" in label.lower():
        return (
            "如何解决：需要先收集执行证据再给出结论。\n"
            "1) 点击继续，让我先读取相关文件或运行验证命令；\n"
            "2) 提供必要的权限/登录/信息后我再继续。"
        )
    return (
        "这通常意味着模型输出的工具调用格式未被执行层识别,"
        "或任务所需的能力/权限当前不可用。\n"
        "如何解决：\n"
        "1) 点击继续重试，或补充必要的信息/权限；\n"
        "2) 检查上面的原因后重新描述任务；\n"
        "3) 如仍失败，尝试切换到 CLI code 模式运行。"
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


def _phase_6e_guards_and_step_emit(
    state: _LoopState,
    *,
    i: int,
    append_pending_live_steering: Callable[[], int],
    build_research_progress_summary: Callable[[list[ReActStep]], str],
) -> Generator[dict, None, _LoopControl]:
    """PHASE 6e guard state machine + step completion emit.

    Moved verbatim from ``react_loop.py`` (PHASE 6e, second half): the
    evidence-answer conflict repair, the live-steering finalization
    deferral, final-answer guard evaluation with the three-strike
    impasse breaker, the deferred ``text_delta`` emit, and the
    ``react_step_complete`` event. Returns ``BREAK`` when a guard hits
    the impasse limit (``state`` then carries ``final_answer`` /
    ``terminated_reason``); ``CONTINUE`` otherwise.
    ``_append_pending_live_steering`` is a react_loop closure and
    ``_build_research_progress_summary`` lives in react_execution (which
    imports this module), so both are injected.
    """
    # Injected callables under their original names.
    _append_pending_live_steering = append_pending_live_steering
    _build_research_progress_summary = build_research_progress_summary
    # Reference-typed aliases — mutations propagate to the main loop.
    intent = state.intent
    steps = state.steps
    step = state.step
    assert step is not None, "phase 6e requires a parsed ReAct step"
    react_task_id = state.react_task_id
    _working_set = state.working_set
    _guard_impasse_state = state.guard_impasse_state
    _final_guard_grounded_source_paths = state.final_guard_grounded_source_paths
    # Scalar mailbox — pulled in, pushed back in the finally below.
    maybe_final = state.maybe_final
    final_answer = state.final_answer
    terminated_reason = state.terminated_reason
    _evidence_convergence_active = state.evidence_convergence_active
    _force_convergence_next = state.force_convergence_next
    _final_stream_started = state.final_stream_started
    _final_delta_emitted_this_iteration = state.final_delta_emitted_this_iteration
    _todo_protocol_required = state.todo_protocol_required
    _todo_protocol_visible = state.todo_protocol_visible
    _is_code_mode = state.is_code_mode
    _browser_operation_mode = state.browser_operation_mode
    _file_inspection_tools_visible = state.file_inspection_tools_visible
    tools_active = state.tools_active
    _green_verification_convergence_active = state.green_verification_convergence_active
    _green_convergence_todo_used = state.green_convergence_todo_used
    _clean_verification_rounds_after_write = state.clean_verification_rounds_after_write
    _streamed_final_chars = state.streamed_final_chars
    _current_phase = state.current_phase
    _progress_summary = state.progress_summary
    _public_progress_summary = state.public_progress_summary
    try:
        if (
            maybe_final
            and _evidence_convergence_active is not None
            and evidence_answer_conflicts_with_goal(
                goal=intent.normalized_goal,
                answer=maybe_final,
            )
        ):
            # Bounded evidence exists, so an idle/greeting answer claiming
            # there was no task is objectively contradictory. Keep it out of
            # the answer stream and retry with the original request attached.
            step.observation = (
                (((step.observation or "") + "\n\n") if step.observation else "")
                + "[evidence-answer-conflict]\n"
                + "The proposed answer falsely denied the active user request or the "
                + "completed evidence. Discard it and answer the original request "
                + "directly from the bounded evidence already supplied."
            )
            maybe_final = None
            _force_convergence_next = True

        # Close the race where a follow-up arrives while the model is composing
        # what would otherwise be the terminal answer. Keep that answer as
        # conversation history, then give the latest user message the next
        # model round instead of finalizing over it.
        if maybe_final and _append_pending_live_steering():
            maybe_final = None
            _logger.info(
                "react_loop deferred finalization for a priority user follow-up",
            )

        if maybe_final:
            _deferred_final_emit = not _final_stream_started and (
                _evidence_convergence_active is not None
                or (_todo_protocol_required and _todo_protocol_visible)
                or _final_answer_needs_pre_emit_guard(
                    maybe_final,
                    is_code_mode=_is_code_mode,
                    browser_operation_mode=_browser_operation_mode,
                )
            )
            _guard_hit = _evaluate_final_answer_guards(
                steps=steps,
                step=step,
                final_answer=maybe_final,
                is_code_mode=_is_code_mode,
                todo_protocol_required=_todo_protocol_required,
                todo_protocol_visible=_todo_protocol_visible,
                file_inspection_tools_visible=_file_inspection_tools_visible,
                tools_active=tools_active,
                goal=intent.normalized_goal,
                browser_operation_mode=_browser_operation_mode,
                grounded_source_paths=_final_guard_grounded_source_paths,
            )
            if _guard_hit is not None:
                _guard_label, _guard_message = _guard_hit
                _guard_outcome = _guard_rejection_outcome(_guard_impasse_state, _guard_label, steps)
                if _guard_outcome == "soft_land":
                    final_answer = _guard_soft_landing_answer(
                        maybe_final,
                        _guard_label,
                        steps=steps,
                    )
                    terminated_reason = "final_answer_with_warning"
                    steps.append(step)
                    return _LoopControl.BREAK
                if _guard_outcome == "hard_stop":
                    # Same guard, three rejections, zero new action-bearing
                    # steps in between: pushing back again only burns the
                    # remaining budget and ends in the auto-pause path's
                    # misleading "paused" report. Terminate with the truth.
                    _logger.warning(
                        "react_loop guard impasse · %s rejected the final answer "
                        "3x with no intervening tool execution — terminating "
                        "explicitly instead of burning the iteration budget",
                        _guard_label,
                    )
                    final_answer = _guard_impasse_final_answer(_guard_label, _guard_message)
                    terminated_reason = "guard_impasse"
                    steps.append(step)
                    return _LoopControl.BREAK
                maybe_final = None
                # A completion guard may discover a semantic defect even
                # after two superficially green verifier rounds. Re-open the
                # tool path so the model can perform the demanded repair;
                # otherwise the convergence gate would suppress every fix
                # and turn a useful guard into an impasse. The todo protocol
                # is different: terminal evidence is still valid and the
                # convergence state already allows exactly one checklist
                # update. Clearing it here caused green agents to resume an
                # unbounded test/lint cycle after that update.
                if _guard_label != "todo-protocol guard":
                    _green_verification_convergence_active = False
                    _green_convergence_todo_used = False
                    _clean_verification_rounds_after_write = 0
                    _force_convergence_next = False
                step.observation = (
                    (((step.observation or "") + "\n\n") if step.observation else "")
                    + f"[{_guard_label}]\n"
                    + _guard_message
                )
            elif _deferred_final_emit:
                _delta = (
                    maybe_final[_streamed_final_chars:] if _streamed_final_chars else maybe_final
                )
                yield {
                    "type": "text_delta",
                    "delta": _delta,
                    "iteration": i + 1,
                }
                _final_delta_emitted_this_iteration = True

        _public_progress_summary = (
            _progress_summary if _is_code_mode else _build_research_progress_summary(steps + [step])
        )

        yield {
            "type": "react_step_complete",
            "iteration": step.iteration,
            "thought": step.thought,
            "public_update": step.public_update,
            "action": step.action,
            "observation": step.observation,
            "task_id": str(react_task_id),
            "current_phase": _current_phase if _is_code_mode else None,
            "working_set": list(_working_set.values()) if _is_code_mode else None,
            "progress_summary": _public_progress_summary,
        }
        return _LoopControl.CONTINUE
    finally:
        state.maybe_final = maybe_final
        state.force_convergence_next = _force_convergence_next
        state.green_verification_convergence_active = _green_verification_convergence_active
        state.green_convergence_todo_used = _green_convergence_todo_used
        state.clean_verification_rounds_after_write = _clean_verification_rounds_after_write
        state.final_answer = final_answer
        state.terminated_reason = terminated_reason
        state.final_delta_emitted_this_iteration = _final_delta_emitted_this_iteration
        state.public_progress_summary = _public_progress_summary

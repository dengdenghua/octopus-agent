"""PHASE 6g — loop-tail housekeeping for the ReAct loop.

Extracted from ``react_execution.py`` (Wave 2). Implements
``_phase_6g_housekeeping``: plan-exit, checkpoints, message append, length
continuation, and context compression. Neither it nor its imports form a
cycle — it imports from react_* leaf modules and the sibling
``_react_execution_progress`` submodule, never react_loop or
react_execution.
"""

from __future__ import annotations

import contextlib
import logging

from runtime.core.cerebrum._react_execution_progress import (
    _build_progress_summary,
    _detect_phase,
    _update_working_set,
)
from runtime.core.cerebrum.react_context import (
    _compress_context,
    _serialize_messages_for_checkpoint,
    context_budget_tokens_for_model,
)
from runtime.core.cerebrum.react_loop_state import (
    _LoopControl,
    _LoopState,
)
from runtime.core.cerebrum.react_types import REACT_OBSERVATION_FOLLOWUP
from runtime.platform.models.llm import Message

_logger = logging.getLogger(__name__)


def _phase_6g_housekeeping(state: _LoopState, *, i: int, max_iterations: int) -> _LoopControl:
    """Loop-tail housekeeping: plan-exit, checkpoints, msg append, compress.

    Moved verbatim from ``react_loop.py`` (PHASE 6g). Returns ``BREAK``
    when a final answer terminates the turn (Python ``break`` in the
    original), otherwise ``CONTINUE`` so the loop proceeds to the next
    iteration. No yields — plain function, not a generator.
    """
    # Reference-typed aliases — mutations propagate to the main loop.
    steps = state.steps
    final_answer_segments = state.final_answer_segments
    messages = state.messages
    _working_set = state.working_set
    stack = state.stack
    react_task_id = state.react_task_id
    router = state.router
    thread_id = state.thread_id
    resp = state.resp
    step = state.step
    _pause = state.pause_controller
    # Scalar pulls — original local names; pushed back in the finally.
    planning_mode = state.planning_mode
    enable_tools = state.enable_tools
    executor = state.executor
    tools_active = state.tools_active
    maybe_final = state.maybe_final
    final_answer = state.final_answer
    final_answer_emitted = state.final_answer_emitted
    terminated_reason = state.terminated_reason
    effective_model = state.effective_model
    _current_phase = state.current_phase
    _progress_summary = state.progress_summary
    _force_convergence_next = state.force_convergence_next
    _length_limit_should_continue = state.length_limit_should_continue
    _is_code_mode = state.is_code_mode
    _native_mode = state.native_mode
    _observed_read_sequence = state.observed_read_sequence
    _length_limited = state.length_limited
    _final_delta_emitted_this_iteration = state.final_delta_emitted_this_iteration
    text = state.text
    _agent_id_for_pause = state.agent_id_for_pause
    try:
        # Mid-turn plan exit: model called exit_plan_mode and user approved.
        # Switch from "plan only" to "execute" without ending the turn.
        if planning_mode:
            try:
                from runtime.platform.process.session import current_session as _cs_plan

                _session_obj = _cs_plan()
            except (ImportError, AttributeError):  # noqa: BLE001
                _session_obj = None
            if (
                _session_obj is not None
                and _session_obj.metadata is not None
                and _session_obj.metadata.pop("_plan_mode_exit_approved", False)
            ):
                planning_mode = False
                enable_tools = True
                executor = getattr(stack, "executor", None)
                tools_active = executor is not None
                _logger.info(
                    "plan_mode exited mid-turn; continuing execution in same turn",
                )

        if _is_code_mode and step.action and step.action.lower() not in {"none", "n/a", ""}:
            _update_working_set(_working_set, step, _current_phase)
            _current_phase = _detect_phase(step, _current_phase)
            _progress_summary = _build_progress_summary(steps, _working_set, _current_phase)

        _has_real_observation = bool(step.observation and step.observation != "N/A")
        _has_response_tool_calls = bool(getattr(resp, "tool_calls", None))
        _length_limit_should_continue = _length_limited and not (
            _has_response_tool_calls or _has_real_observation
        )
        _checkpoint_has_final = maybe_final is not None and not _length_limit_should_continue
        if react_task_id is not None and _checkpoint_has_final:
            _ckpt_journal = getattr(stack, "journal", None)
            if _ckpt_journal is not None and hasattr(_ckpt_journal, "write_react_checkpoint"):
                try:
                    from runtime.platform.models import ArmId

                    _ckpt_journal.write_react_checkpoint(
                        react_task_id,
                        arm_id=ArmId("react_arm"),
                        iteration_completed=i + 1,
                        max_iterations=max_iterations,
                        messages_snapshot=_serialize_messages_for_checkpoint(messages),
                        steps_snapshot=[
                            {
                                "iteration": s.iteration,
                                "thought": s.thought,
                                "public_update": s.public_update,
                                "action": s.action,
                                "observation": s.observation,
                            }
                            for s in steps
                        ],
                        has_final_answer=_checkpoint_has_final,
                        final_answer=maybe_final if _checkpoint_has_final else "",
                        working_set_snapshot=list(_working_set.values()),
                        progress_summary=_progress_summary,
                        current_phase=_current_phase,
                    )
                except (OSError, TypeError):
                    _logger.debug("checkpoint write failed", exc_info=True)
        if maybe_final and _length_limit_should_continue:
            final_answer_segments.append(maybe_final)
            maybe_final = None

        if maybe_final:
            if final_answer_segments:
                final_answer = "".join(final_answer_segments + [maybe_final])
                final_answer_segments.clear()
            else:
                final_answer = maybe_final
            # A guarded long-task answer may have been intentionally buffered
            # until every completion gate passed.  Only suppress the final
            # emitter when this iteration actually yielded answer text.
            final_answer_emitted = _final_delta_emitted_this_iteration
            terminated_reason = "final_answer"
            return _LoopControl.BREAK

        if (
            react_task_id is not None
            and max_iterations >= 15
            and (max_iterations - (i + 1)) <= 3
            and not _pause.is_pause_requested(str(react_task_id))
        ):
            remaining = max_iterations - (i + 1)
            _logger.info(
                "react_loop auto-pause at iter %d · task %s · %d left · "
                "will checkpoint next loop top",
                i + 1,
                react_task_id,
                remaining,
            )
            _pause.request_pause(
                task_id=str(react_task_id),
                reason="iteration_near_limit",
                requested_by="system",
                note=(
                    f"自动暂停 · 已跑 {i + 1}/{max_iterations} 轮 · "
                    f"剩余 {remaining} 轮 · 点继续并加预算可接续"
                ),
                thread_id=thread_id or "",
                agent_id=_agent_id_for_pause,
            )

        _assistant_content = text
        if _native_mode and not _assistant_content and step.action:
            # Native tool-use turns often carry no prose — record the
            # synthesised action so the history isn't an (API-invalid) empty
            # assistant message and the model can see what it just called.
            _assistant_content = step.action
        messages.append(Message(role="assistant", content=_assistant_content))
        # Length-limit continuation. When the upstream model truncated
        # its response (finish_reason=="length" / "max_tokens" / etc.)
        # the assistant message we just appended is mid-sentence — the
        # model itself doesn't know it stopped early, so on the NEXT
        # iteration it will either repeat work or give up and write a
        # short summary. Inject a user message asking it to continue
        # exactly where it left off so long-form generation (research
        # reports, code files, plans) can finish across multiple
        # iterations without the user seeing a half-finished doc.
        if _length_limit_should_continue:
            _code_action_recovery = _is_code_mode and not final_answer_segments
            if _code_action_recovery:
                _force_convergence_next = True
                _length_recovery_prompt = (
                    "Your previous code-task response hit the output limit before producing an "
                    "executable action. Do not continue or repeat the prose analysis. Extended "
                    "thinking is disabled for this recovery round. Emit exactly one concrete next "
                    "Action: skill_name({JSON}) now; prefer the required source/test mutation, or "
                    "the smallest targeted verifier if the implementation is already written."
                )
            else:
                _length_recovery_prompt = (
                    "Your previous response was cut off by the output "
                    "length limit. Continue exactly where it stopped — "
                    "do NOT repeat earlier text, do NOT restart the "
                    "report, do NOT switch to writing a summary or "
                    "calling todo_write. Resume from the exact "
                    "character you stopped at and finish every "
                    "remaining section."
                )
            messages.append(
                Message(
                    role="user",
                    content=_length_recovery_prompt,
                )
            )
            _logger.info(
                "react_loop iter %d · finish_reason=length, injecting continue prompt",
                i + 1,
            )
        elif step.observation and step.observation != "N/A":
            # TokenJuice: compress the observation before it enters
            # the message stream so the next LLM round sees a leaner
            # version. The full observation is preserved in
            # step.observation for journal / display / guards. On
            # by default — opt out via OCTOPUS_TOKEN_JUICE=0.
            _obs_for_model = step.observation
            try:
                from runtime.core.cerebrum.token_juicer import (
                    is_enabled as _juice_enabled,
                )
                from runtime.core.cerebrum.token_juicer import (
                    juice as _juice,
                )

                if _observed_read_sequence or _juice_enabled():
                    _juiced, _stats = _juice(
                        step.observation,
                        max_chars=6000,
                    )
                    if _stats.passes:
                        _obs_for_model = _juiced
                        (_logger.info if _observed_read_sequence else _logger.debug)(
                            "token_juice iter %d · %d→%d chars (%.1f%% saved) passes=%s",
                            i + 1,
                            _stats.before,
                            _stats.after,
                            (1 - _stats.ratio) * 100,
                            ",".join(_stats.passes),
                        )
            except (ImportError, ValueError, TypeError):
                _logger.debug("token_juice unavailable", exc_info=True)
            messages.append(
                Message(
                    role="user",
                    content=(f"Observation: {_obs_for_model}\n\n{REACT_OBSERVATION_FOLLOWUP}"),
                )
            )

        messages = _compress_context(
            messages,
            max_tokens=context_budget_tokens_for_model(effective_model),
            router=router,
            model=effective_model,
            is_code_mode=_is_code_mode,
        )

        with contextlib.suppress(Exception):
            _pause.update_active_iteration(str(react_task_id), i + 1)
        return _LoopControl.CONTINUE
    finally:
        state.planning_mode = planning_mode
        state.enable_tools = enable_tools
        state.executor = executor
        state.tools_active = tools_active
        state.maybe_final = maybe_final
        state.final_answer = final_answer
        state.final_answer_emitted = final_answer_emitted
        state.terminated_reason = terminated_reason
        state.current_phase = _current_phase
        state.progress_summary = _progress_summary
        state.force_convergence_next = _force_convergence_next
        state.length_limit_should_continue = _length_limit_should_continue
        state.messages = messages

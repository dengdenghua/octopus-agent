"""In-flight nudges for the ReAct main loop (PHASE 6e, first half).

Moved from ``react_loop.py``: the soft guards that fire DURING the
loop, not at Final Answer time — background-task heartbeat,
completion / verification / code-semantic / green-verification
trackers, and the once-per-turn context-pressure signal. Each nudge
appends a short reminder to the current step's observation so the
model sees it before composing the next action. All are silent when
the model is already doing the right thing.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from runtime.core.cerebrum.react_execution import (
    _background_task_info_from_observation,
    _format_background_task_heartbeat,
)
from runtime.core.cerebrum.react_guards import (
    _code_semantic_followup_guard,
    _completion_phrase_without_todo_guard,
    _failed_verification_followup_guard,
    _redundant_green_verification_guard,
    _unverified_write_followup_guard,
)
from runtime.core.cerebrum.react_loop_controls import (
    _CONTEXT_PRESSURE_NUDGE,
    _estimate_context_fullness,
)
from runtime.core.cerebrum.react_types import ReActStep

_logger = logging.getLogger(__name__)


class _InFlightNudgeFlags(NamedTuple):
    """Post-nudge values of the three loop flags this block can flip."""

    context_pressure_signaled: bool
    green_verification_convergence_active: bool
    force_convergence_next: bool


def _apply_in_flight_nudges(
    *,
    steps: list,
    step: ReActStep,
    i: int,
    known_background_tasks: dict,
    todo_protocol_required: bool,
    todo_protocol_visible: bool,
    is_code_mode: bool,
    messages: list,
    effective_model: str,
    context_pressure_signaled: bool,
    green_verification_convergence_active: bool,
    force_convergence_next: bool,
) -> _InFlightNudgeFlags:
    """Append any due in-flight nudges to ``step.observation``.

    Mutates ``step.observation`` and ``known_background_tasks`` in
    place; returns the post-state of the three loop flags for the
    caller to unpack.
    """
    # ── In-flight nudges (octopus optimisation §15 + §18) ───
    # Two soft guards that fire DURING the loop, not at Final
    # Answer time. They append a short reminder to this step's
    # observation so the model sees it before composing the
    # next action. Both are silent when the model is already
    # doing the right thing.
    _steps_with_current = steps + [step]
    _midflight_nudges: list[str] = []
    # Track any background process snapshot present in this
    # step's observation so the periodic heartbeat below can
    # remind the model about live processes.
    _bg_task_info = _background_task_info_from_observation(step.observation)
    if _bg_task_info is not None:
        _bg_task_id = _bg_task_info.get("task_id")
        if isinstance(_bg_task_id, str) and _bg_task_id:
            known_background_tasks[_bg_task_id] = _bg_task_info
    # Heartbeat: every 5 iterations (i > 0 and i % 5 == 0),
    # if we have any registered background tasks, append a
    # reminder to the NEXT step's observation injection.
    if i > 0 and i % 5 == 0 and known_background_tasks:
        _midflight_nudges.append(
            _format_background_task_heartbeat(list(known_background_tasks.keys()))
        )
    _completion_nudge = _completion_phrase_without_todo_guard(
        _steps_with_current,
        todo_protocol_required=todo_protocol_required and todo_protocol_visible,
    )
    if _completion_nudge:
        _midflight_nudges.append(f"[completion-tracker]\n{_completion_nudge}")
    _verify_nudge = _unverified_write_followup_guard(
        _steps_with_current,
        is_code_mode=is_code_mode,
    )
    if _verify_nudge:
        _midflight_nudges.append(f"[verification-tracker]\n{_verify_nudge}")
    _red_verify_nudge = _failed_verification_followup_guard(
        _steps_with_current,
        is_code_mode=is_code_mode,
    )
    if _red_verify_nudge:
        _midflight_nudges.append(f"[red-verification-recovery]\n{_red_verify_nudge}")
    _concurrency_nudge = _code_semantic_followup_guard(
        _steps_with_current,
        is_code_mode=is_code_mode,
    )
    if _concurrency_nudge:
        _midflight_nudges.append(f"[code-semantic-repair]\n{_concurrency_nudge}")
    _green_verify_nudge = _redundant_green_verification_guard(
        _steps_with_current,
        is_code_mode=is_code_mode,
    )
    if _green_verify_nudge:
        _midflight_nudges.append(f"[green-verification-convergence]\n{_green_verify_nudge}")
        green_verification_convergence_active = True
        force_convergence_next = True
    # Context-pressure signal — fires once per turn when the rolling
    # message list approaches the model's context budget. Gives the
    # model a chance to write a "resume state" hand-off paragraph
    # before _compress_context starts dropping older steps.
    if not context_pressure_signaled:
        _ctx_ratio = _estimate_context_fullness(messages, effective_model)
        if _ctx_ratio > 0.70:
            _midflight_nudges.append(_CONTEXT_PRESSURE_NUDGE.format(level=f"{_ctx_ratio:.0%}"))
            context_pressure_signaled = True
    if _midflight_nudges:
        step.observation = (
            ((step.observation or "") + "\n\n") if step.observation else ""
        ) + "\n\n".join(_midflight_nudges)
    return _InFlightNudgeFlags(
        context_pressure_signaled=context_pressure_signaled,
        green_verification_convergence_active=green_verification_convergence_active,
        force_convergence_next=force_convergence_next,
    )

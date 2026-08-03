"""PHASE 6d — pre-dispatch guard cluster for the ReAct loop.

Extracted from ``_react_execution_phase6d.py`` (Wave 2b). Implements
``_phase_6d_pre_dispatch_guards``: the block of approval/guard checks that
run *before* a step's action(s) are dispatched. It deduplicates batched
actions, bounds explicit large reads, applies the repeated-failure /
repeated-noop / evidence-convergence / todo-protocol / semantic-repair /
green-verification suppressors, and returns the scalar locals the caller
must push back onto its loop state. ``step`` is mutated in place.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.core.cerebrum.react_convergence import (
    constrain_explicit_read_scope,
)
from runtime.core.cerebrum.react_explicit_reads import (
    _bound_explicit_large_reads,
)
from runtime.core.cerebrum.react_guards import (
    _code_semantic_followup_guard,
    _goal_requests_code_mutation,
)
from runtime.core.cerebrum.react_parsing import (
    _has_code_verification,
    _is_code_write_step,
    _parse_action,
)
from runtime.core.cerebrum.react_types import ReActStep
from runtime.core.cerebrum.todo_protocol import (
    _todo_completion_before_write_guard,
    _todo_prewrite_guard,
)
from runtime.platform.models import Step


def _phase_6d_pre_dispatch_guards(
    step: ReActStep,
    steps: list[ReActStep],
    intent: Any,
    i: int,
    *,
    tools_active: bool,
    _effective_wp: Any,
    _read_only_turn: bool,
    _observed_read_sequence: Any,
    _consecutive_same_failed_actions: int,
    _last_failed_action_fingerprint: str,
    _consecutive_same_noop_actions: int,
    _last_noop_action_fingerprint: str,
    _evidence_convergence_active: Any,
    _todo_protocol_required: bool,
    _is_goal_mode: bool,
    _todo_protocol_visible: bool,
    _is_code_mode: bool,
    _green_verification_convergence_active: bool,
    _green_convergence_todo_used: bool,
    maybe_final: Any,
    _force_convergence_next: bool,
    _deduplicate_actions: Callable[..., Any],
    _action_batch_fingerprint: Callable[..., str],
) -> tuple[Any, ...]:
    """Run the pre-dispatch guards and return the updated scalar locals.

    ``step`` is mutated in place. The returned tuple carries, in order:
    ``observation``, ``resolved_name``, ``action_args``, ``beak_step``,
    ``tool_ok``, ``tool_action_requested``, ``maybe_final``,
    ``_force_convergence_next``, ``_green_convergence_todo_used``,
    ``_duplicate_action_count``, ``_explicit_read_scope_note``,
    ``_current_action_fingerprint``, ``_repeated_failure_skipped``,
    ``_repeated_noop_skipped``.
    """
    observation: str | None = step.observation or None
    resolved_name: str | None = None
    action_args: dict[str, Any] | None = None
    beak_step: Step | None = None
    tool_ok = False
    tool_action_requested = (
        tools_active and step.action and step.action.lower() not in {"none", "n/a", ""}
    )
    _duplicate_action_count = 0
    _explicit_read_scope_note = ""
    if tool_action_requested and len(step.actions) > 1:
        step.actions, _duplicate_action_count = _deduplicate_actions(step.actions)
        step.action = "; ".join(step.actions)
        tool_action_requested = bool(step.actions)
    if tool_action_requested:
        _candidate_actions = step.actions or [step.action]
        _candidate_actions = _bound_explicit_large_reads(
            goal=intent.normalized_goal,
            workspace_path=(_effective_wp if isinstance(_effective_wp, str) else None),
            actions=_candidate_actions,
            read_only=_read_only_turn,
        )
        step.actions = _candidate_actions
        step.action = "; ".join(_candidate_actions)
        _scope_constraint = constrain_explicit_read_scope(
            goal=intent.normalized_goal,
            steps=steps,
            actions=_candidate_actions,
            read_only=_read_only_turn,
            enforce_order=_observed_read_sequence,
        )
        if _scope_constraint is not None:
            step.actions = list(_scope_constraint.actions)
            step.action = "; ".join(step.actions)
            _explicit_read_scope_note = _scope_constraint.observation_note()
            tool_action_requested = bool(step.actions)
            if not tool_action_requested:
                observation = _explicit_read_scope_note
                step.observation = observation
                maybe_final = None
    _current_action_fingerprint = ""
    _repeated_failure_skipped = False
    if tool_action_requested:
        _current_action_fingerprint = _action_batch_fingerprint(step.actions or [step.action])
        if (
            _consecutive_same_failed_actions >= 2
            and _current_action_fingerprint == _last_failed_action_fingerprint
        ):
            observation = (
                "[repeated-failing-tool-skipped] The same tool call or ordered tool batch "
                "with identical arguments already failed twice, so the runtime did not "
                "execute it a third time. Treat the prior failure as definitive. Choose a different "
                "action: for a missing file, create it with an allowed write tool; for "
                "invalid arguments, correct them; otherwise use a different evidence source."
            )
            step.observation = observation
            step.action = ""
            step.actions = []
            tool_action_requested = False
            maybe_final = None
            _repeated_failure_skipped = True
    _repeated_noop_skipped = False
    if (
        tool_action_requested
        and not _repeated_failure_skipped
        and _consecutive_same_noop_actions >= 2
        and _current_action_fingerprint == _last_noop_action_fingerprint
    ):
        observation = (
            "[repeated-noop-tool-skipped] The same tool call with identical "
            "arguments already ran twice but produced no effect (ok=True but "
            "empty/zero-count result). The runtime did not execute it a third "
            "time. The arguments are likely under a wrong key — re-read the "
            "tool description and re-issue with the correct parameter names."
        )
        step.observation = observation
        step.action = ""
        step.actions = []
        tool_action_requested = False
        maybe_final = None
        _repeated_noop_skipped = True
    if _evidence_convergence_active is not None and tool_action_requested:
        observation = (
            "The read-only evidence requested by the user is already complete, so "
            "the runtime did not execute this additional tool call. Answer now from "
            "the recorded observations; do not broaden the search or call another tool."
        )
        step.observation = observation
        step.action = ""
        step.actions = []
        tool_action_requested = False
        maybe_final = None
        _force_convergence_next = True
    if tool_action_requested:
        _todo_prewrite_message = _todo_prewrite_guard(
            step.actions or [step.action],
            steps,
            # Keep bounded inspections and one-command probes lightweight.
            # ReAct's plan-first gate applies to genuinely long or explicit
            # goal-mode work; the native tool bridge enforces its own
            # equivalent bootstrap from the shared protocol classifier.
            required=(
                _todo_protocol_required
                and (
                    _is_goal_mode
                    or "\n" in intent.normalized_goal
                    or len(intent.normalized_goal) >= 80
                )
            ),
            visible=_todo_protocol_visible,
        )
        if _todo_prewrite_message:
            observation = _todo_prewrite_message
            step.observation = observation
            step.action = ""
            step.actions = []
            tool_action_requested = False
            maybe_final = None
    if _is_code_mode and tool_action_requested:
        _premature_todo_completion = _todo_completion_before_write_guard(
            step.actions or [step.action],
            steps,
            required=_goal_requests_code_mutation(intent.normalized_goal),
        )
        if _premature_todo_completion:
            observation = _premature_todo_completion
            step.observation = observation
            step.action = ""
            step.actions = []
            tool_action_requested = False
            maybe_final = None
    if _is_code_mode and tool_action_requested:
        # A deterministic source-level concurrency defect is stronger
        # evidence than another green/red probe.  Do not let providers
        # evade the repair instruction by cycling through pytest, lint,
        # typecheck, or shell variants.  Reads and actual code writes stay
        # available; a write+verify batch is also allowed because the
        # ordered outcome tracker will evaluate the post-repair checks.
        _semantic_repair = _code_semantic_followup_guard(
            steps,
            is_code_mode=True,
        )
        if _semantic_repair:
            _candidate_steps = [
                ReActStep(iteration=i + 1, action=_candidate)
                for _candidate in (step.actions or [step.action])
            ]
            _candidate_has_write = any(
                _is_code_write_step(_candidate_step) for _candidate_step in _candidate_steps
            )
            _candidate_has_verifier = any(
                _has_code_verification([_candidate_step])
                for _candidate_step in _candidate_steps
            )
            if _candidate_has_verifier and not _candidate_has_write:
                observation = (
                    "[semantic-repair-tool-skipped] A deterministic source defect "
                    "is still present in the latest source edit, so the runtime did not "
                    "execute another verifier or shell probe. Repair the source first.\n"
                    + _semantic_repair
                )
                step.observation = observation
                step.action = ""
                step.actions = []
                tool_action_requested = False
                maybe_final = None
                _force_convergence_next = True
    if _green_verification_convergence_active and tool_action_requested:
        _candidate_actions = step.actions or [step.action]
        _candidate_names = []
        for _candidate_action in _candidate_actions:
            _candidate_parsed = _parse_action(_candidate_action)
            if _candidate_parsed is not None:
                _candidate_names.append(_candidate_parsed[0])
        _allow_one_todo = (
            bool(_candidate_names)
            and all(name == "todo_write" for name in _candidate_names)
            and not _green_convergence_todo_used
        )
        if _allow_one_todo:
            _green_convergence_todo_used = True
        else:
            # Two independent green verification rounds after the latest
            # write are sufficient evidence. Re-running read/test/lint or
            # shell probes only burns the turn budget and can turn a valid
            # implementation into a timeout. Suppress those actions while
            # preserving one checklist-finalization opportunity.
            observation = (
                "[redundant-tool-skipped] Two separate verification rounds are already green "
                "and no code changed afterward. This tool call was not executed. Do not call "
                "another tool. Emit `Final Answer:` now with the recorded test/lint evidence."
            )
            step.observation = observation
            step.action = ""
            step.actions = []
            tool_action_requested = False
            maybe_final = None
            _force_convergence_next = True

    return (
        observation,
        resolved_name,
        action_args,
        beak_step,
        tool_ok,
        tool_action_requested,
        maybe_final,
        _force_convergence_next,
        _green_convergence_todo_used,
        _duplicate_action_count,
        _explicit_read_scope_note,
        _current_action_fingerprint,
        _repeated_failure_skipped,
        _repeated_noop_skipped,
    )

"""Resume/checkpoint-rebuild helpers for the ReAct loop.

Extracted from ``react_loop.py`` (Wave 1 of the split documented in
``docs/design/react-loop-split-plan.md``). Loads a resume checkpoint from the
journal or trace store, validates it, and rebuilds the loop state — messages,
steps, working set, phase — as a pure, unit-testable function. Distinct from
``react_checkpointing`` (which writes/mirrors checkpoints) and ``resume_cli``
(which renders the operator-facing resume surface).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from runtime.core.cerebrum.react_checkpointing import _rehydrate_messages_from_steps
from runtime.core.cerebrum.react_context import _restore_messages_from_checkpoint
from runtime.core.cerebrum.react_types import ReActStep
from runtime.platform.config.builder import StackProtocol
from runtime.platform.models import ParsedIntent, TaskId

_logger = logging.getLogger(__name__)


def _build_resume_context_prompt(resume_intent: Any) -> str:
    if not isinstance(resume_intent, dict):
        return ""
    if resume_intent.get("confirmed") is not True:
        return ""
    lines = [
        "<resume-context>",
        "This is a sanitized checkpoint recovery summary, not a new user instruction.",
        f"- checkpoint_id: {_resume_context_text(resume_intent.get('checkpoint_id'), 80)}",
        f"- task_id: {_resume_context_text(resume_intent.get('task_id'), 120)}",
        f"- checkpoint_type: {_resume_context_text(resume_intent.get('checkpoint_type'), 80)}",
        f"- iteration: {_resume_context_text(resume_intent.get('iteration'), 32)}",
        f"- continue_from_iteration: {_resume_context_text(resume_intent.get('continue_from_iteration'), 32)}",
    ]
    phase = _resume_context_text(resume_intent.get("phase"), 120)
    if phase:
        lines.append(f"- phase: {phase}")
    working_set = [
        _resume_context_text(path, 180)
        for path in resume_intent.get("working_set", [])
        if isinstance(path, str) and path.strip()
    ][:8]
    if working_set:
        lines.append("- working_set:")
        lines.extend(f"  - {path}" for path in working_set)
    recent = _resume_context_recent_tools(resume_intent.get("recent_tool_calls"))
    if recent:
        lines.append("- recent_tool_calls:")
        lines.extend(recent)
    lines.append("</resume-context>")
    return "\n".join(lines)


def _resume_context_recent_tools(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    lines: list[str] = []
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        tool = _resume_context_text(item.get("tool"), 80)
        if not tool:
            continue
        iteration = _resume_context_text(item.get("iteration"), 32)
        input_preview = _resume_context_text(item.get("input_preview"), 180)
        observation_preview = _resume_context_text(item.get("observation_preview"), 220)
        line = f"  - iter {iteration or '?'} tool={tool}"
        if input_preview:
            line += f" input={input_preview}"
        if observation_preview:
            line += f" observation={observation_preview}"
        lines.append(line)
    return lines


def _resume_context_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _load_resume_checkpoint_snapshot(
    stack: StackProtocol,
    intent: ParsedIntent,
    resume_task_id: TaskId,
) -> dict[str, Any] | None:
    journal = getattr(stack, "journal", None)
    if journal is not None:
        ckpts = [
            e
            for e in journal.read_by_type("react_checkpoint")
            if str(getattr(e, "task_id", "")) == str(resume_task_id)
        ]
        if ckpts:
            return _checkpoint_snapshot_from_journal_event(ckpts[-1])
    return _load_trace_resume_checkpoint_snapshot(intent, resume_task_id)


def _checkpoint_snapshot_from_journal_event(event: Any) -> dict[str, Any]:
    return {
        "source": "journal",
        "iteration_completed": int(getattr(event, "iteration_completed", 0) or 0),
        "max_iterations": int(getattr(event, "max_iterations", 0) or 0),
        "messages_snapshot": getattr(event, "messages_snapshot", []) or [],
        "steps_snapshot": getattr(event, "steps_snapshot", []) or [],
        "has_final_answer": bool(getattr(event, "has_final_answer", False)),
        "final_answer": str(getattr(event, "final_answer", "") or ""),
        "working_set_snapshot": getattr(event, "working_set_snapshot", []) or [],
        "progress_summary": str(getattr(event, "progress_summary", "") or ""),
        "current_phase": str(getattr(event, "current_phase", "") or ""),
    }


def _load_trace_resume_checkpoint_snapshot(
    intent: ParsedIntent,
    resume_task_id: TaskId,
) -> dict[str, Any] | None:
    resume_intent = (intent.user_context or {}).get("resume_intent")
    if not isinstance(resume_intent, dict):
        return None
    checkpoint_id = resume_intent.get("checkpoint_id")
    if not isinstance(checkpoint_id, int) or checkpoint_id <= 0:
        return None
    try:
        from runtime.platform.process.session import current_session

        session = current_session()
    except (ImportError, AttributeError):
        session = None
    metadata = getattr(session, "metadata", None) if session is not None else None
    trace_store = metadata.get("_trace_store") if isinstance(metadata, dict) else None
    if trace_store is None or not hasattr(trace_store, "checkpoint_by_id"):
        return None
    checkpoint = trace_store.checkpoint_by_id(checkpoint_id)
    if not isinstance(checkpoint, dict):
        return None
    if str(checkpoint.get("task_id") or "") != str(resume_task_id):
        return None
    if str(checkpoint.get("checkpoint_type") or "").lower() != "react":
        return None
    _state_raw = checkpoint.get("state")
    state: dict[str, Any] = _state_raw if isinstance(_state_raw, dict) else {}
    return {
        "source": "trace_store",
        "iteration_completed": int(
            state.get("iteration_completed")
            or checkpoint.get("iteration")
            or resume_intent.get("iteration")
            or 0
        ),
        "max_iterations": int(state.get("max_iterations") or 0),
        "messages_snapshot": state.get("messages_snapshot")
        if isinstance(state.get("messages_snapshot"), list)
        else [],
        "steps_snapshot": state.get("steps_snapshot")
        if isinstance(state.get("steps_snapshot"), list)
        else [],
        "has_final_answer": bool(state.get("has_final_answer") is True),
        "final_answer": str(state.get("final_answer") or ""),
        "working_set_snapshot": state.get("working_set_snapshot")
        if isinstance(state.get("working_set_snapshot"), list)
        else [],
        "progress_summary": str(state.get("progress_summary") or checkpoint.get("summary") or ""),
        "current_phase": str(state.get("current_phase") or ""),
    }


@dataclass
class _ResumeState:
    """Loop state rebuilt from a resume checkpoint. Aggregating the ~9 values
    PHASE 5 used to assign inline lets the rebuild live in a pure, unit-testable
    function (``_compute_resume_state``) instead of being welded into the loop's
    closure."""

    resume_from_iter: int
    messages: list[Any]
    steps: list[ReActStep]
    working_set: dict[str, dict[str, Any]]
    progress_summary: str
    current_phase: str
    final_answer: str | None
    terminated_reason: str
    resume_event: dict[str, Any]


def _compute_resume_state(
    stack: StackProtocol,
    intent: ParsedIntent,
    resume_task_id: TaskId,
    *,
    base_messages: list[Any],
    base_working_set: dict[str, dict[str, Any]],
    base_progress_summary: str,
    base_current_phase: str,
    max_iterations: int,
) -> _ResumeState | None:
    """Load + validate a resume checkpoint and rebuild loop state from it.

    Pure except for logging: no ``yield``, no mutation of caller state. Returns
    ``None`` when there is nothing to resume (the caller keeps its defaults).
    Raises ``ValueError`` on an unsafe checkpoint — the caller catches it (along
    with the AttributeError/KeyError/TypeError a malformed snapshot can raise)
    and falls back to a fresh run.
    """
    last = _load_resume_checkpoint_snapshot(stack, intent, resume_task_id)
    if last is None:
        return None

    from runtime.core.cerebrum.checkpoint_integrity import validate_checkpoint_state

    checkpoint_iteration = int(last["iteration_completed"] or 0)
    integrity = validate_checkpoint_state(
        {
            "messages_snapshot": last["messages_snapshot"],
            "steps_snapshot": last["steps_snapshot"],
            "working_set_snapshot": last["working_set_snapshot"],
            "progress_summary": last["progress_summary"],
            "current_phase": last["current_phase"],
        },
        iteration=checkpoint_iteration,
    )
    if not integrity.resume_safe:
        _logger.warning(
            "react_loop resume checkpoint rejected (task %s): %s",
            resume_task_id,
            ", ".join(integrity.errors),
        )
        raise ValueError("unsafe checkpoint")

    resume_from_iter = checkpoint_iteration
    messages = base_messages
    steps: list[ReActStep] = []
    working_set = base_working_set
    progress_summary = base_progress_summary
    current_phase = base_current_phase
    final_answer: str | None = None
    terminated_reason = "max_iter"

    if last["messages_snapshot"]:
        messages = _restore_messages_from_checkpoint(last["messages_snapshot"])
    if last["steps_snapshot"]:
        steps = [
            ReActStep(
                iteration=s.get("iteration", 0),
                thought=s.get("thought", ""),
                public_update=s.get("public_update", ""),
                action=s.get("action", ""),
                observation=s.get("observation", ""),
            )
            for s in last["steps_snapshot"]
            if isinstance(s, dict)
        ]
        messages = _rehydrate_messages_from_steps(messages, steps)
    if last["working_set_snapshot"]:
        working_set = {
            f["path"]: f
            for f in last["working_set_snapshot"]
            if isinstance(f, dict) and f.get("path")
        }
    if last["progress_summary"]:
        progress_summary = last["progress_summary"]
    if last["current_phase"]:
        current_phase = last["current_phase"]
    if last["has_final_answer"] and last["final_answer"]:
        final_answer = str(last["final_answer"])
        terminated_reason = "final_answer"
        resume_from_iter = max_iterations

    resume_event = {
        "type": "react_resumed",
        "task_id": str(resume_task_id),
        "checkpoint_iteration": checkpoint_iteration,
        "resume_from_iteration": resume_from_iter,
        "restored_step_count": len(steps),
        "has_final_answer": bool(final_answer),
        "current_phase": current_phase,
        "progress_summary": progress_summary,
        "checkpoint_source": last.get("source"),
    }
    _logger.info(
        "react_loop resuming from iteration %d (task %s, source=%s)",
        resume_from_iter,
        resume_task_id,
        last.get("source"),
    )
    return _ResumeState(
        resume_from_iter=resume_from_iter,
        messages=messages,
        steps=steps,
        working_set=working_set,
        progress_summary=progress_summary,
        current_phase=current_phase,
        final_answer=final_answer,
        terminated_reason=terminated_reason,
        resume_event=resume_event,
    )

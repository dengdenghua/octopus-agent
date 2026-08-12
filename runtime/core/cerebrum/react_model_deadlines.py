"""Model-call deadline machinery for the ReAct loop.

Extracted from ``react_loop.py`` (Wave 1 of the split documented in
``docs/design/react-loop-split-plan.md``). Provider read timeouts only fire
when bytes stop arriving; these helpers bound hidden model thinking with a
wall-clock deadline pumped through a daemon thread, and switch to an
inactivity deadline once user-visible tokens start flowing.
"""

from __future__ import annotations

import contextvars
import queue
import threading
import time
from collections.abc import Callable, Generator
from typing import Any

from runtime.core.cerebrum.react_types import ReActStep

_LENGTH_LIMITED_FINISH_REASONS = frozenset(
    {"length", "max_tokens", "max_output_tokens", "output_limit", "token_limit"}
)


def _model_iteration_timeout_s(config_timeout_s: float | None = None) -> float:
    """Wall-clock ceiling for one hidden model-thinking iteration.

    Provider read timeouts only fire when no bytes arrive. A reasoning model
    can keep sending private thinking forever, so the loop needs its own bound.
    The value is injected from ``config.budget.model_iteration_timeout_s`` by
    the loop; invalid values fall back safely. Precedence: config > 120s.
    """
    if config_timeout_s is not None:
        return max(10.0, min(config_timeout_s, 900.0))
    return 120.0


# Per-stage deadline policy for model rounds. Each entry maps a stage name to
# (ceiling, lower clamp, upper clamp); the model call never exceeds the
# operator's ordinary iteration timeout and never lengthens tiny injected
# deadlines used by deterministic tests. Aggregates the former
# ``_model_recovery_timeout_s`` / ``_model_post_tool_timeout_s`` /
# ``_model_evidence_synthesis_timeout_s`` helpers into one stage-driven policy.
_MODEL_STAGE_TIMEOUT_S: dict[str, tuple[float, float, float]] = {
    # stage -> (ceiling, lower clamp, upper clamp)
    "recovery": (60.0, 10.0, 240.0),
    "post_tool": (90.0, 10.0, 300.0),
    "evidence_synthesis": (120.0, 15.0, 300.0),
}


def _reasoning_only_watchdog_s(*, has_tool_evidence: bool, recovery: bool) -> float | None:
    """Bound post-tool private reasoning before it becomes an idle loop."""
    if not has_tool_evidence:
        return None
    return 30.0 if recovery else 45.0


def _stage_model_timeout_s(base_timeout_s: float, stage: str) -> float:
    """Clamp a model round's timeout to its stage ceiling.

    ``stage`` is one of ``"recovery"`` / ``"post_tool"`` / ``"evidence_synthesis"``.

    - recovery: a shorter ceiling for the no-extended-thinking convergence
      retry. The first model round may legitimately spend time on deep
      reasoning; once it has exceeded its deadline the recovery request is a
      bounded direct-answer attempt, so granting it the full original allowance
      could make one silent turn block for another two minutes.
    - post_tool: a tighter ceiling once the turn already has executable
      evidence.
    - evidence_synthesis: a modest dedicated window for a normal
      evidence-complete answer, keeping it well below the initial deep
      reasoning allowance without treating it as a stall recovery.

    Each ceiling is fixed by the stage, clamped to its range, and never
    lengthens the base timeout (nor tiny injected test deadlines).
    """

    default, lower, upper = _MODEL_STAGE_TIMEOUT_S[stage]
    ceiling = max(lower, min(default, upper))
    return min(base_timeout_s, ceiling)


_MODEL_STREAM_DEADLINE = object()


def _iter_model_stream_with_deadline(
    router: Any,
    request: Any,
    timeout_s: float,
    visible_started: Callable[[], Any],
) -> Generator[Any, None, None]:
    """Pump a blocking model iterator through a hard wall-clock deadline.

    Checking elapsed time inside ``for evt in call_stream(...)`` cannot stop a
    provider that sends no bytes at all: control never returns to the loop.
    A daemon pump keeps the synchronous router contract while the ReAct thread
    waits on a bounded queue.  The copied context preserves actor/tracing data.
    """
    event_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=64)
    stop_event = threading.Event()
    caller_context = contextvars.copy_context()
    _current_cancellation_token: Any = None
    try:
        from runtime.safety.approval.cancellation import (
            current_cancellation_token as _imported_token,
        )

        _current_cancellation_token = _imported_token
    except ImportError:  # pragma: no cover - optional subsystem
        _current_cancellation_token = None

    def _put(kind: str, value: Any) -> None:
        while not stop_event.is_set():
            try:
                event_queue.put((kind, value), timeout=0.1)
                return
            except queue.Full:
                continue

    def _consume() -> None:
        try:
            for event in router.call_stream(request):
                if stop_event.is_set():
                    break
                _put("event", event)
        except Exception as exc:  # pragma: no cover - re-raised in caller
            _put("error", exc)
        finally:
            _put("done", None)

    worker = threading.Thread(
        target=lambda: caller_context.run(_consume),
        name="react-model-stream-pump",
        daemon=True,
    )
    worker.start()
    timeout_s = max(0.0, timeout_s)
    deadline = time.monotonic() + timeout_s
    visible_mode = False
    visible_activity: Any = None
    try:
        while True:
            token = (
                _current_cancellation_token() if _current_cancellation_token is not None else None
            )
            if token is not None and token.is_cancelled:
                return
            current_visible_activity = visible_started()
            if current_visible_activity and (
                not visible_mode or current_visible_activity != visible_activity
            ):
                # Once an answer is visibly streaming, switch from a hard
                # thinking ceiling to an inactivity deadline. Long reports
                # may legitimately exceed the thinking ceiling as long as
                # user-visible tokens continue to arrive.
                visible_mode = True
                visible_activity = current_visible_activity
                deadline = time.monotonic() + timeout_s
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                yield _MODEL_STREAM_DEADLINE
                return
            try:
                kind, value = event_queue.get(timeout=min(0.25, remaining))
            except queue.Empty:
                continue
            if kind == "event":
                yield value
            elif kind == "error":
                raise value
            else:
                return
    finally:
        stop_event.set()


def _collect_model_stream_text_with_deadline(
    router: Any,
    request: Any,
    timeout_s: float,
) -> tuple[str, Any] | object:
    """Collect a tools-disabled synthesis stream without an unbounded call.

    The main ReAct rounds already use the guarded streaming path, but the
    post-loop convergence pass historically fell back to ``router.call``.
    A provider that only hangs on that non-streaming endpoint could therefore
    strand an otherwise completed long task after its final tool.  Reuse the
    same deadline here and switch to an inactivity deadline after answer text
    begins, so long reports can finish while silent/private reasoning cannot
    run forever.
    """
    text_parts: list[str] = []
    final_response = None
    visible_state = {"chars": 0}
    for event in _iter_model_stream_with_deadline(
        router,
        request,
        timeout_s,
        lambda: visible_state["chars"],
    ):
        if event is _MODEL_STREAM_DEADLINE:
            return _MODEL_STREAM_DEADLINE
        if getattr(event, "type", "") == "text_delta":
            delta = str(getattr(event, "delta", "") or "")
            if delta:
                text_parts.append(delta)
                visible_state["chars"] += len(delta)
        elif getattr(event, "type", "") in {"done", "response_end"}:
            final_response = getattr(event, "final", None) or getattr(event, "response", None)
    text = "".join(text_parts).strip()
    if not text and final_response is not None:
        text = str(getattr(final_response, "text", "") or "").strip()
    return text, final_response


def _stage_update_timeout_fallback(steps: list[ReActStep]) -> str:
    """Return a truthful visible handoff when final synthesis times out."""
    updates: list[str] = []
    for step in steps:
        update = (step.public_update or "").strip()
        if update and update not in updates:
            updates.append(update)
    if not updates:
        return (
            "最终汇总模型在收尾时超过了单轮时限。已完成的工具结果和来源仍保留在"
            "过程记录中，但这次无法可靠生成最终答复；点击继续即可从现有进度重新收敛。"
        )
    joined = "\n\n".join(updates[-6:])
    return (
        "最终汇总模型在收尾时超过了单轮时限。以下阶段结论已经在执行过程中确认，"
        "相关来源和工具结果仍保留在过程记录中；这不是完整最终报告，点击继续可直接"
        "从现有进度重新收敛。\n\n"
        f"{joined}"
    )


def _model_stall_handoff_answer(steps: list[ReActStep]) -> str:
    """Graceful degradation when the model stalls mid-turn.

    Instead of emitting a ``react_error`` event (which the gateway treats as a
    turn failure and shows a system error banner), surface a friendly handoff
    as ordinary answer text.  The turn still ends, but the user sees a natural
    message — like a thoughtful person pausing mid-conversation — and can click
    "继续" to resume from the preserved progress.
    """
    # Collect any public stage conclusions so the handoff carries real content,
    # not just an apology.  A turn that already did substantial work should
    # surface what it found before handing off.
    updates: list[str] = []
    for step in steps:
        update = (step.public_update or "").strip()
        if update and update not in updates:
            updates.append(update)

    # Count completed tool calls so the user knows progress was made.
    completed_tools = sum(
        1 for step in steps if (step.action or "").strip() and (step.observation or "").strip()
    )

    if updates:
        joined = "\n\n".join(updates[-4:])
        return (
            "我正在思考下一步，但这一轮响应比较慢。前面已经做了一些工作，"
            "以下是目前的进展：\n\n"
            f"{joined}\n\n"
            "点击继续，我会从当前进度接着完成。"
        )
    if completed_tools > 0:
        return (
            f"我正在思考下一步，但这一轮响应比较慢。前面已经完成了 {completed_tools} 步操作，"
            "结果都已保留。点击继续，我会从当前进度接着完成。"
        )
    return "我正在思考，但这一轮响应比较慢。点击继续，我会重新梳理并给出回复。"


def _finish_reason_is_length_limited(reason: str | None) -> bool:
    """True when ``finish_reason`` signals the model was cut off by the output
    token ceiling rather than finishing on its own. Centralizes the set that
    PHASE 6c previously inlined in two identical places."""
    return (reason or "").strip().lower() in _LENGTH_LIMITED_FINISH_REASONS

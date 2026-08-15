"""Drive a sub-agent through the MAIN react loop.

The end-state model treats a dispatched sub-agent as its OWN thread running
the same ``stream_react_loop`` machinery as the main conversation — instead of
a bespoke mini-loop. This module is that bridge: it builds a sub-agent
``ParsedIntent``, runs ``stream_react_loop`` on the shared stack, and forwards
the loop's events onto the typed sub-agent event bus + parent emitter so the
workbench independent stream renders it exactly like a first-class thread.

The react loop is synchronous (LLM calls happen inside), so this driver runs
in the caller's worker thread just like the existing ephemeral runner. It is
deliberately additive: callers opt in via ``react_loop_subagent`` in the
sub-agent context, and the legacy mini-loop remains the safe default until the
realtime server is wired to pass its live stack.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from runtime.core.cerebrum.react_loop import ReActResult, stream_react_loop
from runtime.platform.models import ParsedIntent

try:
    from runtime.safety.approval.approval_gate import (
        ApprovalProvider,
        AutoApproveProvider,
    )
except ImportError:  # pragma: no cover - optional import at runtime
    ApprovalProvider = Any  # type: ignore[misc,assignment]
    AutoApproveProvider = Any  # type: ignore[misc,assignment]

_TERMINAL_KINDS = frozenset(
    {"react_completed", "react_cancelled", "react_error", "react_paused"},
)


def build_subagent_intent(
    prompt: str,
    *,
    role_id: str,
    model: str,
    thread_id: str,
    conversation_messages: Iterable[dict[str, Any]] | None = None,
    tool_allowlist: Iterable[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ParsedIntent:
    """Build a sub-agent ``ParsedIntent`` the react loop can drive.

    The prompt is the user turn; the role persona/memory are carried in
    ``conversation_messages`` (the parent already glues role context together
    in ``call.composed_system_prompt``) and the per-role tool allowlist rides
    in ``user_context`` so the executor gates the sub-agent's tool surface.
    ``auto_approve`` mirrors the ephemeral runner's bypass — sub-agents run
    headless without a human approval prompt.
    """
    metadata = dict(metadata or {})
    user_context: dict[str, Any] = {
        "metadata": metadata,
        "mode": "react",
        "model_name": model,
        "workspace_path": str(metadata.get("workspace_path") or ""),
        "thread_id": thread_id,
        "auto_approve": True,
        "conversation_messages": list(conversation_messages or []),
    }
    if tool_allowlist:
        user_context["tool_allowlist"] = list(tool_allowlist)
    return ParsedIntent(
        raw=prompt,
        intent_type="task",
        normalized_goal=prompt,
        user_context=user_context,
    )


def _react_tool_call(event: dict[str, Any]) -> Any:
    """Wrap a react ``tool_start``/``tool_end`` event as a call-like object
    the ephemeral emit helpers understand (they read ``id`` / ``name``)."""
    return _SimpleToolCall(
        call_id=str(event.get("tool_call_id") or ""),
        name=str(event.get("tool_name") or ""),
    )


class _SimpleToolCall:
    __slots__ = ("id", "name")

    def __init__(self, *, call_id: str, name: str) -> None:
        self.id = call_id
        self.name = name


def run_subagent_react_loop(
    stack: Any,
    *,
    prompt: str,
    role_id: str,
    model: str,
    thread_id: str,
    session_id: str = "",
    emitter: Any = None,
    agent: Any = None,
    max_iterations: int = 30,
    approval_provider: ApprovalProvider | None = None,
    conversation_messages: Iterable[dict[str, Any]] | None = None,
    tool_allowlist: Iterable[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReActResult | None:
    """Run ``stream_react_loop`` for a sub-agent, forwarding events to the bus.

    Returns the ``ReActResult`` so callers can read ``final_answer`` /
    ``success``. Events are best-effort mirrors: losing telemetry never breaks
    the run.
    """
    from runtime.execution.suckers._ephemeral_events import (
        _current_subagent_codename,
        _emit_sub_text_delta,
        _emit_sub_tool_event,
        _publish_to_bus,
    )

    intent = build_subagent_intent(
        prompt,
        role_id=role_id,
        model=model,
        thread_id=thread_id,
        conversation_messages=conversation_messages,
        tool_allowlist=tool_allowlist,
        metadata=metadata,
    )
    provider = approval_provider or AutoApproveProvider()

    gen = stream_react_loop(
        stack,
        intent,
        agent,
        model=model,
        thread_id=thread_id,
        max_iterations=max_iterations,
        approval_provider=provider,
    )

    result: ReActResult | None = None
    round_no = 0
    failure: str | None = None
    try:
        while True:
            try:
                evt = next(gen)
            except StopIteration as stop:
                result = stop.value
                break
            if not isinstance(evt, dict):
                continue
            kind = evt.get("type")
            if kind == "text_delta":
                delta = evt.get("delta")
                if delta:
                    _emit_sub_text_delta(
                        role_id,
                        round_no + 1,
                        str(delta),
                        session_id=session_id,
                        emitter=emitter,
                    )
            elif kind == "tool_start":
                round_no += 1
                _emit_sub_tool_event(
                    "sub_tool_start",
                    role_id=role_id,
                    tool_call=_react_tool_call(evt),
                    iteration=round_no,
                )
            elif kind == "tool_end":
                _emit_sub_tool_event(
                    "sub_tool_end",
                    role_id=role_id,
                    tool_call=_react_tool_call(evt),
                    iteration=round_no,
                    is_error=str(evt.get("status")) in ("error", "rejected", "failed"),
                    duration_ms=evt.get("duration_ms"),
                )
            elif kind == "react_error":
                failure = str(evt.get("message") or "react loop error")
                _publish_to_bus(
                    "sub_failed",
                    {
                        "role": role_id,
                        "codename": _current_subagent_codename(),
                        "ok": False,
                        "error": failure,
                    },
                )
            elif kind == "react_cancelled":
                failure = "sub-agent cancelled"
                _publish_to_bus(
                    "sub_failed",
                    {
                        "role": role_id,
                        "codename": _current_subagent_codename(),
                        "ok": False,
                        "error": failure,
                    },
                )
    except Exception as exc:  # noqa: BLE001 - surface as a sub-agent failure
        failure = f"{type(exc).__name__}: {exc}"
        _publish_to_bus(
            "sub_failed",
            {
                "role": role_id,
                "codename": _current_subagent_codename(),
                "ok": False,
                "error": failure,
            },
        )
        return None

    if result is None or not getattr(result, "success", True):
        reason = failure or (
            getattr(result, "terminated_reason", None) or "incomplete"
        )
        _publish_to_bus(
            "sub_failed",
            {
                "role": role_id,
                "codename": _current_subagent_codename(),
                "ok": False,
                "error": reason,
                "iteration_count": round_no,
            },
        )
        return result

    _publish_to_bus(
        "sub_concluded",
        {
            "role": role_id,
            "codename": _current_subagent_codename(),
            "ok": True,
            "iteration_count": round_no,
        },
    )
    return result


__all__ = [
    "build_subagent_intent",
    "run_subagent_react_loop",
]

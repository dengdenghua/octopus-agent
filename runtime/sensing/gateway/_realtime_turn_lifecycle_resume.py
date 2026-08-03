"""Resume-intent persistence for the realtime turn lifecycle.

Unit: the pending resume-intent store — recording a pending resume
intent (``_record_pending_resume_intent``) and consuming a confirmed
resume intent (``_consume_confirmed_resume_intent``).

Split out of ``realtime_turn_lifecycle.py`` so that orchestrator stays
under the god-file line budget.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from runtime.sensing.gateway.realtime_turn_input import (
    _execution_resume_intent,
    _parse_resume_confirmation,
    _safe_int,
)

if TYPE_CHECKING:
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime


async def _record_pending_resume_intent(
    runtime: CerebrumRuntime,
    thread_id: str,
    resume_intent: dict[str, Any],
) -> None:
    async with runtime._resume_intents_lock:
        runtime._pending_resume_intents[thread_id] = dict(resume_intent)
    if runtime._trace_store is None:
        return
    with contextlib.suppress(Exception):
        runtime._trace_store.record_resume_request(
            thread_id=thread_id,
            checkpoint_id=int(resume_intent.get("checkpoint_id") or 0),
            task_id=resume_intent.get("task_id"),
            status="pending",
            intent=resume_intent,
        )


async def _consume_confirmed_resume_intent(
    runtime: CerebrumRuntime,
    thread_id: str,
    text: str,
) -> dict[str, Any] | None:
    checkpoint_id = _parse_resume_confirmation(text)
    if checkpoint_id is None:
        return None
    async with runtime._resume_intents_lock:
        pending = runtime._pending_resume_intents.get(thread_id)
        pending_request_id: int | None = None
        if not isinstance(pending, dict) and runtime._trace_store is not None:
            with contextlib.suppress(Exception):
                request = runtime._trace_store.latest_pending_resume_request(thread_id=thread_id)
                if isinstance(request, dict):
                    pending = request.get("intent")
                    pending_request_id = _safe_int(request.get("id"))
        if not isinstance(pending, dict):
            return None
        if _safe_int(pending.get("checkpoint_id")) != checkpoint_id:
            return None
        runtime._pending_resume_intents.pop(thread_id, None)
    if runtime._trace_store is not None:
        with contextlib.suppress(Exception):
            confirmed = runtime._trace_store.confirm_resume_request(
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                confirmation_text=f"确认恢复 checkpoint #{checkpoint_id}",
            )
            if isinstance(confirmed, dict):
                confirmed_intent = confirmed.get("intent")
                pending = confirmed_intent if isinstance(confirmed_intent, dict) else pending
                pending_request_id = _safe_int(confirmed.get("id")) or pending_request_id
            if pending_request_id is not None:
                runtime._trace_store.consume_resume_request(pending_request_id)
    return _execution_resume_intent(pending, checkpoint_id)

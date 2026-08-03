"""Reducer that maps bridge events to ``item/*`` notifications.

Extracted from ``realtime_react_stream.py``: ``_apply_react_event`` turns a
single event dict (text/commentary/tool/lifecycle/grounding ...) into the
corresponding ``item/*`` / ``turn/*`` / ``thread/*`` notifications via the
bridge state. Kept independent of the other ``_realtime_react_stream_*``
submodules.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from runtime.memory.threads.event_log import EventLog
from runtime.protocol import (
    ErrorItem,
    GroundingSource,
    ItemStatus,
    ServerMethod,
    TurnStatus,
)
from runtime.sensing.gateway.realtime_event_bridge import _ReactBridgeState
from runtime.sensing.gateway.realtime_gateway import EventEmitter

if TYPE_CHECKING:
    from runtime.protocol import Turn
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime


async def _apply_react_event(
    runtime: CerebrumRuntime,
    turn: Turn,
    log: EventLog,
    emitter: EventEmitter,
    state: _ReactBridgeState,
    evt: dict[str, Any],
) -> None:
    runtime._record_react_trace_event(turn, evt)
    kind = evt.get("type")
    if kind == "text_delta":
        await state.append_agent_message(turn, log, emitter, evt.get("delta", ""))
        return
    if kind == "commentary_delta":
        # Generic runtime fallback prose remains private: it made every
        # provider sound identical and often duplicated the final synthesis.
        # A completed, explicitly marked evidence receipt is different: it is
        # grounded in a real tool result and must remain visible between
        # ordered batches so the timeline does not collapse into tool rows.
        if (
            evt.get("progress_source") == "runtime"
            and not evt.get("public_evidence")
            and not evt.get("public_status")
        ):
            return
        await state.append_commentary(
            turn,
            log,
            emitter,
            evt.get("delta", ""),
            # Complete checkpoints default to a new conversational beat. A
            # provider may explicitly continue the current beat so token
            # chunks grow one message/avatar instead of producing a log row.
            start_new_segment=bool(evt.get("start_new_segment", True)),
        )
        return
    if kind == "thinking_delta":
        await state.append_reasoning(turn, log, emitter, evt.get("delta", ""))
        return
    if kind == "tool_start":
        await state.start_tool(turn, log, emitter, evt)
        return
    if kind == "tool_output_delta":
        await state.append_tool_output(turn, log, emitter, evt)
        return
    if kind == "tool_background":
        await state.track_background_tool(turn, log, emitter, evt)
        return
    if kind == "tool_end":
        await state.complete_tool(turn, log, emitter, evt)
        return
    if kind == "react_cancelled":
        # Producer already decided the loop is done. Flush any open
        # prose and mark the turn as interrupted so the gateway's
        # turn/completed wrapper preserves that status.
        await state.flush(
            turn,
            log,
            emitter,
            status=ItemStatus.INTERRUPTED,
        )
        turn.status = TurnStatus.INTERRUPTED
        if not turn.interrupt_reason:
            turn.interrupt_reason = "任务被取消"
        return
    if kind == "throughput":
        # Piggyback on thread/tokenUsage/updated — the frontend
        # reducer already routes this to a free-form ``tokenUsage``
        # record, so we can ship any shape without a schema bump.
        usage = evt.get("usage")
        if isinstance(usage, str) and usage.strip():
            import json

            try:
                parsed = json.loads(usage)
                token_usage = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                token_usage = {}
        elif isinstance(usage, dict):
            token_usage = usage
        else:
            token_usage = {
                "chars": evt.get("chars", 0),
                "elapsedMs": evt.get("elapsed_ms", 0),
                "charsPerSec": evt.get("chars_per_sec", 0.0),
            }
        await emitter.notify(
            ServerMethod.THREAD_TOKEN_USAGE_UPDATED,
            {
                "threadId": turn.thread_id,
                "tokenUsage": token_usage,
            },
        )
        return
    if kind == "codebase_grounding":
        # The loop folded these project docs/chunks into the prompt this turn.
        # Forward them so the frontend can show a plain-language grounding chip
        # on the AI reply. Best-effort UX — never a turn-breaking contract.
        sources = evt.get("sources")
        if isinstance(sources, list) and sources:
            validated_sources: list[GroundingSource] = []
            for source in sources:
                if not isinstance(source, dict):
                    continue
                with contextlib.suppress(TypeError, ValueError):
                    validated_sources.append(GroundingSource.model_validate(source))
            if not validated_sources:
                return
            turn.grounding = validated_sources
            sources_payload = [
                source.model_dump(mode="json") for source in validated_sources
            ]
            logged_update = log.turn_updated(
                turn.thread_id,
                turn.id,
                grounding=sources_payload,
            )
            await emitter.notify(
                ServerMethod.TURN_GROUNDING,
                {
                    "threadId": turn.thread_id,
                    "turnId": turn.id,
                    "sources": sources_payload,
                    **({"eventId": logged_update.event_id} if logged_update is not None else {}),
                },
            )
        return
    if kind == "react_step_complete":
        await state.flush(turn, log, emitter)
        return
    if kind == "react_completed":
        success = evt.get("success") is not False
        await state.flush(
            turn,
            log,
            emitter,
            status=ItemStatus.COMPLETED if success else ItemStatus.FAILED,
        )
        if not success:
            turn.status = TurnStatus.FAILED
        return
    if kind == "react_paused":
        await state.flush(
            turn,
            log,
            emitter,
            status=ItemStatus.INTERRUPTED,
        )
        turn.status = TurnStatus.INTERRUPTED
        return
    if kind == "react_resumed":
        await emitter.notify(
            ServerMethod.THREAD_STATUS_CHANGED,
            {
                "threadId": turn.thread_id,
                "status": {
                    "type": "resumed",
                    "taskId": evt.get("task_id"),
                    "checkpointIteration": evt.get("checkpoint_iteration"),
                    "resumeFromIteration": evt.get("resume_from_iteration"),
                    "restoredStepCount": evt.get("restored_step_count"),
                    "hasFinalAnswer": evt.get("has_final_answer"),
                    "currentPhase": evt.get("current_phase"),
                },
            },
        )
        return
    if kind in ("react_error",):
        await state.flush(
            turn,
            log,
            emitter,
            status=ItemStatus.FAILED,
        )
        err = ErrorItem(
            message=str(evt.get("message") or evt.get("kind") or "react error"),
            will_retry=False,
        )
        turn.status = TurnStatus.FAILED
        turn.items.append(err)
        log.item_started(turn.thread_id, turn.id, err)
        await emitter.notify(
            ServerMethod.ITEM_STARTED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": err.model_dump(by_alias=True, mode="json"),
            },
        )
        log.item_completed(turn.thread_id, turn.id, err)
        await emitter.notify(
            ServerMethod.ITEM_COMPLETED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": err.model_dump(by_alias=True, mode="json"),
            },
        )

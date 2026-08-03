"""ReAct loop stream driver.

Extracted from ``realtime_react_stream.py``: ``_drive_react`` pumps the
``react_loop`` iterator (or the protocol-native tool-loop fallback) on a
worker thread, marshals every yielded event onto an asyncio queue, and
dispatches them via ``_apply_react_event``.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from runtime.memory.threads.event_log import EventLog
from runtime.platform.models import ParsedIntent
from runtime.protocol import TurnStatus
from runtime.safety.approval.approval_gate import ApprovalProvider
from runtime.sensing.gateway._realtime_react_stream_apply import _apply_react_event
from runtime.sensing.gateway._realtime_react_stream_helpers import (
    _SINGLE_AGENT_HEARTBEAT_INTERVAL_S,
    _agentic_stream_event_to_react_event,
    _apply_orchestration_grant,
    _emit_turn_heartbeat,
    _logger,
    _safe_stream_error_message,
    _should_use_native_tool_loop,
)
from runtime.sensing.gateway.realtime_gateway import EventEmitter
from runtime.sensing.gateway.realtime_turn_input import (
    _resume_task_id_from_intent,
)

if TYPE_CHECKING:
    from runtime.protocol import Turn
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime


async def _drive_react(
    runtime: CerebrumRuntime,
    turn: Turn,
    log: EventLog,
    emitter: EventEmitter,
    intent: ParsedIntent,
    provider: ApprovalProvider,
    agent: Any,
    *,
    model: str | None = None,
) -> None:
    """Pump the react_loop iterator, mapping each event to ``item/*``.

    The loop runs on a worker thread (``asyncio.to_thread``) so
    synchronous LLM calls inside ``stream_react_loop`` don't block
    the event loop. Each yielded event is delivered back to the
    coroutine via a queue.
    """
    from runtime.core.cerebrum.react_loop import stream_react_loop
    from runtime.safety.approval.cancellation import (
        CancellationSource,
        scoped_cancellation,
    )

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=64)
    loop = asyncio.get_running_loop()

    # Per-turn cancellation source. Tripped when the gateway records a
    # ``turn/interrupt`` for this turn id; every tool call inside
    # ``stream_react_loop`` sees the same token via the
    # ``scoped_cancellation`` contextvar and bails out fast.
    cancel_source = CancellationSource()

    def _safe_put(event: dict[str, Any] | None, *, timeout: float = 10.0) -> None:
        """Bounded blocking ``queue.put`` from the worker thread.

        ``run_coroutine_threadsafe(...).result()`` without a timeout
        deadlocks the worker if the consumer exits early (exception
        in the dispatch loop, ws error, etc.). Bounded blocking
        preserves backpressure for the normal case while leaving a
        kill-switch when something downstream is wedged.
        """
        try:
            asyncio.run_coroutine_threadsafe(
                queue.put(event),
                loop,
            ).result(timeout=timeout)
        except (RuntimeError, TimeoutError):
            # RuntimeError: loop closed.
            # TimeoutError: consumer stuck — drop this event rather
            # than block the worker indefinitely.
            _logger.warning(
                "react bridge enqueue failed/timed out (event=%s) — "
                "text/tool events may be lost, frontend may show incomplete output",
                event.get("type") if isinstance(event, dict) else event,
            )

    def _push_chunk(call_id: str, stream: str, chunk: str) -> None:
        # Called from a reader sub-thread inside the tool's subprocess
        # plumbing. Hop back to the asyncio loop so the queue stays
        # single-producer-from-the-event-loop's-perspective.
        #
        # We use a SHORT timeout here (vs the 10s in _safe_put):
        # tool stdout chunks are high-frequency and individually
        # disposable — better to drop a chunk than block the
        # subprocess reader thread for 10s if the consumer is slow.
        evt = {
            "type": "tool_output_delta",
            "tool_call_id": call_id,
            "stream": stream,
            "delta": chunk,
        }
        try:
            asyncio.run_coroutine_threadsafe(
                queue.put(evt),
                loop,
            ).result(timeout=2.0)
        except (RuntimeError, TimeoutError):
            _logger.warning(
                "tool_output_delta drop (consumer slow) — "
                "command output may be truncated in the UI"
            )

    def producer() -> None:
        # ``asyncio.to_thread`` copies ContextVars from the calling
        # task, so installing the cancellation scope here makes the
        # token visible to every subprocess call downstream.
        from runtime.memory.journal.journal_context import journal_context
        from runtime.platform.process.session import Session, session_scope

        session_metadata = dict(intent.user_context or {})
        _apply_orchestration_grant(session_metadata)
        if runtime._workspaces is not None:
            session_metadata["_artifact_output_root"] = str(
                runtime._workspaces.layout(turn.thread_id).final,
            )
        if runtime._trace_store is not None:
            session_metadata["_trace_store"] = runtime._trace_store
        session_agent = agent if hasattr(agent, "agent_id") else None
        turn_session = Session(
            agent=session_agent,
            thread_id=turn.thread_id,
            conversation_id=turn.thread_id,
            turn_id=turn.id,
            metadata=session_metadata,
        )
        # journal_context drives a SEPARATE contextvar that journal
        # write_* methods read for conversation_id/agent_id; without
        # it every journal/trace row lands with thread_id=None.
        # session_scope alone does not feed it.
        _journal_agent_id = getattr(session_agent, "agent_id", None)
        from runtime.execution.suckers.delegation_skills import (
            orchestration_progress_scope,
        )

        def _orchestration_progress(line: str) -> None:
            _safe_put({"type": "thinking_delta", "delta": line + "\n"})

        with (
            session_scope(turn_session),
            journal_context(
                conversation_id=turn.thread_id,
                agent_id=_journal_agent_id,
            ),
            scoped_cancellation(cancel_source.token),
            orchestration_progress_scope(_orchestration_progress),
        ):
            try:
                _planning_mode = bool(
                    (intent.user_context or {}).get("planning_mode", False),
                )
                if _should_use_native_tool_loop(
                    runtime._stack,
                    intent,
                    planning_mode=_planning_mode,
                ):
                    from runtime.sensing.gateway.tool_bridge import (
                        stream_agentic_fallback,
                    )

                    for kind, delta, final in stream_agentic_fallback(
                        runtime._stack,
                        intent,
                        agent,
                        model=model,
                        steering_drain=lambda: runtime._drain_turn_steering(turn.id),
                    ):
                        evt = _agentic_stream_event_to_react_event(
                            kind,
                            delta,
                            final,
                        )
                        if evt is not None:
                            _safe_put(evt)
                else:
                    _resume_task_id = _resume_task_id_from_intent(intent)
                    events: Iterator[dict[str, Any]] = stream_react_loop(
                        runtime._stack,
                        intent,
                        agent,
                        thread_id=turn.thread_id,
                        max_iterations=runtime._max_iterations,
                        resume_task_id=_resume_task_id,
                        approval_provider=provider,
                        output_chunk_sink=_push_chunk,
                        planning_mode=_planning_mode,
                        model=model,
                        reasoning_effort=(intent.user_context or {}).get(
                            "reasoning_effort",
                        ),
                        steering_drain=lambda: runtime._drain_turn_steering(turn.id),
                    )
                    for evt in events:
                        _safe_put(evt)
            except Exception as exc:
                _safe_put(
                    {
                        "type": "react_error",
                        "kind": exc.__class__.__name__,
                        "message": _safe_stream_error_message(exc),
                    }
                )
            finally:
                _safe_put(None, timeout=5.0)

    worker = asyncio.create_task(asyncio.to_thread(producer))
    state = runtime._make_bridge_state(turn.thread_id, turn.id, agent=agent)

    async def _interrupt_watcher() -> None:
        # Polls the gateway's interrupt registry. Consumer-side polling
        # alone isn't enough: if the producer is blocked inside a long
        # subprocess.wait, no events reach the queue and the consumer
        # never wakes to notice. This task trips cancellation the
        # instant the flag flips, unblocking the subprocess wait via
        # current_cancellation_token() inside stream_run.
        try:
            while not cancel_source.is_cancelled:
                if emitter.is_turn_interrupted(turn.id):
                    cancel_source.cancel(reason="user interrupted turn")
                    return
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            return

    watcher = asyncio.create_task(_interrupt_watcher())
    saw_terminal_event = False
    try:
        loop_started = time.monotonic()
        while True:
            try:
                evt = await asyncio.wait_for(
                    queue.get(), timeout=_SINGLE_AGENT_HEARTBEAT_INTERVAL_S
                )
            except TimeoutError:
                # No event for a while: the model is thinking or a tool is
                # running silently. Emit a keepalive (unless the turn is
                # already winding down) so the frontend reads "working",
                # not "stuck", then keep waiting.
                if not (cancel_source.is_cancelled or emitter.is_turn_interrupted(turn.id)):
                    await runtime._publish_discovered_steering(turn, emitter)
                    await _emit_turn_heartbeat(emitter, turn, loop_started)
                continue
            if evt is None:
                break
            await runtime._publish_discovered_steering(turn, emitter)
            if evt.get("type") in {
                "react_completed",
                "react_cancelled",
                "react_paused",
                "react_error",
            }:
                saw_terminal_event = True
            if emitter.is_turn_interrupted(turn.id):
                if not cancel_source.is_cancelled:
                    cancel_source.cancel(reason="user interrupted turn")
                turn.status = TurnStatus.INTERRUPTED
                # Record the concrete interrupt reason so the
                # frontend can tell the user *why* the turn stopped.
                if not turn.interrupt_reason:
                    with contextlib.suppress(Exception):
                        reason = emitter.get_interrupt_reason(turn.id)
                        if reason:
                            turn.interrupt_reason = reason
                # Keep draining so the producer's bounded ``put``
                # calls succeed and it can reach its ``None`` sentinel
                # cleanly. Breaking here would leave the worker
                # blocked on a full queue.
                continue
            try:
                await _apply_react_event(runtime, turn, log, emitter, state, evt)
            except Exception as exc:  # noqa: BLE001
                # A single bad event shouldn't kill the dispatch
                # loop — swallow and keep draining so the producer
                # can finish (and so we still emit the trailing
                # ``state.flush`` for whatever made it through).
                _logger.warning(
                    "react event apply failed (kind=%s): %s",
                    evt.get("type") if isinstance(evt, dict) else "?",
                    exc,
                    exc_info=True,
                )
    finally:
        # Trip cancellation so the producer THREAD (asyncio.to_thread)
        # observes it and bails — task cancellation alone can't stop a
        # real OS thread. On ws-disconnect teardown this is what stops
        # the react loop from running to completion against a dead
        # queue and flooding pending Queue.put() tasks.
        cancel_source.cancel(reason="consumer teardown")
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
        with contextlib.suppress(Exception):
            await worker

    # Finalize anything still open. Wrapped in suppress so a torn-
    # down ws doesn't take the whole turn-completion path with it.
    if not saw_terminal_event and turn.status == TurnStatus.IN_PROGRESS:
        answer_text = (
            str(state.agent_message.text or "").strip() if state.agent_message is not None else ""
        )
        if answer_text:
            # Some provider adapters finish after yielding the complete
            # text_delta stream but omit the trailing react_completed event.
            # The answer item is already user-visible and is stronger terminal
            # evidence than the generator's empty return value; finalize it as
            # success instead of appending a contradictory error card.
            await _apply_react_event(
                runtime,
                turn,
                log,
                emitter,
                state,
                {"type": "react_completed", "recovered_from_text": True},
            )
        else:
            # A generator that returns ``None`` without a terminal event used
            # to make any earlier tool/commentary item count as a successful
            # turn, leaving the user with progress fragments and no final
            # answer. Fail explicitly while preserving those fragments for a
            # later Continue.
            await _apply_react_event(
                runtime,
                turn,
                log,
                emitter,
                state,
                {
                    "type": "react_error",
                    "kind": "missing_terminal_answer",
                    "message": (
                        "模型执行已结束，但没有生成可确认的最终答案。阶段进度已保留；"
                        "请点击继续重新收敛，或切换模型后重试。"
                    ),
                },
            )
    with contextlib.suppress(Exception):
        await state.flush(
            turn,
            log,
            emitter,
            status=state.prose_status_for_turn(turn.status),
        )
    if turn.status == TurnStatus.IN_PROGRESS:
        with contextlib.suppress(Exception):
            await state.finalize_workbench(
                turn,
                log,
                emitter,
                terminal_status=TurnStatus.COMPLETED,
            )
    # Note: background tool watchers (started by ``track_background_tool``)
    # are intentionally NOT cancelled here. They're designed to outlive
    # the current turn — the user starts a long-running shell command,
    # the LLM finalises with ``react_completed``, and the watcher keeps
    # streaming output deltas onto the open ``commandExecution`` item
    # until the process exits. See ``test_background_tool_item_completes
    # _after_turn_response``.

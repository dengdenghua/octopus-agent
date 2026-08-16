"""ReAct loop stream driver.

Extracted from ``realtime_react_stream.py``: ``_drive_react`` pumps the
``react_loop`` iterator (or the protocol-native tool-loop fallback) on a
worker thread, marshals every yielded event onto an asyncio queue, and
dispatches them via ``_apply_react_event``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from runtime.execution.subagents._ambient import react_stack_scope
from runtime.memory.threads.event_log import EventLog
from runtime.platform.models import ParsedIntent
from runtime.platform.models.llm import default_reasoning_effort
from runtime.protocol import (
    ItemMarker,
    ItemStatus,
    McpToolCallItem,
    ServerMethod,
    TurnStatus,
)
from runtime.safety.approval.approval_gate import ApprovalProvider
from runtime.sensing.gateway._realtime_react_stream_apply import (
    _apply_react_event,
    _start_orchestrator_bridge,
)
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


# High-frequency, individually disposable stream deltas. These decorate the
# turn (reasoning / commentary / throughput) and are safe to drop when the
# bridge queue is full: keeping the producer from blocking 10s per event is
# what prevents cascading stalls that lose *structural* events (tool results,
# final answer). Structural events keep backpressure-bounded enqueue.
_COALESCABLE_DELTA_TYPES = frozenset({"throughput", "visibility"})


def _is_coalescable_delta(event: dict[str, Any] | None) -> bool:
    """True for decorative deltas that may be dropped under queue pressure."""
    return isinstance(event, dict) and event.get("type") in _COALESCABLE_DELTA_TYPES


def _lease_renewal_interval_s(lease_ttl_seconds: float) -> float:
    """Renewal cadence for the supervisor lease (lease_ttl/3, capped at 30s).

    Matches the execution/loops heartbeat cadence so long realtime turns
    keep their TaskSupervisor lease alive without hammering the store.
    """
    return max(0.1, min(float(lease_ttl_seconds) / 3.0, 30.0))


# ── Sub-agent lifecycle journal → workbench bridge ────────────────────
# ``run_orchestration`` (the audit.ultracode fan-out) spawns its parallel
# sub-agents via ``_call_agent_parallel`` → ``call_subagent`` WITHOUT an
# in-memory ``event_emitter``, so their ``subagent_spawned`` /
# ``subagent_finished`` events never reach any live stream — only the
# journal mirror (``bridge._safe_journal_emit``) carries them, and only
# when the bound ``Session.metadata`` injects a journal. The realtime WS —
# the only stream the workbench reads — has no journal→WS consumer, so
# the audit's parallel sub-agents render as one opaque
# ``run_orchestration`` row instead of live agent tiles.
#
# These helpers are that missing consumer: a per-turn journal subscription
# that lifts the marker events onto the turn as the same ``McpToolCallItem``
# the wired paths emit, which the frontend's ``mcpItemToLiveEvent`` already
# translates into lifecycle tiles (zero frontend changes).

_AGENT_LIFECYCLE_MARKERS: frozenset[str] = frozenset(
    {
        ItemMarker.SUBAGENT_SPAWNED.value,
        ItemMarker.SUBAGENT_FINISHED.value,
    }
)


def _parse_lifecycle_preview(preview: Any) -> dict[str, Any]:
    """Parse the bridge's JSON preview blob back into a dict.

    ``bridge.py`` serialises the spawn/finish payloads into
    ``args_preview`` / ``output_preview`` JSON strings before writing the
    journal event; the WS item needs them as a dict again.
    """
    if not isinstance(preview, str) or not preview.strip():
        return {}
    try:
        parsed = json.loads(preview)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _subagent_lifecycle_item_from_journal(event: Any) -> McpToolCallItem | None:
    """Synthesise a marker ``McpToolCallItem`` from a journal SubTool event.

    Fires only for the sub-agent lifecycle markers the bridge mirrors onto
    the journal (``__subagent_spawned__`` / ``__subagent_finished__``);
    every other journal event returns ``None``.
    """
    kind = getattr(event, "event_type", None)
    if kind not in ("sub_tool_start", "sub_tool_end"):
        return None
    tool_name = getattr(event, "tool_name", "") or ""
    if tool_name not in _AGENT_LIFECYCLE_MARKERS:
        return None
    spawned = kind == "sub_tool_start"
    preview = (
        getattr(event, "args_preview", None) if spawned else getattr(event, "output_preview", None)
    )
    payload = _parse_lifecycle_preview(preview)
    parent_id = getattr(event, "parent_tool_use_id", None)
    if parent_id:
        payload["parent_tool_use_id"] = str(parent_id)
    event_id = str(getattr(event, "event_id", "") or "")
    if len(event_id) > 16:
        event_id = event_id.replace("-", "")[:16]
    created = getattr(event, "ts", None)
    if spawned:
        return McpToolCallItem(
            id=f"subagent_spawn_{event_id}" if event_id else "subagent_spawn",
            server="runtime",
            tool=ItemMarker.SUBAGENT_SPAWNED.value,
            arguments=payload,
            status=ItemStatus.IN_PROGRESS,
            created_at=created,
        )
    ok = bool(payload.get("ok", True))
    return McpToolCallItem(
        id=f"subagent_finish_{event_id}" if event_id else "subagent_finish",
        server="runtime",
        tool=ItemMarker.SUBAGENT_FINISHED.value,
        arguments={"parent_tool_use_id": str(parent_id)} if parent_id else {},
        result=payload,
        status=ItemStatus.COMPLETED if ok else ItemStatus.FAILED,
        created_at=created,
    )


def _subagent_lifecycle_matches(event: Any, task_id: str) -> bool:
    """True when ``event`` is this turn's sub-agent lifecycle marker."""
    if not task_id:
        return False
    return str(getattr(event, "task_id", None) or "") == str(task_id)


async def _emit_subagent_lifecycle_item(
    turn: Any,
    log: EventLog,
    emitter: EventEmitter,
    item: McpToolCallItem,
    *,
    terminal: bool,
) -> None:
    """Append + notify a synthesised lifecycle item on the driver's loop.

    Runs on the same asyncio loop as the react driver's consumer so
    ``turn.items`` is only mutated there — the same no-race rule
    ``_start_orchestrator_bridge`` documents.
    """
    turn.items.append(item)
    method = ServerMethod.ITEM_COMPLETED if terminal else ServerMethod.ITEM_STARTED
    logged = (
        log.item_completed(turn.thread_id, turn.id, item)
        if terminal
        else log.item_started(turn.thread_id, turn.id, item)
    )
    with contextlib.suppress(Exception):
        await emitter.notify(
            method,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
                "eventId": logged.event_id,
            },
        )


def _start_subagent_lifecycle_bridge(
    runtime: Any,
    turn: Any,
    log: EventLog,
    emitter: EventEmitter,
    loop: asyncio.AbstractEventLoop,
    task_id: str,
) -> Callable[[], None] | None:
    """Subscribe the genome journal for this turn's sub-agent lifecycle.

    Returns the unsubscribe callable, or ``None`` when the stack's journal
    isn't a live ``StreamingJournal`` (the base ``Journal.subscribe`` is a
    documented no-op that still returns an unsubscribe — mirror
    ``stream_handler._has_live_subscribe``'s guard).
    """
    journal = getattr(getattr(runtime, "_stack", None), "journal", None)
    if journal is None:
        return None
    from runtime.memory.journal.journal import Journal as _JournalBase

    subscribe = getattr(type(journal), "subscribe", None)
    if subscribe is None or subscribe is _JournalBase.subscribe:
        return None
    task_id = str(task_id or "").strip()

    def _on_journal_event(event: Any) -> None:
        if not _subagent_lifecycle_matches(event, task_id):
            return
        item = _subagent_lifecycle_item_from_journal(event)
        if item is None:
            return
        terminal = item.status in {
            ItemStatus.COMPLETED,
            ItemStatus.FAILED,
        }
        try:
            asyncio.run_coroutine_threadsafe(
                _emit_subagent_lifecycle_item(
                    turn,
                    log,
                    emitter,
                    item,
                    terminal=terminal,
                ),
                loop,
            )
        except (RuntimeError, ValueError):
            # Loop already closed / task cancelled — drop the frame rather
            # than leak it into a torn-down turn.
            return

    try:
        return journal.subscribe(_on_journal_event)
    except Exception:  # noqa: BLE001 — telemetry bridge never breaks the turn
        return None


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

        Coalescable decorative deltas bypass the blocking put: they are
        high-frequency and individually disposable, so on a full queue we
        drop the newest delta instead of stalling the producer 10s (which
        used to cascade and lose *structural* events downstream).
        """
        if _is_coalescable_delta(event):
            try:
                # put_nowait is a plain method, so wrap it in a coroutine that
                # swallows QueueFull: on a full queue the decorative delta is
                # dropped rather than making the producer block 10s.
                async def _coalesce() -> None:
                    with contextlib.suppress(asyncio.QueueFull):
                        queue.put_nowait(event)

                asyncio.run_coroutine_threadsafe(
                    _coalesce(),
                    loop,
                ).result(timeout=0.05)
            except (RuntimeError, TimeoutError):
                # Loop closed or consumer wedged — drop the decorative delta.
                _logger.debug(
                    "react bridge coalesced-delta drop (consumer slow) event=%s",
                    event.get("type"),
                )
            return
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
                "tool_output_delta drop (consumer slow) — command output may be truncated in the UI"
            )

    def producer() -> None:
        # ``asyncio.to_thread`` copies ContextVars from the calling
        # task, so installing the cancellation scope here makes the
        # token visible to every subprocess call downstream.
        from runtime.memory.journal.journal_context import journal_context
        from runtime.platform.process.session import Session, session_scope

        session_metadata = dict(intent.user_context or {})
        _apply_orchestration_grant(session_metadata)
        # Sub-agents spawned inside the turn (run_orchestration fan-out,
        # call_agent_parallel, ...) mirror their lifecycle/tool events onto
        # the journal ONLY when the bound Session carries one
        # (see _ephemeral_events._emit_subagent_lifecycle_event). The
        # realtime WS is not a journal subscriber, so this injection is what
        # lets the per-turn bridge below lift those events onto the workbench.
        _stack_journal = getattr(getattr(runtime, "_stack", None), "journal", None)
        if _stack_journal is not None:
            session_metadata.setdefault("journal", _stack_journal)
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
            workflow_settlement_scope,
        )

        def _orchestration_progress(line: str) -> None:
            _safe_put({"type": "thinking_delta", "delta": line + "\n"})

        def _workflow_settlement(payload: dict) -> None:
            """Handle workflow completion and emit notification to client."""
            try:
                from runtime.protocol import ServerMethod

                # Build notification payload
                notification_payload = {
                    "threadId": turn.thread_id,
                    "workflowName": payload.get("workflowName", "workflow"),
                    "workflowDescription": payload.get("workflowDescription", ""),
                    "runId": payload.get("runId", ""),
                    "stopReason": payload.get("stopReason", "unknown"),
                    "success": payload.get("success", False),
                    "agentsStarted": payload.get("agentsStarted", 0),
                    "error": payload.get("error"),
                }

                # Schedule notification on the event loop (emitter.notify is async)
                import asyncio

                asyncio.create_task(
                    emitter.notify(
                        ServerMethod.WORKFLOW_COMPLETED,
                        notification_payload,
                    )
                )
            except Exception:  # noqa: BLE001 — notification is best-effort
                pass

        with (
            session_scope(turn_session),
            journal_context(
                conversation_id=turn.thread_id,
                agent_id=_journal_agent_id,
            ),
            scoped_cancellation(cancel_source.token),
            orchestration_progress_scope(_orchestration_progress),
            workflow_settlement_scope(_workflow_settlement),
            react_stack_scope(runtime._stack),
        ):
            # Per-turn sub-agent lifecycle bridge. Launched once the react
            # boot yields ``react_started`` — the task_id it carries is the
            # only reliable key for the journal events sub-agents mirror.
            unsubscribe_lifecycle: Callable[[], None] | None = None
            try:
                _planning_mode = bool(
                    (intent.user_context or {}).get("planning_mode", False),
                )
                if _should_use_native_tool_loop(
                    runtime._stack,
                    intent,
                    planning_mode=_planning_mode,
                    model=model,
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

                    def _on_auto_parallel_batch(batch_id: str) -> None:
                        # The auto-parallel short-circuit (running on the
                        # producer thread) dispatched a parallel batch. Hop
                        # back to the event loop and start the orchestrator
                        # bridge so the workbench renders each sub-task as a
                        # live tile immediately.
                        async def _spawn() -> None:
                            _start_orchestrator_bridge(runtime, turn, log, emitter, batch_id)

                        with contextlib.suppress(RuntimeError):
                            asyncio.run_coroutine_threadsafe(_spawn(), loop)

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
                        reasoning_effort=(
                            (intent.user_context or {}).get("reasoning_effort")
                            or default_reasoning_effort(model)
                        ),
                        steering_drain=lambda: runtime._drain_turn_steering(turn.id),
                        on_auto_parallel_batch=_on_auto_parallel_batch,
                    )
                    for evt in events:
                        if (
                            isinstance(evt, dict)
                            and evt.get("type") == "react_started"
                            and unsubscribe_lifecycle is None
                        ):
                            _react_task_id = str(evt.get("task_id") or "").strip()
                            if _react_task_id:
                                # Stamp task_id onto the session so sub-agent
                                # journal events carry it (they read
                                # session.metadata, and the react boot
                                # generates the id after this session was
                                # created).
                                with contextlib.suppress(Exception):
                                    turn_session.metadata["task_id"] = _react_task_id
                                unsubscribe_lifecycle = _start_subagent_lifecycle_bridge(
                                    runtime,
                                    turn,
                                    log,
                                    emitter,
                                    loop,
                                    _react_task_id,
                                )
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
                if unsubscribe_lifecycle is not None:
                    with contextlib.suppress(Exception):
                        unsubscribe_lifecycle()
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

    # ── Supervisor lease renewal ─────────────────────────────────
    # The realtime react loop (unlike the execution/loops controller
    # path) never renews its TaskSupervisor lease. A turn that outlives
    # the default 300s TTL fails at finish with "lease is no longer
    # current" and stays a zombie "running" task. Heartbeat from the
    # consumer loop (throttled to lease_ttl/3, matching the loops path)
    # keeps the lease alive for long tasks and still lets them
    # terminate cleanly.
    supervisor = getattr(runtime, "_task_supervisor", None)
    _last_supervisor_heartbeat = time.monotonic()
    _supervisor_heartbeat_interval = 0.0
    if supervisor is not None:
        try:
            _supervisor_heartbeat_interval = _lease_renewal_interval_s(
                float(supervisor.lease_ttl_seconds)
            )
        except Exception:  # noqa: BLE001 — malformed supervisor; skip renewal
            _supervisor_heartbeat_interval = 0.0

    def _supervisor_heartbeat_if_due(now: float) -> None:
        nonlocal _last_supervisor_heartbeat
        if (
            supervisor is None
            or _supervisor_heartbeat_interval <= 0.0
            or now - _last_supervisor_heartbeat < _supervisor_heartbeat_interval
        ):
            return
        task_id = turn.task_id or ""
        if not task_id:
            # react_started not seen yet — nothing registered to renew.
            return
        _last_supervisor_heartbeat = now
        try:
            supervisor.heartbeat(task_id)
        except Exception as exc:  # noqa: BLE001 — lease lost/revoked; abort turn
            _logger.warning(
                "react supervisor heartbeat failed for %s: %s — cancelling turn",
                task_id,
                exc,
            )
            if not cancel_source.is_cancelled:
                cancel_source.cancel(reason="task supervisor lease lost")

    saw_terminal_event = False
    try:
        loop_started = time.monotonic()
        while True:
            _supervisor_heartbeat_if_due(time.monotonic())
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
                turn.status = TurnStatus.CANCELLED
                turn.outcome_reason = "user_cancelled"
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
        # Cancel any live orchestrator bridges for this turn. Each bridge
        # subscribes to a parallel batch that already terminated (the loop
        # consumed its synthetic observation), so leaving them running would
        # only leak tasks idling until batch GC.
        bridge_tasks: set[asyncio.Task] = getattr(runtime, "_orchestrator_bridge_tasks", set())
        for task in list(bridge_tasks):
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*bridge_tasks, return_exceptions=True)

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

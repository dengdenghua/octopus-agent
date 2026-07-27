"""Single-agent stream drivers for the realtime runtime.

Split out of ``realtime_cerebrum.py``: pump the ReAct loop (or the
protocol-native tool loop / direct-LLM reflection fast path) on a worker
thread, marshal every yielded event onto an asyncio queue, and translate
each event into ``item/*`` notifications via ``_apply_react_event``.

Every function takes the owning :class:`~runtime.sensing.gateway.
realtime_cerebrum.CerebrumRuntime` as its first argument; cross-method
calls go through the runtime so subclass overrides keep working.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from runtime.execution.tool_engine import (
    normalize_tool_lifecycle_event,
    tool_lifecycle_event_to_react_event,
)
from runtime.memory.threads.event_log import EventLog
from runtime.platform.models import ParsedIntent
from runtime.protocol import (
    ErrorItem,
    GroundingSource,
    ItemStatus,
    ServerMethod,
    TurnParams,
    TurnStatus,
)
from runtime.safety.approval.approval_gate import ApprovalProvider
from runtime.sensing.gateway.realtime_event_bridge import _ReactBridgeState
from runtime.sensing.gateway.realtime_gateway import EventEmitter
from runtime.sensing.gateway.realtime_turn_input import (
    _conversation_messages_from_params,
    _input_metadata,
    _reflex_response_to_text,
    _resume_task_id_from_intent,
    _turn_mode,
)

if TYPE_CHECKING:
    from runtime.protocol import Turn
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

_logger = logging.getLogger(__name__)

# Cadence for the single-agent keepalive. Team turns get a heartbeat from
# the team runner; a solo ReAct turn has no such signal, so a slow model or
# a silently-running tool looks identical to a wedged connection from the
# frontend. We emit a heartbeat only when the event queue has been idle for
# this long (see the consumer loops), so a normally-streaming turn never
# pays for it. Kept well under the frontend's ~10s stall threshold so a
# live-but-quiet turn always gets a keepalive before it's flagged "slow".
_SINGLE_AGENT_HEARTBEAT_INTERVAL_S = 5.0


def _safe_stream_error_message(exc: BaseException, *, limit: int = 1200) -> str:
    """Redact an exception before it becomes a user-visible error item."""

    message = str(exc).strip() or type(exc).__name__
    try:
        from runtime.platform.observability.redactor import redact_text

        message = redact_text(message)
    except Exception:  # pragma: no cover - error reporting must not recurse
        message = type(exc).__name__
    return message[:limit]


async def _emit_turn_heartbeat(emitter: EventEmitter, turn: Turn, started_at: float) -> None:
    """Best-effort ``turn/heartbeat`` for a solo turn's idle stretches.

    Mirrors the team runner's keepalive so the frontend's stream-vitals
    can tell "model still working" from "connection stuck". Never allowed
    to disturb the turn — a failed notify is swallowed.
    """
    with contextlib.suppress(Exception):
        await emitter.notify(
            ServerMethod.TURN_HEARTBEAT,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "elapsedS": round(time.monotonic() - started_at, 1),
            },
        )


def _agentic_stream_event_to_react_event(
    kind: str,
    delta: Any,
    final: Any,
) -> dict[str, Any] | None:
    """Translate native tool-loop tuple events into realtime bridge events."""

    if kind == "text":
        return {"type": "text_delta", "delta": str(delta or "")}
    if kind in {"commentary", "commentary_runtime"}:
        text = str(delta or "")
        return {
            "type": "commentary_delta",
            "delta": text,
            "progress_source": ("runtime" if kind == "commentary_runtime" else "model"),
        }
    if kind == "reasoning":
        return {"type": "thinking_delta", "delta": str(delta or "")}
    if kind == "tool_start" and isinstance(delta, dict):
        return tool_lifecycle_event_to_react_event(
            normalize_tool_lifecycle_event(
                "tool_start",
                delta,
                origin="native",
            )
        )
    if kind == "tool_end" and isinstance(delta, dict):
        return tool_lifecycle_event_to_react_event(
            normalize_tool_lifecycle_event(
                "tool_end",
                delta,
                origin="native",
            )
        )
    if kind == "stats" and isinstance(delta, dict):
        return {"type": "throughput", "usage": delta}
    if kind == "done":
        if final and not isinstance(final, str):
            return {"type": "text_delta", "delta": str(final)}
        return {"type": "react_completed"}
    if kind == "error":
        payload = delta if isinstance(delta, dict) else {}
        return {
            "type": "react_error",
            "kind": str(payload.get("kind") or "agentic_error"),
            "message": str(payload.get("message") or delta or "agentic error"),
        }
    return None


def _apply_orchestration_grant(session_metadata: dict[str, Any]) -> None:
    """Scrub then (maybe) grant the per-turn orchestration token budget.

    ``run_orchestration`` treats ``session.metadata["orchestration_token_budget"]``
    as a TRUSTED spawn-ceiling source, but this metadata dict starts life as the
    client-supplied ``user_context`` — so any client-sent value is a spawn-budget
    escalation and is dropped unconditionally. When the turn carries the
    ``audit.ultracode`` workflow preset, the SERVER grants the budget
    (``ultracode_token_budget()``: preset env → operator env → default), which is
    what lets the preset actually widen the fan-out without the client ever
    choosing the number.
    """
    session_metadata.pop("orchestration_token_budget", None)
    preset = str(session_metadata.get("workflow_preset") or "").strip().lower()
    if preset != "audit.ultracode":
        return
    from runtime.execution.suckers.delegation_budget import ultracode_token_budget

    session_metadata["orchestration_token_budget"] = ultracode_token_budget()


def _should_use_native_tool_loop(
    stack: Any,
    intent: ParsedIntent,
    *,
    planning_mode: bool,
) -> bool:
    """Whether this turn should use protocol-native tool calls first.

    ``planning_mode`` is a plan-first prompt nudge, not a plan-only execution
    tier.  Since 2026-05-31 it deliberately leaves tools enabled, so it must
    not downgrade capable models to the legacy text-parsed ReAct path.
    """
    flag = os.environ.get("OCTOPUS_NATIVE_TOOL_LOOP", "1").strip().lower()
    if flag in {"0", "false", "off", "no"}:
        return False

    user_context = intent.user_context or {}
    explicit = user_context.get("native_tool_loop")
    if explicit is False:
        return False
    metadata = user_context.get("metadata")
    if isinstance(metadata, dict) and metadata.get("native_tool_loop") is False:
        return False

    from runtime.core.cerebrum.todo_protocol import context_mode

    if context_mode(user_context) == "chat":
        return False

    executor = getattr(stack, "executor", None)
    router = getattr(getattr(stack, "planner", None), "router", None)
    if executor is None or router is None or not hasattr(router, "call_stream"):
        return False

    caps = getattr(router, "capabilities", None)
    supports = getattr(caps, "supports_tool_use", None)
    if supports is True:
        return True
    if supports is False:
        return False

    primary = getattr(router, "primary", None)
    primary_caps = getattr(primary, "capabilities", None)
    return getattr(primary_caps, "supports_tool_use", None) is True


def _is_auth_context_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return (
        "current_actor" in text
        or "登录态" in text
        or "Unauthorized" in text
        or "Credentials" in text
        or "Auth" in text
    )


def _model_error_reply(exc: BaseException) -> str | None:
    text = f"{type(exc).__name__}: {exc}"
    lower = text.lower()
    if "http_402" in lower or "insufficient_balance" in lower or "模型账户余额不足" in text:
        return "当前模型账户余额不足，所以这次没有完成。请给当前模型供应商账户充值，或切换到其他可用模型后重试。"
    if "http_401" in lower or "http_403" in lower or "api key" in lower:
        return "当前模型 API Key 无效或没有权限，所以这次没有完成。请在模型设置里更新 Key，或切换到其他可用模型后重试。"
    return None


def _personalize_reflex_reply(reply: str, agent: Any) -> str:
    display_name = str(
        getattr(agent, "display_name", None)
        or getattr(agent, "name", None)
        or getattr(agent, "agent_id", None)
        or ""
    ).strip()
    if not display_name:
        return reply
    return reply.replace("我是 Octopus", f"我是 {display_name}").replace(
        "I'm Octopus", f"I'm {display_name}"
    )


def _should_use_reflection_fast_path(
    runtime: CerebrumRuntime,
    text: str,
    params: TurnParams,
    *,
    conversation_messages: list[dict[str, object]] | None = None,
) -> bool:
    """Route simple, non-tool turns through the reflective direct path."""
    router = getattr(getattr(runtime._stack, "planner", None), "router", None)
    if router is None:
        return False
    mode = _turn_mode(params)
    metadata = _input_metadata(params)
    context = metadata.get("context")
    context_payload = context if isinstance(context, dict) else {}
    capability_mode = str(
        context_payload.get("capability_mode") or metadata.get("capability_mode") or ""
    ).strip()
    # Capability-bearing turns must reach an agentic driver.  The direct
    # reflection path cannot inspect a workspace, invoke browser tools, edit
    # files, or produce verifiable side effects.  Previously ``mode=code``
    # fell through to the broad final return below and silently became a
    # text-only answer.
    if capability_mode or mode in {
        "browser",
        "chrome",
        "code",
        "deep",
        "research",
        "swarm",
    }:
        return False
    from runtime.sensing.gateway.realtime_turn_routing import (
        looks_like_contextual_tool_followup,
        looks_like_plain_chat,
    )

    history = conversation_messages or _conversation_messages_from_params(params)
    if mode == "chat":
        return not looks_like_contextual_tool_followup(text, history)
    if looks_like_contextual_tool_followup(text, history):
        return False
    if mode in {"", "react"}:
        return looks_like_plain_chat(text)
    return True


async def _drive_reflection_fast_path(
    runtime: CerebrumRuntime,
    turn: Turn,
    log: EventLog,
    emitter: EventEmitter,
    intent: ParsedIntent,
    agent: Any,
    *,
    model: str | None = None,
) -> None:
    """Pump direct-LLM reflection output into realtime item events."""
    reflex_reply = runtime._try_reflex_reply(intent)
    if reflex_reply:
        await runtime._emit_agent_message(
            turn,
            log,
            emitter,
            _personalize_reflex_reply(reflex_reply, agent),
        )
        return

    from runtime.safety.approval.cancellation import (
        CancellationSource,
        scoped_cancellation,
    )
    from runtime.sensing.gateway.openai_gateway.stream_handler import (
        _stream_direct_llm_fallback,
    )
    from runtime.sensing.gateway.realtime_turn_routing import local_non_tool_reply

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=64)
    loop = asyncio.get_running_loop()
    cancel_source = CancellationSource()

    def _safe_put(event: dict[str, Any] | None, *, timeout: float = 10.0) -> None:
        try:
            asyncio.run_coroutine_threadsafe(
                queue.put(event),
                loop,
            ).result(timeout=timeout)
        except (RuntimeError, TimeoutError):
            _logger.debug("reflection bridge enqueue dropped")

    def producer() -> None:
        # Chat fast-path (direct LLM, no ReAct). Feed journal_context
        # so token-usage events emitted here carry the thread_id
        # instead of None — this path has no Session/session_scope.
        from runtime.memory.journal.journal_context import journal_context

        _jagent = getattr(agent, "agent_id", None) if agent is not None else None
        with (
            journal_context(
                conversation_id=turn.thread_id,
                agent_id=_jagent,
            ),
            scoped_cancellation(cancel_source.token),
        ):
            try:
                for kind, payload, _final in (
                    _stream_direct_llm_fallback(
                        runtime._stack,
                        intent,
                        agent,
                        model=model,
                        reasoning_effort=(intent.user_context or {}).get(
                            "reasoning_effort",
                        ),
                    )
                    or ()
                ):
                    if cancel_source.is_cancelled:
                        _safe_put({"type": "react_cancelled"})
                        return
                    if kind == "text":
                        evt = {"type": "text_delta", "delta": payload or ""}
                    elif kind == "reasoning":
                        evt = {"type": "thinking_delta", "delta": payload or ""}
                    elif kind == "done":
                        evt = {"type": "throughput", "usage": payload}
                    else:
                        continue
                    _safe_put(evt)
            except Exception as exc:  # noqa: BLE001
                if cancel_source.is_cancelled:
                    _safe_put({"type": "react_cancelled"})
                    return
                fallback = _model_error_reply(exc) or (
                    local_non_tool_reply(intent.raw) if _is_auth_context_error(exc) else None
                )
                if fallback:
                    _safe_put({"type": "text_delta", "delta": fallback})
                    return
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
    state = runtime._make_bridge_state(turn.thread_id)

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
                    await _emit_turn_heartbeat(emitter, turn, loop_started)
                continue
            if evt is None:
                break
            if emitter.is_turn_interrupted(turn.id):
                if not cancel_source.is_cancelled:
                    cancel_source.cancel(reason="user interrupted turn")
                turn.status = TurnStatus.INTERRUPTED
                # Drain rather than break — the producer must reach
                # its ``None`` sentinel for the worker thread to
                # finish cleanly.
                continue
            try:
                await runtime._apply_react_event(turn, log, emitter, state, evt)
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "reflection event apply failed (kind=%s): %s",
                    evt.get("type") if isinstance(evt, dict) else "?",
                    exc,
                    exc_info=True,
                )
    finally:
        # Trip cancellation so the producer THREAD (asyncio.to_thread,
        # which task cancellation can't reach) observes it and bails
        # fast instead of looping to completion against a dead queue.
        # Without this, a consumer cancelled by ws disconnect leaves
        # the worker piling up pending Queue.put() tasks.
        cancel_source.cancel(reason="consumer teardown")
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
        with contextlib.suppress(Exception):
            await worker
    with contextlib.suppress(Exception):
        await state.flush(
            turn,
            log,
            emitter,
            status=state.prose_status_for_turn(turn.status),
        )


def _try_reflex_reply(runtime: CerebrumRuntime, intent: ParsedIntent) -> str | None:
    router = runtime._reflex_router
    if router is None:
        return None
    try:
        result = router.try_match(intent)
    except Exception:  # noqa: BLE001
        _logger.debug("realtime reflex match skipped", exc_info=True)
        return None
    if not hasattr(result, "response"):
        return None
    return _reflex_response_to_text(getattr(result, "response", None))


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
            _logger.debug(
                "react bridge enqueue failed/timed out (event=%s)",
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
            _logger.debug("tool_output_delta drop (consumer slow)")

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
    state = runtime._make_bridge_state(turn.thread_id, turn.id)

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
                # Keep draining so the producer's bounded ``put``
                # calls succeed and it can reach its ``None`` sentinel
                # cleanly. Breaking here would leave the worker
                # blocked on a full queue.
                continue
            try:
                await runtime._apply_react_event(turn, log, emitter, state, evt)
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
            await runtime._apply_react_event(
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
            await runtime._apply_react_event(
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
        if evt.get("progress_source") == "runtime" and not evt.get("public_evidence"):
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
            log.turn_updated(
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

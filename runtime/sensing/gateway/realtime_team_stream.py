"""Multi-agent team-topology stream driver for the realtime runtime.

Split out of ``realtime_cerebrum.py``: resolve a ``topology_id`` through
the organization registry, run ``TeamRunner`` on a worker thread, and
bridge its live events (role text, sub-tool calls, subagent lifecycle,
heartbeats) onto the same ``item/*`` notifications the ReAct path uses.
Falls back to single-agent ReAct when the topology id is stale.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from typing import TYPE_CHECKING, Any

from runtime.memory.threads.event_log import EventLog
from runtime.platform.models import ParsedIntent
from runtime.protocol import (
    AgentMessageItem,
    ErrorItem,
    ItemStatus,
    ServerMethod,
    SubagentItem,
    Turn,
    TurnStatus,
)
from runtime.sensing.gateway.realtime_approval import GatewayApprovalProvider
from runtime.sensing.gateway.realtime_gateway import EventEmitter

if TYPE_CHECKING:
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

_logger = logging.getLogger(__name__)


async def _drive_team_topology(
    runtime: CerebrumRuntime,
    turn: Turn,
    log: EventLog,
    emitter: EventEmitter,
    intent: ParsedIntent,
    *,
    text: str,
    topology_id: str,
) -> None:
    """Run the turn through a multi-agent ``TeamTopology``.

    ╔═══════════════════════════════════════════════════════════════╗
    ║ _drive_team_topology · navigation (523 lines, async bridge).  ║
    ║                                                               ║
    ║   PHASE 1 · topology resolution + fallback       ~L2182      ║
    ║   PHASE 2 · queue bridge setup                   ~L2230      ║
    ║   PHASE 3 · producer thread definition           ~L2281      ║
    ║   PHASE 4 · interrupt watcher + helpers          ~L2360      ║
    ║   PHASE 5 · consumer loop (event dispatch)       ~L2480      ║
    ║   PHASE 6 · finalization + perf log              ~L2635      ║
    ║                                                               ║
    ║ Why one big async method: producer thread + asyncio queue     ║
    ║ bridge + nested async closures sharing ~10 state vars.        ║
    ╚═══════════════════════════════════════════════════════════════╝

    The topology id resolves through the organization registry by
    fingerprint *or* by name. On miss we fall back to single-agent
    ReAct so a stale ``topology_id`` never aborts the turn.

    Each role's output emits as a separate ``AgentMessageItem`` so
    the client sees the team's reasoning trace; the team's final
    output becomes the trailing AgentMessageItem and the run gets
    recorded into ``data/topology_performance.jsonl`` for the
    evolver to score next tick.
    """
    # ── PHASE 1 · topology resolution + fallback ────────────────
    from runtime.safety.evolution.governance_audit import (
        append_governance_audit_event,
    )
    from runtime.safety.evolution.subagent_policy import evaluate_agent_policy
    from runtime.safety.organization import TeamTopology
    from runtime.safety.organization.forge import load_registry
    from runtime.safety.organization.performance_log import record_run
    from runtime.safety.organization.team_runner import (
        TeamRunner,
        TeamRunResult,
    )

    async def _fallback_to_react() -> None:
        loop = asyncio.get_running_loop()
        gateway_provider = GatewayApprovalProvider(
            emitter,
            loop,
            thread_id=intent.user_context.get("thread_id", turn.thread_id),
            turn_id=turn.id,
            trace_store=runtime._trace_store,
        )
        provider = runtime._wrap_with_policy(gateway_provider)
        from runtime.protocol.items import TurnParams  # local

        agent = None
        try:
            agent = runtime._resolve_agent(
                TurnParams(threadId=turn.thread_id, input=[]),  # type: ignore[call-arg]
            )
        except Exception:  # noqa: BLE001
            _logger.debug("agent resolution failed, using default", exc_info=True)
            agent = None
        await runtime._drive_react(turn, log, emitter, intent, provider, agent)

    thread_id = turn.thread_id
    registry = load_registry()
    topology: TeamTopology | None = registry.get(topology_id)
    if topology is None:
        # Allow name lookup as a convenience (UI users will refer
        # to topologies by their human-readable name, not the
        # fingerprint).
        for t in registry.values():
            if t.name == topology_id:
                topology = t
                break
    if topology is None:
        _logger.warning(
            "topology_id %r not in registry · falling back to react",
            topology_id,
        )
        await _fallback_to_react()
        return
    policy_report = evaluate_agent_policy({
        str(role): spec.agent_id
        for role, spec in topology.agents.items()
    })
    if policy_report.get("blocked"):
        _logger.warning(
            "topology_id %r is blocked by operator subagent policy · "
            "falling back to react",
            topology_id,
        )
        with contextlib.suppress(Exception):
            append_governance_audit_event(
                event_type="topology_policy_block",
                target="topology_policy",
                status="blocked",
                agent_id=str(intent.user_context.get("agent_id") or ""),
                artifact={
                    "topology_id": topology_id,
                    "topology_name": topology.name,
                    "topology_fingerprint": topology.fingerprint,
                    "subagent_policy": policy_report,
                },
                decision_context={
                    "thread_id": thread_id,
                    "turn_id": turn.id,
                    "source": "realtime_team_topology",
                },
            )
        await _fallback_to_react()
        return

    # ── PHASE 2 · queue bridge setup ────────────────────────────
    runner_timeout = int(runtime._max_iterations * 30)

    # Live-event bridge: TeamRunner -> emitter (this coroutine).
    #
    # Why this exists: ``TeamRunner.run`` is synchronous and used to
    # be invoked through ``asyncio.to_thread(...)`` followed by a
    # batch flush of every role's output. For a 3-role research swarm
    # that meant the user saw nothing for 60-120 seconds, then a
    # wall of text — and during the silent window the WS often
    # closed because the frontend treated "no events for N seconds"
    # as an interrupted stream ("本次回复已中断").
    #
    # Now: producer thread runs ``runner.run`` with an emitter that
    # marshals every progress event onto the asyncio queue; this
    # coroutine drains the queue and translates events into
    # ``item/*`` notifications using the same ``_ReactBridgeState``
    # the ReAct path uses, so subagents in a swarm appear in the
    # UI's tool timeline alongside regular tool calls.
    from runtime.safety.approval.cancellation import (
        CancellationSource,
        scoped_cancellation,
    )

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=128)
    loop = asyncio.get_running_loop()
    cancel_source = CancellationSource()

    def _push(event: dict[str, Any]) -> None:
        # Producer side: marshal events back to the asyncio loop.
        # Use ``run_coroutine_threadsafe(...).result()`` so the
        # producer thread blocks if the consumer can't keep up
        # (instead of fire-and-forget which silently drops events
        # when the queue is full). Bounded blocking is safe here
        # because the consumer drains continuously; the only way
        # we'd block forever is consumer dead, which would surface
        # as a hung turn anyway.
        try:
            asyncio.run_coroutine_threadsafe(
                queue.put(event),
                loop,
            ).result(timeout=10.0)
        except (RuntimeError, TimeoutError):
            # RuntimeError: loop closed mid-call.
            # TimeoutError: consumer stuck — drop this event rather
            # than block the producer indefinitely. Telemetry only;
            # the run keeps going.
            _logger.debug(
                "team_runner emitter push failed/timed out",
            )

    # ── PHASE 3 · producer thread definition ────────────────────
    def producer() -> TeamRunResult:
        from runtime.memory.journal.journal_context import journal_context
        from runtime.platform.process.session import Session, session_scope

        session_metadata = dict(intent.user_context or {})
        turn_session = Session(
            agent=None,
            thread_id=thread_id,
            conversation_id=thread_id,
            turn_id=turn.id,
            metadata=session_metadata,
        )
        # Install the cancellation scope on the worker thread so
        # ``call_subagent`` inside the runner sees the same token
        # as react_loop does — every long-running subprocess /
        # network call inside a role checks
        # ``current_cancellation_token()`` and bails out fast.
        # journal_context feeds the journal's conversation_id
        # contextvar (separate from session_scope) so trace rows
        # carry thread_id instead of None.
        with (
            session_scope(turn_session),
            journal_context(conversation_id=thread_id),
            scoped_cancellation(cancel_source.token),
        ):
            try:
                runner = TeamRunner(
                    timeout_seconds=runner_timeout,
                    event_emitter=_push,
                )
                return runner.run(
                    topology,
                    text,
                    context={
                        "thread_id": thread_id,
                        "turn_id": turn.id,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - surface as event
                with contextlib.suppress(RuntimeError, TimeoutError):
                    asyncio.run_coroutine_threadsafe(
                        queue.put(
                            {
                                "type": "team_runner_error",
                                "kind": exc.__class__.__name__,
                                "message": str(exc),
                            }
                        ),
                        loop,
                    ).result(timeout=5.0)
                return TeamRunResult(
                    topology_name=topology.name,
                    topology_fingerprint=topology.fingerprint,
                    task_bucket=topology.task_bucket,
                    success=False,
                    final_output="",
                    error=f"{type(exc).__name__}: {exc}",
                )
            finally:
                # Always send the sentinel even if the consumer has
                # already gone away — suppress so we don't deadlock
                # the worker thread when the loop is torn down.
                with contextlib.suppress(RuntimeError, TimeoutError):
                    asyncio.run_coroutine_threadsafe(
                        queue.put(None),
                        loop,
                    ).result(timeout=5.0)

    worker = asyncio.create_task(asyncio.to_thread(producer))
    state = runtime._make_bridge_state(turn.thread_id)
    # Track how many characters of role text streamed in via
    # ``sub_text_delta`` for the currently-open role. ``team_role_end``
    # uses this to decide whether to dump the role's full output as a
    # one-shot bubble (zero streamed → we never got live text, fall
    # back to the post-hoc dump) or skip it (already streamed).
    streamed_chars: dict[str, int] = {"count": 0}
    subagent_items: dict[str, SubagentItem] = {}
    subagent_seq = 0

    # ── PHASE 4 · interrupt watcher + helpers ───────────────────
    async def _interrupt_watcher() -> None:
        # Trip cancellation the instant the gateway records a
        # ``turn/interrupt`` for this turn id. Without this the
        # swarm runs to natural completion (or to the
        # ``runner_timeout`` of ``max_iterations * 30`` seconds)
        # even after the user clicks "stop".
        try:
            while not cancel_source.is_cancelled:
                if emitter.is_turn_interrupted(turn.id):
                    cancel_source.cancel(reason="user interrupted turn")
                    return
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            return

    watcher = asyncio.create_task(_interrupt_watcher())

    async def _safe_notify(method: Any, params: dict[str, Any]) -> None:
        # WS may close while we're mid-stream. Notify is best-effort
        # at the consumer layer — we don't want a single ws.send
        # failure to abort processing of the rest of the queue
        # (and the run_result we're waiting on).
        try:
            await emitter.notify(method, params)
        except Exception as exc:  # noqa: BLE001
            _logger.debug("emitter.notify failed: %s", exc, exc_info=True)

    async def _safe_emit_started(turn: Turn, log: EventLog, item: Any) -> None:
        log.item_started(turn.thread_id, turn.id, item)
        await _safe_notify(
            ServerMethod.ITEM_STARTED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )

    async def _safe_emit_completed(turn: Turn, log: EventLog, item: Any) -> None:
        log.item_completed(turn.thread_id, turn.id, item)
        await _safe_notify(
            ServerMethod.ITEM_COMPLETED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )

    def _coerce_str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item is not None]

    def _subagent_key(evt: dict[str, Any]) -> str:
        raw = str(evt.get("agent_id") or evt.get("role") or "subagent")
        return raw or "subagent"

    async def _emit_subagent_lifecycle(evt: dict[str, Any]) -> None:
        nonlocal subagent_seq
        ekind = str(evt.get("type") or "")
        agent_key = _subagent_key(evt)
        role = str(evt.get("role") or "") or None
        codename = str(evt.get("codename") or "") or None
        avatar = str(evt.get("avatar") or "") or None
        status = str(evt.get("status") or "") or None
        existing = subagent_items.get(agent_key)
        if existing is None:
            subagent_seq += 1
            safe_agent = re.sub(r"[^A-Za-z0-9_.:-]+", "_", agent_key).strip("_")
            item_id = f"sub_{safe_agent or 'agent'}_{subagent_seq}"[:80]
            existing = SubagentItem(
                id=item_id,
                subagent_id=agent_key,
                role=role,
                name=codename,
                codename=codename,
                avatar=avatar,
                status=ItemStatus.IN_PROGRESS,
            )
            subagent_items[agent_key] = existing
            turn.items.append(existing)
            await _safe_emit_started(turn, log, existing)
        elif ekind == "subagent_spawned":
            existing = existing.model_copy(
                update={
                    "role": role or existing.role,
                    "name": codename or existing.name,
                    "codename": codename or existing.codename,
                    "avatar": avatar or existing.avatar,
                }
            )
            subagent_items[agent_key] = existing
            turn.items = [existing if item.id == existing.id else item for item in turn.items]
            await _safe_emit_started(turn, log, existing)
        if ekind != "subagent_finished":
            return

        ok = bool(evt.get("ok", True)) and not evt.get("error")
        try:
            iteration_count = int(evt.get("iteration_count"))
        except (TypeError, ValueError):
            iteration_count = existing.iteration_count
        completed = existing.model_copy(
            update={
                "status": ItemStatus.COMPLETED if ok else ItemStatus.FAILED,
                "role": role or existing.role,
                "name": codename or existing.name,
                "codename": codename or existing.codename,
                "avatar": avatar or existing.avatar,
                "summary": status or existing.summary,
                "error": str(evt.get("error")) if evt.get("error") else None,
                "iteration_count": iteration_count,
                "files_touched": _coerce_str_list(evt.get("files_touched")),
            }
        )
        subagent_items[agent_key] = completed
        turn.items = [completed if item.id == completed.id else item for item in turn.items]
        await _safe_emit_completed(turn, log, completed)

    # ── PHASE 5 · consumer loop (event dispatch) ────────────────
    run_result: TeamRunResult | None = None
    try:
        while True:
            evt = await queue.get()
            if evt is None:
                break
            if emitter.is_turn_interrupted(turn.id):
                if not cancel_source.is_cancelled:
                    cancel_source.cancel(reason="user interrupted turn")
                turn.status = TurnStatus.INTERRUPTED
                # Keep draining so the producer can finish cleanly
                # (and emit its final None sentinel) — don't break
                # mid-queue or the worker hangs on its put().
                continue
            ekind = evt.get("type")
            if ekind == "team_role_start":
                # Close any running role bubble first.
                await state.flush(turn, log, emitter)
                role_label = str(evt.get("role") or "role")
                agent_id = str(evt.get("agent_id") or "")
                header = f"[{role_label}] starting · agent={agent_id}\n"
                await state.append_agent_message(
                    turn,
                    log,
                    emitter,
                    header,
                )
                # Reset the streamed-chars counter for this role so
                # the team_role_end completion check below can tell
                # whether the role's text already streamed in vs.
                # needs a one-shot dump.
                streamed_chars["count"] = 0
            elif ekind == "sub_text_delta":
                # Live role text. Each chunk lands on the currently-
                # open AgentMessageItem (opened by team_role_start).
                # Without this, role text only appeared after the
                # role finished — the user saw a 30s gap between
                # "role starting" and the role's verdict.
                chunk = str(evt.get("delta") or "")
                if chunk:
                    await state.append_agent_message(
                        turn,
                        log,
                        emitter,
                        chunk,
                    )
                    streamed_chars["count"] += len(chunk)
            elif ekind == "team_role_end":
                await state.flush(turn, log, emitter)
                if evt.get("status") == "error":
                    err_text = str(evt.get("error") or "role failed")
                    body = f"[{evt.get('role')}] FAILED · {err_text}"
                    item = AgentMessageItem(
                        text=body,
                        status=ItemStatus.COMPLETED,
                    )
                    turn.items.append(item)
                    await _safe_emit_started(turn, log, item)
                    await _safe_emit_completed(turn, log, item)
                else:
                    # Two completion paths:
                    #
                    # 1. ``streamed_chars["count"] > 0``: text already
                    #    landed via ``sub_text_delta`` chunks. Just
                    #    flush the open AgentMessageItem so the UI
                    #    marks it complete; the body is already there.
                    #
                    # 2. ``streamed_chars["count"] == 0``: the
                    #    underlying router didn't stream (synthetic
                    #    fallback, or this role used ``call`` not
                    #    ``call_stream``). Fall back to a one-shot
                    #    AgentMessageItem with the role's full output
                    #    so the user still sees the verdict instead
                    #    of just the header.
                    await state.flush(turn, log, emitter)
                    if streamed_chars["count"] == 0:
                        out_text = str(evt.get("output") or "").strip()
                        if out_text:
                            body = f"[{evt.get('role')}] {out_text[:8000]}"
                            item = AgentMessageItem(
                                text=body,
                                status=ItemStatus.COMPLETED,
                            )
                            turn.items.append(item)
                            await _safe_emit_started(turn, log, item)
                            await _safe_emit_completed(turn, log, item)
                    # Reset for the next role.
                    streamed_chars["count"] = 0
            elif ekind == "sub_tool_start":
                # Translate to the react_loop tool_start shape so
                # ``state.start_tool`` can render this in the UI's
                # live tool timeline alongside react-mode tools.
                # Prefer the upstream ``tool_call_id`` (the LLM's
                # ToolCall.id, guaranteed unique within a round)
                # and fall back to a synthetic key only when the
                # producer didn't supply one (older path / mocks).
                call_id = str(evt.get("tool_call_id") or "") or (
                    f"{evt.get('agent_id', 'role')}-r"
                    f"{evt.get('round', 0)}-{evt.get('skill', 'tool')}"
                )
                await state.start_tool(
                    turn,
                    log,
                    emitter,
                    {
                        "tool_call_id": call_id,
                        "tool_name": str(evt.get("skill") or "tool"),
                        "input_preview": evt.get("args_preview"),
                        "iteration": evt.get("round"),
                    },
                )
            elif ekind == "sub_tool_end":
                call_id = str(evt.get("tool_call_id") or "") or (
                    f"{evt.get('agent_id', 'role')}-r"
                    f"{evt.get('round', 0)}-{evt.get('skill', 'tool')}"
                )
                await state.complete_tool(
                    turn,
                    log,
                    emitter,
                    {
                        "tool_call_id": call_id,
                        "status": evt.get("status", "success"),
                        "duration_ms": evt.get("duration_ms"),
                    },
                )
            elif ekind in {"subagent_spawned", "subagent_finished"}:
                await _emit_subagent_lifecycle(evt)
            elif ekind == "team_heartbeat":
                # Lightweight keepalive: prevents the frontend's
                # pong-timeout (70s) from killing the WS during
                # long-running roles that don't produce text deltas
                # (e.g. a researcher doing multi-step web_search).
                # Emit an empty agent message delta so the frontend
                # sees activity without polluting the message body.
                await _safe_notify(
                    ServerMethod.TURN_HEARTBEAT,
                    {
                        "threadId": thread_id,
                        "turnId": turn.id,
                        "role": str(evt.get("role") or ""),
                        "agentId": str(evt.get("agent_id") or ""),
                        "elapsedS": evt.get("elapsed_s", 0),
                    },
                )
            elif ekind == "team_runner_error":
                await state.flush(turn, log, emitter)
                err = ErrorItem(
                    message=str(evt.get("message") or "team runner error"),
                    will_retry=False,
                )
                turn.status = TurnStatus.FAILED
                turn.items.append(err)
                await _safe_emit_started(turn, log, err)
                await _safe_emit_completed(turn, log, err)
    finally:
        # ── PHASE 6 · finalization + perf log ───────────────────
        # Trip cancellation so the producer THREAD bails fast (task
        # cancellation can't reach an asyncio.to_thread worker). On a
        # ws-disconnect teardown this is what stops the runner from
        # looping against a dead queue and orphaning the thread.
        cancel_source.cancel(reason="consumer teardown")
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
        with contextlib.suppress(Exception):
            await state.flush(turn, log, emitter)
        # Always reap the worker so the thread can't outlive the turn.
        with contextlib.suppress(Exception):
            run_result = await worker
    if run_result is None:
        # Consumer was torn down before the worker produced a result
        # (e.g. ws disconnect). Nothing more to finalize.
        return

    # If the watcher tripped cancellation, prefer that over the
    # natural success/fail outcome — the user explicitly stopped.
    if cancel_source.is_cancelled:
        turn.status = TurnStatus.INTERRUPTED
    elif run_result.success:
        turn.status = TurnStatus.COMPLETED
    else:
        turn.status = TurnStatus.FAILED

    with contextlib.suppress(Exception):
        await state.finalize_workbench(
            turn,
            log,
            emitter,
            terminal_status=turn.status,
        )

    # Record into the topology performance log so the evolver has
    # something to score. Best-effort: a write failure must not
    # take down the turn that just succeeded.
    with contextlib.suppress(Exception):
        record_run(
            run_result,
            extra={
                "thread_id": thread_id,
                "turn_id": turn.id,
            },
        )


def _graph_favors_mesh(graph: Any) -> bool:
    """Decide whether the parallel mesh swarm is worth it for this graph.

    Mesh only beats the sequential team when there is real parallelism to
    exploit — several nodes AND a topo-layer with independent siblings. A small
    or strictly-sequential graph runs no faster on the mesh (and the mesh skips
    the team's curated topologies), so those go to the team. This is what lets
    the engine be auto-selected instead of toggled by hand.
    """
    nodes = getattr(graph, "nodes", None) or []
    if len(nodes) < 3:
        return False
    try:
        from runtime.execution.swarm.runtime import _split_topo_layers

        layers = _split_topo_layers(graph)
    except Exception:  # noqa: BLE001 — undecidable → let the team handle it
        return False
    widest = max((len(layer) for layer in layers), default=1)
    return widest >= 2


async def _drive_swarm_mesh(
    runtime: Any,
    turn: Turn,
    log: EventLog,
    emitter: EventEmitter,
    intent: ParsedIntent,
    *,
    text: str,
    topology_id: str = "",
) -> None:
    """Run a swarm-mode turn on the best engine for the task — auto-selected.

    Plans the graph, then: a parallel graph (>=3 nodes, a layer with
    independent siblings) runs on the boids/SignalBus MESH swarm
    (``SwarmRuntime`` — parallel arms over a registry-derived pool with live
    Arm-to-Arm coordination); a small or sequential graph runs on the
    sequential ``TeamRunner`` (``topology_id``). ``OCTOPUS_SERVE_MESH=1``/``0``
    forces mesh/team; unset = auto. Any mesh fault falls back to react, so a
    swarm problem never takes down the turn.
    """
    import asyncio

    async def _emit(body: str) -> None:
        item = AgentMessageItem(text=body, status=ItemStatus.COMPLETED)
        turn.items.append(item)
        with contextlib.suppress(Exception):
            log.item_started(turn.thread_id, turn.id, item)
            log.item_completed(turn.thread_id, turn.id, item)
        payload = {
            "threadId": turn.thread_id,
            "turnId": turn.id,
            "item": item.model_dump(by_alias=True, mode="json"),
        }
        with contextlib.suppress(Exception):
            await emitter.notify(ServerMethod.ITEM_STARTED, payload)
            await emitter.notify(ServerMethod.ITEM_COMPLETED, payload)

    async def _fallback_to_react() -> None:
        loop = asyncio.get_running_loop()
        gateway_provider = GatewayApprovalProvider(
            emitter,
            loop,
            thread_id=intent.user_context.get("thread_id", turn.thread_id),
            turn_id=turn.id,
            trace_store=runtime._trace_store,
        )
        provider = runtime._wrap_with_policy(gateway_provider)
        from runtime.protocol.items import TurnParams

        agent = None
        with contextlib.suppress(Exception):
            agent = runtime._resolve_agent(
                TurnParams(threadId=turn.thread_id, input=[]),  # type: ignore[call-arg]
            )
        await runtime._drive_react(turn, log, emitter, intent, provider, agent)

    def _session():
        from runtime.memory.journal.journal_context import journal_context
        from runtime.platform.process.session import Session, session_scope

        turn_session = Session(
            agent=None,
            thread_id=turn.thread_id,
            conversation_id=turn.thread_id,
            turn_id=turn.id,
            metadata=dict(intent.user_context or {}),
        )
        return session_scope(turn_session), journal_context(
            conversation_id=turn.thread_id,
        )

    def _plan() -> Any:
        scope, jctx = _session()
        with scope, jctx:
            return runtime._stack.planner.plan(intent)

    def _run(graph: Any) -> Any:
        from runtime.core.graph_runtime import GraphRuntime
        from runtime.execution.swarm.drive import (
            build_arm_pool_from_registry,
            run_swarm,
        )
        from runtime.platform.models import Budget, BudgetLimits
        from runtime.safety.chromatophores import SignalBus

        stack = runtime._stack
        scope, jctx = _session()
        with scope, jctx:
            grt = GraphRuntime(executor=stack.executor, journal=stack.journal)
            sb = SignalBus()
            pool = build_arm_pool_from_registry(stack.registry, grt, signal_bus=sb)
            budget = Budget(
                task_id=graph.task_id,
                limits=BudgetLimits(tokens=200_000, usd=2.0),
            )
            strategy = "topo_layers" if getattr(graph, "edges", None) else "per_node"
            signals: list[Any] = []
            result = run_swarm(
                graph, budget, arm_pool=pool, signal_bus=sb,
                journal=stack.journal, split_strategy=strategy,
                on_signal=signals.append,
            )
            return result, len(signals)

    import os

    # Engine choice precedence: the per-turn UI pick (集群 vs 蜂群) wins, then
    # the OCTOPUS_SERVE_MESH env, then auto (_graph_favors_mesh). The UI sends
    # serve_mesh="1" for 蜂群 (mesh) and "0" for 集群 (sequential TeamRunner);
    # absent = auto, which keeps the "smart default, overridable" (B) behavior.
    ctx = getattr(intent, "user_context", None) or {}
    force = str(ctx.get("serve_mesh") or "").strip().lower()
    if not force:
        force = os.environ.get("OCTOPUS_SERVE_MESH", "").strip().lower()
    forced_off = force in {"0", "false", "no", "off"}
    forced_on = force in {"1", "true", "yes", "on"}

    graph: Any = None
    with contextlib.suppress(Exception):
        graph = await asyncio.to_thread(_plan)

    use_mesh = (
        graph is not None
        and not forced_off
        and (forced_on or _graph_favors_mesh(graph))
    )
    if not use_mesh:
        # small / sequential / planning failed / forced off → sequential team
        await _drive_team_topology(
            runtime, turn, log, emitter, intent, text=text, topology_id=topology_id,
        )
        return

    try:
        result, signal_count = await asyncio.to_thread(_run, graph)
        arms = list(getattr(result, "arm_results", []) or [])
        # Plain language for the chat: no "swarm / arm / coordination signal"
        # jargon. Only surface the agents that hit a problem, then one summary.
        failed = [a for a in arms if str(getattr(a, "status", "")) != "success"]
        for arm in failed:
            reason = str(getattr(arm, "reason", "") or "").strip()[:2000]
            await _emit(f"One agent couldn't finish: {reason or 'unknown error'}")
        done = len(arms) - len(failed)
        tail = f", {len(failed)} need a look" if failed else ""
        # Surface the SignalBus chatter — observable proof the agents actually
        # shared progress with each other, not just ran in isolation.
        shared = (
            f" · shared {signal_count} live updates between them"
            if signal_count
            else ""
        )
        await _emit(f"Ran {len(arms)} agents in parallel — {done} done{tail}{shared}")
    except Exception as exc:  # noqa: BLE001 — never break the turn on a mesh fault
        _logger.warning(
            "mesh swarm failed (%s: %s) — falling back to react",
            type(exc).__name__, exc,
        )
        await _fallback_to_react()


async def _drive_group_fanout(
    runtime: Any,
    turn: Turn,
    log: EventLog,
    emitter: EventEmitter,
    intent: ParsedIntent,
    *,
    text: str,
) -> None:
    """蜂群 / 冒泡: fan the message out to every member agent in parallel and
    emit each persona reply as its own group-chat bubble — the "boss speaks,
    everyone chimes in" experience. Falls back to single-agent ReAct when the
    room has <2 member agents or nobody answers, so the turn never stalls.
    """
    import asyncio

    ctx = getattr(intent, "user_context", None) or {}
    roster = ctx.get("agent_roster") or []
    members = [
        {
            "name": str(r.get("agent_id")),
            "display_name": str(r.get("display_name") or r.get("agent_id")),
        }
        for r in roster
        if isinstance(r, dict) and r.get("agent_id")
    ]

    async def _emit(
        body: str,
        *,
        display_name: str | None = None,
        agent_id: str | None = None,
        icon: str | None = None,
    ) -> None:
        # Tag the bubble with its real author so the UI shows that member's
        # avatar + name instead of the turn leader's. Use the shared resolver so
        # the URL carries ``?v=<mtime>`` — that cache-busts when an agent's
        # avatar file changes (e.g. swapping in a brand logo).
        avatar_url: str | None = None
        if agent_id:
            try:
                from runtime.sensing.gateway.agents_router import _avatar_url_for

                avatar_url = _avatar_url_for(agent_id)
            except Exception:  # noqa: BLE001 — avatar is decoration; never break the turn
                avatar_url = None
            avatar_url = avatar_url or f"/api/agents/{agent_id}/avatar"
        item = AgentMessageItem(
            text=body,
            status=ItemStatus.COMPLETED,
            agent_display_name=display_name,
            agent_avatar_url=avatar_url,
            agent_icon=icon,
        )
        turn.items.append(item)
        with contextlib.suppress(Exception):
            log.item_started(turn.thread_id, turn.id, item)
            log.item_completed(turn.thread_id, turn.id, item)
        payload = {
            "threadId": turn.thread_id,
            "turnId": turn.id,
            "item": item.model_dump(by_alias=True, mode="json"),
        }
        with contextlib.suppress(Exception):
            await emitter.notify(ServerMethod.ITEM_STARTED, payload)
            await emitter.notify(ServerMethod.ITEM_COMPLETED, payload)

    async def _fallback_to_react() -> None:
        loop = asyncio.get_running_loop()
        gateway_provider = GatewayApprovalProvider(
            emitter,
            loop,
            thread_id=intent.user_context.get("thread_id", turn.thread_id),
            turn_id=turn.id,
            trace_store=runtime._trace_store,
        )
        provider = runtime._wrap_with_policy(gateway_provider)
        from runtime.protocol.items import TurnParams

        agent = None
        with contextlib.suppress(Exception):
            agent = runtime._resolve_agent(
                TurnParams(threadId=turn.thread_id, input=[]),  # type: ignore[call-arg]
            )
        await runtime._drive_react(turn, log, emitter, intent, provider, agent)

    if len(members) < 2:
        # Not a real group → one agent answers (the normal single-agent path).
        await _fallback_to_react()
        return

    try:
        import os

        from runtime.execution.agents.cli_team import (
            detect_installed_partners,
            run_cli_team,
        )
        from runtime.execution.agents.group_fanout import run_group_fanout
        from runtime.execution.agents.local_partner_bridge import run_local_partner
        from runtime.execution.suckers.delegation_skills import _call_agent

        # agent_id → {partner_id, command} for the CLIs actually on this machine.
        detected = {d["agent_id"]: d for d in detect_installed_partners()}

        def _mentioned(display: str) -> bool:
            parts = display.split()
            cands = {display, parts[0] if parts else display, display.replace(" ", "")}
            return any(c and ("@" + c) in text for c in cands)

        # Cheap cue that the user wants a CLI partner to actually DO work (run
        # in a worktree) rather than just chime in. Conservative — defaults to
        # chat so a casual "@Codex 在么" never fires a heavyweight run.
        task_cues = (
            "改", "写", "修", "实现", "重构", "添加", "新增", "删", "创建", "生成",
            "优化", "修复", "测试", "运行", "跑", "重命名", "替换", "集成", "接入",
            "fix", "add", "implement", "refactor", "write", "create", "run",
            "test", "build", "rename", "replace", "update", "bug",
        )

        def _looks_like_task(t: str) -> bool:
            low = t.lower()
            return len(t.strip()) >= 6 and any(cue in low for cue in task_cues)

        # Split: local partners @-mentioned WITH a task → real worktree run;
        # everyone else (persona agents + partners just chatting) → group bubble.
        work_members = [
            m
            for m in members
            if m["name"] in detected
            and _mentioned(m["display_name"])
            and _looks_like_task(text)
        ]
        work_ids = {m["name"] for m in work_members}
        chat_members = [m for m in members if m["name"] not in work_ids]
        # @-mentioned chat members first so a small fan-out cap never drops them.
        chat_members.sort(key=lambda m: 0 if _mentioned(m["display_name"]) else 1)

        def _member_caller(
            agent_id: str, prompt: str, timeout_s: int = 90
        ) -> dict[str, Any]:
            """Persona agents run in-process; local CLI partners bridge to their
            real CLI for a short, conversational group-chat bubble."""
            info = detected.get(agent_id)
            if info is not None:
                r = run_local_partner(
                    partner_id=info["partner_id"],
                    command=info["command"],
                    prompt=prompt,
                    timeout=min(int(timeout_s), 60),
                )
                return {
                    "success": bool(r.ok),
                    "output": r.output or "",
                    "error": r.error,
                }
            return _call_agent(agent_id=agent_id, prompt=prompt, timeout_s=timeout_s)

        spoke = 0
        if chat_members:
            result = await asyncio.to_thread(
                run_group_fanout,
                text,
                chat_members,
                agent_caller=_member_caller,
                # Cover the whole roster (was hard-capped at 5, which silently
                # dropped members ordered last — e.g. the local CLI partners).
                max_members=min(8, max(2, len(chat_members))),
                turn_id=turn.id,
            )
            for reply in result.get("replies", []):
                body = str(reply.get("reply") or "").strip()
                if reply.get("ok") and body:
                    await _emit(
                        body,
                        display_name=str(reply.get("display_name") or ""),
                        agent_id=str(reply.get("agent_id") or ""),
                    )
                    spoke += 1

        # Each @-mentioned partner with a task runs it in its OWN git worktree
        # (no collision with the live tree) and reports the diff for review.
        for wm in work_members:
            disp = wm["display_name"]
            info = detected[wm["name"]]
            await _emit(
                "收到，正在独立 worktree 里处理这个任务，"
                "完成后把 diff 给你 review（不会自动合并）……",
                display_name=disp,
                agent_id=wm["name"],
            )
            try:
                cli = await asyncio.to_thread(
                    run_cli_team, text, [info], repo_root=os.getcwd(), turn_id=turn.id
                )
                mem = (cli.get("members") or [{}])[0]
                diff = str(mem.get("diff") or "").strip()
                if mem.get("ok") and diff:
                    files = mem.get("files") or []
                    flist = "、".join(files[:8]) + ("…" if len(files) > 8 else "")
                    shown = diff if len(diff) <= 1500 else diff[:1500] + "\n…(diff 截断，完整在 worktree)"
                    await _emit(
                        f"✅ 已在隔离 worktree 完成 · 改动 {len(files)} 个文件"
                        + (f"：{flist}" if files else "")
                        + f"。diff 待 review：\n\n```diff\n{shown}\n```",
                        display_name=disp,
                        agent_id=wm["name"],
                    )
                else:
                    err = str(mem.get("error") or "没有产生改动")
                    await _emit(
                        f"⚠️ 这次没能完成：{err[:400]}",
                        display_name=disp,
                        agent_id=wm["name"],
                    )
                spoke += 1
            except Exception as exc:  # noqa: BLE001 — isolate one partner's failure
                await _emit(
                    f"⚠️ 运行出错：{type(exc).__name__}: {exc}",
                    display_name=disp,
                    agent_id=wm["name"],
                )

        if spoke == 0:
            await _fallback_to_react()
    except Exception as exc:  # noqa: BLE001 — never break the turn on a fan-out fault
        _logger.warning(
            "group fan-out failed (%s: %s) — falling back to react",
            type(exc).__name__,
            exc,
        )
        await _fallback_to_react()

"""Realtime gateway — JSON-RPC 2.0 over WebSocket.

This is the production transport between any client and the runtime.
Replaces the SSE+POST pattern. The gateway owns:

  * One ``RpcConnection`` per WebSocket — bidirectional JSON-RPC.
  * Per-connection ``ApprovalManager`` — server-initiated requests
    (command approval, file approval, user input) are awaited via
    asyncio Futures bound to the connection. No global dict, no
    cross-worker state, no threading.Event.
  * Method dispatch — client Requests are routed to handlers registered
    on the gateway. Notifications from the client are dropped (the
    server side never expects unsolicited fire-and-forget from clients
    today; add notification handlers when that changes).

The gateway is transport-bound. The actual turn loop (planning, LLM
calls, tool dispatch) lives in implementations of ``RealtimeRuntime``.
The gateway only knows about envelopes and items.

This module is intentionally split into cohesive submodules
(``_realtime_gateway_*``) to keep it under the line budget; the public
surface (``RealtimeGateway``, ``RpcConnection``, ``ApprovalManager``,
protocols, exceptions) is re-exported here so ``from
runtime.sensing.gateway.realtime_gateway import X`` keeps working.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from typing import Any

try:  # Optional-dep guard: mirror sibling gateways (openai_gateway etc.)
    from fastapi import APIRouter, WebSocket, WebSocketDisconnect

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment,misc]
    WebSocket = None  # type: ignore[assignment,misc]

    class WebSocketDisconnect(Exception):  # type: ignore[no-redef]
        """Fallback shim so type references resolve when fastapi is absent."""

        pass


from runtime.platform.models.primitives import now_utc
from runtime.platform.process.keyed_lock import KeyedLock
from runtime.platform.process.sliding_window_limiter import SlidingWindowLimiter
from runtime.protocol import (
    ClientMethod,
    Item,
    JsonRpcError,
    JsonRpcErrorCode,
    JsonRpcRequest,
    JsonRpcResponse,
    Notification,
    ServerMethod,
    Turn,
    TurnStatus,
    decode_message,
)
from runtime.sensing.gateway._realtime_detached_turn import _DetachedTurnEmitter
from runtime.sensing.gateway._realtime_gateway_approval import ApprovalManager, SharedTurnInterrupts
from runtime.sensing.gateway._realtime_gateway_connection import RpcConnection
from runtime.sensing.gateway._realtime_gateway_frame import (
    _FRAME_BYTE_LIMIT,
    _FRAME_TRUNC_MARK,
    _INBOUND_FRAME_BYTE_LIMIT,
    _INBOUND_MSG_PER_SEC,
    _bound_oversized_frame,
)
from runtime.sensing.gateway._realtime_gateway_types import (
    _APPROVAL_TIMEOUT_DEFAULT,
    EventEmitter,
    RealtimeRuntime,
    _ApprovalError,
    _RpcError,
)

_logger = logging.getLogger(__name__)


# ── Gateway — FastAPI wiring + dispatch loop ─────────────────


class RealtimeGateway:
    """Mountable FastAPI router exposing a single WebSocket endpoint.

    Usage::

        gateway = RealtimeGateway(runtime=my_runtime)
        app.include_router(gateway.router)

    Clients connect to ``GET /api/realtime`` (upgraded to WebSocket) and
    speak JSON-RPC 2.0 envelopes both directions.
    """

    def __init__(
        self,
        *,
        runtime: RealtimeRuntime,
        path: str = "/api/realtime",
        approval_timeout: float = _APPROVAL_TIMEOUT_DEFAULT,
        identity_store: Any = None,
        require_auth: bool = False,
        jwt_secret: str | None = None,
        jwt_issuer: str | None = None,
        jwt_audience: str | None = None,
        jwt_leeway_seconds: int = 0,
        # Claims never synthesize an identity; the subject must be registered
        # in the configured IdentityStore before a WebSocket is accepted.
        trust_jwt_sub: bool = False,
        allow_client_approval_bypass: bool = False,
        max_in_flight_requests_per_connection: int = 32,
        max_connections_per_actor: int = 64,
        max_turns_per_minute_per_actor: int = 120,
        # Per-connection inbound anti-abuse ceilings (mirror team_rooms_ws):
        # a single frame over ``max_inbound_msg_bytes`` is dropped before
        # parsing, and a sustained flood over ``max_inbound_msgs_per_sec``
        # is shed. Set either to 0 to disable. Lenient defaults — a legit
        # JSON-RPC frame is a few KB and clients send a few frames/sec.
        max_inbound_msg_bytes: int = _INBOUND_FRAME_BYTE_LIMIT,
        max_inbound_msgs_per_sec: int = _INBOUND_MSG_PER_SEC,
    ) -> None:
        self._runtime = runtime
        self._approval_timeout = approval_timeout
        self._identity_store = identity_store
        self._require_auth = require_auth
        self._jwt_secret = jwt_secret
        self._jwt_issuer = jwt_issuer
        self._jwt_audience = jwt_audience
        self._jwt_leeway_seconds = jwt_leeway_seconds
        self._trust_jwt_sub = trust_jwt_sub
        self._allow_client_approval_bypass = allow_client_approval_bypass
        self._max_in_flight_requests_per_connection = max(
            1,
            max_in_flight_requests_per_connection,
        )
        self._max_inbound_msg_bytes = max(0, int(max_inbound_msg_bytes))
        self._max_inbound_msgs_per_sec = max(0, int(max_inbound_msgs_per_sec))
        # Lenient per-actor anti-abuse ceilings (auth-on only — a local
        # single-user server with actor_id None is never limited). Sized
        # so many tabs/devices and bursty use pass freely; only a runaway
        # or hostile client trips them. Set to 0 to disable either.
        self._max_connections_per_actor = max(0, int(max_connections_per_actor))
        self._conn_counts: dict[str, int] = {}
        self._turn_rate_limiter = (
            SlidingWindowLimiter(int(max_turns_per_minute_per_actor), window_s=60.0)
            if int(max_turns_per_minute_per_actor) > 0
            else None
        )
        # Per-thread turn serialization. Reference-counted so the map is
        # reclaimed when a thread goes idle instead of leaking one lock
        # per thread_id for the process lifetime.
        self._turn_locks = KeyedLock()
        # Subagent wakeup auto-turn (dsh report lane): a ``wakeup`` report
        # arriving while the owning thread is idle and watched by a live
        # connection schedules a NEW parent turn that claims the parked
        # reports. Refcounts keep the store handler registered exactly as
        # long as at least one connection watches the thread.
        self._wake_watch_refs: dict[str, int] = {}
        self._active_turn_threads: set[str] = set()
        self._auto_turn_tasks: dict[str, asyncio.Task[None]] = {}
        # Audit T-01: turns run as server-resident tasks, decoupled from
        # the originating WS request task. The event loop only keeps WEAK
        # references to tasks, so a strong set is required to keep a
        # detached turn alive after its requester disconnects.
        self._resident_turn_tasks: set[asyncio.Task[Turn]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        # Cross-connection state: the shared interrupt registry (see
        # SharedTurnInterrupts) plus the live-connection set used to
        # fan terminal turn events out to same-thread watchers.
        self._shared_interrupts = SharedTurnInterrupts()
        self._connections: set[RpcConnection] = set()
        self._router = APIRouter()

        @self._router.websocket(path)
        async def _ws(ws: WebSocket) -> None:  # noqa: ANN202
            await self._serve(ws)

    @property
    def router(self) -> APIRouter:
        return self._router

    def _resolve_ws_actor(self, ws: WebSocket) -> str | None:
        """Authenticate a WebSocket handshake before ``accept()``.

        Mirrors ``_resolve_actor`` (openai_gateway) but for WS.
        Token sources, in order of preference:
          1. ``Authorization: Bearer <token>`` header (some proxies pass it)
          2. ``Sec-WebSocket-Protocol`` subprotocol value (browser-safe)
          3. ``?token=...`` query parameter

        Returns ``actor_id`` on success, ``None`` when ``require_auth`` is
        false and no credentials were presented. Raises ``_RpcError`` on
        explicit auth failure so the caller can close with 4401.
        """
        if self._identity_store is None:
            if self._require_auth:
                raise _RpcError(
                    JsonRpcErrorCode.UNAUTHORIZED,
                    "identity store required for realtime auth",
                )
            return None

        token: str | None = None
        try:
            auth_header = ws.headers.get("authorization") or ""
        except Exception:  # noqa: BLE001
            auth_header = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

        if token is None:
            try:
                subproto = ws.headers.get("sec-websocket-protocol") or ""
            except Exception:  # noqa: BLE001
                subproto = ""
            if subproto:
                # Browsers can't set Authorization on WS; convention is to
                # pass ``bearer, <token>`` (two protocol values, comma-sep).
                parts = [p.strip() for p in subproto.split(",") if p.strip()]
                if len(parts) >= 2 and parts[0].lower() == "bearer":
                    token = parts[1]

        if token is None:
            try:
                token = ws.query_params.get("token")  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                token = None

        if not token:
            if self._require_auth:
                raise _RpcError(
                    JsonRpcErrorCode.UNAUTHORIZED,
                    "missing realtime auth token",
                )
            return None

        if self._jwt_secret and token.count(".") == 2:
            identity = self._identity_store.verify_jwt(
                token,
                secret=self._jwt_secret,
                leeway_seconds=self._jwt_leeway_seconds,
                required_issuer=self._jwt_issuer,
                required_audience=self._jwt_audience,
                trust_jwt_sub=self._trust_jwt_sub,
            )
            if identity is not None:
                return identity.actor_id
            if self._require_auth:
                raise _RpcError(JsonRpcErrorCode.UNAUTHORIZED, "invalid jwt")

        identity = self._identity_store.verify_api_key(token)
        if identity is not None:
            return identity.actor_id
        if self._require_auth:
            raise _RpcError(JsonRpcErrorCode.UNAUTHORIZED, "invalid token")
        return None

    @staticmethod
    def _accept_subprotocol(ws: WebSocket) -> str | None:
        """Pick the subprotocol to acknowledge in ``accept()``.

        Browser clients that authenticate via ``Sec-WebSocket-Protocol``
        offer ``bearer, <token>`` (parsed by ``_resolve_ws_actor``). RFC
        6455 requires the server to select one of the offered protocols
        when the client's handshake listed any — answering without a
        ``Sec-WebSocket-Protocol`` header makes the browser fail the
        connection outright. Only the ``bearer`` marker is echoed; the
        token value itself is never a valid selection. Clients that
        offer nothing (legacy ``?token=`` or header auth) get the old
        behavior: no subprotocol.
        """
        try:
            offered = ws.headers.get("sec-websocket-protocol") or ""
        except Exception:  # noqa: BLE001
            return None
        parts = [p.strip().lower() for p in offered.split(",") if p.strip()]
        return "bearer" if "bearer" in parts else None

    def _admit_connection(self, actor_id: str | None) -> bool:
        """Reserve a connection slot for ``actor_id`` under the per-actor
        cap. Returns False when the actor is already at the cap. A no-op
        (always True) when auth is off (actor_id None) or the cap is 0."""
        if actor_id is None or self._max_connections_per_actor <= 0:
            return True
        count = self._conn_counts.get(actor_id, 0)
        if count >= self._max_connections_per_actor:
            return False
        self._conn_counts[actor_id] = count + 1
        return True

    def _release_connection(self, actor_id: str | None) -> None:
        """Return a slot reserved by _admit_connection; drop the key at 0
        so the counter map stays O(actors with a live connection)."""
        if actor_id is None or self._max_connections_per_actor <= 0:
            return
        count = self._conn_counts.get(actor_id, 0) - 1
        if count <= 0:
            self._conn_counts.pop(actor_id, None)
        else:
            self._conn_counts[actor_id] = count

    async def _serve(self, ws: WebSocket) -> None:
        try:
            actor_id = self._resolve_ws_actor(ws)
        except _RpcError as exc:
            # Refuse the handshake. 4401 mirrors the HTTP 401 semantic
            # in WS close-code space (the 4000–4999 range is for app use).
            with suppress(Exception):
                await ws.close(code=4401, reason=exc.message)
            return
        # Per-actor connection cap (4429 ≈ HTTP 429). Checked before
        # accept so an over-limit actor never spawns connection state.
        if not self._admit_connection(actor_id):
            with suppress(Exception):
                await ws.close(code=4429, reason="too many connections for this actor")
            return
        await ws.accept(subprotocol=self._accept_subprotocol(ws))
        conn = RpcConnection(
            ws,
            approval_timeout=self._approval_timeout,
            max_in_flight_requests=self._max_in_flight_requests_per_connection,
            shared_interrupts=self._shared_interrupts,
        )
        conn.actor_id = actor_id
        if actor_id is not None and self._identity_store is not None:
            identity = self._identity_store.get(actor_id)
            metadata = getattr(identity, "metadata", None) or {}
            conn.tenant_id = str(metadata.get("tenant_id") or f"legacy:{actor_id}")
        self._connections.add(conn)
        # Each inbound client Request becomes a background task so the
        # receive loop stays free to deliver the corresponding Responses
        # for any server-initiated approval requests the handler may
        # await. Without this, awaiting an approval future from inside
        # ``_handle_payload`` blocks the only coroutine that could
        # ever resolve it — classic deadlock.
        in_flight: set[asyncio.Task[None]] = set()
        # Per-connection inbound guard, local to this handler so it's freed
        # when the connection closes — no shared map to leak. Over-sized
        # frames are dropped before decode; a runaway client's sustained
        # flood is shed without parsing. Mirrors ``team_rooms_ws``.
        _inbound_limiter = (
            SlidingWindowLimiter(limit=self._max_inbound_msgs_per_sec, window_s=1.0)
            if self._max_inbound_msgs_per_sec > 0
            else None
        )
        try:
            while True:
                try:
                    payload = await ws.receive_text()
                except WebSocketDisconnect:
                    break
                if self._max_inbound_msg_bytes > 0 and len(payload) > self._max_inbound_msg_bytes:
                    _logger.warning(
                        "realtime: dropping %d-byte inbound frame (limit %d)",
                        len(payload),
                        self._max_inbound_msg_bytes,
                    )
                    continue
                if _inbound_limiter is not None and not _inbound_limiter.allow(
                    actor_id or "<anon>"
                ):
                    _logger.debug("realtime: shedding over-rate inbound frame")
                    continue
                task = asyncio.create_task(self._handle_payload(conn, payload))
                in_flight.add(task)
                task.add_done_callback(in_flight.discard)
        finally:
            self._connections.discard(conn)
            for watched in list(getattr(conn, "watched_threads", ())):
                self._unwatch_thread(watched)
            self._release_connection(actor_id)
            for task in list(in_flight):
                task.cancel()
            await conn.close()

    async def _handle_payload(self, conn: RpcConnection, payload: str) -> None:
        try:
            message = decode_message(payload)
        except ValueError as exc:
            _logger.warning("realtime: malformed envelope: %s", exc)
            return  # Notification-style malformed input: drop. Per JSON-RPC
            # we *should* reply with PARSE_ERROR for ambiguous cases, but
            # without a recoverable id, the spec-compliant id is null and
            # most clients ignore it anyway. Logging is enough.

        if isinstance(message, JsonRpcResponse):
            await conn.approval.resolve(message.id, message)
            return

        if isinstance(message, Notification):
            # ``ping`` is a client-side keepalive — reply with ``pong``
            # so the client can detect a wedged or black-holed server
            # connection (silent TCP half-open, proxy timeout, etc).
            if message.method == "ping":
                with suppress(Exception):
                    await conn.notify("pong", {})
                return
            _logger.debug("realtime: dropping client notification %s", message.method)
            return

        # JsonRpcRequest — dispatch and reply.
        if conn.requests_saturated():
            await conn.send(
                JsonRpcResponse(
                    id=message.id,
                    error=JsonRpcError(
                        code=JsonRpcErrorCode.SERVER_BUSY,
                        message="too many in-flight realtime requests",
                    ),
                ),
            )
            return
        slot = await conn.acquire_request_slot()
        try:
            await self._dispatch_request(conn, message)
        finally:
            slot.release()

    async def _dispatch_request(self, conn: RpcConnection, request: JsonRpcRequest) -> None:
        try:
            result = await self._invoke(request.method, request.params, conn)
        except _ApprovalError as exc:
            await conn.send(JsonRpcResponse(id=request.id, error=exc.error))
            return
        except _RpcError as exc:
            await conn.send(
                JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=exc.code, message=exc.message, data=exc.data),
                )
            )
            return
        except Exception as exc:  # noqa: BLE001
            _logger.exception("realtime: handler raised for %s", request.method)
            await conn.send(
                JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(
                        code=JsonRpcErrorCode.INTERNAL_ERROR,
                        message=str(exc) or exc.__class__.__name__,
                    ),
                )
            )
            return
        await conn.send(JsonRpcResponse(id=request.id, result=result))

    async def _invoke(
        self,
        method: str,
        params: dict[str, Any],
        conn: RpcConnection,
    ) -> Any:
        if method == ClientMethod.TURN_START.value:
            return await self._invoke_turn_start(params, conn)

        if method == ClientMethod.TURN_INTERRUPT.value:
            turn_id = params.get("turnId")
            if not isinstance(turn_id, str) or not turn_id:
                raise _RpcError(
                    JsonRpcErrorCode.INVALID_PARAMS,
                    "turn/interrupt requires turnId",
                )
            conn.request_interrupt(turn_id)
            # The turn may be running on a *different* connection
            # (second tab on the same thread, post-reconnect socket),
            # so flag the gateway-wide registry too. The response is
            # honest: ``interrupted`` is True only when a currently
            # running turn was actually flagged — a stale or unknown
            # id is acknowledged but marks nothing, and the client
            # must not render it as "stopped".
            interrupted = self._shared_interrupts.request_interrupt(turn_id)
            # Approval waits are part of the turn, not independent dialogs.
            # Flag interruption before cancelling them: a racing approval
            # request then either sees the flag and declines immediately, or
            # registers early enough for cancel_turn to settle it.
            await asyncio.gather(
                *(connection.approval.cancel_turn(turn_id) for connection in self._connections)
            )
            return {"turnId": turn_id, "interrupted": interrupted}

        # Anything else: defer to the runtime. Implementations that
        # don't override get a method-not-found.
        handler = getattr(self._runtime, "handle_request", None)
        if handler is None:
            raise _RpcError(JsonRpcErrorCode.METHOD_NOT_FOUND, f"no handler for {method}")
        try:
            result = await handler(method, params, conn)
        except NotImplementedError as exc:
            raise _RpcError(JsonRpcErrorCode.METHOD_NOT_FOUND, str(exc) or method) from exc
        if method == ClientMethod.THREAD_RESUME.value:
            # Remember which thread this connection watches so turn
            # terminals reached on sibling connections can be fanned
            # out (see _invoke_turn_start). Recorded only after the
            # handler succeeded — a rejected resume (unknown thread,
            # foreign actor) must not subscribe the connection.
            resumed_thread = params.get("threadId")
            if isinstance(resumed_thread, str) and resumed_thread:
                conn.last_resumed_thread_id = resumed_thread
                self._watch_thread(resumed_thread, conn)
        return result

    # ── Subagent wakeup auto-turn (dsh report lane) ─────────────────

    def _capture_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        return self._loop

    def _watch_thread(self, thread_id: str, conn: RpcConnection) -> None:
        """Register the auto-wake watcher for a thread this connection watches.

        Idempotent per connection; refcounted across connections so the
        store handler lives exactly as long as a live watcher exists.
        Best-effort: a missing subagent store never raises.
        """
        if not thread_id:
            return
        conn.watched_threads.add(thread_id)
        refs = self._wake_watch_refs.get(thread_id, 0)
        if refs == 0:
            try:
                from runtime.execution.subagents.sessions import (
                    get_subagent_session_store,
                )

                store = get_subagent_session_store()
                if store is not None:
                    store.register_thread_wake_handler(
                        thread_id,
                        self._make_wake_handler(thread_id),
                    )
            except Exception:  # noqa: BLE001 — watcher registration is best-effort
                _logger.debug("subagent wake watcher register failed", exc_info=True)
        self._wake_watch_refs[thread_id] = refs + 1

    def _unwatch_thread(self, thread_id: str) -> None:
        """Drop one connection's watch; unregister the store handler at zero."""
        if not thread_id:
            return
        refs = self._wake_watch_refs.get(thread_id, 0)
        if refs <= 1:
            self._wake_watch_refs.pop(thread_id, None)
            try:
                from runtime.execution.subagents.sessions import (
                    get_subagent_session_store,
                )

                store = get_subagent_session_store()
                if store is not None:
                    store.unregister_thread_wake_handler(thread_id)
            except Exception:  # noqa: BLE001 — best-effort
                _logger.debug("subagent wake watcher unregister failed", exc_info=True)
        else:
            self._wake_watch_refs[thread_id] = refs - 1

    def _make_wake_handler(self, thread_id: str) -> Callable[[str, Any], None]:
        """Build the store wake handler hopping onto this gateway's loop.

        ``append_report`` invokes the handler synchronously on the
        reporting (worker) thread; the handler only schedules the
        auto-turn coroutine on the event loop and returns immediately.
        """
        loop = self._capture_loop()

        def _wake(session_id: str, report: Any) -> None:
            try:
                loop.call_soon_threadsafe(self._schedule_auto_turn, thread_id)
            except RuntimeError:
                _logger.debug(
                    "subagent wake scheduling skipped (event loop closed)",
                    exc_info=True,
                )

        return _wake

    def _schedule_auto_turn(self, thread_id: str) -> None:
        """Dedupe rapid wakeups: one pending task claims every parked report."""
        if thread_id in self._auto_turn_tasks:
            return
        task = asyncio.create_task(self._maybe_auto_turn(thread_id))
        self._auto_turn_tasks[thread_id] = task
        task.add_done_callback(lambda _t: self._auto_turn_tasks.pop(thread_id, None))

    def _watching_connection(self, thread_id: str) -> RpcConnection | None:
        for conn in list(self._connections):
            if (
                thread_id in conn.watched_threads
                and not getattr(conn, "_closed", False)
            ):
                return conn
        return None

    async def _maybe_auto_turn(self, thread_id: str) -> None:
        """Open a new parent turn when a wakeup report finds the thread idle.

        dsh report lane: a ``wakeup`` report spends wake budget at the
        store (``maxConsecutiveWakes``); the gateway half is turning that
        wake into an actual parent turn. Guards, in order:

        * an active turn on the thread → the report is already queued
          (busy-owner ``inject``) and this is a no-op;
        * no live connection watching the thread → the report stays
          parked until the next resume surfaces it;
        * no undelivered reports left by the time the per-thread turn
          lock is held → a racing user turn already claimed them.

        The auto-turn input is a neutral stub; ``_start_turn`` surfaces
        every parked report via the steering lane (``[子代理报告] …``) and
        acks it, and the ``auto_wake`` metadata marker keeps this turn
        from refilling the consecutive-wake budget (only human input
        resets dsh ``spentWakes``).
        """
        if thread_id in self._active_turn_threads:
            return
        conn = self._watching_connection(thread_id)
        if conn is None:
            return
        try:
            from runtime.execution.subagents.sessions import (
                get_subagent_session_store,
            )

            store = get_subagent_session_store()
        except Exception:  # noqa: BLE001 — store is optional
            store = None
        if store is None or not store.pending_thread_reports(thread_id):
            return
        async with self._turn_locks.hold(thread_id):
            if thread_id in self._active_turn_threads:
                return
            if not store.pending_thread_reports(thread_id):
                return
            params = {
                "threadId": thread_id,
                "input": [
                    {
                        "type": "text",
                        "text": "[子代理报告]",
                        "metadata": {"context": {"auto_wake": True}},
                    }
                ],
            }
            self._active_turn_threads.add(thread_id)
            try:
                turn = await self._runtime.start_turn(params, conn)
            except Exception as exc:  # noqa: BLE001 — surface, never crash the loop
                _logger.warning(
                    "subagent auto-wake turn failed for thread %s: %s",
                    thread_id,
                    exc,
                )
                with suppress(Exception):
                    await conn.notify(
                        ServerMethod.ERROR,
                        {
                            "threadId": thread_id,
                            "error": {
                                "message": str(exc) or exc.__class__.__name__,
                            },
                            "willRetry": False,
                        },
                    )
                return
            finally:
                self._active_turn_threads.discard(thread_id)
        await self._emit_turn_completed(conn, thread_id, turn)

    async def _emit_turn_completed(
        self,
        conn: RpcConnection,
        thread_id: str,
        turn: Turn,
    ) -> None:
        """Emit the terminal TURN_COMPLETED snapshot plus sibling fan-out.

        Shared by RPC-initiated and auto-woken turns so both paths keep
        the same fail-closed invariants (terminal status, completedAt,
        same-thread watcher fan-out).
        """
        # A runtime return without a terminal outcome is a lifecycle protocol
        # violation, never evidence of success.  Fail closed so the client can
        # offer a truthful retry instead of persisting a fabricated completion.
        with suppress(Exception):
            if turn.status == TurnStatus.IN_PROGRESS:
                turn.status = TurnStatus.FAILED
                turn.error = {
                    "message": "runtime returned without a terminal task outcome",
                    "code": "missing_terminal_state",
                }
                turn.outcome_reason = "missing_terminal_state"
                log_for = getattr(self._runtime, "_log_for", None)
                if callable(log_for):
                    log_for(thread_id).turn_completed(
                        thread_id,
                        turn.id,
                        turn.status,
                        error=turn.error,
                    )
            # Terminal snapshots must carry completedAt: journal replay
            # stamps it from the turn_completed event ts, so a null here
            # makes the live view disagree with the post-refresh view
            # (client duration math falls back to startedAt → 0ms).
            if turn.completed_at is None:
                turn.completed_at = now_utc()
            completed_params = {
                "threadId": thread_id,
                "turn": turn.model_dump(by_alias=True, mode="json"),
            }
            await conn.notify(ServerMethod.TURN_COMPLETED, completed_params)
            # Fan the terminal snapshot out to sibling connections that
            # resumed this thread (second tab, reconnected socket).
            # Without this they only learn the turn ended on their next
            # thread/resume and keep spinning. Best-effort: one dead
            # watcher must not starve the others or fail the caller.
            for watcher in list(self._connections):
                if watcher is conn or watcher.last_resumed_thread_id != thread_id:
                    continue
                with suppress(Exception):
                    await watcher.notify(ServerMethod.TURN_COMPLETED, completed_params)

    async def _invoke_turn_start(
        self,
        params: dict[str, Any],
        conn: RpcConnection,
    ) -> dict[str, Any]:
        """Run a turn to completion, streaming events on ``conn``.

        Returns the final ``Turn`` snapshot to the caller as the RPC
        result. The same turn lifecycle was already broadcast over
        notifications, so this return value is for callers that prefer
        a synchronous "wait for done" answer over watching the stream.

        Audit T-01: the turn itself runs in a server-resident task; if
        this connection drops mid-turn, the turn CONTINUES server-side
        and this RPC simply stops waiting. A reconnected client catches
        up via ``thread/resume`` (event-log replay) and keeps receiving
        live events as a watcher of the thread.
        """
        # Lenient per-actor turn-rate ceiling (auth-on only). Bursts pass;
        # only a sustained flood trips SERVER_BUSY, which clients treat as
        # "back off and retry". Different threads still run concurrently —
        # this caps how fast one actor may *start* turns, not how many run.
        if (
            self._turn_rate_limiter is not None
            and conn.actor_id is not None
            and not self._turn_rate_limiter.allow(conn.actor_id)
        ):
            raise _RpcError(
                JsonRpcErrorCode.SERVER_BUSY,
                "rate limit: too many turns started; slow down and retry",
            )
        thread_id = params.get("threadId")
        if not isinstance(thread_id, str):
            raise _RpcError(
                JsonRpcErrorCode.INVALID_PARAMS,
                "turn/start requires threadId",
            )
        try:
            from runtime.memory.threads.event_log import validate_thread_id

            thread_id = validate_thread_id(thread_id)
        except ValueError as exc:
            raise _RpcError(JsonRpcErrorCode.INVALID_PARAMS, str(exc)) from exc
        params = self._sanitize_turn_params(params, conn)
        # A turn makes the thread live-watched (wakeup reports may open
        # further parent turns while this connection stays open) and
        # marks it busy for the auto-wake lane.
        self._watch_thread(thread_id, conn)
        self._active_turn_threads.add(thread_id)
        # Audit T-01: the turn runs as a SERVER-RESIDENT task, decoupled
        # from this WS request task. A disconnect cancels only this
        # handler (the shield below re-raises without touching the
        # resident); the turn keeps running, its events re-attach to
        # whoever resumes the thread, and the terminal snapshot still
        # fans out. Per-thread serialization is unchanged: the resident
        # holds the turn lock for the whole run, so a second turn/start
        # for the same thread queues behind it exactly as before.
        resident = asyncio.create_task(
            self._run_resident_turn(thread_id, params, conn),
            name=f"resident-turn:{thread_id}",
        )
        self._resident_turn_tasks.add(resident)
        resident.add_done_callback(self._resident_turn_tasks.discard)
        try:
            turn = await asyncio.shield(resident)
        except asyncio.CancelledError:
            # Requester went away mid-turn: the resident keeps running
            # server-side; a reconnected client catches up via
            # thread/resume replay + watcher fan-out.
            _logger.info(
                "realtime: requester disconnected; turn for thread %s "
                "continues server-side",
                thread_id,
            )
            raise
        except _RpcError:
            raise
        except Exception as exc:  # noqa: BLE001
            # The resident already surfaced ERROR to every live watcher;
            # this caller gets the JSON-RPC error response only.
            raise _RpcError(JsonRpcErrorCode.INTERNAL_ERROR, str(exc)) from exc
        return {"turn": turn.model_dump(by_alias=True, mode="json")}

    async def _run_resident_turn(
        self,
        thread_id: str,
        params: dict[str, Any],
        conn: RpcConnection,
    ) -> Turn:
        """Drive one turn to completion, decoupled from ``conn`` (T-01).

        The turn is steered through a ``_DetachedTurnEmitter`` so a
        dropped WebSocket no longer interrupts it: events flow to the
        owner while it is alive, then to connections that resumed the
        thread; only an explicit ``turn/interrupt`` stops the run.
        Terminal fan-out reuses ``_emit_turn_completed`` — ``send`` on a
        dead connection is a no-op, so the owner leg is safe either way.
        """
        emitter = _DetachedTurnEmitter(self, thread_id, conn)
        try:
            try:
                async with self._turn_locks.hold(thread_id):
                    turn = await self._runtime.start_turn(params, emitter)
            except _RpcError:
                # Validation-style failures answer ONLY the RPC caller
                # (the handler converts this into the JSON-RPC error
                # response); no stream notification, matching the
                # pre-detachment behaviour.
                raise
            except Exception as exc:  # noqa: BLE001
                _logger.exception("realtime: turn/start crashed")
                await emitter.notify(
                    ServerMethod.ERROR,
                    {
                        "threadId": thread_id,
                        "error": {"message": str(exc) or exc.__class__.__name__},
                        "willRetry": False,
                    },
                )
                raise
        finally:
            self._active_turn_threads.discard(thread_id)
        await self._emit_turn_completed(conn, thread_id, turn)
        return turn

    def _sanitize_turn_params(
        self,
        params: dict[str, Any],
        conn: RpcConnection,
    ) -> dict[str, Any]:
        cleaned = dict(params)
        if cleaned.get("approvalPolicy") == "never" and not self._allow_client_approval_bypass:
            cleaned["approvalPolicy"] = "on-request"
        if conn.actor_id is not None:
            metadata = cleaned.get("metadata")
            metadata_dict = dict(metadata) if isinstance(metadata, dict) else {}
            metadata_dict.setdefault("actor_id", conn.actor_id)
            cleaned["metadata"] = metadata_dict
            blocks = cleaned.get("input")
            input_blocks = list(blocks) if isinstance(blocks, list) else []
            if not input_blocks:
                input_blocks.append({"type": "metadata"})
            first = (
                dict(input_blocks[0]) if isinstance(input_blocks[0], dict) else {"type": "metadata"}
            )
            block_metadata = first.get("metadata")
            block_metadata_dict = dict(block_metadata) if isinstance(block_metadata, dict) else {}
            block_metadata_dict.setdefault("actor_id", conn.actor_id)
            first["metadata"] = block_metadata_dict
            input_blocks[0] = first
            cleaned["input"] = input_blocks
            # Server-injected ownership context. The client never chooses
            # these values; the gateway overwrites them after authentication.
            cleaned["tenant_id"] = conn.tenant_id or f"legacy:{conn.actor_id}"
            cleaned["owner_actor_id"] = conn.actor_id
        return cleaned


# Type re-exports for runtime authors.
__all__ = [
    "_FRAME_BYTE_LIMIT",
    "_FRAME_TRUNC_MARK",
    "_bound_oversized_frame",
    "ApprovalManager",
    "EventEmitter",
    "Item",
    "RealtimeGateway",
    "RealtimeRuntime",
    "RpcConnection",
    "Turn",
]

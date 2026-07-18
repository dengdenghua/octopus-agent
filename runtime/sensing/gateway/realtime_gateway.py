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
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, Protocol

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
    encode_message,
)

_logger = logging.getLogger(__name__)

# Default approval wait. 10 minutes is enough for the operator to
# notice and respond; tune via the RealtimeGateway constructor for
# environments with stricter SLAs.
_APPROVAL_TIMEOUT_DEFAULT = 600.0


# ── Public types ──────────────────────────────────────────────


class EventEmitter(Protocol):
    """Sink the runtime uses to push events out to a client.

    A ``RpcConnection`` implements this. Implementations must be
    coroutine-safe — one turn loop may interleave deltas from multiple
    items, and asyncio task scheduling can reorder otherwise atomic
    sequences.
    """

    async def notify(self, method: ServerMethod | str, params: dict[str, Any]) -> None: ...

    async def request_approval(
        self,
        method: ServerMethod | str,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any: ...

    def is_turn_interrupted(self, turn_id: str) -> bool:
        """Cooperative cancel signal.

        Runtime authors poll this between long-running steps. Returns
        ``True`` once the client has issued ``turn/interrupt`` for the
        given ``turn_id`` (or once the connection is closing).
        """
        ...

    def register_turn(self, turn_id: str) -> None:
        """Tell the connection a new turn has begun.

        The gateway routes any ``turn/interrupt`` RPC for this turn id
        to this connection's interrupt registry. Runtime authors call
        this immediately after constructing the Turn but before the
        first await that could be interrupted.
        """
        ...

    def unregister_turn(self, turn_id: str) -> None: ...


class RealtimeRuntime(Protocol):
    """The contract turn loops implement to plug into the gateway.

    Implementations supply the actual agent logic. The gateway only
    invokes ``start_turn``; everything else (interruption, steering,
    listing) is dispatched by ``handle_request`` if implemented.
    """

    async def start_turn(self, params: dict[str, Any], emitter: EventEmitter) -> Turn: ...

    async def handle_request(
        self,
        method: str,
        params: dict[str, Any],
        emitter: EventEmitter,
    ) -> Any:
        """Dispatch any non-``turn/start`` client method.

        Defaults to method-not-found. Override to add ``thread/list``,
        ``turn/interrupt``, etc.
        """
        ...


# ── ApprovalManager — per-connection ──────────────────────────


class ApprovalManager:
    """Tracks server→client requests awaiting a client response.

    Bound to a single ``RpcConnection``: when the WS closes, all
    outstanding futures are cancelled. There is no shared state across
    connections, so multi-worker deployments don't deadlock.
    """

    def __init__(self) -> None:
        self._pending: dict[int | str, asyncio.Future[Any]] = {}
        self._pending_turn_ids: dict[int | str, str] = {}
        self._lock = asyncio.Lock()
        self._next_id = 1

    async def open(self, *, turn_id: str | None = None) -> tuple[int, asyncio.Future[Any]]:
        """Reserve a request id and return its pending future."""
        async with self._lock:
            req_id = self._next_id
            self._next_id += 1
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[Any] = loop.create_future()
            self._pending[req_id] = fut
            if turn_id:
                self._pending_turn_ids[req_id] = turn_id
            return req_id, fut

    async def resolve(self, req_id: int | str, response: JsonRpcResponse) -> None:
        async with self._lock:
            fut = self._pending.pop(req_id, None)
            self._pending_turn_ids.pop(req_id, None)
        if fut is None or fut.done():
            return
        if response.error is not None:
            fut.set_exception(_ApprovalError(response.error))
            return
        fut.set_result(response.result)

    async def cancel_one(self, req_id: int | str, reason: str = "cancelled") -> None:
        async with self._lock:
            fut = self._pending.pop(req_id, None)
            self._pending_turn_ids.pop(req_id, None)
        if fut is not None and not fut.done():
            fut.cancel()
        _logger.debug("approval cancelled req_id=%s (%s)", req_id, reason)

    async def cancel_turn(self, turn_id: str) -> int:
        """Cancel every approval request owned by one interrupted turn."""
        async with self._lock:
            request_ids = [
                req_id
                for req_id, pending_turn_id in self._pending_turn_ids.items()
                if pending_turn_id == turn_id
            ]
            futures = [self._pending.pop(req_id, None) for req_id in request_ids]
            for req_id in request_ids:
                self._pending_turn_ids.pop(req_id, None)
        cancelled = 0
        for fut in futures:
            if fut is not None and not fut.done():
                # Resolve as an explicit decline instead of cancelling the
                # Future: asyncio.wait_for can translate inner cancellation
                # into a timeout, which incorrectly fails the whole turn.
                fut.set_result({"action": "decline", "reason": "turn interrupted"})
                cancelled += 1
        if cancelled:
            _logger.debug("approval manager cancelled %d for turn %s", cancelled, turn_id)
        return cancelled

    async def cancel_all(self, reason: str = "connection closed") -> None:
        async with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
            self._pending_turn_ids.clear()
        for _, fut in pending:
            if not fut.done():
                fut.cancel()
        if pending:
            _logger.debug("approval manager cancelled %d pending (%s)", len(pending), reason)


class _ApprovalError(Exception):
    def __init__(self, error: JsonRpcError) -> None:
        super().__init__(error.message)
        self.error = error


class SharedTurnInterrupts:
    """Gateway-wide interrupt registry, shared by every connection.

    The per-connection ``_interrupted_turns`` set only works when the
    ``turn/interrupt`` RPC arrives on the same connection that runs
    the turn. A second tab (or a post-reconnect socket) on the same
    thread is a *different* connection, so its interrupt must be
    visible to the emitter the turn was registered on. Runtimes keep
    polling ``emitter.is_turn_interrupted`` — that check consults this
    registry too. Entries are keyed by turn id, flagged only while the
    turn is known to be running, and cleared on unregister (the turn
    lifecycle's ``finally``) so ids never leak.
    """

    def __init__(self) -> None:
        self._active_turn_ids: set[str] = set()
        self._interrupted_turn_ids: set[str] = set()

    def register(self, turn_id: str) -> None:
        self._active_turn_ids.add(turn_id)
        # A stale interrupt that predates this registration must not
        # poison the new turn (mirrors RpcConnection.register_turn).
        self._interrupted_turn_ids.discard(turn_id)

    def unregister(self, turn_id: str) -> None:
        self._active_turn_ids.discard(turn_id)
        self._interrupted_turn_ids.discard(turn_id)

    def request_interrupt(self, turn_id: str) -> bool:
        """Flag ``turn_id``; True only when a running turn was hit."""
        if turn_id not in self._active_turn_ids:
            return False
        self._interrupted_turn_ids.add(turn_id)
        return True

    def is_interrupted(self, turn_id: str) -> bool:
        return turn_id in self._interrupted_turn_ids


# ── RpcConnection — per WebSocket ────────────────────────────


RequestHandler = Callable[[dict[str, Any]], Awaitable[Any]]

# A single WS frame over the client's ~16 MiB message ceiling is dropped
# with code 1009, which kills the whole connection (and has taken backends
# down mid-run). The per-field caps upstream (e.g. command output) are the
# primary defense; this is the last-ditch net for ANY field that grows
# unbounded — a huge diff, a huge snapshot. Bound to 12 MiB, leaving margin
# for protocol overhead. The trigger is an O(1) char-count so normal frames
# pay nothing; only the rare oversized frame does the precise byte work.
_FRAME_BYTE_LIMIT = 12 * 1024 * 1024
# A JSON char is at most 4 UTF-8 bytes, so under this many chars a frame is
# guaranteed under the byte limit and can skip the encode-and-measure path.
_FRAME_CHAR_FASTPASS = _FRAME_BYTE_LIMIT // 4
_FRAME_TRUNC_MARK = "…(字段过大已截断以保住连接)"


def _iter_string_leaves(obj: Any) -> list[tuple[Any, Any, int]]:
    """Every (container, key, length) for string leaves, so the largest can
    be found and shortened in place."""
    out: list[tuple[Any, Any, int]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str):
                    out.append((node, k, len(v)))
                else:
                    walk(v)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                if isinstance(v, str):
                    out.append((node, i, len(v)))
                else:
                    walk(v)

    walk(obj)
    return out


def _bound_oversized_frame(
    message: JsonRpcRequest | JsonRpcResponse | Notification,
) -> JsonRpcRequest | JsonRpcResponse | Notification:
    """Return a copy whose serialized size is under ``_FRAME_BYTE_LIMIT``,
    halving the single longest string leaf until it fits. Structure is
    preserved (only string leaves shrink), so the JSON stays valid."""
    params = getattr(message, "params", None)
    if not isinstance(params, dict):
        return message  # responses/errors carry no bulk field to shrink
    import copy

    params = copy.deepcopy(params)
    for _ in range(80):  # bounded; each pass halves the biggest string
        leaves = _iter_string_leaves(params)
        if not leaves:
            break
        container, key, longest = max(leaves, key=lambda x: x[2])
        if longest <= len(_FRAME_TRUNC_MARK) + 1024:
            break  # nothing left big enough to help
        s = container[key]
        container[key] = s[: max(1024, len(s) // 2)] + _FRAME_TRUNC_MARK
        trimmed = message.model_copy(update={"params": params})
        if len(encode_message(trimmed).encode("utf-8")) <= _FRAME_BYTE_LIMIT:
            _logger.warning(
                "realtime: frame for %s exceeded %d bytes — truncated its "
                "largest field to protect the connection",
                getattr(message, "method", "?"),
                _FRAME_BYTE_LIMIT,
            )
            return trimmed
    return message.model_copy(update={"params": params})


class RpcConnection:
    """One client. Owns the WS, the approval manager, and a write lock.

    The write lock serializes ``websocket.send_text`` calls — Starlette
    raises if two coroutines write concurrently. The class is the only
    place that ever touches the WS object.
    """

    def __init__(
        self,
        ws: WebSocket,
        *,
        approval_timeout: float = _APPROVAL_TIMEOUT_DEFAULT,
        max_in_flight_requests: int = 32,
        shared_interrupts: SharedTurnInterrupts | None = None,
    ) -> None:
        self.ws = ws
        self.approval = ApprovalManager()
        self._approval_timeout = approval_timeout
        self._request_slots = asyncio.Semaphore(max(1, max_in_flight_requests))
        self._write_lock = asyncio.Lock()
        self._closed = False
        # Authenticated actor id (None when auth is not required and no
        # credentials were presented). Set by ``RealtimeGateway._serve``
        # after the handshake gate runs. Runtime handlers consult this
        # for thread-ownership scoping.
        self.actor_id: str | None = None
        # Last thread this connection successfully resumed. The gateway
        # uses it to fan terminal turn events out to sibling
        # connections watching the same thread.
        self.last_resumed_thread_id: str | None = None
        # Per-turn interrupt flags. The runtime registers each turn id
        # before any awaitable that could be cancelled; the dispatcher
        # for ``turn/interrupt`` flips the flag; the runtime polls
        # ``is_turn_interrupted`` between steps. ``shared_interrupts``
        # is the gateway-wide registry so interrupts issued on *other*
        # connections reach turns running on this one.
        self._interrupted_turns: set[str] = set()
        self._shared_interrupts = shared_interrupts

    async def send(self, message: JsonRpcRequest | JsonRpcResponse | Notification) -> None:
        if self._closed:
            return
        async with self._write_lock:
            try:
                text = encode_message(message)
                # O(1) char-count fast-path; only a rare oversized frame
                # pays the precise byte measure + shrink.
                if (
                    len(text) > _FRAME_CHAR_FASTPASS
                    and len(text.encode("utf-8")) > _FRAME_BYTE_LIMIT
                ):
                    text = encode_message(_bound_oversized_frame(message))
                await self.ws.send_text(text)
            except WebSocketDisconnect:
                # Client went away mid-stream. Flip the closed flag so
                # subsequent ``send`` calls fast-path return rather than
                # raising on every queued notify; also signal interrupt
                # for every in-flight turn so the runtime bails out
                # promptly. Swallowing here keeps the runtime's per-
                # event try/except simple — they don't have to know
                # the difference between "a single bad payload" and
                # "the connection died".
                self._closed = True
                self._interrupted_turns.add("*")
            except RuntimeError as exc:
                # Starlette raises RuntimeError when ``send`` is called
                # after the WS lifecycle has progressed past ``connected``
                # (e.g. ``Cannot call "send" once a close message has been
                # sent``). Treat the same as a clean disconnect.
                if "close" in str(exc).lower() or "disconnect" in str(exc).lower():
                    self._closed = True
                    self._interrupted_turns.add("*")
                else:
                    raise

    # EventEmitter
    async def notify(self, method: ServerMethod | str, params: dict[str, Any]) -> None:
        method_str = method.value if isinstance(method, ServerMethod) else method
        await self.send(Notification(method=method_str, params=params))

    # EventEmitter
    async def request_approval(
        self,
        method: ServerMethod | str,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any:
        method_str = method.value if isinstance(method, ServerMethod) else method
        turn_id = params.get("turnId")
        if isinstance(turn_id, str) and self.is_turn_interrupted(turn_id):
            return {"action": "decline", "reason": "turn interrupted"}
        req_id, fut = await self.approval.open(
            turn_id=turn_id if isinstance(turn_id, str) else None,
        )
        await self.send(JsonRpcRequest(id=req_id, method=method_str, params=params))
        try:
            return await asyncio.wait_for(fut, timeout=timeout or self._approval_timeout)
        except TimeoutError as exc:
            await self.approval.cancel_one(req_id, "timeout")
            raise _ApprovalError(
                JsonRpcError(
                    code=JsonRpcErrorCode.APPROVAL_TIMEOUT,
                    message=f"timed out waiting for {method_str}",
                )
            ) from exc

    async def close(self) -> None:
        self._closed = True
        # Treat a closing connection as an interrupt for every
        # in-flight turn. Runtime authors should bail out promptly
        # rather than try to push more state down a dead socket.
        self._interrupted_turns.add("*")
        await self.approval.cancel_all()

    # EventEmitter — interrupt registry
    def register_turn(self, turn_id: str) -> None:
        # Discarding any stale interrupt that arrived before the turn
        # was even known. Out-of-order ``turn/interrupt`` is unusual
        # but possible (client races); treat as a no-op rather than
        # leaving a poisoned flag for the next turn with the same id.
        self._interrupted_turns.discard(turn_id)
        if self._shared_interrupts is not None:
            self._shared_interrupts.register(turn_id)

    def unregister_turn(self, turn_id: str) -> None:
        self._interrupted_turns.discard(turn_id)
        if self._shared_interrupts is not None:
            self._shared_interrupts.unregister(turn_id)

    def is_turn_interrupted(self, turn_id: str) -> bool:
        if "*" in self._interrupted_turns:
            return True
        if turn_id in self._interrupted_turns:
            return True
        return self._shared_interrupts is not None and self._shared_interrupts.is_interrupted(
            turn_id
        )

    def request_interrupt(self, turn_id: str) -> None:
        """Called by the dispatcher when a ``turn/interrupt`` arrives."""
        self._interrupted_turns.add(turn_id)

    def requests_saturated(self) -> bool:
        return self._request_slots.locked()

    async def acquire_request_slot(self) -> asyncio.Semaphore:
        await self._request_slots.acquire()
        return self._request_slots


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
        trust_jwt_sub: bool = True,
        allow_client_approval_bypass: bool = False,
        max_in_flight_requests_per_connection: int = 32,
        max_connections_per_actor: int = 64,
        max_turns_per_minute_per_actor: int = 120,
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
        await ws.accept()
        conn = RpcConnection(
            ws,
            approval_timeout=self._approval_timeout,
            max_in_flight_requests=self._max_in_flight_requests_per_connection,
            shared_interrupts=self._shared_interrupts,
        )
        conn.actor_id = actor_id
        self._connections.add(conn)
        # Each inbound client Request becomes a background task so the
        # receive loop stays free to deliver the corresponding Responses
        # for any server-initiated approval requests the handler may
        # await. Without this, awaiting an approval future from inside
        # ``_handle_payload`` blocks the only coroutine that could
        # ever resolve it — classic deadlock.
        in_flight: set[asyncio.Task[None]] = set()
        try:
            while True:
                try:
                    payload = await ws.receive_text()
                except WebSocketDisconnect:
                    break
                task = asyncio.create_task(self._handle_payload(conn, payload))
                in_flight.add(task)
                task.add_done_callback(in_flight.discard)
        finally:
            self._connections.discard(conn)
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
        return result

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
        try:
            async with self._turn_locks.hold(thread_id):
                turn = await self._runtime.start_turn(params, conn)
        except _RpcError:
            raise
        except Exception as exc:  # noqa: BLE001
            _logger.exception("realtime: turn/start crashed")
            await conn.notify(
                ServerMethod.ERROR,
                {
                    "threadId": thread_id,
                    "error": {"message": str(exc) or exc.__class__.__name__},
                    "willRetry": False,
                },
            )
            raise _RpcError(JsonRpcErrorCode.INTERNAL_ERROR, str(exc)) from exc
        # Best-effort: emit turn/completed if the runtime didn't.
        # The runtime owns the authoritative status — we only flip the
        # in-progress placeholder to completed so clients watching the
        # notification stream see a terminal state. INTERRUPTED /
        # FAILED are preserved as-is.
        with suppress(Exception):
            if turn.status == TurnStatus.IN_PROGRESS:
                turn.status = TurnStatus.COMPLETED
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
        return {"turn": turn.model_dump(by_alias=True, mode="json")}

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
        return cleaned


class _RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


# Type re-exports for runtime authors.
__all__ = [
    "ApprovalManager",
    "EventEmitter",
    "Item",
    "RealtimeGateway",
    "RealtimeRuntime",
    "RpcConnection",
    "Turn",
]

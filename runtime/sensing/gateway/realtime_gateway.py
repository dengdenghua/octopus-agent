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
        self._lock = asyncio.Lock()
        self._next_id = 1

    async def open(self) -> tuple[int, asyncio.Future[Any]]:
        """Reserve a request id and return its pending future."""
        async with self._lock:
            req_id = self._next_id
            self._next_id += 1
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[Any] = loop.create_future()
            self._pending[req_id] = fut
            return req_id, fut

    async def resolve(self, req_id: int | str, response: JsonRpcResponse) -> None:
        async with self._lock:
            fut = self._pending.pop(req_id, None)
        if fut is None or fut.done():
            return
        if response.error is not None:
            fut.set_exception(_ApprovalError(response.error))
            return
        fut.set_result(response.result)

    async def cancel_one(self, req_id: int | str, reason: str = "cancelled") -> None:
        async with self._lock:
            fut = self._pending.pop(req_id, None)
        if fut is not None and not fut.done():
            fut.cancel()
        _logger.debug("approval cancelled req_id=%s (%s)", req_id, reason)

    async def cancel_all(self, reason: str = "connection closed") -> None:
        async with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
        for _, fut in pending:
            if not fut.done():
                fut.cancel()
        if pending:
            _logger.debug("approval manager cancelled %d pending (%s)", len(pending), reason)


class _ApprovalError(Exception):
    def __init__(self, error: JsonRpcError) -> None:
        super().__init__(error.message)
        self.error = error


# ── RpcConnection — per WebSocket ────────────────────────────


RequestHandler = Callable[[dict[str, Any]], Awaitable[Any]]


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
        # Per-turn interrupt flags. The runtime registers each turn id
        # before any awaitable that could be cancelled; the dispatcher
        # for ``turn/interrupt`` flips the flag; the runtime polls
        # ``is_turn_interrupted`` between steps.
        self._interrupted_turns: set[str] = set()

    async def send(self, message: JsonRpcRequest | JsonRpcResponse | Notification) -> None:
        if self._closed:
            return
        async with self._write_lock:
            try:
                await self.ws.send_text(encode_message(message))
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
        req_id, fut = await self.approval.open()
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

    def unregister_turn(self, turn_id: str) -> None:
        self._interrupted_turns.discard(turn_id)

    def is_turn_interrupted(self, turn_id: str) -> bool:
        if "*" in self._interrupted_turns:
            return True
        return turn_id in self._interrupted_turns

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
        self._turn_locks: dict[str, asyncio.Lock] = {}
        self._turn_locks_guard = asyncio.Lock()
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

    async def _serve(self, ws: WebSocket) -> None:
        try:
            actor_id = self._resolve_ws_actor(ws)
        except _RpcError as exc:
            # Refuse the handshake. 4401 mirrors the HTTP 401 semantic
            # in WS close-code space (the 4000–4999 range is for app use).
            with suppress(Exception):
                await ws.close(code=4401, reason=exc.message)
            return
        await ws.accept()
        conn = RpcConnection(
            ws,
            approval_timeout=self._approval_timeout,
            max_in_flight_requests=self._max_in_flight_requests_per_connection,
        )
        conn.actor_id = actor_id
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
            return {"turnId": turn_id, "interrupted": True}

        # Anything else: defer to the runtime. Implementations that
        # don't override get a method-not-found.
        handler = getattr(self._runtime, "handle_request", None)
        if handler is None:
            raise _RpcError(JsonRpcErrorCode.METHOD_NOT_FOUND, f"no handler for {method}")
        try:
            return await handler(method, params, conn)
        except NotImplementedError as exc:
            raise _RpcError(JsonRpcErrorCode.METHOD_NOT_FOUND, str(exc) or method) from exc

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
            lock = await self._lock_for_thread(thread_id)
            async with lock:
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
            await conn.notify(
                ServerMethod.TURN_COMPLETED,
                {
                    "threadId": thread_id,
                    "turn": turn.model_dump(by_alias=True, mode="json"),
                },
            )
        return {"turn": turn.model_dump(by_alias=True, mode="json")}

    async def _lock_for_thread(self, thread_id: str) -> asyncio.Lock:
        async with self._turn_locks_guard:
            lock = self._turn_locks.get(thread_id)
            if lock is None:
                lock = asyncio.Lock()
                self._turn_locks[thread_id] = lock
            return lock

    def _sanitize_turn_params(
        self,
        params: dict[str, Any],
        conn: RpcConnection,
    ) -> dict[str, Any]:
        cleaned = dict(params)
        if (
            cleaned.get("approvalPolicy") == "never"
            and not self._allow_client_approval_bypass
        ):
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
            first = dict(input_blocks[0]) if isinstance(input_blocks[0], dict) else {"type": "metadata"}
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

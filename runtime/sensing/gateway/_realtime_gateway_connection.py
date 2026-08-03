"""Per-WebSocket RPC connection (``RpcConnection``).

Split from ``realtime_gateway.py``. This class owns the WS socket, the
per-connection ``ApprovalManager``, the write lock, and the per-turn
interrupt registry. It is the only place that ever touches the WS object.
"""

from __future__ import annotations

import asyncio
from typing import Any

try:  # Optional-dep guard: mirror sibling gateways (openai_gateway etc.)
    from fastapi import WebSocket, WebSocketDisconnect

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    WebSocket = None  # type: ignore[assignment,misc]

    class WebSocketDisconnect(Exception):  # type: ignore[no-redef]
        """Fallback shim so type references resolve when fastapi is absent."""

        pass


from runtime.protocol import (
    JsonRpcError,
    JsonRpcErrorCode,
    JsonRpcRequest,
    JsonRpcResponse,
    Notification,
    ServerMethod,
    encode_message,
)

from ._realtime_gateway_approval import ApprovalManager, SharedTurnInterrupts
from ._realtime_gateway_frame import (
    _FRAME_BYTE_LIMIT,
    _FRAME_CHAR_FASTPASS,
    _bound_oversized_frame,
)
from ._realtime_gateway_types import _APPROVAL_TIMEOUT_DEFAULT, _ApprovalError


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

    def get_interrupt_reason(self, turn_id: str) -> str | None:
        """Return the human-readable reason this turn was interrupted.

        Distinguishes connection teardown (``"*"`` wildcard) from an
        explicit ``turn/interrupt`` RPC (specific ``turn_id``) so the
        frontend can tell the user what actually happened.
        """
        if "*" in self._interrupted_turns:
            return "连接断开或后端重启"
        if turn_id in self._interrupted_turns:
            return "用户停止了任务"
        if self._shared_interrupts is not None and self._shared_interrupts.is_interrupted(turn_id):
            return "用户停止了任务"
        return None

    def request_interrupt(self, turn_id: str) -> None:
        """Called by the dispatcher when a ``turn/interrupt`` arrives."""
        self._interrupted_turns.add(turn_id)

    def requests_saturated(self) -> bool:
        return self._request_slots.locked()

    async def acquire_request_slot(self) -> asyncio.Semaphore:
        await self._request_slots.acquire()
        return self._request_slots

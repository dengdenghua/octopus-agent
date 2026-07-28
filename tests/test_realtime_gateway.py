"""End-to-end tests for the JSON-RPC realtime gateway.

Covers:
  * Envelope codec — roundtrip + malformed rejection
  * Turn lifecycle — turn/start emits started, items, completed
  * Approval loop — server request → client response → turn proceeds
  * Approval denial — turn still completes but command item is DECLINED
  * Resume — replay from disk reconstructs the same turn
  * Multiple concurrent connections don't cross-pollinate pending approvals

The tests mount a minimal FastAPI app with the gateway + EchoRuntime and
drive it via Starlette's WebSocket test client. No network, no real LLM.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore[assignment]
    TestClient = None  # type: ignore[assignment]
    WebSocketDisconnect = None  # type: ignore[assignment]

from runtime.protocol import (
    JsonRpcRequest,
    JsonRpcResponse,
    Notification,
    decode_message,
    encode_message,
)
from runtime.protocol.envelope import JsonRpcError, JsonRpcErrorCode

pytestmark = pytest.mark.skipif(
    FastAPI is None,
    reason="fastapi extras required for realtime gateway tests",
)


# ── Envelope tests ────────────────────────────────────────────


def test_envelope_request_roundtrip() -> None:
    original = JsonRpcRequest(id=7, method="turn/start", params={"threadId": "abc"})
    decoded = decode_message(encode_message(original))
    assert isinstance(decoded, JsonRpcRequest)
    assert decoded.id == 7
    assert decoded.method == "turn/start"
    assert decoded.params == {"threadId": "abc"}


def test_envelope_notification_roundtrip() -> None:
    original = Notification(method="turn/started", params={"turnId": "t1"})
    decoded = decode_message(encode_message(original))
    assert isinstance(decoded, Notification)
    assert decoded.method == "turn/started"


def test_envelope_response_requires_exactly_one_outcome() -> None:
    with pytest.raises(ValidationError):
        JsonRpcResponse(id=1)  # neither result nor error
    with pytest.raises(ValidationError):
        JsonRpcResponse(
            id=1,
            result={"ok": True},
            error=JsonRpcError(code=JsonRpcErrorCode.INTERNAL_ERROR, message="x"),
        )


def test_envelope_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        decode_message("not json")
    with pytest.raises(ValueError):
        decode_message("[1, 2, 3]")  # array, not an object
    with pytest.raises(ValueError):
        decode_message(json.dumps({"no": "id", "and": "no method"}))


# ── Gateway tests ─────────────────────────────────────────────


@pytest.fixture()
def gateway_client(tmp_path: Path) -> Any:
    """Mount a fresh gateway + EchoRuntime per-test with a temp log dir."""
    from runtime.sensing.gateway.realtime_echo import EchoRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    runtime = EchoRuntime(logs_root=tmp_path / "threads")
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)
    with TestClient(app) as client:
        yield client, tmp_path / "threads"


@pytest.fixture()
def authenticated_gateway_client(tmp_path: Path) -> Any:
    """Gateway with auth required, backed by a real IdentityStore."""
    from runtime.safety.auth import Identity, IdentityStore
    from runtime.sensing.gateway.realtime_echo import EchoRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    runtime = EchoRuntime(logs_root=tmp_path / "threads")
    gateway = RealtimeGateway(
        runtime=runtime,
        approval_timeout=5.0,
        identity_store=store,
        require_auth=True,
    )
    app = FastAPI()
    app.include_router(gateway.router)
    with TestClient(app) as client:
        yield client, tmp_path / "threads"


@pytest.fixture()
def two_actor_gateway_client(tmp_path: Path) -> Any:
    from runtime.safety.auth import Identity, IdentityStore
    from runtime.sensing.gateway.realtime_echo import EchoRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    store.add(Identity(actor_id="bob"), api_key_plaintext="sk-bob")
    runtime = EchoRuntime(logs_root=tmp_path / "threads")
    gateway = RealtimeGateway(
        runtime=runtime,
        approval_timeout=5.0,
        identity_store=store,
        require_auth=True,
    )
    app = FastAPI()
    app.include_router(gateway.router)
    with TestClient(app) as client:
        yield client, tmp_path / "threads"


def _send(ws: Any, message: JsonRpcRequest | JsonRpcResponse | Notification) -> None:
    ws.send_text(encode_message(message))


def _recv(ws: Any) -> Any:
    return decode_message(ws.receive_text())


def test_sanitize_turn_params_preserves_auto_approval_when_enabled(tmp_path: Path) -> None:
    from runtime.sensing.gateway.realtime_echo import EchoRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    runtime = EchoRuntime(logs_root=tmp_path / "threads")
    gateway = RealtimeGateway(
        runtime=runtime,
        approval_timeout=5.0,
        allow_client_approval_bypass=True,
    )
    conn = type("Conn", (), {"actor_id": None})()
    params = gateway._sanitize_turn_params(  # type: ignore[attr-defined]
        {
            "threadId": "th",
            "input": [{"type": "text", "text": "hi"}],
            "approvalPolicy": "never",
            "sandboxPolicy": {
                "type": "dangerFullAccess",
                "networkAccess": True,
            },
        },
        conn,
    )

    assert params["approvalPolicy"] == "never"
    assert params["sandboxPolicy"] == {
        "type": "dangerFullAccess",
        "networkAccess": True,
    }


class _BlockingRuntime:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.started: list[str] = []
        self._lock = threading.Lock()

    async def start_turn(self, params: dict[str, Any], emitter: Any) -> Any:
        from runtime.protocol import ServerMethod, Turn, TurnStatus

        thread_id = params["threadId"]
        with self._lock:
            self.started.append(thread_id)
        turn = Turn(threadId=thread_id)
        emitter.register_turn(turn.id)
        try:
            await emitter.notify(
                ServerMethod.TURN_STARTED,
                {
                    "threadId": thread_id,
                    "turn": turn.model_dump(by_alias=True, mode="json"),
                },
            )
            await asyncio.to_thread(self.release.wait)
            turn.status = TurnStatus.COMPLETED
            return turn
        finally:
            emitter.unregister_turn(turn.id)


def _drive_turn(
    ws: Any,
    *,
    thread_id: str,
    text: str,
    approval_policy: str = "on-request",
    approve: bool = True,
) -> dict[str, Any]:
    """Run one turn, responding to any approval request with ``approve``.

    Returns the final response to turn/start (carrying the Turn
    snapshot) plus the ordered list of notifications received.
    """
    _send(
        ws,
        JsonRpcRequest(
            id=1,
            method="turn/start",
            params={
                "threadId": thread_id,
                "input": [{"type": "text", "text": text}],
                "approvalPolicy": approval_policy,
            },
        ),
    )
    notifications: list[Notification] = []
    final: JsonRpcResponse | None = None
    while True:
        msg = _recv(ws)
        if isinstance(msg, Notification):
            notifications.append(msg)
            continue
        if isinstance(msg, JsonRpcRequest):
            # Server-initiated approval request. Reply immediately.
            _send(
                ws,
                JsonRpcResponse(id=msg.id, result={"action": "accept" if approve else "decline"}),
            )
            continue
        if isinstance(msg, JsonRpcResponse) and msg.id == 1:
            final = msg
            break
    assert final is not None
    return {"response": final, "notifications": notifications}


def test_turn_lifecycle_with_approval_accept(gateway_client: Any) -> None:
    client, logs_root = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        outcome = _drive_turn(ws, thread_id="th1", text="hello world")

    methods = [n.method for n in outcome["notifications"]]

    # Required lifecycle events, in order.
    assert "thread/started" in methods
    assert methods.count("turn/started") == 1
    assert methods.count("turn/completed") == 1
    assert methods[-1] == "turn/completed"

    # At least one item started + completed for each of reasoning,
    # commandExecution, agentMessage.
    started = [
        n.params["item"]["type"] for n in outcome["notifications"] if n.method == "item/started"
    ]
    completed = [
        n.params["item"]["type"] for n in outcome["notifications"] if n.method == "item/completed"
    ]
    assert set(started) == {"reasoning", "commandExecution", "agentMessage"}
    assert set(completed) == {"reasoning", "commandExecution", "agentMessage"}

    # Agent message deltas accumulate to the input text.
    deltas = [
        n.params["delta"] for n in outcome["notifications"] if n.method == "item/agentMessage/delta"
    ]
    assert "".join(deltas) == "hello world"

    # Final turn snapshot includes completed commandExecution with exit 0.
    turn = outcome["response"].result["turn"]
    assert turn["status"] == "completed"
    cmd_items = [it for it in turn["items"] if it["type"] == "commandExecution"]
    assert len(cmd_items) == 1
    assert cmd_items[0]["status"] == "completed"
    assert cmd_items[0]["exitCode"] == 0

    # The event log on disk should have recorded every event.
    log_path = logs_root / "th1.jsonl"
    assert log_path.exists()
    lines = [json.loads(line) for line in log_path.read_text("utf-8").splitlines() if line.strip()]
    event_types = [line["event"] for line in lines]
    assert "thread_started" in event_types
    assert "turn_started" in event_types
    assert "turn_completed" in event_types
    # At minimum one item_delta per streamed item kind.
    assert event_types.count("item_started") == 3
    assert event_types.count("item_completed") == 3


def test_turn_lifecycle_with_approval_decline(gateway_client: Any) -> None:
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        outcome = _drive_turn(ws, thread_id="th2", text="deny me", approve=False)

    turn = outcome["response"].result["turn"]
    cmd_items = [it for it in turn["items"] if it["type"] == "commandExecution"]
    assert cmd_items[0]["status"] == "declined"
    # Turn still completes normally.
    assert turn["status"] == "completed"


def test_turn_lifecycle_client_approval_never_is_coerced(gateway_client: Any) -> None:
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        _send(
            ws,
            JsonRpcRequest(
                id=1,
                method="turn/start",
                params={
                    "threadId": "th3",
                    "input": [{"type": "text", "text": "no approval"}],
                    "approvalPolicy": "never",
                },
            ),
        )
        notifications: list[Notification] = []
        while True:
            msg = _recv(ws)
            if isinstance(msg, JsonRpcRequest):
                _send(ws, JsonRpcResponse(id=msg.id, result={"action": "accept"}))
                continue
            if isinstance(msg, Notification):
                notifications.append(msg)
                continue
            if isinstance(msg, JsonRpcResponse):
                break

    starts = [n.params["item"]["type"] for n in notifications if n.method == "item/started"]
    assert "commandExecution" in starts


def test_realtime_rejects_unauthenticated_when_required(
    authenticated_gateway_client: Any,
) -> None:
    client, _ = authenticated_gateway_client
    assert WebSocketDisconnect is not None
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/realtime"):
        pass


def test_realtime_accepts_query_token_when_required(
    authenticated_gateway_client: Any,
) -> None:
    client, _ = authenticated_gateway_client
    with client.websocket_connect("/api/realtime?token=sk-alice") as ws:
        outcome = _drive_turn(ws, thread_id="auth_th", text="hello auth")

    assert outcome["response"].result["turn"]["status"] == "completed"


def test_realtime_accepts_subprotocol_token_when_required(
    authenticated_gateway_client: Any,
) -> None:
    """Browser clients authenticate via Sec-WebSocket-Protocol instead of a
    query param, so the token stays out of access/proxy logs. The gateway
    must extract the token AND echo the ``bearer`` marker as the selected
    subprotocol — RFC 6455 fails the handshake otherwise."""
    client, _ = authenticated_gateway_client
    with client.websocket_connect(
        "/api/realtime",
        subprotocols=["bearer", "sk-alice"],
    ) as ws:
        assert ws.accepted_subprotocol == "bearer"
        outcome = _drive_turn(ws, thread_id="auth_th_subproto", text="hello auth")

    assert outcome["response"].result["turn"]["status"] == "completed"


def test_realtime_thread_resume_rejects_other_actor(
    two_actor_gateway_client: Any,
) -> None:
    client, _ = two_actor_gateway_client
    with client.websocket_connect("/api/realtime?token=sk-alice") as ws:
        _drive_turn(
            ws,
            thread_id="auth_owner_thread",
            text="alice only",
            approval_policy="never",
        )

    with client.websocket_connect("/api/realtime?token=sk-bob") as ws:
        _send(
            ws,
            JsonRpcRequest(
                id=91,
                method="thread/resume",
                params={"threadId": "auth_owner_thread"},
            ),
        )
        msg = _recv(ws)

    assert isinstance(msg, JsonRpcResponse)
    assert msg.error is not None
    assert msg.error.code in {
        JsonRpcErrorCode.THREAD_NOT_FOUND,
        JsonRpcErrorCode.UNAUTHORIZED,
    }


def test_in_flight_request_limit_rejects_extra_turns() -> None:
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    runtime = _BlockingRuntime()
    gateway = RealtimeGateway(
        runtime=runtime,
        max_in_flight_requests_per_connection=1,
    )
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        _send(
            ws,
            JsonRpcRequest(
                id=1,
                method="turn/start",
                params={"threadId": "busy-a", "input": []},
            ),
        )
        first = _recv(ws)
        assert isinstance(first, Notification)
        assert first.method == "turn/started"

        _send(
            ws,
            JsonRpcRequest(
                id=2,
                method="turn/start",
                params={"threadId": "busy-b", "input": []},
            ),
        )
        second = _recv(ws)
        assert isinstance(second, JsonRpcResponse)
        assert second.id == 2
        assert second.error is not None
        assert second.error.code == JsonRpcErrorCode.SERVER_BUSY

        runtime.release.set()
        while True:
            msg = _recv(ws)
            if isinstance(msg, JsonRpcResponse) and msg.id == 1:
                break
        assert msg.result["turn"]["status"] == "completed"


def test_same_thread_turns_are_serialized() -> None:
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    runtime = _BlockingRuntime()
    gateway = RealtimeGateway(
        runtime=runtime,
        max_in_flight_requests_per_connection=2,
    )
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        for req_id in (1, 2):
            _send(
                ws,
                JsonRpcRequest(
                    id=req_id,
                    method="turn/start",
                    params={"threadId": "same-thread", "input": []},
                ),
            )

        first = _recv(ws)
        assert isinstance(first, Notification)
        assert first.method == "turn/started"
        time.sleep(0.1)
        assert runtime.started == ["same-thread"]

        runtime.release.set()
        saw_second_started = False
        saw_responses: set[int] = set()
        while saw_responses != {1, 2}:
            msg = _recv(ws)
            if isinstance(msg, Notification) and msg.method == "turn/started":
                saw_second_started = True
            if isinstance(msg, JsonRpcResponse):
                saw_responses.add(int(msg.id))

        assert saw_second_started
        assert runtime.started == ["same-thread", "same-thread"]


def test_resume_reconstructs_turns(gateway_client: Any) -> None:
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        _drive_turn(ws, thread_id="th4", text="hello resume")

    with client.websocket_connect("/api/realtime") as ws:
        _send(ws, JsonRpcRequest(id=42, method="thread/resume", params={"threadId": "th4"}))
        while True:
            msg = _recv(ws)
            if isinstance(msg, JsonRpcResponse) and msg.id == 42:
                break

    assert msg.result is not None
    turns = msg.result["turns"]
    assert len(turns) == 1
    turn = turns[0]
    assert turn["status"] == "completed"
    # agent message rebuilt from deltas on disk
    agent_items = [it for it in turn["items"] if it["type"] == "agentMessage"]
    assert agent_items
    assert agent_items[0]["text"] == "hello resume"


def test_method_not_found_returns_proper_error(gateway_client: Any) -> None:
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        _send(ws, JsonRpcRequest(id=99, method="does/not/exist", params={}))
        msg = _recv(ws)
    assert isinstance(msg, JsonRpcResponse)
    assert msg.error is not None
    assert msg.error.code == JsonRpcErrorCode.METHOD_NOT_FOUND


def test_concurrent_connections_dont_share_pending_approvals(gateway_client: Any) -> None:
    """A pending approval on connection A must not bleed into B."""
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws_a:  # noqa: SIM117 — body uses both ws_a and ws_b separately
        with client.websocket_connect("/api/realtime") as ws_b:
            # Start A, which will block on approval.
            _send(
                ws_a,
                JsonRpcRequest(
                    id=1,
                    method="turn/start",
                    params={
                        "threadId": "th_a",
                        "input": [{"type": "text", "text": "a"}],
                        "approvalPolicy": "on-request",
                    },
                ),
            )
            # Pump A until it issues the approval request.
            a_request: JsonRpcRequest | None = None
            while a_request is None:
                msg = _recv(ws_a)
                if isinstance(msg, JsonRpcRequest):
                    a_request = msg

            # Meanwhile B runs its own approval loop without touching
            # A's pending state.
            _send(
                ws_b,
                JsonRpcRequest(
                    id=1,
                    method="turn/start",
                    params={
                        "threadId": "th_b",
                        "input": [{"type": "text", "text": "b"}],
                        "approvalPolicy": "on-request",
                    },
                ),
            )
            while True:
                msg = _recv(ws_b)
                if isinstance(msg, JsonRpcRequest):
                    _send(ws_b, JsonRpcResponse(id=msg.id, result={"action": "accept"}))
                    continue
                if isinstance(msg, JsonRpcResponse) and msg.id == 1:
                    break

            # Now reply to A and let it finish.
            _send(ws_a, JsonRpcResponse(id=a_request.id, result={"action": "accept"}))
            while True:
                msg = _recv(ws_a)
                if isinstance(msg, JsonRpcResponse) and msg.id == 1:
                    break

    assert msg.result is not None
    assert msg.result["turn"]["status"] == "completed"


# ── thread/list and thread/archive tests ────────────────────


def test_thread_list_orders_by_recency(gateway_client: Any) -> None:
    client, _ = gateway_client

    def run_thread(thread_id: str) -> None:
        with client.websocket_connect("/api/realtime") as ws:
            _drive_turn(ws, thread_id=thread_id, text=f"hi {thread_id}", approval_policy="never")

    run_thread("th_alpha")
    run_thread("th_beta")
    run_thread("th_gamma")

    with client.websocket_connect("/api/realtime") as ws:
        _send(ws, JsonRpcRequest(id=11, method="thread/list", params={}))
        while True:
            msg = _recv(ws)
            if isinstance(msg, JsonRpcResponse) and msg.id == 11:
                break

    assert msg.result is not None
    threads = msg.result["threads"]
    ids = [t["threadId"] for t in threads]
    assert set(ids) == {"th_alpha", "th_beta", "th_gamma"}
    # Most-recent first.
    assert ids[0] == "th_gamma"
    # Each summary carries lifecycle metadata.
    for t in threads:
        assert t["turnCount"] == 1
        assert t["lastTurnStatus"] == "completed"
        assert t["archived"] is False


def test_thread_archive_hides_from_list(gateway_client: Any) -> None:
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        _drive_turn(ws, thread_id="th_kept", text="alive", approval_policy="never")
        _drive_turn(ws, thread_id="th_gone", text="bye", approval_policy="never")

    # Archive one.
    with client.websocket_connect("/api/realtime") as ws:
        _send(ws, JsonRpcRequest(id=21, method="thread/archive", params={"threadId": "th_gone"}))
        while True:
            msg = _recv(ws)
            if isinstance(msg, JsonRpcResponse) and msg.id == 21:
                break
    assert msg.result == {"threadId": "th_gone", "archived": True}

    # Default list excludes archived.
    with client.websocket_connect("/api/realtime") as ws:
        _send(ws, JsonRpcRequest(id=22, method="thread/list", params={}))
        while True:
            msg = _recv(ws)
            if isinstance(msg, JsonRpcResponse) and msg.id == 22:
                break
    assert msg.result is not None
    ids = [t["threadId"] for t in msg.result["threads"]]
    assert ids == ["th_kept"]

    # includeArchived=True surfaces both.
    with client.websocket_connect("/api/realtime") as ws:
        _send(
            ws,
            JsonRpcRequest(
                id=23,
                method="thread/list",
                params={"includeArchived": True},
            ),
        )
        while True:
            msg = _recv(ws)
            if isinstance(msg, JsonRpcResponse) and msg.id == 23:
                break
    assert msg.result is not None
    payload = msg.result["threads"]
    archived_ids = {t["threadId"] for t in payload if t["archived"]}
    assert archived_ids == {"th_gone"}


def test_thread_archive_blocks_resume(gateway_client: Any) -> None:
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        _drive_turn(ws, thread_id="th_archived_resume", text="bye", approval_policy="never")
        _send(
            ws,
            JsonRpcRequest(
                id=24,
                method="thread/archive",
                params={"threadId": "th_archived_resume"},
            ),
        )
        while True:
            msg = _recv(ws)
            if isinstance(msg, JsonRpcResponse) and msg.id == 24:
                break
        _send(
            ws,
            JsonRpcRequest(
                id=25,
                method="thread/resume",
                params={"threadId": "th_archived_resume"},
            ),
        )
        while True:
            msg = _recv(ws)
            if isinstance(msg, JsonRpcResponse) and msg.id == 25:
                break

    assert msg.error is not None
    assert msg.error.code == JsonRpcErrorCode.THREAD_NOT_FOUND


def test_thread_archive_unknown_returns_error(gateway_client: Any) -> None:
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        _send(
            ws,
            JsonRpcRequest(id=31, method="thread/archive", params={"threadId": "missing"}),
        )
        msg = _recv(ws)
    assert isinstance(msg, JsonRpcResponse)
    assert msg.error is not None
    assert msg.error.code == JsonRpcErrorCode.THREAD_NOT_FOUND


def test_turn_start_rejects_path_traversal_thread_id(gateway_client: Any) -> None:
    client, logs_root = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        _send(
            ws,
            JsonRpcRequest(
                id=90,
                method="turn/start",
                params={
                    "threadId": "../escape",
                    "input": [{"type": "text", "text": "escape"}],
                    "approvalPolicy": "never",
                },
            ),
        )
        while True:
            msg = _recv(ws)
            if isinstance(msg, JsonRpcRequest):
                _send(ws, JsonRpcResponse(id=msg.id, result={"action": "accept"}))
                continue
            if isinstance(msg, JsonRpcResponse) and msg.id == 90:
                break

    assert msg.error is not None
    assert msg.error.code == JsonRpcErrorCode.INVALID_PARAMS
    assert not (logs_root.parent / "escape.jsonl").exists()


def test_turn_interrupt_stops_streaming_at_boundary(gateway_client: Any) -> None:
    """Interrupting after turn/started but before the first reasoning
    delta should short-circuit to a turn with ``status == interrupted``.

    The EchoRuntime polls ``is_turn_interrupted`` between items, so
    the cleanest observable effect is that no item of the later kinds
    appears on the final snapshot.
    """
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        _send(
            ws,
            JsonRpcRequest(
                id=1,
                method="turn/start",
                params={
                    "threadId": "th_int",
                    "input": [{"type": "text", "text": "will be cut"}],
                    "approvalPolicy": "never",
                },
            ),
        )
        # Grab turn id from turn/started, then interrupt.
        interrupted = False
        turn_id: str | None = None
        final: JsonRpcResponse | None = None
        notifications: list[Notification] = []
        while final is None:
            msg = _recv(ws)
            if isinstance(msg, Notification):
                notifications.append(msg)
                if msg.method == "turn/started" and not interrupted:
                    turn_id = msg.params["turn"]["id"]
                    _send(
                        ws,
                        JsonRpcRequest(
                            id=2,
                            method="turn/interrupt",
                            params={"threadId": "th_int", "turnId": turn_id},
                        ),
                    )
                    interrupted = True
                continue
            if isinstance(msg, JsonRpcResponse):
                if msg.id == 2:
                    # interrupt response; ignore
                    continue
                if msg.id == 1:
                    final = msg
    assert final.result is not None
    turn = final.result["turn"]
    assert turn["status"] == "interrupted"
    # At most the reasoning item may have partially started before
    # the interrupt was observed; commandExecution and agentMessage
    # should never appear because approvalPolicy=never skips command
    # and the interrupt fires before agentMessage.
    types = {it["type"] for it in turn["items"]}
    assert "agentMessage" not in types


def test_turn_interrupt_unknown_turn_acks_without_marking(gateway_client: Any) -> None:
    """Client races a stale turn id — the server acknowledges without
    error, but honestly reports that no running turn was flagged
    (``interrupted: False``). It used to claim True unconditionally,
    letting clients render "stopped" for turns that kept running."""
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        _send(
            ws,
            JsonRpcRequest(
                id=5,
                method="turn/interrupt",
                params={"threadId": "th_noop", "turnId": "trn_nonexistent"},
            ),
        )
        msg = _recv(ws)
    assert isinstance(msg, JsonRpcResponse)
    assert msg.result == {"turnId": "trn_nonexistent", "interrupted": False}


class _SpinningRuntime:
    """Turn spins until its interrupt flag lands (bounded, then completes).

    Polls ``is_turn_interrupted`` like a real driver, so a flag raised
    by a *different* connection must stop the turn. The spin is bounded
    so a regression fails the test loudly (status ``completed``)
    instead of hanging.
    """

    async def start_turn(self, params: dict[str, Any], emitter: Any) -> Any:
        from runtime.protocol import ServerMethod, Turn, TurnStatus

        thread_id = params["threadId"]
        turn = Turn(threadId=thread_id)
        emitter.register_turn(turn.id)
        try:
            await emitter.notify(
                ServerMethod.TURN_STARTED,
                {
                    "threadId": thread_id,
                    "turn": turn.model_dump(by_alias=True, mode="json"),
                },
            )
            for _ in range(400):
                if emitter.is_turn_interrupted(turn.id):
                    turn.status = TurnStatus.INTERRUPTED
                    break
                await asyncio.sleep(0.02)
            else:
                turn.status = TurnStatus.COMPLETED
            return turn
        finally:
            emitter.unregister_turn(turn.id)


def test_turn_interrupt_from_second_connection_stops_running_turn() -> None:
    """Regression: the interrupt flag used to be per-connection, so a
    second tab (its own WS) interrupting a turn running on the first
    connection marked only its own registry — the server kept running
    while the interrupting client showed "stopped". The gateway now
    keeps a shared registry that the running turn's emitter also polls.
    """
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    runtime = _SpinningRuntime()
    gateway = RealtimeGateway(runtime=runtime)
    app = FastAPI()
    app.include_router(gateway.router)

    with (
        TestClient(app) as client,
        client.websocket_connect("/api/realtime") as ws_a,
        client.websocket_connect("/api/realtime") as ws_b,
    ):
        _send(
            ws_a,
            JsonRpcRequest(
                id=1,
                method="turn/start",
                params={"threadId": "th_xconn", "input": []},
            ),
        )
        turn_id: str | None = None
        while turn_id is None:
            msg = _recv(ws_a)
            if isinstance(msg, Notification) and msg.method == "turn/started":
                turn_id = msg.params["turn"]["id"]

        # B — a different connection — interrupts A's running turn.
        _send(
            ws_b,
            JsonRpcRequest(
                id=2,
                method="turn/interrupt",
                params={"threadId": "th_xconn", "turnId": turn_id},
            ),
        )
        b_resp = _recv(ws_b)
        assert isinstance(b_resp, JsonRpcResponse)
        # Honest ack: a running turn really was flagged.
        assert b_resp.result == {"turnId": turn_id, "interrupted": True}

        final: JsonRpcResponse | None = None
        while final is None:
            msg = _recv(ws_a)
            if isinstance(msg, JsonRpcResponse) and msg.id == 1:
                final = msg

    assert final.result is not None
    assert final.result["turn"]["status"] == "interrupted"


def test_turn_completed_fans_out_to_thread_watchers(gateway_client: Any) -> None:
    """A second connection that resumed the thread receives the
    terminal turn/completed even though the turn ran on the first
    connection (previously it had to poll thread/resume again).

    Since the delta-fanout fix, the sibling also receives throttled
    delta events before the terminal snapshot — drain until
    ``turn/completed`` arrives.
    """
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws_a:
        _drive_turn(ws_a, thread_id="th_fanout", text="seed", approval_policy="never")
        with client.websocket_connect("/api/realtime") as ws_b:
            _send(
                ws_b,
                JsonRpcRequest(
                    id=7,
                    method="thread/resume",
                    params={"threadId": "th_fanout"},
                ),
            )
            while True:
                msg = _recv(ws_b)
                if isinstance(msg, JsonRpcResponse) and msg.id == 7:
                    break
            # The second turn runs on A; B must observe its terminal event.
            outcome = _drive_turn(
                ws_a,
                thread_id="th_fanout",
                text="second",
                approval_policy="never",
            )
            assert outcome["response"].result["turn"]["status"] == "completed"
            # Drain B: deltas may arrive first, then turn/completed.
            fanned: Notification | None = None
            while True:
                msg = _recv(ws_b)
                if isinstance(msg, Notification) and msg.method == "turn/completed":
                    fanned = msg
                    break
            assert fanned is not None
            assert fanned.params["threadId"] == "th_fanout"
            assert fanned.params["turn"]["status"] == "completed"


def test_sibling_connection_receives_delta_events(gateway_client: Any) -> None:
    """A sibling connection watching the same thread receives delta
    events (throttled), not just the terminal turn/completed snapshot.

    Previously the sibling only got turn/completed; now the gateway
    wraps the primary emitter with a fanout proxy that forwards delta
    notifications to every connection that resumed the thread.
    """
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws_a:
        # Seed the thread so ws_b can resume it and gain reducer state.
        _drive_turn(ws_a, thread_id="th_delta_fanout", text="seed", approval_policy="never")
        with client.websocket_connect("/api/realtime") as ws_b:
            # ws_b resumes → becomes a watcher with reducer state.
            _send(
                ws_b,
                JsonRpcRequest(
                    id=7,
                    method="thread/resume",
                    params={"threadId": "th_delta_fanout"},
                ),
            )
            while True:
                msg = _recv(ws_b)
                if isinstance(msg, JsonRpcResponse) and msg.id == 7:
                    break

            # Second turn runs on A; B must observe delta events.
            outcome = _drive_turn(
                ws_a,
                thread_id="th_delta_fanout",
                text="second turn",
                approval_policy="never",
            )
            assert outcome["response"].result["turn"]["status"] == "completed"

            # Drain B: collect all messages until turn/completed arrives.
            b_notifications: list[Notification] = []
            while True:
                msg = _recv(ws_b)
                if isinstance(msg, Notification):
                    b_notifications.append(msg)
                    if msg.method == "turn/completed":
                        break

            delta_methods = {
                "item/agentMessage/delta",
                "item/reasoning/textDelta",
                "item/plan/delta",
                "item/commandExecution/outputDelta",
            }
            delta_events = [n for n in b_notifications if n.method in delta_methods]
            # The sibling must have received at least some deltas.
            assert len(delta_events) > 0, "sibling should receive delta events"

            # agentMessage deltas forwarded to the sibling must
            # reconstruct the same text the primary connection saw.
            agent_deltas = [
                n.params["delta"]
                for n in b_notifications
                if n.method == "item/agentMessage/delta"
            ]
            if agent_deltas:
                assert "".join(agent_deltas) == "second turn"

            # turn/completed must also arrive (existing fanout path).
            assert any(n.method == "turn/completed" for n in b_notifications)


def test_sibling_without_reducer_state_skips_delta_fanout(gateway_client: Any) -> None:
    """A connection that has NOT resumed the thread must not receive
    delta events — it has no reducer state, so forwarding deltas would
    produce ghost UI for items it doesn't know about.

    A non-watcher connection receives no unsolicited notifications at
    all (no deltas, no ``turn/completed`` — the terminal fanout also
    keys off ``last_resumed_thread_id``). We verify the absence of
    deltas by sending a ``ping`` after the turn completes and asserting
    the ``pong`` reply is the only message received: any incorrectly
    fanned-out delta or terminal snapshot would precede or follow the
    pong and surface in ``b_notifications``.
    """
    client, _ = gateway_client
    delta_methods = {
        "item/agentMessage/delta",
        "item/reasoning/textDelta",
        "item/plan/delta",
        "item/commandExecution/outputDelta",
    }
    with client.websocket_connect("/api/realtime") as ws_a:
        _drive_turn(ws_a, thread_id="th_no_reducer", text="seed", approval_policy="never")
        with client.websocket_connect("/api/realtime") as ws_b:
            # ws_b does NOT resume the thread → no reducer state, and
            # last_resumed_thread_id stays None, so the gateway's
            # sibling list and terminal-fanout list both skip it.
            outcome = _drive_turn(
                ws_a,
                thread_id="th_no_reducer",
                text="second",
                approval_policy="never",
            )
            assert outcome["response"].result["turn"]["status"] == "completed"

            # Drive the event loop so any best-effort fanout notifications
            # (had ws_b been wrongly included) would be queued before the
            # ping. The ping reply (``pong``) is the ONLY message a
            # non-watcher should ever see here.
            _send(ws_b, Notification(method="ping", params={}))

            b_notifications: list[Notification] = []
            while True:
                msg = _recv(ws_b)
                if isinstance(msg, Notification):
                    b_notifications.append(msg)
                    if msg.method == "pong":
                        break

            delta_events = [n for n in b_notifications if n.method in delta_methods]
            assert len(delta_events) == 0, "non-watcher should not receive deltas"
            completed_events = [n for n in b_notifications if n.method == "turn/completed"]
            assert len(completed_events) == 0, "non-watcher should not receive turn/completed"
            # The only message received must be the pong reply.
            assert len(b_notifications) == 1
            assert b_notifications[0].method == "pong"


def test_turn_interrupt_missing_turn_id_is_invalid_params(gateway_client: Any) -> None:
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        _send(ws, JsonRpcRequest(id=6, method="turn/interrupt", params={}))
        msg = _recv(ws)
    assert isinstance(msg, JsonRpcResponse)
    assert msg.error is not None
    assert msg.error.code == JsonRpcErrorCode.INVALID_PARAMS


def test_ping_elicits_pong(gateway_client: Any) -> None:
    """Client-side keepalive: server must reply with ``pong`` notification
    so the client can detect a wedged-but-open connection (half-open
    TCP, proxy black-hole) and force-reconnect."""
    client, _ = gateway_client
    with client.websocket_connect("/api/realtime") as ws:
        # ping is a Notification (no id), so the server replies with a
        # Notification (``pong``) — not a JsonRpcResponse.
        ws.send_text(encode_message(Notification(method="ping", params={})))
        msg = _recv(ws)
    assert isinstance(msg, Notification)
    assert msg.method == "pong"


class TestCreateAppApprovalBypassDefault:
    """create_app must default client approval-bypass to OFF. It used to
    hardcode allow_client_auto_approve=True / allow_client_approval_bypass
    =True, letting any WS client set approvalPolicy="never" and skip the
    human gate. Now it's driven by safety.allow_client_approval_bypass,
    secure-by-default.
    """

    def _app(self, tmp_path: Path, monkeypatch: Any, allow_bypass: Any):
        monkeypatch.chdir(tmp_path)
        from runtime.platform.config.builder import build_from_config
        from runtime.platform.config.schema import (
            AgentConfig,
            PlannerConfig,
            SafetyConfig,
        )
        from runtime.platform.ui.app import create_app

        safety = (
            SafetyConfig(allow_client_approval_bypass=allow_bypass)
            if allow_bypass is not None
            else SafetyConfig()
        )
        cfg = AgentConfig(
            planner=PlannerConfig(
                type="llm",
                model="mock/ob",
                mock_response='{"reasoning":"r","nodes":[]}',
            ),
            safety=safety,
        )
        stack = build_from_config(cfg)
        return create_app(
            journal=stack.journal,
            registry=stack.registry,
            stack=stack,
        )

    def test_secure_default_is_no_bypass(self, tmp_path: Path, monkeypatch: Any):
        app = self._app(tmp_path, monkeypatch, allow_bypass=None)
        gw = app.state.realtime_gateway
        assert gw._allow_client_approval_bypass is False

    def test_operator_can_opt_in(self, tmp_path: Path, monkeypatch: Any):
        app = self._app(tmp_path, monkeypatch, allow_bypass=True)
        gw = app.state.realtime_gateway
        assert gw._allow_client_approval_bypass is True


@pytest.mark.asyncio
async def test_approval_manager_cancels_only_the_interrupted_turn() -> None:
    from runtime.sensing.gateway.realtime_gateway import ApprovalManager

    manager = ApprovalManager()
    _, turn_a = await manager.open(turn_id="turn-a")
    _, turn_b = await manager.open(turn_id="turn-b")

    assert await manager.cancel_turn("turn-a") == 1
    assert await turn_a == {"action": "decline", "reason": "turn interrupted"}
    assert not turn_b.done()

    await manager.cancel_all()

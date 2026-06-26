"""Auth on tentacle screen-stream WebSockets.

The HTTP /api/tentacle/* routes can be protected by app middleware, but
the screen-stream sockets bypass HTTP middleware entirely. These tests
lock the handshake boundary: when require_auth is enabled, an anonymous
or wrong-token client is closed with 4401 before any stream subscription
is established.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from runtime.safety.auth import Identity, IdentityStore
from runtime.tentacle.dashboard import create_tentacle_router


class _DummyCoordinator:
    screen_relay = None
    _dashboard_port = 8000


def _store() -> IdentityStore:
    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    return store


def _client(require_auth: bool, store: IdentityStore | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_tentacle_router(
            _DummyCoordinator(),
            identity_store=store,
            require_auth=require_auth,
        )
    )
    return TestClient(app)


def test_tentacle_screen_ws_rejects_missing_token_when_required() -> None:
    client = _client(require_auth=True, store=_store())
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(
        "/api/tentacle/screen/stream"
    ) as ws:
        ws.receive_text()
    assert exc_info.value.code == 4401


def test_tentacle_pc_screen_ws_rejects_wrong_token_when_required() -> None:
    client = _client(require_auth=True, store=_store())
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(
        "/api/tentacle/pc-screen/stream?token=nope"
    ) as ws:
        ws.receive_text()
    assert exc_info.value.code == 4401


def test_tentacle_ws_require_auth_without_identity_store_rejects() -> None:
    client = _client(require_auth=True, store=None)
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(
        "/api/tentacle/screen/stream?token=anything"
    ) as ws:
        ws.receive_text()
    assert exc_info.value.code == 4401

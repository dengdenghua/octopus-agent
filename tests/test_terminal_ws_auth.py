"""Auth on the persistent-shell terminal WebSocket.

/api/terminal/ws opens a real shell, and used to ``accept()`` and spawn
it for anyone. These tests lock the security guarantee: when require_auth
is set, an unauthenticated (or wrong-token) client is closed with 4401
BEFORE a process is ever created.

(The accepted-token path spawns a real subprocess whose lifetime spans
the TestClient's event loop, which makes deterministic cleanup flaky in
a unit test; the rejection path — the actual security boundary — needs
no subprocess and is what we lock here.)
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from runtime.safety.auth import Identity, IdentityStore
from runtime.sensing.gateway import terminal_router
from runtime.sensing.gateway.terminal_router import ShellSession, mount_terminal_routes


def _store() -> IdentityStore:
    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    store.add(Identity(actor_id="bob"), api_key_plaintext="sk-bob")
    return store


@pytest.fixture(autouse=True)
def _isolate_sessions():
    """Restore the module-global _sessions map after each test so a
    pre-seeded session never leaks into a sibling test."""
    saved = dict(terminal_router._sessions)
    try:
        yield
    finally:
        terminal_router._sessions.clear()
        terminal_router._sessions.update(saved)


def _seed_owned_session(session_id: str, owner: str) -> None:
    """Register a session already owned by ``owner`` without spawning a
    shell — start() is never called, so there is no subprocess."""
    sess = ShellSession(session_id)
    sess.owner_actor = owner
    terminal_router._sessions[session_id] = sess


def _client(require_auth: bool, store: IdentityStore | None = None) -> TestClient:
    app = FastAPI()
    mount_terminal_routes(app, identity_store=store, require_auth=require_auth)
    return TestClient(app)


def test_ws_rejects_missing_token_when_required():
    client = _client(require_auth=True, store=_store())
    with (
        pytest.raises(WebSocketDisconnect) as ei,
        client.websocket_connect("/api/terminal/ws/s1") as ws,
    ):
        ws.receive_text()
    assert ei.value.code == 4401  # closed before any shell spawned


def test_ws_rejects_wrong_token_when_required():
    client = _client(require_auth=True, store=_store())
    with (
        pytest.raises(WebSocketDisconnect) as ei,
        client.websocket_connect("/api/terminal/ws/s1?token=nope") as ws,
    ):
        ws.receive_text()
    assert ei.value.code == 4401


def test_ws_require_auth_without_identity_store_rejects():
    # require_auth set but no identity store wired → fail closed, not open.
    client = _client(require_auth=True, store=None)
    with (
        pytest.raises(WebSocketDisconnect) as ei,
        client.websocket_connect("/api/terminal/ws/s1?token=anything") as ws,
    ):
        ws.receive_text()
    assert ei.value.code == 4401


def test_terminal_kill_requires_auth_when_required():
    client = _client(require_auth=True, store=_store())
    unauth = client.post("/api/terminal/kill/s1")
    assert unauth.status_code == 401
    ok = client.post(
        "/api/terminal/kill/s1",
        headers={"Authorization": "Bearer sk-alice"},
    )
    assert ok.status_code == 200


# ── Per-session ownership (IDOR) ───────────────────────────────
# session_id is a client-controlled URL segment; without an owner check a
# second authenticated actor could attach to another user's live shell.


def test_ws_rejects_foreign_owner_before_spawn():
    # alice owns the session; bob (a valid, different actor) must not be
    # able to attach — closed 4403 before any shell is (re)started.
    client = _client(require_auth=True, store=_store())
    _seed_owned_session("agent-workbench-thread-alice", owner="alice")
    with (
        pytest.raises(WebSocketDisconnect) as ei,
        client.websocket_connect(
            "/api/terminal/ws/agent-workbench-thread-alice?token=sk-bob"
        ) as ws,
    ):
        ws.receive_text()
    assert ei.value.code == 4403
    # bob never took ownership; the shell is still alice's.
    assert terminal_router._sessions["agent-workbench-thread-alice"].owner_actor == "alice"


def test_bind_or_check_owner_semantics():
    # Unit-level (no subprocess): the accepted-owner path spawns a real
    # shell whose lifetime spans the TestClient loop and is flaky to reap,
    # so the allow-path is locked here on the pure gate function instead.
    from runtime.sensing.gateway.terminal_router import _bind_or_check_owner

    sess = ShellSession("s-gate")
    # Auth off (actor None): ownership never enforced, nothing bound.
    assert _bind_or_check_owner(sess, None) is True
    assert sess.owner_actor is None
    # First authenticated connect binds the owner.
    assert _bind_or_check_owner(sess, "alice") is True
    assert sess.owner_actor == "alice"
    # Owner reconnecting is allowed; a foreign actor is refused.
    assert _bind_or_check_owner(sess, "alice") is True
    assert _bind_or_check_owner(sess, "bob") is False
    # An auth-off probe against an owned session is still allowed (local
    # single-user mode is unaffected by the multi-tenant gate).
    assert _bind_or_check_owner(sess, None) is True


def test_kill_foreign_owner_returns_404():
    client = _client(require_auth=True, store=_store())
    _seed_owned_session("agent-workbench-thread-alice", owner="alice")
    # bob may not kill alice's session — 404 hides its existence.
    foreign = client.post(
        "/api/terminal/kill/agent-workbench-thread-alice",
        headers={"Authorization": "Bearer sk-bob"},
    )
    assert foreign.status_code == 404
    assert "agent-workbench-thread-alice" in terminal_router._sessions
    # the owner still can.
    owned = client.post(
        "/api/terminal/kill/agent-workbench-thread-alice",
        headers={"Authorization": "Bearer sk-alice"},
    )
    assert owned.status_code == 200

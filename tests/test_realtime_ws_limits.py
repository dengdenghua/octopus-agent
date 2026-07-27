"""Lenient per-actor anti-abuse ceilings on the realtime WS gateway.

Two ceilings, both no-ops when auth is off (actor_id None) or set to 0:
  * connection cap — one actor can't open unbounded WS connections;
  * turn-start rate — one actor can't flood turn/start.

They're sized generously (many tabs/devices + bursts pass); these tests
drive tiny caps to exercise the boundary without needing real load.
"""

from __future__ import annotations

import asyncio
import types

import pytest

try:
    import fastapi  # noqa: F401

    _FASTAPI = True
except ImportError:  # pragma: no cover
    _FASTAPI = False

from runtime.protocol.envelope import JsonRpcErrorCode

pytestmark = pytest.mark.skipif(not _FASTAPI, reason="fastapi extras required")


def _gateway(**kw):
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    return RealtimeGateway(runtime=object(), **kw)


# ── connection cap ────────────────────────────────────────────


def test_connection_cap_admits_to_limit_then_refuses():
    gw = _gateway(max_connections_per_actor=2)
    assert gw._admit_connection("alice") is True
    assert gw._admit_connection("alice") is True
    assert gw._admit_connection("alice") is False  # at cap
    assert gw._admit_connection("bob") is True  # a different actor is free


def test_connection_release_restores_capacity_and_self_cleans():
    gw = _gateway(max_connections_per_actor=1)
    assert gw._admit_connection("alice") is True
    assert gw._admit_connection("alice") is False
    gw._release_connection("alice")
    assert "alice" not in gw._conn_counts  # counter map drops the key at 0
    assert gw._admit_connection("alice") is True  # capacity restored


def test_connection_cap_ignores_anonymous_actor():
    gw = _gateway(max_connections_per_actor=1)
    for _ in range(100):
        assert gw._admit_connection(None) is True  # auth off → never limited
    assert gw._conn_counts == {}


def test_connection_cap_disabled_when_zero():
    gw = _gateway(max_connections_per_actor=0)
    for _ in range(100):
        assert gw._admit_connection("alice") is True
    assert gw._conn_counts == {}
    assert gw._turn_rate_limiter is not None  # rate limit independent of cap


@pytest.mark.parametrize(
    ("offered", "expected"),
    [
        ("bearer, token-value", "bearer"),
        ("Bearer, token-value", "bearer"),
        ("chat, bearer, token-value", "bearer"),
        ("chat", None),
        ("", None),
    ],
)
def test_websocket_subprotocol_acceptance(offered: str, expected: str | None):
    gw = _gateway()
    ws = types.SimpleNamespace(
        headers={"sec-websocket-protocol": offered},
    )
    assert gw._accept_subprotocol(ws) == expected


# ── turn-start rate ───────────────────────────────────────────


def test_turn_rate_limit_raises_server_busy_when_exhausted():
    from runtime.sensing.gateway.realtime_gateway import _RpcError

    gw = _gateway(max_turns_per_minute_per_actor=1)
    conn = types.SimpleNamespace(actor_id="alice")
    # Spend alice's single-turn budget, so the next start is over the line.
    assert gw._turn_rate_limiter.allow("alice") is True
    with pytest.raises(_RpcError) as ei:
        asyncio.run(gw._invoke_turn_start({"threadId": "t1"}, conn))
    assert ei.value.code == JsonRpcErrorCode.SERVER_BUSY


def test_turn_rate_limit_skipped_for_anonymous_actor():
    from runtime.sensing.gateway.realtime_gateway import _RpcError

    gw = _gateway(max_turns_per_minute_per_actor=1)
    conn = types.SimpleNamespace(actor_id=None)
    # No rate limit for anon → the guard is skipped and we fall through to
    # threadId validation, which rejects the missing id with INVALID_PARAMS
    # (i.e. NOT SERVER_BUSY — proof the limiter never fired).
    with pytest.raises(_RpcError) as ei:
        asyncio.run(gw._invoke_turn_start({}, conn))
    assert ei.value.code == JsonRpcErrorCode.INVALID_PARAMS


def test_turn_rate_disabled_when_zero():
    gw = _gateway(max_turns_per_minute_per_actor=0)
    assert gw._turn_rate_limiter is None

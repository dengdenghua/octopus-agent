"""Dense coverage for realtime_gateway pure logic (audit Q-05)."""

from __future__ import annotations

from types import SimpleNamespace

from runtime.sensing.gateway.realtime_gateway import RealtimeGateway


def _gw(**kw) -> RealtimeGateway:
    kw.setdefault("runtime", SimpleNamespace())
    return RealtimeGateway(**kw)


class _FakeWs:
    def __init__(self, subprotocol: str = ""):
        self.headers = {"sec-websocket-protocol": subprotocol}


def test_accept_subprotocol() -> None:
    assert RealtimeGateway._accept_subprotocol(_FakeWs("bearer, xyz")) == "bearer"
    assert RealtimeGateway._accept_subprotocol(_FakeWs("other, bearer")) == "bearer"
    assert RealtimeGateway._accept_subprotocol(_FakeWs("other")) is None
    assert RealtimeGateway._accept_subprotocol(_FakeWs("")) is None
    assert RealtimeGateway._accept_subprotocol(SimpleNamespace(headers={})) is None


def test_admit_release_connection_cap() -> None:
    gw = _gw(max_connections_per_actor=2)
    assert gw._admit_connection("alice") is True
    assert gw._admit_connection("alice") is True
    assert gw._admit_connection("alice") is False  # at cap
    assert gw._admit_connection("bob") is True
    gw._release_connection("alice")
    gw._release_connection("alice")
    gw._release_connection("alice")  # drops the key
    assert "alice" not in gw._conn_counts
    assert gw._admit_connection("alice") is True

    unlimited = _gw(max_connections_per_actor=0)
    assert unlimited._admit_connection("x") is True
    unlimited._release_connection("x")  # no-op


def test_sanitize_turn_params_approval_bypass() -> None:
    gw = _gw(allow_client_approval_bypass=False)
    conn = SimpleNamespace(actor_id=None, tenant_id=None)
    out = gw._sanitize_turn_params({"approvalPolicy": "never"}, conn)
    assert out["approvalPolicy"] == "on-request"

    gw2 = _gw(allow_client_approval_bypass=True)
    out2 = gw2._sanitize_turn_params({"approvalPolicy": "never"}, conn)
    assert out2["approvalPolicy"] == "never"


def test_sanitize_turn_params_ownership() -> None:
    gw = _gw()
    conn = SimpleNamespace(actor_id="alice", tenant_id="t1")
    out = gw._sanitize_turn_params({"input": []}, conn)
    assert out["tenant_id"] == "t1"
    assert out["owner_actor_id"] == "alice"
    assert out["metadata"]["actor_id"] == "alice"
    assert out["input"][0]["type"] == "metadata"
    assert out["input"][0]["metadata"]["actor_id"] == "alice"

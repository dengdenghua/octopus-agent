"""HTTP layer for the one-click SearXNG: public status + auth-gated control."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import runtime.sensing.gateway.searxng_supervisor as sx
from runtime.platform.ui.health_router import create_health_router
from runtime.platform.ui.searxng_router import create_searxng_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_health_router(state=object()))
    # require_auth defaults to False → the actor dependency is a no-op (single-user dev).
    app.include_router(create_searxng_router())
    return TestClient(app)


def test_status_reports_up(monkeypatch) -> None:
    monkeypatch.setattr(
        sx, "searxng_status", lambda: {"up": True, "heartbeat": True, "docker_present": True}
    )
    resp = _client().get("/api/searxng/status")
    assert resp.status_code == 200
    assert resp.json()["up"] is True


def test_status_never_500s_on_error(monkeypatch) -> None:
    def _boom() -> dict:
        raise RuntimeError("supervisor exploded")

    monkeypatch.setattr(sx, "searxng_status", _boom)
    resp = _client().get("/api/searxng/status")
    assert resp.status_code == 200
    assert resp.json()["up"] is False


def test_enable_invokes_supervisor(monkeypatch) -> None:
    called = {}

    def _fake_enable() -> dict:
        called["enable"] = True
        return {"status": "starting", "up": False}

    monkeypatch.setattr(sx, "enable_searxng", _fake_enable)
    resp = _client().post("/api/searxng/enable")
    assert resp.status_code == 200
    assert resp.json()["status"] == "starting"
    assert called.get("enable") is True


def test_disable_invokes_supervisor(monkeypatch) -> None:
    monkeypatch.setattr(sx, "disable_searxng", lambda: {"status": "stopped", "up": False})
    resp = _client().post("/api/searxng/disable")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"

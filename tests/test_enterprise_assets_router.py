"""数字分身归并 C · 消费侧:agent 列举企业版角色资产(只读、门控、优雅降级)。"""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.sensing.gateway.enterprise_assets_router import (
    create_enterprise_assets_router,
)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_enterprise_assets_router())
    return TestClient(app)


class _FakeResp:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> object:
        return self._payload


def test_unconfigured_available_false(monkeypatch):
    monkeypatch.delenv("OCTOPUS_ENTERPRISE_URL", raising=False)
    body = _client().get("/api/agent-market/enterprise").json()
    assert body["available"] is False
    assert body["items"] == []


def test_list_unwraps_enterprise_envelope(monkeypatch):
    monkeypatch.setenv("OCTOPUS_ENTERPRISE_URL", "http://ent:8000")
    captured: dict = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return _FakeResp(
            {"success": True, "data": [{"id": "a", "name": "A"}], "total": 1}
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    body = _client().get(
        "/api/agent-market/enterprise?category=coder&search=test"
    ).json()
    assert body["available"] is True
    assert body["items"] == [{"id": "a", "name": "A"}]
    assert captured["url"] == "http://ent:8000/api/v1/agent-assets"
    assert captured["params"] == {"category": "coder", "search": "test"}


def test_get_asset_unwraps_body(monkeypatch):
    monkeypatch.setenv("OCTOPUS_ENTERPRISE_URL", "http://ent:8000")

    def fake_get(url, **kwargs):
        return _FakeResp(
            {"success": True, "data": {"id": "a", "name": "A", "body": "soul"}}
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    body = _client().get("/api/agent-market/enterprise/a").json()
    assert body["available"] is True
    assert body["asset"]["body"] == "soul"


def test_network_error_graceful(monkeypatch):
    monkeypatch.setenv("OCTOPUS_ENTERPRISE_URL", "http://ent:8000")

    def fake_get(url, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(httpx, "get", fake_get)
    body = _client().get("/api/agent-market/enterprise").json()
    # 网络错:仍 available(已配),但带 error、items 空——前端不崩。
    assert body["available"] is True
    assert "network down" in (body["error"] or "")
    assert body["items"] == []

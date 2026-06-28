"""MCP OAuth step-2: .well-known discovery + dynamic client registration + /start.

Hermetic — every network call (well-known metadata, registration) is routed
through a fake urlopen keyed by URL substring; nothing hits the network.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib import error as urllib_error

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from runtime.adapters.mcp_client import oauth, oauth_discovery  # noqa: E402
from runtime.platform.ui.app import create_app  # noqa: E402


def _routed_urlopen(routes: dict[str, dict | None]):
    """Fake urlopen: match request URL by substring → JSON payload (None → 404)."""
    class _Resp:
        def __init__(self, payload: dict) -> None:
            self._p = json.dumps(payload).encode()

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *_a: object) -> bool:
            return False

        def read(self) -> bytes:
            return self._p

    def _open(req: object, timeout: float | None = None):
        url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
        for frag, payload in routes.items():
            if frag in url:
                if payload is None:
                    raise urllib_error.HTTPError(url, 404, "not found", {}, None)  # type: ignore[arg-type]
                return _Resp(payload)
        raise urllib_error.URLError("no route")

    return _open


def test_discover_via_protected_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = {
        "/.well-known/oauth-protected-resource": {"authorization_servers": ["https://auth.example"]},
        "/.well-known/oauth-authorization-server": {
            "issuer": "https://auth.example",
            "authorization_endpoint": "https://auth.example/authorize",
            "token_endpoint": "https://auth.example/token",
            "registration_endpoint": "https://auth.example/register",
            "scopes_supported": ["a", "b"],
        },
    }
    monkeypatch.setattr(oauth_discovery.urllib_request, "urlopen", _routed_urlopen(routes))
    ep = oauth_discovery.discover("https://mcp.example/mcp")
    assert ep is not None
    assert ep.authorize_url == "https://auth.example/authorize"
    assert ep.token_url == "https://auth.example/token"
    assert ep.registration_url == "https://auth.example/register"
    assert ep.scopes == ("a", "b")


def test_discover_falls_back_to_origin_as_auth_server(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = {
        "/.well-known/oauth-protected-resource": None,  # 404 → fall back to origin
        "/.well-known/oauth-authorization-server": {
            "authorization_endpoint": "https://mcp.example/authorize",
            "token_endpoint": "https://mcp.example/token",
        },
    }
    monkeypatch.setattr(oauth_discovery.urllib_request, "urlopen", _routed_urlopen(routes))
    ep = oauth_discovery.discover("https://mcp.example/mcp")
    assert ep is not None
    assert ep.authorize_url == "https://mcp.example/authorize"


def test_register_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        oauth_discovery.urllib_request, "urlopen",
        _routed_urlopen({"/register": {"client_id": "CID123"}}),
    )
    cid = oauth_discovery.register_client("https://auth.example/register", redirect_uri="http://cb")
    assert cid == "CID123"


def test_start_discovers_registers_and_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    oauth.reset_oauth_store_for_tests()
    routes = {
        "/.well-known/oauth-protected-resource": {"authorization_servers": ["https://auth.example"]},
        "/.well-known/oauth-authorization-server": {
            "issuer": "https://auth.example",
            "authorization_endpoint": "https://auth.example/authorize",
            "token_endpoint": "https://auth.example/token",
            "registration_endpoint": "https://auth.example/register",
        },
        "/register": {"client_id": "CID123"},
    }
    monkeypatch.setattr(oauth_discovery.urllib_request, "urlopen", _routed_urlopen(routes))

    client = TestClient(create_app())
    r = client.post("/api/mcp-oauth/start", json={"server": "cf", "url": "https://mcp.example/mcp"})
    assert r.status_code == 200
    body = r.json()
    assert "https://auth.example/authorize" in body["authorize_url"]
    assert "client_id=CID123" in body["authorize_url"]
    assert f"state={body['state']}" in body["authorize_url"]
    # the registered client is cached per issuer (no re-registration next time)
    assert oauth.get_oauth_store().get_client("https://auth.example") == "CID123"
    oauth.reset_oauth_store_for_tests()

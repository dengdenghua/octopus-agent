"""MCP OAuth router: authorize (auth-gated) → callback (state-gated) → token.

Hermetic — OCTOPUS_HOME + cwd under tmp_path, token endpoint mocked.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from runtime.adapters.mcp_client import oauth  # noqa: E402
from runtime.platform.ui.app import create_app  # noqa: E402
from runtime.safety.auth.identity import Identity, IdentityStore  # noqa: E402


def _mock_token(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    raw = json.dumps(payload).encode()

    class _Resp:
        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *_a: object) -> bool:
            return False

        def read(self) -> bytes:
            return raw

    monkeypatch.setattr(oauth.urllib_request, "urlopen", lambda *_a, **_k: _Resp())


def test_authorize_then_callback_stores_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    oauth.reset_oauth_store_for_tests()
    client = TestClient(create_app())

    r = client.post("/api/mcp-oauth/authorize", json={
        "server": "cloudflare", "authorize_url": "https://p/auth",
        "token_url": "https://p/token", "client_id": "cid", "scopes": ["x"],
    })
    assert r.status_code == 200
    body = r.json()
    state = body["state"]
    assert f"state={state}" in body["authorize_url"]
    assert "code_challenge_method=S256" in body["authorize_url"]

    _mock_token(monkeypatch, {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})
    cb = client.get(f"/api/mcp-oauth/callback?code=CODE&state={state}")
    assert cb.status_code == 200
    assert "authorized" in cb.text
    assert oauth.get_oauth_store().bearer("cloudflare") == "AT"
    oauth.reset_oauth_store_for_tests()


def test_callback_rejects_unknown_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    oauth.reset_oauth_store_for_tests()
    client = TestClient(create_app())
    cb = client.get("/api/mcp-oauth/callback?code=X&state=bogus")
    assert cb.status_code == 400
    oauth.reset_oauth_store_for_tests()


def test_authorize_auth_gated_callback_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    oauth.reset_oauth_store_for_tests()
    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    client = TestClient(create_app(cocoloop_require_auth=True, cocoloop_identity_store=store))

    payload = {
        "server": "cf", "authorize_url": "https://p/a",
        "token_url": "https://p/t", "client_id": "cid",
    }
    # authorize: operator must be authenticated
    assert client.post("/api/mcp-oauth/authorize", json=payload).status_code == 401
    ok = client.post(
        "/api/mcp-oauth/authorize", json=payload,
        headers={"Authorization": "Bearer sk-alice"},
    )
    assert ok.status_code == 200

    # callback: reachable WITHOUT operator auth even when auth is on (state-gated,
    # because the provider's redirect carries no operator token).
    cb = client.get("/api/mcp-oauth/callback?code=X&state=bogus")
    assert cb.status_code == 400  # 400 (bad state), NOT 401 (auth) → not auth-gated
    oauth.reset_oauth_store_for_tests()

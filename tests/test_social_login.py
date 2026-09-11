from urllib.parse import parse_qs, urlsplit
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.adapters.integrations.social_auth import create_social_auth_router, safe_return_to
from runtime.safety.auth.identity import IdentityStore


def client_for(tmp_path):
    store = IdentityStore()
    app = FastAPI()
    app.include_router(
        create_social_auth_router(
            identity_store=store,
            jwt_secret="Test-secret-123456789012345678901234!",
            data_dir=tmp_path,
        )
    )
    return TestClient(app), store


def test_disabled_provider_and_return_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("ECHO_GOOGLE_CLIENT_ID", raising=False)
    client, _ = client_for(tmp_path)
    assert client.get("/api/auth/social/google/start").status_code == 503
    for path in ["//evil.test", "https://evil.test", "/\\evil", "/\nunsafe"]:
        assert safe_return_to(path) == "/workspace/realtime/new"


def test_callback_requires_same_browser_and_is_one_time(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_GOOGLE_CLIENT_ID", "test-id")
    monkeypatch.setenv("ECHO_GOOGLE_CLIENT_SECRET", "test-secret")
    client, _ = client_for(tmp_path)
    response = client.get(
        "/api/auth/social/google/start?return_to=//evil.test", follow_redirects=False
    )
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert "test-secret" not in response.headers["location"]
    callback = (
        "/api/auth/social/google/callback?state=" + query["state"][0] + "&error=access_denied"
    )
    cookie = client.cookies.get("echo_oauth_flow")
    client.cookies.clear()
    assert client.get(callback).status_code == 400
    client.cookies.set("echo_oauth_flow", cookie)
    response = client.get(callback, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("http://localhost:3310/#/login?")
    assert client.get(callback).status_code == 400


@pytest.mark.parametrize("provider", ["google", "github"])
@pytest.mark.parametrize("verified", [True, False])
def test_verified_signin_sets_cookie_and_persists_identity(
    tmp_path, monkeypatch, provider, verified
):
    monkeypatch.setenv(f"ECHO_{provider.upper()}_CLIENT_ID", "test-id")
    monkeypatch.setenv(f"ECHO_{provider.upper()}_CLIENT_SECRET", "test-secret")

    class Reply:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class HTTP:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            assert kwargs["data"]["code_verifier"]
            return Reply({"access_token": "provider-secret"})

        async def get(self, url, **kwargs):
            if url.endswith("/emails"):
                return Reply([{"email": "test@example.com", "primary": True, "verified": verified}])
            return Reply(
                {
                    "sub": "stable-subject",
                    "id": "stable-subject",
                    "email": "test@example.com",
                    "email_verified": verified,
                    "name": "Test",
                }
            )

    monkeypatch.setattr("runtime.adapters.integrations.social_auth.httpx.AsyncClient", HTTP)
    client, store = client_for(tmp_path)
    response = client.get(f"/api/auth/social/{provider}/start", follow_redirects=False)
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    response = client.get(
        f"/api/auth/social/{provider}/callback?state={state}&code=test", follow_redirects=False
    )
    assert response.status_code == 303
    if not verified:
        assert "social_error=" in response.headers["location"]
        return
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "provider-secret" not in str(response.headers)
    _, restored = client_for(tmp_path)
    import hashlib

    actor = provider + ":" + hashlib.sha256(b"stable-subject").hexdigest()[:32]
    assert store.get(actor) is not None
    assert restored.get(actor) is not None

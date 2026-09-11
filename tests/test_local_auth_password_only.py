import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.adapters.integrations.local_auth.config import LocalAuthConfig, hash_password
from runtime.adapters.integrations.local_auth.router import create_local_auth_router


@pytest.mark.parametrize(
    "environment,mode,host,origin,password,status",
    [
        ("development", "local", "127.0.0.1", "http://localhost:4173", "test-pin", 200),
        ("development", "local", "127.0.0.1", "http://localhost:4173", "wrong", 401),
        ("production", "local", "127.0.0.1", None, "test-pin", 503),
        ("development", "shared", "127.0.0.1", None, "test-pin", 503),
        ("development", "local", "192.0.2.1", None, "test-pin", 403),
        ("development", "local", "127.0.0.1", "https://example.com", "test-pin", 403),
    ],
)
def test_password_only_login_boundaries(monkeypatch, environment, mode, host, origin, password, status):
    monkeypatch.setenv("ECHO_ENV", environment)
    monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", mode)
    config = LocalAuthConfig(
        enabled=True, users={"owner": hash_password("test-pin")}, password_only_username="owner"
    )
    app = FastAPI()
    app.include_router(create_local_auth_router(config=config))
    with TestClient(app, client=(host, 50000)) as client:
        response = client.post(
            "/api/auth/local/login",
            json={"username": "owner", "password": password},
            headers={"Origin": origin} if origin else {},
        )
    assert response.status_code == status


def test_password_only_requires_hashed_account():
    with pytest.raises(ValueError, match="configured password hash"):
        LocalAuthConfig(enabled=True, allow_any_username=True, password_only_username="owner")


def test_config_loader_preserves_bcrypt_salt(monkeypatch):
    from runtime.platform.config.loader import _interpolate_env

    encoded = "bcrypt:$2b$12$ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyza"
    monkeypatch.setenv("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "must-not-replace")
    assert _interpolate_env(encoded) == encoded

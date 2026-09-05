"""Explicit local administrators; ordinary login cannot self-assign a role."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.adapters.integrations.local_auth.router import create_local_auth_router
from runtime.platform.config.schema import LocalAuthConfig
from runtime.safety.auth.identity import IdentityStore
from runtime.sensing.gateway.agent_world_router import create_agent_world_router


def test_only_configured_local_owner_passes_real_cloud_install_role_gate(monkeypatch):
    import runtime.platform.plugins.cloud_catalog as catalog_module

    calls = []

    class Catalog:
        def __init__(self, kind):
            pass

        def items(self):
            return [{"id": "example", "kind": "plugin", "plugin": "example"}]

        def install_plugin(self, name, **kwargs):
            calls.append(name)
            return {"installed": True, "name": name}

    monkeypatch.setattr(catalog_module, "CloudCatalog", Catalog)
    monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "local")
    config = LocalAuthConfig(
        enabled=True,
        allow_any_username=True,
        admin_usernames=["owner"],
        jwt_secret="Test-Local-Admin-Secret-Has-Entropy-123456!",
    )
    identities = IdentityStore()
    app = FastAPI()
    app.include_router(create_local_auth_router(config=config, identity_store=identities))
    app.include_router(
        create_agent_world_router(
            identity_store=identities,
            require_auth=True,
            jwt_secret=config.jwt_secret,
            jwt_issuer=config.jwt_issuer,
        )
    )
    with TestClient(app) as client:
        for username, status in [("guest", 403), ("owner", 200), ("OWNER", 403)]:
            login = client.post(
                "/api/auth/local/login",
                json={"username": username, "roles": ["admin"], "admin_usernames": [username]},
            )
            assert login.status_code == 200
            token = login.json()["access_token"]
            response = client.post(
                "/api/agent-market/cloud/plugins/example/install",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == status, response.text
    assert calls == ["example"]
    assert identities.get("local:guest").roles == ("user", "local")
    assert identities.get("local:owner").roles == ("user", "local", "admin")


def test_admin_allowlist_does_not_bypass_login_allowlist():
    identities = IdentityStore()
    config = LocalAuthConfig(enabled=True, allowed_usernames=["guest"], admin_usernames=["owner"])
    app = FastAPI()
    app.include_router(create_local_auth_router(config=config, identity_store=identities))
    with TestClient(app) as client:
        assert client.post("/api/auth/local/login", json={"username": "owner"}).status_code == 403
    assert identities.get("local:owner") is None

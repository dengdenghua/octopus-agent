from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.safety.auth import Identity, IdentityStore
from runtime.sensing.gateway.plugin_hub_router import create_plugin_hub_router


class _FakeHub:
    def list_plugins(self):
        return []

    def discover(self):
        return []

    def load(self, _name: str):
        return True

    def start(self, _name: str):
        return True

    def stop(self, _name: str):
        return True

    def unload(self, _name: str):
        return True

    def get_plugin_config(self, _name: str):
        return {}

    def update_plugin_config(self, _name: str, _body):
        return True


def test_plugin_hub_router_requires_auth_when_enabled() -> None:
    store = IdentityStore()
    store.add(Identity(actor_id="alice", roles=("operator",)), api_key_plaintext="sk-alice")
    app = FastAPI()
    app.include_router(
        create_plugin_hub_router(
            hub=_FakeHub(),
            identity_store=store,
            require_auth=True,
        )
    )
    client = TestClient(app)

    assert client.get("/api/plugin-hub/plugins").status_code == 401
    assert (
        client.get(
            "/api/plugin-hub/plugins",
            headers={"Authorization": "Bearer sk-alice"},
        ).status_code
        == 200
    )


def test_plugin_hub_mutation_requires_operator_role() -> None:
    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    app = FastAPI()
    app.include_router(
        create_plugin_hub_router(
            hub=_FakeHub(),
            identity_store=store,
            require_auth=True,
        )
    )
    client = TestClient(app)

    response = client.post(
        "/api/plugin-hub/plugins/demo/load",
        headers={"Authorization": "Bearer sk-alice"},
    )
    assert response.status_code == 403

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.platform.capabilities.capability_registry import CapabilityRegistry
from runtime.platform.capabilities.permission_grants import CapabilityPermissionStore
from runtime.platform.connectors.auth_orchestrator import AuthOrchestrator
from runtime.platform.connectors.connector_registry import ConnectorRegistry
from runtime.platform.connectors.credential_store import CredentialStore
from runtime.platform.models.model_provider_plugin import (
    ModelProviderPluginManager,
    model_provider_entry_has_key,
    model_provider_responses_models,
    resolve_model_provider_api_key,
)
from runtime.safety.auth import Identity, IdentityStore
from runtime.sensing.gateway.capability_router import create_capability_router
from runtime.sensing.gateway.config_router import create_config_router


class _Credentials:
    def __init__(self) -> None:
        self.values = {
            "opencode-zen": {"api_key": "zen-secret"},
            "freebuff2api-community": {
                "api_key": "sk-fb-secret",
                "base_url": "https://gateway.example/v1",
            },
        }

    def get_secret(self, connector_id: str, key: str) -> str | None:
        return self.values.get(connector_id, {}).get(key)

    def list_secrets(self, connector_id: str) -> list[str]:
        return list(self.values.get(connector_id, {}))


def _item() -> dict[str, Any]:
    return {
        "id": "opencode-zen",
        "name": "OpenCode Zen Models",
        "name_zh": "OpenCode Zen 模型适配器",
        "model_provider": {
            "entry_id": "opencode-zen",
            "display_name": "OpenCode Zen",
            "display_name_zh": "OpenCode Zen 免费模型",
            "base_url": "https://opencode.ai/zen/v1",
            "models_endpoint": "https://opencode.ai/zen/v1/models",
            "free_models": [
                "big-pickle",
                "muse-spark-1.2-contributor-free",
                "mimo-v2.5-free",
            ],
            "excluded_models": [],
            "responses_models": ["muse-spark-1.2-contributor-free"],
            "responses_model_prefixes": ["muse-spark-"],
            "compat_profile": "opencode_zen",
            "supports_tool_use": True,
            "models_are_free": True,
        },
    }


def test_credential_reference_resolves_without_persisting_secret() -> None:
    entry = {
        "credential_ref": "connector:opencode-zen:api_key",
        "api_key": "",
    }
    credentials = _Credentials()

    assert resolve_model_provider_api_key(entry, credential_store=credentials) == "zen-secret"
    assert model_provider_entry_has_key(entry, credential_store=credentials) is True
    assert "zen-secret" not in repr(entry)


def test_one_opencode_plugin_owns_both_channels_and_removes_both():
    state = {}
    manager = ModelProviderPluginManager(
        custom_models=state, lock=threading.RLock(), save=lambda *ids: None,
        unregister_entry=lambda *args, **kwargs: True,
        rebuild_routes=lambda: {key: {"ok": True} for key in state},
        credential_store=_Credentials(),
    )
    item = _item()
    item["model_provider"]["channels"] = {"opencode-go": {
        "entry_id": "opencode-go", "display_name": "OpenCode Go",
        "base_url": "https://opencode.ai/zen/go/v1", "models_are_free": False,
    }}
    manager.configure(item, models=["big-pickle"], channels={"opencode-go": ["glm-5.3"]})
    assert set(state) == {"opencode-zen", "opencode-go"}
    assert state["opencode-go"]["managed_by_plugin"] == "opencode-zen"
    assert state["opencode-go"]["credential_ref"] == state["opencode-zen"]["credential_ref"]
    assert state["opencode-go"]["is_free"] is False
    manager.remove(item)
    assert state == {}


def test_validate_discovers_only_current_free_models(monkeypatch) -> None:
    class _Response:
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                "data": [
                    {"id": "big-pickle"},
                    {"id": "mimo-v2.5-free"},
                    {"id": "kimi-k3"},
                    {"id": "future-coder-free"},
                    {"id": "muse-spark-1.2-contributor-free"},
                ]
            }

    monkeypatch.setattr(httpx, "get", lambda *_args, **_kwargs: _Response())
    manager = ModelProviderPluginManager(
        custom_models={},
        lock=threading.RLock(),
        save=lambda *_ids: None,
        unregister_entry=lambda *_args, **_kwargs: False,
        rebuild_routes=lambda: {},
        credential_store=_Credentials(),
    )

    result = manager.validate(_item(), tokens={"api_key": "zen-secret"})

    assert result["models"] == [
        "big-pickle",
        "muse-spark-1.2-contributor-free",
        "mimo-v2.5-free",
        "future-coder-free",
    ]
    assert "kimi-k3" not in result["models"]


def test_community_provider_discovers_all_models_and_uses_custom_base_url(monkeypatch) -> None:
    requested: list[str] = []

    class _Response:
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, Any]:
            return {"data": [{"id": "freebuff/model-a"}, {"id": "vendor/model-b"}]}

    def fake_get(url: str, **_kwargs: Any) -> _Response:
        requested.append(url)
        return _Response()

    monkeypatch.setattr(httpx, "get", fake_get)
    manager = ModelProviderPluginManager(
        custom_models={},
        lock=threading.RLock(),
        save=lambda *_ids: None,
        unregister_entry=lambda *_args, **_kwargs: False,
        rebuild_routes=lambda: {},
        credential_store=_Credentials(),
    )
    item = {
        "id": "freebuff2api-community",
        "name_zh": "Freebuff2API 社区适配器",
        "model_provider": {
            "entry_id": "freebuff2api-community",
            "display_name_zh": "Freebuff2API 社区适配器",
            "base_url": "https://open.freebuff.app/v1",
            "configurable_base_url": True,
            "discover_all_models": True,
            "free_models": [],
        },
    }

    result = manager.validate(item, tokens=None)

    assert requested == ["https://gateway.example/v1/models"]
    assert result["models"] == ["freebuff/model-a", "vendor/model-b"]
    assert result["base_url"] == "https://gateway.example/v1"


def test_configurable_provider_rejects_insecure_remote_http() -> None:
    manager = ModelProviderPluginManager(
        custom_models={},
        lock=threading.RLock(),
        save=lambda *_ids: None,
        unregister_entry=lambda *_args, **_kwargs: False,
        rebuild_routes=lambda: {},
        credential_store=_Credentials(),
    )
    item = {
        "id": "freebuff2api-community",
        "name_zh": "Freebuff2API 社区适配器",
        "model_provider": {
            "entry_id": "freebuff2api-community",
            "base_url": "https://open.freebuff.app/v1",
            "configurable_base_url": True,
        },
    }

    try:
        manager.validate(
            item,
            tokens={"api_key": "sk-fb-secret", "base_url": "http://remote.example/v1"},
        )
    except ValueError as exc:
        assert "必须使用 HTTPS" in str(exc)
    else:  # pragma: no cover - documents the security boundary
        raise AssertionError("insecure remote URL should be rejected")


def test_configure_and_remove_hot_model_routes() -> None:
    state: dict[str, dict[str, Any]] = {}
    saved: list[str] = []
    unregistered: list[str] = []

    def unregister(entry: dict[str, Any], *, fallback_id: str = "") -> bool:
        unregistered.append(str(entry.get("id") or fallback_id))
        return True

    def rebuild() -> dict[str, dict[str, Any]]:
        return {model_id: {"ok": True, "model_id": model_id} for model_id in state}

    manager = ModelProviderPluginManager(
        custom_models=state,
        lock=threading.RLock(),
        save=lambda *ids: saved.extend(ids),
        unregister_entry=unregister,
        rebuild_routes=rebuild,
        credential_store=_Credentials(),
    )

    configured = manager.configure(
        _item(),
        models=["big-pickle", "muse-spark-1.2-contributor-free", "muse-spark-1.3-contributor-free"],
    )

    assert configured == {
        "configured": True,
        "entry_id": "opencode-zen",
        "models": [
            "big-pickle",
            "muse-spark-1.2-contributor-free",
            "muse-spark-1.3-contributor-free",
        ],
    }
    entry = state["opencode-zen"]
    assert entry["api_key"] == ""
    assert entry["credential_ref"] == "connector:opencode-zen:api_key"
    assert entry["supports_tool_use"] is True
    assert entry["is_free"] is True
    assert entry["responses_models"] == [
        "muse-spark-1.2-contributor-free",
        "muse-spark-1.3-contributor-free",
    ]
    assert "zen-secret" not in repr(entry)

    removed = manager.remove(_item())

    assert removed == {"removed": True, "entry_id": "opencode-zen"}
    assert state == {}
    assert unregistered == ["opencode-zen"]
    assert saved == ["opencode-zen", "opencode-zen"]


@pytest.mark.parametrize(
    ("overrides", "uses_responses"),
    [
        ({}, True),
        ({"base_url": "https://relay.example/v1"}, False),
        ({"managed_by_plugin": "other-provider"}, False),
        ({"responses_model_prefixes": []}, False),
    ],
)
def test_legacy_zen_protocol_repair_is_scoped_to_provider(overrides, uses_responses) -> None:
    model = "muse-spark-1.3-contributor-free"
    entry = {
        "managed_by_plugin": "opencode-zen",
        "base_url": "https://opencode.ai/zen/v1",
        "responses_models": ["muse-spark-1.2-contributor-free"],
        **overrides,
    }
    resolved = model_provider_responses_models(entry, [model, "big-pickle"])
    assert resolved == ([model] if uses_responses else [])


def test_restart_routes_discovered_muse_through_responses(tmp_path, monkeypatch) -> None:
    from runtime.platform.capabilities.tenant_context import use_capability_scope
    from runtime.platform.models.llm import (
        LLMResponseFormatError,
        ModelRequest,
        ModelResponse,
        ModelStreamEvent,
    )
    from runtime.safety.auth.scope import TenantScope
    from runtime.sensing.model_router.openai_responses_router import OpenAIResponsesModelRouter
    from runtime.sensing.model_router.openai_router import OpenAIModelRouter

    model = "muse-spark-1.3-contributor-free"
    entry = {
        "id": "opencode-zen",
        "managed_by_plugin": "opencode-zen",
        "provider": "openai-compatible",
        "base_url": "https://opencode.ai/zen/v1",
        "credential_ref": "connector:opencode-zen:api_key",
        "models": [model, "big-pickle"],
        "responses_models": ["muse-spark-1.2-contributor-free"],
    }
    path = tmp_path / "custom-models.json"
    path.write_text(json.dumps({"opencode-zen": entry}), encoding="utf-8")
    credentials = CredentialStore(root=tmp_path / "credentials")
    scopes = [TenantScope(tenant_id="tenant-a", actor_id=name) for name in ("alice", "bob")]
    for scope in scopes:
        with use_capability_scope(scope):
            credentials.set_secret("opencode-zen", "api_key", f"test-key-{scope.actor_id}")
    routes = {}
    dispatcher = SimpleNamespace(register=lambda key, router: routes.__setitem__(key, router))
    create_config_router(
        stack=SimpleNamespace(planner=SimpleNamespace(router=dispatcher)),
        custom_models_path=path,
        credential_store=credentials,
    )
    monkeypatch.setattr(
        OpenAIResponsesModelRouter,
        "call",
        lambda router, _: ModelResponse(text=f"responses:{router._api_key}"),
    )
    monkeypatch.setattr(
        OpenAIModelRouter,
        "call",
        lambda router, _: ModelResponse(text=f"chat_completions:{router.api_key}"),
    )
    for cls in (OpenAIModelRouter, OpenAIResponsesModelRouter):
        monkeypatch.setattr(
            cls,
            "call_stream",
            lambda router, request: iter(
                [ModelStreamEvent(type="done", final=router.call(request))]
            ),
        )
    for selected, expected in [(model, "responses"), ("big-pickle", "chat_completions")]:
        request = ModelRequest(model=selected, messages=[{"role": "user", "content": "OK"}])
        for scope in [*scopes, scopes[0]]:
            with use_capability_scope(scope):
                response = routes[selected].call(request)
                assert response.text == f"{expected}:test-key-{scope.actor_id}"
                streamed = list(routes[selected].call_stream(request))
                assert streamed[-1].final == response
        with use_capability_scope(TenantScope(tenant_id="tenant-b", actor_id="alice")):
            with pytest.raises(LLMResponseFormatError, match="尚未连接"):
                routes[selected].call(request)
            with pytest.raises(LLMResponseFormatError, match="尚未连接"):
                list(routes[selected].call_stream(request))


def test_plugin_connect_hot_registers_and_disconnect_removes_routes(
    tmp_path,
    monkeypatch,
) -> None:
    class _Response:
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, Any]:
            return {"data": [{"id": "big-pickle"}, {"id": "mimo-v2.5-free"}]}

    class _Dispatcher:
        def __init__(self) -> None:
            self.routes: dict[str, Any] = {}

        def register(self, model_id: str, router: Any) -> None:
            self.routes[model_id] = router

        def unregister(self, model_id: str) -> bool:
            return self.routes.pop(model_id, None) is not None

    class _Planner:
        def __init__(self, router: Any) -> None:
            self.router = router

    class _Stack:
        def __init__(self, router: Any) -> None:
            self.planner = _Planner(router)

    monkeypatch.setattr(httpx, "get", lambda *_args, **_kwargs: _Response())
    credentials = CredentialStore(root=tmp_path / "credentials")
    connector_registry = ConnectorRegistry(
        marketplace_root=(
            Path(__file__).resolve().parents[1] / "extensions" / "workbuddy-connectors"
        ),
        skills_root=tmp_path / "skills",
        state_file=tmp_path / "connectors.json",
    )
    permission_store = CapabilityPermissionStore(tmp_path / "permission-grants.json")
    capability_registry = CapabilityRegistry(
        connector_registry=connector_registry,
        auth_orchestrator=AuthOrchestrator(credentials=credentials),
        codex_cache=tmp_path / "codex-plugins",
        capability_state_file=tmp_path / "capabilities.json",
        skills_root=tmp_path / "skills",
        permission_store=permission_store,
    )
    dispatcher = _Dispatcher()
    config = create_config_router(
        stack=_Stack(dispatcher),
        custom_models_path=tmp_path / "custom-models.json",
        credential_store=credentials,
    )
    app = FastAPI()
    app.include_router(config.router)
    identities = IdentityStore()
    identities.add(
        Identity(actor_id="oct:user@example.com", roles=("user", "oct")),
        api_key_plaintext="sk-user",
    )
    app.include_router(
        create_capability_router(
            registry=capability_registry,
            model_provider_plugins=config.model_provider_plugins,
            identity_store=identities,
            require_auth=True,
            allow_local_user_plugin_lifecycle=True,
        )
    )
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer sk-user"})

    installed = client.post("/api/capabilities/opencode-zen/install")
    assert installed.status_code == 200
    connected = client.post(
        "/api/capabilities/opencode-zen/connect",
        json={
            "tokens": {"api_key": "zen-secret"},
            "grant_permissions": ["account.credentials", "network.remote"],
        },
    )

    assert connected.status_code == 200
    assert connected.json()["model_provider"]["models"] == [
        "big-pickle",
        "mimo-v2.5-free",
    ]
    persisted = (tmp_path / "custom-models.json").read_text(encoding="utf-8")
    assert "zen-secret" not in persisted
    assert "connector:opencode-zen:api_key" in persisted
    assert "opencode-zen" in dispatcher.routes
    assert "big-pickle" in dispatcher.routes
    listed = client.get("/api/config/custom-models").json()["models"][0]
    assert listed["has_api_key"] is True
    assert "credential_ref" not in listed

    disabled = client.post("/api/capabilities/opencode-zen/disable")
    assert disabled.status_code == 200
    assert config.custom_models == {}

    enabled = client.post("/api/capabilities/opencode-zen/enable")
    assert enabled.status_code == 200
    assert config.custom_models["opencode-zen"]["models"] == [
        "big-pickle",
        "mimo-v2.5-free",
    ]

    disconnected = client.post("/api/capabilities/opencode-zen/disconnect")

    assert disconnected.status_code == 200
    assert config.custom_models == {}
    assert "opencode-zen" not in dispatcher.routes


def test_zen_discovers_paid_models_after_free_and_preserves_per_model_pricing(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"data": [{"id": "paid-model"}, {"id": "big-pickle"}, {"id": "new-free"}]}
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: Response())
    item = _item()
    item["model_provider"].update(discover_all_models=True, models_are_free=False)
    state = {}
    manager = ModelProviderPluginManager(custom_models=state, lock=threading.RLock(),
        save=lambda *args: None, unregister_entry=lambda *args, **kwargs: False,
        rebuild_routes=lambda: {"opencode-zen": {"ok": True}}, credential_store=_Credentials())
    discovered = manager.validate(item, tokens={"api_key": "zen-secret"})
    assert discovered["models"] == ["big-pickle", "new-free", "paid-model"]
    manager.configure(item, models=discovered["models"])
    assert state["opencode-zen"]["model_free_status"] == {"big-pickle": True, "new-free": True, "paid-model": False}
    assert state["opencode-zen"]["is_free"] is False

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.core.cerebrum.capability_router import (
    activate_capabilities,
    order_skill_names,
)
from runtime.platform.capabilities.capability_registry import CapabilityRegistry
from runtime.safety.auth import Identity, IdentityStore
from runtime.sensing.gateway.capability_router import create_capability_router


class _FakeRegistry:
    def __init__(self, names: list[str]):
        self._names = set(names)

    def has(self, name: str) -> bool:
        return name in self._names

    def is_enabled(self, name: str) -> bool:  # noqa: ARG002
        return True


def test_research_goal_activates_research_tools() -> None:
    reg = _FakeRegistry(
        [
            "web_search",
            "fetch_url",
            "deep-research",
            "report-writing",
            "query_skill",
        ]
    )

    activation = activate_capabilities(
        "调研一个值得进入的细分赛道，输出竞品格局和风险",
        registry=reg,
    )

    assert "research" in activation.labels
    assert "web_search" in activation.priority_skills
    assert "deep-research" in activation.priority_skills
    assert "query_skill" in activation.priority_skills
    assert activation.render_prompt()


def test_order_skill_names_keeps_edge_distance_relevant_tools_first() -> None:
    names = [
        "filler_a",
        "filler_b",
        "web_search",
        "deep-research",
        "query_skill",
    ]
    activation = activate_capabilities(
        "market research with sources",
        registry=_FakeRegistry(names),
    )

    ordered = order_skill_names(names, activation=activation)

    assert ordered[:3] == ["query_skill", "web_search", "deep-research"]


def test_code_ui_regression_excludes_desktop_bridge_from_activation() -> None:
    names = [
        "live_browser_navigate",
        "live_browser_type",
        "browser_navigate",
        "browser_state",
        "browser_type",
        "browser_click",
        "browser_extract",
        "browser_wait",
    ]
    activation = activate_capabilities(
        "verify the frontend regression at localhost",
        user_context={
            "mode": "code",
            "browser_regression_enabled": True,
            "browser_regression_preview_url": "http://127.0.0.1:4321/index.html",
        },
        registry=_FakeRegistry(names),
    )

    assert "code-ui-regression" in activation.labels
    assert activation.priority_skills[:6] == (
        "browser_navigate",
        "browser_state",
        "browser_type",
        "browser_click",
        "browser_extract",
        "browser_wait",
    )
    assert not any(name.startswith("live_browser_") for name in activation.priority_skills)


class _FakeConnectorRegistry:
    def __init__(self) -> None:
        self.connector = object()

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "cli-one",
                "name": "CLI One",
                "type": "cli",
                "auth_mode": "token",
                "has_cli_auth": True,
                "installed": True,
                "enabled": False,
            }
        ]

    def get(self, connector_id: str) -> object | None:
        return self.connector if connector_id == "cli-one" else None


class _FakeAuthOrchestrator:
    def __init__(self) -> None:
        self.status_calls: list[object] = []
        self.cancel_calls: list[tuple[object, str]] = []

    def device_flow_status(self, connector: object) -> dict[str, Any]:
        self.status_calls.append(connector)
        return {
            "connector_id": "cli-one",
            "active": True,
            "device_flow": {
                "flow_id": "flow-a",
                "connector_id": "cli-one",
                "verification_uri": "https://example.test/device",
                "user_code": "ABCD-EFGH",
                "expires_in": 240,
                "code_embedded_in_uri": False,
            },
        }

    def cancel_device_flow(
        self,
        connector: object,
        *,
        expected_flow_id: str,
    ) -> dict[str, Any]:
        self.cancel_calls.append((connector, expected_flow_id))
        return {"cancelled": True, "connector_id": "cli-one"}


def _write_codex_plugin(cache: Path, plugin_id: str) -> None:
    manifest = cache / plugin_id / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"name": plugin_id, "version": "1.0.0"}),
        encoding="utf-8",
    )


def test_registry_delegates_unified_device_flow_status_and_idempotent_cancel(
    tmp_path: Path,
) -> None:
    connector_registry = _FakeConnectorRegistry()
    auth = _FakeAuthOrchestrator()
    codex_cache = tmp_path / "codex-plugins"
    codex_cache.mkdir()
    registry = CapabilityRegistry(
        connector_registry=connector_registry,
        auth_orchestrator=auth,
        codex_cache=codex_cache,
        capability_state_file=tmp_path / "capabilities.json",
        skills_root=tmp_path / "skills",
    )

    status = registry.device_flow_status("cli-one")
    first_cancel = registry.cancel_device_flow("cli-one", expected_flow_id="flow-a")
    second_cancel = registry.cancel_device_flow("cli-one", expected_flow_id="flow-a")

    assert status["device_flow"]["user_code"] == "ABCD-EFGH"
    assert (
        first_cancel
        == second_cancel
        == {
            "cancelled": True,
            "connector_id": "cli-one",
        }
    )
    assert auth.status_calls == [connector_registry.connector]
    assert auth.cancel_calls == [
        (connector_registry.connector, "flow-a"),
        (connector_registry.connector, "flow-a"),
    ]


def test_connector_capabilities_expose_native_brand_icons(tmp_path: Path) -> None:
    workbuddy_root = tmp_path / "workbuddy"
    workbuddy_icon = workbuddy_root / "linear-mcp.png"
    workbuddy_icon.parent.mkdir(parents=True)
    workbuddy_icon.write_bytes(b"workbuddy-original")
    native_root = tmp_path / "native"
    icon = native_root / "linear" / "assets" / "linear-icon.svg"
    icon.parent.mkdir(parents=True)
    icon.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    registry = CapabilityRegistry(
        connector_registry=_FakeConnectorRegistry(),
        auth_orchestrator=_FakeAuthOrchestrator(),
        codex_cache=tmp_path / "codex",
        capability_state_file=tmp_path / "capabilities.json",
        skills_root=tmp_path / "skills",
        workbuddy_icon_root=workbuddy_root,
        native_icon_root=native_root,
        storefront_icon_root=tmp_path / "fallback",
    )
    # The fake id has no matching asset and therefore remains iconless.
    assert registry.list()[0].get("icon") is None

    connector_registry = _FakeConnectorRegistry()
    connector_registry.list = lambda: [
        {
            "id": "linear-mcp",
            "name": "Linear",
            "type": "mcp",
            "auth_mode": "oauth",
            "provider_id": "linear",
            "installed": False,
            "enabled": False,
        }
    ]
    registry = CapabilityRegistry(
        connector_registry=connector_registry,
        auth_orchestrator=_FakeAuthOrchestrator(),
        codex_cache=tmp_path / "codex",
        capability_state_file=tmp_path / "capabilities.json",
        skills_root=tmp_path / "skills",
        workbuddy_icon_root=workbuddy_root,
        native_icon_root=native_root,
        storefront_icon_root=tmp_path / "fallback",
    )

    assert registry.list()[0]["icon"].startswith("/api/capabilities/linear-mcp/icon?v=")
    assert registry.icon_path("linear-mcp") == workbuddy_icon

    workbuddy_icon.unlink()
    assert registry.icon_path("linear-mcp") == icon


def test_codex_plugin_state_preserves_parallel_registry_updates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache = tmp_path / "codex-plugins"
    _write_codex_plugin(cache, "plugin-a")
    _write_codex_plugin(cache, "plugin-b")
    state_file = tmp_path / "capabilities.json"
    skills_root = tmp_path / "skills"
    first = CapabilityRegistry(
        connector_registry=_FakeConnectorRegistry(),
        auth_orchestrator=_FakeAuthOrchestrator(),
        codex_cache=cache,
        capability_state_file=state_file,
        skills_root=skills_root,
    )
    second = CapabilityRegistry(
        connector_registry=_FakeConnectorRegistry(),
        auth_orchestrator=_FakeAuthOrchestrator(),
        codex_cache=cache,
        capability_state_file=state_file,
        skills_root=skills_root,
    )
    assert first.install("plugin-a")["installed"] is True

    install_barrier = threading.Barrier(2)
    first_mutate = first._mutate_state
    second_mutate = second._mutate_state

    def first_install_gated(mutate):
        install_barrier.wait(timeout=2)
        return first_mutate(mutate)

    def second_install_gated(mutate):
        install_barrier.wait(timeout=2)
        return second_mutate(mutate)

    monkeypatch.setattr(first, "_mutate_state", first_install_gated)
    monkeypatch.setattr(second, "_mutate_state", second_install_gated)
    parse_errors: list[Exception] = []
    stop_reader = threading.Event()
    reader_ready = threading.Event()

    def observe_json() -> None:
        while not stop_reader.wait(0.0005):
            try:
                json.loads(state_file.read_text(encoding="utf-8"))
                reader_ready.set()
            except Exception as exc:  # pragma: no cover - regression evidence
                parse_errors.append(exc)
                return

    reader = threading.Thread(target=observe_json)
    reader.start()
    try:
        assert reader_ready.wait(timeout=1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            removed = executor.submit(first.uninstall, "plugin-a")
            installed = executor.submit(second.install, "plugin-b")
            assert removed.result(timeout=3) is True
            assert installed.result(timeout=3)["installed"] is True
    finally:
        stop_reader.set()
        reader.join(timeout=2)

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert not parse_errors
    assert "plugin-a" not in state
    assert state["plugin-b"]["installed"] is True

    monkeypatch.setattr(first, "_mutate_state", first_mutate)
    monkeypatch.setattr(second, "_mutate_state", second_mutate)
    assert first.install("plugin-a")["installed"] is True
    assert second.set_enabled("plugin-b", True) is True

    enabled_barrier = threading.Barrier(2)

    def first_enabled_gated(mutate):
        enabled_barrier.wait(timeout=2)
        return first_mutate(mutate)

    def second_enabled_gated(mutate):
        enabled_barrier.wait(timeout=2)
        return second_mutate(mutate)

    monkeypatch.setattr(first, "_mutate_state", first_enabled_gated)
    monkeypatch.setattr(second, "_mutate_state", second_enabled_gated)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        updates = [
            executor.submit(first.set_enabled, "plugin-a", True),
            executor.submit(second.set_enabled, "plugin-b", False),
        ]
        assert [future.result(timeout=3) for future in updates] == [True, True]

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["plugin-a"]["enabled"] is True
    assert state["plugin-b"]["enabled"] is False


class _FakeCapabilityRegistry:
    def __init__(self) -> None:
        self.status_calls: list[str] = []
        self.cancel_calls: list[tuple[str, str]] = []
        self.install_calls: list[str] = []
        self.uninstall_calls: list[str] = []
        self.items = {
            "cli-one": {"id": "cli-one", "source": "connector", "type": "cli"},
            "plugin-one": {
                "id": "plugin-one",
                "source": "codex_plugin",
                "type": "plugin",
            },
        }

    def get(self, capability_id: str) -> dict[str, Any] | None:
        return self.items.get(capability_id)

    def list(self) -> list[dict[str, Any]]:
        return list(self.items.values())

    def install(self, capability_id: str) -> dict[str, Any]:
        self.install_calls.append(capability_id)
        return {"installed": True, "capability_id": capability_id}

    def uninstall(self, capability_id: str) -> bool:
        self.uninstall_calls.append(capability_id)
        return True

    def install_plan(self, capability_id: str) -> dict[str, Any]:
        if capability_id not in self.items:
            raise KeyError(capability_id)
        return {
            "schema": "octopus.capability_install_plan.v1",
            "capability_id": capability_id,
            "permissions": list(self.items[capability_id].get("permissions") or []),
            "can_install": True,
            "blockers": [],
            "plan_id": f"plan:{capability_id}",
        }

    @staticmethod
    def grant_permissions(capability_id: str, permissions: Any) -> dict[str, Any]:
        return {"id": capability_id, "granted": list(permissions or [])}

    @staticmethod
    def require_permissions(
        capability_id: str,
        permissions: Any = (),
        *,
        require_active: bool = False,
    ) -> dict[str, Any]:
        del permissions, require_active
        return {"id": capability_id, "installed": True}

    @staticmethod
    def _public(item: dict[str, Any]) -> dict[str, Any]:
        return dict(item)

    def device_flow_status(self, capability_id: str) -> dict[str, Any]:
        self.status_calls.append(capability_id)
        return {
            "connector_id": capability_id,
            "active": True,
            "device_flow": {
                "flow_id": "flow-a",
                "connector_id": capability_id,
                "verification_uri": "https://example.test/device",
                "user_code": "ABCD-EFGH",
                "expires_in": 240,
                "code_embedded_in_uri": False,
            },
        }

    def cancel_device_flow(
        self,
        capability_id: str,
        *,
        expected_flow_id: str,
    ) -> dict[str, Any]:
        self.cancel_calls.append((capability_id, expected_flow_id))
        return {"cancelled": True, "connector_id": capability_id}


def _device_flow_client(
    registry: _FakeCapabilityRegistry,
    *,
    identity_store: IdentityStore | None = None,
    require_auth: bool = False,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_capability_router(
            registry=registry,
            identity_store=identity_store,
            require_auth=require_auth,
        )
    )
    return TestClient(app)


def test_capability_list_supports_offset_pagination() -> None:
    client = _device_flow_client(_FakeCapabilityRegistry())

    response = client.get("/api/capabilities?limit=1&offset=1")

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert [item["id"] for item in response.json()["capabilities"]] == ["plugin-one"]


def test_local_install_rejects_a_stale_reviewed_plan_before_writes() -> None:
    registry = _FakeCapabilityRegistry()
    client = _device_flow_client(registry)

    stale = client.post(
        "/api/capabilities/plugin-one/install",
        json={"plan_id": "plan:old-generation"},
    )
    installed = client.post(
        "/api/capabilities/plugin-one/install",
        json={"plan_id": "plan:plugin-one"},
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "INSTALL_PLAN_STALE"
    assert installed.status_code == 200
    assert registry.install_calls == ["plugin-one"]


def test_capability_install_plan_endpoint_is_read_only() -> None:
    registry = _FakeCapabilityRegistry()
    response = _device_flow_client(registry).get("/api/capabilities/plugin-one/install-plan")

    assert response.status_code == 200
    assert response.json()["plan_id"] == "plan:plugin-one"
    assert registry.install_calls == []


class _FakeCodexAccounts:
    def __init__(self) -> None:
        self.install_calls: list[str] = []
        self.uninstall_calls: list[str] = []

    async def list_plugins(
        self,
        _scope: object,
        *,
        force_refetch: bool = False,
    ) -> list[dict[str, Any]]:
        del force_refetch
        return [
            {
                "id": "codex-marketplace:remote-one@openai-curated",
                "name": "Remote One",
                "name_zh": "Remote One",
                "description": "Fetched from Codex App Server",
                "description_zh": "Fetched from Codex App Server",
                "type": "plugin",
                "auth_mode": "none",
                "source": "codex_plugin",
                "provider_id": "remote-one",
                "author": "OpenAI",
                "category": "developer",
                "icon": "https://example.test/remote-one.png",
                "mcp_servers": [],
                "skill_count": 0,
                "installed": False,
                "enabled": False,
                "version": "1.0.0",
                "installable": True,
                "is_codex_marketplace": True,
            },
            {
                "id": "codex-marketplace:plugin-one@openai-curated",
                "provider_id": "plugin-one",
                "source": "codex_plugin",
                "is_codex_marketplace": True,
            },
        ]

    async def install_plugin(
        self,
        _scope: object,
        *,
        catalog_id: str,
    ) -> dict[str, Any]:
        self.install_calls.append(catalog_id)
        return {"installed": True, "enabled": True, "capability_id": catalog_id}

    async def uninstall_plugin(
        self,
        _scope: object,
        *,
        catalog_id: str,
    ) -> dict[str, Any]:
        self.uninstall_calls.append(catalog_id)
        return {"installed": False, "capability_id": catalog_id}


def test_capability_market_aggregates_and_manages_codex_app_server_plugins() -> None:
    registry = _FakeCapabilityRegistry()
    codex_accounts = _FakeCodexAccounts()
    app = FastAPI()
    app.include_router(create_capability_router(registry=registry, codex_accounts=codex_accounts))

    with TestClient(app) as client:
        listed = client.get("/api/capabilities?source=codex_plugin")
        catalog_id = "codex-marketplace:remote-one@openai-curated"
        installed = client.post(f"/api/capabilities/{catalog_id}/install")
        removed = client.delete(f"/api/capabilities/{catalog_id}/install")

    assert listed.status_code == 200
    ids = [item["id"] for item in listed.json()["capabilities"]]
    assert ids == [catalog_id, "codex-marketplace:plugin-one@openai-curated"]
    assert installed.json()["installed"] is True
    assert removed.json()["installed"] is False
    assert codex_accounts.install_calls == [catalog_id]
    assert codex_accounts.uninstall_calls == [catalog_id]


def test_personal_codex_marketplace_lifecycle_needs_login_not_operator() -> None:
    registry = _FakeCapabilityRegistry()
    codex_accounts = _FakeCodexAccounts()
    identities = IdentityStore()
    identities.add(
        Identity(actor_id="oct:user@example.com", roles=("user", "oct")),
        api_key_plaintext="sk-user",
    )
    app = FastAPI()
    app.include_router(
        create_capability_router(
            registry=registry,
            codex_accounts=codex_accounts,
            identity_store=identities,
            require_auth=True,
        )
    )
    client = TestClient(app)
    remote_id = "codex-marketplace:remote-one@openai-curated"
    headers = {"Authorization": "Bearer sk-user"}

    assert client.post(f"/api/capabilities/{remote_id}/install").status_code == 401
    installed = client.post(
        f"/api/capabilities/{remote_id}/install",
        headers=headers,
    )
    removed = client.delete(
        f"/api/capabilities/{remote_id}/install",
        headers=headers,
    )

    assert installed.status_code == 200
    assert removed.status_code == 200
    assert codex_accounts.install_calls == [remote_id]
    assert codex_accounts.uninstall_calls == [remote_id]
    # Legacy/local packages still mutate process-global state and keep the
    # existing operator boundary.
    assert client.post("/api/capabilities/plugin-one/install", headers=headers).status_code == 403
    local_detail = client.get("/api/capabilities/plugin-one", headers=headers)
    assert local_detail.json()["lifecycle_manageable"] is False


def test_local_desktop_user_can_manage_cloud_backed_bundled_plugins() -> None:
    registry = _FakeCapabilityRegistry()
    identities = IdentityStore()
    identities.add(
        Identity(actor_id="oct:user@example.com", roles=("user", "oct")),
        api_key_plaintext="sk-user",
    )
    app = FastAPI()
    app.include_router(
        create_capability_router(
            registry=registry,
            identity_store=identities,
            require_auth=True,
            allow_local_user_plugin_lifecycle=True,
        )
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer sk-user"}

    listed = client.get("/api/capabilities?source=codex_plugin", headers=headers)
    installed = client.post("/api/capabilities/plugin-one/install", headers=headers)
    removed = client.delete("/api/capabilities/plugin-one/install", headers=headers)

    assert listed.status_code == 200
    assert listed.json()["capabilities"][0]["lifecycle_manageable"] is True
    assert installed.status_code == 200
    assert removed.status_code == 200
    assert registry.install_calls == ["plugin-one"]
    assert registry.uninstall_calls == ["plugin-one"]


def test_local_plugin_install_failure_returns_bounded_json_error() -> None:
    class _FailingRegistry(_FakeCapabilityRegistry):
        def install(self, cid: str) -> dict[str, Any]:
            del cid
            raise ValueError("remote archive exceeded an internal limit")

    app = FastAPI()
    app.include_router(
        create_capability_router(
            registry=_FailingRegistry(),
            allow_local_user_plugin_lifecycle=True,
        )
    )

    response = TestClient(app).post("/api/capabilities/plugin-one/install")

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "插件包下载或安装失败，请稍后重试"}


def test_local_plugin_install_keeps_event_loop_responsive() -> None:
    class _SlowRegistry(_FakeCapabilityRegistry):
        def __init__(self) -> None:
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def install(self, cid: str) -> dict[str, Any]:
            self.started.set()
            self.release.wait(timeout=1)
            return {"installed": True, "capability_id": cid}

    registry = _SlowRegistry()
    app = FastAPI()
    app.include_router(
        create_capability_router(
            registry=registry,
            allow_local_user_plugin_lifecycle=True,
        )
    )

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            request_task = asyncio.create_task(client.post("/api/capabilities/plugin-one/install"))
            try:
                assert await asyncio.to_thread(registry.started.wait, 1)
                assert not request_task.done()
                heartbeat = asyncio.Event()
                asyncio.get_running_loop().call_soon(heartbeat.set)
                await asyncio.wait_for(heartbeat.wait(), timeout=0.1)
                assert not request_task.done()
            finally:
                registry.release.set()
            return await asyncio.wait_for(request_task, timeout=1)

    response = asyncio.run(exercise())

    assert response.status_code == 200
    assert response.json()["installed"] is True


def test_unified_device_flow_routes_recover_cancel_and_reject_non_connectors() -> None:
    registry = _FakeCapabilityRegistry()
    client = _device_flow_client(registry)

    status = client.get("/api/capabilities/cli-one/device-flow")
    missing_generation = client.delete("/api/capabilities/cli-one/device-flow")
    first_cancel = client.delete(
        "/api/capabilities/cli-one/device-flow",
        params={"expected_flow_id": "flow-a"},
    )
    second_cancel = client.delete(
        "/api/capabilities/cli-one/device-flow",
        params={"expected_flow_id": "flow-a"},
    )

    assert status.status_code == 200
    assert status.json()["device_flow"]["user_code"] == "ABCD-EFGH"
    assert status.json()["device_flow"]["flow_id"] == "flow-a"
    assert missing_generation.status_code == 422
    assert (
        first_cancel.json()
        == second_cancel.json()
        == {
            "cancelled": True,
            "connector_id": "cli-one",
        }
    )
    assert registry.status_calls == ["cli-one"]
    assert registry.cancel_calls == [("cli-one", "flow-a"), ("cli-one", "flow-a")]
    assert client.get("/api/capabilities/plugin-one/device-flow").status_code == 409
    assert (
        client.delete(
            "/api/capabilities/plugin-one/device-flow",
            params={"expected_flow_id": "flow-a"},
        ).status_code
        == 409
    )
    assert client.get("/api/capabilities/missing/device-flow").status_code == 404
    assert registry.status_calls == ["cli-one"]
    assert registry.cancel_calls == [("cli-one", "flow-a"), ("cli-one", "flow-a")]


def test_unified_device_flow_routes_require_operator_authorization() -> None:
    identities = IdentityStore()
    identities.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    identities.add(
        Identity(actor_id="operator", roles=("operator",)),
        api_key_plaintext="sk-operator",
    )
    registry = _FakeCapabilityRegistry()
    client = _device_flow_client(
        registry,
        identity_store=identities,
        require_auth=True,
    )
    user_headers = {"Authorization": "Bearer sk-alice"}
    operator_headers = {"Authorization": "Bearer sk-operator"}

    assert client.get("/api/capabilities/cli-one/device-flow").status_code == 401
    assert (
        client.get("/api/capabilities/cli-one/device-flow", headers=user_headers).status_code == 403
    )
    assert (
        client.delete(
            "/api/capabilities/cli-one/device-flow",
            params={"expected_flow_id": "flow-a"},
            headers=user_headers,
        ).status_code
        == 403
    )
    assert registry.status_calls == []
    assert registry.cancel_calls == []

    assert (
        client.get("/api/capabilities/cli-one/device-flow", headers=operator_headers).status_code
        == 200
    )
    assert (
        client.delete(
            "/api/capabilities/cli-one/device-flow",
            params={"expected_flow_id": "flow-a"},
            headers=operator_headers,
        ).status_code
        == 200
    )
    assert registry.status_calls == ["cli-one"]
    assert registry.cancel_calls == [("cli-one", "flow-a")]


def test_uninstall_reaps_replacement_and_rejects_prechecked_connect_until_reinstall(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Uninstall owns the final lifecycle boundary, even after A's stale cancel."""
    from runtime.platform.connectors import auth_orchestrator as ao
    from runtime.platform.connectors.auth_orchestrator import (
        AuthOrchestrator,
        DeviceFlowSession,
    )
    from runtime.platform.connectors.connector_registry import ConnectorRegistry
    from runtime.platform.connectors.credential_store import CredentialStore

    class FakeProc:
        def __init__(self) -> None:
            self.terminated = False
            self.wait_calls = 0

        def poll(self):
            return None if not self.terminated else 0

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout=None):
            self.wait_calls += 1
            self.terminated = True
            return 0

    connector_id = "cnb-api"
    connector_registry = ConnectorRegistry(
        marketplace_root=Path(__file__).resolve().parents[1]
        / "extensions"
        / "workbuddy-connectors",
        skills_root=tmp_path / "skills",
        state_file=tmp_path / "connectors.json",
    )
    connector_registry._set_state(
        connector_id,
        installed=True,
        enabled=True,
    )
    auth = AuthOrchestrator(
        credentials=CredentialStore(
            root=tmp_path / "credentials",
            master_key_file=tmp_path / "credentials" / "key",
            credentials_file=tmp_path / "credentials" / "secrets.json",
        )
    )
    registry = CapabilityRegistry(
        connector_registry=connector_registry,
        auth_orchestrator=auth,
        codex_cache=tmp_path / "codex-plugins",
        capability_state_file=tmp_path / "capabilities.json",
        skills_root=tmp_path / "skills",
    )
    client = _device_flow_client(registry)  # type: ignore[arg-type]

    def register(proc: FakeProc) -> DeviceFlowSession:
        session = DeviceFlowSession(
            connector_id=connector_id,
            proc=proc,
            verification_uri="https://cnb.cool/device",
            user_code="CODE",
            expires_in=240,
            started_at=time.time(),
        )
        with ao._device_lock:
            ao._device_flows[connector_id] = session
        return session

    first_proc = FakeProc()
    first = register(first_proc)
    first_cancel = client.delete(
        f"/api/capabilities/{connector_id}/device-flow",
        params={"expected_flow_id": first.flow_id},
    )
    assert first_cancel.status_code == 200
    assert first_proc.terminated is True

    replacement_proc = FakeProc()
    register(replacement_proc)
    late_cancel = client.delete(
        f"/api/capabilities/{connector_id}/device-flow",
        params={"expected_flow_id": first.flow_id},
    )
    assert late_cancel.status_code == 200
    assert late_cancel.json()["reason"] == "generation_mismatch"
    assert replacement_proc.terminated is False

    uninstall_entered = threading.Event()
    release_uninstall = threading.Event()
    real_uninstall = connector_registry.uninstall

    def paused_uninstall(selected: str) -> bool:
        uninstall_entered.set()
        assert release_uninstall.wait(timeout=3), "test did not release uninstall"
        return real_uninstall(selected)

    monkeypatch.setattr(connector_registry, "uninstall", paused_uninstall)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            uninstall = pool.submit(
                client.delete,
                f"/api/capabilities/{connector_id}/install",
            )
            assert uninstall_entered.wait(timeout=1)
            assert replacement_proc.terminated is True
            assert replacement_proc.wait_calls == 1

            connect = pool.submit(
                client.post,
                f"/api/capabilities/{connector_id}/connect",
                json={"tokens": {"access_token": "must-not-store"}},
            )
            assert not connect.done()
            release_uninstall.set()
            uninstall_response = uninstall.result(timeout=3)
            connect_response = connect.result(timeout=3)

        assert uninstall_response.status_code == 200
        assert connect_response.status_code == 409
        assert "not installed" in connect_response.text
        with ao._device_lock:
            assert connector_id not in ao._device_flows

        def reinstall(selected: str) -> dict[str, object]:
            connector_registry._set_state(selected, installed=True, enabled=False)
            return {"installed": True, "connector_id": selected}

        monkeypatch.setattr(connector_registry, "install", reinstall)
        reinstalled = client.post(f"/api/capabilities/{connector_id}/install")
        assert reinstalled.status_code == 200
        assert (
            client.post(
                f"/api/capabilities/{connector_id}/connect",
                json={"tokens": {"access_token": "without-review"}},
            ).status_code
            == 409
        )
        reconnected = client.post(
            f"/api/capabilities/{connector_id}/connect",
            json={
                "tokens": {"access_token": "after-reinstall"},
                "grant_permissions": reinstalled.json()["permissions"],
            },
        )
        assert reconnected.status_code == 200
        assert reconnected.json()["connected"] is True
    finally:
        release_uninstall.set()
        with ao._device_lock:
            leftover = ao._device_flows.pop(connector_id, None)
        if leftover is not None:
            leftover.watchdog_stop.set()


def test_disable_reaps_current_device_flow(tmp_path: Path) -> None:
    from runtime.platform.connectors import auth_orchestrator as ao
    from runtime.platform.connectors.auth_orchestrator import (
        AuthOrchestrator,
        DeviceFlowSession,
    )
    from runtime.platform.connectors.connector_registry import ConnectorRegistry
    from runtime.platform.connectors.credential_store import CredentialStore

    class FakeProc:
        def __init__(self) -> None:
            self.terminated = False
            self.wait_calls = 0

        def poll(self):
            return None if not self.terminated else 0

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout=None):
            self.wait_calls += 1
            return 0

    connector_id = "cnb-api"
    connector_registry = ConnectorRegistry(
        marketplace_root=Path(__file__).resolve().parents[1]
        / "extensions"
        / "workbuddy-connectors",
        skills_root=tmp_path / "skills",
        state_file=tmp_path / "connectors.json",
    )
    connector_registry._set_state(connector_id, installed=True, enabled=True)
    auth = AuthOrchestrator(credentials=CredentialStore(root=tmp_path / "credentials"))
    registry = CapabilityRegistry(
        connector_registry=connector_registry,
        auth_orchestrator=auth,
        codex_cache=tmp_path / "codex-plugins",
        capability_state_file=tmp_path / "capabilities.json",
        skills_root=tmp_path / "skills",
    )
    proc = FakeProc()
    session = DeviceFlowSession(
        connector_id=connector_id,
        proc=proc,
        verification_uri="https://cnb.cool/device",
        user_code="CODE",
        expires_in=240,
        started_at=time.time(),
    )
    with ao._device_lock:
        ao._device_flows[connector_id] = session
    try:
        client = _device_flow_client(registry)  # type: ignore[arg-type]
        response = client.post(f"/api/capabilities/{connector_id}/disable")

        assert response.status_code == 200
        assert proc.terminated is True
        assert proc.wait_calls == 1
        assert connector_id not in ao._device_flows
        state = connector_registry._state()[connector_id]
        assert state["installed"] is True
        assert state["enabled"] is False
    finally:
        with ao._device_lock:
            ao._device_flows.pop(connector_id, None)


def test_connect_keeps_event_loop_responsive_during_slow_auth() -> None:
    class SlowCapabilityRegistry(_FakeCapabilityRegistry):
        def __init__(self) -> None:
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()
            self.connect_calls: list[tuple[str, dict | None, bool]] = []

        def connect(
            self,
            capability_id: str,
            *,
            tokens: dict | None,
            run_cli: bool,
        ) -> dict[str, object]:
            self.connect_calls.append((capability_id, tokens, run_cli))
            self.started.set()
            self.release.wait(timeout=0.5)
            return {
                "connected": False,
                "device_flow": {
                    "flow_id": "slow-flow",
                    "connector_id": capability_id,
                    "verification_uri": "https://example.test/device",
                    "user_code": "SLOW",
                    "expires_in": 240,
                    "code_embedded_in_uri": False,
                },
            }

    registry = SlowCapabilityRegistry()
    app = FastAPI()
    app.include_router(create_capability_router(registry=registry))

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            request_task = asyncio.create_task(
                client.post(
                    "/api/capabilities/cli-one/connect",
                    json={"tokens": {"access_token": "secret"}, "run_cli": True},
                )
            )
            try:
                assert await asyncio.to_thread(registry.started.wait, 1)
                assert not request_task.done()
                heartbeat = asyncio.Event()
                asyncio.get_running_loop().call_soon(heartbeat.set)
                await asyncio.wait_for(heartbeat.wait(), timeout=0.1)
                assert not request_task.done()
            finally:
                registry.release.set()
            return await asyncio.wait_for(request_task, timeout=1)

    response = asyncio.run(exercise())

    assert response.status_code == 200
    assert response.json()["device_flow"]["user_code"] == "SLOW"
    assert registry.connect_calls == [
        ("cli-one", {"access_token": "secret"}, True),
    ]

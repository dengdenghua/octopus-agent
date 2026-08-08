"""PluginHub management REST API.

Provides CRUD + lifecycle control endpoints for the frontend plugin page.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from runtime.platform.plugins.plugin_hub import PluginHub


def create_plugin_hub_router(
    hub: PluginHub | None = None,
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    """Create a FastAPI router with PluginHub management endpoints.

    Parameters
    ----------
    hub : PluginHub or None
        The PluginHub instance. If ``None``, uses the singleton.
    """
    if hub is None:
        hub = PluginHub.get()

    def _auth_dep(request: Request) -> None:
        # Plugin lifecycle/config control is an operator-only surface in
        # shared deployments. Dev mode remains open when require_auth is off.
        if require_auth and identity_store is None:
            raise HTTPException(401, "identity store required for plugin hub auth")
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    def _operator_dep(request: Request) -> None:
        from runtime.safety.auth.principal import require_operator

        require_operator(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    router = APIRouter(
        prefix="/api/plugin-hub",
        tags=["plugin-hub"],
        dependencies=[Depends(_auth_dep)],
    )

    # ── List / Discover ────────────────────────────────────────

    @router.get("/plugins")
    def list_plugins():
        """Return metadata for all loaded plugins."""
        return hub.list_plugins()

    @router.get("/plugins/discover", dependencies=[Depends(_operator_dep)])
    def discover_plugins():
        """Scan plugin directories and return unloaded plugin candidates."""
        return hub.discover()

    # ── Lifecycle control ──────────────────────────────────────

    @router.post("/plugins/{name}/load", dependencies=[Depends(_operator_dep)])
    def load_plugin(name: str):
        """Load a discovered plugin by name."""
        if hub.load(name):
            return {"ok": True, "name": name}
        raise HTTPException(400, f"Failed to load plugin: {name}")

    @router.post("/plugins/{name}/start", dependencies=[Depends(_operator_dep)])
    def start_plugin(name: str):
        """Start a loaded plugin."""
        if hub.start(name):
            return {"ok": True, "name": name}
        raise HTTPException(400, f"Failed to start plugin: {name}")

    @router.post("/plugins/{name}/stop", dependencies=[Depends(_operator_dep)])
    def stop_plugin(name: str):
        """Stop a started plugin."""
        if hub.stop(name):
            return {"ok": True, "name": name}
        raise HTTPException(400, f"Failed to stop plugin: {name}")

    @router.post("/plugins/{name}/unload", dependencies=[Depends(_operator_dep)])
    def unload_plugin(name: str):
        """Unload a plugin."""
        if hub.unload(name):
            return {"ok": True, "name": name}
        raise HTTPException(400, f"Failed to unload plugin: {name}")

    # ── Config management ──────────────────────────────────────

    @router.get("/plugins/{name}/config", dependencies=[Depends(_operator_dep)])
    def get_config(name: str):
        """Get the current configuration for a plugin."""
        config = hub.get_plugin_config(name)
        if config is None:
            raise HTTPException(404, f"Plugin not found: {name}")
        return config

    @router.put("/plugins/{name}/config", dependencies=[Depends(_operator_dep)])
    def update_config(name: str, body: dict[str, Any]):
        """Update the configuration for a plugin."""
        if hub.update_plugin_config(name, body):
            return {"ok": True}
        raise HTTPException(404, f"Plugin not found: {name}")

    # ── Single plugin detail ───────────────────────────────────

    @router.get("/plugins/{name}")
    def get_plugin_detail(name: str):
        """Return full metadata for a single plugin."""
        plugins = hub.list_plugins()
        for p in plugins:
            if p["id"] == name:
                return p
        raise HTTPException(404, f"Plugin not found: {name}")

    return router

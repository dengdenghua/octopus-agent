from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from runtime.platform.plugins.codex_discovery import (  # re-exported
    _string,
    discover_codex_plugins,
)


def create_plugins_router(
    *,
    plugin_roots: list[Path] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["plugins"])

    @router.get("/api/plugins")
    def _plugins() -> list[dict[str, Any]]:
        return discover_codex_plugins(plugin_roots)

    @router.get("/api/plugins/capabilities")
    def _plugin_caps(type: str | None = None) -> list[dict[str, Any]]:
        caps: list[dict[str, Any]] = []
        for plugin in discover_codex_plugins(plugin_roots):
            for cap in plugin["capabilities"]:
                if type is None or cap.get("type") == type:
                    caps.append(cap)
        return caps

    @router.get("/api/plugins/{plugin_id}/assets/{asset_path:path}")
    def _plugin_asset(plugin_id: str, asset_path: str) -> FileResponse:
        for plugin in discover_codex_plugins(plugin_roots):
            if plugin["id"] != plugin_id:
                continue
            plugin_dir = Path(_string(plugin.get("path"))).resolve()
            requested = Path(asset_path)
            if requested.is_absolute() or ".." in requested.parts:
                raise HTTPException(status_code=404, detail="asset not found")
            candidate = (plugin_dir / requested).resolve()
            try:
                candidate.relative_to(plugin_dir)
            except ValueError:
                raise HTTPException(status_code=404, detail="asset not found") from None
            if not candidate.is_file():
                raise HTTPException(status_code=404, detail="asset not found")
            return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="plugin not found")

    @router.get("/api/plugins/{plugin_id}")
    def _plugin_get(plugin_id: str) -> dict[str, Any]:
        for plugin in discover_codex_plugins(plugin_roots):
            if plugin["id"] == plugin_id:
                return plugin
        raise HTTPException(status_code=404, detail="plugin not found")

    return router


__all__ = ["create_plugins_router", "discover_codex_plugins"]

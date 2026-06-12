"""Discover Codex-format plugins from disk and normalise their manifests.

This scanning/parsing logic lived in ``sensing/gateway/plugins_router``,
so the execution-layer capability skills had to reach up into the web
layer to enumerate installed plugins. It is pure (stdlib + project_root)
and is plugin-domain logic, so it belongs under ``platform.plugins``
alongside the plugin hub. ``plugins_router`` re-exports
``discover_codex_plugins`` (and helpers, for its asset endpoints).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from runtime.platform.process.paths import project_root


def _default_plugin_roots() -> list[Path]:
    root = project_root(Path(__file__))
    return [
        root / ".octopus" / "plugins" / "codex",
        Path.home() / ".octopus" / "plugins" / "codex",
    ]


def _read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _string(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return default


def _author_name(author: Any) -> str:
    if isinstance(author, str):
        return author
    if isinstance(author, dict):
        return _string(author.get("name"))
    return ""


def _capability_records(raw: Any, plugin_name: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            name = _string(item.get("name") or item.get("type"), "capability")
            out.append({
                "name": name,
                "type": _string(item.get("type"), "codex"),
                "description": _string(item.get("description")),
                "version": _string(item.get("version"), "1.0.0"),
                "requires": item.get("requires") if isinstance(item.get("requires"), list) else [],
                "provider": plugin_name,
            })
        elif isinstance(item, str) and item.strip():
            out.append({
                "name": item.strip(),
                "type": "codex",
                "description": "",
                "version": "1.0.0",
                "requires": [],
                "provider": plugin_name,
            })
    return out


def _dependencies(manifest: dict[str, Any]) -> list[str]:
    deps: list[str] = []
    for key in ("requires", "dependencies"):
        raw = manifest.get(key)
        if isinstance(raw, list):
            deps.extend(_string(item) for item in raw if _string(item))
    if manifest.get("mcpServers"):
        deps.append("mcp")
    if manifest.get("apps"):
        deps.append("app")
    if manifest.get("skills"):
        deps.append("skills")
    return sorted(set(deps))


def _asset_url(plugin_dir: Path, plugin_id: str, raw_path: Any) -> str | None:
    rel = _string(raw_path).strip()
    if not rel:
        return None
    asset_path = Path(rel)
    if asset_path.is_absolute() or ".." in asset_path.parts:
        return None
    candidate = (plugin_dir / asset_path).resolve()
    try:
        candidate.relative_to(plugin_dir.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    posix_rel = candidate.relative_to(plugin_dir.resolve()).as_posix()
    return f"/api/plugins/{quote(plugin_id, safe='')}/assets/{quote(posix_rel, safe='/')}"


def _plugin_info(plugin_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        interface = {}
    name = _string(manifest.get("name"), plugin_dir.name)
    display_name = _string(interface.get("displayName"), name)
    capabilities = _capability_records(interface.get("capabilities"), name)
    logo_url = _asset_url(plugin_dir, name, interface.get("logo"))
    composer_icon_url = _asset_url(plugin_dir, name, interface.get("composerIcon"))
    error = ""
    if not (plugin_dir / ".codex-plugin" / "plugin.json").is_file():
        error = "missing .codex-plugin/plugin.json"
    author = (
        _author_name(manifest.get("author"))
        or _string(interface.get("developerName"))
        or "octopus"
    )
    return {
        "id": name,
        "name": display_name,
        "version": _string(manifest.get("version"), "0.1.0"),
        "description": _string(
            interface.get("shortDescription") or manifest.get("description"),
        ),
        "author": author,
        "capabilities": capabilities,
        "dependencies": _dependencies(manifest),
        "enabled": not error,
        "state": "registered" if not error else "error",
        "error": error or None,
        "logo_url": logo_url,
        "icon_url": composer_icon_url or logo_url,
        "brand_color": _string(interface.get("brandColor")) or None,
        "source": "codex",
        "path": str(plugin_dir),
    }


def discover_codex_plugins(roots: list[Path] | None = None) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for root in roots or _default_plugin_roots():
        if not root.is_dir():
            continue
        for manifest_path in sorted(root.glob("*/.codex-plugin/plugin.json")):
            manifest = _read_manifest(manifest_path)
            if manifest is None:
                continue
            info = _plugin_info(manifest_path.parent.parent, manifest)
            out[info["id"]] = info
    return sorted(out.values(), key=lambda item: item["name"].lower())

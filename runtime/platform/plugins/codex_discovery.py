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


def _has_skill_files(plugin_dir: Path) -> bool:
    skills_dir = plugin_dir / "skills"
    return skills_dir.is_dir() and any(skills_dir.glob("*/SKILL.md"))


def _has_app_manifest(plugin_dir: Path) -> bool:
    return any(
        (plugin_dir / name).is_file()
        for name in (".app.json", "octopus-app.jsonc", "app.json")
    )


def _plugin_smoke_check(
    plugin_dir: Path,
    manifest: dict[str, Any],
    *,
    info: dict[str, Any],
    logo_url: str | None,
    composer_icon_url: str | None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    warnings: list[str] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            issues.append(detail or name)

    manifest_path = plugin_dir / ".codex-plugin" / "plugin.json"
    add("manifest", manifest_path.is_file(), "missing .codex-plugin/plugin.json")
    add("name", bool(_string(manifest.get("name")).strip()), "manifest is missing name")
    add(
        "version",
        bool(_string(manifest.get("version")).strip()),
        "manifest is missing version",
    )

    interface = manifest.get("interface") if isinstance(manifest.get("interface"), dict) else {}
    has_capabilities = bool(info.get("capabilities"))
    has_skills = _has_skill_files(plugin_dir)
    has_apps = bool(manifest.get("apps")) or _has_app_manifest(plugin_dir)
    has_mcp = bool(manifest.get("mcpServers")) or (plugin_dir / ".mcp.json").is_file()
    has_commands = (plugin_dir / "commands").is_dir()
    surface_count = sum(
        1
        for present in (has_capabilities, has_skills, has_apps, has_mcp, has_commands)
        if present
    )
    add(
        "capability_surface",
        surface_count > 0,
        "plugin exposes no capabilities, skills, apps, MCP servers, or commands",
    )

    if interface.get("logo") and logo_url is None:
        warnings.append("logo path is missing, unsafe, or outside plugin root")
    if interface.get("composerIcon") and composer_icon_url is None:
        warnings.append("composer icon path is missing, unsafe, or outside plugin root")
    if has_mcp and not manifest.get("permissions"):
        warnings.append("MCP-capable plugin has no explicit permissions declaration")

    permission_resolution = _permission_resolution(
        manifest,
        has_mcp=has_mcp,
        warnings=warnings,
    )
    ok = not issues
    return {
        "schema": "octopus.codex_plugin_smoke.v1",
        "ok": ok,
        "checks": checks,
        "issues": issues,
        "warnings": warnings,
        "surfaces": {
            "capabilities": has_capabilities,
            "skills": has_skills,
            "apps": has_apps,
            "mcp": has_mcp,
            "commands": has_commands,
        },
        "trust": {
            "level": "local_verified" if ok and not warnings else "local_review_required",
            "signed": False,
            "reason": "local plugin manifest smoke check",
        },
        "permission_resolution": permission_resolution,
    }


def _permission_resolution(
    manifest: dict[str, Any],
    *,
    has_mcp: bool,
    warnings: list[str],
) -> dict[str, Any]:
    raw_permissions = manifest.get("permissions")
    explicit_permissions = raw_permissions if isinstance(raw_permissions, list) else []
    if explicit_permissions:
        return {
            "schema": "octopus.codex_plugin_permission_resolution.v1",
            "status": "explicit",
            "review_required": False,
            "accepted_risk": False,
            "permissions": explicit_permissions,
            "reason": "plugin declares explicit permissions",
        }
    inferred: list[str] = []
    if has_mcp:
        inferred.append("mcp:execute:review_required")
    if manifest.get("apps"):
        inferred.append("app:render:review_required")
    if manifest.get("interface"):
        inferred.append("ui:metadata:local")
    status = "review_required" if inferred or warnings else "none"
    return {
        "schema": "octopus.codex_plugin_permission_resolution.v1",
        "status": status,
        "review_required": status == "review_required",
        "accepted_risk": False,
        "permissions": inferred,
        "reason": (
            "default permissions inferred from plugin surfaces"
            if inferred
            else "no permission-bearing surfaces detected"
        ),
    }


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
    info = {
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
    info["smoke"] = _plugin_smoke_check(
        plugin_dir,
        manifest,
        info=info,
        logo_url=logo_url,
        composer_icon_url=composer_icon_url,
    )
    return info


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

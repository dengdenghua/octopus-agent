from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.platform.plugins.codex_discovery import discover_codex_plugins
from runtime.sensing.gateway.plugins_router import create_plugins_router


def test_codex_plugin_discovery_includes_smoke_metadata(tmp_path: Path) -> None:
    plugin_dir = _write_plugin(tmp_path)

    plugins = discover_codex_plugins([tmp_path])

    assert [plugin["id"] for plugin in plugins] == ["research"]
    smoke = plugins[0]["smoke"]
    assert smoke["schema"] == "octopus.codex_plugin_smoke.v1"
    assert smoke["ok"] is True
    assert smoke["surfaces"]["skills"] is True
    assert smoke["surfaces"]["mcp"] is True
    assert smoke["trust"]["level"] == "local_review_required"
    assert smoke["permission_resolution"]["status"] == "review_required"
    assert smoke["permission_resolution"]["permissions"] == [
        "mcp:execute:review_required",
        "ui:metadata:local",
    ]
    assert plugin_dir.name == "research"


def test_codex_plugin_smoke_endpoint(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    app = FastAPI()
    app.include_router(create_plugins_router(plugin_roots=[tmp_path]))
    client = TestClient(app)

    response = client.get("/api/plugins/research/smoke")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_codex_plugin_smoke_summary_endpoint(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    plugin_dir = tmp_path / "empty"
    (plugin_dir / ".codex-plugin").mkdir(parents=True)
    (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "empty", "version": "0.1.0"}),
        encoding="utf-8",
    )
    app = FastAPI()
    app.include_router(create_plugins_router(plugin_roots=[tmp_path]))
    client = TestClient(app)

    response = client.get("/api/plugins/smoke-summary")

    assert response.status_code == 200
    data = response.json()
    assert data["schema"] == "octopus.codex_plugin_smoke_summary.v1"
    assert data["total"] == 2
    assert data["ok_count"] == 1
    assert data["failed_count"] == 1
    assert data["review_required_count"] == 2
    assert data["warning_count"] == 1
    assert data["failed"][0]["plugin_id"] == "empty"
    assert data["warnings"][0]["plugin_id"] == "research"
    assert data["permission_resolutions"][0]["schema"] == (
        "octopus.codex_plugin_permission_resolution.v1"
    )
    assert data["compatibility"]["schema"] == "octopus.codex_plugin_compatibility.v1"
    assert data["compatibility"]["verdict"] == "fail"
    assert data["compatibility"]["surface_totals"]["skills"] == 1
    assert data["compatibility"]["surface_totals"]["mcp"] == 1
    assert any(
        item["id"] == "no_smoke_failures" and item["passed"] is False
        for item in data["compatibility"]["requirements"]
    )


def test_codex_plugin_smoke_summary_marks_review_compatible_set(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    app = FastAPI()
    app.include_router(create_plugins_router(plugin_roots=[tmp_path]))
    client = TestClient(app)

    response = client.get("/api/plugins/smoke-summary")

    assert response.status_code == 200
    data = response.json()
    assert data["failed_count"] == 0
    assert data["compatibility"]["verdict"] == "review"
    assert data["compatibility"]["passed"] == data["compatibility"]["total"]
    assert data["compatibility"]["next_actions"] == [
        "Resolve inferred plugin permission defaults or mark accepted risk.",
        "Resolve plugin warnings or mark accepted risk.",
    ]


def test_codex_plugin_smoke_summary_guides_empty_ecosystem(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(create_plugins_router(plugin_roots=[tmp_path]))
    client = TestClient(app)

    response = client.get("/api/plugins/smoke-summary")

    assert response.status_code == 200
    data = response.json()
    assert data["compatibility"]["verdict"] == "fail"
    assert data["compatibility"]["next_actions"] == [
        "Install or enable at least one local Codex-compatible plugin.",
        "Expose at least one plugin capability, skill, app, MCP server, or command.",
    ]


def test_codex_plugin_smoke_flags_empty_surface(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "empty"
    (plugin_dir / ".codex-plugin").mkdir(parents=True)
    (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "empty", "version": "0.1.0"}),
        encoding="utf-8",
    )

    plugins = discover_codex_plugins([tmp_path])

    smoke = plugins[0]["smoke"]
    assert smoke["ok"] is False
    assert any("no capabilities" in issue for issue in smoke["issues"])


def _write_plugin(root: Path) -> Path:
    plugin_dir = root / "research"
    (plugin_dir / ".codex-plugin").mkdir(parents=True)
    (plugin_dir / "skills" / "brief").mkdir(parents=True)
    (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "research",
                "version": "0.1.0",
                "interface": {
                    "displayName": "Research",
                    "capabilities": [{"name": "brief", "type": "codex"}],
                },
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "skills" / "brief" / "SKILL.md").write_text(
        "# Brief\n",
        encoding="utf-8",
    )
    (plugin_dir / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"research": {"command": "node"}}}),
        encoding="utf-8",
    )
    return plugin_dir

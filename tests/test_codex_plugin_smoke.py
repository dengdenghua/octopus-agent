from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.platform.plugins.codex_discovery import discover_codex_plugins
from runtime.safety.auth import Identity, IdentityStore
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
    assert smoke["trust"]["signed"] is False
    assert smoke["trust"]["provenance"]["schema"] == (
        "octopus.codex_plugin_provenance.v1"
    )
    assert smoke["trust"]["provenance"]["signature"]["present"] is False
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
    assert data["provenance"][0]["schema"] == "octopus.codex_plugin_provenance.v1"
    assert data["provenance"][0]["signed"] is False
    assert data["lifecycle_audit"]["schema"] == "octopus.plugin_lifecycle_audit.v1"
    assert data["lifecycle_audit"]["fail_count"] == 1
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
    assert data["lifecycle_audit"]["verdict"] == "review"
    assert data["lifecycle_audit"]["rows"][0]["finding_codes"] == [
        "permission_review_required",
        "unsigned_local_plugin",
    ]
    assert data["lifecycle_audit"]["rows"][0]["provenance"]["schema"] == (
        "octopus.codex_plugin_provenance.v1"
    )
    assert data["compatibility"]["verdict"] == "review"
    assert data["compatibility"]["passed"] == data["compatibility"]["total"]
    assert data["compatibility"]["next_actions"] == [
        "Resolve inferred plugin permission defaults or mark accepted risk.",
        "Resolve plugin warnings or mark accepted risk.",
    ]


def test_codex_plugin_smoke_accepts_signed_provenance(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        manifest_patch={
            "permissions": ["mcp:execute", "ui:metadata"],
            "provenance": {
                "source": "https://example.test/research",
                "source_type": "git",
                "revision": "abc123",
                "signature": {
                    "kind": "sha256",
                    "value": "sha256:abc123",
                },
            },
        },
    )
    app = FastAPI()
    app.include_router(create_plugins_router(plugin_roots=[tmp_path]))
    client = TestClient(app)

    smoke = client.get("/api/plugins/research/smoke").json()
    summary = client.get("/api/plugins/smoke-summary").json()

    assert smoke["trust"]["level"] == "signed_verified"
    assert smoke["trust"]["signed"] is True
    assert smoke["trust"]["provenance"]["signature"]["present"] is True
    assert smoke["permission_resolution"]["status"] == "explicit"
    assert summary["lifecycle_audit"]["verdict"] == "pass"
    assert summary["compatibility"]["verdict"] == "pass"
    assert any(
        item["id"] == "signed_provenance_visible" and item["passed"] is True
        for item in summary["compatibility"]["requirements"]
    )


def test_codex_plugin_smoke_summary_guides_empty_ecosystem(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(create_plugins_router(plugin_roots=[tmp_path]))
    client = TestClient(app)

    response = client.get("/api/plugins/smoke-summary")

    assert response.status_code == 200
    data = response.json()
    assert data["compatibility"]["verdict"] == "fail"
    assert data["lifecycle_audit"]["schema"] == "octopus.plugin_lifecycle_audit.v1"
    assert data["lifecycle_audit"]["total"] == 0
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


def test_plugins_router_requires_auth_when_enabled(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    app = FastAPI()
    app.include_router(
        create_plugins_router(
            plugin_roots=[tmp_path],
            identity_store=store,
            require_auth=True,
        )
    )
    client = TestClient(app)

    assert client.get("/api/plugins").status_code == 401
    assert client.get(
        "/api/plugins",
        headers={"Authorization": "Bearer sk-alice"},
    ).status_code == 200


def test_plugin_assets_are_public_read_only_when_auth_enabled(tmp_path: Path) -> None:
    plugin_dir = _write_plugin(tmp_path)
    (plugin_dir / "assets").mkdir()
    (plugin_dir / "assets" / "logo.txt").write_text("logo", encoding="utf-8")
    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    app = FastAPI()
    app.include_router(
        create_plugins_router(
            plugin_roots=[tmp_path],
            identity_store=store,
            require_auth=True,
        )
    )
    client = TestClient(app)

    assert client.get("/api/plugins").status_code == 401
    asset = client.get("/api/plugins/research/assets/assets/logo.txt")
    assert asset.status_code == 200
    assert asset.text == "logo"


def _write_plugin(
    root: Path,
    *,
    manifest_patch: dict[str, object] | None = None,
) -> Path:
    plugin_dir = root / "research"
    (plugin_dir / ".codex-plugin").mkdir(parents=True)
    (plugin_dir / "skills" / "brief").mkdir(parents=True)
    manifest = {
        "name": "research",
        "version": "0.1.0",
        "interface": {
            "displayName": "Research",
            "capabilities": [{"name": "brief", "type": "codex"}],
        },
    }
    manifest.update(manifest_patch or {})
    (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(manifest),
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

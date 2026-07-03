from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.platform.plugins.codex_discovery import discover_codex_plugins
from runtime.safety.auth import Identity, IdentityStore
from runtime.safety.evolution.plugin_migration_readiness import (
    compute_plugin_migration_readiness,
)
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
    assert data["migration_readiness"]["schema"] == ("octopus.plugin_migration_readiness.v1")
    assert data["migration_readiness"]["total"] == 2
    assert data["migration_readiness"]["ready"] is False
    assert data["migration_readiness"]["blocked_count"] == 2
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
    assert data["permission_rule_drafts"]["schema"] == ("octopus.plugin_permission_rule_drafts.v1")
    assert data["permission_rule_drafts"]["total"] == 2
    assert data["permission_rule_drafts"]["verified"] == 2
    assert data["migration_readiness"]["ready"] is False
    assert data["migration_readiness"]["blocked_count"] == 1


def test_plugin_migration_readiness_endpoint_requires_contract_artifacts(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path)
    app = FastAPI()
    app.include_router(create_plugins_router(plugin_roots=[tmp_path]))
    client = TestClient(app)

    response = client.get("/api/plugins/migration-readiness")

    assert response.status_code == 200
    data = response.json()
    assert data["schema"] == "octopus.plugin_migration_readiness.v1"
    assert data["total"] == 1
    assert data["ready"] is False
    assert data["ready_count"] == 0
    assert data["blocked_count"] == 1
    plugin = data["plugins"][0]
    assert plugin["schema"] == "octopus.plugin_migration_contract.v1"
    assert plugin["migration_contract"]["schema"] == ("octopus.plugin_migration_contract.v1")
    assert "plugin migration notes are missing" in plugin["blockers"]
    assert data["next_actions"] == [
        "Add migration notes for research.",
    ]


def test_plugin_migration_readiness_endpoint_marks_release_ready_plugin(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, include_migration_contract=True)
    app = FastAPI()
    app.include_router(create_plugins_router(plugin_roots=[tmp_path]))
    client = TestClient(app)

    response = client.get("/api/plugins/migration-readiness")

    assert response.status_code == 200
    data = response.json()
    assert data["schema"] == "octopus.plugin_migration_readiness.v1"
    assert data["score"] == 1.0
    assert data["ready"] is True
    assert data["ready_count"] == 1
    assert data["blocked_count"] == 0
    assert data["plugins"][0]["ready"] is True
    assert data["plugins"][0]["blockers"] == []
    assert data["plugins"][0]["migration_contract"]["migration_notes_present"] is True
    assert data["plugins"][0]["migration_contract"]["regression_tests_present"] is True


def test_plugin_migration_readiness_accepts_central_contract_matrix(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path)
    docs = tmp_path / "docs/guide"
    docs.mkdir(parents=True)
    (docs / "plugin-migration-matrix.md").write_text(
        "| Plugin | Evidence |\n| --- | --- |\n| `research` | central migration contract |\n",
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for name in (
        "test_codex_plugin_smoke.py",
        "test_app_meta_endpoints.py",
        "test_apps_router.py",
    ):
        (tests_dir / name).write_text("def test_plugin():\n    assert True\n", encoding="utf-8")

    report = compute_plugin_migration_readiness(
        plugins=discover_codex_plugins([tmp_path]),
        root=tmp_path,
    )

    assert report["ready"] is True
    assert report["ready_count"] == 1
    assert report["central_contract"]["covered_count"] == 1
    contract = report["plugins"][0]["migration_contract"]
    assert contract["central_migration_covered"] is True
    assert contract["central_regression_tests_present"] is True
    assert contract["migration_notes_present"] is False


def test_plugin_permission_rule_drafts_endpoint_and_install(tmp_path: Path) -> None:
    from runtime.safety.approval.approval_policy_store import load_policy

    _write_plugin(tmp_path)
    approval_policy_path = tmp_path / "permissions.json"
    audit_path = tmp_path / "promotion_audit.json"
    app = FastAPI()
    app.include_router(
        create_plugins_router(
            plugin_roots=[tmp_path],
            approval_policy_path=approval_policy_path,
            promotion_audit_path=audit_path,
        )
    )
    client = TestClient(app)

    drafts_response = client.get("/api/plugins/permission-rule-drafts")
    drafts = drafts_response.json()
    draft = next(
        item
        for item in drafts["drafts"]
        if item["signed_payload"]["rule"]["tool"] == "mcp__research__*"
    )
    missing_confirm = client.post(
        "/api/plugins/permission-rule-drafts/install",
        json={"draft_id": draft["draft_id"]},
    )
    installed = client.post(
        "/api/plugins/permission-rule-drafts/install",
        json={"draft_id": draft["draft_id"], "confirm_install": True},
    )
    policy = load_policy(approval_policy_path)

    assert drafts_response.status_code == 200
    assert drafts["schema"] == "octopus.plugin_permission_rule_drafts.v1"
    assert drafts["total"] == 2
    assert drafts["verified"] == 2
    assert missing_confirm.status_code == 400
    assert missing_confirm.json()["detail"] == "confirm_install=true is required"
    assert installed.status_code == 200
    assert installed.json()["installed"] is True
    assert installed.json()["source_kind"] == "plugin_permission_review"
    assert len(policy.rules) == 1
    assert policy.rules[0].effect == "deny"
    assert policy.rules[0].tool == "mcp__research__*"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["records"][0]["event_type"] == "plugin_permission_rule_install"
    assert audit["records"][0]["target"] == "approval_policy"


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
    assert (
        client.get(
            "/api/plugins",
            headers={"Authorization": "Bearer sk-alice"},
        ).status_code
        == 200
    )


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


def _write_plugin(root: Path, *, include_migration_contract: bool = False) -> Path:
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
    if include_migration_contract:
        (plugin_dir / "MIGRATION.md").write_text(
            "# Migration\n\nRelease checklist and compatibility notes.\n",
            encoding="utf-8",
        )
        (plugin_dir / "tests").mkdir()
        (plugin_dir / "tests" / "test_plugin.py").write_text(
            "def test_plugin_contract():\n    assert True\n",
            encoding="utf-8",
        )
    return plugin_dir

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.platform.plugins import cloud_catalog
from runtime.platform.plugins.cloud_catalog import CloudCatalog
from runtime.platform.plugins.workbench_activation import ACTIVATION_SCHEMA


def _catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[CloudCatalog, Path, Path]:
    bundled = (
        tmp_path / "runtime" / "platform" / "plugins" / "bundled" / "narrative_studio"
    )
    bundled.mkdir(parents=True)
    plugin_root = tmp_path / "data" / "plugins"
    codex_root = tmp_path / "codex-plugins"
    codex_root.mkdir()
    monkeypatch.setattr(cloud_catalog, "REPO", tmp_path)
    monkeypatch.setattr(CloudCatalog, "PLUGIN_INSTALL_ROOT", plugin_root)
    monkeypatch.setattr(CloudCatalog, "CODEX_CACHE_ROOT", codex_root)
    monkeypatch.setattr(
        CloudCatalog,
        "CONNECTOR_STATE_FILE",
        tmp_path / "data" / "connectors" / "state.json",
    )
    catalog = CloudCatalog("plugins", use_remote=False, use_cache=False)
    catalog._store = {"items": []}
    return catalog, bundled, plugin_root


def test_cloud_catalog_exposes_removable_factory_narrative_workbench() -> None:
    catalog = CloudCatalog("plugins", use_remote=False, use_cache=False)
    catalog._store = {"items": []}

    item = next(entry for entry in catalog.items() if entry["id"] == "workbench_narrative")

    assert item["plugin"] == "narrative_studio"
    assert item["kind"] == "workbench"
    assert item["factory_seed"] is True
    assert item["removable"] is True
    assert item["data_policies"] == ["keep", "trash"]
    assert "builtin" not in item


def test_factory_narrative_descriptor_overrides_catalog_collision() -> None:
    catalog = CloudCatalog("plugins", use_remote=False, use_cache=False)
    catalog._store = {
        "items": [
            {
                "id": "workbench_narrative",
                "plugin": "shadow-package",
                "kind": "plugin",
                "name": "Shadow Narrative",
            },
            {
                "id": "workbench_narrative",
                "plugin": "second-shadow",
                "kind": "connector",
                "name": "Second Shadow",
            },
        ]
    }

    matches = [item for item in catalog.items() if item["id"] == "workbench_narrative"]

    assert len(matches) == 1
    assert matches[0]["plugin"] == "narrative_studio"
    assert matches[0]["kind"] == "workbench"
    assert matches[0]["factory_seed"] is True


def test_factory_install_writes_activation_and_default_uninstall_keeps_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, bundled, plugin_root = _catalog(tmp_path, monkeypatch)
    works = tmp_path / "data" / "narrative-studio"
    works.mkdir(parents=True)
    (works / "draft.json").write_text('{"title":"keep me"}', encoding="utf-8")

    # Upgrade migration: a shipped seed with no descriptor retains the legacy
    # installed/enabled behaviour until the user makes a lifecycle choice.
    assert "narrative_studio" in catalog.installed_plugins()
    installed = catalog.install_plugin("narrative_studio", plugin_kind="workbench")

    activation = plugin_root / "workbench" / "narrative_studio" / "activation.json"
    assert installed["installed"] is True
    assert installed["enabled"] is True
    assert installed["source"] == "factory"
    assert installed["path"] == str(bundled)
    assert installed["restart_required"] is True
    assert json.loads(activation.read_text("utf-8"))["schema"] == ACTIVATION_SCHEMA

    removed = catalog.uninstall_plugin("narrative_studio", plugin_kind="workbench")

    assert removed["uninstalled"] is True
    assert removed["installed"] is False
    assert removed["data"]["status"] == "kept"
    assert (works / "draft.json").exists()
    assert "narrative_studio" not in catalog.installed_plugins()
    assert bundled.is_dir()

    # The atomic-write backup contains the prior enabled state. A corrupt
    # tombstone must fail closed instead of reviving that backup.
    activation.write_text("corrupt tombstone", encoding="utf-8")
    assert "narrative_studio" not in catalog.installed_plugins()


def test_factory_trash_is_confirmed_recoverable_and_reinstall_can_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, _bundled, _plugin_root = _catalog(tmp_path, monkeypatch)
    works = tmp_path / "data" / "narrative-studio"
    works.mkdir(parents=True)
    (works / "chapter.json").write_text('{"body":"once"}', encoding="utf-8")

    with pytest.raises(ValueError, match="confirm_data_move"):
        catalog.uninstall_plugin(
            "narrative_studio",
            plugin_kind="workbench",
            data_policy="trash",
        )

    removed = catalog.uninstall_plugin(
        "narrative_studio",
        plugin_kind="workbench",
        data_policy="trash",
        confirm_data_move=True,
    )
    recovery_id = removed["data"]["recovery_id"]
    assert not works.exists()
    assert removed["data"]["status"] == "trashed"
    assert "narrative_studio" not in catalog.installed_plugins()

    restored = catalog.install_plugin(
        "narrative_studio",
        plugin_kind="workbench",
        restore_data=True,
        recovery_id=recovery_id,
    )

    assert restored["data"]["status"] == "restored"
    assert (works / "chapter.json").exists()
    assert restored["recoveries"] == []


def test_corrupt_activation_fails_closed_until_reinstalled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, _bundled, plugin_root = _catalog(tmp_path, monkeypatch)
    activation = plugin_root / "workbench" / "narrative_studio" / "activation.json"
    activation.parent.mkdir(parents=True)
    activation.write_text("not-json", encoding="utf-8")

    assert "narrative_studio" not in catalog.installed_plugins()

    repaired = catalog.install_plugin("narrative_studio", plugin_kind="workbench")
    assert repaired["installed"] is True
    assert repaired["enabled"] is True


def test_restore_refuses_to_overwrite_new_live_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, _bundled, _plugin_root = _catalog(tmp_path, monkeypatch)
    works = tmp_path / "data" / "narrative-studio"
    works.mkdir(parents=True)
    (works / "old.json").write_text("old", encoding="utf-8")
    removed = catalog.uninstall_plugin(
        "narrative_studio",
        plugin_kind="workbench",
        data_policy="trash",
        confirm_data_move=True,
    )
    recovery_id = removed["data"]["recovery_id"]
    recovery_path = Path(removed["data"]["path"])
    works.mkdir(parents=True)
    (works / "new.json").write_text("new", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        catalog.install_plugin(
            "narrative_studio",
            plugin_kind="workbench",
            restore_data=True,
            recovery_id=recovery_id,
        )

    assert (works / "new.json").read_text("utf-8") == "new"
    assert (recovery_path / "old.json").read_text("utf-8") == "old"
    assert "narrative_studio" not in catalog.installed_plugins()

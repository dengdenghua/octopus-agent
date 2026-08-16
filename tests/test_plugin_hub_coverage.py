"""Dense coverage for PluginHub lifecycle (audit Q-05)."""

from __future__ import annotations

from pathlib import Path

from runtime.platform.plugins.plugin_base import ModulePlugin
from runtime.platform.plugins.plugin_hub import PluginHub


def _make_plugin(root: Path, name: str = "testplug") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "plugin.yaml").write_text(
        f"name: {name}\nversion: 1.0.0\ndescription: test\n", encoding="utf-8"
    )
    (d / "__init__.py").write_text(
        "from runtime.platform.plugins.plugin_base import ModulePlugin\n\n"
        "class TestPlugin(ModulePlugin):\n"
        f"    name = '{name}'\n"
        "    def register_skills(self):\n        pass\n"
        "    def register_channels(self):\n        pass\n"
        "    def register_routes(self):\n        pass\n",
        encoding="utf-8",
    )
    return d


def test_discover_and_manifest(tmp_path: Path) -> None:
    hub = PluginHub(plugin_dir=tmp_path)
    _make_plugin(tmp_path)
    found = hub.discover()
    assert any(p.get("name") == "testplug" for p in found)
    d = tmp_path / "testplug"
    manifest = hub._read_manifest_file(d)
    assert manifest and manifest["name"] == "testplug"
    assert hub._read_manifest_file(tmp_path / "missing") is None


def test_load_unload_lifecycle(tmp_path: Path) -> None:
    hub = PluginHub(plugin_dir=tmp_path)
    _make_plugin(tmp_path)
    plugin = hub.load("testplug")
    assert plugin is not None and plugin.name == "testplug"
    assert hub.load("testplug") is plugin  # cached
    assert hub.get_plugin("testplug") is plugin
    assert hub.unload("testplug") is True
    assert hub.get_plugin("testplug") is None
    assert hub.load("nope") is None


def test_list_and_plugin_dir_resolution(tmp_path: Path) -> None:
    hub = PluginHub(plugin_dir=tmp_path)
    _make_plugin(tmp_path)
    assert hub.load("testplug") is not None
    listed = hub.list_plugins()
    assert any(p.get("name") == "testplug" for p in listed)
    assert hub._resolve_plugin_dir("testplug") == (tmp_path / "testplug")
    assert hub._resolve_plugin_dir("missing") is None

import json
from pathlib import Path

import pytest

from runtime.platform.plugins.cloud_catalog import CloudCatalog
from runtime.tentacle.mobile.capabilities import android_capabilities
from runtime.tentacle.ios.capabilities import ios_capabilities
from runtime.tentacle.mobile._mcp_skill_tools import load_all_skill_tools


@pytest.mark.parametrize("platform,count,capabilities", [
    ("android", 30, android_capabilities), ("ios", 13, ios_capabilities),
])
def test_device_plugin_install_activation_and_removal(tmp_path, monkeypatch, platform, count, capabilities):
    for field, suffix in {
        "PLUGIN_INSTALL_ROOT": "plugins", "SKILLS_ROOT": "skills",
        "CODEX_CACHE_ROOT": "cache", "CAPABILITY_STATE_FILE": "state.json",
        "CONNECTOR_STATE_FILE": "connectors.json",
    }.items():
        monkeypatch.setattr(CloudCatalog, field, tmp_path / suffix)
    plugin_id = f"echo-{platform}"
    catalog = CloudCatalog("plugins", use_remote=False, use_cache=False)
    assert capabilities() == ()
    result = catalog.install_plugin(plugin_id, plugin_kind="codex")
    assert result["copied_skills"] == []
    # Installation stages permission-bearing plugins disabled; activation is
    # a separate marketplace operation.
    assert capabilities() == ()
    state_path = CloudCatalog.CAPABILITY_STATE_FILE
    state = json.loads(state_path.read_text())
    state[plugin_id]["enabled"] = True
    state_path.write_text(json.dumps(state))
    assert len(capabilities()) == count
    assert len(load_all_skill_tools()) == count
    state[plugin_id]["enabled"] = False
    state_path.write_text(json.dumps(state))
    assert capabilities() == ()
    assert load_all_skill_tools() == []
    state[plugin_id]["enabled"] = True
    state_path.write_text(json.dumps(state))
    assert len(capabilities()) == count
    catalog.uninstall_plugin(plugin_id, plugin_kind="codex")
    assert capabilities() == ()


def test_device_manifests_are_not_marketplace_skills(monkeypatch):
    from runtime.platform.assets import skill_inventory
    monkeypatch.setattr(skill_inventory, "scan_local_skills", lambda: [
        {"name": name, "variants": []} for name in ["android.tap", "ios.tap", "pdf"]
    ])
    assert skill_inventory.public_skill_inventory() == [{"name": "pdf"}]

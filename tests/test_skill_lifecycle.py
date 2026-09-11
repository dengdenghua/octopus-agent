from pathlib import Path
from types import SimpleNamespace
import pytest

from runtime.platform.assets import skill_lifecycle as lifecycle
from runtime.platform.assets import skill_inventory
from runtime.execution.suckers.registry import SkillRegistry, Skill
from runtime.execution.suckers.market_skills import register_market_skills


@pytest.fixture
def env(tmp_path, monkeypatch):
    data, builtin = tmp_path / "data", tmp_path / "builtin"
    (data / "skills").mkdir(parents=True)
    builtin.mkdir()
    monkeypatch.setattr(lifecycle, "app_paths", lambda: SimpleNamespace(data_dir=data))
    monkeypatch.setattr(skill_inventory, "skill_roots", lambda: [(data / "skills", "local"), (builtin, "builtin")])
    registry = SkillRegistry()
    registry.set_state_file(data / "state.json")
    return data, builtin, registry


def package(root, name):
    folder = root / name
    folder.mkdir()
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: example\naliases: [{name}-alias]\n---\nInstructions", encoding="utf-8")
    return folder


def test_disable_aliases_persist_and_enable_without_removing_builtin(env):
    data, builtin, registry = env
    folder = package(builtin, "creator")
    register_market_skills(registry, all_skills_dir=builtin, verify_tests=False)
    lifecycle.manage_skill("creator", "disable", registry)
    assert not registry.is_enabled("creator") and not registry.is_enabled("creator-alias")
    assert lifecycle.skill_management_states(registry)["creator"] == {"enabled": False, "can_toggle": True, "can_uninstall": False}
    restarted = SkillRegistry()
    register_market_skills(restarted, all_skills_dir=builtin, verify_tests=False)
    restarted.set_state_file(data / "state.json")
    assert not restarted.is_enabled("creator")
    lifecycle.manage_skill("creator", "enable", restarted)
    assert restarted.is_enabled("creator-alias") and (folder / "SKILL.md").exists()
    with pytest.raises(ValueError, match="不能"):
        lifecycle.manage_skill("creator", "uninstall", restarted)


def test_uninstall_unregisters_aliases_and_allows_reinstall(env):
    data, builtin, registry = env
    root = data / "skills"
    folder = package(root, "download")
    register_market_skills(registry, all_skills_dir=root, verify_tests=False)
    assert lifecycle.skill_management_states(registry)["download"]["can_uninstall"]
    lifecycle.manage_skill("download", "disable", registry)
    lifecycle.manage_skill("download", "uninstall", registry)
    assert not folder.exists() and not registry.has("download") and not registry.has("download-alias")
    assert "download" not in lifecycle.skill_management_states(registry)
    package(root, "download")
    register_market_skills(registry, all_skills_dir=root, verify_tests=False)
    registry.set_state_file(data / "state.json")
    assert registry.is_enabled("download")


def test_uninstall_restores_bundled_copy(env):
    data, builtin, registry = env
    package(data / "skills", "same")
    preserved = package(builtin, "same")
    register_market_skills(registry, all_skills_dir=data / "skills", verify_tests=False)
    lifecycle.manage_skill("same", "uninstall", registry)
    assert registry.has("same") and (preserved / "SKILL.md").exists()
    assert Path(registry.get("same").handler()["cwd"]) == preserved


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a\\b", "a:stream"])
def test_reject_unsafe_download_paths(env, name):
    with pytest.raises(ValueError):
        lifecycle._download_path(name)


def test_only_inventory_skills_can_be_managed(env):
    _, _, registry = env
    registry.register(Skill(name="delete_file", trusted_source="builtin", handler=lambda: None), verify_tests=False)
    with pytest.raises(KeyError):
        lifecycle.manage_skill("delete_file", "disable", registry)


def test_management_route_enforces_auth_and_deployment_and_updates_runtime(env, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from runtime.sensing.gateway.agent_world_router import create_agent_world_router
    data, builtin, registry = env
    package(builtin, "creator")
    register_market_skills(registry, all_skills_dir=builtin, verify_tests=False)
    protected = FastAPI()
    protected.include_router(create_agent_world_router(skill_registry=registry, require_auth=True))
    url = "/api/agent-market/cloud/skills/creator/manage"
    assert TestClient(protected).post(url, json={"action": "disable"}).status_code in {401, 403}
    app = FastAPI()
    app.include_router(create_agent_world_router(skill_registry=registry))
    client = TestClient(app)
    monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "local")
    assert client.post(url, json={"action": "disable"}).status_code == 200
    assert not registry.is_enabled("creator")
    assert client.post(url, json={"action": "invalid"}).status_code == 400
    monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "commercial")
    assert client.post(url, json={"action": "enable"}).status_code == 403
    assert not registry.is_enabled("creator")

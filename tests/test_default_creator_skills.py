from runtime.execution.suckers.market_skills import register_market_skills
from runtime.execution.suckers.registry import SkillRegistry
from runtime.platform.assets.skill_inventory import scan_local_skills
from runtime.platform.process.paths import bundled_market_skills_dir


def test_creator_skills_are_bundled_discoverable_and_callable_offline(monkeypatch):
    monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "local")
    root = bundled_market_skills_dir()
    creators = {"skill-creator", "plugin-creator", "agent-generator"}
    inventory = {row["name"]: row for row in scan_local_skills([(root, "builtin")])}
    registry = SkillRegistry()
    register_market_skills(registry, all_skills_dir=root, verify_tests=False)
    for name in creators:
        assert inventory[name]["source"] == "builtin"
        assert registry.has(name)
        payload = registry.get(name).handler()
        assert payload["skill"] == name
        assert payload["instructions"].strip()
    assert (root / "plugin-creator/references/echo-plugin.md").is_file()

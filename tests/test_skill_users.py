from runtime.platform.assets.skill_users import build_skill_users
from runtime.execution.suckers.registry import Skill, SkillRegistry


def test_users_are_unique_explicit_local_role_bindings_with_aliases():
    roles = [
        {"id": "one", "display_name": "Eve", "private_skills": ["ad-copywriter", "ad-creative", "ad-creative"]},
        {"id": "two", "display_name": "Leon", "private_skills": ["ad-creative"]},
        {"id": "not-bound", "display_name": "Raven", "private_skills": [], "available_skills": ["ad-creative"]},
        {"id": "template", "is_installed": False, "private_skills": ["ad-creative"]},
    ]
    result = build_skill_users(roles)
    assert result["ad-creative"] == [{"id": "one", "name": "Eve"}, {"id": "two", "name": "Leon"}]
    assert result["ad-copywriter"] == result["ad-creative"]
    assert build_skill_users([]) == {}


def test_runtime_aliases_match_but_other_source_versions_do_not():
    registry = SkillRegistry()
    for name, source in [("creator", "skill://all_skills/creator"),
                         ("make-skill", "skill://all_skills/creator#alias"),
                         ("external-a", "skill://all_skills/external-a")]:
        registry.register(Skill(name=name, trusted_source=source, handler=lambda: {}), verify_tests=False)
    registry.disable("creator")
    roles = [{"id": "leon", "display_name": "Leon", "private_skills": ["make-skill", "creator"]}]
    result = build_skill_users(roles, registry)
    assert result["creator"] == result["make-skill"] == [{"id": "leon", "name": "Leon"}]
    assert "external-a" not in result
    roles[0]["private_skills"] = []
    assert build_skill_users(roles, registry) == {}


def test_invalid_binding_fields_do_not_become_fake_role_links():
    assert build_skill_users([{"id": "one", "private_skills": "pdf"},
                              {"id": "two", "private_skills": [None, {}, " "]},
                              {"private_skills": ["pdf"]}]) == {}

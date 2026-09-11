"""Reverse index of explicit role skill bindings, not invocation history."""
from runtime.execution.skill_aliases import SKILL_ALIAS_TO_CANONICAL, canonical_skill_id


def build_skill_users(agents: list[dict], registry=None) -> dict[str, list[dict]]:
    def resolve(name: str) -> str:
        name = canonical_skill_id(name)
        if registry is not None and registry.has(name):
            skill = registry.get(name)
            source = str(skill.trusted_source or "")
            if source.startswith("skill://all_skills/") and "#alias" in source:
                return canonical_skill_id(source.removeprefix("skill://all_skills/").split("#", 1)[0])
            return skill.name
        return name

    by_skill: dict[str, dict[str, dict]] = {}
    for agent in agents:
        if agent.get("is_installed") is False:
            continue
        role_id = agent.get("id")
        if not isinstance(role_id, str) or not role_id:
            continue
        bindings = agent.get("private_skills", [])
        if not isinstance(bindings, list):
            continue
        user = {"id": role_id, "name": str(agent.get("display_name") or role_id)}
        if isinstance(agent.get("avatar_url"), str) and agent["avatar_url"]:
            user["avatar_url"] = agent["avatar_url"]
        if isinstance(agent.get("icon"), str) and agent["icon"]:
            user["icon"] = agent["icon"]
        for name in bindings:
            if not isinstance(name, str) or not name.strip():
                continue
            key = resolve(name.strip())
            by_skill.setdefault(key, {})[role_id] = user
    result = {name: sorted(users.values(), key=lambda user: (user["name"].casefold(), user["id"]))
              for name, users in by_skill.items()}
    aliases = set(SKILL_ALIAS_TO_CANONICAL)
    if registry is not None:
        aliases.update(registry.all_names())
    for alias in aliases:
        canonical = resolve(alias)
        if canonical in result:
            result[alias] = result[canonical]
    return result

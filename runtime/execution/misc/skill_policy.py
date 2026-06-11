from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

FULL_ACCESS_MARKERS: frozenset[str] = frozenset({
    "*",
    "all",
    "full",
    "inherit_all",
    "\u5168\u90e8",
})


def normalize_skill_name(value: Any) -> str:
    return str(value).strip()


def coerce_skill_names(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None and parsed is not value:
            return coerce_skill_names(parsed)
        for sep in ("\uff0c", "\u3001", ";", "\n", "\t"):
            raw = raw.replace(sep, ",")
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(value, Mapping):
        out: list[str] = []
        for key in (
            "tools",
            "skills",
            "skill_pack",
            "skill_packs",
            "plugins",
            "items",
        ):
            out.extend(coerce_skill_names(value.get(key)))
        return out
    if isinstance(value, Iterable):
        out: list[str] = []
        for item in value:
            out.extend(coerce_skill_names(item))
        return out
    name = normalize_skill_name(value)
    return [name] if name else []


def dedupe_skill_names(names: Iterable[Any]) -> list[str]:
    return list(OrderedDict(
        (name, None)
        for raw in names
        if (name := normalize_skill_name(raw))
    ).keys())


@dataclass
class SkillPolicy:
    allowed: tuple[str, ...] = ()
    sources: dict[str, tuple[str, ...]] = field(default_factory=dict)
    reason_map: dict[str, tuple[str, ...]] = field(default_factory=dict)
    allow_all: bool = False

    def as_list(self) -> list[str]:
        return ["*"] if self.allow_all else list(self.allowed)

    def allows(self, skill_name: Any) -> bool:
        if self.allow_all:
            return True
        return normalize_skill_name(skill_name) in self.reason_map

    def reasons_for(self, skill_name: Any) -> tuple[str, ...]:
        return self.reason_map.get(normalize_skill_name(skill_name), ())


def build_skill_policy(
    source_map: Mapping[str, Any],
    *,
    sort_allowed: bool = False,
) -> SkillPolicy:
    sources: dict[str, tuple[str, ...]] = {}
    reason_lists: dict[str, list[str]] = {}
    ordered: list[str] = []
    allow_all = False

    for source, raw_names in source_map.items():
        names = dedupe_skill_names(coerce_skill_names(raw_names))
        if not names:
            continue
        sources[str(source)] = tuple(names)
        if any(name.lower() in FULL_ACCESS_MARKERS for name in names):
            allow_all = True
        for name in names:
            ordered.append(name)
            reason_lists.setdefault(name, []).append(str(source))

    reason_map = {
        name: tuple(dedupe_skill_names(reasons))
        for name, reasons in reason_lists.items()
    }
    unique_ordered = dedupe_skill_names(ordered)
    allowed = (
        ("*",)
        if allow_all
        else tuple(sorted(unique_ordered) if sort_allowed else unique_ordered)
    )
    return SkillPolicy(
        allowed=allowed,
        sources=sources,
        reason_map=reason_map,
        allow_all=allow_all,
    )


def resolve_agent_skill_policy(agent: Any) -> SkillPolicy:
    from runtime.execution.suckers.layers import ATOMIC_SKILL_NAMES

    source_map: dict[str, Any] = {"atomic": sorted(ATOMIC_SKILL_NAMES)}
    try:
        arms = list(agent.arms)
    except (AttributeError, TypeError):
        arms = []
    for idx, arm in enumerate(arms):
        arm_id = str(getattr(arm, "arm_id", "") or "unknown")
        source = f"arm:{arm_id}"
        if source in source_map:
            source = f"{source}#{idx}"
        source_map[source] = getattr(arm, "allowed_skills", ()) or ()

    extra = getattr(agent, "extra_skills", None)
    if extra:
        source_map["agent:extra"] = extra
    return build_skill_policy(source_map, sort_allowed=True)


def filter_allowed_names(
    names: Iterable[str],
    *,
    policy: SkillPolicy | None = None,
    agent: Any = None,
) -> list[str]:
    if policy is None and agent is not None:
        policy = resolve_agent_skill_policy(agent)
    if policy is None or policy.allow_all:
        return list(names)
    allowed = set(policy.allowed)
    return [name for name in names if name in allowed]


def resolve_context_tool_policy(
    *,
    role_allowlist: Any = None,
    context: Mapping[str, Any] | None = None,
) -> SkillPolicy:
    ctx = context or {}
    mode = normalize_skill_name(ctx.get("tool_allowlist_mode")).lower()
    source_map: dict[str, Any] = {}
    if mode in FULL_ACCESS_MARKERS:
        source_map["mode"] = ["*"]
    if role_allowlist:
        source_map["role"] = role_allowlist

    for key, source in (
        ("extra_tool_allowlist", "dynamic"),
        ("extra_tools", "extra_tools"),
        ("extra_skills", "extra_skills"),
    ):
        values = coerce_skill_names(ctx.get(key))
        if values:
            source_map[source] = values

    return build_skill_policy(source_map)

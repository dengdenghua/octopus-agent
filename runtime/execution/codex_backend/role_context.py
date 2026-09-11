"""Codex-specific contract over the shared Echo role instructions."""

from collections.abc import Mapping
from typing import Any

from runtime.execution.tool_engine.role_instructions import (
    compose_role_instructions,
    resolve_explicit_skill_instructions,
)


def compose_codex_role_instructions(
    agent: Any,
    *,
    context: Mapping[str, Any] | None,
    goal: str,
    registry: Any = None,
) -> str:
    sections = [compose_role_instructions(agent, context=context, goal=goal, registry=registry)]
    sections.append(
        "<octopus-codex-role-contract>\n"
        "You are the standard Octopus role identified above; Codex App Server "
        "is only this role's coding engine. Preserve the role name, soul, "
        "memory, selected mode, group/project identity and response style.\n"
        "Octopus is the capability authority. Use only the dynamic tools "
        "advertised for this turn for Octopus skills, plugins, apps and "
        "delegation. Their results and denials are authoritative. Do not "
        "discover or enable ambient user Codex MCP servers, plugins, skills, "
        "apps, hooks or subagents. Slash commands have already been expanded "
        "by Octopus before this turn.\n"
        "</octopus-codex-role-contract>"
    )
    return "\n\n".join(sections)


__all__ = ["compose_codex_role_instructions", "resolve_explicit_skill_instructions"]

"""Agent documentation skills loaded from ``all_skills``.

These are prompt-as-skill packages copied from public agent-skill
repositories. They are registered explicitly so code/admin mode can
whitelist and call them like normal tools.
"""

from __future__ import annotations

from .market_skills import load_single_market_skill
from .registry import SkillRegistry

AGENT_DOC_SKILL_IDS: tuple[str, ...] = (
    "gemini-api-dev",
    "gemini-interactions-api",
    "gemini-live-api-dev",
    "vertex-ai-api-dev",
    "frontend-ui-engineering",
    "api-and-interface-design",
    "browser-testing-with-devtools",
    "performance-optimization",
    "code-review-and-quality",
    "awesome-design-md",
    "frontend-design",
    "react-best-practices",
    "typescript-best-practices",
    "code-quality",
    "uiux-pro-max",
    "writing-plans",
    "brainstorming",
)


def register_agent_doc_skills(registry: SkillRegistry) -> int:
    registered = 0
    for skill_id in AGENT_DOC_SKILL_IDS:
        if load_single_market_skill(
            registry,
            skill_id,
            ignore_frontmatter_enabled=True,
            verify_tests=False,
        ):
            registered += 1
    return registered


__all__ = ["AGENT_DOC_SKILL_IDS", "register_agent_doc_skills"]

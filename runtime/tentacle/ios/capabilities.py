"""Canonical iOS capability list loaded from ios SKILL.md files.

Mirrors :mod:`runtime.tentacle.mobile.capabilities` but loads skills under
``runtime/tentacle/ios/skills/`` whose names use the ``ios.*`` prefix.
"""

from __future__ import annotations

from pathlib import Path

from runtime.tentacle.llm.skill_manifest import SkillManifestLoader


def ios_skills_root() -> Path:
    """Return manifests from the installed, enabled device plugin."""
    from runtime.tentacle.device_plugins import device_plugin_tools_root
    return device_plugin_tools_root("ios")

def ios_capabilities() -> tuple[str, ...]:
    """Load all iOS capability names from the canonical SKILL.md set."""
    specs = SkillManifestLoader().load_directory(ios_skills_root())
    return tuple(sorted(spec.name for spec in specs if spec.name.startswith("ios.")))


__all__ = [
    "ios_capabilities",
    "ios_skills_root",
]

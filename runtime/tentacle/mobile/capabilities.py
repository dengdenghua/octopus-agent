"""Canonical Android capability list loaded from mobile SKILL.md files."""

from __future__ import annotations

from pathlib import Path

from runtime.tentacle.llm.skill_manifest import SkillManifestLoader


def mobile_skills_root() -> Path:
    """Return manifests from the installed, enabled device plugin."""
    from runtime.tentacle.device_plugins import device_plugin_tools_root
    return device_plugin_tools_root("android")

def android_capabilities() -> tuple[str, ...]:
    """Load all Android capability names from the canonical SKILL.md set."""
    specs = SkillManifestLoader().load_directory(mobile_skills_root())
    return tuple(sorted(spec.name for spec in specs if spec.name.startswith("android.")))


def android_browser_capabilities() -> tuple[str, ...]:
    """Load browser-only Android capabilities for the mobile browser arm."""
    return tuple(
        name
        for name in android_capabilities()
        if name.startswith("android.browser.") and name != "android.browser.install_extension"
    )


__all__ = [
    "android_browser_capabilities",
    "android_capabilities",
    "mobile_skills_root",
]

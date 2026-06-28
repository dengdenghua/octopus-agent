"""Register skills shipped inside imported Codex-format plugins.

Codex plugins copied into ``.octopus/plugins/codex/<plugin>/`` ship
``skills/<skill>/SKILL.md`` bundles in the **same format** octopus already
loads from ``skills/public`` via :func:`register_market_skills`. This bridge
points that same loader at each plugin's ``skills/`` directory so the
plugin's skills become real, callable registry skills:

* discoverable in the skill index (name + summary),
* their handler returns the SKILL.md instructions + bundled scripts, which
  the agent runs through the already-gated ``exec_shell`` path (no skill
  auto-executes anything by itself),
* tagged ``codex://plugin/<plugin>`` so the TrustEngine treats them as
  externally-sourced rather than bundled.

Non-skill codex surfaces are out of scope here: ``mcpServers`` are wired
separately into the MCP config, and ``apps`` / ``commands`` are Codex-UI
formats octopus does not execute.
"""
from __future__ import annotations

import logging
from pathlib import Path

from runtime.platform.plugins.codex_discovery import codex_plugin_roots

from .market_skills import register_market_skills
from .registry import SkillRegistry

_log = logging.getLogger(__name__)


def register_codex_plugin_skills(
    registry: SkillRegistry,
    *,
    roots: list[Path] | None = None,
    verify_tests: bool = False,
) -> int:
    """Register every ``<root>/<plugin>/skills/<skill>/SKILL.md`` skill.

    Returns the total number of skills registered across all installed
    codex plugins. A skill whose name collides with an already-registered
    skill is skipped by the underlying loader (first registration wins), so
    octopus's own skills always take precedence.
    """
    total = 0
    seen_roots: set[Path] = set()
    for raw_root in roots or codex_plugin_roots():
        try:
            root = raw_root.resolve()
        except OSError:
            continue
        if root in seen_roots or not root.is_dir():
            continue
        seen_roots.add(root)
        for plugin_dir in sorted(root.iterdir()):
            skills_dir = plugin_dir / "skills"
            if not skills_dir.is_dir():
                continue
            try:
                count = register_market_skills(
                    registry,
                    all_skills_dir=skills_dir,
                    respect_enabled_flag=False,
                    verify_tests=verify_tests,
                    source=f"codex://plugin/{plugin_dir.name}",
                )
            except Exception as exc:  # noqa: BLE001 — one bad plugin must not break the rest
                _log.warning(
                    "codex_plugin_skills: plugin %r failed to register (%s: %s)",
                    plugin_dir.name, type(exc).__name__, exc,
                )
                continue
            total += count
    if total:
        _log.info(
            "codex_plugin_skills: registered %d skills from codex plugins", total,
        )
    return total


__all__ = ["register_codex_plugin_skills"]

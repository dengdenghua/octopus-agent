"""Register skills imported via tool-migration.

``apply_plan`` stages migrated skill bundles into
``.octopus/imported/<source>/skills/<name>/SKILL.md`` (Codex, Claude, ...). This
registrar loads them through the same SKILL.md loader octopus uses everywhere
(:func:`register_market_skills`), tagged ``imported://<source>`` so the
TrustEngine treats them as externally-sourced and the ReAct catalog keeps them
*search-only* (discoverable + callable on demand, not resident every turn).
"""
from __future__ import annotations

import logging
from pathlib import Path

from .market_skills import register_market_skills
from .registry import SkillRegistry

_log = logging.getLogger(__name__)


def register_imported_skills(
    registry: SkillRegistry,
    *,
    project_root: Path | None = None,
    verify_tests: bool = False,
) -> int:
    """Register every ``.octopus/imported/<source>/skills/<name>/SKILL.md`` skill."""
    root = (project_root or Path.cwd()) / ".octopus" / "imported"
    if not root.is_dir():
        return 0
    total = 0
    for source_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        skills_dir = source_dir / "skills"
        if not skills_dir.is_dir():
            continue
        try:
            total += register_market_skills(
                registry,
                all_skills_dir=skills_dir,
                respect_enabled_flag=False,
                verify_tests=verify_tests,
                source=f"imported://{source_dir.name}",
            )
        except Exception as exc:  # noqa: BLE001 — one bad source must not break the rest
            _log.warning(
                "imported_skills: source %r failed (%s: %s)",
                source_dir.name, type(exc).__name__, exc,
            )
    if total:
        _log.info("imported_skills: registered %d migrated skills", total)
    return total


__all__ = ["register_imported_skills"]

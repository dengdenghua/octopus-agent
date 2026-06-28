"""Codex-format plugin skills must register as callable registry skills.

Regression for the compatibility bridge that turns imported codex plugins
(``.octopus/plugins/codex/<plugin>/skills/<skill>/SKILL.md``) from
catalog-only shells into real, callable skills via the shared
``register_market_skills`` loader.
"""
from __future__ import annotations

from pathlib import Path

from runtime.execution.suckers.codex_plugin_skills import register_codex_plugin_skills
from runtime.execution.suckers.registry import Skill, SkillRegistry


def _make_plugin(root: Path, plugin: str, skill: str, *, name: str | None = None) -> Path:
    skill_dir = root / plugin / "skills" / skill
    (skill_dir / "scripts").mkdir(parents=True)
    front = f"name: {name}\n" if name else ""
    (skill_dir / "SKILL.md").write_text(
        f"---\n{front}description: Do the {skill} thing\n---\n"
        f"Step 1. Run the bundled script.\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "run.py").write_text("print('hi')\n", encoding="utf-8")
    return skill_dir


def test_codex_plugin_skill_registers_and_is_callable(tmp_path: Path) -> None:
    root = tmp_path / ".octopus" / "plugins" / "codex"
    _make_plugin(root, "github", "gh-fix-ci")

    reg = SkillRegistry()
    n = register_codex_plugin_skills(reg, roots=[root])

    assert n == 1
    assert reg.has("gh-fix-ci")
    sk = reg.get("gh-fix-ci")
    # Provenance carries the real codex origin so the TrustEngine can gate it.
    assert sk.trusted_source == "codex://plugin/github/gh-fix-ci"

    # Calling the skill yields its SKILL.md instructions + bundled scripts —
    # the agent then runs the script through the gated exec_shell path.
    out = sk.handler()
    assert "Run the bundled script" in out["instructions"]
    assert any(s["path"] == "scripts/run.py" for s in out["scripts"])
    assert out["cwd"].endswith("github/skills/gh-fix-ci")


def test_codex_plugin_skill_uses_frontmatter_name(tmp_path: Path) -> None:
    root = tmp_path / ".octopus" / "plugins" / "codex"
    _make_plugin(root, "datadog", "dir-name", name="dd-metrics")

    reg = SkillRegistry()
    register_codex_plugin_skills(reg, roots=[root])

    assert reg.has("dd-metrics")
    assert not reg.has("dir-name")


def test_existing_skill_wins_over_codex_collision(tmp_path: Path) -> None:
    root = tmp_path / ".octopus" / "plugins" / "codex"
    _make_plugin(root, "github", "read_file")  # collides with a builtin name

    reg = SkillRegistry()
    reg.register(
        Skill(
            name="read_file",
            description="builtin",
            trusted_source="builtin://read_file",
            handler=lambda **_: {"ok": True},
        ),
        verify_tests=False,
    )
    register_codex_plugin_skills(reg, roots=[root])

    # The builtin is not clobbered by the codex plugin's same-named skill.
    assert reg.get("read_file").trusted_source == "builtin://read_file"


def test_no_codex_dir_is_noop(tmp_path: Path) -> None:
    reg = SkillRegistry()
    assert register_codex_plugin_skills(reg, roots=[tmp_path / "absent"]) == 0


def test_codex_plugin_skill_is_search_only_not_resident(tmp_path: Path) -> None:
    """Codex plugin skills are callable + searchable but NOT in the always-on
    catalog — they inject dynamically on search+use, not resident every turn.
    """
    from runtime.core.cerebrum.react_context import _format_skill_catalog

    root = tmp_path / ".octopus" / "plugins" / "codex"
    _make_plugin(root, "github", "gh-fix-ci")
    reg = SkillRegistry()
    register_codex_plugin_skills(reg, roots=[root])

    # Registered → callable, and discoverable via search (registry listing).
    assert reg.has("gh-fix-ci")
    assert "gh-fix-ci" in set(reg.all_names())

    # ...but kept OUT of the per-turn skill catalog, even for a matching goal.
    catalog = _format_skill_catalog(reg, agent=None, goal="fix the github ci")
    assert "gh-fix-ci" not in catalog

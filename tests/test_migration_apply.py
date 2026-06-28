"""Apply step: stage a migration plan into octopus, idempotently + safely.

Hermetic — builds a fake source on tmp_path, applies into a tmp project root,
and asserts staging + that migrated skills register (search-only) and are
callable. Nothing touches the real machine or repo.
"""
from __future__ import annotations

import json
from pathlib import Path

from runtime.core.cerebrum.react_context import _format_skill_catalog
from runtime.execution.suckers.imported_skills import register_imported_skills
from runtime.execution.suckers.registry import SkillRegistry
from runtime.platform.migration import MigrationItem, MigrationPlan, apply_plan


def _fake_plan(src: Path) -> MigrationPlan:
    skill_dir = src / "myskill"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: myskill\ndescription: do a thing\n---\nrun the script\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "x.py").write_text("print('hi')\n", encoding="utf-8")
    agents = src / "AGENTS.md"
    agents.write_text("always write tests\n", encoding="utf-8")
    return MigrationPlan("codex", (
        MigrationItem("skill", "myskill", "codex", "do a thing", str(skill_dir)),
        MigrationItem("memory", "AGENTS.md", "codex", "", str(agents)),
        MigrationItem("mcp_server", "node_repl", "codex", "", str(src / "config.toml"), needs=("node",)),
    ))


def test_apply_stages_skill_memory_mcp(tmp_path: Path) -> None:
    plan = _fake_plan(tmp_path / "src")
    proj = tmp_path / "proj"

    report = apply_plan(plan, project_root=proj)
    assert report.applied == {"skill": 1, "memory": 1, "mcp_server": 1}

    base = proj / ".octopus" / "imported" / "codex"
    # skill bundle copied whole (SKILL.md + bundled scripts)
    assert (base / "skills" / "myskill" / "SKILL.md").is_file()
    assert (base / "skills" / "myskill" / "scripts" / "x.py").is_file()
    # memory staged for review
    assert (base / "memory" / "AGENTS.md").is_file()
    # mcp recorded disabled, never auto-launched
    mcp = json.loads((base / "mcp.disabled.json").read_text(encoding="utf-8"))
    assert mcp["mcp_servers"][0]["name"] == "node_repl"
    assert mcp["mcp_servers"][0]["enabled"] is False


def test_apply_is_idempotent(tmp_path: Path) -> None:
    plan = _fake_plan(tmp_path / "src")
    proj = tmp_path / "proj"
    apply_plan(plan, project_root=proj)
    again = apply_plan(plan, project_root=proj)
    assert again.skipped.get("skill") == 1
    assert again.skipped.get("memory") == 1
    assert again.applied.get("skill", 0) == 0


def test_apply_dry_run_writes_nothing(tmp_path: Path) -> None:
    plan = _fake_plan(tmp_path / "src")
    proj = tmp_path / "proj"
    report = apply_plan(plan, project_root=proj, dry_run=True)
    assert report.applied.get("skill") == 1          # counted
    assert not (proj / ".octopus").exists()          # but nothing written


def test_applied_skills_register_callable_and_search_only(tmp_path: Path) -> None:
    plan = _fake_plan(tmp_path / "src")
    proj = tmp_path / "proj"
    apply_plan(plan, project_root=proj)

    reg = SkillRegistry()
    n = register_imported_skills(reg, project_root=proj)
    assert n == 1
    assert reg.has("myskill")
    assert str(reg.get("myskill").trusted_source).startswith("imported://codex")
    # callable: handler returns instructions + bundled scripts
    out = reg.get("myskill").handler()
    assert "run the script" in out["instructions"]
    # search-only: NOT in the resident per-turn catalog
    catalog = _format_skill_catalog(reg, agent=None, goal="myskill thing")
    assert "myskill" not in catalog


def test_apply_only_selected_kinds(tmp_path: Path) -> None:
    plan = _fake_plan(tmp_path / "src")
    proj = tmp_path / "proj"
    report = apply_plan(plan, project_root=proj, kinds={"skill"})
    assert report.applied == {"skill": 1}
    base = proj / ".octopus" / "imported" / "codex"
    assert (base / "skills" / "myskill").is_dir()
    assert not (base / "memory").exists()
    assert not (base / "mcp.disabled.json").exists()

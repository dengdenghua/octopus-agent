from __future__ import annotations

import json
from pathlib import Path

import pytest

from octopus_runtime.bootstrap import bootstrap_skills, read_lockfile, write_lockfile


def test_read_lockfile_missing_file_returns_empty(tmp_path) -> None:
    assert read_lockfile(tmp_path / "missing.lock.json") == {"skills": []}


def test_read_lockfile_rejects_invalid_json(tmp_path) -> None:
    lockfile = tmp_path / "skills.lock.json"
    lockfile.write_text("{not json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        read_lockfile(lockfile)


def test_read_lockfile_rejects_non_object(tmp_path) -> None:
    lockfile = tmp_path / "skills.lock.json"
    lockfile.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        read_lockfile(lockfile)


def test_read_lockfile_rejects_non_list_skills(tmp_path) -> None:
    lockfile = tmp_path / "skills.lock.json"
    lockfile.write_text('{"skills": "research-pack"}', encoding="utf-8")

    with pytest.raises(ValueError, match="skills must be a list"):
        read_lockfile(lockfile)


def test_bootstrap_rejects_unsafe_lockfile_slug_before_sync(tmp_path) -> None:
    lockfile = tmp_path / "skills.lock.json"
    lockfile.write_text('{"skills": ["skill/../escape"]}', encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe registry asset id"):
        bootstrap_skills(lockfile, tmp_path / "skills")


def test_bootstrap_rejects_non_skill_asset_lockfile_entry(tmp_path) -> None:
    lockfile = tmp_path / "skills.lock.json"
    lockfile.write_text('{"skills": ["role/researcher"]}', encoding="utf-8")

    with pytest.raises(ValueError, match="must reference a skill asset"):
        bootstrap_skills(lockfile, tmp_path / "skills")


def test_bootstrap_marks_present_for_bare_slug_and_asset_id(tmp_path) -> None:
    skills = tmp_path / "skills"
    (skills / "research-pack").mkdir(parents=True)
    (skills / "research-pack" / "SKILL.md").write_text("present", encoding="utf-8")
    lockfile = tmp_path / "skills.lock.json"
    lockfile.write_text(
        json.dumps({"skills": ["research-pack", {"slug": "skill/research-pack"}]}),
        encoding="utf-8",
    )

    synced, present, errors = bootstrap_skills(lockfile, skills)

    assert synced == []
    assert present == ["research-pack", "research-pack"]
    assert errors == []


def test_bootstrap_surfaces_skipped_sync_results(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    lockfile = tmp_path / "skills.lock.json"
    lockfile.write_text('{"skills": ["research-pack"]}', encoding="utf-8")

    def fake_sync_skills(*_args, **_kwargs):
        return [], [("research-pack", "type=plugin/kind=code")], []

    monkeypatch.setattr("octopus_runtime.bootstrap.sync_skills", fake_sync_skills)

    synced, present, errors = bootstrap_skills(lockfile, tmp_path / "skills")

    assert synced == []
    assert present == []
    assert errors == [("research-pack", "skipped:type=plugin/kind=code")]


def test_write_lockfile_only_includes_real_safe_skill_dirs(tmp_path) -> None:
    skills = tmp_path / "skills"
    (skills / "research-pack").mkdir(parents=True)
    (skills / "research-pack" / "SKILL.md").write_text("ok", encoding="utf-8")
    (skills / "bad/name").mkdir(parents=True)
    (skills / "bad:name").mkdir()
    (skills / "bad:name" / "SKILL.md").write_text("bad", encoding="utf-8")
    (skills / "not-a-skill").mkdir()
    (skills / "plain-file").write_text("not a dir", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("outside", encoding="utf-8")
    (skills / "linked-pack").symlink_to(outside, target_is_directory=True)
    out = tmp_path / "skills.lock.json"

    slugs = write_lockfile(skills, out)

    assert slugs == ["research-pack"]
    assert json.loads(out.read_text(encoding="utf-8")) == {"skills": ["research-pack"]}


def test_write_lockfile_is_atomic_on_replace_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills = tmp_path / "skills"
    (skills / "research-pack").mkdir(parents=True)
    (skills / "research-pack" / "SKILL.md").write_text("ok", encoding="utf-8")
    out = tmp_path / "skills.lock.json"
    out.write_text('{"skills": ["old"]}\n', encoding="utf-8")
    original_replace = Path.replace

    def fail_temp_replace(self: Path, target: Path) -> Path:
        if self.name.startswith(".skills.lock.json.") and target.name == "skills.lock.json":
            raise OSError("replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_temp_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_lockfile(skills, out)

    assert out.read_text(encoding="utf-8") == '{"skills": ["old"]}\n'
    assert list(tmp_path.glob(".skills.lock.json.*")) == []

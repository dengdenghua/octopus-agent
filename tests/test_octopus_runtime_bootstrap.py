from __future__ import annotations

import json

import pytest

from octopus_runtime.bootstrap import bootstrap_skills, read_lockfile


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

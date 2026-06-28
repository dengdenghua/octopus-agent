"""HTTP migration API: preview / apply, auth-gated.

Apply tests point HOME at a fake ~/.codex and chdir to a temp project, so the
endpoint reads/writes only under tmp_path — never the real machine or repo.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from runtime.platform.ui.app import create_app  # noqa: E402
from runtime.safety.auth.identity import Identity, IdentityStore  # noqa: E402


def _fake_codex_home(home: Path) -> None:
    plugin = home / ".codex" / "plugins" / "cache" / "mkt" / "plug" / "1.0"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / ".codex-plugin" / "plugin.json").write_text('{"name": "plug"}', encoding="utf-8")
    skill = plugin / "skills" / "s1"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: s1\ndescription: a skill\n---\nbody\n", encoding="utf-8",
    )


def test_preview_open_in_dev_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = TestClient(create_app())
    r = client.get("/api/migrate/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["schema"] == "octopus.migrate.preview.v1"
    assert "codex" in body["supported"]
    assert "claude" in body["supported"]
    assert isinstance(body["plans"], list)


def test_apply_stages_and_activates_under_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _fake_codex_home(home)
    monkeypatch.setenv("HOME", str(home))
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)

    client = TestClient(create_app())
    r = client.post("/api/migrate/apply", json={"sources": "codex", "activate": True})
    assert r.status_code == 200
    body = r.json()
    assert body["schema"] == "octopus.migrate.apply.v1"
    codex = next(rep for rep in body["reports"] if rep["source"] == "codex")
    assert codex["applied"].get("skill", 0) >= 1
    # staged on disk under the temp project
    assert (proj / ".octopus" / "imported" / "codex" / "skills" / "s1" / "SKILL.md").is_file()
    assert body["activation"] is not None


def test_migrate_requires_auth_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    app = create_app(cocoloop_require_auth=True, cocoloop_identity_store=store)
    client = TestClient(app)

    assert client.get("/api/migrate/preview").status_code == 401
    assert (
        client.get("/api/migrate/preview", headers={"Authorization": "Bearer sk-alice"}).status_code
        != 401
    )

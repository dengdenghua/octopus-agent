import io
import json
import tarfile
import zipfile
import stat
from pathlib import Path

import pytest

from runtime.platform.plugins import external_skills as ext

SHA = "a" * 40


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tf:
        for name, body in entries.items():
            item = tarfile.TarInfo(name if name.startswith("/") else "repo-commit/" + name)
            item.size = len(body)
            tf.addfile(item, io.BytesIO(body))
    return output.getvalue()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ext, "_cache", lambda: tmp_path / "cache")
    return tmp_path / "cache"


def test_install_pins_version_namespaces_identity_and_preserves_resources(cache, tmp_path, monkeypatch):
    body = archive({"skills/demo/SKILL.md": b"---\nname: demo\ndescription: useful\n---\nRead references/guide.md\n",
                    "skills/demo/references/guide.md": b"reference content",
                    "skills/other/SKILL.md": b"do not install",
                    "LICENSE": b"repository license"})
    rows = ext._rows("openai/skills", SHA, ext._files(body), "openai")
    ext._remember(rows)
    seen = []
    def download(repo, commit):
        seen.append((repo, commit))
        return body
    monkeypatch.setattr(ext, "_archive", download)
    result = ext.install_external_skill(rows[0]["name"], skills_dir=tmp_path / "skills")
    target = Path(result["path"])
    meta, instructions = ext._frontmatter((target / "SKILL.md").read_bytes())
    assert meta["name"] == rows[0]["name"]
    assert "Read references/guide.md" in instructions
    assert (target / "references/guide.md").read_text() == "reference content"
    assert (target / "REPOSITORY-LICENSE").read_text() == "repository license"
    assert not (target / "other").exists()
    assert json.loads((target / ".source.json").read_text(encoding="utf-8"))["commit"] == SHA
    assert ext.install_external_skill(rows[0]["name"], skills_dir=tmp_path / "skills")["already_exists"]
    assert seen == [("openai/skills", SHA)]


@pytest.mark.parametrize("name", ["../escape", "/absolute", "skills/a:stream", "skills\\escape"])
def test_archive_rejects_traversal_and_windows_paths(name):
    with pytest.raises(ValueError):
        ext._files(archive({name: b"unsafe"}))


def test_archive_never_materializes_symlinks():
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tf:
        item = tarfile.TarInfo("root/skills/link")
        item.type = tarfile.SYMTYPE
        item.linkname = "../../../outside"
        tf.addfile(item)
    links = set()
    assert ext._files(output.getvalue(), links=links) == {}
    assert links == {"skills/link"}


def test_sources_fail_independently_and_cached_official_is_usable(cache, monkeypatch):
    cache.mkdir(parents=True)
    (cache / "openai.json").write_text(json.dumps({"checked_at": 1, "items": [{"name": "cached"}]}))
    monkeypatch.setattr(ext, "_json", lambda url: (_ for _ in ()).throw(RuntimeError("offline")))
    result = ext.list_external_skills()
    assert result["items"] == [{"name": "cached"}]
    states = {row["source"]: row["state"] for row in result["meta"]["sources"]}
    assert states == {"openai": "stale", "anthropic": "unavailable", "vercel": "unavailable", "skills.sh": "search_required", "minimax-design": "unavailable"}


def test_search_uses_github_identity_rejects_malicious_sources_and_never_executes(cache, monkeypatch):
    monkeypatch.setattr(ext, "_json", lambda url: {"skills": [
        {"name": "demo", "source": "team/skills"}, {"name": "demo", "source": "other/skills"},
        {"name": "evil", "source": "https://127.0.0.1/private"}]})
    rows, state = ext._search("frontend")
    assert len(rows) == 2 and state["state"] == "ready"
    assert rows[0]["name"] != rows[1]["name"]
    assert all(row["source_url"].startswith("https://github.com/") for row in rows)


def test_search_does_not_overwrite_pinned_selection(cache):
    row = {"name": ext._id("openai/skills", "demo"), "commit": SHA}
    ext._remember([row])
    ext._remember([{**row, "commit": None}])
    assert json.loads((cache / "index.json").read_text())[row["name"]]["commit"] == SHA


def test_install_rejects_unknown_ids(cache, tmp_path):
    with pytest.raises(ValueError):
        ext.install_external_skill("../../bad", skills_dir=tmp_path)
    with pytest.raises(ValueError):
        ext.install_external_skill("external-" + "a" * 24, skills_dir=tmp_path)


def test_official_curated_paths_are_visible_but_system_skills_are_not():
    body = b"---\nname: demo\ndescription: useful\n---\nInstructions"
    files = {"skills/.curated/demo/SKILL.md": body, "skills/.system/private/SKILL.md": body}
    assert len(ext._rows("openai/skills", SHA, files, "openai")) == 1


def test_api_external_catalog_paginates_without_fetching_echo_catalog(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from runtime.sensing.gateway.agent_world_router import create_agent_world_router

    monkeypatch.setattr(ext, "list_external_skills", lambda search: {
        "items": [{"name": "one"}, {"name": "two"}], "total": 2,
        "meta": {"sources": [{"source": "skills.sh", "state": "ready", "count": 2}]}})
    app = FastAPI()
    app.include_router(create_agent_world_router())
    response = TestClient(app).get("/api/agent-market/cloud/skills?source=external&search=frontend&offset=1&limit=1")
    assert response.status_code == 200
    assert response.json()["items"] == [{"name": "two"}]
    assert response.json()["total"] == 2


def test_design_catalog_paginates_and_requires_version_for_install(cache, tmp_path, monkeypatch):
    calls = []
    def fetch(url):
        calls.append(url)
        if "page=1&" in url:
            return {"total": 2, "skills": [{"name": "storyboard", "display_name_zh": "分镜", "summary_zh": "规划镜头", "version": "1.0", "tags_cn": ["短剧漫剧"]}]}
        return {"total": 2, "skills": [{"name": "dubbing", "display_name_zh": "配音"}]}
    monkeypatch.setattr(ext, "_json", fetch)
    rows, state = ext._minimax_design()
    assert len(calls) == 2 and state["count"] == 2 and state["state"] == "ready"
    assert rows[0]["display_name"] == "分镜" and rows[0]["tags"] == ["短剧漫剧"]
    assert not rows[0]["catalog_only"] and rows[1]["catalog_only"]
    assert all(row["source"] == "minimax-design" for row in rows)
    assert ext._minimax_design()[0] == rows
    assert len(calls) == 2
    with pytest.raises(ValueError, match="MiniMax Design"):
        ext.install_external_skill(rows[1]["name"], skills_dir=tmp_path / "skills")
    assert not (tmp_path / "skills").exists()


def test_design_partial_refresh_keeps_previous_complete_catalog(cache, monkeypatch):
    cache.mkdir(parents=True)
    old = [{"name": "old", "catalog_only": True}]
    (cache / "minimax-design.json").write_text(json.dumps({"checked_at": 1, "items": old}))
    monkeypatch.setattr(ext, "_json", lambda url: {"total": 2, "skills": [{"name": "repeated"}]})
    rows, state = ext._minimax_design()
    assert rows == old and state["state"] == "stale"
    assert json.loads((cache / "minimax-design.json").read_text())["items"] == old


def zip_package(entries=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, body in (entries or {
            "SKILL.md": b"---\nname: story\ndescription: story workflow\n---\nRead references/guide.md\n",
            "meta.yaml": b"version: 1.2.3\n",
            "references/guide.md": b"original resource",
            "LICENSE": b"original license",
        }).items():
            zf.writestr(path, body)
    return output.getvalue()


def design_row():
    return {"name": ext._id("minimax-design/catalog", "story"), "original_name": "story",
            "source": "minimax-design", "version": "1.2.3", "catalog_only": False}


def test_design_install_version_resources_provenance_and_no_overwrite(cache, tmp_path, monkeypatch):
    row, body, calls = design_row(), zip_package(), []
    ext._remember([row])
    def download(url, **kwargs):
        calls.append(url)
        assert kwargs["max_bytes"] == ext.MAX_ARCHIVE
        return body
    monkeypatch.setattr(ext, "fetch_public_https_bytes", download)
    result = ext.install_external_skill(row["name"], skills_dir=tmp_path / "skills")
    target = Path(result["path"])
    meta, instructions = ext._frontmatter((target / "SKILL.md").read_bytes())
    assert meta["name"] == row["name"] and meta["version"] == "1.2.3"
    assert "Read references/guide.md" in instructions
    assert (target / "references/guide.md").read_bytes() == b"original resource"
    assert (target / "LICENSE").read_bytes() == b"original license"
    assert ext._frontmatter((target / "SKILL.original.md").read_bytes())[0]["name"] == "story"
    provenance = json.loads((target / ".source.json").read_text())
    assert provenance["archive_sha256"] == ext.hashlib.sha256(body).hexdigest()
    assert calls == ["https://design.minimaxi.com/api/v1/skills/market/download?name=story&version=1.2.3"]
    (target / "references/guide.md").write_bytes(b"user edit")
    assert ext.install_external_skill(row["name"], skills_dir=tmp_path / "skills")["already_exists"]
    assert len(calls) == 1 and (target / "references/guide.md").read_bytes() == b"user edit"


@pytest.mark.parametrize("bad", ["../escape", "/absolute", "C:/file", "a\\b", "CON.txt", "a.", "a:stream", ".source.json"])
def test_design_zip_rejects_unsafe_paths(bad):
    body = zip_package({"SKILL.md": b"skill", bad: b"bad"})
    # Windows ZipInfo normalizes separators when creating the fixture.
    if bad == "a\\b":
        body = body.replace(b"a/b", b"a\\b")
    with pytest.raises(ValueError):
        ext._zip_files(body)


@pytest.mark.parametrize("entries", [
    {"SKILL.md": b"skill", "skill.md": b"collision"},
    {"SKILL.md": b"skill", "a": b"file", "a/b": b"child"},
    {"SKILL.md": b"skill", "other/SKILL.md": b"ambiguous"},
    {"story/SKILL.md": b"skill", "unrelated": b"file"},
])
def test_design_zip_rejects_collisions_and_ambiguous_roots(entries):
    with pytest.raises(ValueError):
        ext._zip_files(zip_package(entries))


def test_design_zip_rejects_symlinks_and_limits(monkeypatch):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zf:
        link = zipfile.ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(link, "../outside")
    with pytest.raises(ValueError, match="unsupported"):
        ext._zip_files(output.getvalue())
    monkeypatch.setattr(ext, "MAX_FILE", 4)
    with pytest.raises(ValueError, match="limits"):
        ext._zip_files(zip_package())


@pytest.mark.parametrize("name,version", [("different", "1.2.3"), ("story", "9.0")])
def test_design_install_rejects_mismatched_package_atomically(cache, tmp_path, monkeypatch, name, version):
    row = design_row()
    ext._remember([row])
    body = zip_package({"SKILL.md": f"---\nname: {name}\ndescription: useful\n---\nbody".encode(),
                        "meta.yaml": f"version: {version}".encode()})
    monkeypatch.setattr(ext, "fetch_public_https_bytes", lambda *args, **kwargs: body)
    with pytest.raises(ValueError, match="mismatch"):
        ext.install_external_skill(row["name"], skills_dir=tmp_path / "skills")
    assert not (tmp_path / "skills" / row["name"]).exists()


def test_design_refreshes_legacy_catalog_before_ttl(cache, monkeypatch):
    cache.mkdir()
    (cache / "minimax-design.json").write_text(json.dumps({"checked_at": ext.time.time(), "items": []}))
    monkeypatch.setattr(ext, "_json", lambda url: {"total": 1, "skills": [{"name": "story", "version": "1.2.3"}]})
    rows, _ = ext._minimax_design()
    assert len(rows) == 1 and not rows[0]["catalog_only"]
    assert json.loads((cache / "index.json").read_text(encoding="utf-8"))[rows[0]["name"]]["catalog_only"] is False

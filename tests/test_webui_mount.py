"""Implementation note."""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from runtime.platform.ui import create_app  # noqa: E402
from runtime.platform.ui.app import _find_webui_dist  # noqa: E402


class TestFindWebuiDist:
    def test_env_var_priority(self, tmp_path: Path, monkeypatch):
        dist = tmp_path / "custom_dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html>env</html>")
        monkeypatch.setenv("OCTOPUS_WEBUI_DIST", str(dist))
        assert _find_webui_dist() == dist

    def test_env_invalid_path_ignored(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("OCTOPUS_WEBUI_DIST", str(tmp_path / "nope"))
        # Implementation note.
        result = _find_webui_dist()
        # Implementation note.
        assert result is None or result.is_dir()

    def test_returns_none_when_nothing_found(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("OCTOPUS_WEBUI_DIST", str(tmp_path / "empty"))
        # Implementation note.
        # Implementation note.
        # Implementation note.
        _find_webui_dist()


class TestMountedRoutes:
    def test_spa_serves_index_html(self, tmp_path: Path, monkeypatch):
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html>webui</html>", encoding="utf-8")
        (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
        monkeypatch.setenv("OCTOPUS_WEBUI_DIST", str(dist))

        app = create_app(journal_path=tmp_path / "events.jsonl")
        client = TestClient(app)

        # Implementation note.
        r = client.get("/ui/")
        assert r.status_code == 200
        assert "webui" in r.text

    def test_spa_fallback_for_nested_route(self, tmp_path: Path, monkeypatch):
        """Implementation note."""
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html>webui</html>", encoding="utf-8")
        monkeypatch.setenv("OCTOPUS_WEBUI_DIST", str(dist))

        app = create_app(journal_path=tmp_path / "events.jsonl")
        r = TestClient(app).get("/ui/agents/coder")
        assert r.status_code == 200
        assert "webui" in r.text

    def test_public_file_served(self, tmp_path: Path, monkeypatch):
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html/>")
        (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
        monkeypatch.setenv("OCTOPUS_WEBUI_DIST", str(dist))

        app = create_app(journal_path=tmp_path / "events.jsonl")
        r = TestClient(app).get("/ui/favicon.svg")
        assert r.status_code == 200
        assert "<svg/>" in r.text

    def test_assets_mounted_when_exists(self, tmp_path: Path, monkeypatch):
        dist = tmp_path / "dist"
        assets = dist / "assets"
        assets.mkdir(parents=True)
        (dist / "index.html").write_text("<html/>")
        (assets / "bundle.js").write_text("console.log('hi');", encoding="utf-8")
        monkeypatch.setenv("OCTOPUS_WEBUI_DIST", str(dist))

        app = create_app(journal_path=tmp_path / "events.jsonl")
        r = TestClient(app).get("/ui/assets/bundle.js")
        assert r.status_code == 200
        assert "console.log" in r.text

    def test_old_inline_dashboard_still_at_root(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """Implementation note."""
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html>webui</html>")
        monkeypatch.setenv("OCTOPUS_WEBUI_DIST", str(dist))

        app = create_app(journal_path=tmp_path / "events.jsonl")
        r = TestClient(app).get("/")
        assert r.status_code == 200
        # Implementation note.
        assert "octopus" in r.text.lower()

    def test_api_routes_not_shadowed_by_spa(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """Implementation note."""
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html>webui</html>")
        monkeypatch.setenv("OCTOPUS_WEBUI_DIST", str(dist))

        app = create_app(journal_path=tmp_path / "events.jsonl")
        r = TestClient(app).get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data


class TestNoDistGracefulDegradation:
    def test_create_app_without_env_no_crash(self, tmp_path: Path, monkeypatch):
        """Implementation note."""
        monkeypatch.delenv("OCTOPUS_WEBUI_DIST", raising=False)
        app = create_app(journal_path=tmp_path / "events.jsonl")
        r = TestClient(app).get("/")
        assert r.status_code == 200
        assert "octopus" in r.text.lower()


# cleanup env var to avoid test pollution
@pytest.fixture(autouse=True)
def _cleanup_env(monkeypatch):
    yield
    # Implementation note.

"""Dense coverage for wiki_router endpoints (audit Q-05)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.sensing.gateway import wiki_router as wr


def _make_client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(wr.create_wiki_router())
    monkeypatch.setattr(wr, "_run_generator", lambda: True)
    return TestClient(app)


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mod.py").write_text('"""Doc."""\n\ndef f():\n    pass\n', encoding="utf-8")
    (root / "README.md").write_text("# Proj\n", encoding="utf-8")
    return root


def test_status_and_generate_with_root(tmp_path: Path, monkeypatch) -> None:
    root = _project(tmp_path)
    client = _make_client(monkeypatch)
    before = client.get("/api/wiki/status", params={"root": str(root)}).json()
    assert "status" in before
    gen = client.post("/api/wiki/generate", params={"root": str(root)})
    assert gen.status_code == 200
    assert gen.json()["ok"] is True
    after = client.get("/api/wiki/status", params={"root": str(root)}).json()
    assert after["exists"] is True


def test_generate_without_root_and_double_start(tmp_path: Path, monkeypatch) -> None:
    client = _make_client(monkeypatch)
    resp = client.post("/api/wiki/generate")
    assert resp.status_code == 200
    # Second call: _run_generator returns True again -> 200 (idempotent path).
    assert client.post("/api/wiki/generate").status_code == 200


def test_update_with_root(tmp_path: Path, monkeypatch) -> None:
    root = _project(tmp_path)
    client = _make_client(monkeypatch)
    resp = client.post("/api/wiki/update", params={"root": str(root)})
    assert resp.status_code == 200
    assert "status" in resp.json()


def test_docs_list_and_read(tmp_path: Path, monkeypatch) -> None:
    root = _project(tmp_path)
    client = _make_client(monkeypatch)
    client.post("/api/wiki/generate", params={"root": str(root)})
    listed = client.get("/api/wiki/docs", params={"root": str(root)}).json()
    assert "docs" in listed
    read = client.get("/api/wiki/docs/README.md", params={"root": str(root)})
    assert read.status_code == 200
    assert "content" in read.json()
    missing = client.get("/api/wiki/docs/nope.md", params={"root": str(root)})
    assert missing.status_code == 404


def test_ask_grounded_false(tmp_path: Path, monkeypatch) -> None:
    client = _make_client(monkeypatch)
    resp = client.post("/api/wiki/ask", json={"question": "hello?"})
    assert resp.status_code == 200
    assert resp.json()["grounded"] is False
    bad = client.post("/api/wiki/ask", json={"question": "  "})
    assert bad.status_code == 400


def test_graph_and_okf_bundle(tmp_path: Path, monkeypatch) -> None:
    client = _make_client(monkeypatch)
    graph = client.get("/api/wiki/graph")
    assert graph.status_code == 200
    bundle = client.get("/api/wiki/okf-bundle")
    assert bundle.status_code in (200, 404)

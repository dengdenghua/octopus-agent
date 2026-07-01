from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import runtime.sensing.gateway.uploads_router as uploads_router
from runtime.sensing.gateway.uploads_router import create_uploads_router


class _ThreadStore:
    def ensure_thread(self, thread_id: str) -> None:
        self.thread_id = thread_id


def _client(workspace_root: Path, legacy_root: Path | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(create_uploads_router(
        thread_store=_ThreadStore(),
        workspace_root=workspace_root,
        legacy_upload_root=legacy_root,
    ))
    return TestClient(app)


def _legacy_client(upload_root: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_uploads_router(
        thread_store=_ThreadStore(),
        upload_root=upload_root,
    ))
    return TestClient(app)


def test_uploads_write_to_workspace_upload_dir(tmp_path: Path) -> None:
    client = _client(tmp_path / "workspaces")

    response = client.post(
        "/api/threads/th-1/uploads",
        files={"files": ("brief.md", b"# brief\n", "text/markdown")},
    )

    assert response.status_code == 200
    upload_path = tmp_path / "workspaces" / "th-1" / "upload" / "brief.md"
    assert upload_path.read_bytes() == b"# brief\n"
    assert Path(response.json()["files"][0]["path"]) == upload_path.resolve()
    assert (tmp_path / "workspaces" / "th-1" / "workspace.json").is_file()


def test_upload_listing_reads_workspace_before_legacy(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspaces"
    legacy_root = tmp_path / "thread_uploads"
    (legacy_root / "th-1").mkdir(parents=True)
    (legacy_root / "th-1" / "legacy.txt").write_text("old", encoding="utf-8")
    client = _client(workspace_root, legacy_root)
    client.post(
        "/api/threads/th-1/uploads",
        files={"files": ("new.txt", b"new", "text/plain")},
    )

    response = client.get("/api/threads/th-1/uploads/list")

    assert response.status_code == 200
    files = response.json()["files"]
    assert [item["filename"] for item in files] == ["new.txt", "legacy.txt"]


def test_artifact_serves_legacy_upload_during_migration(tmp_path: Path) -> None:
    legacy_root = tmp_path / "thread_uploads"
    (legacy_root / "th-1").mkdir(parents=True)
    (legacy_root / "th-1" / "old.txt").write_text("old", encoding="utf-8")
    client = _client(tmp_path / "workspaces", legacy_root)

    response = client.get("/api/threads/th-1/artifacts/old.txt")

    assert response.status_code == 200
    assert response.content == b"old"


def test_legacy_upload_root_rejects_thread_path_escape(tmp_path: Path) -> None:
    client = _legacy_client(tmp_path / "thread_uploads")

    response = client.get("/api/threads/%2E%2E/uploads/list")
    dot_response = client.get("/api/threads/%2E/uploads/list")

    assert response.status_code == 400
    assert dot_response.status_code == 400


def test_upload_rejects_invalid_filename(tmp_path: Path) -> None:
    client = _legacy_client(tmp_path / "thread_uploads")

    response = client.post(
        "/api/threads/th-1/uploads",
        files={"files": (".", b"x", "text/plain")},
    )

    assert response.status_code == 400


def test_upload_rejects_file_over_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(uploads_router, "MAX_UPLOAD_FILE_BYTES", 4)
    client = _legacy_client(tmp_path / "thread_uploads")

    response = client.post(
        "/api/threads/th-1/uploads",
        files={"files": ("big.bin", b"12345", "application/octet-stream")},
    )

    assert response.status_code == 413


def test_upload_rejects_too_many_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(uploads_router, "MAX_UPLOAD_FILES", 2)
    client = _legacy_client(tmp_path / "thread_uploads")

    response = client.post(
        "/api/threads/th-1/uploads",
        files=[
            ("files", ("a.txt", b"a", "text/plain")),
            ("files", ("b.txt", b"b", "text/plain")),
            ("files", ("c.txt", b"c", "text/plain")),
        ],
    )

    assert response.status_code == 413


def test_upload_refuses_symlink_target(tmp_path: Path) -> None:
    root = tmp_path / "thread_uploads"
    upload_dir = root / "th-1"
    upload_dir.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (upload_dir / "link.txt").symlink_to(outside)
    except OSError:
        return
    client = _legacy_client(root)

    response = client.post(
        "/api/threads/th-1/uploads",
        files={"files": ("link.txt", b"replace", "text/plain")},
    )

    assert response.status_code == 409
    assert outside.read_text(encoding="utf-8") == "secret"


def test_upload_list_and_artifact_skip_symlink_files(tmp_path: Path) -> None:
    root = tmp_path / "thread_uploads"
    upload_dir = root / "th-1"
    upload_dir.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (upload_dir / "link.txt").symlink_to(outside)
    except OSError:
        return
    client = _legacy_client(root)

    listing = client.get("/api/threads/th-1/uploads/list")
    artifact = client.get("/api/threads/th-1/artifacts/link.txt")

    assert listing.status_code == 200
    assert listing.json() == {"files": [], "count": 0}
    assert artifact.status_code == 404

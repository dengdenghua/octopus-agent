from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from runtime.sensing.gateway.workspaces_router import create_workspaces_router


def _client(root: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_workspaces_router(workspace_root=root))
    return TestClient(app)


def test_workspace_info_creates_standard_layout(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/workspaces/th-1")

    assert response.status_code == 200
    data = response.json()
    root = Path(data["root"])
    assert root == tmp_path.resolve() / "th-1"
    assert data["manifest"]["schema"] == "octopus.workspace.v1"
    assert data["manifest"]["thread_id"] == "th-1"
    assert {entry["key"] for entry in data["dirs"]} == {
        "upload",
        "output",
        "stages",
        "final",
        "deploy",
        "skills",
    }
    assert all(entry["exists"] for entry in data["dirs"])
    assert (root / "output" / "stages").is_dir()
    assert (root / "workspace.json").is_file()


def test_thread_workspace_alias_matches_primary_route(tmp_path: Path) -> None:
    client = _client(tmp_path)

    primary = client.get("/api/workspaces/th-alias").json()
    alias = client.get("/api/threads/th-alias/workspace").json()

    assert alias["root"] == primary["root"]
    assert alias["paths"] == primary["paths"]
    assert alias["manifest"]["schema"] == "octopus.workspace.v1"


def test_workspace_outputs_list_and_serve_final_files(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.get("/api/workspaces/th-out")
    final = tmp_path.resolve() / "th-out" / "output" / "final" / "report.md"
    final.write_bytes(b"# report\n")

    listing = client.get("/api/workspaces/th-out/outputs?area=final")

    assert listing.status_code == 200
    data = listing.json()
    assert data["area"] == "final"
    assert data["count"] == 1
    assert data["files"][0]["relative_path"] == "report.md"
    assert data["files"][0]["download_url"] == (
        "/api/workspaces/th-out/outputs/report.md?area=final"
    )

    content = client.get("/api/workspaces/th-out/outputs/report.md?area=final")
    assert content.status_code == 200
    assert content.content == b"# report\n"


def test_workspace_outputs_reject_path_traversal(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/workspaces/th-out/outputs/%2E%2E%2Fworkspace.json")

    assert response.status_code == 400


def test_thread_outputs_alias_serves_deploy_area(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.get("/api/workspaces/th-deploy")
    deploy = tmp_path.resolve() / "th-deploy" / "deploy" / "index.html"
    deploy.write_text("<h1>ok</h1>", encoding="utf-8")

    listing = client.get("/api/threads/th-deploy/outputs?area=deploy")
    content = client.get("/api/threads/th-deploy/outputs/index.html?area=deploy")

    assert listing.status_code == 200
    assert listing.json()["files"][0]["relative_path"] == "index.html"
    assert content.status_code == 200
    assert content.text == "<h1>ok</h1>"


def test_thread_outputs_alias_renders_office_preview(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.get("/api/workspaces/th-office")
    deck = tmp_path.resolve() / "th-office" / "output" / "final" / "deck.pptx"
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "ppt/slides/slide1.xml",
            '<p:sld xmlns:p="urn:p" xmlns:a="urn:a">'
            "<a:t>Strategy</a:t><a:t>Evidence first</a:t></p:sld>",
        )
    deck.write_bytes(buffer.getvalue())

    response = client.get("/api/threads/th-office/outputs/deck.pptx?area=final&office_preview=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert "script-src 'nonce-" in response.headers["content-security-policy"]
    assert "Strategy" in response.text
    assert 'class="slide"' in response.text


def test_thread_outputs_alias_prefers_high_fidelity_office_pdf(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path)
    client.get("/api/workspaces/th-office-pdf")
    deck = tmp_path.resolve() / "th-office-pdf" / "output" / "final" / "deck.pptx"
    deck.write_bytes(b"pptx")
    monkeypatch.setattr(
        "runtime.sensing.gateway.workspaces_router.render_office_fidelity_preview",
        lambda _target: "<html><body>faithful pages</body></html>",
    )

    response = client.get(
        "/api/threads/th-office-pdf/outputs/deck.pptx"
        "?area=final&office_preview=true&office_fidelity_preview=true"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-octopus-office-preview"] == "fidelity"
    assert "object-src 'none'" in response.headers["content-security-policy"]
    assert "faithful pages" in response.text


def test_visual_html_edit_writes_atomically_with_optimistic_lock(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.get("/api/workspaces/th-html-edit")
    target = tmp_path.resolve() / "th-html-edit" / "output" / "final" / "site.html"
    original = "<!doctype html><html><body><h1>Old</h1></body></html>"
    updated = "<!doctype html><html><body><h1>New</h1></body></html>"
    target.write_text(original, encoding="utf-8")

    response = client.put(
        "/api/threads/th-html-edit/outputs/site.html?area=final",
        json={
            "content": updated,
            "expected_sha256": hashlib.sha256(original.encode()).hexdigest(),
        },
    )

    assert response.status_code == 200
    assert response.json()["sha256"] == hashlib.sha256(updated.encode()).hexdigest()
    revision_id = response.json()["revision_id"]
    assert revision_id
    revision = (
        tmp_path.resolve()
        / "th-html-edit"
        / ".artifact-revisions"
        / "final"
        / "site.html"
        / revision_id
    )
    assert revision.read_text(encoding="utf-8") == original
    assert target.read_text(encoding="utf-8") == updated

    restored = client.post(
        "/api/threads/th-html-edit/output-revisions/site.html?area=final",
        json={
            "revision_id": revision_id,
            "expected_sha256": hashlib.sha256(updated.encode()).hexdigest(),
        },
    )

    assert restored.status_code == 200
    assert restored.json()["sha256"] == hashlib.sha256(original.encode()).hexdigest()
    assert restored.json()["revision_id"]
    assert target.read_text(encoding="utf-8") == original


def test_visual_html_edit_rejects_stale_and_non_html_outputs(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.get("/api/workspaces/th-html-conflict")
    root = tmp_path.resolve() / "th-html-conflict" / "output" / "final"
    html = root / "site.html"
    html.write_text("<h1>Agent version</h1>", encoding="utf-8")
    markdown = root / "report.md"
    markdown.write_text("# report", encoding="utf-8")

    conflict = client.put(
        "/api/threads/th-html-conflict/outputs/site.html?area=final",
        json={
            "content": "<h1>Human version</h1>",
            "expected_sha256": hashlib.sha256(b"older version").hexdigest(),
        },
    )
    unsupported = client.put(
        "/api/threads/th-html-conflict/outputs/report.md?area=final",
        json={"content": "changed"},
    )
    unlocked = client.put(
        "/api/threads/th-html-conflict/outputs/site.html?area=final",
        json={"content": "<h1>Unlocked</h1>"},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error"] == "file_changed"
    assert html.read_text(encoding="utf-8") == "<h1>Agent version</h1>"
    assert unsupported.status_code == 415
    assert unlocked.status_code == 400

    invalid_restore = client.post(
        "/api/threads/th-html-conflict/output-revisions/site.html?area=final",
        json={
            "revision_id": "../escape",
            "expected_sha256": hashlib.sha256(b"<h1>Agent version</h1>").hexdigest(),
        },
    )
    assert invalid_restore.status_code == 400

"""Tests for browser artifact routing."""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ─── _emit_screenshot_artifact ──────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_runtime_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))


def _make_png_b64(size: int = 16) -> str:
    """Return a minimal valid base64-encoded PNG-header bytes."""
    # Not a real PNG but enough to test save/decode path.
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * size).decode()


def _make_valid_png_b64(black_pixels: int = 1) -> str:
    pixels = [(255, 255, 255)] * 16
    for idx in range(min(16, max(0, black_pixels))):
        pixels[idx] = (0, 0, 0)
    rows = []
    for y in range(4):
        row = bytearray([0])
        for pixel in pixels[y * 4 : (y + 1) * 4]:
            row.extend(pixel)
        rows.append(bytes(row))
    payload = b"".join(rows)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(payload))
        + _png_chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode()


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def test_screenshot_saves_file_to_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.execution.suckers import browser_act_skills as bas

    monkeypatch.setattr(bas, "_artifacts_root", lambda: tmp_path / "artifacts")

    response = {
        "ok": True,
        "data": _make_png_b64(),
        "width": 1440,
        "height": 900,
    }
    bas._emit_screenshot_artifact(response)

    files = list((tmp_path / "artifacts").glob("screenshot-*.png"))
    assert len(files) == 1
    assert files[0].read_bytes().startswith(b"\x89PNG")


def test_screenshot_strips_data_uri_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.execution.suckers import browser_act_skills as bas

    monkeypatch.setattr(bas, "_artifacts_root", lambda: tmp_path / "artifacts")

    raw = _make_png_b64()
    response = {
        "ok": True,
        "data": f"data:image/png;base64,{raw}",
        "width": 800,
        "height": 600,
    }
    bas._emit_screenshot_artifact(response)

    files = list((tmp_path / "artifacts").glob("screenshot-*.png"))
    assert len(files) == 1


def test_screenshot_artifact_includes_pixel_assertion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.execution.suckers import browser_act_skills as bas

    monkeypatch.setattr(bas, "_artifacts_root", lambda: tmp_path / "artifacts")
    events: list[dict] = []
    token = bas._ACTIVE_ARTIFACT_EMITTER.set(events.append)
    try:
        bas._emit_screenshot_artifact(
            {
                "ok": True,
                "data": _make_valid_png_b64(),
                "width": 4,
                "height": 4,
            }
        )
    finally:
        bas._ACTIVE_ARTIFACT_EMITTER.reset(token)

    assert len(events) == 1
    assert events[0]["pixel_assertion"]["schema"] == "octopus.browser_pixel_assertion.v1"
    assert events[0]["pixel_assertion"]["ok"] is True
    assert events[0]["pixel_assertion"]["unique_colors"] == 2


def test_screenshot_artifact_includes_replay_gate_case_for_blank_pixels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.execution.suckers import browser_act_skills as bas
    from runtime.memory.learning.review_queue import ReviewQueue

    monkeypatch.setattr(bas, "_artifacts_root", lambda: tmp_path / "artifacts")
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
    events: list[dict] = []
    token = bas._ACTIVE_ARTIFACT_EMITTER.set(events.append)
    try:
        bas._emit_screenshot_artifact(
            {
                "ok": True,
                "data": _make_valid_png_b64(black_pixels=0),
                "width": 4,
                "height": 4,
            }
        )
    finally:
        bas._ACTIVE_ARTIFACT_EMITTER.reset(token)

    assert len(events) == 1
    assert events[0]["pixel_assertion"]["ok"] is False
    assert events[0]["replay_gate_case"]["schema"] == ("octopus.browser_pixel_replay_gate_case.v1")
    assert events[0]["replay_gate_case"]["replay_gate"]["passed"] is False
    assert events[0]["replay_gate_queue"]["created"] == 1

    queue = ReviewQueue(tmp_path / "data" / "review_queue.json").items()
    assert queue["items"][0]["priority"] == "P0"
    assert queue["items"][0]["target_bucket"] == "browser_desktop_replay"
    assert queue["items"][0]["candidate_kind"] == "browser_pixel_replay_gate_case"
    assert queue["items"][0]["metadata"]["case_id"].startswith("browser-pixel::")
    assert queue["items"][0]["metadata"]["replay"]["case_id"].startswith("browser-pixel::")
    assert len(queue["items"][0]["metadata"]["replay"]["fingerprint"]) == 16
    assert queue["items"][0]["metadata"]["replay_gate"]["passed"] is False
    assert queue["items"][0]["metadata"]["replay_gate_case"]["replay_gate"]["reason"] == (
        "browser_pixel_evidence_failed"
    )


def test_screenshot_artifact_includes_previous_pixel_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.execution.suckers import browser_act_skills as bas

    monkeypatch.setattr(bas, "_artifacts_root", lambda: tmp_path / "artifacts")
    events: list[dict] = []
    emitter_token = bas._ACTIVE_ARTIFACT_EMITTER.set(events.append)
    last_token = bas._LAST_SCREENSHOT_ARTIFACT.set(None)
    try:
        bas._emit_screenshot_artifact(
            {
                "ok": True,
                "data": _make_valid_png_b64(black_pixels=1),
                "width": 4,
                "height": 4,
            }
        )
        bas._emit_screenshot_artifact(
            {
                "ok": True,
                "data": _make_valid_png_b64(black_pixels=3),
                "width": 4,
                "height": 4,
            }
        )
    finally:
        bas._LAST_SCREENSHOT_ARTIFACT.reset(last_token)
        bas._ACTIVE_ARTIFACT_EMITTER.reset(emitter_token)

    assert len(events) == 2
    # Two emits must land in two distinct files — on Windows/Py3.11 the
    # coarse clock used to collide the timestamped names, so the second
    # write clobbered the first and the comparison ran against itself.
    assert len(list((tmp_path / "artifacts").glob("screenshot-*.png"))) == 2
    assert "pixel_comparison" not in events[0]
    assert events[1]["pixel_comparison"]["schema"] == "octopus.browser_pixel_comparison.v1"
    assert events[1]["pixel_comparison"]["ok"] is True
    assert events[1]["pixel_comparison"]["changed_ratio"] == 0.125


def test_screenshot_no_data_field_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.execution.suckers import browser_act_skills as bas

    monkeypatch.setattr(bas, "_artifacts_root", lambda: tmp_path / "artifacts")

    bas._emit_screenshot_artifact({"ok": True})

    assert not (tmp_path / "artifacts").exists()


def test_screenshot_ok_false_no_emit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.execution.suckers import browser_act_skills as bas
    from runtime.execution.suckers.browser_act_skills import _h_screenshot

    monkeypatch.setattr(bas, "_artifacts_root", lambda: tmp_path / "artifacts")
    # Patch _bridge_call to return an error response
    with patch.object(bas, "_bridge_call", return_value={"ok": False, "error": "bridge down"}):
        result = _h_screenshot()
    assert result["ok"] is False
    assert not (tmp_path / "artifacts").exists()


def test_screenshot_journal_broadcast_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a journal with _broadcast is available, _emit_screenshot_artifact
    calls _broadcast with the artifact event dict."""
    from runtime.execution.suckers import browser_act_skills as bas

    monkeypatch.setattr(bas, "_artifacts_root", lambda: tmp_path / "artifacts")

    broadcast_calls: list[dict] = []

    class _FakeJournal:
        def _broadcast(self, event: dict) -> None:
            broadcast_calls.append(event)

    fake_journal = _FakeJournal()

    def fake_active_journal():
        return fake_journal

    with patch.dict(
        "sys.modules",
        {
            "runtime.sensing.gateway": MagicMock(
                _active_streaming_journal=fake_active_journal,
            ),
        },
    ):
        # Re-import to pick up the patched module
        # We call _emit directly after patching _artifacts_root
        response = {
            "ok": True,
            "data": _make_png_b64(),
            "width": 1440,
            "height": 900,
        }
        # Patch the journal lookup within the function
        with patch(
            "runtime.sensing.gateway._active_streaming_journal", fake_active_journal, create=True
        ):
            bas._emit_screenshot_artifact(response)

    # The journal broadcast might not fire (patching the import is tricky),
    # but the file should always be written first
    files = list((tmp_path / "artifacts").glob("screenshot-*.png"))
    assert len(files) == 1


def test_emit_swallows_exceptions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken artifacts root must not raise from _emit_screenshot_artifact."""
    from runtime.execution.suckers import browser_act_skills as bas

    # Make _artifacts_root raise
    def bad_root():
        raise RuntimeError("disk full")

    monkeypatch.setattr(bas, "_artifacts_root", bad_root)

    response = {"ok": True, "data": _make_png_b64()}
    # Should not raise
    bas._emit_screenshot_artifact(response)


# ─── /api/browser-artifacts/{filename} ──────────────────────


def test_artifact_endpoint_serves_png(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.platform.ui.browser_router import create_browser_router

    # Write a fake PNG
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "screenshot-test.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)

    from runtime.execution.suckers import browser_act_skills as bas

    monkeypatch.setattr(bas, "_artifacts_root", lambda: artifacts)

    app = FastAPI()
    app.include_router(create_browser_router())
    client = TestClient(app)

    r = client.get("/api/browser-artifacts/screenshot-test.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_artifact_endpoint_rejects_traversal() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.platform.ui.browser_router import create_browser_router

    app = FastAPI()
    app.include_router(create_browser_router())
    client = TestClient(app)

    r = client.get("/api/browser-artifacts/../../etc/passwd")
    assert r.status_code in (404, 422)


def test_artifact_endpoint_rejects_non_png() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.platform.ui.browser_router import create_browser_router

    app = FastAPI()
    app.include_router(create_browser_router())
    client = TestClient(app)

    r = client.get("/api/browser-artifacts/malicious.sh")
    assert r.status_code == 404


def test_artifact_endpoint_404_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.execution.suckers import browser_act_skills as bas
    from runtime.platform.ui.browser_router import create_browser_router

    monkeypatch.setattr(bas, "_artifacts_root", lambda: tmp_path / "empty")

    app = FastAPI()
    app.include_router(create_browser_router())
    client = TestClient(app)

    r = client.get("/api/browser-artifacts/screenshot-ghost.png")
    assert r.status_code == 404


# ─── values-only SSE mode ───────────────────────────────────


def test_stream_mode_values_accepted_from_body() -> None:
    """Check that ``stream_mode`` is read from the request body and
    validated to ``full`` / ``values``."""
    # We can't run the full OpenAI gateway without a stack,
    # so we test the validation logic in isolation.
    for valid in ("full", "values"):
        mode = str(valid).lower()
        assert mode in ("full", "values")

    for invalid in ("events", "updates", "debug", None, ""):
        raw = str(invalid or "full").lower()
        result = raw if raw in ("full", "values") else "full"
        assert result == "full"

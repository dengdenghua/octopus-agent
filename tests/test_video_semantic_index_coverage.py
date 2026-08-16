"""Dense coverage for video_semantic_index model-free helpers (audit Q-05)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from runtime.memory.hemolymph import video_semantic_index as vsi


def test_tenant_db_path(monkeypatch, tmp_path: Path) -> None:
    import runtime.platform.process.paths as pp

    assert vsi.tenant_video_db_path(None) == vsi._DEFAULT_DB
    assert vsi.tenant_video_db_path(SimpleNamespace(tenant_id="", actor_id="")) == vsi._DEFAULT_DB
    monkeypatch.setattr(pp, "app_paths", lambda: type("P", (), {"data_dir": tmp_path / "d"})())
    scoped = vsi.tenant_video_db_path(SimpleNamespace(tenant_id="t1", actor_id="alice"))
    assert str(scoped).startswith(str(tmp_path / "d" / "tenants"))
    assert scoped.name == "video_index.db"


def test_video_disabled_and_accel(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_VIDEO_SEMANTIC", "auto")
    assert vsi._disabled() is False
    monkeypatch.setenv("OCTOPUS_VIDEO_SEMANTIC", "off")
    assert vsi._disabled() is True
    monkeypatch.setenv("OCTOPUS_WHISPER_DEVICE", "gpu")
    monkeypatch.setenv("OCTOPUS_WHISPER_MODEL", "large")
    accel = vsi.hardware_accel()
    assert accel["whisper_device"] == "gpu"
    assert accel["whisper_model"] == "large"


def test_iter_videos_and_rel_mtime(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.MOV").write_bytes(b"x")
    (tmp_path / "c.txt").write_text("no", encoding="utf-8")
    found = vsi._iter_videos(tmp_path)
    assert len(found) == 2
    assert len(vsi._iter_videos(tmp_path, max_files=1)) == 1

    rel = vsi._rel(tmp_path / "a.mp4", tmp_path)
    assert rel == "a.mp4"
    outside = vsi._rel(Path("/elsewhere/x.mp4"), tmp_path)
    assert outside == "/elsewhere/x.mp4"

    assert vsi._mtime(tmp_path / "a.mp4") > 0
    assert vsi._mtime(tmp_path / "missing.mp4") == 0.0


def test_extract_frame_jpeg_without_av(tmp_path: Path) -> None:
    # av is not installed in CI -> self-gated None.
    p = tmp_path / "x.mp4"
    p.write_bytes(b"not-a-real-video")
    out = vsi.extract_frame_jpeg(p, time_sec=0.5)
    assert out is None or isinstance(out, bytes)

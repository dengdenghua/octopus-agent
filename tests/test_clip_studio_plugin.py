from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageChops

from runtime.execution.suckers.registry import SkillRegistry
from runtime.platform.plugins.bundled import clip_studio
from runtime.platform.plugins.bundled.clip_studio import ClipStudioPlugin
from runtime.platform.plugins.plugin_base import ModuleContext


def _client() -> TestClient:
    app = FastAPI()
    plugin_dir = (
        Path(__file__).resolve().parents[1] / "runtime/platform/plugins/bundled/clip_studio"
    )
    plugin = ClipStudioPlugin()
    plugin.on_load(
        ModuleContext(
            plugin_name="clip_studio",
            plugin_dir=str(plugin_dir),
            manifest=None,
            fastapi_app=app,
        )
    )
    return TestClient(app)


def test_clip_studio_health_and_editor_surface() -> None:
    client = _client()
    health = client.get("/api/plugins/clip-studio/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert health.json()["plugin"] == "clip_studio"
    assert "project.edit" in health.json()["methods"]

    page = client.get("/api/plugins/clip-studio/page")
    assert page.status_code == 200
    assert "媒体" in page.text
    assert "播放器" not in page.text  # visual label stays implicit in the preview surface
    assert "添加字幕" in page.text
    assert "octopus.design.close-surface" in page.text


def test_clip_studio_project_edit_history_and_diagnostics(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(clip_studio, "_projects_dir", lambda: tmp_path)
    client = _client()

    initial = client.get("/api/plugins/clip-studio/projects/campaign?view=full")
    assert initial.status_code == 200
    assert initial.json()["counts"]["tracks"] == 3

    video_track = next(track for track in initial.json()["tracks"] if track["type"] == "video")
    edited = client.post(
        "/api/plugins/clip-studio/projects/campaign/edit",
        json={
            "description": "导入样片并添加字幕",
            "operations": [
                {
                    "type": "import_media",
                    "path": "assets/launch.mp4",
                    "name": "发布会样片",
                    "durationSec": 8,
                    "trackId": video_track["id"],
                },
                {"type": "add_text", "text": "全新发布", "atSec": 1, "durationSec": 2},
            ],
        },
    )
    assert edited.status_code == 200
    assert edited.json()["applied"] == 2

    project = client.get("/api/plugins/clip-studio/projects/campaign?view=full").json()
    assert project["counts"]["clips"] == 2
    assert project["textClips"][0]["text"] == "全新发布"

    diagnostics = client.get("/api/plugins/clip-studio/projects/campaign/diagnostics")
    assert diagnostics.status_code == 200
    assert diagnostics.json()["clean"] is True

    undone = client.post(
        "/api/plugins/clip-studio/projects/campaign/history",
        json={"action": "undo"},
    )
    assert undone.status_code == 200
    assert undone.json()["stepsTaken"] == 1
    assert client.get("/api/plugins/clip-studio/projects/campaign").json()["counts"]["clips"] == 0


def test_clip_studio_edit_rolls_back_on_invalid_operation(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(clip_studio, "_projects_dir", lambda: tmp_path)
    client = _client()
    response = client.post(
        "/api/plugins/clip-studio/projects/campaign/edit",
        json={
            "operations": [
                {"type": "add_text", "text": "不会落盘", "atSec": 0},
                {"type": "unknown_operation"},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["rolledBack"] is True
    assert client.get("/api/plugins/clip-studio/projects/campaign").json()["counts"]["clips"] == 0


def test_clip_studio_advanced_timeline_operations(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(clip_studio, "_projects_dir", lambda: tmp_path)
    client = _client()
    track_id = next(
        track["id"]
        for track in client.get("/api/plugins/clip-studio/projects/advanced").json()["tracks"]
        if track["type"] == "video"
    )
    imported = client.post(
        "/api/plugins/clip-studio/projects/advanced/edit",
        json={
            "operations": [
                {
                    "type": "import_media",
                    "path": "assets/scene.mp4",
                    "durationSec": 4,
                    "atSec": 0,
                    "trackId": track_id,
                }
            ]
        },
    ).json()
    clip_id = imported["results"][0]["clipId"]

    edited = client.post(
        "/api/plugins/clip-studio/projects/advanced/edit",
        json={
            "operations": [
                {"type": "duplicate_clip", "clipId": clip_id, "atSec": 6},
                {
                    "type": "add_transition",
                    "clipId": clip_id,
                    "transitionType": "crossfade",
                    "durationSec": 0.4,
                },
                {"type": "add_effect", "clipId": clip_id, "effectType": "sharpen"},
                {
                    "type": "set_color_grading",
                    "clipId": clip_id,
                    "settings": {"contrast": 1.08, "temperature": -4},
                },
            ]
        },
    )
    assert edited.status_code == 200
    duplicate_id = edited.json()["results"][0]["createdClipId"]

    closed = client.post(
        "/api/plugins/clip-studio/projects/advanced/edit",
        json={"operations": [{"type": "close_gap", "clipId": duplicate_id}]},
    ).json()
    assert closed["results"][0]["closedGapSec"] == 2
    clips = client.get("/api/plugins/clip-studio/projects/advanced").json()["clips"]
    duplicate = next(clip for clip in clips if clip["id"] == duplicate_id)
    original = next(clip for clip in clips if clip["id"] == clip_id)
    assert (duplicate["startSec"], duplicate["endSec"]) == (4, 8)
    assert original["transitions"][0]["type"] == "crossfade"
    assert original["effects"][0]["type"] == "sharpen"
    assert original["colorGrading"]["contrast"] == 1.08

    removed = client.post(
        "/api/plugins/clip-studio/projects/advanced/edit",
        json={"operations": [{"type": "remove_clip", "clipId": clip_id, "ripple": True}]},
    ).json()
    assert removed["ok"] is True
    remaining = client.get("/api/plugins/clip-studio/projects/advanced").json()["clips"]
    assert [(clip["startSec"], clip["endSec"]) for clip in remaining] == [(0, 4)]


def test_clip_studio_remove_range_and_srt(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(clip_studio, "_projects_dir", lambda: tmp_path)
    client = _client()
    tracks = client.get("/api/plugins/clip-studio/projects/subtitles").json()["tracks"]
    video_track = next(track for track in tracks if track["type"] == "video")
    response = client.post(
        "/api/plugins/clip-studio/projects/subtitles/edit",
        json={
            "operations": [
                {
                    "type": "import_media",
                    "path": "assets/long-take.mp4",
                    "durationSec": 10,
                    "atSec": 0,
                    "trackId": video_track["id"],
                },
                {
                    "type": "import_srt",
                    "content": (
                        "1\n00:00:01,000 --> 00:00:02,500\n第一句\n\n"
                        "2\n00:00:03,000 --> 00:00:04,000\n第二句"
                    ),
                },
                {
                    "type": "set_subtitle_style",
                    "preset": "minimal",
                    "fontSizePx": 48,
                    "color": "#ffffff",
                },
                {"type": "remove_range", "fromSec": 4, "toSec": 6, "ripple": True},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    project = client.get("/api/plugins/clip-studio/projects/subtitles?view=full").json()
    assert [clip["text"] for clip in project["textClips"]] == ["第一句", "第二句"]
    assert all(clip["fontSizePx"] == 48 for clip in project["textClips"])
    assert project["clips"][0]["endSec"] == 4
    assert project["clips"][1]["startSec"] == 4
    assert project["durationSec"] == 8


def test_clip_studio_diagnostics_reports_missing_media_and_caption_bounds(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(clip_studio, "_projects_dir", lambda: tmp_path)
    client = _client()
    client.post(
        "/api/plugins/clip-studio/projects/diagnostics/edit",
        json={
            "operations": [{"type": "add_text", "text": "越界字幕", "atSec": 5, "durationSec": 1}]
        },
    )
    stored = clip_studio.load_project(tmp_path, "diagnostics")
    stored["tracks"][0]["clips"].append(
        {
            "id": "clip-missing",
            "mediaId": "media-does-not-exist",
            "startSec": 0,
            "endSec": 0.01,
            "durationSec": 0.01,
        }
    )
    clip_studio.save_project(tmp_path, stored)
    diagnostics = client.get("/api/plugins/clip-studio/projects/diagnostics/diagnostics").json()
    kinds = {issue["kind"] for issue in diagnostics["issues"]}
    assert {"tiny_clip", "media_missing", "caption_out_of_video"} <= kinds
    assert diagnostics["clean"] is False


def test_clip_studio_snapshot_renders_real_frame_with_caption_and_look(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(clip_studio, "_projects_dir", lambda: tmp_path / "projects")
    monkeypatch.setattr(
        clip_studio, "_snapshots_dir", lambda project_id: tmp_path / "snapshots" / project_id
    )
    source = tmp_path / "source.png"
    Image.new("RGB", (320, 180), (40, 120, 220)).save(source)
    client = _client()
    initial = client.get("/api/plugins/clip-studio/projects/visual").json()
    video_track = next(track for track in initial["tracks"] if track["type"] == "video")
    imported = client.post(
        "/api/plugins/clip-studio/projects/visual/edit",
        json={
            "operations": [
                {
                    "type": "import_media",
                    "path": str(source),
                    "durationSec": 3,
                    "trackId": video_track["id"],
                },
                {
                    "type": "add_text",
                    "text": "真实合成帧",
                    "atSec": 0,
                    "durationSec": 3,
                    "fontSizePx": 72,
                },
            ]
        },
    ).json()
    clip_id = imported["results"][0]["clipId"]
    client.post(
        "/api/plugins/clip-studio/projects/visual/edit",
        json={
            "operations": [
                {
                    "type": "add_effect",
                    "clipId": clip_id,
                    "effectType": "brightness",
                    "params": {"amount": 0.7},
                },
                {
                    "type": "set_color_grading",
                    "clipId": clip_id,
                    "settings": {"temperature": 30, "tint": -10},
                },
            ]
        },
    )
    response = client.post(
        "/api/plugins/clip-studio/projects/visual/snapshot",
        json={"times": [1], "maxDim": 320},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["frames"][0]["clipId"] == clip_id
    rendered = Image.open(payload["frames"][0]["path"]).convert("RGB")
    assert rendered.size == (320, 180)
    assert ImageChops.difference(rendered, Image.open(source).convert("RGB")).getbbox()


def test_clip_studio_snapshot_rejects_timeline_gap(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(clip_studio, "_projects_dir", lambda: tmp_path / "projects")
    monkeypatch.setattr(
        clip_studio, "_snapshots_dir", lambda project_id: tmp_path / "snapshots" / project_id
    )
    response = _client().post(
        "/api/plugins/clip-studio/projects/empty/snapshot",
        json={"times": [0]},
    )
    assert response.status_code == 400
    assert "timeline gap" in response.json()["detail"]


def test_clip_studio_cut_silences_analyzes_real_audio(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(clip_studio, "_projects_dir", lambda: tmp_path / "projects")
    sample_rate = 16000
    media_path = tmp_path / "speech-with-gap.wav"
    samples: list[int] = []
    for index in range(sample_rate * 3):
        second = index / sample_rate
        if 1 <= second < 2:
            samples.append(0)
        else:
            samples.append(round(math.sin(2 * math.pi * 440 * second) * 12000))
    with wave.open(str(media_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"".join(struct.pack("<h", value) for value in samples))

    client = _client()
    initial = client.get("/api/plugins/clip-studio/projects/podcast").json()
    audio_track = next(track for track in initial["tracks"] if track["type"] == "audio")
    imported = client.post(
        "/api/plugins/clip-studio/projects/podcast/edit",
        json={
            "operations": [
                {
                    "type": "import_media",
                    "path": str(media_path),
                    "durationSec": 3,
                    "trackId": audio_track["id"],
                }
            ]
        },
    ).json()
    clip_id = imported["results"][0]["clipId"]
    cut = client.post(
        "/api/plugins/clip-studio/projects/podcast/edit",
        json={
            "operations": [
                {
                    "type": "cut_silences",
                    "clipId": clip_id,
                    "thresholdDb": -35,
                    "minSilenceSec": 0.5,
                    "padSec": 0.1,
                }
            ]
        },
    )
    assert cut.status_code == 200
    result = cut.json()["results"][0]
    assert len(result["ranges"]) == 1
    assert 0.6 <= result["removedSec"] <= 1.0
    project = client.get("/api/plugins/clip-studio/projects/podcast?view=full").json()
    assert len(project["clips"]) == 2
    assert project["durationSec"] < 2.4
    assert project["clips"][1]["sourceInSec"] > 1.8


def test_clip_studio_registers_agent_callable_skills(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(clip_studio, "_projects_dir", lambda: tmp_path)
    registry = SkillRegistry()
    plugin_dir = (
        Path(__file__).resolve().parents[1] / "runtime/platform/plugins/bundled/clip_studio"
    )
    plugin = ClipStudioPlugin()
    plugin.on_load(
        ModuleContext(
            plugin_name="clip_studio",
            plugin_dir=str(plugin_dir),
            manifest=None,
            skill_registry=registry,
        )
    )
    assert {
        "clip_studio.project_get",
        "clip_studio.project_edit",
        "clip_studio.project_snapshot",
        "clip_studio.project_diagnostics",
        "clip_studio.project_history",
        "clip_studio.project_view",
    } <= set(registry.all_names())
    result = registry.get("clip_studio.project_edit").handler(
        project_id="agent-edit",
        operations=[{"type": "add_text", "text": "Agent 字幕", "atSec": 0}],
    )
    assert result["ok"] is True
    project = registry.get("clip_studio.project_get").handler(project_id="agent-edit", view="full")
    assert project["textClips"][0]["text"] == "Agent 字幕"
    viewed = registry.get("clip_studio.project_view").handler(
        project_id="agent-edit", action="seek", to_sec=1.25
    )
    assert viewed["playheadSec"] == 1.25
    undone = registry.get("clip_studio.project_history").handler(
        project_id="agent-edit", action="undo"
    )
    assert undone["stepsTaken"] == 1
    project = registry.get("clip_studio.project_get").handler(project_id="agent-edit", view="full")
    assert project["textClips"] == []

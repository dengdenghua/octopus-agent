from __future__ import annotations

import json
from types import SimpleNamespace

import runtime.execution.suckers.kimi_compat_skills as media


def _clear_media_keys(monkeypatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_MEDIA_API_KEY",
        "VOLCENGINE_API_KEY",
        "ARK_API_KEY",
        "AGNES_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_generate_image_uses_agnes_when_openai_media_is_unconfigured(monkeypatch) -> None:
    _clear_media_keys(monkeypatch)
    monkeypatch.setenv("AGNES_API_KEY", "test-agnes-key")
    calls: dict = {}

    def generate_image(prompt, **kwargs):
        calls.update({"prompt": prompt, **kwargs})
        return {
            "url": "https://example.test/image.png",
            "urls": ["https://example.test/image.png"],
            "model": "agnes-image-2.5-flash",
            "raw": {"large": "provider payload"},
        }

    monkeypatch.setattr(
        media,
        "_load_bundled_media_module",
        lambda kind: SimpleNamespace(generate_image=generate_image),
    )

    result = media._generate_image("a red panda", provider="agnes", n=2)

    assert result == {
        "ok": True,
        "url": "https://example.test/image.png",
        "urls": ["https://example.test/image.png"],
        "model": "agnes-image-2.5-flash",
        "provider": "agnes",
    }
    assert calls["api_key"] == "test-agnes-key"
    assert calls["n"] == 2


def test_generate_image_falls_back_from_volcano_to_agnes(monkeypatch) -> None:
    _clear_media_keys(monkeypatch)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "test-volcano-key")
    monkeypatch.setenv("AGNES_API_KEY", "test-agnes-key")
    calls: list[str] = []

    def generate_image(prompt, **kwargs):  # noqa: ARG001
        base_url = kwargs["base_url"]
        calls.append(base_url)
        if "volces.com" in base_url:
            raise RuntimeError("InvalidSubscription")
        return {
            "url": "https://example.test/fallback.png",
            "urls": ["https://example.test/fallback.png"],
            "model": "agnes-image-2.5-flash",
        }

    monkeypatch.setattr(
        media,
        "_load_bundled_media_module",
        lambda kind: SimpleNamespace(generate_image=generate_image),
    )

    result = media._generate_image("a small octopus", size="1:1")

    assert result["ok"] is True
    assert result["provider"] == "agnes"
    assert result["fallback_from"] == ["volcano"]
    assert calls == [
        "https://ark.cn-beijing.volces.com/api/plan/v3",
        "https://apihub.agnes-ai.com/v1",
    ]


def test_agent_visuals_default_to_agnes_image_25(monkeypatch) -> None:
    from runtime.execution.misc.image_generation import _resolve_agnes_config

    monkeypatch.setenv("AGNES_API_KEY", "test-agnes-key")
    monkeypatch.delenv("AGNES_IMAGE_MODEL", raising=False)

    config = _resolve_agnes_config()

    assert config["model"] == "agnes-image-2.5-flash"


def test_agnes_image_accepts_aspect_ratio_size_alias(monkeypatch) -> None:
    module = media._load_bundled_media_module("image")
    captured: dict = {}

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {"data": [{"url": "https://example.test/octopus.png"}]}

    def post(url, *, headers, data, timeout):
        captured.update({"url": url, "payload": json.loads(data)})
        return Response()

    monkeypatch.setattr(module.requests, "post", post)

    result = module.generate_image(
        "a small octopus",
        api_key="test-key",
        base_url="https://apihub.agnes-ai.com/v1",
        size="1:1",
    )

    assert result["url"] == "https://example.test/octopus.png"
    assert captured["payload"]["size"] == "1024x1024"


def test_generate_video_submits_and_polls_with_same_tool(monkeypatch) -> None:
    _clear_media_keys(monkeypatch)
    monkeypatch.setenv("AGNES_API_KEY", "test-agnes-key")
    submitted: dict = {}
    polled: dict = {}

    def generate_video(prompt, **kwargs):
        submitted.update({"prompt": prompt, **kwargs})
        return {
            "task_id": "video-task-1",
            "status": "queued",
            "model": "agnes-video-2.5-flash",
        }

    def poll_video(task_id, **kwargs):
        polled.update({"task_id": task_id, **kwargs})
        return {
            "task_id": task_id,
            "status": "completed",
            "video_url": "https://example.test/video.mp4",
            "model": "agnes-video-2.5-flash",
        }

    monkeypatch.setattr(
        media,
        "_load_bundled_media_module",
        lambda kind: SimpleNamespace(generate_video=generate_video, poll_video=poll_video),
    )

    created = media._generate_video("a flying whale", provider="agnes", wait=False)
    completed = media._generate_video(task_id="video-task-1", provider="agnes")

    assert created["ok"] is True
    assert created["task_id"] == "video-task-1"
    assert created["model"] == "agnes-video-2.5-flash"
    assert completed["ok"] is True
    assert completed["video_url"] == "https://example.test/video.mp4"
    assert submitted["wait"] is False
    assert polled["task_id"] == "video-task-1"


def test_generate_video_falls_back_from_volcano_to_agnes(monkeypatch) -> None:
    _clear_media_keys(monkeypatch)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "test-volcano-key")
    monkeypatch.setenv("AGNES_API_KEY", "test-agnes-key")
    calls: list[str] = []

    def generate_video(prompt, **kwargs):  # noqa: ARG001
        base_url = kwargs["base_url"]
        calls.append(base_url)
        if "volces.com" in base_url:
            raise RuntimeError("InvalidSubscription")
        return {
            "task_id": "video-task-fallback",
            "status": "completed",
            "video_url": "https://example.test/fallback.mp4",
            "model": "agnes-video-2.5-flash",
        }

    monkeypatch.setattr(
        media,
        "_load_bundled_media_module",
        lambda kind: SimpleNamespace(generate_video=generate_video),
    )

    result = media._generate_video("a waving octopus")

    assert result["ok"] is True
    assert result["provider"] == "agnes"
    assert result["fallback_from"] == ["volcano"]
    assert calls == [
        "https://ark.cn-beijing.volces.com/api/plan/v3",
        "https://apihub.agnes-ai.com/v1",
    ]


def test_media_tools_report_all_supported_key_options(monkeypatch) -> None:
    _clear_media_keys(monkeypatch)

    image = media._generate_image("a lighthouse")
    video = media._generate_video("a lighthouse at sunset")

    assert image["error"] == "generate_image_provider_not_configured"
    assert "AGNES_API_KEY" in image["hint"]
    assert video["error"] == "generate_video_provider_not_configured"
    assert "AGNES_API_KEY" in video["hint"]


def test_agnes_video_25_omits_forbidden_legacy_frame_controls(monkeypatch) -> None:
    module = media._load_bundled_media_module("video")
    captured: dict = {}

    class Response:
        status_code = 200

        def json(self):
            return {"id": "task-25", "status": "queued"}

    def post(url, *, headers, data, timeout):
        captured.update(
            {
                "url": url,
                "headers": headers,
                "payload": json.loads(data),
                "timeout": timeout,
            }
        )
        return Response()

    monkeypatch.setattr(module.requests, "post", post)

    result = module.generate_video(
        "a waving octopus",
        api_key="test-key",
        base_url="https://apihub.agnes-ai.com/v1",
        model="agnes-video-2.5-flash",
        width=1152,
        height=768,
        num_frames=49,
        wait=False,
    )

    assert result["task_id"] == "task-25"
    assert captured["payload"]["model"] == "agnes-video-2.5-flash"
    assert captured["payload"]["mode"] == "text"
    assert captured["payload"]["seconds"] == "5"
    assert captured["payload"]["size"] == "720P"
    assert "width" not in captured["payload"]
    assert "height" not in captured["payload"]
    assert "num_frames" not in captured["payload"]
    assert "frame_rate" not in captured["payload"]

"""Agnes AI video generation skill (async).

Wraps:
    POST  https://apihub.agnes-ai.com/v1/videos        — create task
    GET   https://apihub.agnes-ai.com/v1/videos/{task_id}  — poll status

The endpoint is async — the create call returns a queued task_id. By
default this skill blocks until the task completes (`wait=True`),
polling at a backed-off cadence so we don't hammer the gateway.

Usage:
    from agnes_video_generate import generate_video, poll_video

    r = generate_video("a red panda walking through a forest")
    print(r["video_url"])  # mp4 URL when status=completed
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

_LOG = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://apihub.agnes-ai.com/v1"
DEFAULT_MODEL = "agnes-video-v2.0"

# Per Agnes docs: agnes-video-v2.0 frame_rule = "8n+1", max_frames = 441
_MAX_FRAMES = 441


@dataclass(frozen=True)
class AgnesConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL

    @classmethod
    def from_env(cls) -> AgnesConfig:
        key = (os.environ.get("AGNES_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
        if not key:
            raise ValueError(
                "AGNES_API_KEY not found. Set AGNES_API_KEY or "
                "OPENAI_API_KEY env var, or pass api_key= explicitly.",
            )
        base = (os.environ.get("AGNES_BASE_URL", "").strip() or DEFAULT_BASE_URL).rstrip("/")
        return cls(api_key=key, base_url=base)


def _validate_frames(num_frames: int) -> None:
    """Enforce the 8n+1 frame rule documented for agnes-video-v2.0."""
    if num_frames <= 0 or num_frames > _MAX_FRAMES:
        raise ValueError(
            f"num_frames must be 1..{_MAX_FRAMES}; got {num_frames}",
        )
    if (num_frames - 1) % 8 != 0:
        raise ValueError(
            f"num_frames must satisfy 8n+1 (e.g. 49, 81, 121, 161, "
            f"...); got {num_frames}. "
            "Try the closest valid value.",
        )


def generate_video(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    width: int = 1152,
    height: int = 768,
    num_frames: int = 49,
    frame_rate: int = 24,
    image: str | list[str] | None = None,
    seed: int | None = None,
    wait: bool = False,
    max_wait_seconds: int = 300,
    poll_interval_seconds: float = 5.0,
    api_key: str | None = None,
    base_url: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a video generation task and (optionally) wait for completion.

    Parameters
    ----------
    prompt
        Text instruction for the desired video. Required.
    model
        Default ``agnes-video-v2.0``.
    width, height
        Output resolution. Default 1152x768 (3:2).
    num_frames
        Total frames. Must satisfy ``num_frames % 8 == 1`` per the
        agnes-video-v2.0 constraint (49, 81, 121, ...). Default 49
        (~2 seconds at 24 fps).
    frame_rate
        Frames per second, 1..60. Default 24.
    image
        Optional reference image URL(s):
          - single string: image-to-video
          - list of two strings: keyframe transition
    seed
        Optional deterministic seed.
    wait
        When False (default), return immediately after submitting the
        task — caller polls later via ``agnes_video_poll(task_id)``.
        Non-blocking is the right default in ReAct loops because video
        renders take 30-180s; blocking the LLM turn that long is wasteful.
        When True, the call blocks until the task reaches a terminal
        state (completed/failed) or ``max_wait_seconds`` elapses.
    max_wait_seconds
        Hard ceiling on how long to wait when ``wait=True``.
    poll_interval_seconds
        Initial poll cadence. Backs off mildly on each iteration.

    Returns
    -------
    dict
        Always contains ``task_id``, ``status``, ``model``.
        On completion: ``video_url`` is populated.
        On failure / timeout: includes ``error`` field.

    Raises
    ------
    ValueError
        Bad inputs (empty prompt, invalid num_frames, missing key).
    RuntimeError
        Non-200 from the gateway, or terminal status=failed.
    TimeoutError
        ``wait=True`` and task didn't finish in time.
    """
    if not prompt or not str(prompt).strip():
        raise ValueError("prompt is required")
    _validate_frames(int(num_frames))
    if not 1 <= int(frame_rate) <= 60:
        raise ValueError(f"frame_rate must be 1..60; got {frame_rate}")

    if api_key is None or base_url is None:
        cfg = AgnesConfig.from_env()
        api_key = api_key or cfg.api_key
        base_url = (base_url or cfg.base_url).rstrip("/")

    payload: dict[str, Any] = {
        "model": model,
        "prompt": str(prompt).strip(),
        "width": int(width),
        "height": int(height),
        "num_frames": int(num_frames),
        "frame_rate": int(frame_rate),
    }
    if seed is not None:
        payload["seed"] = int(seed)
    if image is not None:
        # Per Agnes doc: image goes under extra_body for backward-compat.
        payload.setdefault("extra_body", {})["image"] = image
    if extra:
        for key, value in extra.items():
            if key == "extra_body" and isinstance(value, dict):
                payload.setdefault("extra_body", {}).update(value)
            elif key not in payload:
                payload[key] = value

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    create_url = f"{base_url}/videos"
    _LOG.info(
        "agnes_video_generate model=%s frames=%d fps=%d size=%dx%d wait=%s",
        model,
        num_frames,
        frame_rate,
        width,
        height,
        wait,
    )

    try:
        resp = requests.post(
            create_url,
            headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=60,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"agnes video create failed: {type(exc).__name__}: {exc}",
        ) from exc

    if resp.status_code != 200:
        body = resp.text[:500].replace("\n", " ")
        raise RuntimeError(
            f"agnes video create error: HTTP {resp.status_code} — {body}",
        )

    data = resp.json()
    task_id = str(data.get("task_id") or data.get("id") or "")
    if not task_id:
        raise RuntimeError(f"agnes video create returned no task_id: {data!r}")

    initial = {
        "task_id": task_id,
        "status": str(data.get("status") or "queued"),
        "model": data.get("model") or model,
        "video_url": None,
        "size": data.get("size"),
        "seconds": data.get("seconds"),
        "progress": int(data.get("progress") or 0),
        "raw": data,
    }
    if not wait:
        return initial

    return _poll_until_done(
        task_id,
        api_key=api_key,
        base_url=base_url,
        initial=initial,
        max_wait_seconds=int(max_wait_seconds),
        poll_interval_seconds=float(poll_interval_seconds),
    )


def poll_video(
    task_id: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """One-shot status poll for a previously-submitted task."""
    if not task_id:
        raise ValueError("task_id is required")
    if api_key is None or base_url is None:
        cfg = AgnesConfig.from_env()
        api_key = api_key or cfg.api_key
        base_url = (base_url or cfg.base_url).rstrip("/")

    url = f"{base_url}/videos/{task_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(
            f"agnes video poll failed: {type(exc).__name__}: {exc}",
        ) from exc
    if resp.status_code != 200:
        body = resp.text[:300].replace("\n", " ")
        raise RuntimeError(
            f"agnes video poll error: HTTP {resp.status_code} — {body}",
        )
    return _normalize_poll_response(task_id, resp.json())


def _poll_until_done(
    task_id: str,
    *,
    api_key: str,
    base_url: str,
    initial: dict[str, Any],
    max_wait_seconds: int,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + max_wait_seconds
    interval = poll_interval_seconds
    last = initial
    while time.time() < deadline:
        time.sleep(interval)
        # Mild back-off: cap at 15s to keep latency reasonable for short clips
        # while not pounding the gateway for long renders.
        interval = min(15.0, interval * 1.2)
        try:
            last = poll_video(task_id, api_key=api_key, base_url=base_url)
        except RuntimeError as exc:
            _LOG.warning("agnes video poll transient error: %s", exc)
            continue
        status = str(last.get("status") or "").lower()
        if status == "completed":
            return last
        if status == "failed":
            raise RuntimeError(
                f"agnes video task failed: {last.get('error') or last.get('raw')}",
            )
        # else: still queued / processing — keep waiting
    raise TimeoutError(
        f"agnes video task did not complete within "
        f"{max_wait_seconds}s (last status: {last.get('status')!r}, "
        f"task_id={task_id})",
    )


def _normalize_poll_response(
    task_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Project the raw poll response into a stable shape."""
    status = str(data.get("status") or "").lower() or "unknown"
    # The completed video URL has been observed under several keys
    # depending on gateway version; check the common ones.
    video_url = data.get("video_url") or data.get("url") or _extract_video_url(data.get("output"))
    return {
        "task_id": task_id,
        "status": status,
        "model": data.get("model"),
        "video_url": video_url,
        "progress": int(data.get("progress") or 0),
        "created_at": data.get("created_at"),
        "completed_at": data.get("completed_at"),
        "error": data.get("error"),
        "raw": data,
    }


def _extract_video_url(output: Any) -> str | None:
    """Try to find a video URL inside an `output` field of varying shape."""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("url", "video_url", "video", "mp4_url"):
            value = output.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(output, list):
        for entry in output:
            url = _extract_video_url(entry)
            if url:
                return url
    return None


__all__ = ["AgnesConfig", "generate_video", "poll_video"]


if __name__ == "__main__":  # pragma: no cover — manual smoke test
    import argparse

    parser = argparse.ArgumentParser(description="Agnes video generate")
    parser.add_argument("prompt", help="Text prompt")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--width", type=int, default=1152)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--frames", type=int, default=49)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    result = generate_video(
        args.prompt,
        model=args.model,
        width=args.width,
        height=args.height,
        num_frames=args.frames,
        frame_rate=args.fps,
        wait=not args.no_wait,
        max_wait_seconds=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

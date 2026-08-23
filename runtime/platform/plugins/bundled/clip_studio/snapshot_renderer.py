"""Render inspectable timeline frames with the project's existing media stack."""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any
from uuid import uuid4

import av
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


def render_project_frames(
    project: dict[str, Any],
    output_dir: Path,
    *,
    times: list[float],
    max_dim: int = 640,
) -> dict[str, Any]:
    if not 1 <= len(times) <= 8:
        raise ValueError("times must contain 1-8 values")
    max_dim = max(160, min(1280, int(max_dim)))
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for at_sec in times:
        at_sec = max(0.0, float(at_sec))
        image, clip = _base_frame(project, at_sec)
        image = _fit_canvas(image, project, max_dim)
        image, frame_warnings = _apply_look(image, clip)
        warnings.extend({"atSec": at_sec, **item} for item in frame_warnings)
        image = _draw_active_text(image, project, at_sec)
        path = output_dir / f"frame-{at_sec:.3f}-{uuid4().hex[:8]}.png"
        image.save(path, format="PNG", optimize=True)
        frames.append(
            {
                "atSec": at_sec,
                "path": str(path.resolve()),
                "width": image.width,
                "height": image.height,
                "clipId": clip.get("id"),
                "mediaId": clip.get("mediaId"),
            }
        )
    return {"ok": True, "frames": frames, "warnings": warnings}


def sample_times(
    project: dict[str, Any],
    *,
    times: list[float] | None = None,
    from_sec: float | None = None,
    to_sec: float | None = None,
    count: int = 4,
) -> list[float]:
    if times and (from_sec is not None or to_sec is not None):
        raise ValueError("pass times or a range, not both")
    if times:
        if not 1 <= len(times) <= 8:
            raise ValueError("times must contain 1-8 values")
        return [max(0.0, float(value)) for value in times]
    start = max(0.0, float(from_sec or 0))
    duration = float(project.get("timelineDurationSec") or 0)
    if not duration:
        duration = max(
            (
                float(clip.get("endSec") or 0)
                for track in project.get("tracks", [])
                for clip in track.get("clips", [])
            ),
            default=0.0,
        )
    end = float(to_sec if to_sec is not None else duration)
    if end < start:
        raise ValueError("toSec must be greater than or equal to fromSec")
    count = max(1, min(8, int(count)))
    if count == 1 or math.isclose(start, end):
        return [start]
    return [start + (end - start) * index / (count - 1) for index in range(count)]


def _base_frame(
    project: dict[str, Any], at_sec: float
) -> tuple[Image.Image, dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for track in project.get("tracks", []):
        if track.get("type") != "video" or track.get("hidden"):
            continue
        visible.extend(
            clip
            for clip in track.get("clips", [])
            if float(clip.get("startSec") or 0) <= at_sec < float(clip.get("endSec") or 0)
        )
    if not visible:
        raise ValueError(f"timeline gap at {at_sec:.3f}s")
    clip = visible[-1]
    media = _media(project, str(clip.get("mediaId") or ""))
    path = _media_path(media)
    if media.get("type") == "image" or path.suffix.lower() in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
    }:
        return Image.open(path).convert("RGB"), clip
    offset = at_sec - float(clip.get("startSec") or 0)
    speed = max(0.1, float(clip.get("speed") or 1))
    source_time = float(clip.get("sourceInSec") or 0) + offset * speed
    if clip.get("reverse"):
        source_time = float(clip.get("sourceOutSec") or 0) - offset * speed
    return _decode_video_frame(path, max(0.0, source_time)), clip


def _decode_video_frame(path: Path, at_sec: float) -> Image.Image:
    try:
        with av.open(str(path)) as container:
            stream = next((item for item in container.streams if item.type == "video"), None)
            if stream is None:
                raise ValueError("media has no video stream")
            if stream.time_base:
                container.seek(
                    max(0, int(at_sec / float(stream.time_base))),
                    stream=stream,
                    backward=True,
                )
            selected = None
            for frame in container.decode(stream):
                selected = frame
                frame_time = float(frame.time or 0)
                if frame_time + 1e-6 >= at_sec:
                    break
            if selected is None:
                raise ValueError("no frame decoded")
            return selected.to_image().convert("RGB")
    except (av.error.FFmpegError, OSError) as exc:
        raise ValueError(f"cannot decode media: {path.name}") from exc


def _fit_canvas(image: Image.Image, project: dict[str, Any], max_dim: int) -> Image.Image:
    settings = project.get("settings", {})
    width = max(1, int(settings.get("width") or 1920))
    height = max(1, int(settings.get("height") or 1080))
    scale = min(1.0, max_dim / max(width, height))
    target = (max(1, round(width * scale)), max(1, round(height * scale)))
    fitted = ImageOps.contain(image, target, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", target, "black")
    canvas.paste(fitted, ((target[0] - fitted.width) // 2, (target[1] - fitted.height) // 2))
    return canvas


def _apply_look(
    image: Image.Image, clip: dict[str, Any]
) -> tuple[Image.Image, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    for effect in clip.get("effects", []):
        kind = str(effect.get("type") or "")
        params = effect.get("params") or {}
        amount = float(params.get("amount", params.get("value", 1)))
        if kind == "brightness":
            image = ImageEnhance.Brightness(image).enhance(max(0, amount))
        elif kind == "contrast":
            image = ImageEnhance.Contrast(image).enhance(max(0, amount))
        elif kind == "saturation":
            image = ImageEnhance.Color(image).enhance(max(0, amount))
        elif kind == "blur":
            image = image.filter(ImageFilter.GaussianBlur(radius=max(0, amount)))
        elif kind == "sharpen":
            image = ImageEnhance.Sharpness(image).enhance(max(0, amount or 2))
        elif kind == "grain":
            image = _grain(image, min(0.25, max(0, amount / 100 if amount > 1 else amount)))
        elif kind:
            warnings.append(
                {"kind": "effect_not_rendered", "effect": kind, "clipId": clip.get("id")}
            )
    grading = clip.get("colorGrading") or {}
    temperature = float(grading.get("temperature") or 0)
    tint = float(grading.get("tint") or 0)
    if temperature or tint:
        image = _temperature_tint(image, temperature, tint)
    if clip.get("transitions"):
        warnings.append(
            {
                "kind": "transition_not_rendered",
                "clipId": clip.get("id"),
                "detail": "单帧快照暂不合成转场中间态",
            }
        )
    return image, warnings


def _draw_active_text(
    image: Image.Image, project: dict[str, Any], at_sec: float
) -> Image.Image:
    active = [
        clip
        for track in project.get("tracks", [])
        if track.get("type") == "text" and not track.get("hidden")
        for clip in track.get("clips", [])
        if float(clip.get("startSec") or 0) <= at_sec < float(clip.get("endSec") or 0)
    ]
    if not active:
        return image
    draw = ImageDraw.Draw(image, "RGBA")
    for index, clip in enumerate(active):
        font_size = max(12, round(float(clip.get("fontSizePx") or 56) * image.width / 1920))
        font = _font(font_size, str(clip.get("fontFamily") or ""))
        text = str(clip.get("text") or "")
        bbox = draw.multiline_textbbox((0, 0), text, font=font, align="center", spacing=4)
        text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        position = str(clip.get("position") or "bottom")
        x = (image.width - text_width) / 2
        if position == "top":
            y = image.height * 0.1 + index * (text_height + 10)
        elif position == "center":
            y = (image.height - text_height) / 2 + index * (text_height + 10)
        else:
            y = image.height * 0.84 - text_height - index * (text_height + 10)
        padding = max(5, font_size // 5)
        background = str(clip.get("backgroundColor") or "#000000a6")
        draw.rounded_rectangle(
            (x - padding, y - padding, x + text_width + padding, y + text_height + padding),
            radius=padding,
            fill=_rgba(background, 166),
        )
        draw.multiline_text(
            (x, y),
            text,
            font=font,
            fill=_rgba(str(clip.get("color") or "#ffffff"), 255),
            align="center",
            spacing=4,
            stroke_width=max(0, round(float(clip.get("outlineWidthPx") or 0))),
            stroke_fill=_rgba(str(clip.get("outlineColor") or "#000000"), 255),
        )
    return image


def _media(project: dict[str, Any], media_id: str) -> dict[str, Any]:
    matches = [
        item for item in project.get("media", []) if str(item.get("id", "")).startswith(media_id)
    ]
    if len(matches) != 1:
        raise ValueError(f"media not found or ambiguous: {media_id}")
    return matches[0]


def _media_path(media: dict[str, Any]) -> Path:
    raw = str(media.get("path") or "")
    if not raw:
        raise ValueError("media has no local path")
    path = Path(raw).expanduser()
    candidates = [path] if path.is_absolute() else [Path.cwd() / path]
    resolved = next((item.resolve() for item in candidates if item.is_file()), None)
    if resolved is None:
        raise ValueError(f"media file not found: {path.name}")
    return resolved


def _font(size: int, family: str) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        family,
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _rgba(value: str, default_alpha: int) -> tuple[int, int, int, int]:
    raw = value.lstrip("#")
    try:
        if len(raw) == 8:
            return tuple(int(raw[index : index + 2], 16) for index in range(0, 8, 2))  # type: ignore[return-value]
        if len(raw) == 6:
            rgb = tuple(int(raw[index : index + 2], 16) for index in range(0, 6, 2))
            return (*rgb, default_alpha)
    except ValueError:
        pass
    return (0, 0, 0, default_alpha)


def _temperature_tint(image: Image.Image, temperature: float, tint: float) -> Image.Image:
    r, g, b = image.split()
    temperature = max(-100, min(100, temperature)) / 100
    tint = max(-100, min(100, tint)) / 100
    r = r.point(lambda value: max(0, min(255, value * (1 + 0.18 * temperature))))
    b = b.point(lambda value: max(0, min(255, value * (1 - 0.18 * temperature))))
    g = g.point(lambda value: max(0, min(255, value * (1 + 0.12 * tint))))
    return Image.merge("RGB", (r, g, b))


def _grain(image: Image.Image, amount: float) -> Image.Image:
    if amount <= 0:
        return image
    rng = random.Random(0)
    noise = Image.new("L", image.size)
    noise.putdata([rng.randrange(256) for _ in range(image.width * image.height)])
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    return Image.blend(image, noise_rgb, amount)


__all__ = ["render_project_frames", "sample_times"]

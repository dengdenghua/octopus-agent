"""Bounded screenshot observations for external engines; never fetch remote URLs."""

from __future__ import annotations

import base64
import binascii
import io
import warnings
from pathlib import Path
from typing import Any

from runtime.execution.request import current_execution_request
from runtime.platform.process.session import current_session

MAX_IMAGE_URL_CHARS = 512_000
MAX_SOURCE_BYTES = 20 * 1024 * 1024
SCREENSHOT_TOOLS = frozenset({"screen_capture", "browser_screenshot", "live_browser_screenshot"})


def valid_inline_image(value: str) -> bool:
    if len(value) > MAX_IMAGE_URL_CHARS:
        return False
    header, separator, payload = value.partition(",")
    if not separator or header not in {
        "data:image/png;base64",
        "data:image/jpeg;base64",
        "data:image/webp;base64",
    }:
        return False
    try:
        return bool(base64.b64decode(payload, validate=True))
    except (ValueError, binascii.Error):
        return False


def _source_bytes(output: dict[str, Any]) -> bytes:
    raw = output.get("dataUrl") or output.get("data")
    if isinstance(raw, str) and raw:
        if len(raw) > 4 * ((MAX_SOURCE_BYTES + 2) // 3) + 100:
            raise ValueError("image too large")
        if raw.startswith("data:"):
            header, _, raw = raw.partition(",")
            if header not in {
                "data:image/png;base64",
                "data:image/jpeg;base64",
                "data:image/webp;base64",
            }:
                raise ValueError("unsupported image")
        return base64.b64decode(raw, validate=True)

    # Only screenshot tools enter here. Never resolve paths against the host's
    # process cwd, or widen access using fields supplied in the tool response.
    session = current_session()
    workspace = (getattr(session, "metadata", None) or {}).get("workspace_path")
    path = output.get("path")
    if not isinstance(workspace, str) or not isinstance(path, str) or not path:
        raise ValueError("no screenshot")
    root = Path(workspace).resolve(strict=True)
    target = Path(path)
    target = (target if target.is_absolute() else root / target).resolve(strict=True)
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("screenshot outside workspace")
    request = current_execution_request()
    if request is not None and not request.task.permissions.allows_read(target):
        raise ValueError("screenshot read denied")
    with target.open("rb") as handle:
        return handle.read(MAX_SOURCE_BYTES + 1)


def screenshot_observation(
    tool_name: str,
    output: Any,
    images: list[dict[str, str]],
) -> Any:
    """Detach image bytes before text pruning, keeping coordinate metadata.

    The caller invokes this only after successful execution and error checks.
    Unrelated results are untouched. Failure preserves text and reports that
    no visual observation was delivered; it never reruns the capture/action.
    """
    if tool_name not in SCREENSHOT_TOOLS or not isinstance(output, dict):
        return output
    text_output = {key: value for key, value in output.items() if key not in {"data", "dataUrl"}}
    unavailable = {
        "attached": False,
        "reason": "Screenshot could not be attached within access, format, or size limits.",
    }
    try:
        from PIL import Image
    except ImportError:
        text_output["visual_observation"] = unavailable
        return text_output
    try:
        data = _source_bytes(output)
        if not data or len(data) > MAX_SOURCE_BYTES:
            raise ValueError("image outside bounds")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                width, height = source.size
                if width * height > 40_000_000:
                    raise ValueError("image dimensions too large")
                source.load()
                mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(
                    source.format
                )
                image = source.convert("RGB")
        # Keep small original screenshots lossless, especially UI text. Only
        # oversized observations need the bounded JPEG/resizing fallback.
        if mime and len(data) * 4 // 3 + 100 <= MAX_IMAGE_URL_CHARS:
            url = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
            images.append({"type": "inputImage", "imageUrl": url})
            text_output["visual_observation"] = {
                "attached": True,
                "original_width": width,
                "original_height": height,
                "image_width": width,
                "image_height": height,
                "coordinate_note": "Original capture dimensions preserved; apply "
                "region/viewport offsets separately.",
            }
            return text_output
        image.thumbnail((1600, 1600))
        for _ in range(5):
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
            url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
            if len(url) <= MAX_IMAGE_URL_CHARS:
                images.append({"type": "inputImage", "imageUrl": url})
                text_output["visual_observation"] = {
                    "attached": True,
                    "original_width": width,
                    "original_height": height,
                    "image_width": image.width,
                    "image_height": image.height,
                    "coordinate_note": "Image may be resized. Map image coordinates to the "
                    "original capture dimensions; apply region/viewport offsets separately.",
                }
                return text_output
            image = image.resize((max(1, image.width // 2), max(1, image.height // 2)))
        raise ValueError("encoded image too large")
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        text_output["visual_observation"] = unavailable
        return text_output

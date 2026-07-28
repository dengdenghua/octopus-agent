"""Agnes AI image generation skill.

Wraps POST https://apihub.agnes-ai.com/v1/images/generations against the
Agnes AI Gateway. The gateway is OpenAI-compatible, so this skill is a
thin adapter — Authorization header + body shape, returns the hosted
image URL(s).

Usage:
    from agnes_image_generate import generate_image
    r = generate_image("a cat astronaut on Mars")
    print(r["url"])

The skill reads its API key from `AGNES_API_KEY` first, then falls back
to `OPENAI_API_KEY` (since Agnes is OpenAI-compatible and many users
already have that var set).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import requests

_LOG = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://apihub.agnes-ai.com/v1"
DEFAULT_MODEL = "agnes-image-2.1-flash"
TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class AgnesConfig:
    """Runtime config resolved from env vars."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout: int = TIMEOUT_SECONDS

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


def generate_image(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    size: str | None = None,
    n: int = 1,
    image: str | list[str] | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate one or more images via Agnes AI's OpenAI-compatible endpoint.

    Parameters
    ----------
    prompt
        Text description of the desired image. Required.
    model
        Agnes image model id. Default ``agnes-image-2.1-flash``
        (supports both text→image and image→image).
    size
        Optional WxH string like ``"1024x1024"``. When omitted the gateway
        picks a sensible default for the model.
    n
        Number of images to generate. Most Agnes image models accept 1-4.
    image
        Optional reference image URL (or list of URLs) for image-to-image.
        Passed through as ``extra_body.image``.
    api_key, base_url
        Override env-resolved config. ``base_url`` should NOT include the
        ``/images/generations`` suffix — it's appended automatically.
    extra
        Extra fields merged into the request body for forward compatibility.

    Returns
    -------
    dict
        ``{"url": str, "urls": list[str], "model": str, "created": int,
        "usage": dict}``. ``url`` is the first URL when ``n > 1``.

    Raises
    ------
    ValueError
        If ``prompt`` is empty or no API key resolved.
    RuntimeError
        If the gateway returns a non-200 status.
    """
    if not prompt or not str(prompt).strip():
        raise ValueError("prompt is required")
    if api_key is None or base_url is None:
        cfg = AgnesConfig.from_env()
        api_key = api_key or cfg.api_key
        base_url = (base_url or cfg.base_url).rstrip("/")

    payload: dict[str, Any] = {
        "model": model,
        "prompt": str(prompt).strip(),
        "n": max(1, int(n)),
    }
    if size:
        payload["size"] = size
    if image is not None:
        payload.setdefault("extra_body", {})["image"] = image
    if extra:
        # Shallow merge — extra_body fields combine; everything else is
        # overwritten by the explicit args above.
        for key, value in extra.items():
            if key == "extra_body" and isinstance(value, dict):
                payload.setdefault("extra_body", {}).update(value)
            elif key not in payload:
                payload[key] = value

    url = f"{base_url}/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    _LOG.info(
        "agnes_image_generate model=%s n=%d size=%s",
        model,
        payload["n"],
        size or "auto",
    )

    try:
        resp = requests.post(
            url,
            headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"agnes API request failed: {type(exc).__name__}: {exc}",
        ) from exc

    if resp.status_code != 200:
        body = resp.text[:500].replace("\n", " ")
        raise RuntimeError(
            f"agnes API error: HTTP {resp.status_code} — {body}",
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(
            f"agnes API returned non-JSON: {resp.text[:200]!r}",
        ) from exc

    items = data.get("data") or []
    urls: list[str] = []
    for item in items:
        if isinstance(item, dict):
            u = item.get("url") or item.get("image_url")
            if u:
                urls.append(str(u))

    return {
        "url": urls[0] if urls else "",
        "urls": urls,
        "model": data.get("model") or model,
        "created": data.get("created"),
        "usage": data.get("usage") or {},
        "raw": data,
    }


__all__ = ["AgnesConfig", "generate_image"]


if __name__ == "__main__":  # pragma: no cover — manual smoke test
    import argparse

    parser = argparse.ArgumentParser(description="Agnes image generate")
    parser.add_argument("prompt", help="Text prompt")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--size", default=None)
    parser.add_argument("--n", type=int, default=1)
    args = parser.parse_args()

    result = generate_image(
        args.prompt,
        model=args.model,
        size=args.size,
        n=args.n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import StreamingResponse

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]

try:
    import httpx  # type: ignore[import-untyped]

    HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    HTTPX_AVAILABLE = False
    httpx = None  # type: ignore[assignment]

from .config import MoliliConfig
from .links import MoliliLink, MoliliLinkStore

logger = logging.getLogger(__name__)

OFFICIAL_MODELS: list[dict[str, Any]] = [
    {
        "id": "minimax-m2.5",
        "object": "model",
        "created": 0,
        "owned_by": "molili",
        "display_name": "MiniMax M2.5",
        "multiplier": "0.2x",
        "recommended": True,
    },
    {
        "id": "glm-4.7",
        "object": "model",
        "created": 0,
        "owned_by": "molili",
        "display_name": "GLM-4.7",
        "multiplier": "0.6x",
        "recommended": True,
    },
    {
        "id": "kimi-k2.5",
        "object": "model",
        "created": 0,
        "owned_by": "molili",
        "display_name": "Kimi K2.5",
        "multiplier": "0.3x",
        "recommended": False,
    },
    {
        "id": "deepseek-v3.2",
        "object": "model",
        "created": 0,
        "owned_by": "molili",
        "display_name": "DeepSeek-V3.2",
        "multiplier": "0.5x",
        "recommended": False,
    },
    {
        "id": "qwen3-max",
        "object": "model",
        "created": 0,
        "owned_by": "molili",
        "display_name": "Qwen3-Max",
        "multiplier": "0.2x",
        "recommended": False,
    },
]


def _official_model_payload(*, include_auto: bool = False) -> dict[str, Any]:
    data: list[dict[str, Any]] = []
    if include_auto:
        data.append({
            "id": "molili",
            "object": "model",
            "created": 0,
            "owned_by": "molili",
            "display_name": "Molili (auto)",
        })
    data.extend(dict(m) for m in OFFICIAL_MODELS)
    return {"object": "list", "data": data}


def create_proxy_router(
    *,
    config: MoliliConfig,
    link_store: MoliliLinkStore,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    http_client: Any = None,
) -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(prefix="/api/molili/openai/v1", tags=["molili"])

    def _require_enabled() -> None:
        if not config.enabled:
            raise HTTPException(
                status_code=503,
                detail="Molili bridge disabled · config.molili.enabled=true",
            )

    def _actor(request: Request) -> str:
        from runtime.sensing.gateway.openai_gateway import _resolve_actor

        actor = _resolve_actor(
            request, identity_store, require_auth,
            jwt_secret=config.jwt_secret or jwt_secret,
            jwt_issuer=config.jwt_issuer or jwt_issuer,
            jwt_audience=jwt_audience,
        )
        if not actor:
            raise HTTPException(401, "authentication required")
        return actor

    def _link_or_404(actor: str) -> MoliliLink:
        link = link_store.get(actor)
        if link is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "no Molili account linked · login via SMS or POST /api/account/molili/link"
                ),
            )
        return link

    @router.get("/catalog")
    def list_model_catalog() -> dict[str, Any]:
        """Public Molili official-model catalog for UI rendering.

        Chat completions and `/models` remain account-gated, but the
        catalog is intentionally public so guests can see which official
        models exist while the frontend keeps them disabled until login.
        """
        _require_enabled()
        return _official_model_payload()

    @router.get("/models")
    def list_proxy_models(request: Request) -> dict[str, Any]:
        _require_enabled()
        actor = _actor(request)
        _link_or_404(actor)
        return _official_model_payload(include_auto=True)


    @router.post("/chat/completions")
    def proxy_chat_completions(request: Request) -> Any:
        _require_enabled()
        actor = _actor(request)
        link = _link_or_404(actor)

        import asyncio

        body_bytes = asyncio.run(request.body())

        try:
            parsed = json.loads(body_bytes or b"{}")
        except json.JSONDecodeError:
            raise HTTPException(400, "invalid JSON body") from None
        stream = bool(parsed.get("stream", False))

        upstream_url = f"{config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {link.molili_user_id}",
            "Content-Type": "application/json",
        }

        client = http_client
        if client is None:
            if not HTTPX_AVAILABLE:
                raise HTTPException(
                    503, "httpx not installed · add 'web' extra",
                )
            client = httpx

        if not stream:
            try:
                r = client.post(
                    upstream_url, headers=headers, content=body_bytes,
                    timeout=config.request_timeout_seconds,
                )
                status = getattr(r, "status_code", 0)
                if status >= 400:
                    raise HTTPException(
                        status, getattr(r, "text", "") or "upstream error",
                    )
                return r.json()
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(502, f"molili upstream: {exc}") from exc

        def _iter() -> Iterator[bytes]:
            try:
                with client.stream(
                    "POST", upstream_url, headers=headers, content=body_bytes,
                    timeout=None,
                ) as r:
                    if getattr(r, "status_code", 0) >= 400:
                        err = r.read() if hasattr(r, "read") else b""
                        yield (
                            b"data: "
                            + json.dumps({
                                "error": {
                                    "status": r.status_code,
                                    "body": err.decode("utf-8", "replace"),
                                },
                            }).encode("utf-8")
                            + b"\n\n"
                        )
                        yield b"data: [DONE]\n\n"
                        return
                    for chunk in r.iter_raw():
                        if chunk:
                            yield chunk
            except Exception as exc:  # noqa: BLE001
                yield (
                    b"data: "
                    + json.dumps({"error": {"body": str(exc)}}).encode("utf-8")
                    + b"\n\n"
                )
                yield b"data: [DONE]\n\n"

        return StreamingResponse(
            _iter(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router

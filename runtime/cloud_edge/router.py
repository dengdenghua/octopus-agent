"""FastAPI surface for the cloud control plane and signed edge devices."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .security import TokenError, decode_token, encode_token
from .store import CloudEdgeStore

TOKEN_ISSUER = "octopus-cloud-edge"
TOKEN_AUDIENCE = "octopus-edge-device"


class PairingBody(BaseModel):
    device_name: str = Field(default="Octopus Desktop", min_length=1, max_length=80)
    ttl_seconds: int = Field(default=600, ge=60, le=3600)


class EnrollBody(BaseModel):
    pairing_code: str = Field(min_length=24, max_length=256)
    public_key: str = Field(min_length=32, max_length=512)
    device_name: str = Field(default="", max_length=80)


class TokenBody(BaseModel):
    device_id: str = Field(min_length=8, max_length=128)
    challenge: str = Field(min_length=24, max_length=256)
    signature: str = Field(min_length=40, max_length=512)


class EntitlementBody(BaseModel):
    feature: str = Field(min_length=1, max_length=100)
    active: bool = True
    expires_at: int | None = None
    owner_id: str | None = Field(default=None, min_length=1, max_length=128)


class EdgeMessage(BaseModel):
    source: str = Field(min_length=1, max_length=40)
    source_room_id: str = Field(min_length=1, max_length=128)
    source_message_id: str = Field(min_length=1, max_length=160)
    title: str = Field(default="", max_length=240)
    content: str = Field(min_length=1, max_length=50_000)
    published_at: str | None = Field(default=None, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class MessageBatch(BaseModel):
    messages: list[EdgeMessage] = Field(min_length=1, max_length=100)


def _decode_public_key(value: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "invalid public key") from exc
    if len(raw) != 32:
        raise HTTPException(400, "public key must be Ed25519 raw bytes")
    return raw


def _verify_device_signature(
    public_key: str, *, device_id: str, challenge: str, signature: str
) -> None:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        sig = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        message = f"octopus-edge-token-v1:{device_id}:{challenge}".encode()
        Ed25519PublicKey.from_public_bytes(_decode_public_key(public_key)).verify(sig, message)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(401, "invalid device signature") from exc


def create_cloud_edge_router(
    *,
    db_path: str | Path,
    token_secret: str | None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    principal_resolver: Callable[[Request], Any] | None = None,
    operator_resolver: Callable[[Request], Any] | None = None,
) -> APIRouter:
    """Create the cloud edge router.

    Management APIs use the host account identity. Device APIs live outside
    the legacy control-plane prefix and authenticate with short-lived tokens.
    """

    router = APIRouter(tags=["cloud-edge"])
    store = CloudEdgeStore(db_path)
    signing_secret = str(token_secret or "").strip()

    def enabled() -> None:
        if len(signing_secret) < 32:
            raise HTTPException(503, "cloud edge is disabled: configure a strong token secret")

    def principal(request: Request) -> Any:
        enabled()
        if principal_resolver is not None:
            return principal_resolver(request)
        from runtime.safety.auth.principal import resolve_principal

        resolved = resolve_principal(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )
        if resolved is not None:
            return resolved
        if require_auth:
            raise HTTPException(401, "authentication required")
        return type("LocalPrincipal", (), {"tenant_id": "local", "actor_id": "local"})()

    def operator(request: Request) -> Any:
        enabled()
        if operator_resolver is not None:
            return operator_resolver(request)
        from runtime.safety.auth.principal import require_operator

        resolved = require_operator(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )
        if resolved is not None:
            return resolved
        if require_auth:
            raise HTTPException(401, "authentication required")
        return type("LocalPrincipal", (), {"tenant_id": "local", "actor_id": "local"})()

    def device_claims(request: Request) -> dict[str, Any]:
        enabled()
        header = str(request.headers.get("Authorization") or "")
        if not header.lower().startswith("bearer "):
            raise HTTPException(401, "missing device bearer token")
        try:
            claims = decode_token(
                header[7:].strip(),
                secret=signing_secret,
                issuer=TOKEN_ISSUER,
                audience=TOKEN_AUDIENCE,
            )
        except TokenError as exc:
            raise HTTPException(401, "invalid or expired device token") from exc
        if claims.get("token_use") != "edge_device":
            raise HTTPException(401, "invalid token use")
        device = store.device(str(claims.get("device_id") or ""))
        if device is None or device.get("revoked_at") is not None:
            raise HTTPException(401, "device revoked or unknown")
        if device["tenant_id"] != claims.get("tenant_id") or device["owner_id"] != claims.get(
            "sub"
        ):
            raise HTTPException(401, "device token binding mismatch")
        return claims

    @router.get("/api/cloud-edge/status")
    def status() -> dict[str, Any]:
        return {"enabled": len(signing_secret) >= 32, "token_ttl_seconds": 900}

    @router.post("/api/cloud-edge/pairing-codes")
    def create_pairing(body: PairingBody, request: Request) -> dict[str, Any]:
        actor = principal(request)
        return store.create_pairing_code(
            tenant_id=actor.tenant_id,
            owner_id=actor.actor_id,
            device_name=body.device_name,
            ttl_seconds=body.ttl_seconds,
        )

    @router.get("/api/cloud-edge/devices")
    def devices(request: Request) -> dict[str, Any]:
        actor = principal(request)
        return {"devices": store.list_devices(tenant_id=actor.tenant_id, owner_id=actor.actor_id)}

    @router.delete("/api/cloud-edge/devices/{device_id}")
    def revoke(device_id: str, request: Request) -> dict[str, Any]:
        actor = principal(request)
        return {
            "ok": store.revoke_device(
                tenant_id=actor.tenant_id, owner_id=actor.actor_id, device_id=device_id
            )
        }

    @router.put("/api/cloud-edge/entitlements")
    def set_entitlement(body: EntitlementBody, request: Request) -> dict[str, Any]:
        actor = operator(request)
        store.set_entitlement(
            tenant_id=actor.tenant_id,
            owner_id=body.owner_id or actor.actor_id,
            feature=body.feature,
            active=body.active,
            expires_at=body.expires_at,
        )
        return {"ok": True}

    @router.get("/api/cloud-edge/entitlements")
    def account_entitlements(request: Request) -> dict[str, Any]:
        actor = principal(request)
        return {
            "features": store.entitlements(
                tenant_id=actor.tenant_id,
                owner_id=actor.actor_id,
            )
        }

    @router.get("/api/cloud-edge/messages")
    def messages(request: Request, limit: int = 100, after_id: int = 0) -> dict[str, Any]:
        actor = principal(request)
        return {
            "messages": store.list_messages(
                tenant_id=actor.tenant_id,
                owner_id=actor.actor_id,
                limit=limit,
                after_id=after_id,
            )
        }

    @router.get("/api/cloud-edge/messages/stream")
    async def message_stream(
        request: Request,
        after_id: int = 0,
    ) -> StreamingResponse:
        actor = principal(request)

        async def events() -> Any:
            cursor = max(0, int(after_id))
            last_heartbeat = time.monotonic()
            while not await request.is_disconnected():
                batch = store.list_messages(
                    tenant_id=actor.tenant_id,
                    owner_id=actor.actor_id,
                    limit=100,
                    after_id=cursor,
                )
                if batch:
                    for item in batch:
                        cursor = max(cursor, int(item["id"]))
                        payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                        yield f"id: {cursor}\nevent: message\ndata: {payload}\n\n"
                    last_heartbeat = time.monotonic()
                    continue
                if time.monotonic() - last_heartbeat >= 15:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.monotonic()
                await asyncio.sleep(1)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post("/edge/v1/enroll")
    def enroll(body: EnrollBody) -> dict[str, Any]:
        enabled()
        _decode_public_key(body.public_key)
        device = store.enroll(
            pairing_code=body.pairing_code,
            public_key=body.public_key,
            device_name=body.device_name,
        )
        if device is None:
            raise HTTPException(401, "invalid, expired, or used pairing code")
        return {"ok": True, **device}

    @router.post("/edge/v1/challenge/{device_id}")
    def challenge(device_id: str) -> dict[str, Any]:
        enabled()
        value = store.create_challenge(device_id)
        if value is None:
            raise HTTPException(404, "device not found")
        return {"challenge": value, "expires_in": 120}

    @router.post("/edge/v1/token")
    def token(body: TokenBody) -> dict[str, Any]:
        enabled()
        device = store.device(body.device_id)
        if device is None or device.get("revoked_at") is not None:
            raise HTTPException(401, "device revoked or unknown")
        _verify_device_signature(
            str(device["public_key"]),
            device_id=body.device_id,
            challenge=body.challenge,
            signature=body.signature,
        )
        if not store.consume_challenge(device_id=body.device_id, challenge=body.challenge):
            raise HTTPException(401, "invalid, expired, or used challenge")
        now = int(time.time())
        features = store.entitlements(tenant_id=device["tenant_id"], owner_id=device["owner_id"])
        access_token = encode_token(
            {
                "iss": TOKEN_ISSUER,
                "aud": TOKEN_AUDIENCE,
                "sub": device["owner_id"],
                "tenant_id": device["tenant_id"],
                "device_id": body.device_id,
                "token_use": "edge_device",
                "features": features,
                "iat": now,
                "exp": now + 900,
            },
            signing_secret,
        )
        store.touch_device(body.device_id)
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 900,
            "features": features,
        }

    @router.get("/edge/v1/entitlements")
    def entitlements(  # noqa: B008 - FastAPI dependency declaration
        claims: dict[str, Any] = Depends(device_claims),  # noqa: B008
    ) -> dict[str, Any]:
        features = store.entitlements(
            tenant_id=str(claims["tenant_id"]), owner_id=str(claims["sub"])
        )
        return {"features": features}

    @router.post("/edge/v1/messages/batch")
    def ingest(  # noqa: B008 - FastAPI dependency declaration
        body: MessageBatch,
        claims: dict[str, Any] = Depends(device_claims),  # noqa: B008
    ) -> dict[str, Any]:
        features = store.entitlements(
            tenant_id=str(claims["tenant_id"]), owner_id=str(claims["sub"])
        )
        if "mx2025.sync" not in features:
            raise HTTPException(403, "mx2025.sync entitlement required")
        result = store.ingest_messages(
            tenant_id=str(claims["tenant_id"]),
            owner_id=str(claims["sub"]),
            device_id=str(claims["device_id"]),
            messages=[item.model_dump() for item in body.messages],
        )
        return {"ok": True, **result}

    return router


def default_cloud_edge_secret(jwt_secret: str | None) -> str | None:
    return os.environ.get("OCTOPUS_CLOUD_EDGE_TOKEN_SECRET") or jwt_secret


__all__ = ["create_cloud_edge_router", "default_cloud_edge_secret"]

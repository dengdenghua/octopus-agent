"""Resolve an actor id from an HTTP request's bearer credentials.

A small web-auth helper shared by the FastAPI routers in both
``adapters/integrations`` and ``sensing/gateway``. It used to live in
``sensing/gateway/openai_gateway/request_parser``, so the adapter
integration routers depended upward on the gateway just to authenticate
a request. It only needs the duck-typed request, a caller-supplied
identity store, and ``HTTPException``, so it sits here in the adapter
layer; ``openai_gateway`` re-exports it for the gateway's own routers.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def _resolve_actor(
    request: Any, identity_store: Any, require_auth: bool,
    *,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    jwt_leeway_seconds: int = 0,
    trust_jwt_sub: bool = True,
) -> str | None:
    if request is None:
        return None

    if identity_store is not None:
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()

            if jwt_secret and token.count(".") == 2:
                identity = identity_store.verify_jwt(
                    token,
                    secret=jwt_secret,
                    leeway_seconds=jwt_leeway_seconds,
                    required_issuer=jwt_issuer,
                    required_audience=jwt_audience,
                    trust_jwt_sub=trust_jwt_sub,
                )
                if identity is not None:
                    return identity.actor_id
                if require_auth:
                    raise HTTPException(401, "invalid jwt")

            # 2. API key
            identity = identity_store.verify_api_key(token)
            if identity is not None:
                return identity.actor_id
            if require_auth:
                raise HTTPException(401, "invalid token")

        if require_auth:
            raise HTTPException(401, "missing Authorization: Bearer <token>")

    return None

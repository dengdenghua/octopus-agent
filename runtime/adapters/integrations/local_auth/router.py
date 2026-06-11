
from __future__ import annotations

import logging
import re
import time
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import Response
    from pydantic import BaseModel, Field

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]
    Response = None  # type: ignore[assignment, misc]

from .config import LocalAuthConfig, verify_password

logger = logging.getLogger(__name__)

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._@\-]{1,64}$")


if FASTAPI_AVAILABLE:

    class LoginRequest(BaseModel):
        username: str = Field(..., min_length=1, max_length=64)
        password: str | None = Field(default=None, max_length=256)
        display_name: str | None = Field(default=None, max_length=128)

    class LoginResponse(BaseModel):
        success: bool
        actor_id: str
        access_token: str | None = None
        token_type: str = "Bearer"
        expires_in: int | None = None
        user: dict[str, Any] = Field(default_factory=dict)

    class WhoamiResponse(BaseModel):
        actor_id: str
        roles: list[str] = Field(default_factory=list)
        metadata: dict[str, Any] = Field(default_factory=dict)


def create_local_auth_router(
    *,
    config: LocalAuthConfig,
    identity_store: Any = None,
) -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(prefix="/api/auth/local", tags=["auth", "local"])

    def _require_enabled() -> None:
        if not config.enabled:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Local auth disabled · set config.local_auth.enabled=true "
                    "（注意：无密码 · 不对外开放）"
                ),
            )

    def _check_username(username: str) -> None:
        if not _USERNAME_RE.match(username):
            raise HTTPException(
                status_code=400,
                detail="username 只能含字母/数字/._@- · 长度 1-64",
            )

    def _check_credentials(username: str, password: str | None) -> None:
        _check_username(username)

        if config.password_required:
            if username not in config.users:
                raise HTTPException(status_code=401, detail="用户名或密码错误")
            if not password:
                raise HTTPException(status_code=401, detail="用户名或密码错误")
            expected_hash = config.users[username]
            if not verify_password(password, expected_hash):
                raise HTTPException(status_code=401, detail="用户名或密码错误")
            return

        if not config.allow_any_username:
            if username not in config.allowed_usernames:
                raise HTTPException(status_code=403, detail="用户名不在白名单")
            return


    @router.post("/login", response_model=LoginResponse)
    def login(body: LoginRequest, request: Request) -> LoginResponse:
        _require_enabled()
        _check_credentials(body.username, body.password)

        actor_id = f"{config.actor_prefix}{body.username}"
        created = False

        if identity_store is not None:
            from runtime.safety.auth.identity import Identity

            existing = (
                identity_store.get(actor_id)
                if hasattr(identity_store, "get")
                else None
            )
            if existing is None:
                meta: dict[str, Any] = {
                    "provider": "local",
                    "username": body.username,
                    "created_at": time.time(),
                }
                if body.display_name:
                    meta["display_name"] = body.display_name
                try:
                    identity_store.add(
                        Identity(
                            actor_id=actor_id,
                            roles=tuple(config.default_roles),
                            metadata=meta,
                        ),
                    )
                    created = True
                except ValueError:  # noqa: BLE001 — duplicate identity silently skipped
                    pass

        access_token: str | None = None
        expires_in: int | None = None
        if config.jwt_secret:
            from runtime.safety.auth.identity import encode_jwt_hs256

            now = int(time.time())
            claims: dict[str, Any] = {
                "sub": actor_id,
                "iat": now,
                "exp": now + config.jwt_expire_seconds,
                "provider": "local",
                "username": body.username,
            }
            if config.jwt_issuer:
                claims["iss"] = config.jwt_issuer
            access_token = encode_jwt_hs256(claims, secret=config.jwt_secret)
            expires_in = config.jwt_expire_seconds

        logger.info(
            "local_auth login · actor=%s created=%s",
            actor_id, created,
        )
        _ = request

        return LoginResponse(
            success=True,
            actor_id=actor_id,
            access_token=access_token,
            expires_in=expires_in,
            user={
                "actor_id": actor_id,
                "username": body.username,
                "display_name": body.display_name,
                "provider": "local",
                "created": created,
            },
        )

    @router.post("/logout", status_code=204, response_class=Response, response_model=None)
    def logout():
        return None

    @router.get("/whoami", response_model=WhoamiResponse)
    def whoami(request: Request) -> WhoamiResponse:
        _require_enabled()
        if identity_store is None:
            raise HTTPException(
                status_code=501,
                detail="no identity_store configured · cannot verify token",
            )
        from runtime.sensing.gateway.openai_gateway import _resolve_actor

        actor = _resolve_actor(
            request,
            identity_store,
            require_auth=True,
            jwt_secret=config.jwt_secret,
            jwt_issuer=config.jwt_issuer,
        )
        if not actor:
            raise HTTPException(401, "not authenticated")
        identity = identity_store.get(actor)
        if identity is None:
            raise HTTPException(401, "unknown actor")
        return WhoamiResponse(
            actor_id=identity.actor_id,
            roles=list(identity.roles),
            metadata=dict(identity.metadata),
        )

    return router

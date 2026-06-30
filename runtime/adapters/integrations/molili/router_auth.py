# ruff: noqa: E402 — module-level imports below are intentionally late

from __future__ import annotations

import hmac
import logging
import secrets
import threading
import time
from typing import Any


def secrets_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)

try:
    from fastapi import APIRouter, HTTPException, Request
    from pydantic import BaseModel, Field

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]

from .client import mask_phone, pluck, post_upstream
from .config import MoliliConfig
from .links import MoliliLink, MoliliLinkStore

logger = logging.getLogger(__name__)


def _actor_from_phone(identifier: str) -> str:
    """Stable actor id from the login identifier.

    The gateway may send a phone OR an email — the mobile gateway uses email
    login. Digits-only extraction would collapse every email to the same actor
    (``molili:``), merging all email users into one identity; so keep digits for
    a pure phone and fall back to the full (lowercased) identifier otherwise.
    """
    ident = (identifier or "").strip()
    digits = "".join(ch for ch in ident if ch.isdigit() or ch == "+")
    if digits and digits == ident:
        return "molili:" + digits
    return "molili:" + ident.lower()


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


if FASTAPI_AVAILABLE:

    class SmsSendRequest(BaseModel):
        phone: str = Field(..., description="手机号 E.164 或纯数字")

    class SmsVerifyRequest(BaseModel):
        phone: str
        code: str = Field(..., description="短信 6 位验证码")

    class SmsSendResponse(BaseModel):
        sent: bool
        upstream: dict[str, Any] = Field(default_factory=dict)

    class SmsLoginResponse(BaseModel):
        success: bool
        actor_id: str
        access_token: str | None = None
        token_type: str = "Bearer"
        expires_in: int | None = None
        user: dict[str, Any] = Field(default_factory=dict)
        credits: dict[str, Any] = Field(default_factory=dict)


def create_auth_router(
    *,
    config: MoliliConfig,
    link_store: MoliliLinkStore,
    identity_store: Any = None,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    http_client: Any = None,
) -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(prefix="/api/auth/molili", tags=["molili", "auth"])

    effective_jwt_secret = config.jwt_secret or jwt_secret
    effective_jwt_issuer = config.jwt_issuer or jwt_issuer

    _mock_codes: dict[str, tuple[str, float]] = {}  # phone → (code, expires_at)
    _mock_lock = threading.Lock()
    _MOCK_TTL = 300.0  # noqa: N806

    def _mock_generate(phone: str) -> str:
        if config.auth.mock_code:
            return config.auth.mock_code
        return f"{secrets.randbelow(1_000_000):06d}"

    def _mock_check(phone: str, code: str) -> bool:
        if config.auth.mock_code and code == config.auth.mock_code:
            return True
        with _mock_lock:
            entry = _mock_codes.get(phone)
            if entry is None:
                return False
            stored, exp = entry
            if time.time() > exp:
                _mock_codes.pop(phone, None)
                return False
            ok = secrets_compare(stored, code)
            if ok:
                _mock_codes.pop(phone, None)
            return ok


    def _require_enabled() -> None:
        if not config.enabled:
            raise HTTPException(
                status_code=503,
                detail="Molili bridge disabled · config.molili.enabled=true",
            )
        if config.auth.mock_mode:
            return
        if not config.auth.sms_send_url or not config.auth.sms_verify_url:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Molili SMS endpoints not configured · "
                    "set config.molili.auth.sms_send_url/sms_verify_url "
                    "或设 mock_mode=true 用本地 mock"
                ),
            )


    @router.post("/sms/send", response_model=SmsSendResponse)
    def sms_send(body: SmsSendRequest) -> SmsSendResponse:
        _require_enabled()

        if config.auth.mock_mode:
            code = _mock_generate(body.phone)
            with _mock_lock:
                _mock_codes[body.phone] = (code, time.time() + _MOCK_TTL)
            logger.warning(
                "[MOCK SMS] phone=%s  code=%s  (TTL=%ds)",
                mask_phone(body.phone), code, int(_MOCK_TTL),
            )
            return SmsSendResponse(
                sent=True,
                upstream={
                    "mock": True,
                    "hint": "code printed to server log",
                    "code_for_dev": code if config.auth.mock_code else None,
                },
            )

        payload: dict[str, Any] = {config.auth.send_phone_field: body.phone}
        if config.auth.sms_type:
            payload["smsType"] = config.auth.sms_type
        try:
            upstream = post_upstream(
                config.auth.sms_send_url or "",
                payload,
                timeout=config.request_timeout_seconds,
                http_client=http_client,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"molili sms_send failed: {exc}",
            ) from exc
        return SmsSendResponse(sent=True, upstream=upstream)

    @router.post("/sms/verify", response_model=SmsLoginResponse)
    def sms_verify(
        body: SmsVerifyRequest, request: Request,
    ) -> SmsLoginResponse:
        _require_enabled()
        t_total = time.perf_counter()

        if config.auth.mock_mode:
            if not _mock_check(body.phone, body.code):
                raise HTTPException(
                    status_code=401, detail="验证码错误或已过期（mock mode）",
                )
            fake_user_id = "mock-" + "".join(
                ch for ch in body.phone if ch.isdigit()
            )
            data: dict[str, Any] = {
                "data": {
                    "userId": fake_user_id,
                    "token": f"mock-token-{fake_user_id}",
                    "userInfo": {
                        "mobile": body.phone,
                        "surplusCredits": 1000,
                        "modelDisplayName": config.default_model,
                        "isMember": False,
                        "mock": True,
                    },
                },
            }
            t_upstream_ms = 0
        else:
            upstream_body = {
                config.auth.verify_phone_field: body.phone,
                config.auth.code_field: body.code,
            }
            t_up = time.perf_counter()
            try:
                data = post_upstream(
                    config.auth.sms_verify_url or "",
                    upstream_body,
                    timeout=config.request_timeout_seconds,
                    http_client=http_client,
                )
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=502, detail=f"molili sms_verify failed: {exc}",
                ) from exc
            t_upstream_ms = int((time.perf_counter() - t_up) * 1000)

        molili_user_id = pluck(data, config.auth.user_id_path)
        molili_token = pluck(data, config.auth.token_path)
        if not molili_user_id or not molili_token:
            raise HTTPException(
                status_code=502,
                detail=(
                    "molili verify response missing userId/token at configured paths"
                ),
            )
        mobile_display = pluck(data, config.auth.mobile_path) or body.phone
        credits_blob = pluck(data, config.auth.credits_path) or {}
        if not isinstance(credits_blob, dict):
            credits_blob = {}

        # ─── Identity upsert ─────────────────────────
        actor_id = _actor_from_phone(body.phone)
        created = False
        try:
            if identity_store is not None:
                from runtime.safety.auth.identity import Identity

                existing = identity_store.get(actor_id) if hasattr(
                    identity_store, "get",
                ) else None
                if existing is None:
                    identity = Identity(
                        actor_id=actor_id,
                        roles=("user", "molili"),
                        metadata={
                            "provider": "molili",
                            "mobile": mobile_display,
                            "molili_user_id": str(molili_user_id),
                            "created_at": time.time(),
                        },
                    )
                    try:
                        identity_store.add(identity)
                        created = True
                    except ValueError:  # noqa: BLE001 — duplicate identity silently skipped
                        pass
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "molili identity upsert failed (non-fatal): %s", exc,
            )

        try:
            link_store.put(
                MoliliLink(
                    octopus_user_id=actor_id,
                    molili_user_id=str(molili_user_id),
                    molili_token=str(molili_token),
                    mobile=str(mobile_display),
                    linked_at=time.time(),
                    last_synced_at=time.time(),
                    credits_snapshot=credits_blob,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "molili link_store.put failed: %s", exc, exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=f"保存登录凭证失败: {exc}",
            ) from exc

        access_token: str | None = None
        expires_in: int | None = None
        if effective_jwt_secret:
            try:
                from runtime.safety.auth.identity import encode_jwt_hs256

                now = int(time.time())
                claims: dict[str, Any] = {
                    "sub": actor_id,
                    "iat": now,
                    "exp": now + config.jwt_expire_seconds,
                    "provider": "molili",
                    "mobile": mobile_display,
                }
                if effective_jwt_issuer:
                    claims["iss"] = effective_jwt_issuer
                if jwt_audience:
                    claims["aud"] = jwt_audience
                access_token = encode_jwt_hs256(claims, secret=effective_jwt_secret)
                expires_in = config.jwt_expire_seconds
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "molili JWT signing failed: %s", exc, exc_info=True,
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"JWT 签发失败: {exc}",
                ) from exc

        t_total_ms = int((time.perf_counter() - t_total) * 1000)
        logger.info(
            "molili sms_verify ok · total_ms=%d upstream_ms=%d created=%s phone=%s",
            t_total_ms, t_upstream_ms, created, mask_phone(body.phone),
        )
        _ = request  # audit hook placeholder

        return SmsLoginResponse(
            success=True,
            actor_id=actor_id,
            access_token=access_token,
            expires_in=expires_in,
            user={
                "actor_id": actor_id,
                "mobile": mobile_display,
                "provider": "molili",
                "created": created,
            },
            credits=credits_blob,
        )

    return router

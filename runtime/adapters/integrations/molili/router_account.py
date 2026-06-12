
from __future__ import annotations

import logging
import time
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request
    from pydantic import BaseModel, Field

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]

import contextlib

from .client import (
    detect_dead_token,
    get_upstream,
    pluck,
    post_upstream_order,
)
from .config import MoliliConfig
from .links import MoliliLink, MoliliLinkStore

logger = logging.getLogger(__name__)


def _credits_base_url(config: MoliliConfig) -> str | None:
    if not config.info_url:
        return None
    return config.info_url.rsplit("/userApi/", 1)[0]


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


if FASTAPI_AVAILABLE:

    class MoliliLinkRequest(BaseModel):
        molili_user_id: str = Field(..., description="Molili userId")
        molili_token: str = Field(..., description="Molili session token")
        mobile: str | None = None
        credits_snapshot: dict[str, Any] | None = None

    class MoliliLinkResponse(BaseModel):
        molili_user_id: str
        mobile: str | None = None
        linked_at: float
        last_synced_at: float | None = None
        credits: dict[str, Any] = Field(default_factory=dict)
        token_invalid: bool = False
        token_invalid_reason: str | None = None

    class DailyClaimRequest(BaseModel):
        draw: bool = Field(
            default=False,
            description="true=抽奖  false=直接领取固定额度",
        )

    class PaymentLinkRequest(BaseModel):
        goods_id: int = Field(..., description="Molili GoodsCo.id")


def create_account_router(
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

    router = APIRouter(prefix="/api/account/molili", tags=["molili"])

    def _require_enabled() -> None:
        if not config.enabled:
            raise HTTPException(
                status_code=503,
                detail="Molili bridge disabled · config.molili.enabled=true",
            )

    def _actor(request: Request) -> str:
        from runtime.adapters.web_auth import _resolve_actor

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
                    "no Molili account linked · "
                    "POST /api/auth/molili/sms/verify or /api/account/molili/link first"
                ),
            )
        return link


    def _link_to_response(
        link: MoliliLink,
        *,
        token_invalid: bool | None = None,
        token_invalid_reason: str | None = None,
    ) -> MoliliLinkResponse:
        effective_invalid = (
            bool(link.token_invalid) if token_invalid is None else token_invalid
        )
        effective_reason = (
            link.token_invalid_reason
            if token_invalid_reason is None and token_invalid is None
            else token_invalid_reason
        )
        return MoliliLinkResponse(
            molili_user_id=link.molili_user_id,
            mobile=link.mobile,
            linked_at=link.linked_at,
            last_synced_at=link.last_synced_at,
            credits=link.credits_snapshot or {},
            token_invalid=effective_invalid,
            token_invalid_reason=effective_reason,
        )

    # ─── link / unlink / show / refresh ─────────────

    @router.post("/link", response_model=MoliliLinkResponse)
    def link_molili(
        body: MoliliLinkRequest, request: Request,
    ) -> MoliliLinkResponse:
        _require_enabled()
        actor = _actor(request)
        link = MoliliLink(
            octopus_user_id=actor,
            molili_user_id=body.molili_user_id,
            molili_token=body.molili_token,
            mobile=body.mobile,
            linked_at=time.time(),
            credits_snapshot=body.credits_snapshot or {},
        )
        link_store.put(link)
        logger.info("molili link set for actor %s", actor)
        return _link_to_response(link)

    @router.delete("/link")
    def unlink_molili(request: Request) -> dict[str, bool]:
        _require_enabled()
        actor = _actor(request)
        removed = link_store.delete(actor)
        return {"unlinked": removed}

    @router.get("", response_model=MoliliLinkResponse)
    def show_molili(request: Request) -> MoliliLinkResponse:
        _require_enabled()
        actor = _actor(request)
        link = _link_or_404(actor)
        if (
            config.info_url
            and isinstance(link.credits_snapshot, dict)
            and not isinstance(link.credits_snapshot.get("surplusCredits"), int)
        ):
            return refresh_molili(request)
        return _link_to_response(link)

    @router.post("/refresh", response_model=MoliliLinkResponse)
    def refresh_molili(request: Request) -> MoliliLinkResponse:
        _require_enabled()
        actor = _actor(request)
        link = _link_or_404(actor)
        if not config.info_url:
            return _link_to_response(link)

        credits_base = _credits_base_url(config)
        dead_token_hint: str | None = None
        info: dict[str, Any] | None = None
        authoritative_balance: int | None = None
        credits_summary: dict[str, Any] | None = None

        try:
            if credits_base:
                try:
                    probe = get_upstream(
                        f"{credits_base}/goodsApi/v1/goodsDetailList",
                        token=link.molili_token,
                        timeout=config.request_timeout_seconds,
                        http_client=http_client,
                    )
                    dead_token_hint = detect_dead_token(probe)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("molili goods probe failed: %s", exc)

            # 1) userInfo
            try:
                info = get_upstream(
                    config.info_url,
                    token=link.molili_token,
                    timeout=config.request_timeout_seconds,
                    http_client=http_client,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("molili userInfo failed: %s", exc)
                info = None

            if credits_base and isinstance(info, dict):
                info_data_for_uid = (info.get("data") or {})
                uid = (
                    info_data_for_uid.get("userId")
                    if isinstance(info_data_for_uid, dict)
                    else None
                ) or link.molili_user_id
                try:
                    bal_resp = get_upstream(
                        f"{credits_base}/creditsApi/v1/surplusCreditsQuery",
                        token=link.molili_token,
                        timeout=config.request_timeout_seconds,
                        params={"userId": uid},
                        http_client=http_client,
                    )
                    if (
                        isinstance(bal_resp, dict)
                        and bal_resp.get("success")
                        and bal_resp.get("data") is not None
                    ):
                        with contextlib.suppress(TypeError, ValueError):
                            authoritative_balance = int(bal_resp["data"])
                except Exception as exc:  # noqa: BLE001
                    logger.debug("molili balance query failed: %s", exc)

            if credits_base:
                try:
                    page = post_upstream_order(
                        f"{credits_base}/creditsApi/v1/page",
                        {"pageNum": 1, "pageSize": 100},
                        token=link.molili_token,
                        timeout=config.request_timeout_seconds,
                        http_client=http_client,
                    )
                    if page and page.get("success"):
                        records = ((page.get("data") or {}).get("records")) or []
                        by_type: dict[str, dict[str, int]] = {}
                        for rec in records:
                            t = (rec.get("type") or "other").lower()
                            bucket = by_type.setdefault(
                                t, {"granted": 0, "remaining": 0},
                            )
                            bucket["granted"] += rec.get("credits") or 0
                            bucket["remaining"] += rec.get("surplusCredits") or 0
                        credits_summary = {
                            "by_type": by_type,
                            "total_remaining": sum(
                                b["remaining"] for b in by_type.values()
                            ),
                            "total_granted": sum(
                                b["granted"] for b in by_type.values()
                            ),
                        }
                except Exception as exc:  # noqa: BLE001
                    logger.debug("molili credits page failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("molili refresh failed for %s: %s", actor, exc)
            return _link_to_response(link)

        if info is None:
            return _link_to_response(link)

        dead_reason = dead_token_hint or detect_dead_token(info)
        if dead_reason:
            logger.warning("molili token invalid for %s: %s", actor, dead_reason)
            marked = link_store.mark_token_invalid(actor, dead_reason)
            return _link_to_response(
                marked or link,
                token_invalid=True,
                token_invalid_reason=dead_reason,
            )

        info_data = info.get("data") if isinstance(info, dict) else None
        configured_credits = pluck(info, config.auth.credits_path)
        if isinstance(configured_credits, dict):
            credits: dict[str, Any] = dict(configured_credits)
        elif isinstance(info_data, dict):
            credits = dict(info_data)
        else:
            credits = {}

        if authoritative_balance is not None:
            credits["surplusCredits"] = authoritative_balance
        if credits_summary is not None:
            if authoritative_balance is not None:
                credits_summary["total_remaining"] = authoritative_balance
            credits["creditsSummary"] = credits_summary

        updated = link_store.update_credits(
            actor, credits, now=time.time(),
        )
        return _link_to_response(updated or link)


    @router.get("/daily-claim/info")
    def daily_claim_info(request: Request) -> dict[str, Any]:
        _require_enabled()
        actor = _actor(request)
        link = _link_or_404(actor)
        base = _credits_base_url(config)
        if not base:
            raise HTTPException(
                503, "molili.info_url not configured",
            )
        try:
            return get_upstream(
                f"{base}/dailyCreditsClaimApi/v1/info",
                token=link.molili_token,
                timeout=config.request_timeout_seconds,
                http_client=http_client,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"molili: {exc}") from exc

    @router.post("/daily-claim/claim")
    def daily_claim_claim(
        body: DailyClaimRequest, request: Request,
    ) -> dict[str, Any]:
        _require_enabled()
        actor = _actor(request)
        link = _link_or_404(actor)
        base = _credits_base_url(config)
        if not base:
            raise HTTPException(503, "molili.info_url not configured")
        try:
            result = post_upstream_order(
                f"{base}/dailyCreditsClaimApi/v1/claim",
                {"claimType": "lottery" if body.draw else "direct"},
                token=link.molili_token,
                timeout=config.request_timeout_seconds,
                http_client=http_client,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"molili: {exc}") from exc

        # best-effort refresh
        try:
            refresh_molili(request)
        except Exception as exc:  # noqa: BLE001
            logger.debug("post-claim refresh failed: %s", exc)
        return result


    @router.get("/goods/detail")
    def goods_detail(request: Request) -> dict[str, Any]:
        _require_enabled()
        actor = _actor(request)
        link = _link_or_404(actor)
        base = _credits_base_url(config)
        if not base:
            raise HTTPException(503, "molili.info_url not configured")
        try:
            return get_upstream(
                f"{base}/goodsApi/v1/goodsDetailList",
                token=link.molili_token,
                timeout=config.request_timeout_seconds,
                http_client=http_client,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"molili: {exc}") from exc

    @router.post("/orders/payment-link")
    def create_payment_link(
        body: PaymentLinkRequest, request: Request,
    ) -> dict[str, Any]:
        _require_enabled()
        actor = _actor(request)
        link = _link_or_404(actor)
        base = _credits_base_url(config)
        if not base:
            raise HTTPException(503, "molili.info_url not configured")
        try:
            return post_upstream_order(
                f"{base}/orderApi/v1/paymentLink",
                {"goodsId": body.goods_id},
                token=link.molili_token,
                timeout=config.request_timeout_seconds,
                http_client=http_client,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"molili: {exc}") from exc

    @router.get("/orders/{order_no}")
    def find_order(order_no: str, request: Request) -> dict[str, Any]:
        _require_enabled()
        actor = _actor(request)
        link = _link_or_404(actor)
        base = _credits_base_url(config)
        if not base:
            raise HTTPException(503, "molili.info_url not configured")
        try:
            return get_upstream(
                f"{base}/orderApi/v1/findByOrderNo",
                token=link.molili_token,
                timeout=config.request_timeout_seconds,
                params={"orderNo": order_no},
                http_client=http_client,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"molili: {exc}") from exc

    @router.post("/orders/{order_no}/confirm")
    def confirm_order(order_no: str, request: Request) -> dict[str, Any]:
        _require_enabled()
        actor = _actor(request)
        link = _link_or_404(actor)
        base = _credits_base_url(config)
        if not base:
            raise HTTPException(503, "molili.info_url not configured")
        try:
            upstream = get_upstream(
                f"{base}/orderApi/v1/findByOrderNo",
                token=link.molili_token,
                timeout=config.request_timeout_seconds,
                params={"orderNo": order_no},
                http_client=http_client,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"molili: {exc}") from exc

        data = upstream.get("data") if isinstance(upstream, dict) else None
        status = (
            data.get("orderStatus")
            if isinstance(data, dict) and data.get("orderStatus") is not None
            else None
        )
        paid = status in (200, 400)
        if paid:
            try:
                refresh_molili(request)
            except Exception as exc:  # noqa: BLE001
                logger.debug("post-payment refresh failed: %s", exc)
        return {"order_status": status, "paid": paid, "upstream": upstream}

    return router

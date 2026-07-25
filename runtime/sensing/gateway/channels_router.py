from __future__ import annotations

import contextlib
import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter, HTTPException, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]

from runtime.sensing._fastapi_guard import require_fastapi

class LocalChannelManager:
    """Small channel manager for dashboard-only sessions.

    ╔════════════════════════════════════════════════════════════════════╗
    ║ channels_router.py · navigation map (1427 lines).                  ║
    ║                                                                    ║
    ║   §1 LocalChannelManager (in-memory store)        ~L25             ║
    ║   §2 create_channels_router (factory)             ~L52             ║
    ║       §2.1 /api/channels (list)                   ~L137            ║
    ║       §2.2 /api/channels/{id}/assistant           ~L195            ║
    ║       §2.3 /api/channels/credentials/{platform}   ~L236            ║
    ║       §2.4 /api/channels/wechat/qr/{start,poll}   ~L317            ║
    ║       §2.5 /api/channels/{id}/pairings + approve  ~L393            ║
    ║       §2.6 /api/channels/{id}/inbound             ~L483            ║
    ║   §3 _PairingStore + state load/save              ~L728            ║
    ║   §4 channel constructor registry + _make_*       ~L904            ║
    ║                                                                    ║
    ║ Each platform's _make_* helper is < 15 lines and shares signature; ║
    ║ they live together because the registry resolves them by name.    ║
    ╚════════════════════════════════════════════════════════════════════╝
    """

    def __init__(self) -> None:
        self._channels: dict[str, Any] = {}

    def register(self, channel: Any) -> None:
        channel_id = getattr(channel, "channel_id", None)
        if not channel_id:
            raise ValueError(f"channel {type(channel).__name__} missing channel_id")
        if hasattr(channel, "bind_dispatcher"):
            channel.bind_dispatcher(self.process_inbound)
        self._channels[str(channel_id)] = channel

    def has(self, channel_id: str) -> bool:
        return channel_id in self._channels

    def get(self, channel_id: str) -> Any:
        return self._channels[channel_id]

    def channel_ids(self) -> list[str]:
        return sorted(self._channels)

    def process_inbound(self, _msg: Any) -> Any:
        raise RuntimeError("channel runtime is not available in this UI session")


def create_channels_router(
    *,
    manager: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    state_path: str | Path | None = None,
) -> Any:
    require_fastapi(__name__)

    if manager is None:
        manager = LocalChannelManager()

    if state_path is None:
        state_path = os.environ.get("OCTOPUS_CHANNEL_STATE") or "data/channel_state.json"
    _state_file: Path | None = Path(state_path) if state_path else None
    _creds_file: Path | None = (
        _state_file.with_name(
            _state_file.stem + ".credentials" + _state_file.suffix,
        )
        if _state_file is not None
        else None
    )
    _load_state(manager, _state_file)
    _load_credentials_and_bootstrap(manager, _creds_file)

    router = APIRouter(tags=["channels"])

    def _auth(request: Any) -> str | None:
        from .openai_gateway_router import _resolve_actor

        return _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    def _resolve_identity(request: Any) -> Any:
        """Resolve full Identity for role checks. None when auth disabled."""
        if not require_auth or identity_store is None:
            return None
        auth_header = request.headers.get("Authorization") or ""
        if not auth_header.lower().startswith("bearer "):
            return None
        token = auth_header[7:].strip()
        if jwt_secret and token.count(".") == 2:
            with contextlib.suppress(Exception):
                identity = identity_store.verify_jwt(
                    token,
                    secret=jwt_secret,
                    required_issuer=jwt_issuer,
                    required_audience=jwt_audience,
                )
                if identity is not None:
                    return identity
        with contextlib.suppress(Exception):
            return identity_store.verify_api_key(token)
        return None

    def _require_admin(request: Any) -> None:
        """Gate for global channel configuration mutations.

        Channels manage shared IM credentials, agent assignments, and
        pairing approvals — all global per-server state. A regular user
        should not be able to rotate Discord tokens, reassign which
        agent answers a channel, or approve a stranger's pairing.

        No-op when ``require_auth=False`` (single-user dev mode).
        """
        _auth(request)  # AUTH-OK: actor-agnostic — credential check; role check follows
        if not require_auth:
            return
        identity = _resolve_identity(request)
        roles = getattr(identity, "roles", ()) or ()
        if "admin" not in {str(r).lower() for r in roles}:
            raise HTTPException(403, "admin role required for channel configuration")

    #
    #

    @router.get("/api/channels")
    def list_channels(request: Request) -> list[dict[str, Any]]:
        _auth(request)  # AUTH-OK: actor-agnostic — channel registry is server-global
        registered_ids = set(manager.channel_ids())
        seen: set[str] = set()
        assignments = _assignments()
        pairings = _pairings(manager)
        out: list[dict[str, Any]] = []

        for cid in manager.channel_ids():
            platform = _guess_platform(
                cid,
                type(manager.get(cid)).__name__,
            )
            meta = _PLATFORM_META.get(platform, _FALLBACK_META)
            out.append(
                {
                    "channel_id": cid,
                    "type": type(manager.get(cid)).__name__,
                    "platform": platform,
                    "connected": True,
                    "display_name": meta["display_name"],
                    "description": meta["description"],
                    "help_url": meta["help_url"],
                    "metrics": pairings.metrics(cid),
                    "assigned_agent_id": assignments.get(cid),
                }
            )
            seen.add(platform)

        for platform, meta in _PLATFORM_META.items():
            if platform in seen:
                continue
            out.append(
                {
                    "channel_id": platform,  # Implementation note.
                    "type": meta["cls_name"],
                    "platform": platform,
                    "connected": False,
                    "display_name": meta["display_name"],
                    "description": meta["description"],
                    "help_url": meta["help_url"],
                    "metrics": _zero_metrics(),
                    "assigned_agent_id": assignments.get(platform),
                }
            )
            seen.add(platform)

        _ = registered_ids  # Implementation note.
        return out

    def _assignments() -> dict[str, str]:
        a = getattr(manager, "_channel_assignments", None)
        if a is None:
            a = {}
            try:
                manager._channel_assignments = a
            except (AttributeError, TypeError):
                _FALLBACK_ASSIGNMENTS.clear()
                return _FALLBACK_ASSIGNMENTS
        return a

    @router.get("/api/channels/{channel_id}/assistant")
    def get_channel_assignment(
        channel_id: str,
        request: Request,
    ) -> dict[str, Any]:
        _auth(request)  # AUTH-OK: actor-agnostic — assignments are server-global
        safe_channel_id = _normalize_channel_id(channel_id)
        if safe_channel_id is None:
            raise HTTPException(400, "invalid channel_id")
        return {"channel_id": safe_channel_id, "agent_id": _assignments().get(safe_channel_id)}

    @router.post("/api/channels/{channel_id}/assistant")
    async def set_channel_assignment(
        channel_id: str,
        request: Request,
    ) -> dict[str, Any]:
        _require_admin(request)  # Mutation: assigns which agent handles this channel (global state)
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise HTTPException(400, f"body: {e}") from e
        agent_id = (body or {}).get("agent_id")
        safe_channel_id = _normalize_channel_id(channel_id)
        safe_agent_id = _normalize_agent_id(agent_id)
        if safe_channel_id is None:
            raise HTTPException(400, "invalid channel_id")
        if safe_agent_id is None:
            raise HTTPException(400, "invalid agent_id")
        _assignments()[safe_channel_id] = safe_agent_id
        _save_state(manager, _state_file)
        return {
            "channel_id": safe_channel_id,
            "agent_id": safe_agent_id,
            "ok": True,
        }

    @router.delete("/api/channels/{channel_id}/assistant")
    def delete_channel_assignment(
        channel_id: str,
        request: Request,
    ) -> dict[str, Any]:
        _require_admin(request)  # Mutation: removes agent assignment
        safe_channel_id = _normalize_channel_id(channel_id)
        if safe_channel_id is None:
            raise HTTPException(400, "invalid channel_id")
        dropped = _assignments().pop(safe_channel_id, None)
        _save_state(manager, _state_file)
        return {"channel_id": safe_channel_id, "dropped": dropped, "ok": True}

    #
    #
    #

    @router.get("/api/channels/credentials")
    def list_credentials(request: Request) -> dict[str, Any]:
        _auth(request)  # AUTH-OK: actor-agnostic — credentials list is server-global (masked)
        creds = _credentials_on(manager)
        return {
            "credentials": {platform: _mask_credentials(body) for platform, body in creds.items()},
        }

    @router.post("/api/channels/credentials/{platform}")
    async def set_credentials(
        platform: str,
        request: Request,
    ) -> dict[str, Any]:
        _require_admin(request)  # Mutation: sets sensitive IM API credentials
        try:
            body = await request.json()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"body: {e}") from e
        if not isinstance(body, dict):
            raise HTTPException(400, "credentials must be a JSON object")

        safe_platform = _normalize_platform_id(platform)
        if safe_platform is None:
            raise HTTPException(
                404,
                f"unknown platform: {platform!r}",
            )

        try:
            clean_body = _sanitize_credentials_body(body)
            channel = _construct_channel(safe_platform, clean_body)
        except _UnsupportedPlatformError as e:
            raise HTTPException(
                400,
                f"platform {safe_platform!r} not yet supported for "
                f"interactive credential setup: {e}",
            ) from e
        except (ValueError, TypeError, KeyError) as e:
            raise HTTPException(
                400,
                f"invalid credentials: {e}",
            ) from e
        safe_channel_id = _normalize_channel_id(
            getattr(channel, "channel_id", None),
        )
        if safe_channel_id is None:
            raise HTTPException(400, "invalid channel_id")

        if manager.has(safe_channel_id):
            with contextlib.suppress(AttributeError):
                manager._channels.pop(safe_channel_id, None)  # noqa: SLF001
        manager.register(channel)

        _credentials_on(manager)[safe_platform] = clean_body
        _save_credentials(manager, _creds_file)
        return {
            "platform": safe_platform,
            "channel_id": safe_channel_id,
            "connected": True,
            "ok": True,
        }

    @router.delete("/api/channels/credentials/{platform}")
    def delete_credentials(
        platform: str,
        request: Request,
    ) -> dict[str, Any]:
        _require_admin(request)  # Mutation: deletes IM credentials, disconnects channels
        safe_platform = _normalize_platform_id(platform)
        if safe_platform is None:
            raise HTTPException(
                404,
                f"unknown platform: {platform!r}",
            )
        creds = _credentials_on(manager)
        dropped = creds.pop(safe_platform, None)
        try:
            for cid in list(manager.channel_ids()):
                cls_name = type(manager.get(cid)).__name__
                if _guess_platform(cid, cls_name) == safe_platform:
                    manager._channels.pop(cid, None)  # noqa: SLF001
        except (AttributeError, TypeError):
            pass
        _save_credentials(manager, _creds_file)
        return {
            "platform": safe_platform,
            "dropped": dropped is not None,
            "ok": True,
        }

    #
    #

    @router.post("/api/channels/wechat/qr/start")
    def wechat_qr_start(request: Request) -> dict[str, Any]:
        _require_admin(request)  # Mutation: starts WeChat OAuth pairing flow
        try:
            from runtime.adapters.channels.weixin_bot import (
                WeixinBotChannel,
            )
        except ImportError as e:
            raise HTTPException(500, f"wechat adapter unavailable: {e}") from e
        try:
            tmp = WeixinBotChannel()
            out = tmp.request_qr_code()
        except (ConnectionError, TimeoutError, OSError) as e:
            raise HTTPException(
                502,
                f"iLink get_bot_qrcode failed: {e}",
            ) from e
        qrcode = out["qrcode"]
        img_content = out["qrcode_img_content"]
        if img_content.startswith("data:"):
            pass
        elif not img_content.startswith("http"):
            img_content = f"data:image/png;base64,{img_content}"
        _WECHAT_QR_SESSIONS[qrcode] = tmp
        return {
            "qrcode": qrcode,
            "qrcode_img_content": img_content,
        }

    @router.post("/api/channels/wechat/qr/poll")
    async def wechat_qr_poll(request: Request) -> dict[str, Any]:
        _require_admin(request)  # Mutation-adjacent: polls + completes the pairing
        try:
            body = await request.json()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"body: {e}") from e
        qrcode = (body or {}).get("qrcode")
        if not isinstance(qrcode, str) or not qrcode:
            raise HTTPException(400, "qrcode required")
        tmp = _WECHAT_QR_SESSIONS.get(qrcode)
        if tmp is None:
            raise HTTPException(404, "unknown or expired qrcode session")

        try:
            resp = tmp.poll_qr_status(qrcode)
        except (ConnectionError, TimeoutError, OSError) as e:
            raise HTTPException(
                502,
                f"iLink poll_qr_status failed: {e}",
            ) from e

        status = resp.get("status", "pending")
        confirmed = status == "confirmed"

        if confirmed:
            if not manager.has(tmp.channel_id):
                try:
                    manager.register(tmp)
                except (ConnectionError, TimeoutError, OSError) as e:
                    _WECHAT_QR_SESSIONS.pop(qrcode, None)
                    raise HTTPException(
                        500,
                        f"register wechat channel failed: {e}",
                    ) from e
            tok = resp.get("bot_token")
            if isinstance(tok, str) and tok:
                _credentials_on(manager)["wechat"] = {
                    "bot_token": tok,
                    "baseurl": str(resp.get("baseurl", "")),
                }
                _save_credentials(manager, _creds_file)
            _WECHAT_QR_SESSIONS.pop(qrcode, None)

        return {
            "status": status,
            "confirmed": confirmed,
        }

    @router.get("/api/channels/{channel_id}/pairings")
    def list_pairings(
        channel_id: str,
        request: Request,
    ) -> dict[str, Any]:
        _auth(request)  # AUTH-OK: actor-agnostic — pairing lists are server-global
        safe_channel_id = _normalize_channel_id(channel_id)
        if safe_channel_id is None:
            raise HTTPException(400, "invalid channel_id")
        p = _pairings(manager)
        return {
            "channel_id": safe_channel_id,
            "users": p.users_list(safe_channel_id),
            "groups": p.groups_list(safe_channel_id),
            "pending": list(p.pending.get(safe_channel_id, [])),
            "metrics": p.metrics(safe_channel_id),
        }

    @router.get("/api/channels/detail")
    def channels_detail(request: Request) -> dict[str, Any]:
        _auth(request)  # AUTH-OK: actor-agnostic — channel details are server-global
        assigns = _assignments()
        p = _pairings(manager)
        seen: set[str] = set()
        channels: list[dict[str, Any]] = []

        for cid in manager.channel_ids():
            platform = _guess_platform(cid, type(manager.get(cid)).__name__)
            m = p.metrics(cid)
            channels.append(
                {
                    "name": platform,
                    "enabled": True,
                    "running": True,
                    "linked": True,
                    "assigned_agent": assigns.get(cid),
                    "stats": {
                        "paired_users": m["pairings_count"],
                        "paired_groups": m["group_count"],
                        "pending_requests": m["pending_count"],
                    },
                }
            )
            seen.add(platform)

        for platform in _PLATFORM_META:
            if platform in seen:
                continue
            channels.append(
                {
                    "name": platform,
                    "enabled": False,
                    "running": False,
                    "linked": False,
                    "assigned_agent": assigns.get(platform),
                    "stats": {
                        "paired_users": 0,
                        "paired_groups": 0,
                        "pending_requests": 0,
                    },
                }
            )
        return {"channels": channels}

    @router.post("/api/channels/pairing/{pairing_id}/approve")
    def approve_pairing(
        pairing_id: str,
        request: Request,
    ) -> dict[str, Any]:
        _require_admin(request)  # Mutation: authorizes external user to access the bot
        safe_pairing_id = _normalize_pairing_ref(pairing_id)
        if safe_pairing_id is None:
            raise HTTPException(400, "invalid pairing_id")
        for cid, pending_list in _pairings(manager).pending.items():
            for entry in pending_list:
                eid = entry.get("sender_id", "") or str(id(entry))
                if eid == safe_pairing_id:
                    pending_list.remove(entry)
                    _pairings(manager).record(
                        cid,
                        sender_id=entry.get("sender_id"),
                        thread_id=entry.get("thread_id"),
                    )
                    _save_state(manager, _state_file)
                    return {"ok": True, "pairing_id": safe_pairing_id}
        raise HTTPException(404, f"pairing {safe_pairing_id!r} not found")

    @router.post("/api/channels/pairing/{pairing_id}/reject")
    def reject_pairing(
        pairing_id: str,
        request: Request,
    ) -> dict[str, Any]:
        _require_admin(request)  # Mutation: denies external user access
        safe_pairing_id = _normalize_pairing_ref(pairing_id)
        if safe_pairing_id is None:
            raise HTTPException(400, "invalid pairing_id")
        for _cid, pending_list in _pairings(manager).pending.items():
            for entry in pending_list:
                eid = entry.get("sender_id", "") or str(id(entry))
                if eid == safe_pairing_id:
                    pending_list.remove(entry)
                    _save_state(manager, _state_file)
                    return {"ok": True, "pairing_id": safe_pairing_id}
        raise HTTPException(404, f"pairing {safe_pairing_id!r} not found")

    @router.post("/api/channels/{channel_id}/inbound")
    async def inbound_webhook(
        channel_id: str,
        request: Request,
    ) -> Any:
        # No _auth() gate here: IM platforms (Discord/Slack/WeChat) don't
        # send bearer tokens. Authenticity is verified by the channel's
        # handle_webhook() via platform-specific signature checks
        # (Discord's X-Signature-Ed25519, Slack's X-Slack-Signature, etc).

        safe_channel_id = _normalize_channel_id(channel_id)
        if safe_channel_id is None:
            raise HTTPException(400, "invalid channel_id")
        if not manager.has(safe_channel_id):
            raise HTTPException(404, f"unknown channel: {channel_id}")
        channel = manager.get(safe_channel_id)

        try:
            body = await request.body()
        except (OSError, ValueError) as e:
            raise HTTPException(400, f"body read failed: {e}") from e

        headers = {k.lower(): v for k, v in request.headers.items()}

        try:
            result = channel.handle_webhook(body=body, headers=headers)
        except NotImplementedError as e:
            raise HTTPException(400, str(e)) from e
        except ValueError as e:
            msg = str(e).lower()
            if any(
                k in msg
                for k in (
                    "signature",
                    "timestamp",
                    "too old",
                    "not yet valid",
                )
            ):
                raise HTTPException(401, str(e)) from e
            raise HTTPException(400, str(e)) from e
        except (ConnectionError, TimeoutError, OSError) as e:
            raise HTTPException(500, f"handle_webhook: {e}") from e

        if isinstance(result, dict):
            return result

        if result is None:
            return {"ok": True, "dispatched": False}

        from runtime.adapters.channels import ChannelRoutingError, InboundMessage

        if not isinstance(result, InboundMessage):
            raise HTTPException(
                500,
                f"handle_webhook returned unexpected type: {type(result).__name__}",
            )

        try:
            out = manager.process_inbound(result)
        except ChannelRoutingError as e:
            raise HTTPException(400, str(e)) from e
        except (ConnectionError, TimeoutError, OSError) as e:
            raise HTTPException(500, f"dispatch: {e}") from e

        try:
            _pairings(manager).record(
                safe_channel_id,
                sender_id=getattr(result, "sender_id", None),
                thread_id=getattr(result, "thread_id", None),
                is_group=_is_group_message(result),
            )
            _save_state(manager, _state_file)
        except (AttributeError, TypeError, OSError):  # noqa: BLE001 — state save best-effort; main op already succeeded
            pass

        return {
            "ok": True,
            "dispatched": True,
            "conversation_id": out.metadata.get("conversation_id"),
            "agent_id": out.metadata.get("agent_id"),
        }

    return router


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

_PLATFORM_META: dict[str, dict[str, str]] = {
    "wechat": {
        "cls_name": "WeChatChannel",
        "display_name": "微信",
        "description": "微信 ClawBot · 扫码对接个人号 / 客服号",
        "help_url": "https://docs.octopus.ai/channels/wechat",
    },
    "dingtalk": {
        "cls_name": "DingTalkChannel",
        "display_name": "钉钉",
        "description": "钉钉机器人",
        "help_url": "https://docs.octopus.ai/channels/dingtalk",
    },
    "feishu": {
        "cls_name": "FeishuChannel",
        "display_name": "飞书",
        "description": "飞书机器人",
        "help_url": "https://docs.octopus.ai/channels/feishu",
    },
    "telegram": {
        "cls_name": "TelegramChannel",
        "display_name": "Telegram",
        "description": "Telegram Bot",
        "help_url": "https://docs.octopus.ai/channels/telegram",
    },
    "slack": {
        "cls_name": "SlackChannel",
        "display_name": "Slack",
        "description": "Slack 应用 / bot",
        "help_url": "https://docs.octopus.ai/channels/slack",
    },
    "discord": {
        "cls_name": "DiscordChannel",
        "display_name": "Discord",
        "description": "Discord Interaction Bot",
        "help_url": "https://docs.octopus.ai/channels/discord",
    },
    "signal": {
        "cls_name": "SignalChannel",
        "display_name": "Signal",
        "description": "Signal Private Messenger",
        "help_url": "https://docs.octopus.ai/channels/signal",
    },
    "whatsapp": {
        "cls_name": "WhatsAppChannel",
        "display_name": "WhatsApp",
        "description": "WhatsApp Business API",
        "help_url": "https://docs.octopus.ai/channels/whatsapp",
    },
    "email": {
        "cls_name": "EmailChannel",
        "display_name": "Email",
        "description": "SMTP / IMAP 邮件通道",
        "help_url": "https://docs.octopus.ai/channels/email",
    },
    "sms": {
        "cls_name": "SmsChannel",
        "display_name": "SMS (Twilio)",
        "description": "Twilio SMS 短信通道",
        "help_url": "https://docs.octopus.ai/channels/sms",
    },
    "mattermost": {
        "cls_name": "MattermostChannel",
        "display_name": "Mattermost",
        "description": "Mattermost 开源协作平台",
        "help_url": "https://docs.octopus.ai/channels/mattermost",
    },
    "matrix": {
        "cls_name": "MatrixChannel",
        "display_name": "Matrix",
        "description": "Matrix / Element 去中心化通信",
        "help_url": "https://docs.octopus.ai/channels/matrix",
    },
    "wecom": {
        "cls_name": "WeComChannel",
        "display_name": "企业微信",
        "description": "WeCom 企业微信应用消息",
        "help_url": "https://docs.octopus.ai/channels/wecom",
    },
    "qqbot": {
        "cls_name": "QQBotChannel",
        "display_name": "QQ 机器人",
        "description": "QQ 官方机器人",
        "help_url": "https://docs.octopus.ai/channels/qqbot",
    },
    "teams": {
        "cls_name": "TeamsChannel",
        "display_name": "Microsoft Teams",
        "description": "Teams Bot Framework",
        "help_url": "https://docs.octopus.ai/channels/teams",
    },
    "line": {
        "cls_name": "LineChannel",
        "display_name": "LINE",
        "description": "LINE Messaging API",
        "help_url": "https://docs.octopus.ai/channels/line",
    },
    "homeassistant": {
        "cls_name": "HomeAssistantChannel",
        "display_name": "Home Assistant",
        "description": "智能家居控制中心",
        "help_url": "https://docs.octopus.ai/channels/homeassistant",
    },
    "bluebubbles": {
        "cls_name": "BlueBubblesChannel",
        "display_name": "BlueBubbles (iMessage)",
        "description": "iMessage 桥接通道",
        "help_url": "https://docs.octopus.ai/channels/bluebubbles",
    },
    "ntfy": {
        "cls_name": "NtfyChannel",
        "display_name": "ntfy",
        "description": "ntfy.sh 推送通知",
        "help_url": "https://docs.octopus.ai/channels/ntfy",
    },
    "webhooks": {
        "cls_name": "WebhooksChannel",
        "display_name": "Webhooks",
        "description": "通用 Webhook 集成",
        "help_url": "https://docs.octopus.ai/channels/webhooks",
    },
    "google_chat": {
        "cls_name": "GoogleChatChannel",
        "display_name": "Google Chat",
        "description": "Google Workspace 聊天机器人",
        "help_url": "https://docs.octopus.ai/channels/google_chat",
    },
    "simplex": {
        "cls_name": "SimpleXChannel",
        "display_name": "SimpleX",
        "description": "SimpleX 隐私聊天",
        "help_url": "https://docs.octopus.ai/channels/simplex",
    },
    "open_webui": {
        "cls_name": "OpenWebUIChannel",
        "display_name": "Open WebUI",
        "description": "Open WebUI 开源聊天界面",
        "help_url": "https://docs.octopus.ai/channels/open_webui",
    },
    "yuanbao": {
        "cls_name": "YuanbaoChannel",
        "display_name": "腾讯元宝",
        "description": "腾讯元宝机器人",
        "help_url": "https://docs.octopus.ai/channels/yuanbao",
    },
}

_FALLBACK_META = {
    "cls_name": "Channel",
    "display_name": "其他",
    "description": "自定义渠道",
    "help_url": "",
}

_FALLBACK_ASSIGNMENTS: dict[str, str] = {}

_WECHAT_QR_SESSIONS: dict[str, Any] = {}


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#
#
#


class _PairingStore:
    # Per-channel queue cap + entry TTL for ``pending``. Prevents an
    # unresponsive channel_id from growing the dict without bound.
    _PENDING_MAX_PER_CHANNEL = 200
    _PENDING_TTL_SECONDS = 24 * 3600

    def __init__(self) -> None:
        self.users: dict[str, set[str]] = {}
        self.groups: dict[str, set[str]] = {}
        self.pending: dict[str, list[dict[str, Any]]] = {}

    def record(
        self,
        channel_id: str,
        *,
        sender_id: str | None = None,
        thread_id: str | None = None,
        is_group: bool = False,
    ) -> None:
        safe_channel_id = _normalize_channel_id(channel_id)
        if safe_channel_id is None:
            return
        safe_thread_id = _normalize_pairing_ref(thread_id)
        safe_sender_id = _normalize_pairing_ref(sender_id)
        if is_group and safe_thread_id:
            bucket = self.groups.setdefault(safe_channel_id, set())
            if len(bucket) < _MAX_PAIRINGS_PER_CHANNEL:
                bucket.add(safe_thread_id)
        if safe_sender_id:
            bucket = self.users.setdefault(safe_channel_id, set())
            if len(bucket) < _MAX_PAIRINGS_PER_CHANNEL:
                bucket.add(safe_sender_id)

    def _gc_pending(self, channel_id: str) -> None:
        """Drop expired entries and cap the queue length."""
        import time as _t

        bucket = self.pending.get(channel_id)
        if not bucket:
            return
        cutoff = _t.time() - self._PENDING_TTL_SECONDS
        bucket[:] = [e for e in bucket if float(e.get("ts", 0.0)) >= cutoff]
        if len(bucket) > self._PENDING_MAX_PER_CHANNEL:
            del bucket[: len(bucket) - self._PENDING_MAX_PER_CHANNEL]
        if not bucket:
            self.pending.pop(channel_id, None)

    def enqueue_pending(
        self,
        channel_id: str,
        msg: Any,
    ) -> None:
        import time as _t

        safe_channel_id = _normalize_channel_id(channel_id)
        if safe_channel_id is None:
            return
        sender_id = _normalize_pairing_ref(getattr(msg, "sender_id", "") or "")
        thread_id = _normalize_pairing_ref(getattr(msg, "thread_id", "") or "")
        entry = {
            "sender_id": sender_id or "",
            "thread_id": thread_id or "",
            "content": (getattr(msg, "content", "") or "")[:500],
            "ts": _t.time(),
        }
        self.pending.setdefault(safe_channel_id, []).append(entry)
        self._gc_pending(safe_channel_id)

    def drain_pending(self, channel_id: str) -> list[dict[str, Any]]:
        self._gc_pending(channel_id)
        out = self.pending.get(channel_id, [])
        self.pending[channel_id] = []
        return out

    def metrics(self, channel_id: str) -> dict[str, int]:
        self._gc_pending(channel_id)
        return {
            "pairings_count": len(self.users.get(channel_id, set())),
            "group_count": len(self.groups.get(channel_id, set())),
            "pending_count": len(self.pending.get(channel_id, [])),
        }

    def users_list(self, channel_id: str) -> list[str]:
        return sorted(self.users.get(channel_id, set()))

    def groups_list(self, channel_id: str) -> list[str]:
        return sorted(self.groups.get(channel_id, set()))


def _pairings(manager: Any) -> _PairingStore:
    store = getattr(manager, "_channel_pairings", None)
    if store is None or not isinstance(store, _PairingStore):
        store = _PairingStore()
        with contextlib.suppress(AttributeError):
            manager._channel_pairings = store
    return store


# ═══════════════════════════════════════════════════════════
# State persistence (assignments + pairings)
# ═══════════════════════════════════════════════════════════
#
#
#   {
#     "version": 1,
#     "assignments": {"slack": "coder", "wechat": "general"},
#     "users":  {"slack": ["U1", "U2"]},
#     "groups": {"slack": ["C_ABC"]}
#   }
#


_STATE_SCHEMA_VERSION = 1
_MAX_STATE_FILE_BYTES = 2 * 1024 * 1024
_MAX_CREDENTIALS_FILE_BYTES = 1024 * 1024
_MAX_ASSIGNMENTS = 512
_MAX_PAIRING_CHANNELS = 256
_MAX_PAIRINGS_PER_CHANNEL = 5_000
_MAX_CREDENTIAL_KEYS = 64
_MAX_CREDENTIAL_TOTAL_BYTES = 256 * 1024
_MAX_CREDENTIAL_VALUE_BYTES = 64 * 1024
_CHANNEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PLATFORM_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _is_oversized_file(path: Path, max_bytes: int) -> bool:
    try:
        return path.stat().st_size > max_bytes
    except OSError:
        return False


def _normalize_channel_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _CHANNEL_ID_RE.fullmatch(text) else None


def _normalize_agent_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _AGENT_ID_RE.fullmatch(text) else None


def _normalize_platform_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not _PLATFORM_RE.fullmatch(text) or text not in _PLATFORM_META:
        return None
    return text


def _normalize_pairing_ref(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 256 or "\x00" in text:
        return None
    return text


def _clean_assignments(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for channel_id, agent_id in raw.items():
        if len(out) >= _MAX_ASSIGNMENTS:
            break
        safe_channel_id = _normalize_channel_id(channel_id)
        safe_agent_id = _normalize_agent_id(agent_id)
        if safe_channel_id and safe_agent_id:
            out[safe_channel_id] = safe_agent_id
    return out


def _clean_pairing_map(raw: Any) -> dict[str, set[str]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, set[str]] = {}
    for channel_id, ids in raw.items():
        if len(out) >= _MAX_PAIRING_CHANNELS:
            break
        safe_channel_id = _normalize_channel_id(channel_id)
        if not safe_channel_id or not isinstance(ids, (list, set, tuple)):
            continue
        clean_ids: set[str] = set()
        for raw_id in ids:
            if len(clean_ids) >= _MAX_PAIRINGS_PER_CHANNEL:
                break
            safe_id = _normalize_pairing_ref(raw_id)
            if safe_id:
                clean_ids.add(safe_id)
        if clean_ids:
            out[safe_channel_id] = clean_ids
    return out


def _sanitize_credentials_body(body: dict[str, Any]) -> dict[str, Any]:
    if len(body) > _MAX_CREDENTIAL_KEYS:
        raise ValueError(f"too many credential fields (max {_MAX_CREDENTIAL_KEYS})")
    out: dict[str, Any] = {}
    total_bytes = 0
    for key, value in body.items():
        if not isinstance(key, str) or not key or len(key) > 96 or _CONTROL_RE.search(key):
            raise ValueError("invalid credential field name")
        if isinstance(value, str):
            value_bytes = len(value.encode("utf-8"))
            if value_bytes > _MAX_CREDENTIAL_VALUE_BYTES or "\x00" in value:
                raise ValueError(f"credential field {key!r} is too large or invalid")
            total_bytes += value_bytes
            if key == "channel_id":
                safe_channel_id = _normalize_channel_id(value)
                if safe_channel_id is None:
                    raise ValueError("invalid channel_id")
                out[key] = safe_channel_id
            else:
                out[key] = value
        elif value is None or isinstance(value, (bool, int, float)):
            total_bytes += len(str(value).encode("utf-8"))
            out[key] = value
        else:
            raise ValueError(f"credential field {key!r} must be scalar")
        total_bytes += len(key.encode("utf-8"))
        if total_bytes > _MAX_CREDENTIAL_TOTAL_BYTES:
            raise ValueError(
                f"credentials payload too large (max {_MAX_CREDENTIAL_TOTAL_BYTES} bytes)",
            )
    return out


def _clean_credentials_map(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for platform, body in raw.items():
        safe_platform = _normalize_platform_id(platform)
        if safe_platform is None or not isinstance(body, dict):
            continue
        try:
            out[safe_platform] = _sanitize_credentials_body(body)
        except ValueError:
            continue
    return out


def _load_state(manager: Any, state_file: Path | None) -> None:
    if state_file is None or not state_file.exists():
        return
    if _is_oversized_file(state_file, _MAX_STATE_FILE_BYTES):
        logger.warning(
            "channel state load skipped: file too large (> %s bytes)",
            _MAX_STATE_FILE_BYTES,
        )
        return
    try:
        raw = state_file.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "channel state load failed (%s): %s · starting empty",
            type(e).__name__,
            e,
        )
        return

    if not isinstance(data, dict):
        return
    if data.get("version") != _STATE_SCHEMA_VERSION:
        logger.info(
            "channel state schema v%s unknown · starting empty",
            data.get("version"),
        )
        return

    try:
        target = _assignments_on(manager)
        target.update(_clean_assignments(data.get("assignments") or {}))
    except (AttributeError, TypeError, ValueError):
        logger.exception("channel state: failed to restore assignments")

    try:
        store = _pairings(manager)
        store.users.update(_clean_pairing_map(data.get("users") or {}))
        store.groups.update(_clean_pairing_map(data.get("groups") or {}))
    except (AttributeError, TypeError, ValueError):
        logger.exception("channel state: failed to restore pairings")


def _save_state(manager: Any, state_file: Path | None) -> None:
    if state_file is None:
        return
    try:
        assigns = _assignments_on(manager)
        store = _pairings(manager)
        payload = {
            "version": _STATE_SCHEMA_VERSION,
            "assignments": _clean_assignments(assigns),
            "users": {k: sorted(v) for k, v in _clean_pairing_map(store.users).items()},
            "groups": {k: sorted(v) for k, v in _clean_pairing_map(store.groups).items()},
        }
        state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_file.with_suffix(state_file.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, state_file)
    except OSError as e:
        logger.warning("channel state save failed: %s", e)


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


class _UnsupportedPlatformError(RuntimeError):
    pass


_CHANNEL_CONSTRUCTORS: dict[str, Callable[[dict[str, Any]], Any]] = {}


def register_channel_constructor(
    platform: str, constructor: Callable[[dict[str, Any]], Any]
) -> None:
    _CHANNEL_CONSTRUCTORS[platform] = constructor


def _credentials_on(manager: Any) -> dict[str, dict[str, Any]]:
    c = getattr(manager, "_channel_credentials", None)
    if c is None:
        c = {}
        with contextlib.suppress(AttributeError):
            manager._channel_credentials = c
    return c


def _mask(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    if len(value) <= 4:
        return "●" * len(value)
    return "●" * (len(value) - 4) + value[-4:]


_SENSITIVE_KEYS = {
    "bot_token",
    "signing_secret",
    "webhook_secret",
    "app_secret",
    "api_key",
    "api_secret",
    "token",
    "secret",
    "password",
    "encoding_aes_key",
    "corp_secret",
    "access_token",
}


def _mask_credentials(body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in body.items():
        if k.lower() in _SENSITIVE_KEYS:
            out[k] = _mask(v)
        else:
            out[k] = v
    return out


def _require(body: dict[str, Any], key: str) -> str:
    v = body.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{key} required (non-empty string)")
    return v.strip()


def _optional(body: dict[str, Any], key: str) -> str | None:
    v = body.get(key)
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _construct_channel(platform: str, body: dict[str, Any]) -> Any:
    constructor = _CHANNEL_CONSTRUCTORS.get(platform)
    if constructor is None:
        raise _UnsupportedPlatformError(platform)
    return constructor(body)


def _make_slack(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels import SlackChannel

    return SlackChannel(
        bot_token=_require(body, "bot_token"),
        signing_secret=_require(body, "signing_secret"),
        channel_id=str(body.get("channel_id", "slack")),
    )


def _make_dingtalk(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.dingtalk import DingTalkChannel

    return DingTalkChannel(
        webhook_url=_require(body, "webhook_url"),
        secret=_optional(body, "secret"),
        channel_id=str(body.get("channel_id", "dingtalk")),
    )


def _make_feishu(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.feishu import FeishuChannel

    return FeishuChannel(
        app_id=_require(body, "app_id"),
        app_secret=_require(body, "app_secret"),
        verification_token=_require(body, "verification_token"),
        channel_id=str(body.get("channel_id", "feishu")),
    )


def _make_telegram(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.telegram import TelegramChannel

    return TelegramChannel(
        bot_token=_require(body, "bot_token"),
        webhook_secret=_optional(body, "webhook_secret") or "",
        channel_id=str(body.get("channel_id", "telegram")),
    )


def _make_discord(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.discord import DiscordChannel

    return DiscordChannel(
        bot_token=_require(body, "bot_token"),
        public_key=_require(body, "public_key"),
        channel_id=str(body.get("channel_id", "discord")),
    )


def _make_wechat(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.weixin_bot import WeixinBotChannel

    return WeixinBotChannel(
        bot_token=_require(body, "bot_token"),
        channel_id=str(body.get("channel_id", "weixin_bot")),
    )


def _make_signal(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.signal import SignalChannel

    return SignalChannel(
        phone_number=_require(body, "phone_number"),
        api_base_url=_optional(body, "api_base_url") or "http://localhost:8080",
        channel_id=str(body.get("channel_id", "signal")),
    )


def _make_whatsapp(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.whatsapp import WhatsAppChannel

    return WhatsAppChannel(
        phone_number_id=_require(body, "phone_number_id"),
        access_token=_require(body, "access_token"),
        verify_token=_require(body, "verify_token"),
        app_secret=_optional(body, "app_secret") or "",
        channel_id=str(body.get("channel_id", "whatsapp")),
    )


def _make_email(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.email import EmailChannel

    return EmailChannel(
        smtp_host=_require(body, "smtp_host"),
        smtp_port=int(body.get("smtp_port", 587)),
        imap_host=_require(body, "imap_host"),
        username=_require(body, "username"),
        password=_require(body, "password"),
        from_address=_require(body, "from_address"),
        channel_id=str(body.get("channel_id", "email")),
    )


def _make_sms(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.sms import SmsChannel

    return SmsChannel(
        account_sid=_require(body, "account_sid"),
        auth_token=_require(body, "auth_token"),
        from_number=_require(body, "from_number"),
        channel_id=str(body.get("channel_id", "sms")),
    )


def _make_mattermost(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.mattermost import MattermostChannel

    return MattermostChannel(
        bot_token=_require(body, "bot_token"),
        server_url=_require(body, "server_url"),
        channel_id=str(body.get("channel_id", "mattermost")),
    )


def _make_matrix(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.matrix import MatrixChannel

    return MatrixChannel(
        homeserver_url=_require(body, "homeserver_url"),
        access_token=_require(body, "access_token"),
        channel_id=str(body.get("channel_id", "matrix")),
    )


def _make_wecom(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.wecom import WeComChannel

    return WeComChannel(
        corp_id=_require(body, "corp_id"),
        agent_id=_require(body, "agent_id"),
        secret=_require(body, "secret"),
        token=_require(body, "token"),
        encoding_aes_key=_require(body, "encoding_aes_key"),
        channel_id=str(body.get("channel_id", "wecom")),
    )


def _make_qqbot(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.qqbot import QQBotChannel

    return QQBotChannel(
        app_id=_require(body, "app_id"),
        app_secret=_require(body, "app_secret"),
        channel_id_param=str(body.get("channel_id", "qqbot")),
    )


def _make_teams(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.teams import TeamsChannel

    return TeamsChannel(
        app_id=_require(body, "app_id"),
        app_password=_require(body, "app_password"),
        channel_id=str(body.get("channel_id", "teams")),
    )


def _make_line(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.line import LineChannel

    return LineChannel(
        channel_access_token=_require(body, "channel_access_token"),
        channel_secret=_require(body, "channel_secret"),
        channel_id=str(body.get("channel_id", "line")),
    )


def _make_homeassistant(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.homeassistant import HomeAssistantChannel

    return HomeAssistantChannel(
        ha_url=_require(body, "ha_url"),
        long_lived_token=_require(body, "long_lived_token"),
        channel_id=str(body.get("channel_id", "homeassistant")),
    )


def _make_bluebubbles(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.bluebubbles import BlueBubblesChannel

    return BlueBubblesChannel(
        server_url=_require(body, "server_url"),
        api_key=_require(body, "api_key"),
        password=_optional(body, "password") or "",
        channel_id=str(body.get("channel_id", "bluebubbles")),
    )


def _make_ntfy(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.ntfy import NtfyChannel

    return NtfyChannel(
        server_url=_optional(body, "server_url") or "https://ntfy.sh",
        topic=_require(body, "topic"),
        channel_id=str(body.get("channel_id", "ntfy")),
    )


def _make_webhooks(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.webhooks import WebhooksChannel

    return WebhooksChannel(
        webhook_secret=_require(body, "webhook_secret"),
        outbound_url=_require(body, "outbound_url"),
        channel_id=str(body.get("channel_id", "webhooks")),
    )


def _make_google_chat(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.google_chat import GoogleChatChannel

    return GoogleChatChannel(
        service_account_key=_require(body, "service_account_key"),
        channel_id=str(body.get("channel_id", "google_chat")),
    )


def _make_simplex(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.simplex import SimpleXChannel

    return SimpleXChannel(
        api_base_url=_optional(body, "api_base_url") or "http://localhost:5225",
        channel_id=str(body.get("channel_id", "simplex")),
    )


def _make_open_webui(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.open_webui import OpenWebUIChannel

    return OpenWebUIChannel(
        base_url=_require(body, "base_url"),
        api_key=_require(body, "api_key"),
        channel_id=str(body.get("channel_id", "open_webui")),
    )


def _make_yuanbao(body: dict[str, Any]) -> Any:
    from runtime.adapters.channels.yuanbao import YuanbaoChannel

    return YuanbaoChannel(
        bot_id=_require(body, "bot_id"),
        bot_token=_require(body, "bot_token"),
        channel_id=str(body.get("channel_id", "yuanbao")),
    )


register_channel_constructor("slack", _make_slack)
register_channel_constructor("dingtalk", _make_dingtalk)
register_channel_constructor("feishu", _make_feishu)
register_channel_constructor("telegram", _make_telegram)
register_channel_constructor("discord", _make_discord)
register_channel_constructor("wechat", _make_wechat)
register_channel_constructor("signal", _make_signal)
register_channel_constructor("whatsapp", _make_whatsapp)
register_channel_constructor("email", _make_email)
register_channel_constructor("sms", _make_sms)
register_channel_constructor("mattermost", _make_mattermost)
register_channel_constructor("matrix", _make_matrix)
register_channel_constructor("wecom", _make_wecom)
register_channel_constructor("qqbot", _make_qqbot)
register_channel_constructor("teams", _make_teams)
register_channel_constructor("line", _make_line)
register_channel_constructor("homeassistant", _make_homeassistant)
register_channel_constructor("bluebubbles", _make_bluebubbles)
register_channel_constructor("ntfy", _make_ntfy)
register_channel_constructor("webhooks", _make_webhooks)
register_channel_constructor("google_chat", _make_google_chat)
register_channel_constructor("simplex", _make_simplex)
register_channel_constructor("open_webui", _make_open_webui)
register_channel_constructor("yuanbao", _make_yuanbao)


def _load_credentials_and_bootstrap(
    manager: Any,
    creds_file: Path | None,
) -> None:
    if creds_file is None or not creds_file.exists():
        return
    if _is_oversized_file(creds_file, _MAX_CREDENTIALS_FILE_BYTES):
        logger.warning(
            "channel credentials load skipped: file too large (> %s bytes)",
            _MAX_CREDENTIALS_FILE_BYTES,
        )
        return
    try:
        raw = creds_file.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "channel credentials load failed (%s): %s",
            type(e).__name__,
            e,
        )
        return
    if not isinstance(data, dict):
        return
    if data.get("_enc") == "aes-gcm":
        decrypted = _try_decrypt_payload(data, creds_file.parent)
        if decrypted is None:
            logger.warning(
                "channel credentials encrypted but decryption failed · "
                "skipping (wrong key / missing cryptography package?)",
            )
            return
        data = decrypted
    target = _credentials_on(manager)
    for platform, body in data.items():
        safe_platform = _normalize_platform_id(platform)
        if safe_platform is None or not isinstance(body, dict):
            continue
        try:
            clean_body = _sanitize_credentials_body(body)
            channel = _construct_channel(safe_platform, clean_body)
        except _UnsupportedPlatformError:
            continue
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(
                "channel credentials for %s invalid · skipping: %s",
                safe_platform,
                e,
            )
            continue
        safe_channel_id = _normalize_channel_id(
            getattr(channel, "channel_id", None),
        )
        if safe_channel_id is None:
            logger.warning(
                "channel credentials for %s invalid · unsafe channel_id",
                safe_platform,
            )
            continue
        target[safe_platform] = clean_body
        if manager.has(safe_channel_id):
            continue  # Implementation note.
        try:
            manager.register(channel)
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning(
                "re-register %s failed: %s",
                safe_platform,
                e,
            )


def _save_credentials(manager: Any, creds_file: Path | None) -> None:
    if creds_file is None:
        return
    try:
        data = _clean_credentials_map(_credentials_on(manager))
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = creds_file.with_suffix(creds_file.suffix + ".tmp")
        encrypted = _try_encrypt_payload(data, creds_file.parent)
        if encrypted is not None:
            tmp.write_text(
                json.dumps(encrypted, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        os.replace(tmp, creds_file)
        with contextlib.suppress(OSError):
            os.chmod(creds_file, 0o600)
    except OSError as e:
        logger.warning("channel credentials save failed: %s", e)


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#
#
#
#   { "_enc": "aes-gcm", "nonce": base64, "ciphertext": base64 }
#


def _aead_key(creds_dir: Path) -> bytes | None:
    import base64

    env_key = os.environ.get("OCTOPUS_CREDENTIAL_KEY")
    if env_key:
        try:
            raw = base64.b64decode(env_key)
            if len(raw) == 32:
                return raw
            logger.warning(
                "OCTOPUS_CREDENTIAL_KEY invalid length %d (need 32 bytes after base64)",
                len(raw),
            )
            return None
        except (ValueError, TypeError):
            logger.warning("OCTOPUS_CREDENTIAL_KEY not valid base64")
            return None

    key_file = creds_dir / ".credential_key"
    try:
        if key_file.exists():
            raw = base64.b64decode(key_file.read_text(encoding="utf-8").strip())
            if len(raw) == 32:
                return raw
            logger.warning(
                ".credential_key length invalid · regenerating",
            )
        import secrets as _secrets

        raw = _secrets.token_bytes(32)
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(
            base64.b64encode(raw).decode("ascii"),
            encoding="utf-8",
        )
        with contextlib.suppress(OSError):
            os.chmod(key_file, 0o600)
        return raw
    except OSError as e:
        logger.warning("could not read/create .credential_key: %s", e)
        return None


def _try_encrypt_payload(
    data: dict[str, Any],
    creds_dir: Path,
) -> dict[str, Any] | None:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return None
    key = _aead_key(creds_dir)
    if key is None:
        return None
    try:
        import base64
        import secrets as _secrets

        nonce = _secrets.token_bytes(12)  # Implementation note.
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        ct = AESGCM(key).encrypt(nonce, plaintext, None)
        return {
            "_enc": "aes-gcm",
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ct).decode("ascii"),
        }
    except (ValueError, TypeError, OSError) as e:
        logger.warning("credential encryption failed: %s", e)
        return None


def _try_decrypt_payload(
    envelope: dict[str, Any],
    creds_dir: Path,
) -> dict[str, Any] | None:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return None
    key = _aead_key(creds_dir)
    if key is None:
        return None
    try:
        import base64

        nonce = base64.b64decode(envelope["nonce"])
        ct = base64.b64decode(envelope["ciphertext"])
        pt = AESGCM(key).decrypt(nonce, ct, None)
        obj = json.loads(pt.decode("utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception as e:  # noqa: BLE001 — cryptography.InvalidTag, KeyError, JSON errors all collapse to "decrypt failed"
        logger.warning("credential decryption failed: %s", e)
        return None


def _assignments_on(manager: Any) -> dict[str, str]:
    a = getattr(manager, "_channel_assignments", None)
    if a is None:
        a = {}
        try:
            manager._channel_assignments = a
        except (AttributeError, TypeError):
            _FALLBACK_ASSIGNMENTS.clear()
            return _FALLBACK_ASSIGNMENTS
    return a


def _is_group_message(msg: Any) -> bool:
    meta = getattr(msg, "metadata", None) or {}
    if meta.get("is_group") is True:
        return True
    if meta.get("channel_type") in ("group", "channel", "supergroup"):
        return True
    thread_id = getattr(msg, "thread_id", "") or ""
    if thread_id.startswith(("C", "G")) and len(thread_id) > 3:  # noqa: SIM103 — explicit per-platform branches read better
        return True  # Slack C.../G...
    if thread_id.startswith("-100"):
        return True  # Telegram supergroup
    return thread_id.startswith("gid:")  # Google-style group id


def _guess_platform(channel_id: str, cls_name: str) -> str:
    hay = f"{channel_id} {cls_name}".lower()
    if "weixin" in hay:
        return "wechat"
    for platform in _PLATFORM_META:
        if platform in hay:
            return platform
    return "other"


def _zero_metrics() -> dict[str, int]:
    return {
        "pairings_count": 0,
        "group_count": 0,
        "pending_count": 0,
    }

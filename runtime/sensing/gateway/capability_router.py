"""统一「插件」市场路由 —— 所有外部能力(WorkBuddy MCP 服务 + Codex 插件)统一叫插件。

给前端一套统一「插件市场」:

  GET    /api/capabilities                   统一列表(连接器 + 插件)
  GET    /api/capabilities/{id}              单个能力详情
  POST   /api/capabilities/{id}/install      安装(技能→skills, 连接器 MCP 登记)
  DELETE /api/capabilities/{id}/install      卸载
  POST   /api/capabilities/{id}/enable       启用
  POST   /api/capabilities/{id}/disable      禁用
  GET    /api/capabilities/{id}/status       认证/连接状态
  POST   /api/capabilities/{id}/connect      认证编排(连接器)
  POST   /api/capabilities/{id}/disconnect   断开
  GET    /api/capabilities/{id}/headers      认证注入头

统一模型: runtime/platform/capabilities/capability_registry.py
"""

from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, Depends, HTTPException, Query, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    Depends = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Query = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]

from runtime.platform.connectors import oauth_support
from runtime.sensing._fastapi_guard import require_fastapi


def create_capability_router(
    *,
    registry: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    require_fastapi(__name__)

    if registry is None:
        from runtime.platform.capabilities.capability_registry import (
            CapabilityRegistry,
        )

        registry = CapabilityRegistry()

    def _auth_dep(request: Request) -> None:
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    def _operator_dep(request: Request) -> None:
        from runtime.safety.auth.principal import require_roles

        require_roles(
            request,
            identity_store,
            require_auth,
            ("admin", "operator"),
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    router = APIRouter(tags=["capabilities"], dependencies=[Depends(_auth_dep)])

    def _get(cid: str) -> dict[str, Any]:
        item = registry.get(cid)
        if item is None:
            raise HTTPException(404, f"capability not found: {cid}")
        return registry._public(item)

    # 需要手动填 token 的判定:既不能跳网页 OAuth,也没有 CLI 设备流。
    def _is_manual_token_only(item: dict[str, Any]) -> bool:
        if item.get("auth_mode") not in ("token", "oneid-token", "mcp", "oauth"):
            return False
        if item.get("oauth_supported") is True:
            return False
        if item.get("oauth_provider"):
            return False
        return not item.get("has_cli_auth")

    @router.get("/api/capabilities")
    def list_capabilities(
        search: str | None = None,
        source: str | None = Query(default=None, alias="source"),
        ctype: str | None = Query(default=None, alias="type"),
        limit: int = Query(default=500, ge=1, le=1000),
        include_manual: bool = Query(
            default=False,
            alias="include_manual",
            description="默认隐藏只能手动填 token 的插件;传 true 全部返回。",
        ),
    ) -> dict[str, Any]:
        items = registry.list()
        if source:
            items = [i for i in items if i.get("source") == source]
        if ctype:
            items = [i for i in items if i.get("type") == ctype]
        if search:
            q = search.lower()
            items = [
                i
                for i in items
                if q in str(i.get("name", "")).lower()
                or q in str(i.get("name_zh", "")).lower()
                or q in str(i.get("description", "")).lower()
                or q in str(i.get("description_zh", "")).lower()
                or q in str(i.get("id", "")).lower()
            ]
        # 网页 OAuth 授权支持探测:后台并发 + 磁盘缓存(不阻塞列表返回)
        urls: list[str] = []
        for i in items:
            urls.extend(
                str(s.get("url", ""))
                for s in i.get("mcp_servers", [])
                if isinstance(s, dict) and s.get("url")
            )
        oauth_support.prewarm(urls)
        items = [registry._public(i) for i in items]
        items = [oauth_support.annotate(i) for i in items]
        for i in items:
            i["manual_token_only"] = _is_manual_token_only(i)
        if not include_manual:
            # 移除「只能手动填 token」且未安装的插件(已安装的保留以便管理/卸载)
            items = [i for i in items if not i["manual_token_only"] or i.get("installed")]
        return {"capabilities": items[:limit], "total": len(items)}

    @router.get("/api/capabilities/{cid}")
    def capability_detail(cid: str) -> dict[str, Any]:
        return _get(cid)

    @router.post(
        "/api/capabilities/{cid}/install",
        dependencies=[Depends(_operator_dep)],
    )
    def capability_install(cid: str) -> dict[str, Any]:
        _get(cid)
        return registry.install(cid)

    @router.delete(
        "/api/capabilities/{cid}/install",
        dependencies=[Depends(_operator_dep)],
    )
    def capability_uninstall(cid: str) -> dict[str, Any]:
        if not registry.uninstall(cid):
            raise HTTPException(404, f"capability not installed: {cid}")
        return {"installed": False, "capability_id": cid}

    @router.post(
        "/api/capabilities/{cid}/enable",
        dependencies=[Depends(_operator_dep)],
    )
    def capability_enable(cid: str) -> dict[str, Any]:
        if not registry.set_enabled(cid, True):
            raise HTTPException(404, f"capability not installed: {cid}")
        return {"enabled": True, "capability_id": cid}

    @router.post(
        "/api/capabilities/{cid}/disable",
        dependencies=[Depends(_operator_dep)],
    )
    def capability_disable(cid: str) -> dict[str, Any]:
        if not registry.set_enabled(cid, False):
            raise HTTPException(404, f"capability not installed: {cid}")
        return {"enabled": False, "capability_id": cid}

    @router.get("/api/capabilities/{cid}/status")
    def capability_status(cid: str) -> dict[str, Any]:
        _get(cid)
        return registry.status(cid)

    @router.post(
        "/api/capabilities/{cid}/connect",
        dependencies=[Depends(_operator_dep)],
    )
    async def capability_connect(cid: str, request: Request) -> dict[str, Any]:
        _get(cid)
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — 无 body / 非 JSON 按空处理
            body = {}
        return registry.connect(
            cid,
            tokens=body.get("tokens") or None,
            run_cli=bool(body.get("run_cli")),
        )

    @router.post(
        "/api/capabilities/{cid}/disconnect",
        dependencies=[Depends(_operator_dep)],
    )
    def capability_disconnect(cid: str) -> dict[str, Any]:
        _get(cid)
        return registry.disconnect(cid)

    @router.get(
        "/api/capabilities/{cid}/headers",
        dependencies=[Depends(_operator_dep)],
    )
    def capability_headers(cid: str) -> dict[str, Any]:
        _get(cid)
        resolved = registry.resolve_headers(cid)
        raw_headers = resolved.get("headers") if isinstance(resolved, dict) else None
        headers = raw_headers if isinstance(raw_headers, dict) else {}
        return {
            "configured": bool(headers),
            "header_names": sorted(str(name) for name in headers),
        }

    return router

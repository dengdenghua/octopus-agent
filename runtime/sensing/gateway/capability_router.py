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

    router = APIRouter(tags=["capabilities"], dependencies=[Depends(_auth_dep)])

    def _get(cid: str) -> dict[str, Any]:
        item = registry.get(cid)
        if item is None:
            raise HTTPException(404, f"capability not found: {cid}")
        return registry._public(item)

    @router.get("/api/capabilities")
    def list_capabilities(
        search: str | None = None,
        source: str | None = Query(default=None, alias="source"),
        ctype: str | None = Query(default=None, alias="type"),
        limit: int = Query(default=500, ge=1, le=1000),
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
        items = [registry._public(i) for i in items]
        return {"capabilities": items[:limit], "total": len(items)}

    @router.get("/api/capabilities/{cid}")
    def capability_detail(cid: str) -> dict[str, Any]:
        return _get(cid)

    @router.post("/api/capabilities/{cid}/install")
    def capability_install(cid: str) -> dict[str, Any]:
        _get(cid)
        return registry.install(cid)

    @router.delete("/api/capabilities/{cid}/install")
    def capability_uninstall(cid: str) -> dict[str, Any]:
        if not registry.uninstall(cid):
            raise HTTPException(404, f"capability not installed: {cid}")
        return {"installed": False, "capability_id": cid}

    @router.post("/api/capabilities/{cid}/enable")
    def capability_enable(cid: str) -> dict[str, Any]:
        if not registry.set_enabled(cid, True):
            raise HTTPException(404, f"capability not installed: {cid}")
        return {"enabled": True, "capability_id": cid}

    @router.post("/api/capabilities/{cid}/disable")
    def capability_disable(cid: str) -> dict[str, Any]:
        if not registry.set_enabled(cid, False):
            raise HTTPException(404, f"capability not installed: {cid}")
        return {"enabled": False, "capability_id": cid}

    @router.get("/api/capabilities/{cid}/status")
    def capability_status(cid: str) -> dict[str, Any]:
        _get(cid)
        return registry.status(cid)

    @router.post("/api/capabilities/{cid}/connect")
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

    @router.post("/api/capabilities/{cid}/disconnect")
    def capability_disconnect(cid: str) -> dict[str, Any]:
        _get(cid)
        return registry.disconnect(cid)

    @router.get("/api/capabilities/{cid}/headers")
    def capability_headers(cid: str) -> dict[str, Any]:
        _get(cid)
        return registry.resolve_headers(cid)

    return router

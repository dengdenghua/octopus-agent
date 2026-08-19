"""连接器网关路由 — 浏览/安装/认证编排/启停。

对齐 WorkBuddy 连接器商城与 Codex connector_* 体系,给前端一套「连接器市场」:

  GET    /api/connectors                      连接器列表(含安装/启用状态)
  GET    /api/connectors/{id}                 单个连接器详情
  POST   /api/connectors/{id}/install         安装(技能→skills, MCP 登记,默认禁用)
  DELETE /api/connectors/{id}/install         卸载
  POST   /api/connectors/{id}/enable          启用 MCP(需已连接)
  POST   /api/connectors/{id}/disable         禁用
  GET    /api/connectors/{id}/status          认证状态
  POST   /api/connectors/{id}/connect         认证编排(带 tokens / 返回 CLI 命令)
  POST   /api/connectors/{id}/disconnect      断开并清除凭据
  GET    /api/connectors/{id}/headers         解析出的 auth 注入头(供 MCP 代理用)

后端实现: runtime/platform/connectors/{credential_store,connector_registry,auth_orchestrator}
数据源:  extensions/workbuddy-connectors/(WorkBuddy 108 连接器 fork)
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


def create_connector_router(
    *,
    registry: Any = None,
    orchestrator: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    auth_injection_rules: list[dict[str, Any]] | None = None,
) -> Any:
    require_fastapi(__name__)

    if registry is None:
        from runtime.platform.connectors.connector_registry import ConnectorRegistry

        registry = ConnectorRegistry()
    if orchestrator is None:
        from runtime.platform.connectors.auth_orchestrator import AuthOrchestrator

        orchestrator = AuthOrchestrator(auth_injection_rules=auth_injection_rules)

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

    router = APIRouter(tags=["connectors"], dependencies=[Depends(_auth_dep)])

    def _get_connector(cid: str) -> Any:
        conn = registry.get(cid)
        if conn is None:
            raise HTTPException(404, f"connector not found: {cid}")
        return conn

    @router.get("/api/connectors")
    def list_connectors(
        search: str | None = None,
        ctype: str | None = Query(default=None, alias="type"),
        limit: int = Query(default=500, ge=1, le=1000),
    ) -> dict[str, Any]:
        conns = registry.list()
        if ctype:
            conns = [c for c in conns if c["type"] == ctype]
        if search:
            q = search.lower()
            conns = [
                c
                for c in conns
                if q in c["name"].lower()
                or q in c["name_zh"].lower()
                or q in c["description_zh"].lower()
                or q in c["id"].lower()
            ]
        return {"connectors": conns[:limit], "total": len(conns)}

    @router.get("/api/connectors/{connector_id}")
    def connector_detail(connector_id: str) -> dict[str, Any]:
        conn = _get_connector(connector_id)
        state = registry._state().get(connector_id) or {}
        return {
            **conn.to_dict(installed=bool(state.get("installed")), enabled=bool(state.get("enabled"))),
            "mcp_config": conn.mcp_servers,
            "cli": conn.cli,
            "skills_dir": str(conn.skills_dir) if conn.skills_dir else None,
            "examples_zh": conn.examples_zh,
        }

    @router.post("/api/connectors/{connector_id}/install")
    def connector_install(connector_id: str) -> dict[str, Any]:
        _get_connector(connector_id)
        return registry.install(connector_id)

    @router.delete("/api/connectors/{connector_id}/install")
    def connector_uninstall(connector_id: str) -> dict[str, Any]:
        if not registry.uninstall(connector_id):
            raise HTTPException(404, f"connector not installed: {connector_id}")
        return {"installed": False, "connector_id": connector_id}

    @router.post("/api/connectors/{connector_id}/enable")
    def connector_enable(connector_id: str) -> dict[str, Any]:
        if not registry.set_enabled(connector_id, True):
            raise HTTPException(404, f"connector not installed: {connector_id}")
        return {"enabled": True, "connector_id": connector_id}

    @router.post("/api/connectors/{connector_id}/disable")
    def connector_disable(connector_id: str) -> dict[str, Any]:
        if not registry.set_enabled(connector_id, False):
            raise HTTPException(404, f"connector not installed: {connector_id}")
        return {"enabled": False, "connector_id": connector_id}

    @router.get("/api/connectors/{connector_id}/status")
    def connector_status(connector_id: str) -> dict[str, Any]:
        conn = _get_connector(connector_id)
        return orchestrator.status(conn)

    @router.post("/api/connectors/{connector_id}/connect")
    async def connector_connect(connector_id: str, request: Request) -> dict[str, Any]:
        conn = _get_connector(connector_id)
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — 无 body / 非 JSON 一律按空处理
            body = {}
        tokens = body.get("tokens") or None
        run_cli = bool(body.get("run_cli"))
        return orchestrator.connect(conn, tokens=tokens, run_cli=run_cli)

    @router.post("/api/connectors/{connector_id}/disconnect")
    def connector_disconnect(connector_id: str) -> dict[str, Any]:
        conn = _get_connector(connector_id)
        return orchestrator.disconnect(conn)

    @router.get("/api/connectors/{connector_id}/headers")
    def connector_headers(connector_id: str) -> dict[str, Any]:
        conn = _get_connector(connector_id)
        return {"headers": orchestrator.resolve_headers(conn)}

    return router

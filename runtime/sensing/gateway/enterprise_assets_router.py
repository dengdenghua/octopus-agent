"""Agent 消费企业版角色资产库(数字分身归并 C · 消费侧,只读)。

企业版(octopus-enterprise)托管角色/任务模板(其 ``/api/v1/agent-assets``,见
octopus-enterprise/backend/app/agent_assets)。本 router 让 agent 的市场前端能
列举企业版的角色——「消费而非 fork」:配 ``OCTOPUS_ENTERPRISE_URL`` 即接通,
不配则 ``available=false``(前端隐藏该来源,零打扰)。

只读(列举 / 详情)。把企业版角色「安装」到本地(scaffold + load+register)是
下一步,需复用 agent_world_router 的安装路径,单独做。
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter


def _enterprise_base() -> str:
    return (os.environ.get("OCTOPUS_ENTERPRISE_URL") or "").rstrip("/")


def _enterprise_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("OCTOPUS_ENTERPRISE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    tenant = os.environ.get("OCTOPUS_ENTERPRISE_TENANT")
    if tenant:
        headers["X-Tenant-ID"] = tenant
    return headers


def _enterprise_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET 企业版。未配 URL → available=False;网络/HTTP 错 → available=True+error。"""
    base = _enterprise_base()
    if not base:
        return {"available": False, "error": "OCTOPUS_ENTERPRISE_URL not configured"}
    import httpx

    try:
        resp = httpx.get(
            f"{base}{path}",
            headers=_enterprise_headers(),
            params=params or {},
            timeout=15.0,
        )
        resp.raise_for_status()
        return {"available": True, "data": resp.json()}
    except httpx.HTTPStatusError as exc:
        return {"available": True, "error": f"enterprise http {exc.response.status_code}"}
    except Exception as exc:  # noqa: BLE001 — 网络/解析错误统一回错,不抛
        return {"available": True, "error": str(exc)}


def _unwrap(body: Any, key: str) -> Any:
    """企业版回 {success, data, total};也兼容直接返回数据。取 data。"""
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body if body is not None else ([] if key == "items" else None)


def create_enterprise_assets_router() -> APIRouter:
    router = APIRouter(tags=["agent-market-enterprise"])

    @router.get("/api/agent-market/enterprise")
    def list_enterprise_assets(
        category: str | None = None, search: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if category:
            params["category"] = category
        if search:
            params["search"] = search
        res = _enterprise_get("/api/v1/agent-assets", params)
        if not res.get("available"):
            return {"available": False, "items": [], "error": res.get("error")}
        items = _unwrap(res.get("data"), "items")
        return {"available": True, "items": items or [], "error": res.get("error")}

    @router.get("/api/agent-market/enterprise/{asset_id}")
    def get_enterprise_asset(asset_id: str) -> dict[str, Any]:
        res = _enterprise_get(f"/api/v1/agent-assets/{asset_id}")
        if not res.get("available"):
            return {"available": False, "asset": None, "error": res.get("error")}
        return {
            "available": True,
            "asset": _unwrap(res.get("data"), "asset"),
            "error": res.get("error"),
        }

    return router


__all__ = ["create_enterprise_assets_router", "_enterprise_base"]

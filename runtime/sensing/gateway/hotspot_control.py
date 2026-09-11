"""Local Echo control plane for the separate invitation-authenticated listener."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request

from runtime.sensing.gateway.codex_hotspot import ROOT, owner_token

BASE = "http://127.0.0.1:8322"
_lock = asyncio.Lock()
_process = None


def require_local_owner(request: Request):
    if not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "热点管理只允许在提供方本机操作")
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        # Echo development UI can run on a different loopback port.
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise HTTPException(403, "热点管理需要本机页面")


async def running():
    try:
        async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
            response = await client.get(BASE + "/health")
            return response.json().get("service") == "echo-codex-hotspot"
    except (httpx.HTTPError, ValueError):
        return False


async def ensure_running():
    global _process
    async with _lock:
        if await running():
            return
        owner_token(ROOT)
        workspace = Path(__file__).resolve().parents[3]
        with (ROOT / "service.log").open("ab") as log:
            _process = subprocess.Popen(
                [sys.executable, "-m", "runtime.sensing.gateway.codex_hotspot"],
                cwd=workspace,
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
        for _ in range(40):
            if await running():
                return
            if _process.poll() is not None:
                break
            await asyncio.sleep(0.25)
        raise HTTPException(503, "热点服务启动失败，请检查 8322 端口和本机运行环境")


async def control(method: str, path: str, body=None):
    try:
        async with httpx.AsyncClient(timeout=45, trust_env=False) as client:
            response = await client.request(
                method,
                BASE + "/admin/" + path,
                json=body,
                headers={"Authorization": "Bearer " + owner_token(ROOT)},
            )
        result = response.json()
        if response.status_code >= 400:
            raise HTTPException(response.status_code, result.get("detail", "热点操作失败"))
        return result
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "热点服务不可用") from None


def mount_control(router):
    @router.post("/hotspot/discover")
    async def discover(request: Request, body: dict):
        require_local_owner(request)
        from runtime.sensing.gateway.hotspot_discovery import discover_hotspot

        return await discover_hotspot(body)

    @router.post("/hotspot/local-role")
    async def local_role(request: Request, body: dict | None = None):
        require_local_owner(request)
        return await register_local_role((body or {}).get("task_engine", "codex"))

    @router.get("/hotspot/status")
    async def status(request: Request):
        require_local_owner(request)
        if not await running():
            return {"running": False, "enabled": False, "members": [], "usage": []}
        return {"running": True, **await control("GET", "status")}

    @router.post("/hotspot/enabled")
    async def enable(request: Request, body: dict):
        require_local_owner(request)
        if type(body.get("enabled")) is not bool:
            raise HTTPException(400, "enabled 必须是布尔值")
        if body["enabled"]:
            await ensure_running()
        elif not await running():
            return {"running": False, "enabled": False, "members": []}
        return {"running": True, **await control("POST", "enabled", body)}

    @router.post("/hotspot/members")
    async def invite(request: Request, body: dict):
        require_local_owner(request)
        return await control("POST", "members", body)

    @router.delete("/hotspot/members/{member}")
    async def revoke(request: Request, member: str):
        require_local_owner(request)
        if not member.isalnum():
            raise HTTPException(400, "无效邀请")
        return await control("DELETE", "members/" + member)


async def register_local_role(engine="codex"):
    if engine not in {"codex", "opencode"}:
        raise HTTPException(400, "不支持的任务引擎")
    label = "OpenCode" if engine == "opencode" else "Codex"
    import uuid
    from datetime import UTC, datetime

    from runtime.sensing.gateway import a2a_router
    from runtime.sensing.gateway.remote_credentials import read_token, save_token

    # Refresh an existing valid local invitation rather than create duplicates.
    with a2a_router._lock:
        existing = next(
            (
                entry
                for entry in a2a_router._load_registry()["agents"]
                if entry.get("hotspot_local_role")
                and entry.get("hotspot_task_engine", "codex") == engine
            ),
            None,
        )
    if existing:
        try:
            await a2a_router._resolve_agent_card(existing["base_url"], read_token(existing))
            return {"agent_id": existing["agent_id"], "name": label}
        except Exception:
            pass
    invitation = await control(
        "POST",
        "members",
        {
            "label": f"本机 {label} 远程角色",
            "task_engine": engine,
            "hours": 168,
            "max_requests": 1000,
        },
    )
    card = await a2a_router._resolve_agent_card(invitation["task_url"], invitation["token"])
    ref = save_token(invitation["token"])
    now = datetime.now(UTC).isoformat()
    entry = {
        **card,
        "agent_id": existing["agent_id"] if existing else "a2a_" + uuid.uuid4().hex[:12],
        "base_url": invitation["task_url"],
        "credential_ref": ref,
        "hotspot_local_role": True,
        "hotspot_task_engine": engine,
        "registered_at": now,
        "updated_at": now,
        "last_health_check": now,
        "status": "active",
    }
    with a2a_router._lock:
        registry = a2a_router._load_registry()
        registry["agents"] = [
            r for r in registry["agents"] if r.get("agent_id") != entry["agent_id"]
        ]
        registry["agents"].append(entry)
        a2a_router._save_registry(registry["agents"])
    return {"agent_id": entry["agent_id"], "name": label}

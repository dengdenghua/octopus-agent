"""Local Echo settings bridge to the independent team gateway."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import httpx
from fastapi import Depends, HTTPException, Request

from .codex_hotspot import owner_token
from .hotspot_control import require_local_owner
from .team_gateway import ROOT

BASE = "http://127.0.0.1:8333"
_lock = asyncio.Lock()


async def control(method, path, body=None):
    async with httpx.AsyncClient(timeout=55, trust_env=False) as client:
        response = await client.request(
            method,
            BASE + "/admin/" + path,
            json=body,
            headers={"Authorization": "Bearer " + owner_token(ROOT)},
        )
    result = response.json()
    if response.status_code >= 400:
        raise HTTPException(response.status_code, result.get("detail", "网关操作失败"))
    return result


async def ensure_running():
    async with _lock:
        try:
            await control("GET", "status")
            return
        except httpx.ConnectError:
            pass
        ROOT.mkdir(parents=True, exist_ok=True)
        with (ROOT / "service.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "runtime.sensing.gateway.team_gateway"],
                cwd=Path(__file__).resolve().parents[3],
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
        for _ in range(40):
            try:
                await control("GET", "status")
                return
            except httpx.ConnectError:
                if process.poll() is not None:
                    break
                await asyncio.sleep(0.25)
        raise HTTPException(503, "团队网关启动失败，请检查 8333 端口")


def mount_team_control(router, require_admin, connections):
    @router.post("/api/team-gateway/join", dependencies=[Depends(require_admin)])
    async def join(request: Request, body: dict):
        require_local_owner(request)
        connection_id = connections.start(str(body.get("base_url") or ""), body.get("code", ""))
        return await connections.sync(connection_id)

    @router.get("/api/team-gateway/connections", dependencies=[Depends(require_admin)])
    def list_connections(request: Request):
        require_local_owner(request)
        return {"connections": connections.rows()}

    @router.post(
        "/api/team-gateway/connections/{connection_id}/sync", dependencies=[Depends(require_admin)]
    )
    async def sync(request: Request, connection_id: str):
        require_local_owner(request)
        return await connections.sync(connection_id)

    @router.delete(
        "/api/team-gateway/connections/{connection_id}", dependencies=[Depends(require_admin)]
    )
    async def disconnect(request: Request, connection_id: str):
        require_local_owner(request)
        return await connections.disconnect(connection_id)

    @router.api_route(
        "/api/team-gateway/admin/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
        dependencies=[Depends(require_admin)],
    )
    async def admin(request: Request, path: str):
        require_local_owner(request)
        import re

        if not re.fullmatch(
            r"(status|enabled|invitations|models/[a-zA-Z0-9_-]{1,80}(/publish|/pause)?|members/[a-f0-9]{24})",
            path,
        ):
            raise HTTPException(404, "未知管理操作")
        await ensure_running()
        body = await request.json() if request.method in {"POST", "PUT"} else None
        try:
            return await control(request.method, path, body)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "团队网关操作失败") from None

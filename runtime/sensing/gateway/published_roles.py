"""Owner-published role endpoints: stable identities, receiver-owned execution."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request

from runtime.platform.io import atomic_write_json


def mount_published_roles(app, *, data_dir: Path, **auth):
    from runtime.execution.suckers._delegation_skills_common import _display_name_for_agent_id
    from runtime.execution.suckers.delegation_skills import _allowed_agent_ids
    from runtime.sensing.gateway.a2a_server import mount_a2a_server

    path = data_dir / "published-roles.json"
    published = {}
    base = os.getenv("OCTOPUS_A2A_PUBLIC_URL", "http://localhost:8310").rstrip("/")

    def valid_id(value):
        return (
            isinstance(value, str)
            and value
            and len(value) <= 100
            and all(c.isascii() and (c.isalnum() or c in "_-") for c in value)
        )

    def publish(role_id, name):
        if role_id in published:
            return published[role_id]
        prefix = f"/api/a2a/roles/{role_id}"
        child = FastAPI()
        handler = mount_a2a_server(
            child,
            data_dir=data_dir / "published-roles" / role_id,
            role_id=role_id,
            role_name=name,
            public_prefix=prefix,
            **auth,
        )
        app.mount(prefix, child)
        app.router.add_event_handler("shutdown", handler.aclose)
        entry = {"role_id": role_id, "name": name, "url": base + prefix}
        published[role_id] = entry
        return entry

    if path.exists():
        for entry in json.loads(path.read_text(encoding="utf-8")):
            if valid_id(entry.get("role_id")) and isinstance(entry.get("name"), str):
                publish(entry["role_id"], entry["name"])

    def owner(request):
        from runtime.adapters.web_auth import _resolve_actor

        if not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(403, "角色发布只允许在本机操作")
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise HTTPException(403, "角色发布需要本机页面")
        _resolve_actor(request, **auth)

    @app.get("/api/a2a/published-roles")
    async def status(request: Request):
        owner(request)
        return {
            "roles": [
                {"role_id": role, "name": _display_name_for_agent_id(role) or role}
                for role in sorted(_allowed_agent_ids())
                if valid_id(role)
            ],
            "published": list(published.values()),
        }

    @app.post("/api/a2a/published-roles")
    async def create(request: Request, body: dict):
        owner(request)
        role = body.get("role_id")
        if not valid_id(role) or role not in _allowed_agent_ids():
            raise HTTPException(400, "请选择本机存在的角色")
        if set(body) != {"role_id"}:
            raise HTTPException(400, "这里只发布角色身份；执行引擎由接收方角色配置决定")
        entry = publish(role, _display_name_for_agent_id(role) or role)
        atomic_write_json(path, list(published.values()))
        return entry

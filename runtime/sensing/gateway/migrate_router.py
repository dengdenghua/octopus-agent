"""HTTP API for one-click tool migration (control-plane; auth-gated).

Thin JSON surface over ``runtime.platform.migration`` so a UI can drive the
preview → apply → activate flow:

* ``GET  /api/migrate/preview``  — read-only plan per installed source
* ``POST /api/migrate/apply``    — stage into ``.octopus/imported/`` (+ optional activate)

Both are gated by the same auth dependency the other control-plane routers use:
migration reads the user's ``~/.codex`` / ``~/.claude`` and writes into the
project, so anonymous callers are refused when auth is enabled. ``apply``
inherits the engine's safety posture (skills search-only, memory bounded index,
MCP staged disabled, credentials never migrated).
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, Depends, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False


def _plan_to_dict(plan: Any) -> dict[str, Any]:
    return {
        "source": plan.source,
        "available": plan.available,
        "kinds": plan.kinds(),
        "items": [asdict(i) for i in plan.items],
        "needs_attention": [asdict(i) for i in plan.needing_attention()],
    }


def _sources(raw: Any) -> list[str] | None:
    if isinstance(raw, list):
        vals = [str(s).strip() for s in raw if str(s).strip()]
        return vals or None
    if isinstance(raw, str) and raw.strip():
        return [s.strip() for s in raw.split(",") if s.strip()]
    return None


def create_migrate_router(
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

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

    router = APIRouter(prefix="/api/migrate", tags=["migrate"], dependencies=[Depends(_auth_dep)])

    from runtime.platform.migration import (
        SUPPORTED_SOURCES,
        activate_plan,
        apply_plan,
        build_migration_plans,
    )

    @router.get("/preview")
    def preview(sources: str | None = None) -> dict[str, Any]:
        plans = build_migration_plans(_sources(sources))
        return {
            "schema": "octopus.migrate.preview.v1",
            "supported": list(SUPPORTED_SOURCES),
            "plans": [_plan_to_dict(p) for p in plans],
        }

    @router.post("/apply")
    def apply(body: dict[str, Any]) -> dict[str, Any]:
        srcs = _sources(body.get("sources"))
        raw_kinds = body.get("kinds")
        kinds = {str(k).strip() for k in raw_kinds if str(k).strip()} if isinstance(raw_kinds, list) and raw_kinds else None
        activate = bool(body.get("activate"))
        root = Path.cwd()

        reports: list[dict[str, Any]] = []
        for plan in build_migration_plans(srcs):
            if not plan.available:
                continue
            rep = apply_plan(plan, project_root=root, kinds=kinds)
            reports.append({
                "source": rep.source,
                "applied": rep.applied,
                "skipped": rep.skipped,
                "target_root": rep.target_root,
            })

        activation: dict[str, Any] | None = None
        if activate:
            arep = activate_plan(root, sources=set(srcs) if srcs else None)
            activation = {
                "memory_added": arep.memory_added,
                "memory_skipped": arep.memory_skipped,
                "mcp_snippets": arep.mcp_snippets,
            }

        return {"schema": "octopus.migrate.apply.v1", "reports": reports, "activation": activation}

    return router

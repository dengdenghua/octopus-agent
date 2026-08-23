"""Lightweight standalone ASGI app for small cloud servers."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from .accounts import AccountAuth, AccountStore, create_account_router
from .router import create_cloud_edge_router


def create_cloud_edge_app(
    *,
    data_dir: str | Path,
    token_secret: str,
    admin_key: str,
    registration_code: str,
    owner_id: str = "admin",
    tenant_id: str = "default",
) -> FastAPI:
    if len(token_secret) < 32:
        raise RuntimeError("OCTOPUS_CLOUD_EDGE_TOKEN_SECRET must contain at least 32 characters")
    if len(admin_key) < 32:
        raise RuntimeError("OCTOPUS_CLOUD_EDGE_ADMIN_KEY must contain at least 32 characters")
    if token_secret == admin_key:
        raise RuntimeError("device token secret and admin key must be independent")
    if len(registration_code) < 12:
        raise RuntimeError("OCTOPUS_CLOUD_REGISTRATION_CODE must contain at least 12 characters")
    clean_owner = owner_id.strip()
    clean_tenant = tenant_id.strip()
    if not clean_owner or not clean_tenant:
        raise RuntimeError("cloud edge owner and tenant must be non-empty")

    root = Path(data_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "cloud_service.sqlite3"
    accounts = AccountStore(db_path)
    auth = AccountAuth(
        store=accounts,
        token_secret=token_secret,
        admin_key=admin_key,
        tenant_id=clean_tenant,
        admin_id=clean_owner,
    )
    app = FastAPI(title="Cloud Account and Message Service", version="1.0")
    app.include_router(
        create_account_router(store=accounts, auth=auth, registration_code=registration_code)
    )
    app.include_router(
        create_cloud_edge_router(
            db_path=db_path,
            token_secret=token_secret,
            require_auth=True,
            principal_resolver=auth.principal,
            operator_resolver=auth.operator,
        )
    )

    @app.get("/livez", include_in_schema=False)
    def livez() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> dict[str, bool]:
        return {"ready": True}

    return app


def create_cloud_edge_app_from_env() -> FastAPI:
    return create_cloud_edge_app(
        data_dir=os.environ.get("OCTOPUS_CLOUD_EDGE_DATA_DIR", "/data"),
        token_secret=os.environ.get("OCTOPUS_CLOUD_EDGE_TOKEN_SECRET", ""),
        admin_key=os.environ.get("OCTOPUS_CLOUD_EDGE_ADMIN_KEY", ""),
        registration_code=os.environ.get("OCTOPUS_CLOUD_REGISTRATION_CODE", ""),
        owner_id=os.environ.get("OCTOPUS_CLOUD_EDGE_OWNER_ID", "admin"),
        tenant_id=os.environ.get("OCTOPUS_CLOUD_EDGE_TENANT_ID", "default"),
    )


__all__ = ["create_cloud_edge_app", "create_cloud_edge_app_from_env"]

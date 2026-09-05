"""Static delivery contract for installed remote workbench surfaces."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from runtime.platform.plugins.workbench_package import WorkbenchPackageStore


def create_workbench_packages_router(
    store: WorkbenchPackageStore | None = None,
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    """Serve installed workbench packages behind the standard auth dependency.

    The router previously shipped with NO auth at all (audit 2026-08-28
    P1-4): the ``_app_auth`` legacy-prefix allowlist falls through to
    ``call_next``, so every ``/api/workbench-packages/*`` route was world
    readable whenever ``require_auth`` was on.  The dependency below closes
    that gap the same way ``control_sessions_router`` /
    ``browser_router`` do: a no-op when ``require_auth`` is off (default /
    single-user dev), enforced 401 across every endpoint when auth is on.
    An authenticated manifest read grants a one-hour, package-scoped HttpOnly
    cookie so iframe documents and their assets can load without bearer headers.
    """
    store = store or WorkbenchPackageStore(require_integrity=True)
    # Use a separate signing key: an asset capability must never be a login JWT.
    asset_secret = (
        hmac.new(jwt_secret.encode(), b"workbench-assets-v1", hashlib.sha256).hexdigest()
        if jwt_secret
        else None
    )
    cookie_name = "octopus_workbench_assets"

    def _auth_dep(request: Request) -> str | None:
        from runtime.adapters.web_auth import _resolve_actor
        from runtime.safety.auth.identity import JWTError, verify_jwt_hs256

        token = request.cookies.get(cookie_name)
        if asset_secret and token and "asset_path" in request.path_params:
            try:
                claims = verify_jwt_hs256(
                    token, secret=asset_secret, required_audience="workbench-assets"
                )
                actor = claims.get("sub")
                if (
                    claims.get("plugin") == request.path_params.get("plugin_id")
                    and isinstance(actor, str)
                    and identity_store is not None
                    and identity_store.get(actor) is not None
                ):
                    return actor
            except JWTError:
                pass

        return _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    router = APIRouter(
        prefix="/api/workbench-packages",
        tags=["workbench-packages"],
        dependencies=[Depends(_auth_dep)],
    )

    @router.get("/{plugin_id}/manifest")
    def get_manifest(
        plugin_id: str,
        request: Request,
        response: Response,
        actor: str | None = Depends(_auth_dep),
    ) -> dict[str, Any]:
        try:
            manifest = store.load_manifest(plugin_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        asset_base = f"/api/workbench-packages/{plugin_id}/assets"
        if actor and asset_secret:
            from runtime.safety.auth.identity import encode_jwt_hs256

            response.set_cookie(
                cookie_name,
                encode_jwt_hs256(
                    {
                        "sub": actor,
                        "plugin": plugin_id,
                        "aud": "workbench-assets",
                        "exp": int(time.time()) + 3600,
                    },
                    secret=asset_secret,
                ),
                max_age=3600,
                path=asset_base + "/",
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="strict",
            )
        response.headers["Cache-Control"] = "no-store"
        return manifest.to_public(asset_base=asset_base)

    @router.get("/{plugin_id}/assets/{asset_path:path}")
    def get_asset(plugin_id: str, asset_path: str) -> FileResponse:
        try:
            if store.require_integrity:
                store.verify_installed_integrity(plugin_id)
            path = store.asset_path(plugin_id, asset_path)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not path.is_file():
            raise HTTPException(404, f"workbench asset not found: {plugin_id}/{asset_path}")
        response = FileResponse(path)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "private, no-cache"
        if path.suffix.lower() == ".html":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob: https:; font-src 'self' data:; "
                "connect-src 'self' http://127.0.0.1:* http://localhost:* "
                "ws://127.0.0.1:* ws://localhost:* https: wss:; "
                "frame-ancestors 'self'; base-uri 'none'; object-src 'none'"
            )
        return response

    return router


__all__ = ["create_workbench_packages_router"]

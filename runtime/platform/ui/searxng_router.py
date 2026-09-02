"""Authenticated control router for the optional one-click local SearXNG.

Deploy / stop spawn or stop a Docker container — privileged actions, so they sit
behind the same ``_resolve_actor`` dependency the other mutating routers use
(no-op when ``require_auth`` is off for single-user dev; 401 when it's on). The
read-only liveness lives on the public ``/api/searxng/status`` health endpoint.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request


def create_searxng_router(
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    """Create the ``/api/searxng/*`` deploy/stop router (auth-gated mutations)."""

    def _auth_dep(request: Request) -> None:
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(  # AUTH-OK: actor-agnostic
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

    router = APIRouter(
        tags=["searxng"],
        dependencies=[Depends(_auth_dep), Depends(_operator_dep)],
    )

    @router.post("/api/searxng/enable")
    def enable() -> dict[str, Any]:
        """One-click deploy a local SearXNG container. Returns immediately; the
        image pull + boot run in the background — poll /api/searxng/status."""
        from runtime.sensing.gateway.searxng_supervisor import enable_searxng

        return enable_searxng()

    @router.post("/api/searxng/disable")
    def disable() -> dict[str, Any]:
        """Stop the managed SearXNG container (kept for fast re-enable)."""
        from runtime.sensing.gateway.searxng_supervisor import disable_searxng

        return disable_searxng()

    return router

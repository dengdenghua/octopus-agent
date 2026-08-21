"""Router-level auth helpers shared by the observability endpoint groups.

Pure structural extraction from ``_observability_router_factory.py`` (no
logic changes). These helpers enforce the ``require_auth`` gate across every
observability endpoint and resolve operator identity for audit-worthy
receipt mutations.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from ._observability_helpers import HTTPException, Request
from ._observability_state import ObservabilityContext


def make_auth_dep(ctx: ObservabilityContext) -> Callable[[Request], None]:
    """Router-level auth gate · mirrors create_browser_router. These
    endpoints expose the journal (file diffs, absolute paths, task
    history) over /api/stream + /api/files/stream. require_auth off
    (default / single-user dev) → _resolve_actor is a no-op so local
    preview + the EventSource-based Observability panel are unchanged;
    require_auth on (deployed / multi-user) → 401 across every endpoint
    instead of leaking the whole work log to any anonymous client.
    """

    def _auth_dep(request: Request) -> None:
        from runtime.safety.auth.principal import require_roles

        # Journal/SSE/KG/progress are process-global today and cannot be
        # reliably filtered by actor/tenant at read time. Until the event
        # schema carries authoritative ownership, fail closed to operational
        # roles in shared mode rather than exposing other users' transcripts.
        require_roles(
            request,
            ctx.identity_store,
            ctx.require_auth,
            ("admin", "operator"),
            jwt_secret=ctx.jwt_secret,
            jwt_issuer=ctx.jwt_issuer,
            jwt_audience=ctx.jwt_audience,
        )

    return _auth_dep


def _operator_identity(request: Request, ctx: ObservabilityContext) -> tuple[str, Any]:
    from runtime.adapters.web_auth import _resolve_actor

    actor = _resolve_actor(
        request,
        ctx.identity_store,
        ctx.require_auth,
        jwt_secret=ctx.jwt_secret,
        jwt_issuer=ctx.jwt_issuer,
        jwt_audience=ctx.jwt_audience,
    )
    if not ctx.require_auth:
        return str(actor or "local_operator"), None

    auth = request.headers.get("Authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    identity = None
    if ctx.identity_store is not None and token:
        if ctx.jwt_secret and token.count(".") == 2:
            with contextlib.suppress(Exception):
                identity = ctx.identity_store.verify_jwt(
                    token,
                    secret=ctx.jwt_secret,
                    required_issuer=ctx.jwt_issuer,
                    required_audience=ctx.jwt_audience,
                )
        if identity is None:
            with contextlib.suppress(Exception):
                identity = ctx.identity_store.verify_api_key(token)
    return str(actor or "authenticated_operator"), identity


def _identity_is_admin(identity: Any) -> bool:
    roles = getattr(identity, "roles", ()) or ()
    return "admin" in {str(role).lower() for role in roles}


def _can_authorize_retry(request: Request, ctx: ObservabilityContext) -> bool:
    if not ctx.require_auth:
        return True
    _, identity = _operator_identity(request, ctx)
    return _identity_is_admin(identity)


def _operator_actor(request: Request, ctx: ObservabilityContext) -> str:
    """Resolve an operator and require admin for receipt mutations."""

    actor, identity = _operator_identity(request, ctx)
    if ctx.require_auth and not _identity_is_admin(identity):
        raise HTTPException(403, "admin role required")
    return actor


__all__ = [
    "make_auth_dep",
    "_operator_identity",
    "_identity_is_admin",
    "_can_authorize_retry",
    "_operator_actor",
]

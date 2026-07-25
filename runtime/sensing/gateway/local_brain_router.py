"""Local-brain setup router · ``/api/local-brain/*``.

Backs the work-mode setup wizard: a single plain-language readiness checklist
the frontend renders so a non-technical user can wire their whole stack to run
locally. Read-only — it probes (Ollama / Storage / embedding backend / index)
and reports; it never installs or restarts anything.
"""

from __future__ import annotations

import ipaddress
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]

from runtime.sensing._fastapi_guard import require_fastapi


def _is_loopback_request(request: Request) -> bool:
    """Storage's bearer token must never leave the local machine."""
    host = getattr(getattr(request, "client", None), "host", "") or ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"

def create_local_brain_router(
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    """Build + return the router. Call site:
    ``app.include_router(create_local_brain_router())``."""
    require_fastapi(__name__)

    router = APIRouter(tags=["local-brain"])

    def _auth(request: Request) -> str | None:
        if require_auth and identity_store is None:
            raise HTTPException(401, "auth required")
        from runtime.sensing.gateway.openai_gateway_router import _resolve_actor

        return _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    @router.get("/api/local-brain/status")
    def api_local_brain_status(request: Request) -> dict[str, Any]:
        _auth(request)
        """Return the plain-language readiness checklist (5 items + summary).
        Best-effort: any probe failure surfaces as that item being not-ok with
        a next step, never a 500."""
        from runtime.sensing.gateway.local_brain import local_brain_status

        return local_brain_status()

    @router.post("/api/local-brain/storage/start")
    def api_local_brain_storage_start(request: Request) -> dict[str, Any]:
        """Start/probe Storage and provide its ephemeral local-session token.

        The storage service deliberately requires a bearer token.  A browser
        reload clears its sessionStorage, so a local, authenticated bridge is
        required to reconnect without weakening Storage itself.  The token is
        never persisted by this API and is refused for non-loopback callers.
        """
        _auth(request)
        if not _is_loopback_request(request):
            raise HTTPException(403, "storage credentials are local-only")

        from runtime.execution.suckers.storage_skills import (
            _base_url,
            _storage_token,
            storage_alive,
        )
        from runtime.sensing.gateway.storage_supervisor import maybe_start_storage

        status = maybe_start_storage()
        available = storage_alive(timeout=1.5)
        return {
            "ok": available,
            "status": status,
            "base_url": _base_url(),
            # The frontend keeps this in sessionStorage only.  Do not return a
            # token until the loopback storage service has actually responded.
            "auth_token": _storage_token() if available else None,
        }

    return router

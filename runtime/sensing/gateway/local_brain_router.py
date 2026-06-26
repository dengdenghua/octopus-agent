"""Local-brain setup router · ``/api/local-brain/*``.

Backs the work-mode setup wizard: a single plain-language readiness checklist
the frontend renders so a non-technical user can wire their whole stack to run
locally. Read-only — it probes (Ollama / Storage / embedding backend / index)
and reports; it never installs or restarts anything.
"""

from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]


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
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

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

    return router

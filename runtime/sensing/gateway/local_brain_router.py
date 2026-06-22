"""Local-brain setup router · ``/api/local-brain/*``.

Backs the work-mode setup wizard: a single plain-language readiness checklist
the frontend renders so a non-technical user can wire their whole stack to run
locally. Read-only — it probes (Ollama / Storage / embedding backend / index)
and reports; it never installs or restarts anything.
"""

from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]


def create_local_brain_router() -> Any:
    """Build + return the router. Call site:
    ``app.include_router(create_local_brain_router())``."""
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(tags=["local-brain"])

    @router.get("/api/local-brain/status")
    def api_local_brain_status() -> dict[str, Any]:
        """Return the plain-language readiness checklist (5 items + summary).
        Best-effort: any probe failure surfaces as that item being not-ok with
        a next step, never a 500."""
        from runtime.sensing.gateway.local_brain import local_brain_status

        return local_brain_status()

    return router

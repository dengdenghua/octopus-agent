"""Team role-model settings router · ``/api/team/role-models``.

Lets the work-mode team settings UI read + set the per-role model tier (cheap vs
primary) — making the cost-saving division of labour configurable instead of
hard-coded. GET returns each role with its built-in default + any override; PUT
persists the overrides.
"""

from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]


class RoleModelsBody(BaseModel):
    overrides: dict[str, str] = {}


def create_team_role_models_router() -> Any:
    """Build + return the router."""
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(tags=["team-role-models"])

    @router.get("/api/team/role-models")
    def api_get_role_models() -> dict[str, Any]:
        from runtime.safety.organization.team_role_models import load_overrides, role_defaults

        defaults = role_defaults()
        overrides = load_overrides()
        return {
            "roles": [
                {
                    "role": role,
                    "default": default,
                    "tier": overrides.get(role, "default"),
                }
                for role, default in sorted(defaults.items())
            ],
            "tiers": ["default", "cheap", "primary"],
        }

    @router.put("/api/team/role-models")
    def api_put_role_models(body: RoleModelsBody) -> dict[str, Any]:
        from runtime.safety.organization.team_role_models import save_overrides

        return {"ok": True, "overrides": save_overrides(body.overrides or {})}

    return router

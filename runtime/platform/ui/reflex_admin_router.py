"""Reflex, gene-locks, and forge admin routes for the UI app."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from runtime.platform.ui._reflex_admin_endpoints import (
    register_reflex_admin_endpoints,
)


def mount_reflex_admin_routes(
    app: Any,
    *,
    stack: Any,
    reflex_router: Any,
    panel_html: str,
    editor_html: str,
) -> None:
    """Mount optional Reflex admin routes when a reflex router exists."""
    if reflex_router is None:
        return
    _reflex_admin = APIRouter(tags=["reflex-admin"])
    register_reflex_admin_endpoints(
        _reflex_admin,
        stack=stack,
        reflex_router=reflex_router,
        panel_html=panel_html,
        editor_html=editor_html,
    )
    app.include_router(_reflex_admin)

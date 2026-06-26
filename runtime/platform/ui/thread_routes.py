"""Thread route mounting for the realtime UI."""

from __future__ import annotations

from typing import Any


def build_reflex_router(stack: Any) -> Any:
    """Build the optional SpinalCord reflex router for stack-backed apps."""
    if stack is None:
        return None
    try:
        from runtime.cli import _build_reflex_router

        return _build_reflex_router()
    except Exception:  # noqa: BLE001
        return None


def mount_thread_state_routes(
    app: Any,
    *,
    thread_store: Any,
    logs_root: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> None:
    """Mount thread state CRUD used by sidebars and scope settings."""
    if thread_store is None:
        return

    from runtime.sensing.gateway.thread_state_router import create_thread_state_router

    app.include_router(create_thread_state_router(
        store=thread_store,
        logs_root=logs_root,
        identity_store=identity_store,
        require_auth=require_auth,
        jwt_secret=jwt_secret,
        jwt_issuer=jwt_issuer,
        jwt_audience=jwt_audience,
    ))


__all__ = ["build_reflex_router", "mount_thread_state_routes"]

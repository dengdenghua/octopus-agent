"""Create the FastAPI app, AppState, and auth config for ``create_app``.

Extracted from ``app.py`` during the god-file reduction (§2.1 of the
navigation map). Builds the ``FastAPI`` instance, the shared
``AppState``, resolves the cocoloop/oct/molili/local jwt config, and
installs the legacy control-plane auth middleware.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from runtime.platform.ui.compression import GzipStaticMiddleware
from runtime.platform.ui.state import AppState

from ._app_auth import _install_legacy_control_plane_auth
from ._app_context import AppContext


def setup_app(
    *,
    journal_path: Any,
    journal: Any,
    registry: Any,
    stack: Any,
    cocoloop_identity_store: Any,
    cocoloop_require_auth: bool,
    molili_config: Any,
    molili_jwt_secret: str | None,
    oct_config: Any,
    oct_jwt_secret: str | None,
    local_auth_config: Any,
) -> AppContext:
    """Build the app shell + auth config; return the shared context."""
    from runtime.platform.process.paths import app_paths, project_root, resources_root

    _paths = app_paths()
    _project_root_path = project_root()
    _resources_root_path = resources_root()
    trace_store_path = _paths.agent_trace_path.resolve()
    state = AppState(
        journal_path=journal_path,
        journal=journal,
        registry=registry,
        trace_store_path=trace_store_path,
    )
    from runtime import __version__

    app = FastAPI(title="octopus-agent", version=__version__)
    app.state.octopus_state = state

    # Gzip the static Vite UI bundle (~18 MB raw) and JSON API responses while
    # leaving SSE / streaming endpoints untouched. See GzipStaticMiddleware.
    app.add_middleware(GzipStaticMiddleware)

    if molili_jwt_secret is None and molili_config is not None:
        molili_jwt_secret = getattr(molili_config, "jwt_secret", None)
    if oct_jwt_secret is None and oct_config is not None:
        oct_jwt_secret = getattr(oct_config, "jwt_secret", None)
    oct_enabled = bool(oct_config is not None and getattr(oct_config, "enabled", False))

    auth_enabled = (
        oct_enabled
        or bool(molili_config is not None and getattr(molili_config, "enabled", False))
        or bool(local_auth_config is not None and getattr(local_auth_config, "enabled", False))
    )
    # oct 网关优先(母本账号体系已统一到 oct),其次 molili,再 local_auth
    cocoloop_jwt_secret = (
        (oct_jwt_secret if oct_enabled else None)
        or molili_jwt_secret
        or (getattr(local_auth_config, "jwt_secret", None) if local_auth_config else None)
    )
    cocoloop_jwt_issuer = (
        getattr(oct_config, "jwt_issuer", None)
        if (oct_enabled and oct_jwt_secret)
        else getattr(molili_config, "jwt_issuer", None)
        if molili_jwt_secret and molili_config
        else getattr(local_auth_config, "jwt_issuer", None)
        if local_auth_config
        else None
    )
    cocoloop_jwt_audience = (
        getattr(oct_config, "jwt_audience", None)
        if (oct_enabled and oct_jwt_secret)
        else getattr(molili_config, "jwt_audience", None)
        if molili_jwt_secret and molili_config
        else getattr(local_auth_config, "jwt_audience", None)
        if local_auth_config
        else None
    )
    local_auth_runtime_config = local_auth_config
    if (
        local_auth_config is not None
        and getattr(local_auth_config, "enabled", False)
        and cocoloop_jwt_secret
        and getattr(local_auth_config, "jwt_secret", None) != cocoloop_jwt_secret
    ):
        try:
            local_auth_runtime_config = local_auth_config.model_copy(
                update={
                    "jwt_secret": cocoloop_jwt_secret,
                    "jwt_issuer": cocoloop_jwt_issuer,
                    "jwt_audience": cocoloop_jwt_audience,
                }
            )
        except AttributeError:
            local_auth_runtime_config = local_auth_config
    if cocoloop_identity_store is None and auth_enabled:
        from runtime.safety.auth.identity import IdentityStore

        cocoloop_identity_store = IdentityStore()
    if (
        local_auth_config is not None
        and getattr(local_auth_config, "enabled", False)
        and getattr(local_auth_config, "allow_any_username", False)
    ):
        logging.getLogger(__name__).warning(
            "local auth allow_any_username=true accepts arbitrary usernames; "
            "use only for trusted local development"
        )

    _install_legacy_control_plane_auth(
        app,
        identity_store=cocoloop_identity_store,
        require_auth=cocoloop_require_auth,
        jwt_secret=cocoloop_jwt_secret,
        jwt_issuer=cocoloop_jwt_issuer,
        jwt_audience=cocoloop_jwt_audience,
    )

    return AppContext(
        app=app,
        state=state,
        stack=stack,
        paths=_paths,
        project_root=_project_root_path,
        resources_root=_resources_root_path,
        trace_store_path=trace_store_path,
        identity_store=cocoloop_identity_store,
        require_auth=cocoloop_require_auth,
        jwt_secret=cocoloop_jwt_secret,
        jwt_issuer=cocoloop_jwt_issuer,
        jwt_audience=cocoloop_jwt_audience,
        local_auth_runtime_config=local_auth_runtime_config,
    )

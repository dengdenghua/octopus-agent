"""Account / auth provider routers for ``create_app``.

Extracted from ``app.py`` during the god-file reduction (§2.6 of the
navigation map). Mounts the molili, oct, and local-auth account
routers, and attaches their fallback model dispatchers.
"""

from __future__ import annotations

from typing import Any

from ._app_context import AppContext
from ._app_fallback_routers import (
    _attach_molili_fallback_router,
    _attach_oct_fallback_router,
)


def mount_auth_routers(
    ctx: AppContext,
    *,
    molili_config: Any,
    molili_link_store: Any,
    oct_config: Any,
    oct_link_store: Any,
) -> None:
    """Mount the molili / oct / local-auth account routers."""
    app = ctx.app
    stack = ctx.stack

    if molili_config is not None and getattr(molili_config, "enabled", False):
        from runtime.adapters.integrations.molili import (
            MoliliLinkStore,
            create_molili_routers,
        )

        effective_link_store = molili_link_store or MoliliLinkStore()
        _attach_molili_fallback_router(
            stack=stack,
            molili_config=molili_config,
            link_store=effective_link_store,
        )

        auth_router, account_router, proxy_router = create_molili_routers(
            config=molili_config,
            link_store=effective_link_store,
            identity_store=ctx.identity_store,
            require_auth=ctx.require_auth,
            jwt_secret=ctx.jwt_secret,
        )
        app.include_router(auth_router)
        app.include_router(account_router)
        app.include_router(proxy_router)

    if oct_config is not None and getattr(oct_config, "enabled", False):
        # oct 账号网关(octopus 自己的,api.octoapk.com)· 替代 molili。
        # agent 内部 LLM 调度接 oct 计费 = actor 感知 fallback(登录走网关计费、guest 走自配,保 P0)。
        from runtime.adapters.integrations.oct import (
            OctLinkStore,
            create_oct_routers,
        )

        effective_oct_link_store = oct_link_store or OctLinkStore()
        _attach_oct_fallback_router(
            stack=stack,
            oct_config=oct_config,
            link_store=effective_oct_link_store,
        )
        oct_auth_router, oct_account_router, oct_proxy_router = create_oct_routers(
            config=oct_config,
            link_store=effective_oct_link_store,
            identity_store=ctx.identity_store,
            require_auth=ctx.require_auth,
            jwt_secret=ctx.jwt_secret,
        )
        app.include_router(oct_auth_router)
        app.include_router(oct_account_router)
        app.include_router(oct_proxy_router)

    if ctx.local_auth_runtime_config is not None and getattr(
        ctx.local_auth_runtime_config,
        "enabled",
        False,
    ):
        from runtime.adapters.integrations.local_auth import create_local_auth_router

        app.include_router(
            create_local_auth_router(
                config=ctx.local_auth_runtime_config,
                identity_store=ctx.identity_store,
            )
        )

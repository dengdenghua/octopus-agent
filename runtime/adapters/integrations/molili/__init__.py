
from .client import MoliliClientError
from .config import MoliliAuthConfig, MoliliConfig, load_molili_config_from_dict
from .links import MoliliLink, MoliliLinkStore
from .router_account import create_account_router
from .router_auth import create_auth_router
from .router_proxy import create_proxy_router


def create_molili_routers(
    *,
    config: MoliliConfig,
    link_store: MoliliLinkStore,
    identity_store: object | None = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> tuple[object, object, object]:
    auth_router = create_auth_router(
        config=config,
        link_store=link_store,
        identity_store=identity_store,
        jwt_secret=jwt_secret,
        jwt_issuer=jwt_issuer,
        jwt_audience=jwt_audience,
    )
    account_router = create_account_router(
        config=config,
        link_store=link_store,
        identity_store=identity_store,
        require_auth=require_auth,
        jwt_secret=jwt_secret,
        jwt_issuer=jwt_issuer,
        jwt_audience=jwt_audience,
    )
    proxy_router = create_proxy_router(
        config=config,
        link_store=link_store,
        identity_store=identity_store,
        require_auth=require_auth,
        jwt_secret=jwt_secret,
        jwt_issuer=jwt_issuer,
        jwt_audience=jwt_audience,
    )
    return auth_router, account_router, proxy_router


__all__ = [
    "MoliliAuthConfig",
    "MoliliClientError",
    "MoliliConfig",
    "MoliliLink",
    "MoliliLinkStore",
    "create_account_router",
    "create_auth_router",
    "create_molili_routers",
    "create_proxy_router",
    "load_molili_config_from_dict",
]

"""OAuth-on-enable for remote MCP servers (control-plane).

Two endpoints, deliberately split on auth:

* ``POST /api/mcp-oauth/authorize`` — operator-initiated, **auth-gated**. Mints
  PKCE + ``state``, returns the provider authorize URL for the UI to open.
* ``GET  /api/mcp-oauth/callback``  — the provider's browser redirect; it carries
  no operator token, so it is **state-gated, not auth-gated** (the high-entropy,
  single-use ``state`` minted by the authorized /authorize call is the CSRF
  guard, and the PKCE verifier never leaves the server).

The prefix is ``/api/mcp-oauth`` (NOT under ``/api/mcp``) on purpose, so the
legacy control-plane middleware doesn't blanket-401 the unauthenticated callback.
"""
from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import HTMLResponse

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False


def _callback_url(request: Any) -> str:
    base = str(getattr(request, "base_url", "") or "").rstrip("/")
    return f"{base}/api/mcp-oauth/callback"


def create_mcp_oauth_router(
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    from runtime.adapters.mcp_client import oauth_discovery
    from runtime.adapters.mcp_client.oauth import (
        build_authorize_url,
        exchange_code,
        get_oauth_store,
        new_pkce,
    )

    router = APIRouter(prefix="/api/mcp-oauth", tags=["mcp-oauth"])

    @router.post("/authorize")
    def authorize(body: dict[str, Any], request: Request) -> dict[str, Any]:
        # Operator-gated. (The callback is NOT — it is state-gated.)
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request, identity_store, require_auth,
            jwt_secret=jwt_secret, jwt_issuer=jwt_issuer, jwt_audience=jwt_audience,
        )

        server = str(body.get("server") or "").strip()
        authorize_url = str(body.get("authorize_url") or "").strip()
        token_url = str(body.get("token_url") or "").strip()
        client_id = str(body.get("client_id") or "").strip()
        if not (server and authorize_url and token_url and client_id):
            raise HTTPException(
                400, "server, authorize_url, token_url, client_id are required",
            )
        raw_scopes = body.get("scopes")
        scopes = [str(s) for s in raw_scopes] if isinstance(raw_scopes, list) else None
        redirect_uri = str(body.get("redirect_uri") or "").strip() or _callback_url(request)

        verifier, challenge = new_pkce()
        state = get_oauth_store().start_pending(
            server=server, code_verifier=verifier, redirect_uri=redirect_uri,
            token_url=token_url, client_id=client_id,
        )
        url = build_authorize_url(
            authorize_url=authorize_url, client_id=client_id, redirect_uri=redirect_uri,
            scopes=scopes, state=state, code_challenge=challenge,
        )
        return {"schema": "octopus.mcp_oauth.authorize.v1", "authorize_url": url, "state": state}

    @router.post("/start")
    def start(body: dict[str, Any], request: Request) -> dict[str, Any]:
        """Auto-discover a server's OAuth endpoints (+ register a client if the
        issuer supports DCR), then return the authorize URL — so the UI only has
        to supply ``server`` + ``url``."""
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request, identity_store, require_auth,
            jwt_secret=jwt_secret, jwt_issuer=jwt_issuer, jwt_audience=jwt_audience,
        )
        server = str(body.get("server") or "").strip()
        url = str(body.get("url") or "").strip()
        if not (server and url):
            raise HTTPException(400, "server and url are required")
        redirect_uri = str(body.get("redirect_uri") or "").strip() or _callback_url(request)

        endpoints = oauth_discovery.discover(url)
        if endpoints is None:
            raise HTTPException(
                502, "OAuth discovery failed for this server; use /authorize with explicit endpoints",
            )
        store = get_oauth_store()
        client_id = store.get_client(endpoints.issuer) or str(body.get("client_id") or "").strip()
        if not client_id and endpoints.registration_url:
            client_id = oauth_discovery.register_client(
                endpoints.registration_url, redirect_uri=redirect_uri,
            ) or ""
            if client_id:
                store.save_client(endpoints.issuer, client_id)
        if not client_id:
            raise HTTPException(
                502, "no client_id (issuer has no dynamic registration); supply client_id",
            )

        verifier, challenge = new_pkce()
        state = store.start_pending(
            server=server, code_verifier=verifier, redirect_uri=redirect_uri,
            token_url=endpoints.token_url, client_id=client_id,
        )
        authorize_url = build_authorize_url(
            authorize_url=endpoints.authorize_url, client_id=client_id,
            redirect_uri=redirect_uri, scopes=list(endpoints.scopes) or None,
            state=state, code_challenge=challenge,
        )
        return {
            "schema": "octopus.mcp_oauth.start.v1",
            "authorize_url": authorize_url, "state": state, "issuer": endpoints.issuer,
        }

    @router.get("/callback")
    def callback(code: str = "", state: str = "", error: str = "") -> Any:
        if error:
            return HTMLResponse(f"<p>authorization failed: {error}</p>", status_code=400)
        store = get_oauth_store()
        pending = store.pop_pending(state) if state else None
        if pending is None:
            return HTMLResponse(
                "<p>invalid or expired authorization (state) · 无效或过期</p>",
                status_code=400,
            )
        if not code:
            return HTMLResponse("<p>missing code · 缺少 code</p>", status_code=400)
        try:
            resp = exchange_code(
                token_url=pending.token_url, code=code, code_verifier=pending.code_verifier,
                client_id=pending.client_id, redirect_uri=pending.redirect_uri,
            )
        except Exception as exc:  # noqa: BLE001 — surface a friendly page, not a 500 trace
            return HTMLResponse(
                f"<p>token exchange failed: {type(exc).__name__}</p>", status_code=502,
            )
        if not resp.get("access_token"):
            return HTMLResponse(
                "<p>authorization server returned no access_token</p>", status_code=502,
            )
        store.save_tokens(
            pending.server, resp, token_url=pending.token_url, client_id=pending.client_id,
        )
        return HTMLResponse(
            f"<p>✓ {pending.server} authorized · 授权成功,可关闭此页。</p>",
        )

    return router

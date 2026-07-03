"""
Remote backends router · ``/api/remote-backends/*``.

Lets the desktop UI register remote octopus-agent runtimes.

Endpoints
---------

    GET    /api/remote-backends              · list registered
    POST   /api/remote-backends              · add { name, url, ssh? }
    DELETE /api/remote-backends/{id}         · remove
    POST   /api/remote-backends/{id}/health  · ping + record outcome
    POST   /api/remote-backends/{id}/proxy   · one-shot HTTP proxy
    WS     /api/remote-backends/{id}/realtime· JSON-RPC 2.0 WebSocket relay

All mutating + proxy endpoints require ``ui.remote_transport``
feature flag to be ON; otherwise they return 403. The ``GET`` is
safe to call regardless — it's just a list.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket

from runtime.sensing.gateway.remote_transport import (
    BackendRegistry,
    SshTunnel,
    health_check,
    proxy_request,
    proxy_websocket,
)


def _require_flag() -> None:
    from runtime.platform import feature_flags as _ff

    if not _ff.is_on("ui.remote_transport"):
        raise HTTPException(
            403,
            detail={
                "error": "remote_transport_disabled",
                "hint": "set feature flag 'ui.remote_transport' to enable",
            },
        )


def _safe_dict(b: Any) -> dict[str, Any]:
    """Strip raw SSH credentials when surfacing to UI.

    ``identity_file`` paths are kept (user already knows them, no
    secret is exposed) — but if the user later inputs SSH passwords
    via the registry we'd scrub them here.
    """
    return b.to_dict()


def create_remote_backends_router(
    *,
    store_path: str | Path | None = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    """Factory. ``store_path`` defaults to
    ``<data>/remote_backends.json``; tests pass a tmp path."""

    if store_path is None:
        from runtime.platform.process.paths import app_paths

        store_path = app_paths().data_dir / "remote_backends.json"

    registry = BackendRegistry(store_path)

    class _WsAuthError(Exception):
        """Raised to refuse an unauthenticated remote-backend WS handshake."""

    def _auth_http(request: Request) -> None:
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    def _resolve_ws_actor(ws: WebSocket) -> str | None:
        if identity_store is None:
            if require_auth:
                raise _WsAuthError("identity store required for remote backend auth")
            return None

        token: str | None = None
        auth_header = ws.headers.get("authorization") or ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        if token is None:
            subproto = ws.headers.get("sec-websocket-protocol") or ""
            parts = [p.strip() for p in subproto.split(",") if p.strip()]
            if len(parts) >= 2 and parts[0].lower() == "bearer":
                token = parts[1]
        if token is None:
            token = ws.query_params.get("token")
        if not token:
            if require_auth:
                raise _WsAuthError("missing remote backend auth token")
            return None

        if jwt_secret and token.count(".") == 2:
            identity = identity_store.verify_jwt(
                token,
                secret=jwt_secret,
                required_issuer=jwt_issuer,
                required_audience=jwt_audience,
                trust_jwt_sub=True,
            )
            if identity is not None:
                return identity.actor_id
            if require_auth:
                raise _WsAuthError("invalid jwt")
        identity = identity_store.verify_api_key(token)
        if identity is not None:
            return identity.actor_id
        if require_auth:
            raise _WsAuthError("invalid token")
        return None

    router = APIRouter()

    @router.get("/api/remote-backends")
    def list_backends(request: Request) -> dict[str, Any]:
        _auth_http(request)
        from runtime.platform import feature_flags as _ff

        return {
            "enabled": _ff.is_on("ui.remote_transport"),
            "backends": [_safe_dict(b) for b in registry.list()],
        }

    @router.post("/api/remote-backends")
    def add_backend(
        request: Request,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _auth_http(request)
        _require_flag()
        payload = body or {}
        name = str(payload.get("name") or "").strip()
        url = str(payload.get("url") or "").strip()
        if not name:
            raise HTTPException(400, "name is required")
        if not url:
            raise HTTPException(400, "url is required")
        ssh: SshTunnel | None = None
        ssh_raw = payload.get("ssh")
        if isinstance(ssh_raw, dict):
            ssh = SshTunnel.from_dict(ssh_raw)
            if ssh is None:
                raise HTTPException(
                    400,
                    "ssh.host is required when ssh is provided",
                )
        try:
            backend = registry.add(name=name, url=url, ssh=ssh)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"backend": _safe_dict(backend)}

    @router.delete("/api/remote-backends/{backend_id}")
    def remove_backend(backend_id: str, request: Request) -> dict[str, Any]:
        _auth_http(request)
        _require_flag()
        if not registry.remove(backend_id):
            raise HTTPException(404, f"backend {backend_id!r} not found")
        return {"removed": backend_id}

    @router.post("/api/remote-backends/{backend_id}/health")
    def ping_backend(backend_id: str, request: Request) -> dict[str, Any]:
        _auth_http(request)
        _require_flag()
        backend = registry.get(backend_id)
        if backend is None:
            raise HTTPException(404, f"backend {backend_id!r} not found")
        status, detail = health_check(backend)
        registry.update_health(backend_id, status=status, detail=detail)
        return {
            "status": status,
            "detail": detail,
            "backend": _safe_dict(registry.get(backend_id)),
        }

    @router.post("/api/remote-backends/{backend_id}/proxy")
    def proxy(
        backend_id: str,
        request: Request,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _auth_http(request)
        _require_flag()
        backend = registry.get(backend_id)
        if backend is None:
            raise HTTPException(404, f"backend {backend_id!r} not found")
        payload = body or {}
        method = str(payload.get("method") or "GET").upper()
        path = str(payload.get("path") or "").strip()
        if not path:
            raise HTTPException(400, "path is required")
        json_body = payload.get("json")
        try:
            result = proxy_request(
                backend,
                method=method,
                path=path,
                json=json_body,
                timeout_seconds=float(payload.get("timeout_seconds") or 30.0),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return result

    @router.websocket("/api/remote-backends/{backend_id}/realtime")
    async def realtime_proxy(
        backend_id: str,
        ws: WebSocket,
    ) -> None:
        """Relay a JSON-RPC 2.0 WebSocket session to the remote
        backend's ``/api/realtime`` gateway.

        The desktop client opens one WebSocket to *this* server; we
        open a second WebSocket to the remote backend and pump
        frames bidirectionally.

        The feature flag check happens AFTER accepting the WebSocket
        so we can send a proper JSON-RPC error frame instead of a
        bare HTTP 403 (which the WS client can't read).
        """
        try:
            _resolve_ws_actor(ws)
        except _WsAuthError:
            await ws.close(code=4401)
            return

        await ws.accept()
        from runtime.platform import feature_flags as _ff

        if not _ff.is_on("ui.remote_transport"):
            from runtime.sensing.gateway.remote_transport import (
                _ws_error_envelope,
            )

            await ws.send_text(
                _ws_error_envelope("remote_transport feature flag is disabled"),
            )
            await ws.close(code=1008)  # 1008 = policy violation
            return

        backend = registry.get(backend_id)
        if backend is None:
            from runtime.sensing.gateway.remote_transport import (
                _ws_error_envelope,
            )

            await ws.send_text(
                _ws_error_envelope(f"backend {backend_id!r} not found"),
            )
            await ws.close(code=1008)
            return

        await proxy_websocket(backend, ws)

    return router


__all__ = ["create_remote_backends_router"]

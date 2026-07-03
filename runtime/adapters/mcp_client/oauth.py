"""MCP OAuth 2.0 (PKCE) client — authorize-on-enable for remote MCP servers.

Step 1 covers **known** authorization endpoints (the caller supplies
``authorize_url`` / ``token_url`` / ``client_id``; auto-discovery via
``.well-known`` + dynamic client registration is step 2). The flow:

1. **authorize** — mint a PKCE verifier + CSRF ``state``, persist a pending
   record, and return the provider authorize URL for the UI to open.
2. **callback** — the provider redirects back with ``?code&state``; we match the
   pending record by ``state``, exchange the code (+ verifier) for tokens, and
   persist them per server.
3. **transport** — :func:`bearer_for_server` returns a valid access token
   (refreshing via ``refresh_token`` near expiry), which the remote MCP client
   attaches as ``Authorization: Bearer``.

Tokens live in ``~/.octopus/mcp_oauth.json`` (chmod 0600). Encryption-at-rest is
a follow-up; for now file perms match how local CLIs store OAuth tokens.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

from runtime.platform.io import atomic_write_json

_PENDING_TTL = 600.0  # authorize→callback round-trip window (10 min)
_REFRESH_SKEW = 60.0  # refresh when within 60s of expiry


# ── PKCE + URL ───────────────────────────────────────────


def new_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for PKCE S256."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(
    *,
    authorize_url: str,
    client_id: str,
    redirect_uri: str,
    scopes: list[str] | None,
    state: str,
    code_challenge: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    sep = "&" if "?" in authorize_url else "?"
    return f"{authorize_url}{sep}{urllib.parse.urlencode(params)}"


def _post_form(url: str, data: dict[str, str], timeout: float = 30.0) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    with urllib_request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — token endpoint
        return json.loads(resp.read().decode("utf-8"))


def exchange_code(
    *,
    token_url: str,
    code: str,
    code_verifier: str,
    client_id: str,
    redirect_uri: str,
) -> dict[str, Any]:
    return _post_form(
        token_url,
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        },
    )


def refresh_access(*, token_url: str, refresh_token: str, client_id: str) -> dict[str, Any]:
    return _post_form(
        token_url,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
    )


# ── Store ────────────────────────────────────────────────


@dataclass
class _Pending:
    server: str
    code_verifier: str
    redirect_uri: str
    token_url: str
    client_id: str
    created_ts: float


@dataclass
class _Tokens:
    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    token_url: str = ""
    client_id: str = ""


def _store_path() -> Path:
    home = os.environ.get("OCTOPUS_HOME")
    base = Path(home) if home else (Path.home() / ".octopus")
    base.mkdir(parents=True, exist_ok=True)
    return base / "mcp_oauth.json"


class MCPOAuthStore:
    """Thread-safe, JSON-backed per-server OAuth token + pending-flow store."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else _store_path()
        self._lock = threading.RLock()
        self._pending: dict[str, _Pending] = {}
        self._tokens: dict[str, _Tokens] = {}
        self._clients: dict[str, str] = {}  # issuer → registered client_id (DCR)
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for srv, tok in (raw.get("tokens") or {}).items():
            try:
                self._tokens[str(srv)] = _Tokens(
                    access_token=str(tok["access_token"]),
                    refresh_token=str(tok.get("refresh_token", "")),
                    expires_at=float(tok.get("expires_at", 0.0)),
                    token_url=str(tok.get("token_url", "")),
                    client_id=str(tok.get("client_id", "")),
                )
            except (KeyError, TypeError, ValueError):
                continue
        for state, pend in (raw.get("pending") or {}).items():
            try:
                self._pending[str(state)] = _Pending(
                    server=str(pend["server"]),
                    code_verifier=str(pend["code_verifier"]),
                    redirect_uri=str(pend["redirect_uri"]),
                    token_url=str(pend["token_url"]),
                    client_id=str(pend["client_id"]),
                    created_ts=float(pend.get("created_ts", 0.0)),
                )
            except (KeyError, TypeError, ValueError):
                continue
        for issuer, cid in (raw.get("clients") or {}).items():
            if isinstance(cid, str):
                self._clients[str(issuer)] = cid

    def _save(self) -> None:
        now = time.time()
        self._pending = {
            s: p for s, p in self._pending.items() if now - p.created_ts < _PENDING_TTL
        }
        payload = {
            "version": 1,
            "tokens": {
                s: {
                    "access_token": t.access_token,
                    "refresh_token": t.refresh_token,
                    "expires_at": t.expires_at,
                    "token_url": t.token_url,
                    "client_id": t.client_id,
                }
                for s, t in self._tokens.items()
            },
            "pending": {
                s: {
                    "server": p.server,
                    "code_verifier": p.code_verifier,
                    "redirect_uri": p.redirect_uri,
                    "token_url": p.token_url,
                    "client_id": p.client_id,
                    "created_ts": p.created_ts,
                }
                for s, p in self._pending.items()
            },
            "clients": dict(self._clients),
        }
        atomic_write_json(self._path, payload)
        with contextlib.suppress(OSError):
            os.chmod(self._path, 0o600)

    def start_pending(
        self,
        *,
        server: str,
        code_verifier: str,
        redirect_uri: str,
        token_url: str,
        client_id: str,
    ) -> str:
        state = secrets.token_urlsafe(32)
        with self._lock:
            self._pending[state] = _Pending(
                server,
                code_verifier,
                redirect_uri,
                token_url,
                client_id,
                time.time(),
            )
            self._save()
        return state

    def pop_pending(self, state: str) -> _Pending | None:
        with self._lock:
            pend = self._pending.pop(state, None)
            self._save()
            if pend is None or time.time() - pend.created_ts >= _PENDING_TTL:
                return None
            return pend

    def save_tokens(
        self,
        server: str,
        token_response: dict[str, Any],
        *,
        token_url: str,
        client_id: str,
    ) -> None:
        with self._lock:
            prior = self._tokens.get(server)
            refresh = str(
                token_response.get("refresh_token") or (prior.refresh_token if prior else "")
            )
            self._tokens[server] = _Tokens(
                access_token=str(token_response.get("access_token", "")),
                refresh_token=refresh,
                expires_at=time.time() + float(token_response.get("expires_in", 3600)),
                token_url=token_url,
                client_id=client_id,
            )
            self._save()

    def bearer(self, server: str) -> str | None:
        with self._lock:
            tok = self._tokens.get(server)
            if tok is None or not tok.access_token:
                return None
            stale = (
                tok.expires_at
                and tok.expires_at - time.time() < _REFRESH_SKEW
                and tok.refresh_token
                and tok.token_url
            )
            if stale:
                try:
                    resp = refresh_access(
                        token_url=tok.token_url,
                        refresh_token=tok.refresh_token,
                        client_id=tok.client_id,
                    )
                except Exception:  # noqa: BLE001 — fall back to existing token on refresh failure
                    return tok.access_token
                self.save_tokens(server, resp, token_url=tok.token_url, client_id=tok.client_id)
                tok = self._tokens.get(server)
            return tok.access_token if tok else None

    def get_client(self, issuer: str) -> str | None:
        with self._lock:
            return self._clients.get(issuer)

    def save_client(self, issuer: str, client_id: str) -> None:
        with self._lock:
            self._clients[issuer] = client_id
            self._save()

    def has_tokens(self, server: str) -> bool:
        with self._lock:
            return server in self._tokens

    def forget(self, server: str) -> bool:
        with self._lock:
            if server not in self._tokens:
                return False
            del self._tokens[server]
            self._save()
            return True


# ── Module singleton ─────────────────────────────────────

_GLOBAL: MCPOAuthStore | None = None
_GLOBAL_LOCK = threading.Lock()


def get_oauth_store() -> MCPOAuthStore:
    global _GLOBAL
    if _GLOBAL is None:
        with _GLOBAL_LOCK:
            if _GLOBAL is None:
                _GLOBAL = MCPOAuthStore()
    return _GLOBAL


def bearer_for_server(name: str) -> str | None:
    """Valid access token for ``name`` (refreshing if needed), or ``None``.

    Never raises — the MCP transport calls this on every connect and must
    degrade to no-auth when there's no token / the store is unavailable.
    """
    try:
        return get_oauth_store().bearer(name)
    except Exception:  # noqa: BLE001
        return None


def reset_oauth_store_for_tests() -> None:
    global _GLOBAL
    with _GLOBAL_LOCK:
        _GLOBAL = None


__all__ = [
    "MCPOAuthStore",
    "bearer_for_server",
    "build_authorize_url",
    "exchange_code",
    "get_oauth_store",
    "new_pkce",
    "refresh_access",
    "reset_oauth_store_for_tests",
]

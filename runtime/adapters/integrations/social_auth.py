"""Google/GitHub sign-in; provider tokens never leave the server."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sqlite3
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from runtime.safety.auth.identity import Identity, encode_jwt_hs256
from runtime.safety.auth.principal import set_session_cookie

PROVIDERS = {
    "google": (
        "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token",
        "openid email profile",
    ),
    "github": (
        "https://github.com/login/oauth/authorize",
        "https://github.com/login/oauth/access_token",
        "read:user user:email",
    ),
}


def safe_return_to(value: str) -> str:
    return (
        value
        if value.startswith("/")
        and not value.startswith("//")
        and not any(c in value for c in "\\\r\n")
        else "/workspace/realtime/new"
    )


def create_social_auth_router(
    *, identity_store, jwt_secret, data_dir: Path, jwt_issuer=None, jwt_audience=None
):
    router = APIRouter(prefix="/api/auth/social", tags=["auth"])
    origin = os.getenv("ECHO_AUTH_PUBLIC_URL", "http://localhost:3310").rstrip("/")
    parsed = urlsplit(origin)
    valid_origin = bool(
        parsed.netloc
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and parsed.path in {"", "/"}
        and (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})
        )
    )
    flows: OrderedDict[str, dict] = OrderedDict()
    database = Path(data_dir) / "social-identities.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS users (actor TEXT PRIMARY KEY, provider TEXT NOT NULL, email TEXT, name TEXT)"
        )
        for actor, provider, email, name in db.execute(
            "SELECT actor, provider, email, name FROM users"
        ):
            if identity_store.get(actor) is None:
                identity_store.add(
                    Identity(
                        actor_id=actor,
                        roles=("user",),
                        metadata={"provider": provider, "email": email, "display_name": name},
                    )
                )

    def credentials(provider):
        return os.getenv(f"ECHO_{provider.upper()}_CLIENT_ID", ""), os.getenv(
            f"ECHO_{provider.upper()}_CLIENT_SECRET", ""
        )

    def enabled(provider):
        return bool(
            valid_origin
            and jwt_secret
            and identity_store is not None
            and all(credentials(provider))
        )

    @router.get("/providers")
    async def providers():
        return {
            "providers": [{"id": provider, "enabled": enabled(provider)} for provider in PROVIDERS]
        }

    @router.get("/{provider}/start")
    async def start(provider: str, return_to: str = "/workspace/realtime/new"):
        if provider not in PROVIDERS or not enabled(provider):
            raise HTTPException(503, "此登录方式尚未配置，请使用邮箱登录。")
        now = time.monotonic()
        for state in list(flows):
            if flows[state]["expires"] < now:
                flows.pop(state)
        if len(flows) >= 1000:
            raise HTTPException(429, "登录请求较多，请稍后重试。")
        state, binding, verifier = (
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(48),
        )
        flows[state] = {
            "provider": provider,
            "binding": binding,
            "verifier": verifier,
            "return_to": safe_return_to(return_to),
            "expires": now + 600,
        }
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        params = {
            "client_id": credentials(provider)[0],
            "redirect_uri": f"{origin}/api/auth/social/{provider}/callback",
            "response_type": "code",
            "scope": PROVIDERS[provider][2],
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        response = RedirectResponse(
            PROVIDERS[provider][0] + "?" + urlencode(params), status_code=302
        )
        response.set_cookie(
            "echo_oauth_flow",
            binding,
            max_age=600,
            httponly=True,
            secure=parsed.scheme == "https",
            samesite="lax",
            path="/api/auth/social",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/{provider}/callback")
    async def callback(
        provider: str, request: Request, state: str = "", code: str = "", error: str = ""
    ):
        flow = flows.get(state)
        if (
            not flow
            or flow["provider"] != provider
            or flow["expires"] < time.monotonic()
            or not secrets.compare_digest(
                flow["binding"], request.cookies.get("echo_oauth_flow", "")
            )
        ):
            raise HTTPException(400, "登录会话已失效，请重新开始登录。")
        flows.pop(state)
        failed = RedirectResponse(
            f"{origin}/#/login?"
            + urlencode(
                {"social_error": "登录未完成，请重试或使用邮箱。", "returnTo": flow["return_to"]}
            ),
            status_code=303,
        )
        failed.delete_cookie("echo_oauth_flow", path="/api/auth/social")
        if error or not code:
            return failed
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                token_response = await client.post(
                    PROVIDERS[provider][1],
                    data={
                        "client_id": credentials(provider)[0],
                        "client_secret": credentials(provider)[1],
                        "code": code,
                        "code_verifier": flow["verifier"],
                        "grant_type": "authorization_code",
                        "redirect_uri": f"{origin}/api/auth/social/{provider}/callback",
                    },
                    headers={"Accept": "application/json"},
                )
                token_response.raise_for_status()
                token = token_response.json()["access_token"]
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "User-Agent": "Echo-SignIn",
                }
                profile_response = await client.get(
                    "https://openidconnect.googleapis.com/v1/userinfo"
                    if provider == "google"
                    else "https://api.github.com/user",
                    headers=headers,
                )
                profile_response.raise_for_status()
                profile = profile_response.json()
                subject = str(profile.get("sub" if provider == "google" else "id") or "")
                email = profile.get("email")
                if provider == "google":
                    if profile.get("email_verified") is not True:
                        raise ValueError("unverified email")
                else:
                    emails_response = await client.get(
                        "https://api.github.com/user/emails", headers=headers
                    )
                    emails_response.raise_for_status()
                    email = next(
                        (
                            row["email"]
                            for row in emails_response.json()
                            if row.get("primary") and row.get("verified")
                        ),
                        None,
                    )
                if not subject or not email:
                    raise ValueError("missing verified identity")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return failed
        # Provider subject is authoritative; never auto-link accounts by email.
        actor = f"{provider}:" + hashlib.sha256(subject.encode()).hexdigest()[:32]
        name = str(profile.get("name") or profile.get("login") or email)[:128]
        with sqlite3.connect(database) as db:
            db.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?) ON CONFLICT(actor) DO UPDATE SET email=excluded.email, name=excluded.name",
                (actor, provider, email, name),
            )
        if identity_store.get(actor) is None:
            identity_store.add(
                Identity(
                    actor_id=actor,
                    roles=("user",),
                    metadata={"provider": provider, "email": email, "display_name": name},
                )
            )
        now = int(time.time())
        claims = {"sub": actor, "iat": now, "exp": now + 604800, "provider": provider}
        if jwt_issuer:
            claims["iss"] = jwt_issuer
        if jwt_audience:
            claims["aud"] = jwt_audience
        response = RedirectResponse(f"{origin}/#{flow['return_to']}", status_code=303)
        set_session_cookie(
            response, request, encode_jwt_hs256(claims, secret=jwt_secret), max_age=604800
        )
        response.delete_cookie("echo_oauth_flow", path="/api/auth/social")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return router

"""Private bearer credentials for invitation-protected A2A endpoints."""

from __future__ import annotations

import os
import uuid
from urllib.parse import urlsplit

import httpx


def save_token(token: str) -> str:
    from runtime.sensing.gateway import a2a_router

    if (
        not isinstance(token, str)
        or not 16 <= len(token) <= 4096
        or any(c in token for c in "\r\n")
    ):
        raise ValueError("远程访问凭证格式无效")
    root = a2a_router._REGISTRY_DIR / "credentials"
    root.mkdir(parents=True, exist_ok=True)
    ref = uuid.uuid4().hex
    fd = os.open(root / ref, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
    return ref


def read_token(entry: dict) -> str | None:
    from runtime.sensing.gateway import a2a_router

    ref = entry.get("credential_ref")
    if not ref:
        return None
    if not isinstance(ref, str) or len(ref) != 32 or any(c not in "0123456789abcdef" for c in ref):
        raise ValueError("远程凭证引用无效")
    path = a2a_router._REGISTRY_DIR / "credentials" / ref
    if path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError("远程凭证不可用")
    return path.read_text(encoding="utf-8").strip()


async def remote_client(entry: dict, *, token: str | None = None):
    from a2a.client import ClientConfig, ClientFactory

    token = token or read_token(entry)
    url = str(entry["base_url"])
    if not token:
        return await ClientFactory().create_from_url(url)
    parsed = urlsplit(url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("带凭证的远程角色需要 HTTPS 或本机 SSH 隧道")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("远程角色地址不能包含凭证或查询参数")
    http = httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token}, timeout=330, follow_redirects=False
    )

    def verify(card):
        for interface in card.supported_interfaces:
            target = urlsplit(interface.url)
            if (target.scheme, target.netloc) != (parsed.scheme, parsed.netloc):
                raise ValueError("远程角色公布了不同源的接口")

    try:
        client = await ClientFactory(ClientConfig(httpx_client=http)).create_from_url(
            url, relative_card_path=".well-known/agent-card.json", signature_verifier=verify
        )
    except BaseException:
        await http.aclose()
        raise

    class OwnedClient:
        def __getattr__(self, name):
            return getattr(client, name)

        async def close(self):
            try:
                await client.close()
            finally:
                await http.aclose()

    return OwnedClient()

"""Read an invited hotspot's models from the receiving Echo backend."""

import json
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException


def normalize_hotspot_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        _ = parsed.port  # Access validates malformed and out-of-range ports.
    except ValueError:
        raise HTTPException(400, "热点地址或端口无效") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
    ):
        raise HTTPException(400, "请填写以 /v1 结尾的热点地址，不要在地址中包含凭证")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(400, "远程热点请使用 HTTPS，或先建立本地 SSH 隧道")
    return value.strip().rstrip("/")


async def discover_hotspot(body: dict, *, transport=None) -> dict:
    base_url = normalize_hotspot_url(str(body.get("base_url") or ""))
    token = str(body.get("token") or "").strip()
    if (
        not token
        or len(token) > 4096
        or not token.isascii()
        or any(not 33 <= ord(c) <= 126 for c in token)
    ):
        raise HTTPException(400, "请填写有效的邀请凭证")
    try:
        async with (
            httpx.AsyncClient(
                timeout=45, trust_env=False, follow_redirects=False, transport=transport
            ) as client,
            client.stream(
                "GET", base_url + "/models", headers={"Authorization": "Bearer " + token}
            ) as response,
        ):
            if response.status_code != 200:
                detail = (
                    "邀请无效、已过期或已撤销"
                    if response.status_code in {401, 403}
                    else "热点未开启、额度受限或模型服务不可用"
                )
                raise HTTPException(502, detail)
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 1024 * 1024:
                    raise HTTPException(502, "热点模型列表过大")
        payload = json.loads(content)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError
        models = list(
            dict.fromkeys(
                row["id"]
                for row in rows[:1000]
                if isinstance(row, dict)
                and isinstance(row.get("id"), str)
                and 0 < len(row["id"]) <= 200
                and not any(ord(c) < 32 for c in row["id"])
            )
        )
        if not models:
            raise ValueError
        return {"base_url": base_url, "models": models, "wire_api": "responses"}
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "无法读取热点模型，请检查提供方服务和本地隧道") from None

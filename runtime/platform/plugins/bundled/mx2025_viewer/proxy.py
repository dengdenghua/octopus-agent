"""MX2025 同源反向代理 —— 让 https://mx2025.hhhuu.com 通过我们的 origin 访问。

照搬 paper_trading/proxy.py 的模式,但去掉登录态注入(用户自己在页面内登录)。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

if TYPE_CHECKING:
    pass

_logger = logging.getLogger(__name__)

# 允许代理的上游路径前缀白名单 —— 防止变成任意 URL 转发器
_ALLOWED_PREFIXES = ("", "pages", "assets", "static", "api", "img", "uni")


def _safe_upstream_path(raw: str) -> str | None:
    """验证并清理上游路径,防止路径穿越和越权访问。

    Returns:
        清理后的安全路径;若不合法返回 None。
    """
    clean = raw.strip().lstrip("/")
    # 拒绝路径穿越
    if ".." in clean.split("/"):
        return None
    # 白名单前缀检查
    if not any(clean.startswith(prefix) or clean == prefix.rstrip("/") for prefix in _ALLOWED_PREFIXES):
        return None
    return clean


def register_origin_proxy(router: APIRouter, *, base_url: str) -> bool:
    """注册同源反向代理路由,把上游站点挂到 /origin/* 下。

    Args:
        router: FastAPI 路由器(prefix 应为 /api/plugins/mx2025_viewer)
        base_url: 上游完整 URL(如 https://mx2025.hhhuu.com)

    Returns:
        是否成功注册
    """
    origin = base_url.rstrip("/")

    # HTTP 代理路由 —— 每个 method 一条,避免 operation_id 重复
    for method in ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]:

        async def proxy_http(request: Request, upstream_path: str) -> Response:
            safe_path = _safe_upstream_path(upstream_path)
            if safe_path is None:
                return Response(content="Forbidden path", status_code=404)

            target = f"{origin}/{safe_path}"
            if request.url.query:
                target += f"?{request.url.query}"

            # 请求头白名单(与 storage_proxy_router 一致,但多加 cookie 以支持会话)
            allowed_req_headers = {
                "accept",
                "accept-encoding",
                "accept-language",
                "cache-control",
                "content-type",
                "range",
                "referer",
                "user-agent",
                "cookie",  # 允许 cookie 以支持用户登录态
            }
            headers = {
                k: v for k, v in request.headers.items() if k.lower() in allowed_req_headers
            }
            # 改写 referer 为上游 origin,避免上游 CSRF 检查拒绝
            if "referer" in headers:
                headers["referer"] = origin + "/"

            client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=5.0),
                follow_redirects=False,
                trust_env=False,  # 不走系统代理(与 paper_trading WS 一致)
            )
            try:
                body = await request.body() if request.method in {"POST", "PUT", "PATCH"} else None
                upstream = client.build_request(
                    method=request.method, url=target, headers=headers, content=body
                )
                upstream_resp = await client.send(upstream, stream=True)

                # 响应头白名单(剔除 CSP/X-Frame-Options,允许 iframe 嵌入)
                allowed_resp_headers = {
                    "content-type",
                    "content-length",
                    "content-encoding",
                    "content-range",
                    "accept-ranges",
                    "cache-control",
                    "etag",
                    "last-modified",
                    "set-cookie",  # 透传 cookie 以支持会话
                }
                resp_headers = {
                    k: v
                    for k, v in upstream_resp.headers.items()
                    if k.lower() in allowed_resp_headers
                }

                # 流式返回
                async def stream_body():
                    try:
                        async for chunk in upstream_resp.aiter_raw():
                            yield chunk
                    finally:
                        await upstream_resp.aclose()
                        await client.aclose()

                return StreamingResponse(
                    stream_body(),
                    status_code=upstream_resp.status_code,
                    headers=resp_headers,
                )

            except (httpx.HTTPError, OSError) as exc:
                _logger.warning("mx2025_viewer proxy failed: %s", exc)
                await client.aclose()
                return Response(
                    content=f"Upstream error: {exc}",
                    status_code=503,
                    headers={"Retry-After": "10"},
                )

        router.add_api_route(
            "/origin/{upstream_path:path}",
            proxy_http,
            methods=[method],
            operation_id=f"mx2025_viewer_proxy_{method.lower()}",
        )

    _logger.info("mx2025_viewer origin proxy registered: %s/origin/*", router.prefix)
    return True

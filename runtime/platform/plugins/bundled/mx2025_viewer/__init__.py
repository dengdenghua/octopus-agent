"""MX技术小筑查看器插件 — fail-closed 的可选同源代理。"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from runtime.platform.plugins.plugin_base import ModulePlugin

from .proxy import secure_upstream_origin

_logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://mx2025.hhhuu.com"
_NOTICE_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'self'"
)
_VIEWER_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)


def _explicitly_enabled(config: dict[str, Any], key: str) -> bool:
    """Security-sensitive switches accept only the boolean value ``true``."""
    return config.get(key) is True


def _page_headers(*, viewer: bool = False) -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": _VIEWER_CSP if viewer else _NOTICE_CSP,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
    }


def _notice_page(*, authenticated_host: bool, base_url: str) -> str:
    if authenticated_host:
        title = "MX技术小筑在当前部署中不可用"
        detail = (
            "当前实例已开启身份认证。为避免第三方脚本获得应用同源权限，"
            "同源代理及其网络路由均已安全关闭。"
        )
        action = "请直接访问可信上游，或仅在隔离的单用户本地实例中启用此功能。"
    else:
        title = "MX技术小筑同源代理未开启"
        detail = (
            "该功能默认关闭。只有同时设置 proxy_origin: true 和 "
            "allow_same_origin_third_party_scripts: true，并配置 HTTPS 上游后才会启用。"
        )
        origin = secure_upstream_origin(base_url) or DEFAULT_BASE_URL
        safe_origin = html.escape(origin, quote=True)
        action = (
            "第三方脚本会使用本应用的 origin 权限；生产或多用户部署不得开启。"
            f'也可以<a href="{safe_origin}" target="_blank" rel="noreferrer noopener">'
            "直接打开上游站点</a>。"
        )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
body{{font-family:system-ui,sans-serif;margin:0;background:#10131f;color:#e6e9f0}}
.card{{max-width:680px;margin:12vh auto;padding:28px;border:1px solid #39415f;
border-radius:14px;background:#1a1d33;line-height:1.8}}h1{{font-size:22px;margin-top:0}}
p{{color:#aeb7ca}}code{{color:#f0b90b}}a{{color:#f0b90b}}
</style></head><body><main class="card"><h1>{title}</h1>
<p>{detail}</p><p>{action}</p></main></body></html>"""


class MX2025ViewerPlugin(ModulePlugin):
    """MX技术小筑查看器；危险同源能力默认关闭。"""

    name = "mx2025_viewer"
    display_name = "MX技术小筑"
    version = "0.2.0"
    description = "MX技术小筑网站查看器 — 可选的本地同源代理，默认安全关闭"

    def __init__(self) -> None:
        super().__init__()
        self.base_url = DEFAULT_BASE_URL
        self.proxy_origin = False
        self.allow_same_origin_third_party_scripts = False
        self._authenticated_host = False

    def on_load(self, ctx: Any) -> None:
        cfg = dict(ctx.config or {})
        self.base_url = str(cfg.get("base_url") or DEFAULT_BASE_URL)
        self.proxy_origin = False
        self.allow_same_origin_third_party_scripts = _explicitly_enabled(
            cfg,
            "allow_same_origin_third_party_scripts",
        )
        app = getattr(ctx, "fastapi_app", None)
        self._authenticated_host = bool(
            app is not None and getattr(getattr(app, "state", None), "octopus_require_auth", False)
        )

        proxy_requested = _explicitly_enabled(cfg, "proxy_origin")
        secure_upstream = bool(secure_upstream_origin(self.base_url))
        self.proxy_origin = (
            proxy_requested
            and self.allow_same_origin_third_party_scripts
            and secure_upstream
            and not self._authenticated_host
        )
        if proxy_requested and not self.proxy_origin:
            reasons = []
            if not self.allow_same_origin_third_party_scripts:
                reasons.append("missing independent risk acceptance")
            if not secure_upstream:
                reasons.append("upstream is not valid HTTPS")
            if self._authenticated_host:
                reasons.append("host authentication is enabled")
            _logger.warning("mx2025_viewer proxy disabled (%s)", "; ".join(reasons))
        super().on_load(ctx)

    def register_routes(self) -> None:
        if self.ctx is None or self.ctx.fastapi_app is None:
            return

        app = self.ctx.fastapi_app
        router = APIRouter(prefix=f"/api/plugins/{self.name}", tags=[self.name])

        # Authenticated hosts expose exactly one inert page. No origin HTTP or
        # WebSocket route is registered, even if both local switches are true.
        if self._authenticated_host:

            @router.get("/page", response_class=HTMLResponse)
            def authenticated_notice() -> HTMLResponse:
                return HTMLResponse(
                    _notice_page(authenticated_host=True, base_url=self.base_url),
                    headers=_page_headers(),
                )

            app.include_router(router)
            return

        proxy_mounted = False
        if self.proxy_origin:
            from .proxy import register_origin_proxy

            proxy_mounted = register_origin_proxy(router, base_url=self.base_url)
            self.proxy_origin = proxy_mounted

        @router.get("/page", response_class=HTMLResponse)
        def viewer_page() -> HTMLResponse:
            if not proxy_mounted:
                return HTMLResponse(
                    _notice_page(authenticated_host=False, base_url=self.base_url),
                    headers=_page_headers(),
                )
            page_path = Path(self.ctx.plugin_dir) / "page" / "index.html"
            try:
                content = page_path.read_text(encoding="utf-8")
            except OSError as exc:
                _logger.warning("mx2025_viewer page unavailable (%s)", type(exc).__name__)
                return HTMLResponse(
                    _notice_page(authenticated_host=False, base_url=self.base_url),
                    status_code=503,
                    headers=_page_headers(),
                )
            return HTMLResponse(content, headers=_page_headers(viewer=True))

        app.include_router(router)


__all__ = ["MX2025ViewerPlugin"]

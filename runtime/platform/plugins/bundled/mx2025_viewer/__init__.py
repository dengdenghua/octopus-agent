"""MX技术小筑查看器插件 - 同源反向代理。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from runtime.platform.plugins.plugin_base import ModulePlugin

_logger = logging.getLogger(__name__)


class MX2025ViewerPlugin(ModulePlugin):
    """MX技术小筑网站查看器 —— 同源反代 https://mx2025.hhhuu.com。"""

    name = "mx2025_viewer"
    display_name = "MX技术小筑"
    version = "0.1.0"
    description = "MX技术小筑网站查看器 — 通过同源反向代理访问 https://mx2025.hhhuu.com"

    def __init__(self) -> None:
        super().__init__()
        self.base_url: str = ""

    def on_load(self, ctx: Any) -> None:
        """插件加载时调用。"""
        cfg = dict(ctx.config or {})
        self.base_url = str(cfg.get("base_url", "https://mx2025.hhhuu.com"))
        _logger.info("mx2025_viewer plugin loaded, base_url=%s", self.base_url)
        # 必须调用父类 on_load,它会自动触发 register_routes()
        super().on_load(ctx)

    def register_routes(self) -> None:
        """注册路由。"""
        _logger.info("mx2025_viewer register_routes called, ctx=%s, app=%s",
                     self.ctx, self.ctx.fastapi_app if self.ctx else None)
        if self.ctx is None or self.ctx.fastapi_app is None:
            _logger.warning("mx2025_viewer: no FastAPI context, skipping route registration")
            return

        from runtime.platform.plugins.bundled.mx2025_viewer import proxy

        router = APIRouter(prefix=f"/api/plugins/{self.name}")

        # 同源反向代理路由
        proxy.register_origin_proxy(router, base_url=self.base_url)

        # 页面路由
        @router.get("/page", operation_id=f"{self.name}_page")
        async def get_page() -> HTMLResponse:
            page_path = Path(__file__).parent / "page" / "index.html"
            html = page_path.read_text(encoding="utf-8")
            return HTMLResponse(content=html)

        self.ctx.fastapi_app.include_router(router)
        _logger.info("mx2025_viewer routes registered")


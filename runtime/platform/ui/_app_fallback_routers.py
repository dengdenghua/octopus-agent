"""Live model-dispatcher fallback routers for the Web UI app.

Extracted from ``app.py`` during the god-file reduction. This attaches
the oct gateway fallback to the live model dispatcher so the
planner can route LLM calls without a named/BYO model.
"""

from __future__ import annotations

from typing import Any


def _attach_oct_fallback_router(
    *,
    stack: Any,
    oct_config: Any,
    link_store: Any,
) -> None:
    """让 live model dispatcher 在无具名/BYO 模型时走 oct 网关计费(actor 感知)。

    fallback = OctFallbackRouter(登录有 link → OctModelRouter 网关计费;否则 → 自配模型)。
    登录用户的 agent LLM 用量计入统一积分池;guest/未配置仍走自配模型,不回退 P0。
    """

    def configure(planner: Any) -> None:
        _configure_oct_fallback_router(
            planner=planner, oct_config=oct_config, link_store=link_store
        )

    if hasattr(type(stack), "configure_native_planner"):
        stack.configure_native_planner(configure)
    else:
        configure(getattr(stack, "planner", None))


def _configure_oct_fallback_router(*, planner: Any, oct_config: Any, link_store: Any) -> None:
    dispatcher = getattr(planner, "router", None)
    if dispatcher is None or not hasattr(dispatcher, "set_fallback"):
        return
    try:
        from runtime.sensing.model_router.models import UnconfiguredModelRouter
        from runtime.sensing.model_router.oct_router import OctFallbackRouter, OctModelRouter
        from runtime.sensing.model_router.openai_router import (
            build_fallback_router_from_custom_models,
        )

        planner_model = getattr(planner, "planner_model", None)
        self_fallback = (
            build_fallback_router_from_custom_models(planner_model) or UnconfiguredModelRouter()
        )
        oct_router = OctModelRouter(
            link_store=link_store,
            base_url=getattr(oct_config, "base_url", None) or "https://api.echo-age.com",
            default_model=getattr(oct_config, "default_model", None) or "qwen3.5-flash",
            timeout_seconds=getattr(oct_config, "llm_timeout_seconds", None) or 120.0,
        )
        dispatcher.set_fallback(
            OctFallbackRouter(
                oct_router=oct_router, self_router=self_fallback, link_store=link_store
            )
        )
        dispatcher.official_router = oct_router
    except (ImportError, AttributeError, TypeError):
        return

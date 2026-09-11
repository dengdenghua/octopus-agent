"""Host policy for optional background model calls, separate from engines."""

from __future__ import annotations

from typing import Any


class SharedExecutionRouter:
    """Keep explicit official and API selections on their chosen service."""

    def __init__(self, router: Any) -> None:
        self.router = router

    def has(self, model: str) -> bool:
        if model.startswith("official/"):
            return bool(model.removeprefix("official/")) and getattr(self.router, "official_router", None) is not None
        has = getattr(self.router, "has", None)
        return bool(has(model)) if callable(has) else callable(getattr(self.router, "call", None))

    @property
    def default_model(self) -> Any:
        return getattr(self.router, "default_model", None)

    def _route(self, request: Any) -> tuple[Any, Any]:
        if request.model.startswith("official/"):
            router = getattr(self.router, "official_router", None)
            if router is None:
                raise ValueError("Official model service is unavailable")
            return router, request.model_copy(update={"model": request.model.removeprefix("official/")})
        if not self.has(request.model):
            raise ValueError("Selected API model has no exact route")
        return self.router, request

    def call(self, request: Any) -> Any:
        router, selected = self._route(request)
        return router.call(selected)

    def call_stream(self, request: Any) -> Any:
        router, selected = self._route(request)
        yield from router.call_stream(selected)


def native_model_services(stack: Any) -> tuple[Any | None, str | None]:
    """Bind native compatibility services without constructing a deferred planner.

    The returned router retains normal behavior when actually called. Older
    stack integrations continue to supply their services through ``planner``.
    """
    if hasattr(type(stack), "native_router"):
        return stack.native_router, stack.native_planner_model
    planner = getattr(stack, "planner", None)
    return getattr(planner, "router", None), getattr(planner, "planner_model", None)


def background_model_calls_enabled(stack: Any) -> bool:
    execution = getattr(getattr(stack, "config", None), "execution", None)
    selected = getattr(execution, "background_model_calls", None)
    if isinstance(selected, bool):
        return selected
    # External members do not imply authorization to also run a host model
    # in unattended jobs. Legacy/native hosts retain their existing policy.
    return getattr(execution, "member_engine", "octopus") != "opencode"


def background_model_router(stack: Any) -> Any | None:
    if not background_model_calls_enabled(stack):
        return None
    missing = object()
    router = getattr(stack, "background_router", missing)
    if router is not missing:
        return router
    return getattr(getattr(stack, "planner", None), "router", None)

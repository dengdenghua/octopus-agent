from __future__ import annotations

import threading
from typing import Any

from .models import ModelRequest, ModelResponse, ModelRouter
from .rescue_policy import (
    is_retryable_model_error as _is_provider_unavailable_error,
)
from .rescue_policy import (
    model_rescue_quality as _model_rescue_quality,
)


class ModelDispatchRouter(ModelRouter):
    def __init__(
        self,
        *,
        fallback: ModelRouter,
        routes: dict[str, ModelRouter] | None = None,
    ) -> None:
        self._fallback = fallback
        self._routes: dict[str, ModelRouter] = dict(routes or {})
        self._lock = threading.RLock()

    # ─── public registry API ──────────────────────────────────

    def register(self, model_id: str, router: ModelRouter) -> None:
        with self._lock:
            self._routes[model_id] = router

    def unregister(self, model_id: str) -> bool:
        with self._lock:
            return self._routes.pop(model_id, None) is not None

    def list_routes(self) -> list[str]:
        with self._lock:
            return sorted(self._routes.keys())

    def has(self, model_id: str) -> bool:
        with self._lock:
            return model_id in self._routes

    def set_fallback(self, router: ModelRouter) -> None:
        self._fallback = router

    # ─── ModelRouter interface ────────────────────────────────

    def call_stream(self, request: ModelRequest):
        picked = self._resolve(request.model)
        yielded_any = False
        try:
            for evt in picked.call_stream(request):
                yielded_any = True
                yield evt
        except Exception as exc:
            if not yielded_any and _is_provider_unavailable_error(exc):
                rescue = self._pick_provider_rescue(request.model, picked)
                if rescue is not None:
                    rescue_model, rescue_router = rescue
                    rewritten = request.model_copy(update={"model": rescue_model})
                    yield from _stamp_stream_model(
                        rescue_router.call_stream(rewritten),
                        rescue_model,
                    )
                    return
            if yielded_any or picked is not self._fallback:
                raise
            exc_class = type(exc).__name__
            exc_msg = str(exc)
            auth_shaped = (
                "Credentials" in exc_class
                or "Unauthorized" in exc_class
                or "Auth" in exc_class
                or "current_actor" in exc_msg
                or "登录态" in exc_msg
            )
            if not auth_shaped:
                raise
            rescue = self._pick_guest_rescue()
            if rescue is None:
                raise
            try:
                rescue_default = (
                    getattr(
                        rescue,
                        "default_model",
                        None,
                    )
                    or request.model
                )
                rewritten = request.model_copy(
                    update={"model": rescue_default},
                )
                yield from rescue.call_stream(rewritten)
            except (ConnectionError, TimeoutError, TypeError, ValueError):
                raise exc from None

    def call(self, request: ModelRequest) -> ModelResponse:
        picked = self._resolve(request.model)
        try:
            return picked.call(request)
        except Exception as exc:
            if _is_provider_unavailable_error(exc):
                rescue = self._pick_provider_rescue(request.model, picked)
                if rescue is not None:
                    rescue_model, rescue_router = rescue
                    rewritten = request.model_copy(update={"model": rescue_model})
                    response = rescue_router.call(rewritten)
                    return response.model_copy(update={"model": rescue_model})
            # Guest-mode rescue · the default fallback (Molili) requires
            # a logged-in actor. A guest with ONE registered custom
            # model of the same family should just use that. Without
            # this rescue every guest turn that doesn't explicitly
            # set model_name crashes with "no current_actor set".
            #
            # Trigger conditions:
            #   * ``picked`` is the fallback (not a named sub-router)
            #   * the exception looks like an auth/credentials issue
            #   * a rescue candidate is registered
            #
            # We check by class NAME rather than importing the exception
            # to avoid a circular import (molili_router imports from
            # .models, which this module also imports).
            if picked is self._fallback:
                exc_class = type(exc).__name__
                exc_msg = str(exc)
                auth_shaped = (
                    "Credentials" in exc_class
                    or "Unauthorized" in exc_class
                    or "Auth" in exc_class
                    or "current_actor" in exc_msg
                    or "登录态" in exc_msg
                )
                if auth_shaped:
                    rescue = self._pick_guest_rescue()
                    if rescue is not None:
                        # Rewrite request.model so the rescue router
                        # (usually an anthropic sub-router) accepts it.
                        try:
                            rescue_default = (
                                getattr(
                                    rescue,
                                    "default_model",
                                    None,
                                )
                                or request.model
                            )
                            rewritten = request.model_copy(
                                update={"model": rescue_default},
                            )
                            return rescue.call(rewritten)
                        except (ConnectionError, TimeoutError, TypeError, ValueError):  # noqa: BLE001 — rescue router failed; re-raise original error
                            pass
            raise

    def _pick_provider_rescue(
        self,
        model_id: str,
        failed_router: ModelRouter,
    ) -> tuple[str, ModelRouter] | None:
        """Pick the strongest distinct route after an unavailable model.

        A code-specialist outage must not silently downgrade a repair task to
        the first cheap/chat entry in catalog order.  Rank model ids by their
        advertised capability, while preserving registration order between
        equal-quality candidates.  Aliases that point at the same router are
        still deduplicated so an entry registered under both its id and
        concrete model cannot retry itself.
        """
        with self._lock:
            routes = list(self._routes.items())
        if not routes:
            return None
        indexed = list(enumerate(routes))
        ordered = [
            route
            for _idx, route in sorted(
                indexed,
                key=lambda row: (-_model_rescue_quality(row[1][0]), row[0]),
            )
        ]
        seen = {id(failed_router)}
        for name, router in ordered:
            if id(router) in seen:
                continue
            seen.add(id(router))
            return name, router
        return None

    def _pick_guest_rescue(self) -> ModelRouter | None:
        """Pick a registered sub-router suitable as a guest-mode rescue.

        Heuristic: any registered router other than the fallback itself.
        When multiple are registered we prefer anthropic-family by
        inspecting ``provider_name`` on the sub-router or its wrapped
        inner (handles the ``_UpstreamModelRewrite`` wrapper that
        config_router.py uses to bind custom-model aliases). Returns
        None when no rescue is available · caller then re-raises the
        original auth error.
        """
        with self._lock:
            candidates = list(self._routes.values())
        if not candidates:
            return None

        def _provider(r: ModelRouter) -> str:
            # Unwrap one layer · custom-models register the real router
            # inside ``_UpstreamModelRewrite(inner=...)`` and the
            # provider_name lives on inner.
            inner = getattr(r, "_inner", r)
            return str(getattr(inner, "provider_name", "") or "").lower()

        # Stable preference order · anthropic first (most users have
        # claude-mirror configured), then openai-compat, then anything.
        priority = {"anthropic": 0, "openai": 1, "gemini": 2}
        candidates.sort(key=lambda r: priority.get(_provider(r), 99))
        return candidates[0]

    def _resolve(self, model_id: str) -> ModelRouter:
        with self._lock:
            r = self._routes.get(model_id)
        if r is not None:
            return r
        # Try prefix match for `provider/model` style ("openai/gpt-4o" → openai)
        prefix = model_id.split("/", 1)[0] if "/" in model_id else None
        if prefix:
            with self._lock:
                r = self._routes.get(prefix)
            if r is not None:
                return r
        return self._fallback

    # Expose default_model so upstream wrappers (e.g. MultiModelRouter) that
    # rewrite request.model won't clobber user-supplied ids.
    @property
    def default_model(self) -> Any:
        return getattr(self._fallback, "default_model", None)


def _stamp_stream_model(events: Any, model_id: str):
    """Make a transparent rescue visible to downstream sticky routing."""
    for event in events:
        if event.type == "done" and event.final is not None:
            final = event.final.model_copy(update={"model": model_id})
            event = event.model_copy(update={"final": final})
        yield event

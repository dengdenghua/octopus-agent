from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from .credential_pool import AllKeysExhausted, CredentialPool
from .models import (
    ModelRequest,
    ModelResponse,
    ModelRouter,
    ModelStreamEvent,
)


class PooledModelRouter(ModelRouter):
    def __init__(
        self,
        pool: CredentialPool,
        router_factory: Callable[[str], ModelRouter],
        max_retries: int = 3,
    ) -> None:
        self._pool = pool
        self._factory = router_factory
        self._max_retries = max_retries
        self._routers: dict[str, ModelRouter] = {}

    @property
    def pool(self) -> CredentialPool:
        return self._pool

    @property
    def default_model(self) -> Any:
        with self._pool._lock:
            if self._routers:
                first = next(iter(self._routers.values()))
                return getattr(first, "default_model", None)
        return None

    def call(self, request: ModelRequest) -> ModelResponse:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                key = self._pool.acquire()
            except AllKeysExhausted as exc:
                raise AllKeysExhausted(f"all keys exhausted after {attempt} attempts") from exc

            router = self._get_router(key)
            try:
                resp = router.call(request)
                self._pool.report_usage(
                    key,
                    cost_usd=resp.cost.usd,
                )
                return resp
            except Exception as exc:
                last_exc = exc
                if _is_rate_limit_or_auth(exc):
                    self._pool.report_exhausted(key)
                    continue
                raise

        raise last_exc or RuntimeError("unexpected pool exhaustion loop")

    def call_stream(self, request: ModelRequest) -> Iterator[ModelStreamEvent]:
        try:
            key = self._pool.acquire()
        except AllKeysExhausted as exc:
            raise AllKeysExhausted("all keys exhausted") from exc

        router = self._get_router(key)
        total_usd = 0.0
        try:
            for event in router.call_stream(request):
                if event.type == "done" and event.final is not None:
                    total_usd = event.final.cost.usd
                yield event
        except Exception as exc:
            if _is_rate_limit_or_auth(exc):
                self._pool.report_exhausted(key)
            raise
        finally:
            self._pool.report_usage(key, cost_usd=total_usd)

    def _get_router(self, key: str) -> ModelRouter:
        if key not in self._routers:
            self._routers[key] = self._factory(key)
        return self._routers[key]


def _is_rate_limit_or_auth(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return any(
        token in name or token in msg
        for token in (
            "ratelimit",
            "rate_limit",
            "429",
            "quota",
            "exceeded",
            "unauthorized",
            "forbidden",
            "auth",
        )
    )

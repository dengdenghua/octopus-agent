
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from runtime.adapters.instrumentation import trace_stage

from .models import ModelRequest, ModelResponse, ModelRouter

_LOG = logging.getLogger("octopus.eyes.multi_router")


def _is_transient_error(exc: BaseException) -> bool:
    """Heuristic: an error worth retrying on the same provider before
    giving up and trying the next one in the fallback chain.

    Matches by error-class name and message substrings so it works
    whether the anthropic / openai SDK is installed (real exception
    classes) or a duck-typed test client is in use.
    """
    name = type(exc).__name__
    msg = str(exc)
    # Name-based: any vendor SDK's RateLimit / Timeout / Connection.
    if any(needle in name for needle in ("RateLimit", "Timeout", "Connection", "APIConnection")):
        return True
    # 429 / 5xx surfaced via message string (proxies, mirrors, …).
    return any(code in msg for code in (" 429", " 500", " 502", " 503", " 504"))


@dataclass
class RouteAttempt:

    role: str                          # "primary" | "strong" | "fallback[i]"
    model: str                         # Implementation note.
    success: bool
    error: str | None = None
    response_provider: str | None = None


@dataclass
class DispatchRecord:

    prefer_strength: str
    attempts: list[RouteAttempt] = field(default_factory=list)

    @property
    def final_role(self) -> str | None:
        for a in self.attempts:
            if a.success:
                return a.role
        return None


class MultiModelRouter(ModelRouter):

    def __init__(
        self,
        *,
        primary: ModelRouter,
        strong: ModelRouter | None = None,
        fallbacks: list[ModelRouter] | None = None,
        retry_attempts: int = 3,
        retry_base_delay: float = 0.5,
    ) -> None:
        self.primary = primary
        self.strong = strong
        self.fallbacks = list(fallbacks or [])
        self.dispatch_log: list[DispatchRecord] = []
        # Retry config — same provider gets up to ``retry_attempts``
        # tries on a transient failure before falling back to the
        # next provider in the chain. Set to 1 to disable.
        self._retry_attempts = max(1, retry_attempts)
        self._retry_base_delay = retry_base_delay

    def call(self, request: ModelRequest) -> ModelResponse:
        with trace_stage("eyes.multi_router.call") as span:
            span.set_attribute("octopus.multi.prefer", request.prefer_strength)

            chain = self._build_chain(request.prefer_strength)
            record = DispatchRecord(prefer_strength=request.prefer_strength)
            last_error: Exception | None = None

            for role, router in chain:
                sub_request = _rewrite_model_for(request, router)
                try:
                    response = self._call_with_retry(router, sub_request, role)
                except Exception as e:  # noqa: BLE001
                    record.attempts.append(RouteAttempt(
                        role=role, model=sub_request.model,
                        success=False, error=f"{type(e).__name__}: {e}",
                    ))
                    last_error = e
                    continue

                record.attempts.append(RouteAttempt(
                    role=role, model=sub_request.model,
                    success=True, response_provider=response.provider or None,
                ))
                self.dispatch_log.append(record)
                span.set_attribute("octopus.multi.final_role", role)
                span.set_attribute("octopus.multi.attempts", len(record.attempts))
                return response

            self.dispatch_log.append(record)
            span.set_attribute("octopus.multi.failed", True)
            span.set_attribute("octopus.multi.attempts", len(record.attempts))
            if last_error is not None:
                raise last_error
            raise RuntimeError("MultiModelRouter: no routes configured")

    def _call_with_retry(
        self,
        router: ModelRouter,
        request: ModelRequest,
        role: str,
    ) -> ModelResponse:
        """Retry transient errors on a single provider before failing
        over to the next one in the chain.

        Uses ``RetryPolicy`` so backoff + jitter is consistent with
        every other retryable boundary in the system.
        """
        if self._retry_attempts <= 1:
            return router.call(request)

        from runtime.platform.runtime_policy.retry import RetryPolicy, retry_call

        policy = RetryPolicy(
            on=(),  # use retry_if predicate instead
            retry_if=_is_transient_error,
            attempts=self._retry_attempts,
            base_delay=self._retry_base_delay,
            jitter=0.25,
        )

        def _on_retry(idx: int, exc: BaseException, delay: float) -> None:
            _LOG.info(
                "multi_router retry · role=%s model=%s attempt=%d "
                "exc=%s sleep=%.3fs",
                role, request.model, idx + 1, type(exc).__name__, delay,
            )

        return retry_call(
            router.call, request,
            policy=policy,
            on_retry=_on_retry,
        )

    # ─── internals ───────────────────────────────────

    def _build_chain(self, prefer: str) -> list[tuple[str, ModelRouter]]:
        chain: list[tuple[str, ModelRouter]] = []

        if prefer == "strong" and self.strong is not None:
            chain.append(("strong", self.strong))
            chain.append(("primary", self.primary))
        else:
            chain.append(("primary", self.primary))

        for i, fb in enumerate(self.fallbacks):
            chain.append((f"fallback[{i}]", fb))

        seen: set[int] = set()
        deduped: list[tuple[str, ModelRouter]] = []
        for role, router in chain:
            if id(router) in seen:
                continue
            seen.add(id(router))
            deduped.append((role, router))
        return deduped


def _rewrite_model_for(request: ModelRequest, router: ModelRouter) -> ModelRequest:
    default_model: Any = getattr(router, "default_model", None)
    if default_model and isinstance(default_model, str) and default_model != request.model:
        return request.model_copy(update={"model": default_model})
    return request

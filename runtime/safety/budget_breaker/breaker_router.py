from __future__ import annotations

from runtime.adapters.instrumentation import trace_stage
from runtime.platform.models.llm import ModelRequest, ModelResponse, ModelRouter

from .breaker import CircuitBreaker, CircuitOpen


class BreakerModelRouter(ModelRouter):
    def __init__(self, *, inner: ModelRouter, breaker: CircuitBreaker) -> None:
        self.inner = inner
        self.breaker = breaker

    def call(self, request: ModelRequest) -> ModelResponse:
        with trace_stage("ink.breaker.call") as span:
            state_before = self.breaker.state
            span.set_attribute("octopus.breaker.state_before_check", state_before)
            try:
                state = self.breaker.check()
            except CircuitOpen as exc:
                span.set_attribute("octopus.breaker.state_on_entry", state_before)
                span.set_attribute("octopus.breaker.state_after", self.breaker.state)
                span.set_attribute("octopus.breaker.rejected", True)
                span.set_attribute("octopus.breaker.reject_reason", exc.reason)
                raise
            span.set_attribute("octopus.breaker.state_on_entry", state)

            try:
                response = self.inner.call(request)
            except Exception:  # noqa: BLE001 — every inner failure must count toward the breaker
                self.breaker.record(success=False)
                raise

            cost_usd = response.cost.usd if response.cost else 0.0
            self.breaker.record(success=True, cost_usd=cost_usd)
            span.set_attribute("octopus.breaker.state_after", self.breaker.state)
            return response

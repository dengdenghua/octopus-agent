
from __future__ import annotations

from runtime.adapters.instrumentation import trace_stage
from runtime.platform.models.llm import ModelRequest, ModelResponse, ModelRouter

from .breaker import CircuitBreaker


class BreakerModelRouter(ModelRouter):

    def __init__(self, *, inner: ModelRouter, breaker: CircuitBreaker) -> None:
        self.inner = inner
        self.breaker = breaker

    def call(self, request: ModelRequest) -> ModelResponse:
        with trace_stage("ink.breaker.call") as span:
            state = self.breaker.check()  # Implementation note.
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

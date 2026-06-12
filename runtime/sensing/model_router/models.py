"""Model router types and the mock implementation.

The request/response/message data types and the ``ModelRouter`` ABC now
live in ``runtime.platform.models.llm`` (the shared base layer) so the
kernel / safety / memory packages can use them without depending upward
on ``sensing``. They are re-exported here for backward compatibility —
the ~70 existing ``from runtime.sensing.model_router.models import ...``
sites keep working unchanged.

``MockModelRouter`` stays here because it depends on instrumentation.
"""
from __future__ import annotations

from collections.abc import Callable

from runtime.adapters.instrumentation import record_gen_ai_cost, trace_stage
from runtime.platform.models import CostEntry
from runtime.platform.models.llm import (
    EventType,
    LLMResponseFormatError,
    Message,
    MessageRole,
    ModelRequest,
    ModelResponse,
    ModelRouter,
    ModelStreamEvent,
    ModelStrength,
    ReasoningEffort,
    ToolCall,
    ToolSpec,
    normalize_reasoning_effort,
    thinking_budget_for_effort,
)

__all__ = [
    "EventType",
    "LLMResponseFormatError",
    "Message",
    "MessageRole",
    "MockModelRouter",
    "ModelRequest",
    "ModelResponse",
    "ModelRouter",
    "ModelStreamEvent",
    "ModelStrength",
    "ReasoningEffort",
    "ToolCall",
    "ToolSpec",
    "normalize_reasoning_effort",
    "thinking_budget_for_effort",
]


class MockModelRouter(ModelRouter):

    def __init__(
        self,
        response: str | None = None,
        response_fn: Callable[[ModelRequest], str] | None = None,
        responses_by_model: dict[str, str] | None = None,
        default_input_tokens: int = 100,
        default_output_tokens: int = 50,
    ) -> None:
        self._response = response
        self._response_fn = response_fn
        self._responses_by_model = responses_by_model or {}
        self._default_in = default_input_tokens
        self._default_out = default_output_tokens
        self.call_log: list[ModelRequest] = []

    def call(self, request: ModelRequest) -> ModelResponse:
        self.call_log.append(request)

        with trace_stage(
            "eyes.model_call",
            **{"octopus.model": request.model},
        ) as span:
            if self._response_fn is not None:
                text = self._response_fn(request)
            elif request.model in self._responses_by_model:
                text = self._responses_by_model[request.model]
            elif self._response is not None:
                text = self._response
            else:
                text = self._default_echo(request)

            input_tokens = self._default_in
            output_tokens = max(1, len(text) // 3)

            cost_usd = (input_tokens + output_tokens) * 1e-7
            cost = CostEntry(
                tokens_in=input_tokens,
                tokens_out=output_tokens,
                usd=cost_usd,
            )

            record_gen_ai_cost(
                span,
                system=request.system_provider,
                model=request.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                usd=cost_usd,
            )

            return ModelResponse(
                text=text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                model=request.model,
                provider=request.system_provider,
            )

    @staticmethod
    def _default_echo(request: ModelRequest) -> str:
        for m in reversed(request.messages):
            if m.role == "user":
                return f"mock-echo: {m.content[:80]}"
        return "mock: (no user message)"

"""LLM request/response data types and the router interface.

These were defined in ``sensing/model_router/models.py``, but the
kernel (cerebrum), safety, and memory layers all need the request /
response / message shapes — importing them from ``sensing`` made those
packages depend "upward" on the web/sensing layer (a wrong-way edge the
import-direction linter flags). The types are pure pydantic models that
depend only on ``platform.models.CostEntry``, so they belong in the
shared base layer. ``sensing/model_router/models.py`` re-exports them
for backward compatibility and keeps the concrete ``MockModelRouter``
(which depends on instrumentation) where it was.

Note this lives in the ``platform.models.llm`` *submodule*, not the
``platform.models`` package namespace, so its ``ToolCall`` (an LLM tool
invocation) doesn't collide with ``platform.models.ToolCall`` (an
execution-pipeline call) — two distinct concepts that share a name.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from runtime.platform.models.primitives import CostEntry

MessageRole = Literal["system", "user", "assistant"]


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: MessageRole
    # Content can be a plain string (the common case · user/assistant
    # prose) OR a list of content-block dicts matching Anthropic's
    # structured shape. The list form is required when the turn
    # carries ``tool_use`` / ``tool_result`` blocks: the API rejects
    # a string-content message as the reply to a tool_use-bearing
    # assistant turn.
    #
    # Example list form:
    #   [{"type": "tool_result",
    #     "tool_use_id": "toolu_01...",
    #     "content": "list of files: ..."}]
    #
    # The anthropic_router passes ``content`` through verbatim, so
    # a well-formed list flows to the API unchanged. Providers that
    # don't understand block lists (Molili legacy, Mock) should
    # flatten via ``str(content)`` before building their request.
    content: str | list[dict[str, Any]]


ModelStrength = Literal["default", "strong"]
ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]
_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh"}
_THINKING_BUDGET_BY_EFFORT: dict[ReasoningEffort, int] = {
    "minimal": 1024,
    "low": 1024,
    "medium": 2048,
    "high": 4096,
    "xhigh": 8192,
}


def normalize_reasoning_effort(value: Any) -> ReasoningEffort | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"ultra", "extra_high", "extra-high", "very_high"}:
        normalized = "xhigh"
    if normalized in _REASONING_EFFORTS:
        return cast(ReasoningEffort, normalized)
    return None


def thinking_budget_for_effort(
    effort: ReasoningEffort | None,
    max_tokens: int | None,
) -> int:
    budget = _THINKING_BUDGET_BY_EFFORT.get(effort or "medium", 2048)
    if max_tokens is None:
        return budget
    if max_tokens <= 1280:
        return 1024
    return max(1024, min(budget, max_tokens - 256))


class ToolSpec(BaseModel):
    """One tool definition handed to the model provider's tool-use API.

    The wire shape mirrors the standard ``tools`` param convention:
    ``{name, description, input_schema}`` where input_schema is
    JSON Schema. For Octopus MVP we use a permissive object
    schema · the tool's description carries all the hint text.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
    )


class ToolCall(BaseModel):
    """One tool invocation the model decided to make."""

    model_config = ConfigDict(frozen=True)

    id: str  # Anthropic's tool_use_id · must echo back in tool_result
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ModelRequest(BaseModel):

    model_config = ConfigDict(frozen=True)

    model: str  # "claude-haiku-4-5-20251001" / "mock/always-fail" / ...
    messages: list[Message]
    max_tokens: int | None = Field(default=2048, gt=0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    system_provider: str = "anthropic"  # "anthropic" / "openai" / "mock"
    prefer_strength: ModelStrength = "default"  # Implementation note.
    images_b64: list[str] = Field(default_factory=list)
    # Extended thinking · when True, capable providers (Anthropic Claude
    # 4+, Sonnet 4.6, Opus 4.7) emit a separate `thinking` block that
    # we capture into ``ModelResponse.thinking``. Providers that don't
    # support thinking silently ignore this flag. Anthropic requires
    # ``temperature=1.0`` when thinking is enabled — the router lifts
    # the caller's temperature accordingly, callers don't need to worry.
    enable_thinking: bool = False
    reasoning_effort: ReasoningEffort | None = None
    # Upper bound on tokens the model can spend on thinking. Must be
    # strictly less than ``max_tokens`` (the remainder is the text
    # budget). 1024 is the Anthropic minimum for extended thinking.
    thinking_budget: int = Field(default=1024, ge=1024)
    # Native tool_use catalog. When non-empty, the provider is asked
    # to emit ``tool_use`` content blocks instead of / alongside
    # text. Providers that don't support tool_use (Molili legacy,
    # pre-o1 OpenAI, Mock) silently ignore this field — the caller
    # is responsible for falling back to prose-based skill parsing
    # (ReAct) in that case. Anthropic's constraint: ``tools`` AND
    # ``thinking`` can't be enabled in the same request · the
    # router resolves the conflict by prioritizing tools (the
    # whole point of passing tools is that the caller wants them).
    tools: list[ToolSpec] = Field(default_factory=list)


class ModelResponse(BaseModel):

    model_config = ConfigDict(frozen=True)

    text: str
    # Extended-thinking trace · populated when the provider supports
    # it AND ``ModelRequest.enable_thinking`` was set. Empty string
    # on providers that don't emit thinking blocks (Mock / Molili /
    # OpenAI pre-o1) so downstream UI code can treat "no thinking"
    # and "feature not enabled" uniformly.
    thinking: str = ""
    # Tool invocations the model decided to make. Empty when the
    # model replied with pure text. Consumer is expected to
    # execute each call, send back a ``tool_result`` in the next
    # turn, and loop.
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    # Anthropic prompt-cache telemetry. ``cache_read_tokens`` are
    # input tokens served from the cache (≈ 10% of the usual cost);
    # ``cache_creation_tokens`` are input tokens written to the cache
    # on this turn (≈ 125% of the usual cost, amortized over future
    # reads). Both are 0 on providers without prompt-cache support.
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost: CostEntry = Field(default_factory=CostEntry)
    finish_reason: str = "stop"
    model: str = ""
    provider: str = ""


class LLMResponseFormatError(ValueError):
    pass


# ─── Streaming event schema ────────────────────────────────
#
# Providers that support progressive output (Anthropic SSE, OpenAI
# SSE, DeepSeek, ...) yield a sequence of ``ModelStreamEvent`` from
# ``call_stream()``. The upstream chat-stream gateway consumes them
# and turns each one into an SSE frame to the browser.

EventType = Literal[
    "text_delta", "thinking_delta", "tool_use", "done",
]


class ModelStreamEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: EventType
    delta: str = ""
    # Populated on ``type == "tool_use"`` when the model decided to
    # call a tool · the block has been fully assembled (name + id
    # + complete JSON input) before this event fires, so the
    # consumer can execute it directly without tracking partial
    # input_json_delta frames.
    tool_call: ToolCall | None = None
    # Only populated on ``type == "done"`` events. Carries the
    # aggregated response shape so downstream cost / trace logic
    # gets the same data as the non-streaming ``call()`` path.
    final: ModelResponse | None = None


class ModelRouter(ABC):

    @abstractmethod
    def call(self, request: ModelRequest) -> ModelResponse: ...

    def call_stream(
        self, request: ModelRequest,
    ) -> Iterator[ModelStreamEvent]:
        """Default fallback · wrap ``call()`` as a synthetic stream.

        Providers that can actually stream (Anthropic's
        ``messages.stream()``, OpenAI's SSE, ...) should override
        this with a real delta iterator. The default implementation
        lets every router be consumed by the streaming code path
        uniformly even when the upstream has no streaming API.

        The emitted shape matches a native stream: a thinking_delta
        (if any), a text_delta, and a done event. The consumer
        can't tell the difference, but TTFT is still
        ``full-response`` time for non-streaming providers — no
        magic, just uniform plumbing.
        """
        resp = self.call(request)
        if resp.thinking:
            yield ModelStreamEvent(
                type="thinking_delta", delta=resp.thinking,
            )
        if resp.text:
            yield ModelStreamEvent(type="text_delta", delta=resp.text)
        for call in resp.tool_calls:
            yield ModelStreamEvent(type="tool_use", tool_call=call)
        yield ModelStreamEvent(type="done", final=resp)

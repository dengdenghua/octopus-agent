from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    stream_mode: str = "full"
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    conversation_id: str | None = None
    agent: str | None = None
    context: dict[str, Any] | None = None


class ToolCallFunction(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    type: str = "function"
    function: ToolCallFunction


class ChatCompletionMessage(BaseModel):
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatCompletionMessage | None = None
    delta: dict[str, Any] | None = None
    finish_reason: str | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: Usage
    octopus: dict[str, Any] | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    octopus: dict[str, Any] | None = None

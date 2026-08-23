"""Turn-scoped OpenAI Responses bridge owned by the Octopus host.

Codex speaks the Responses wire protocol, while Octopus already owns the
configured model router and its long-lived provider credentials.  This module
keeps those credentials out of the model-controlled Codex process: one turn
gets one loopback listener and one in-memory bearer token.  The token is bound
to the full authenticated turn scope, expires, rejects logical replays, and is
revoked when the execution session closes.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping, Sequence
from contextlib import nullcontext, suppress
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit
from uuid import uuid4

from runtime.platform.models.llm import (
    Message,
    ModelRequest,
    ModelResponse,
    ToolSpec,
    normalize_reasoning_effort,
    thinking_budget_for_effort,
)
from runtime.platform.process.session import Session, session_scope

from .types import CodexProviderProfile, ConfigurationError

_AUTH_ENV_KEY: Literal["OCTOPUS_CODEX_PROXY_TOKEN"] = "OCTOPUS_CODEX_PROXY_TOKEN"
_MAX_HEADER_BYTES = 64 * 1024
_MAX_BODY_BYTES = 2 * 1024 * 1024
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_REQUESTS = 256
_IGNORED_HISTORY_TYPES = frozenset(
    {
        "compaction",
        "item_reference",
        "reasoning",
        "response_metadata",
    }
)


class ResponsesRouter(Protocol):
    def call(self, request: ModelRequest) -> ModelResponse: ...


class ResponsesProxyError(ConfigurationError):
    """A scoped proxy could not safely translate or serve a request."""


@dataclass(frozen=True, slots=True)
class CodexResponsesScope:
    """Authorization coordinates captured when a Coder turn is admitted."""

    tenant_id: str
    principal_id: str
    thread_id: str
    turn_id: str
    model: str

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "principal_id", "thread_id", "turn_id", "model"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 256
                or any(char in value for char in "\x00\r\n")
            ):
                raise ResponsesProxyError(f"{field_name} must be a bounded safe identifier")
            object.__setattr__(self, field_name, value.strip())


@dataclass(frozen=True, slots=True)
class _ToolProjection:
    name: str
    response_type: Literal["function", "custom", "local_shell"]


class _RequestRejected(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ScopedResponsesProxy:
    """One bounded loopback Responses server for one authenticated turn."""

    def __init__(
        self,
        router: ResponsesRouter,
        *,
        scope: CodexResponsesScope,
        trusted_session: Session | None,
        ttl_s: float = 30.0 * 60.0,
        max_requests: int = _MAX_REQUESTS,
    ) -> None:
        if not callable(getattr(router, "call", None)):
            raise ResponsesProxyError("Octopus model router is unavailable")
        if not 1.0 <= float(ttl_s) <= 4.0 * 60.0 * 60.0 + 120.0:
            raise ResponsesProxyError("Responses proxy TTL is outside the safe range")
        if not 1 <= int(max_requests) <= _MAX_REQUESTS:
            raise ResponsesProxyError("Responses proxy request budget is invalid")
        if trusted_session is not None:
            if trusted_session.actor and trusted_session.actor != scope.principal_id:
                raise ResponsesProxyError("trusted session principal does not match proxy scope")
            metadata = trusted_session.metadata
            trusted_tenant = (
                str(metadata.get("tenant_id") or "").strip()
                if isinstance(metadata, Mapping)
                else ""
            )
            if trusted_tenant and trusted_tenant != scope.tenant_id:
                raise ResponsesProxyError("trusted session tenant does not match proxy scope")
        self._router = router
        self.scope = scope
        self._trusted_session = trusted_session
        self._ttl_s = float(ttl_s)
        self._max_requests = int(max_requests)
        self._server: asyncio.AbstractServer | None = None
        self._profile: CodexProviderProfile | None = None
        self._token: str | None = None
        self._expires_at = 0.0
        self._request_count = 0
        self._seen_requests: set[bytes] = set()
        self._active = False
        self._call_lock = asyncio.Lock()
        self._writers: set[asyncio.StreamWriter] = set()
        self._handlers: set[asyncio.Task[Any]] = set()

    @property
    def provider_profile(self) -> CodexProviderProfile:
        profile = self._profile
        if not self._active or profile is None:
            raise ResponsesProxyError("Responses proxy is not active")
        return profile

    async def __aenter__(self) -> ScopedResponsesProxy:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def start(self) -> CodexProviderProfile:
        if self._active or self._server is not None:
            raise ResponsesProxyError("Responses proxy can only be started once")
        token = secrets.token_urlsafe(48)
        server = await asyncio.start_server(
            self._handle_connection,
            host="127.0.0.1",
            port=0,
            limit=_MAX_BODY_BYTES + _MAX_HEADER_BYTES,
        )
        sockets = server.sockets or ()
        if len(sockets) != 1:
            server.close()
            await server.wait_closed()
            raise ResponsesProxyError("Responses proxy did not bind one loopback socket")
        address = sockets[0].getsockname()
        port = int(address[1])
        try:
            profile = CodexProviderProfile(
                provider_id="octopus_proxy",
                name="Octopus scoped system model",
                base_url=f"http://127.0.0.1:{port}/v1",
                model=self.scope.model,
                auth_env_key=_AUTH_ENV_KEY,
                scoped_bearer_token=token,
            )
        except BaseException:
            server.close()
            await server.wait_closed()
            raise
        self._server = server
        self._token = token
        self._expires_at = time.monotonic() + self._ttl_s
        self._profile = profile
        self._active = True
        return self._profile

    async def close(self) -> None:
        self._active = False
        self._token = None
        self._seen_requests.clear()
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()
        for writer in tuple(self._writers):
            writer.close()
        for writer in tuple(self._writers):
            with suppress(ConnectionError, OSError, RuntimeError):
                await writer.wait_closed()
        pending = {task for task in self._handlers if task is not asyncio.current_task()}
        if pending:
            done, still_pending = await asyncio.wait(pending, timeout=2.0)
            for task in still_pending:
                task.cancel()
            if still_pending:
                await asyncio.gather(*still_pending, return_exceptions=True)
            for task in done:
                task.exception() if not task.cancelled() else None
        self._handlers.clear()
        self._writers.clear()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handlers.add(task)
        self._writers.add(writer)
        try:
            status, headers, payload = await self._process_http(reader, writer)
        except _RequestRejected as exc:
            status, headers, payload = (
                exc.status,
                {"Content-Type": "application/json"},
                _json_bytes({"error": {"message": exc.message, "type": "invalid_request_error"}}),
            )
        except (ConnectionError, OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            return
        except Exception:  # noqa: BLE001 - provider details must never cross the proxy boundary
            status, headers, payload = (
                502,
                {"Content-Type": "application/json"},
                _json_bytes(
                    {"error": {"message": "Octopus model request failed", "type": "server_error"}}
                ),
            )
        try:
            await _write_http_response(writer, status, headers, payload)
        except (ConnectionError, OSError, RuntimeError):
            pass
        finally:
            self._writers.discard(writer)
            if task is not None:
                self._handlers.discard(task)
            writer.close()
            with suppress(ConnectionError, OSError, RuntimeError):
                await writer.wait_closed()

    async def _process_http(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> tuple[int, dict[str, str], bytes]:
        peer = writer.get_extra_info("peername")
        if not isinstance(peer, tuple) or str(peer[0]) not in {"127.0.0.1", "::1"}:
            raise _RequestRejected(403, "Loopback access required")
        raw_head = await reader.readuntil(b"\r\n\r\n")
        if len(raw_head) > _MAX_HEADER_BYTES:
            raise _RequestRejected(431, "Request headers are too large")
        method, target, headers = _parse_headers(raw_head)
        if method != "POST" or urlsplit(target).path not in {"/v1/responses", "/responses"}:
            raise _RequestRejected(404, "Responses endpoint not found")
        if urlsplit(target).query:
            raise _RequestRejected(400, "Responses endpoint does not accept query parameters")
        if headers.get("transfer-encoding") is not None:
            raise _RequestRejected(400, "Chunked request bodies are not supported")
        try:
            content_length = int(headers.get("content-length") or "")
        except ValueError:
            raise _RequestRejected(411, "Content-Length is required") from None
        if not 1 <= content_length <= _MAX_BODY_BYTES:
            raise _RequestRejected(413, "Responses request body is outside the allowed size")
        body = await reader.readexactly(content_length)
        payload = _parse_json_object(body)
        await self._authorize_and_reserve(headers, payload)
        request, projections = responses_payload_to_model_request(
            payload,
            expected_model=self.scope.model,
        )
        async with self._call_lock:
            response = await asyncio.to_thread(self._call_router, request)
        response_object = model_response_to_responses(
            response,
            model=self.scope.model,
            projections=projections,
        )
        if payload.get("stream") is False:
            encoded = _json_bytes(response_object)
            if len(encoded) > _MAX_RESPONSE_BYTES:
                raise ResponsesProxyError("Octopus model response exceeded the proxy limit")
            return 200, {"Content-Type": "application/json"}, encoded
        encoded = _responses_sse(response_object)
        if len(encoded) > _MAX_RESPONSE_BYTES:
            raise ResponsesProxyError("Octopus model response exceeded the proxy limit")
        return (
            200,
            {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
            encoded,
        )

    async def _authorize_and_reserve(
        self,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ) -> None:
        token = self._token
        supplied = headers.get("authorization") or ""
        expected = f"Bearer {token}" if token is not None else ""
        if not expected or not hmac.compare_digest(supplied, expected):
            raise _RequestRejected(401, "Scoped Responses token is invalid")
        if not self._active or time.monotonic() >= self._expires_at:
            raise _RequestRejected(401, "Scoped Responses token has expired")
        if str(payload.get("model") or "").strip() != self.scope.model:
            raise _RequestRejected(403, "Responses model is outside the authorized turn scope")
        canonical = _json_bytes(payload, sort_keys=True)
        fingerprint = hashlib.sha256(canonical).digest()
        if fingerprint in self._seen_requests:
            raise _RequestRejected(409, "Responses request replay was rejected")
        if self._request_count >= self._max_requests:
            raise _RequestRejected(429, "Responses turn request budget was exhausted")
        self._seen_requests.add(fingerprint)
        self._request_count += 1

    def _call_router(self, request: ModelRequest) -> ModelResponse:
        scope = (
            session_scope(self._trusted_session)
            if self._trusted_session is not None
            else nullcontext()
        )
        with scope:
            response = self._router.call(request)
        if not isinstance(response, ModelResponse):
            raise ResponsesProxyError("Octopus model router returned an invalid response")
        return response


def responses_payload_to_model_request(
    payload: Mapping[str, Any],
    *,
    expected_model: str,
) -> tuple[ModelRequest, dict[str, _ToolProjection]]:
    """Translate one bounded Responses request into Octopus' provider-neutral form."""

    model = str(payload.get("model") or "").strip()
    if model != expected_model:
        raise _RequestRejected(403, "Responses model is outside the authorized turn scope")
    messages: list[Message] = []
    images_b64: list[str] = []
    instructions = payload.get("instructions")
    if instructions is not None:
        if not isinstance(instructions, str) or len(instructions) > 200_000:
            raise _RequestRejected(400, "Responses instructions are invalid")
        if instructions.strip():
            messages.append(Message(role="system", content=instructions))
    raw_input = payload.get("input")
    if isinstance(raw_input, str):
        messages.append(Message(role="user", content=raw_input))
    elif isinstance(raw_input, Sequence) and not isinstance(raw_input, (str, bytes, bytearray)):
        _append_input_items(messages, images_b64, list(raw_input))
    else:
        raise _RequestRejected(400, "Responses input must be text or an item list")
    if not messages:
        raise _RequestRejected(400, "Responses input contains no model-visible content")
    projections, tools = _convert_tools(payload.get("tools"))
    max_tokens = _bounded_int(
        payload.get("max_output_tokens"),
        default=4096,
        minimum=1,
        maximum=131_072,
    )
    temperature = _bounded_float(payload.get("temperature"), default=0.0, minimum=0.0, maximum=2.0)
    effort = _reasoning_effort(payload.get("reasoning"))
    thinking_budget = thinking_budget_for_effort(effort, max_tokens)
    tool_choice = payload.get("tool_choice")
    require_tool_use = tool_choice == "required" or (
        isinstance(tool_choice, Mapping)
        and str(tool_choice.get("type") or "").strip() in {"function", "custom"}
    )
    return (
        ModelRequest(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            system_provider="octopus",
            images_b64=images_b64,
            enable_thinking=effort is not None and not tools and max_tokens > 1280,
            reasoning_effort=effort,
            thinking_budget=thinking_budget,
            tools=tools,
            require_tool_use=require_tool_use,
        ),
        projections,
    )


def model_response_to_responses(
    response: ModelResponse,
    *,
    model: str,
    projections: Mapping[str, _ToolProjection],
) -> dict[str, Any]:
    """Build the smallest complete Responses object understood by Codex."""

    response_id = f"resp_{uuid4().hex}"
    output: list[dict[str, Any]] = []
    if response.text:
        output.append(
            {
                "id": f"msg_{uuid4().hex}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": response.text,
                        "annotations": [],
                    }
                ],
            }
        )
    for call in response.tool_calls:
        projection = projections.get(call.name)
        if projection is None:
            raise ResponsesProxyError("Octopus model selected an unadvertised tool")
        call_id = _validated_response_call_id(call.id)
        item_id = f"fc_{uuid4().hex}"
        if projection.response_type == "custom":
            raw_input = call.input.get("input")
            output.append(
                {
                    "id": f"ctc_{uuid4().hex}",
                    "type": "custom_tool_call",
                    "status": "completed",
                    "call_id": call_id,
                    "name": call.name,
                    "input": (
                        raw_input
                        if isinstance(raw_input, str)
                        else json.dumps(call.input, ensure_ascii=False, separators=(",", ":"))
                    ),
                }
            )
        elif projection.response_type == "local_shell":
            action = call.input.get("action", call.input)
            output.append(
                {
                    "id": f"lsc_{uuid4().hex}",
                    "type": "local_shell_call",
                    "status": "completed",
                    "call_id": call_id,
                    "action": action,
                }
            )
        else:
            output.append(
                {
                    "id": item_id,
                    "type": "function_call",
                    "status": "completed",
                    "call_id": call_id,
                    "name": call.name,
                    "arguments": json.dumps(
                        call.input,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            )
    input_tokens = max(0, int(response.input_tokens))
    output_tokens = max(0, int(response.output_tokens))
    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "usage": {
            "input_tokens": input_tokens,
            "input_tokens_details": {
                "cached_tokens": max(0, int(response.cache_read_tokens)),
            },
            "output_tokens": output_tokens,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": input_tokens + output_tokens,
        },
    }


def _append_input_items(
    messages: list[Message],
    images_b64: list[str],
    items: list[Any],
) -> None:
    for raw_item in items:
        if isinstance(raw_item, str):
            messages.append(Message(role="user", content=raw_item))
            continue
        if not isinstance(raw_item, Mapping):
            raise _RequestRejected(400, "Responses input item is invalid")
        item = cast(Mapping[str, Any], raw_item)
        item_type = str(item.get("type") or "").strip()
        if item_type == "message" or (not item_type and item.get("role") is not None):
            _append_message_item(messages, images_b64, item)
        elif item_type in {"function_call", "custom_tool_call", "local_shell_call"}:
            call_id, name, tool_input = _history_tool_call(item_type, item)
            messages.append(
                Message(
                    role="assistant",
                    content=[
                        {
                            "type": "tool_use",
                            "id": call_id,
                            "name": name,
                            "input": tool_input,
                        }
                    ],
                )
            )
        elif item_type in {
            "function_call_output",
            "custom_tool_call_output",
            "local_shell_call_output",
        }:
            call_id = _safe_call_id(item.get("call_id"))
            messages.append(
                Message(
                    role="user",
                    content=[
                        {
                            "type": "tool_result",
                            "tool_use_id": call_id,
                            "content": _flatten_output(item.get("output")),
                        }
                    ],
                )
            )
        elif item_type in _IGNORED_HISTORY_TYPES:
            continue
        else:
            raise _RequestRejected(400, "Responses input item type is unsupported")


def _append_message_item(
    messages: list[Message],
    images_b64: list[str],
    item: Mapping[str, Any],
) -> None:
    raw_role = str(item.get("role") or "user").strip().lower()
    if raw_role in {"developer", "system"}:
        role = "system"
    elif raw_role in {"user", "assistant"}:
        role = raw_role
    else:
        raise _RequestRejected(400, "Responses message role is unsupported")
    content = item.get("content", "")
    if isinstance(content, str):
        if content:
            messages.append(Message(role=role, content=content))  # type: ignore[arg-type]
        return
    if not isinstance(content, Sequence) or isinstance(content, (bytes, bytearray)):
        raise _RequestRejected(400, "Responses message content is invalid")
    text_parts: list[str] = []
    for raw_part in content:
        if not isinstance(raw_part, Mapping):
            raise _RequestRejected(400, "Responses content part is invalid")
        part_type = str(raw_part.get("type") or "").strip()
        if part_type in {"input_text", "output_text", "text"}:
            text = raw_part.get("text")
            if not isinstance(text, str):
                raise _RequestRejected(400, "Responses text content is invalid")
            text_parts.append(text)
        elif part_type in {"input_image", "image_url"}:
            images_b64.append(_decode_inline_image(raw_part))
        elif part_type in {"refusal", "reasoning_text"}:
            text = raw_part.get("refusal", raw_part.get("text", ""))
            if isinstance(text, str) and text:
                text_parts.append(text)
        else:
            raise _RequestRejected(400, "Responses content part type is unsupported")
    if text_parts:
        messages.append(Message(role=role, content="\n".join(text_parts)))  # type: ignore[arg-type]


def _history_tool_call(
    item_type: str,
    item: Mapping[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    call_id = _safe_call_id(item.get("call_id") or item.get("id"))
    if item_type == "function_call":
        name = _safe_tool_name(item.get("name"))
        arguments = item.get("arguments", "{}")
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError:
                parsed = {"input": arguments}
        else:
            parsed = arguments
        tool_input = parsed if isinstance(parsed, dict) else {"input": parsed}
    elif item_type == "custom_tool_call":
        name = _safe_tool_name(item.get("name"))
        raw_input = item.get("input", "")
        tool_input = raw_input if isinstance(raw_input, dict) else {"input": str(raw_input)}
    else:
        name = "local_shell"
        action = item.get("action", {})
        tool_input = {"action": action if isinstance(action, Mapping) else {"input": action}}
    return call_id, name, tool_input


def _convert_tools(raw_tools: Any) -> tuple[dict[str, _ToolProjection], list[ToolSpec]]:
    if raw_tools is None:
        return {}, []
    if not isinstance(raw_tools, Sequence) or isinstance(raw_tools, (str, bytes, bytearray)):
        raise _RequestRejected(400, "Responses tools must be a list")
    if len(raw_tools) > 256:
        raise _RequestRejected(400, "Responses tool catalog is too large")
    projections: dict[str, _ToolProjection] = {}
    tools: list[ToolSpec] = []
    for raw_tool in raw_tools:
        if not isinstance(raw_tool, Mapping):
            raise _RequestRejected(400, "Responses tool entry is invalid")
        tool_type = str(raw_tool.get("type") or "").strip()
        if tool_type == "function":
            name = _safe_tool_name(raw_tool.get("name"))
            schema = raw_tool.get("parameters") or {
                "type": "object",
                "properties": {},
                "additionalProperties": True,
            }
            response_type: Literal["function", "custom", "local_shell"] = "function"
        elif tool_type == "custom":
            name = _safe_tool_name(raw_tool.get("name"))
            schema = {
                "type": "object",
                "properties": {"input": {"type": "string"}},
                "required": ["input"],
                "additionalProperties": False,
            }
            response_type = "custom"
        elif tool_type == "local_shell":
            name = _safe_tool_name(raw_tool.get("name") or "local_shell")
            schema = {
                "type": "object",
                "properties": {"action": {"type": "object", "additionalProperties": True}},
                "required": ["action"],
                "additionalProperties": False,
            }
            response_type = "local_shell"
        else:
            raise _RequestRejected(400, "Responses tool type is unsupported")
        if name in projections:
            raise _RequestRejected(400, "Responses tool names must be unique")
        if not isinstance(schema, Mapping):
            raise _RequestRejected(400, "Responses tool schema is invalid")
        description = raw_tool.get("description")
        projections[name] = _ToolProjection(name, response_type)
        tools.append(
            ToolSpec(
                name=name,
                description=description if isinstance(description, str) else "",
                input_schema=dict(schema),
            )
        )
    return projections, tools


def _reasoning_effort(raw: Any):
    if isinstance(raw, Mapping):
        return normalize_reasoning_effort(raw.get("effort"))
    return normalize_reasoning_effort(raw)


def _decode_inline_image(part: Mapping[str, Any]) -> str:
    raw = part.get("image_url", part.get("url", ""))
    if isinstance(raw, Mapping):
        raw = raw.get("url", "")
    if not isinstance(raw, str):
        raise _RequestRejected(400, "Responses image URL is invalid")
    if raw.startswith(("http://", "https://")):
        raise _RequestRejected(400, "Remote image URLs are not allowed")
    if not raw.startswith("data:image/") or ";base64," not in raw:
        raise _RequestRejected(400, "Responses images must use inline base64 data URLs")
    encoded = raw.split(";base64,", 1)[1]
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise _RequestRejected(400, "Responses inline image is invalid") from None
    if not decoded or len(decoded) > _MAX_IMAGE_BYTES:
        raise _RequestRejected(413, "Responses inline image is outside the allowed size")
    return encoded


def _flatten_output(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                else:
                    parts.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if raw is None:
        return ""
    return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))


def _responses_sse(response: Mapping[str, Any]) -> bytes:
    created = dict(response)
    created["status"] = "in_progress"
    created["output"] = []
    frames: list[tuple[str, dict[str, Any]]] = [
        (
            "response.created",
            {"type": "response.created", "response": created, "sequence_number": 0},
        )
    ]
    sequence = 1
    for index, item in enumerate(cast(list[dict[str, Any]], response["output"])):
        frames.append(
            (
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": index,
                    "item": item,
                    "sequence_number": sequence,
                },
            )
        )
        sequence += 1
    frames.append(
        (
            "response.completed",
            {
                "type": "response.completed",
                "response": dict(response),
                "sequence_number": sequence,
            },
        )
    )
    return b"".join(
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()
        for event, data in frames
    )


def _parse_headers(raw: bytes) -> tuple[str, str, dict[str, str]]:
    try:
        lines = raw[:-4].decode("ascii").split("\r\n")
        method, target, version = lines[0].split(" ", 2)
    except (UnicodeDecodeError, ValueError, IndexError):
        raise _RequestRejected(400, "Malformed HTTP request") from None
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise _RequestRejected(400, "Unsupported HTTP version")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            raise _RequestRejected(400, "Malformed HTTP header")
        name, value = line.split(":", 1)
        normalized = name.strip().lower()
        if not normalized or normalized in headers:
            raise _RequestRejected(400, "Duplicate or empty HTTP header")
        headers[normalized] = value.strip()
    return method, target, headers


def _parse_json_object(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise _RequestRejected(400, "Responses request must be valid JSON") from None
    if not isinstance(payload, dict):
        raise _RequestRejected(400, "Responses request must be a JSON object")
    return payload


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _json_bytes(value: Any, *, sort_keys: bool = False) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=sort_keys,
    ).encode("utf-8")


async def _write_http_response(
    writer: asyncio.StreamWriter,
    status: int,
    headers: Mapping[str, str],
    payload: bytes,
) -> None:
    reason = {
        200: "OK",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        409: "Conflict",
        411: "Length Required",
        413: "Payload Too Large",
        429: "Too Many Requests",
        431: "Request Header Fields Too Large",
        502: "Bad Gateway",
    }.get(status, "Error")
    merged = {
        "Connection": "close",
        "Content-Length": str(len(payload)),
        **headers,
    }
    head = [f"HTTP/1.1 {status} {reason}", *(f"{key}: {value}" for key, value in merged.items())]
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode("ascii") + payload)
    await writer.drain()


def _safe_call_id(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value or len(value) > 256 or any(char in value for char in "\x00\r\n"):
        raise _RequestRejected(400, "Responses tool call id is invalid")
    return value


def _validated_response_call_id(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        return f"call_{uuid4().hex}"
    if len(value) > 256 or any(char in value for char in "\x00\r\n"):
        raise ResponsesProxyError("Octopus model returned an invalid tool call id")
    return value


def _safe_tool_name(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value or len(value) > 128 or any(char in value for char in "\x00\r\n"):
        raise _RequestRejected(400, "Responses tool name is invalid")
    return value


def _bounded_int(raw: Any, *, default: int, minimum: int, maximum: int) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise _RequestRejected(400, "Responses integer option is invalid")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise _RequestRejected(400, "Responses integer option is invalid") from None
    if not minimum <= value <= maximum:
        raise _RequestRejected(400, "Responses integer option is outside the allowed range")
    return value


def _bounded_float(raw: Any, *, default: float, minimum: float, maximum: float) -> float:
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise _RequestRejected(400, "Responses numeric option is invalid")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise _RequestRejected(400, "Responses numeric option is invalid") from None
    if not minimum <= value <= maximum:
        raise _RequestRejected(400, "Responses numeric option is outside the allowed range")
    return value


__all__ = [
    "CodexResponsesScope",
    "ResponsesProxyError",
    "ScopedResponsesProxy",
    "model_response_to_responses",
    "responses_payload_to_model_request",
]

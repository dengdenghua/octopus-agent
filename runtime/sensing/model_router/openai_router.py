# ruff: noqa: E402 — module-level imports below are intentionally late

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from runtime.adapters.instrumentation import record_gen_ai_cost, trace_stage
from runtime.platform.models import CostEntry

from .models import (
    LLMResponseFormatError,
    Message,
    ModelRequest,
    ModelResponse,
    ModelRouter,
    normalize_reasoning_effort,
    thinking_budget_for_effort,
)

try:
    import httpx  # type: ignore[import-untyped]

    HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    HTTPX_AVAILABLE = False
    httpx = None  # type: ignore[assignment]


_DEFAULT_INPUT_USD_PER_TOKEN = 1e-7
_DEFAULT_OUTPUT_USD_PER_TOKEN = 3e-7
_MIN_THINKING_OUTPUT_TOKENS = 128

# OpenAI's reasoning_effort only accepts minimal/low/medium/high. Octopus's
# xhigh tier (and the ultra/extra_high aliases that normalize to it) has no
# native value, so clamp it to "high" rather than putting an unknown string on
# the wire — a strict endpoint 400s on it, and a lenient one silently ignores
# it (losing the high-effort signal entirely). Anthropic is unaffected: it
# routes effort through a numeric thinking budget, not this string.
_OPENAI_REASONING_EFFORT: dict[str, str] = {
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}


@dataclass(frozen=True)
class OpenAICompatModelCapabilities:
    """Provider/model quirks for OpenAI-compatible chat endpoints.

    The OpenAI-compatible label is a wire-shape promise, not a guarantee that
    every provider accepts every optional field. Custom-model entries can
    declare the differences explicitly; this resolver centralizes the defaults
    so payload construction does not grow a pile of provider-specific branches.
    """

    supports_tool_use: bool = True
    supports_thinking: bool = False
    omit_sampling_parameters: bool = False
    omit_system_messages: bool = False
    thinking_wire_format: str = "openai"


def _openai_reasoning_effort(value: Any) -> str:
    """Map an octopus reasoning-effort tier onto a value native OpenAI accepts."""
    return _OPENAI_REASONING_EFFORT.get(normalize_reasoning_effort(value) or "high", "high")


def resolve_openai_compat_model_capabilities(
    model: str,
    entry: dict[str, Any] | None = None,
) -> OpenAICompatModelCapabilities:
    """Resolve OpenAI-compatible protocol quirks for a model.

    ``entry`` is an optional custom-model row from ``custom_models.json``.
    Passing it lets audits and config tooling evaluate a candidate entry
    without first persisting it. When omitted, the resolver reads the persisted
    custom-model registry and falls back to conservative built-in defaults.
    """
    if entry is not None:
        return _entry_openai_compat_capabilities(entry, model)
    data = _read_custom_models()
    if isinstance(data, dict):
        for existing in data.values():
            if _entry_matches_model(existing, model):
                return _entry_openai_compat_capabilities(existing, model)
    return OpenAICompatModelCapabilities(
        omit_system_messages=_model_defaults_omit_system_messages(model),
        thinking_wire_format=_model_defaults_thinking_wire_format(model),
    )


class OpenAIRouterError(LLMResponseFormatError):
    pass


from .provider import Provider, ProviderCapabilities


class OpenAIModelRouter(Provider, ModelRouter):

    provider_name = "openai"
    capabilities = ProviderCapabilities(
        supports_vision=True,
        supports_tool_use=True,
        supports_streaming=True,
        supports_prompt_cache=True,   # OpenAI honors `prompt_cache_key`
        supports_structured_output=True,
        default_model="gpt-4o-mini",
        pricing_hint="mid",
    )

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        default_model: str = "gpt-4o-mini",
        env_var_name: str = "OPENAI_API_KEY",
        timeout_seconds: float = 60.0,
        pricing_per_1k: dict[str, tuple[float, float]] | None = None,
        extra_headers: dict[str, str] | None = None,
        client: Any = None,
    ) -> None:
        if not HTTPX_AVAILABLE:
            raise OpenAIRouterError(
                "httpx not installed · `pip install httpx` (or install extras: '.[web]')"
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get(env_var_name, "")
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds
        self.pricing_per_1k = pricing_per_1k or {}
        self.extra_headers = dict(extra_headers or {})
        self._client = client  # Implementation note.
        self._owns_client = client is None


    def call(self, request: ModelRequest) -> ModelResponse:
        model = request.model or self.default_model

        with trace_stage(
            "eyes.openai_router.call",
            **{"octopus.model": model, "octopus.provider": "openai_compat"},
        ) as span:
            payload = self._build_payload(request, model)
            client = self._client if self._client is not None else httpx.Client(
                timeout=self.timeout_seconds,
            )
            try:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._build_headers(),
                )
                if _should_retry_without_openai_thinking(
                    resp.status_code, payload,
                ):
                    fallback_payload = _without_openai_thinking(payload)
                    resp = client.post(
                        f"{self.base_url}/chat/completions",
                        json=fallback_payload,
                        headers=self._build_headers(),
                    )
            except Exception as e:  # noqa: BLE001
                raise OpenAIRouterError(
                    f"http_error: {type(e).__name__}: {e}"
                ) from e
            finally:
                if self._client is None:
                    client.close()

            if resp.status_code >= 400:
                raise OpenAIRouterError(
                    _format_openai_http_error(resp.status_code, resp.text)
                )

            try:
                data = resp.json()
            except Exception as e:  # noqa: BLE001
                raise OpenAIRouterError(f"invalid_json: {e}") from e

            text, finish_reason, thinking = self._extract_text(data)
            tool_calls = self._extract_tool_calls(data)
            usage = data.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", 0) or 0)
            output_tokens = int(usage.get("completion_tokens", 0) or 0)
            cost_usd = self._estimate_cost(model, input_tokens, output_tokens)

            cost = CostEntry(
                tokens_in=input_tokens,
                tokens_out=output_tokens,
                usd=cost_usd,
            )
            record_gen_ai_cost(
                span,
                system="openai_compat",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                usd=cost_usd,
            )

            return ModelResponse(
                text=text,
                thinking=thinking,
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                finish_reason=finish_reason,
                model=data.get("model", model),
                provider="openai_compat",
            )

    # ─── Streaming ────────────────────────────────────

    def call_stream(self, request: ModelRequest):
        """Real SSE streaming via the shared OpenAI-compat parser.

        Opens an httpx streaming POST with ``stream=True`` and
        delegates line parsing to ``iter_openai_sse``. Any new
        OpenAI-compat provider gets streaming for free by following
        the same pattern.
        """
        from .openai_compat_stream import iter_openai_sse

        model = request.model or self.default_model
        payload = self._build_payload(request, model)
        payload["stream"] = True

        client = self._client if self._client is not None else httpx.Client(
            # Streaming-tuned timeouts: ``connect`` for the initial
            # handshake, ``read`` is the gap between successive bytes
            # — must be tight or a hung upstream (mimo / smaller
            # OpenAI-compat proxies sometimes finish the model
            # output but never send ``data: [DONE]``) leaves the
            # request blocked indefinitely. Without a read cap the
            # ReAct loop's interrupt watcher can't break us out
            # because the producer thread is stuck inside
            # ``response.iter_lines()``.
            timeout=httpx.Timeout(
                connect=30.0,
                read=45.0,
                write=30.0,
                pool=10.0,
            ),
        )
        close_after = self._client is None
        url = f"{self.base_url}/chat/completions"
        try:
            with client.stream(
                "POST", url, json=payload, headers=self._build_headers(),
            ) as r:
                if r.status_code < 400:
                    yield from iter_openai_sse(
                        r, model=model, provider="openai_compat",
                    )
                    return
                r.read()
                first_status = r.status_code
                first_text = r.text

            if _should_retry_without_openai_thinking(first_status, payload):
                fallback_payload = _without_openai_thinking(payload)
                with client.stream(
                    "POST", url,
                    json=fallback_payload,
                    headers=self._build_headers(),
                ) as r:
                    if r.status_code < 400:
                        yield from iter_openai_sse(
                            r, model=model, provider="openai_compat",
                        )
                        return
                    r.read()
                    first_status = r.status_code
                    first_text = r.text

            raise OpenAIRouterError(
                _format_openai_http_error(first_status, first_text)
            )
        finally:
            if close_after:
                client.close()


    def _build_payload(self, request: ModelRequest, model: str) -> dict[str, Any]:
        caps = self._model_capabilities(model)
        # Message shape · caller may hand us Anthropic-style
        # block lists (tool_use / tool_result) that we need to
        # translate into OpenAI's flat function-call format
        # before sending. ``_messages_to_openai`` is the
        # translator; it falls back to the old 1-to-1 mapping
        # when no blocks are present.
        msgs = _messages_to_openai(request.messages)
        if caps.omit_system_messages:
            msgs = [m for m in msgs if m.get("role") != "system"]
        if request.images_b64 and msgs:
            _attach_images_to_last_user_openai(msgs, request.images_b64)
        msgs = _sanitize_openai_messages(msgs)
        payload: dict[str, Any] = {
            "model": model,
            "messages": msgs,
        }
        if not caps.omit_sampling_parameters:
            payload["temperature"] = request.temperature
        max_tokens = request.max_tokens
        if (
            (
                request.enable_thinking
                or caps.supports_thinking
            )
            and max_tokens is not None
            and max_tokens < _MIN_THINKING_OUTPUT_TOKENS
        ):
            max_tokens = _MIN_THINKING_OUTPUT_TOKENS
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        # Native function calling · OpenAI ``tools`` spec shape is
        # ``[{type:"function", function:{name, description, parameters}}]``
        # where parameters is JSON Schema (== our input_schema).
        # Most OpenAI-compat providers (GLM, Kimi, DeepSeek,
        # Qwen, OpenRouter) follow the same shape. Providers that
        # don't will just ignore the field — except some (mimo,
        # smaller community models) silently swallow it AND have the
        # model hallucinate "I cannot call tools" in pure prose.
        # Skip the tools block entirely when ``custom_models.json``
        # explicitly declares ``supports_tool_use=false`` for this
        # model id, so the LLM doesn't get a tools spec it can't act
        # on. The caller (ReAct loop / ephemeral runner) will see
        # the lack of tool_calls and fall back to text-only synthesis.
        if request.tools and caps.supports_tool_use:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in request.tools
            ]
            # Let the model decide · default "auto" means tools
            # are available but not required · matches Anthropic
            # default behavior and works for agentic loops.
            payload["tool_choice"] = "auto"
        if request.enable_thinking:
            _apply_thinking_wire_format(
                payload,
                request,
                caps,
                max_tokens=max_tokens,
            )
        return payload

    @staticmethod
    def _model_capabilities(model: str) -> OpenAICompatModelCapabilities:
        return resolve_openai_compat_model_capabilities(model)

    @staticmethod
    def _model_supports_tool_use(model: str) -> bool:
        """Return False when ``custom_models.json`` (or per-model env
        overrides) marks this model id as not supporting native
        function calling.

        Default is True — most OpenAI-compatible endpoints honor
        ``tools``. We only flip to False when the operator has
        explicitly declared incompatibility, so we don't accidentally
        disable working providers.
        """
        return OpenAIModelRouter._model_capabilities(model).supports_tool_use

    @staticmethod
    def _model_omits_sampling_parameters(model: str) -> bool:
        """Return True for strict OpenAI-compatible coding endpoints.

        Some coding-model gateways reject sampling knobs entirely (or
        require their undocumented defaults). Operators can declare
        ``omit_sampling_parameters=true`` in ``custom_models.json`` so
        Octopus sends only model/messages/max_tokens/tool fields.
        """
        return OpenAIModelRouter._model_capabilities(model).omit_sampling_parameters

    @staticmethod
    def _model_omits_system_messages(model: str) -> bool:
        """Whether to drop system-role messages before sending.

        Some OpenAI-compatible coding endpoints reject ``role=system`` or
        handle it poorly. Prefer explicit custom-model configuration, with a
        tiny compatibility default for known strict GLM variants.
        """
        return OpenAIModelRouter._model_capabilities(model).omit_system_messages

    @staticmethod
    def _custom_model_supports_thinking(model: str) -> bool:
        return OpenAIModelRouter._model_capabilities(model).supports_thinking

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)
        return headers

    def _extract_text(self, data: dict[str, Any]) -> tuple[str, str, str]:
        choices = data.get("choices") or []
        if not choices:
            raise OpenAIRouterError(
                f"no choices in response · keys={list(data.keys())}"
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise OpenAIRouterError("choice[0] not a dict")
        msg = first.get("message") or {}
        content = msg.get("content", "")
        if content is None:
            content = ""
        thinking = msg.get("reasoning_content") or ""
        if isinstance(content, list):
            parts = [
                p.get("text") or ""
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            content = "".join(parts)
        if not isinstance(content, str):
            content = json.dumps(content)
        if not isinstance(thinking, str):
            thinking = json.dumps(thinking, ensure_ascii=False)
        finish_reason = first.get("finish_reason") or "stop"
        return content, finish_reason, thinking

    def _extract_tool_calls(self, data: dict[str, Any]) -> list[Any]:
        """Pull native function calls from an OpenAI response.

        Response shape::

            choices[0].message.tool_calls = [
                {"id": "call_...",
                 "type": "function",
                 "function": {"name": "...", "arguments": "<json str>"}},
                ...
            ]

        Returns a list of ``ToolCall`` · empty when the model
        didn't invoke any functions. JSON argument parsing is
        permissive: a malformed ``arguments`` string yields an
        empty dict rather than raising, so the agentic loop can
        surface the error back to the model instead of 500-ing."""
        from .models import ToolCall
        choices = data.get("choices") or []
        if not choices:
            return []
        first = choices[0]
        if not isinstance(first, dict):
            return []
        msg = first.get("message") or {}
        raw_calls = msg.get("tool_calls") or []
        out: list[ToolCall] = []
        for call in raw_calls:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            args_raw = fn.get("arguments") or ""
            try:
                args = (
                    json.loads(args_raw) if args_raw else {}
                )
            except json.JSONDecodeError:
                args = {}
            out.append(ToolCall(
                id=str(call.get("id") or ""),
                name=str(name),
                input=args if isinstance(args, dict) else {},
            ))
        return out

    def _estimate_cost(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        pricing = self.pricing_per_1k.get(model)
        if pricing is not None:
            in_usd, out_usd = pricing
            return (input_tokens / 1000) * in_usd + (output_tokens / 1000) * out_usd
        return (
            input_tokens * _DEFAULT_INPUT_USD_PER_TOKEN
            + output_tokens * _DEFAULT_OUTPUT_USD_PER_TOKEN
        )


# ═══════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════


def _read_custom_models() -> dict[str, Any] | None:
    try:
        from runtime.platform.process.paths import app_paths

        path = app_paths().custom_models_path
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, ImportError, TypeError):
        return None


def _entry_matches_model(entry: Any, model: str) -> bool:
    if not isinstance(entry, dict):
        return False
    target = (model or "").strip()
    if not target:
        return False
    candidates = {
        str(value).strip()
        for value in (
            entry.get("id"),
            entry.get("name"),
            entry.get("model"),
            entry.get("display_name"),
        )
        if isinstance(value, str) and value.strip()
    }
    raw_models = entry.get("models")
    if isinstance(raw_models, list):
        candidates.update(
            str(value).strip()
            for value in raw_models
            if isinstance(value, str) and value.strip()
        )
    return target in candidates


def _entry_openai_compat_capabilities(
    entry: dict[str, Any],
    model: str,
) -> OpenAICompatModelCapabilities:
    return OpenAICompatModelCapabilities(
        supports_tool_use=bool(entry.get("supports_tool_use", True)),
        supports_thinking=bool(entry.get("supports_thinking", False)),
        omit_sampling_parameters=bool(entry.get("omit_sampling_parameters", False)),
        omit_system_messages=bool(
            entry.get(
                "omit_system_messages",
                _model_defaults_omit_system_messages(model),
            )
        ),
        thinking_wire_format=_entry_thinking_wire_format(entry, model),
    )


def _model_defaults_omit_system_messages(model: str) -> bool:
    return "glm-5.1" in (model or "").lower()


def _model_defaults_thinking_wire_format(model: str) -> str:
    m = (model or "").lower()
    if "qwen" in m or "通义" in m:
        return "qwen_enable_thinking"
    if "deepseek-reasoner" in m or "deepseek-r1" in m:
        return "implicit"
    return "openai"


def _entry_thinking_wire_format(entry: dict[str, Any], model: str) -> str:
    for key in (
        "thinking_wire_format",
        "thinking_parameter_style",
        "thinking_protocol",
    ):
        if key in entry:
            return _normalize_thinking_wire_format(entry.get(key))
    haystack = _entry_haystack(entry, model)
    if "dashscope" in haystack or "qwen" in haystack or "通义" in haystack:
        return "qwen_enable_thinking"
    if "deepseek-reasoner" in haystack or "deepseek-r1" in haystack:
        return "implicit"
    return _model_defaults_thinking_wire_format(model)


def _entry_haystack(entry: dict[str, Any], model: str) -> str:
    raw = [
        model,
        entry.get("id"),
        entry.get("name"),
        entry.get("display_name"),
        entry.get("provider"),
        entry.get("base_url"),
    ]
    models = entry.get("models")
    if isinstance(models, list):
        raw.extend(models)
    return " ".join(str(value or "") for value in raw).lower()


def _normalize_thinking_wire_format(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "": "openai",
        "default": "openai",
        "openai_compat": "openai",
        "openai_extensions": "openai",
        "qwen": "qwen_enable_thinking",
        "dashscope": "qwen_enable_thinking",
        "enable_thinking": "qwen_enable_thinking",
        "model_default": "implicit",
        "auto": "implicit",
        "none": "implicit",
        "off": "implicit",
        "disabled": "implicit",
        "reasoning": "reasoning_effort",
        "thinking": "thinking_object",
    }
    normalized = aliases.get(raw, raw)
    supported = {
        "openai",
        "qwen_enable_thinking",
        "implicit",
        "reasoning_effort",
        "thinking_object",
    }
    return normalized if normalized in supported else "openai"


def _apply_thinking_wire_format(
    payload: dict[str, Any],
    request: ModelRequest,
    caps: OpenAICompatModelCapabilities,
    *,
    max_tokens: int | None,
) -> None:
    wire_format = _normalize_thinking_wire_format(caps.thinking_wire_format)
    if wire_format == "implicit":
        return
    if wire_format == "qwen_enable_thinking":
        payload["enable_thinking"] = True
        budget = thinking_budget_for_effort(
            normalize_reasoning_effort(request.reasoning_effort),
            max_tokens,
        )
        if max_tokens is None or budget < max_tokens:
            payload["thinking_budget"] = budget
        return
    if wire_format == "reasoning_effort":
        payload["reasoning_effort"] = _openai_reasoning_effort(
            request.reasoning_effort,
        )
        return
    if wire_format == "thinking_object":
        payload["thinking"] = {"type": "enabled"}
        return
    payload["reasoning_effort"] = _openai_reasoning_effort(
        request.reasoning_effort,
    )
    payload["thinking"] = {"type": "enabled"}


def _format_openai_http_error(status_code: int, body: str) -> str:
    body_preview = (body or "").strip()[:500]
    parsed_message = ""
    parsed_type = ""
    try:
        payload = json.loads(body or "{}")
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            parsed_message = str(error.get("message") or "").strip()
            parsed_type = str(error.get("type") or error.get("code") or "").strip()
    except (TypeError, json.JSONDecodeError):  # noqa: BLE001 — error body parse failed; keep empty parsed fields
        pass

    lower = f"{parsed_type} {parsed_message} {body_preview}".lower()
    if (
        status_code == 402
        or "insufficient_balance" in lower
        or "insufficient account balance" in lower
    ):
        return (
            f"http_{status_code}: 模型账户余额不足，请充值当前模型供应商账户，"
            "或在模型选择里切换到可用模型。"
        )
    if status_code in (401, 403):
        detail = parsed_message or body_preview
        suffix = f"（{detail}）" if detail else ""
        return f"http_{status_code}: 模型 API Key 无效或没有权限{suffix}"

    detail = parsed_message or body_preview
    if status_code == 400 and (not detail or detail == "openai_error"):
        return (
            f"http_{status_code}: 上游 OpenAI 兼容接口拒绝请求"
            f"{f'（{detail}）' if detail else ''}。"
            "通常是模型名、API Key、额度或供应商不支持的 reasoning/thinking "
            "参数导致；请切换到可用模型，或在模型设置里关闭该模型的思考能力后重试。"
        )
    return f"http_{status_code}: {detail}"


def _without_openai_thinking(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a Chat Completions payload without thinking extensions.

    OpenAI-compatible gateways disagree on reasoning knobs: some accept
    ``reasoning_effort`` and/or ``thinking``, others return a generic
    ``400 openai_error`` for either field. A one-shot fallback keeps custom
    providers usable without forcing operators to know every proxy dialect.
    """
    fallback = dict(payload)
    fallback.pop("reasoning_effort", None)
    fallback.pop("thinking", None)
    fallback.pop("enable_thinking", None)
    fallback.pop("thinking_budget", None)
    return fallback


def _should_retry_without_openai_thinking(
    status_code: int,
    payload: dict[str, Any],
) -> bool:
    if status_code != 400:
        return False
    return any(
        key in payload
        for key in ("reasoning_effort", "thinking", "enable_thinking", "thinking_budget")
    )


def _message_to_openai(m: Message) -> dict[str, str]:
    """Legacy 1-to-1 translator · preserved for callers that only
    handle plain string content. New code should use
    ``_messages_to_openai`` which handles Anthropic-style blocks.
    """
    content = m.content if isinstance(m.content, str) else ""
    return {"role": m.role, "content": content}


def _coerce_openai_content(content: Any) -> str | list[Any]:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def _openai_content_is_empty(content: Any) -> bool:
    if content is None:
        return True
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                if str(block or "").strip():
                    return False
                continue
            btype = block.get("type")
            if btype == "text":
                if str(block.get("text") or "").strip():
                    return False
                continue
            # Image/media blocks are meaningful even without text.
            if btype in {"image_url", "input_image", "image"}:
                return False
            if block:
                return False
        return True
    return not str(content).strip()


def _sanitize_openai_tool_calls(
    tool_calls: Any,
    *,
    message_index: int,
) -> list[dict[str, Any]]:
    if not isinstance(tool_calls, list):
        return []
    sanitized: list[dict[str, Any]] = []
    for raw_call in tool_calls:
        if not isinstance(raw_call, dict):
            continue
        fn = raw_call.get("function")
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        arguments = fn.get("arguments")
        if arguments is None or arguments == "":
            arguments = "{}"
        elif not isinstance(arguments, str):
            arguments = json.dumps(arguments, ensure_ascii=False, default=str)
        sanitized.append({
            "id": str(raw_call.get("id") or f"call_{message_index}_{len(sanitized)}"),
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments,
            },
        })
    return sanitized


def _sanitize_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize chat history for strict OpenAI-compatible providers.

    Several compatible gateways are stricter than OpenAI's own endpoint:
    they reject empty assistant turns, orphan ``tool`` messages, non-string
    tool-call arguments, or blank system/user messages. The kernel may still
    produce those shapes while recovering from empty model output or provider
    tool-call quirks, so the router boundary cleans them before they go on the
    wire.
    """
    out: list[dict[str, Any]] = []
    known_tool_call_ids: set[str] = set()
    unpaired_tool_call_ids: list[str] = []

    for index, raw_msg in enumerate(messages):
        if not isinstance(raw_msg, dict):
            continue
        role = str(raw_msg.get("role") or "").strip()
        if role not in {"system", "user", "assistant", "tool"}:
            role = "user"

        if role == "assistant":
            content = _coerce_openai_content(raw_msg.get("content", ""))
            tool_calls = _sanitize_openai_tool_calls(
                raw_msg.get("tool_calls"),
                message_index=index,
            )
            if _openai_content_is_empty(content) and not tool_calls:
                continue
            msg: dict[str, Any] = {"role": "assistant", "content": content}
            if tool_calls:
                msg["tool_calls"] = tool_calls
                for call in tool_calls:
                    call_id = str(call.get("id") or "")
                    if call_id:
                        known_tool_call_ids.add(call_id)
                        unpaired_tool_call_ids.append(call_id)
            out.append(msg)
            continue

        if role == "tool":
            content = _coerce_openai_content(raw_msg.get("content", ""))
            if _openai_content_is_empty(content):
                content = "(empty tool result)"
            call_id = str(raw_msg.get("tool_call_id") or "").strip()
            if not call_id and unpaired_tool_call_ids:
                call_id = unpaired_tool_call_ids.pop(0)
            elif call_id in unpaired_tool_call_ids:
                unpaired_tool_call_ids.remove(call_id)
            if call_id and call_id in known_tool_call_ids:
                out.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": content,
                })
            else:
                # Tool output without a matching assistant tool_call is invalid
                # OpenAI history. Keep the evidence as plain user context.
                out.append({
                    "role": "user",
                    "content": (
                        "Tool result without matching tool call"
                        f"{f' ({call_id})' if call_id else ''}: {content}"
                    ),
                })
            continue

        content = _coerce_openai_content(raw_msg.get("content", ""))
        if _openai_content_is_empty(content):
            continue
        out.append({"role": role, "content": content})

    if not out:
        out.append({"role": "user", "content": "Continue."})
    return out


def _messages_to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    """Translate Octopus messages to OpenAI chat-completion shape.

    Octopus internally uses Anthropic-style block lists for
    multi-turn tool flows:

        assistant · content=[{"type":"text",...}, {"type":"tool_use", id, name, input}]
        user      · content=[{"type":"tool_result", tool_use_id, content, [is_error]}]

    OpenAI's schema is different:

        assistant · {"role":"assistant", "content":"...", "tool_calls":[{id, type:"function", function:{name, arguments}}]}
        tool      · {"role":"tool", "tool_call_id":"...", "content":"..."}

    This translator does the mapping. A plain-string content
    message passes through unchanged.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m.content, str):
            # Fast path · plain string · pass through.
            out.append({"role": m.role, "content": m.content})
            continue

        # Block-list content · need to split and re-shape.
        blocks = m.content if isinstance(m.content, list) else []

        if m.role == "assistant":
            # Collect text + tool_use blocks into a single
            # assistant message.
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                btype = b.get("type")
                if btype == "text":
                    text_parts.append(str(b.get("text", "")))
                elif btype == "tool_use":
                    args = b.get("input") or {}
                    tool_calls.append({
                        "id": b.get("id") or "",
                        "type": "function",
                        "function": {
                            "name": b.get("name") or "",
                            "arguments": json.dumps(
                                args, ensure_ascii=False,
                            ),
                        },
                    })
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(text_parts),
            }
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
            continue

        if m.role == "user":
            # Separate tool_result blocks from text content.
            # Tool results become standalone ``{"role":"tool"}``
            # messages; any stray text goes into a user message.
            text_parts = []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                btype = b.get("type")
                if btype == "tool_result":
                    content = b.get("content") or ""
                    if not isinstance(content, str):
                        content = json.dumps(
                            content, ensure_ascii=False, default=str,
                        )
                    out.append({
                        "role": "tool",
                        "tool_call_id": b.get("tool_use_id") or "",
                        "content": content,
                    })
                elif btype == "text":
                    text_parts.append(str(b.get("text", "")))
            if text_parts:
                out.append({
                    "role": "user",
                    "content": "".join(text_parts),
                })
            continue

        # System (or unknown role) · stringify best-effort.
        text_parts = [
            str(b.get("text", ""))
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        out.append({"role": m.role, "content": "".join(text_parts)})
    return out


def _attach_images_to_last_user_openai(
    msgs: list[dict[str, Any]], images_b64: list[str],
) -> None:
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") == "user":
            text = msgs[i].get("content", "")
            blocks: list[dict[str, Any]] = []
            for b64 in images_b64:
                blocks.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
            if text:
                blocks.append({"type": "text", "text": text})
            msgs[i]["content"] = blocks
            return

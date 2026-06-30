# ruff: noqa: E402 — module-level imports below are intentionally late

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

try:
    import httpx  # type: ignore[import-untyped]

    HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    HTTPX_AVAILABLE = False
    httpx = None  # type: ignore[assignment]

from .actor_context import current_actor  # noqa: F401 — re-export: moved to a neutral home
from .models import CostEntry, ModelRequest, ModelResponse, ModelRouter, ModelStreamEvent


class MoliliCredentialsRequired(RuntimeError):
    pass


from .provider import Provider, ProviderCapabilities


class MoliliModelRouter(Provider, ModelRouter):

    provider_name = "molili"
    capabilities = ProviderCapabilities(
        # Molili is a multi-model gateway; capabilities reflect the
        # *superset* · individual sub-models (glm-4.7 / kimi-k2.5 /
        # minimax-m2.5 / deepseek-v3.2 / qwen3-max) vary. Frontend
        # ModelPicker should prefer per-model capability flags once
        # we surface them; this class-level declaration is a floor.
        supports_vision=True,
        supports_tool_use=False,
        supports_streaming=True,
        supports_prompt_cache=False,
        supports_structured_output=False,
        default_model="molili",
        pricing_hint="low",   # Implementation note.
    )

    def __init__(
        self,
        *,
        link_store: Any,          # Implementation note.
        base_url: str,
        default_model: str = "molili",
        timeout_seconds: float = 60.0,
        http_client: Any = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url required")
        self.link_store = link_store
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds
        self._http = http_client

    def _resolve_actor(self) -> str:
        actor = current_actor.get()
        if actor:
            return actor
        if os.environ.get("OCTOPUS_DESKTOP") == "1":
            try:
                actor_ids = self.link_store.all_actor_ids()
            except (OSError, RuntimeError):  # noqa: BLE001
                actor_ids = []
            if len(actor_ids) == 1:
                return actor_ids[0]
        raise MoliliCredentialsRequired(
            "no current_actor set · MoliliModelRouter 需要登录态",
        )

    def call(self, request: ModelRequest) -> ModelResponse:
        actor = self._resolve_actor()
        if not actor:
            raise MoliliCredentialsRequired(
                "no current_actor set · MoliliModelRouter 需要登录态",
            )
        link = self.link_store.get(actor)
        if link is None:
            raise MoliliCredentialsRequired(
                f"actor {actor!r} 没有绑定 Molili 账号",
            )

        model = request.model or self.default_model
        # Messages · reuse the OpenAI-compat translator so
        # Anthropic-style block lists (tool_use / tool_result)
        # get converted to OpenAI's flat shape. A single code
        # path handles all provider-interchange quirks; no more
        # silent content-loss when an agentic caller hands us
        # structured blocks.
        from .openai_router import _messages_to_openai
        messages = _messages_to_openai(list(request.messages or []))

        imgs = list(getattr(request, "images_b64", []) or [])
        if imgs:
            for i in range(len(messages) - 1, -1, -1):
                if messages[i]["role"] == "user":
                    text = messages[i]["content"]
                    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
                    for b64 in imgs:
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        })
                    messages[i] = {"role": "user", "content": content}
                    break

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,          # Implementation note.
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        # Native function calling · Molili's proxies forward
        # ``tools`` / ``tool_choice`` to the backing model. GLM-4
        # family, Kimi K2, DeepSeek, Qwen3 all support this. For
        # models that don't, the field is ignored and the call
        # degrades gracefully to a plain completion.
        if request.tools:
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
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {link.molili_user_id}",
            "Content-Type": "application/json",
        }

        client = self._http or (httpx if HTTPX_AVAILABLE else None)
        if client is None:
            raise RuntimeError(
                "httpx 未安装 · 无法调 Molili · pip install httpx 或注入 http_client",
            )

        url = f"{self.base_url}/chat/completions"
        try:
            r = client.post(
                url, json=payload, headers=headers, timeout=self.timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Molili upstream unreachable: {exc}") from exc
        status = getattr(r, "status_code", 0)
        text = getattr(r, "text", "") or ""
        if status >= 400:
            raise RuntimeError(
                f"Molili upstream HTTP {status}: {text[:500]}",
            )
        try:
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Molili upstream non-JSON: {text[:200]}",
            ) from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(
                f"Molili response missing choices: {str(data)[:200]}",
            )
        content = (
            choices[0].get("message", {}).get("content")
            or choices[0].get("text")
            or ""
        )
        # Tool calls · OpenAI-compat shape
        # ``choices[0].message.tool_calls = [{id, type, function:{name, arguments}}]``
        # · empty list when the model didn't decide to call any.
        from .models import ToolCall
        raw_calls = (
            choices[0].get("message", {}).get("tool_calls") or []
        )
        tool_calls: list[ToolCall] = []
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
            tool_calls.append(ToolCall(
                id=str(call.get("id") or ""),
                name=str(name),
                input=args if isinstance(args, dict) else {},
            ))
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)

        return ModelResponse(
            text=content,
            tool_calls=tool_calls,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            cost=CostEntry(
                tokens_in=prompt_tokens,
                tokens_out=completion_tokens,
                usd=0.0,
            ),
            model=model,
            provider="molili",
        )

    def call_stream(
        self, request: ModelRequest,
    ) -> Iterator[ModelStreamEvent]:
        """Real SSE streaming via Molili's OpenAI-compat endpoint.

        Delegates to the shared ``iter_openai_sse`` parser so adding
        another OpenAI-compat provider never requires re-implementing
        SSE parsing.
        """
        from .openai_compat_stream import iter_openai_sse

        actor = self._resolve_actor()
        if not actor:
            raise MoliliCredentialsRequired(
                "no current_actor set · MoliliModelRouter 需要登录态",
            )
        link = self.link_store.get(actor)
        if link is None:
            raise MoliliCredentialsRequired(
                f"actor {actor!r} 没有绑定 Molili 账号",
            )

        model = request.model or self.default_model
        messages: list[dict[str, Any]] = [
            {"role": m.role, "content": m.content}
            for m in (request.messages or [])
        ]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        headers = {
            "Authorization": f"Bearer {link.molili_user_id}",
            "Content-Type": "application/json",
        }

        client = self._http or (httpx if HTTPX_AVAILABLE else None)
        if client is None:
            yield from super().call_stream(request)
            return

        url = f"{self.base_url}/chat/completions"
        try:
            with client.stream(
                "POST", url, json=payload, headers=headers,
                timeout=self.timeout_seconds,
            ) as r:
                yield from iter_openai_sse(
                    r, model=model, provider="molili",
                )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Molili stream failed: {exc}") from exc

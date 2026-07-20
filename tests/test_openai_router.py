"""Implementation note."""

from __future__ import annotations

from typing import Any

import pytest

httpx = pytest.importorskip("httpx")

from runtime.sensing.model_router import (  # noqa: E402
    Message,
    ModelRequest,
    MultiModelRouter,
    OpenAIModelRouter,
    OpenAIRouterError,
)
from runtime.sensing.model_router.models import ToolSpec  # noqa: E402

# ═══════════════════════════════════════════════════════════
# fake httpx client
# ═══════════════════════════════════════════════════════════


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any = None,
        text: str = "",
        lines: list[str] | None = None,
    ):
        self.status_code = status_code
        self._payload = payload
        self.text = (
            text if text else (__import__("json").dumps(payload) if payload is not None else "")
        )
        self._lines = list(lines or [])

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def read(self):
        return self.text.encode("utf-8")

    def iter_lines(self):
        return iter(self._lines)


class _FakeStream:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def __enter__(self) -> _FakeResponse:
        return self._response

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeClient:
    """Implementation note."""

    def __init__(
        self,
        response: _FakeResponse | None = None,
        raise_exc: Exception | None = None,
        responses: list[_FakeResponse] | None = None,
    ):
        self._response = response
        self._responses = list(responses or [])
        self._raise = raise_exc
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self._raise:
            raise self._raise
        if self._responses:
            return self._responses.pop(0)
        return self._response

    def stream(self, method: str, url: str, *, json=None, headers=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "headers": headers,
            }
        )
        if self._raise:
            raise self._raise
        if self._responses:
            return _FakeStream(self._responses.pop(0))
        if self._response is None:
            raise AssertionError("fake stream response missing")
        return _FakeStream(self._response)

    def close(self):
        pass


def _req(model: str = "gpt-4o-mini", content: str = "hello") -> ModelRequest:
    return ModelRequest(
        model=model,
        messages=[Message(role="user", content=content)],
        max_tokens=128,
        temperature=0.0,
    )


def _openai_response(text: str = "hi back", *, prompt_tokens: int = 10, completion_tokens: int = 5):
    return {
        "id": "chatcmpl-test",
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestRequestShape:
    def test_url_and_headers(self):
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(
            base_url="http://localhost:11434/v1",
            api_key="sk-xxx",
            client=fake,
        )
        r.call(_req())
        call = fake.calls[0]
        assert call["url"] == "http://localhost:11434/v1/chat/completions"
        assert call["headers"]["Authorization"] == "Bearer sk-xxx"
        assert call["headers"]["Content-Type"] == "application/json"

    def test_payload_contains_messages_and_params(self):
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        r.call(_req(content="ping"))
        payload = fake.calls[0]["json"]
        assert payload["model"] == "gpt-4o-mini"
        assert payload["messages"] == [{"role": "user", "content": "ping"}]
        assert payload["max_tokens"] == 128
        assert payload["temperature"] == 0.0

    def test_reasoning_effort_is_sent_when_thinking_enabled(self):
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        r.call(
            _req(content="hard problem").model_copy(
                update={
                    "enable_thinking": True,
                    "reasoning_effort": "xhigh",
                },
            ),
        )

        payload = fake.calls[0]["json"]
        # xhigh is octopus-only; OpenAI's reasoning_effort tops out at "high",
        # so the wire value is clamped rather than sent verbatim (which a strict
        # endpoint would 400 on).
        assert payload["reasoning_effort"] == "high"
        assert payload["thinking"] == {"type": "enabled"}

    def test_reasoning_effort_can_bound_default_thinking_without_enabling_it(self):
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        r.call(
            _req(content="summarize completed evidence").model_copy(
                update={"enable_thinking": False, "reasoning_effort": "low"},
            ),
        )

        payload = fake.calls[0]["json"]
        assert payload["reasoning_effort"] == "low"
        assert "thinking" not in payload

    def test_thinking_400_retries_without_openai_extension_fields(self):
        fake = _FakeClient(
            responses=[
                _FakeResponse(400, {"error": {"message": "openai_error"}}),
                _FakeResponse(200, _openai_response("fallback ok")),
            ]
        )
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)

        resp = r.call(
            _req(content="hard problem").model_copy(
                update={
                    "enable_thinking": True,
                    "reasoning_effort": "xhigh",
                },
            ),
        )

        assert resp.text == "fallback ok"
        assert len(fake.calls) == 2
        first_payload = fake.calls[0]["json"]
        second_payload = fake.calls[1]["json"]
        assert first_payload["reasoning_effort"] == "high"
        assert first_payload["thinking"] == {"type": "enabled"}
        assert second_payload["model"] == first_payload["model"]
        assert "reasoning_effort" not in second_payload
        assert "thinking" not in second_payload

    def test_strict_custom_model_omits_sampling_parameters(
        self,
        monkeypatch,
        tmp_path,
    ):
        import json as _json

        custom_models_path = tmp_path / "custom_models.json"
        custom_models_path.write_text(
            _json.dumps(
                {
                    "kimi-code": {
                        "id": "kimi-code",
                        "name": "kimi-code",
                        "provider": "openai",
                        "models": ["kimi-k2.7-code"],
                        "omit_sampling_parameters": True,
                    },
                }
            ),
            encoding="utf-8",
        )
        from runtime.platform.process.paths import app_paths

        original = app_paths()

        class _Patched:
            pass

        _Patched.custom_models_path = custom_models_path

        def _getattr(self, name: str) -> object:
            return getattr(original, name)

        _Patched.__getattr__ = _getattr

        monkeypatch.setattr(
            "runtime.platform.process.paths.app_paths",
            lambda: _Patched(),
        )

        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        r.call(_req(model="kimi-k2.7-code"))

        payload = fake.calls[0]["json"]
        assert payload["model"] == "kimi-k2.7-code"
        assert "temperature" not in payload
        assert payload["max_tokens"] == 128

    def test_custom_model_compat_profile_overrides_payload_policy(
        self,
        monkeypatch,
        tmp_path,
    ):
        import json as _json

        custom_models_path = tmp_path / "custom_models.json"
        custom_models_path.write_text(
            _json.dumps(
                {
                    "manual-kimi": {
                        "id": "manual-kimi",
                        "name": "manual-kimi",
                        "provider": "openai",
                        "models": ["manual-code-model"],
                        "compat_profile": "kimi_coding",
                        "drop_tool_choice": True,
                        "unsupported_request_fields": ["parallel_tool_calls"],
                    },
                }
            ),
            encoding="utf-8",
        )
        from runtime.platform.process.paths import app_paths

        original = app_paths()

        class _Patched:
            pass

        _Patched.custom_models_path = custom_models_path

        def _getattr(self, name: str) -> object:
            return getattr(original, name)

        _Patched.__getattr__ = _getattr

        monkeypatch.setattr(
            "runtime.platform.process.paths.app_paths",
            lambda: _Patched(),
        )

        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(base_url="https://plain-proxy.example/v1", client=fake)
        r.call(
            _req(model="manual-code-model").model_copy(
                update={
                    "enable_thinking": True,
                    "reasoning_effort": "high",
                    "tools": [
                        ToolSpec(
                            name="read_file",
                            description="read",
                            input_schema={"type": "object"},
                        ),
                    ],
                },
            ),
        )

        payload = fake.calls[0]["json"]
        assert payload["model"] == "manual-code-model"
        assert "temperature" not in payload
        assert "reasoning_effort" not in payload
        assert "thinking" not in payload
        assert "tool_choice" not in payload
        assert r._profile_for_model("manual-code-model").id == "kimi_coding"

    def test_kimi_coding_profile_omits_sampling_without_custom_flag(self):
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(
            base_url="https://api.kimi.com/coding/v1",
            client=fake,
        )
        r.call(_req(model="kimi-k2.7-code"))

        payload = fake.calls[0]["json"]
        assert payload["model"] == "kimi-k2.7-code"
        assert payload["max_tokens"] == 128
        assert "temperature" not in payload

    def test_kimi_coding_agentic_payload_drops_thinking_and_sampling_but_keeps_tools(
        self,
    ):
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(
            base_url="https://api.kimi.com/coding/v1",
            client=fake,
        )
        r.call(
            _req(model="K2.7 Code").model_copy(
                update={
                    "enable_thinking": True,
                    "reasoning_effort": "xhigh",
                    "temperature": 0.8,
                    "tools": [
                        ToolSpec(
                            name="read_file",
                            description="Read a project file",
                            input_schema={
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                                "required": ["path"],
                            },
                        ),
                    ],
                },
            ),
        )

        payload = fake.calls[0]["json"]
        assert payload["model"] == "K2.7 Code"
        assert payload["tools"][0]["function"]["name"] == "read_file"
        assert payload["tool_choice"] == "auto"
        assert payload["max_tokens"] == 128
        assert "temperature" not in payload
        assert "reasoning_effort" not in payload
        assert "thinking" not in payload
        assert r._profile_for_model("K2.7 Code").id == "kimi_coding"

    def test_agentic_request_can_require_a_tool_call(self):
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)

        r.call(
            _req(model="deepseek-chat").model_copy(
                update={
                    "tools": [
                        ToolSpec(
                            name="read_file",
                            description="Read a project file",
                        ),
                    ],
                    "require_tool_use": True,
                },
            ),
        )

        assert fake.calls[0]["json"]["tool_choice"] == "required"

    def test_kimi_coding_model_name_omits_sampling_on_plain_proxy(self):
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(
            base_url="https://proxy.example/v1",
            client=fake,
        )
        r.call(_req(model="K2.7 Code"))

        payload = fake.calls[0]["json"]
        assert payload["model"] == "K2.7 Code"
        assert payload["max_tokens"] == 128
        assert "temperature" not in payload
        assert r._profile_for_model("K2.7 Code").id == "kimi_coding"

    def test_kimi_k2_general_model_name_keeps_sampling_on_plain_proxy(self):
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(
            base_url="https://proxy.example/v1",
            client=fake,
        )
        r.call(
            _req(model="kimi-k2-0711-preview").model_copy(
                update={"temperature": 1.8},
            ),
        )

        payload = fake.calls[0]["json"]
        assert payload["model"] == "kimi-k2-0711-preview"
        assert payload["temperature"] == 1.0
        assert payload["max_tokens"] == 128
        assert r._profile_for_model("kimi-k2-0711-preview").id == "kimi"

    def test_moonshot_profile_clamps_temperature(self):
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(
            base_url="https://api.moonshot.cn/v1",
            client=fake,
        )
        r.call(_req(model="moonshot-v1-128k").model_copy(update={"temperature": 1.8}))

        payload = fake.calls[0]["json"]
        assert payload["temperature"] == 1.0

    def test_qwen_retries_max_tokens_as_completion_tokens(self):
        fake = _FakeClient(
            responses=[
                _FakeResponse(
                    400,
                    {
                        "error": {
                            "message": "max_completion_tokens is expected instead of max_tokens",
                        },
                    },
                ),
                _FakeResponse(200, _openai_response("qwen ok")),
            ]
        )
        r = OpenAIModelRouter(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            client=fake,
        )

        resp = r.call(_req(model="qwen-plus"))

        assert resp.text == "qwen ok"
        assert len(fake.calls) == 2
        assert "max_tokens" in fake.calls[0]["json"]
        assert "max_completion_tokens" in fake.calls[1]["json"]
        assert "max_tokens" not in fake.calls[1]["json"]
        assert r.last_compatibility_events == [
            {
                "attempt": 1,
                "model": "qwen-plus",
                "profile": "qwen",
                "reason": "rename_max_tokens",
                "removed_fields": ["max_tokens"],
                "added_fields": ["max_completion_tokens"],
                "changed_fields": [],
            },
        ]

    def test_openai_compat_retries_can_chain_new_error_fields(self):
        fake = _FakeClient(
            responses=[
                _FakeResponse(
                    400,
                    {
                        "error": {
                            "message": "max_completion_tokens is expected instead of max_tokens",
                        },
                    },
                ),
                _FakeResponse(
                    400,
                    {
                        "error": {
                            "message": "unsupported parameter: response_format",
                        },
                    },
                ),
                _FakeResponse(200, _openai_response("compat ok")),
            ]
        )
        r = OpenAIModelRouter(
            base_url="https://plain-proxy.example/v1",
            client=fake,
        )
        r._build_payload = lambda _request, model: {
            "model": model,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 128,
            "response_format": {"type": "json_object"},
        }

        resp = r.call(_req(model="proxy-model"))

        assert resp.text == "compat ok"
        assert len(fake.calls) == 3
        assert fake.calls[0]["json"]["max_tokens"] == 128
        assert "response_format" in fake.calls[0]["json"]
        assert fake.calls[1]["json"]["max_completion_tokens"] == 128
        assert "response_format" in fake.calls[1]["json"]
        assert fake.calls[2]["json"]["max_completion_tokens"] == 128
        assert "response_format" not in fake.calls[2]["json"]
        assert [event["reason"] for event in r.last_compatibility_events] == [
            "rename_max_tokens",
            "drop_unsupported_fields:response_format",
        ]

    def test_openai_compat_retries_unnamed_strict_validation_optional_fields(self):
        fake = _FakeClient(
            responses=[
                _FakeResponse(
                    400,
                    {
                        "error": {
                            "message": "extra inputs are not permitted",
                        },
                    },
                ),
                _FakeResponse(200, _openai_response("compat ok")),
            ]
        )
        r = OpenAIModelRouter(
            base_url="https://plain-proxy.example/v1",
            client=fake,
        )
        r._build_payload = lambda _request, model: {
            "model": model,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 128,
            "response_format": {"type": "json_object"},
            "stream_options": {"include_usage": True},
            "parallel_tool_calls": True,
            "temperature": 0.2,
        }

        resp = r.call(_req(model="proxy-model"))

        assert resp.text == "compat ok"
        assert len(fake.calls) == 2
        first_payload = fake.calls[0]["json"]
        retry_payload = fake.calls[1]["json"]
        assert "response_format" in first_payload
        assert "stream_options" in first_payload
        assert "parallel_tool_calls" in first_payload
        assert "response_format" not in retry_payload
        assert "stream_options" not in retry_payload
        assert "parallel_tool_calls" not in retry_payload
        assert retry_payload["temperature"] == 0.2
        assert r.last_compatibility_events == [
            {
                "attempt": 1,
                "model": "proxy-model",
                "profile": "openai_compat",
                "reason": (
                    "drop_unsupported_fields:parallel_tool_calls,response_format,stream_options"
                ),
                "removed_fields": [
                    "parallel_tool_calls",
                    "response_format",
                    "stream_options",
                ],
                "added_fields": [],
                "changed_fields": [],
            },
        ]

    def test_qwen_initial_payload_strips_strict_tool_schema_edges(self):
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            client=fake,
        )

        r.call(
            _req(model="qwen-plus").model_copy(
                update={
                    "tools": [
                        ToolSpec(
                            name="read_file",
                            description="Read a project file",
                            input_schema={
                                "$schema": "https://json-schema.org/draft/2020-12/schema",
                                "title": "Read file args",
                                "type": "object",
                                "properties": {
                                    "path": {
                                        "type": "string",
                                        "default": "README.md",
                                        "examples": ["README.md"],
                                        "format": "uri-reference",
                                        "additionalProperties": False,
                                    },
                                },
                                "additionalProperties": True,
                            },
                        ),
                    ],
                },
            ),
        )

        payload = fake.calls[0]["json"]
        params = payload["tools"][0]["function"]["parameters"]
        assert payload["tool_choice"] == "auto"
        assert "$schema" not in params
        assert "title" not in params
        assert "additionalProperties" not in params
        assert "additionalProperties" not in params["properties"]["path"]
        assert "default" not in params["properties"]["path"]
        assert "examples" not in params["properties"]["path"]
        assert "format" not in params["properties"]["path"]
        assert params["properties"]["path"]["type"] == "string"

    def test_minimax_thinking_payload_uses_adaptive_style(self):
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(
            base_url="https://api.minimaxi.com/v1",
            client=fake,
        )
        r.call(
            _req(model="MiniMax-M2").model_copy(
                update={"enable_thinking": True, "reasoning_effort": "high"},
            ),
        )

        payload = fake.calls[0]["json"]
        assert "reasoning_effort" not in payload
        assert payload["thinking"] == {"type": "adaptive"}

    def test_thinking_custom_model_lifts_tiny_token_budget(
        self,
        monkeypatch,
        tmp_path,
    ):
        import json as _json

        custom_models_path = tmp_path / "custom_models.json"
        custom_models_path.write_text(
            _json.dumps(
                {
                    "kimi-code": {
                        "id": "kimi-code",
                        "name": "kimi-code",
                        "provider": "openai",
                        "models": ["kimi-for-coding"],
                        "supports_thinking": True,
                        "omit_sampling_parameters": True,
                    },
                }
            ),
            encoding="utf-8",
        )
        from runtime.platform.process.paths import app_paths

        original = app_paths()

        class _Patched:
            pass

        _Patched.custom_models_path = custom_models_path

        def _getattr(self, name: str) -> object:
            return getattr(original, name)

        _Patched.__getattr__ = _getattr

        monkeypatch.setattr(
            "runtime.platform.process.paths.app_paths",
            lambda: _Patched(),
        )

        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        r.call(_req(model="kimi-for-coding").model_copy(update={"max_tokens": 32}))

        payload = fake.calls[0]["json"]
        assert payload["model"] == "kimi-for-coding"
        assert payload["max_tokens"] == 128
        assert "temperature" not in payload

    def test_stream_thinking_400_retries_without_openai_extension_fields(self):
        import json as _json

        fake = _FakeClient(
            responses=[
                _FakeResponse(400, {"error": {"message": "openai_error"}}),
                _FakeResponse(
                    200,
                    lines=[
                        "data: "
                        + _json.dumps(
                            {
                                "choices": [
                                    {
                                        "delta": {"content": "stream ok"},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                        ),
                        "data: [DONE]",
                    ],
                ),
            ]
        )
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)

        events = list(
            r.call_stream(
                _req(content="hard problem").model_copy(
                    update={
                        "enable_thinking": True,
                        "reasoning_effort": "xhigh",
                    },
                ),
            ),
        )

        assert [event.type for event in events] == ["text_delta", "done"]
        assert events[-1].final.text == "stream ok"
        assert len(fake.calls) == 2
        assert "thinking" in fake.calls[0]["json"]
        assert "thinking" not in fake.calls[1]["json"]
        assert "reasoning_effort" not in fake.calls[1]["json"]

    def test_stream_openai_compat_retries_can_chain_new_error_fields(self):
        import json as _json

        fake = _FakeClient(
            responses=[
                _FakeResponse(
                    400,
                    {
                        "error": {
                            "message": "max_completion_tokens is expected instead of max_tokens",
                        },
                    },
                ),
                _FakeResponse(
                    400,
                    {
                        "error": {
                            "message": "unsupported parameter: response_format",
                        },
                    },
                ),
                _FakeResponse(
                    200,
                    lines=[
                        "data: "
                        + _json.dumps(
                            {
                                "choices": [
                                    {
                                        "delta": {"content": "stream compat ok"},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                        ),
                        "data: [DONE]",
                    ],
                ),
            ]
        )
        r = OpenAIModelRouter(
            base_url="https://plain-proxy.example/v1",
            client=fake,
        )
        r._build_payload = lambda _request, model: {
            "model": model,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 128,
            "response_format": {"type": "json_object"},
        }

        events = list(r.call_stream(_req(model="proxy-model")))

        assert [event.type for event in events] == ["text_delta", "done"]
        assert events[-1].final.text == "stream compat ok"
        assert len(fake.calls) == 3
        assert fake.calls[0]["json"]["stream"] is True
        assert fake.calls[1]["json"]["max_completion_tokens"] == 128
        assert "response_format" in fake.calls[1]["json"]
        assert fake.calls[2]["json"]["max_completion_tokens"] == 128
        assert "response_format" not in fake.calls[2]["json"]
        assert [event["reason"] for event in r.last_compatibility_events] == [
            "rename_max_tokens",
            "drop_unsupported_fields:response_format",
        ]

    def test_final_http_error_includes_compat_retry_summary(self):
        fake = _FakeClient(
            responses=[
                _FakeResponse(
                    400,
                    {
                        "error": {
                            "message": "max_completion_tokens is expected instead of max_tokens",
                        },
                    },
                ),
                _FakeResponse(
                    400,
                    {
                        "error": {"message": "unsupported parameter: response_format"},
                    },
                ),
                _FakeResponse(400, {"error": {"message": "openai_error"}}),
            ]
        )
        r = OpenAIModelRouter(
            base_url="https://plain-proxy.example/v1",
            client=fake,
        )
        r._build_payload = lambda _request, model: {
            "model": model,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 128,
            "response_format": {"type": "json_object"},
        }

        with pytest.raises(OpenAIRouterError) as exc:
            r.call(_req(model="proxy-model"))

        message = str(exc.value)
        assert "已自动尝试 OpenAI 兼容降级" in message
        assert "rename_max_tokens" in message
        assert "drop_unsupported_fields:response_format" in message
        assert "移除:max_tokens" in message
        assert "新增:max_completion_tokens" in message

    def test_stream_final_http_error_includes_compat_retry_summary(self):
        fake = _FakeClient(
            responses=[
                _FakeResponse(
                    400,
                    {
                        "error": {
                            "message": "max_completion_tokens is expected instead of max_tokens",
                        },
                    },
                ),
                _FakeResponse(
                    400,
                    {
                        "error": {"message": "unsupported parameter: response_format"},
                    },
                ),
                _FakeResponse(400, {"error": {"message": "openai_error"}}),
            ]
        )
        r = OpenAIModelRouter(
            base_url="https://plain-proxy.example/v1",
            client=fake,
        )
        r._build_payload = lambda _request, model: {
            "model": model,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 128,
            "response_format": {"type": "json_object"},
        }

        with pytest.raises(OpenAIRouterError) as exc:
            list(r.call_stream(_req(model="proxy-model")))

        message = str(exc.value)
        assert "已自动尝试 OpenAI 兼容降级" in message
        assert "rename_max_tokens" in message
        assert "drop_unsupported_fields:response_format" in message

    def test_reasoning_effort_mapping_to_native_openai(self):
        from runtime.sensing.model_router.openai_router import (
            _openai_reasoning_effort,
        )

        # Native values pass through unchanged.
        assert _openai_reasoning_effort("minimal") == "minimal"
        assert _openai_reasoning_effort("low") == "low"
        assert _openai_reasoning_effort("medium") == "medium"
        assert _openai_reasoning_effort("high") == "high"
        # xhigh/max (and the ultra/extra_high aliases) clamp to high.
        assert _openai_reasoning_effort("xhigh") == "high"
        assert _openai_reasoning_effort("max") == "high"
        assert _openai_reasoning_effort("ultra") == "high"
        assert _openai_reasoning_effort("extra_high") == "high"
        # Unset / unknown fall back to the prior default ("high").
        assert _openai_reasoning_effort(None) == "high"
        assert _openai_reasoning_effort("garbage") == "high"

    def test_extra_headers_merged(self):
        """Implementation note."""
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(
            base_url="https://openrouter.ai/api/v1",
            client=fake,
            extra_headers={"HTTP-Referer": "https://my-app.com", "X-Title": "my-app"},
        )
        r.call(_req())
        hdrs = fake.calls[0]["headers"]
        assert hdrs["HTTP-Referer"] == "https://my-app.com"
        assert hdrs["X-Title"] == "my-app"

    def test_no_auth_header_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        r.call(_req())
        hdrs = fake.calls[0]["headers"]
        assert "Authorization" not in hdrs


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestResponseParsing:
    def test_extracts_content_and_cost(self):
        fake = _FakeClient(
            response=_FakeResponse(
                200,
                _openai_response(text="hi back", prompt_tokens=100, completion_tokens=50),
            )
        )
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        resp = r.call(_req())

        assert resp.text == "hi back"
        assert resp.input_tokens == 100
        assert resp.output_tokens == 50
        assert resp.finish_reason == "stop"
        assert resp.provider == "openai_compat"
        assert resp.model == "gpt-4o-mini"
        assert resp.cost.tokens_in == 100
        assert resp.cost.tokens_out == 50
        assert resp.cost.usd > 0

    def test_list_content_merged(self):
        """Implementation note."""
        payload = _openai_response()
        payload["choices"][0]["message"]["content"] = [
            {"type": "text", "text": "part1 "},
            {"type": "text", "text": "part2"},
            {"type": "image_url", "url": "..."},  # Implementation note.
        ]
        fake = _FakeClient(response=_FakeResponse(200, payload))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        resp = r.call(_req())
        assert resp.text == "part1 part2"

    def test_null_content_with_tool_calls_is_empty_text(self):
        payload = _openai_response(text="")
        payload["choices"][0]["message"]["content"] = None
        payload["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "bb_read", "arguments": '{"key":"plan"}'},
            }
        ]
        fake = _FakeClient(response=_FakeResponse(200, payload))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)

        resp = r.call(_req())

        assert resp.text == ""
        assert [call.name for call in resp.tool_calls] == ["bb_read"]

    def test_python_repr_tool_arguments_are_parsed(self):
        payload = _openai_response(text="")
        payload["choices"][0]["message"]["content"] = None
        payload["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{'path': 'README.md'}"},
            }
        ]
        fake = _FakeClient(response=_FakeResponse(200, payload))
        r = OpenAIModelRouter(
            base_url="https://open.bigmodel.cn/api/paas/v4",
            client=fake,
        )

        resp = r.call(_req(model="glm-4.6"))

        assert resp.tool_calls[0].name == "read_file"
        assert resp.tool_calls[0].input == {"path": "README.md"}

    def test_legacy_function_call_is_parsed_as_tool_call(self):
        payload = _openai_response(text="")
        payload["choices"][0]["finish_reason"] = "function_call"
        payload["choices"][0]["message"]["content"] = None
        payload["choices"][0]["message"]["function_call"] = {
            "name": "read_file",
            "arguments": '{"path":"README.md"}',
        }
        fake = _FakeClient(response=_FakeResponse(200, payload))
        r = OpenAIModelRouter(
            base_url="https://open.bigmodel.cn/api/paas/v4",
            client=fake,
        )

        resp = r.call(_req(model="glm-4.6"))

        assert resp.text == ""
        assert resp.finish_reason == "function_call"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].id == "function_call_0"
        assert resp.tool_calls[0].name == "read_file"
        assert resp.tool_calls[0].input == {"path": "README.md"}

    def test_reasoning_aliases_and_usage_aliases_are_parsed(self):
        payload = _openai_response(text="answer")
        payload["choices"][0]["message"]["reasoning"] = "plan"
        payload["choices"][0]["usage"] = {
            "input_tokens": "11",
            "output_tokens": "6",
        }
        del payload["usage"]
        fake = _FakeClient(response=_FakeResponse(200, payload))
        r = OpenAIModelRouter(base_url="https://api.deepseek.com/v1", client=fake)

        resp = r.call(_req(model="deepseek-reasoner"))

        assert resp.thinking == "plan"
        assert resp.input_tokens == 11
        assert resp.output_tokens == 6

    def test_null_text_block_is_ignored(self):
        payload = _openai_response()
        payload["choices"][0]["message"]["content"] = [
            {"type": "text", "text": None},
            {"type": "text", "text": "usable"},
        ]
        fake = _FakeClient(response=_FakeResponse(200, payload))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)

        resp = r.call(_req())

        assert resp.text == "usable"

    def test_missing_usage_defaults_to_zero(self):
        payload = _openai_response()
        del payload["usage"]
        fake = _FakeClient(response=_FakeResponse(200, payload))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        resp = r.call(_req())
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0
        assert resp.cost.usd == 0.0  # Implementation note.


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestPricing:
    def test_per_model_pricing_overrides_default(self):
        fake = _FakeClient(
            response=_FakeResponse(
                200,
                _openai_response(prompt_tokens=1000, completion_tokens=500),
            )
        )
        r = OpenAIModelRouter(
            base_url="http://x/v1",
            client=fake,
            pricing_per_1k={"gpt-4o-mini": (0.15, 0.60)},  # USD / 1k tokens
        )
        resp = r.call(_req())
        # 1000/1000 * 0.15 + 500/1000 * 0.60 = 0.15 + 0.30 = 0.45
        assert abs(resp.cost.usd - 0.45) < 1e-9

    def test_unknown_model_falls_to_default_rate(self):
        fake = _FakeClient(
            response=_FakeResponse(
                200,
                _openai_response(prompt_tokens=100, completion_tokens=50),
            )
        )
        r = OpenAIModelRouter(
            base_url="http://x/v1",
            client=fake,
            pricing_per_1k={"other-model": (1.0, 2.0)},  # Implementation note.
        )
        resp = r.call(_req())
        # Implementation note.
        assert resp.cost.usd > 0
        assert resp.cost.usd < 0.01  # Implementation note.


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestErrors:
    def test_http_error_raises(self):
        fake = _FakeClient(response=_FakeResponse(500, text="Internal Server Error"))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        with pytest.raises(OpenAIRouterError, match="http_500"):
            r.call(_req())

    def test_http_4xx_raises_with_body(self):
        fake = _FakeClient(response=_FakeResponse(401, text="Invalid API key"))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        with pytest.raises(OpenAIRouterError, match="http_401.*Invalid"):
            r.call(_req())

    def test_http_error_redacts_provider_prefixed_api_keys(self):
        secret = "sk-kimi-" + ("A" * 32)
        fake = _FakeClient(
            response=_FakeResponse(
                401,
                {
                    "error": {"message": f"invalid api key {secret}"},
                },
            )
        )
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)

        with pytest.raises(OpenAIRouterError) as exc:
            r.call(_req())

        message = str(exc.value)
        assert secret not in message
        assert "[REDACTED:api_key]" in message

    def test_http_402_balance_error_is_user_readable(self):
        fake = _FakeClient(
            response=_FakeResponse(
                402,
                {
                    "error": {
                        "code": "402",
                        "message": "Insufficient account balance",
                        "type": "insufficient_balance",
                    }
                },
            )
        )
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        with pytest.raises(OpenAIRouterError) as exc:
            r.call(_req())
        message = str(exc.value)
        assert "http_402" in message
        assert "模型账户余额不足" in message
        assert "Insufficient account balance" not in message

    def test_generic_openai_error_is_diagnostic(self):
        fake = _FakeClient(
            response=_FakeResponse(
                400,
                {
                    "error": {"message": "openai_error"},
                },
            )
        )
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)

        with pytest.raises(OpenAIRouterError) as exc:
            r.call(_req())

        message = str(exc.value)
        assert "http_400" in message
        assert "上游 OpenAI 兼容接口拒绝请求" in message
        assert "切换到可用模型" in message

    def test_network_error_wrapped(self):
        fake = _FakeClient(raise_exc=ConnectionError("refused"))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        with pytest.raises(OpenAIRouterError, match="http_error.*ConnectionError"):
            r.call(_req())

    def test_invalid_json_raises(self):
        resp = _FakeResponse(200, payload=None, text="not json at all")
        fake = _FakeClient(response=resp)
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        with pytest.raises(OpenAIRouterError, match="invalid_json"):
            r.call(_req())

    def test_no_choices_raises(self):
        fake = _FakeClient(response=_FakeResponse(200, {"id": "x", "choices": []}))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        with pytest.raises(OpenAIRouterError, match="no choices"):
            r.call(_req())


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestAuthFromEnv:
    def test_reads_from_default_env_var(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(base_url="http://x/v1", client=fake)
        r.call(_req())
        assert fake.calls[0]["headers"]["Authorization"] == "Bearer sk-from-env"

    def test_custom_env_var(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-123")
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(
            base_url="https://openrouter.ai/api/v1",
            env_var_name="OPENROUTER_API_KEY",
            client=fake,
        )
        r.call(_req())
        assert fake.calls[0]["headers"]["Authorization"] == "Bearer sk-or-123"

    def test_explicit_api_key_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        r = OpenAIModelRouter(
            base_url="http://x/v1",
            api_key="explicit-key",
            client=fake,
        )
        r.call(_req())
        assert fake.calls[0]["headers"]["Authorization"] == "Bearer explicit-key"


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestMultiRouterIntegration:
    def test_default_model_rewrites_via_multi(self):
        """Implementation note."""
        fake = _FakeClient(response=_FakeResponse(200, _openai_response()))
        primary = OpenAIModelRouter(
            base_url="http://ollama/v1",
            default_model="llama3.2:3b",
            client=fake,
        )
        mm = MultiModelRouter(primary=primary)
        # Implementation note.
        mm.call(
            ModelRequest(
                model="caller-specified",
                messages=[Message(role="user", content="hi")],
            )
        )
        assert fake.calls[0]["json"]["model"] == "llama3.2:3b"

    def test_as_fallback_in_multi(self):
        """Implementation note."""
        from runtime.sensing.model_router import ModelRouter

        class _Bad(ModelRouter):
            def call(self, r):
                raise RuntimeError("primary dead")

        fake = _FakeClient(response=_FakeResponse(200, _openai_response("via-fallback")))
        openai = OpenAIModelRouter(
            base_url="http://x/v1",
            default_model="gpt-4o-mini",
            client=fake,
        )
        mm = MultiModelRouter(primary=_Bad(), fallbacks=[openai])
        resp = mm.call(
            ModelRequest(
                model="any",
                messages=[Message(role="user", content="hi")],
            )
        )
        assert resp.text == "via-fallback"
        assert mm.dispatch_log[-1].final_role == "fallback[0]"

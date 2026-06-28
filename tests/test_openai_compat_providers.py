from __future__ import annotations

from runtime.sensing.model_router.openai_compat_providers import (
    extract_openai_compat_reasoning,
    extract_openai_compat_usage,
    known_openai_compat_profiles,
    normalize_openai_compat_payload,
    parse_tool_call_arguments,
    resolve_openai_compat_profile,
    retry_payloads_after_openai_compat_error,
)


def test_domestic_provider_profile_detection_by_base_url() -> None:
    cases = {
        "https://api.deepseek.com/v1": "deepseek",
        "https://api.kimi.com/coding/v1": "kimi_coding",
        "https://api.moonshot.cn/v1": "kimi",
        "https://dashscope.aliyuncs.com/compatible-mode/v1": "qwen",
        "https://open.bigmodel.cn/api/paas/v4": "glm",
        "https://ark.cn-beijing.volces.com/api/v3": "doubao",
        "https://api.minimaxi.com/v1": "minimax",
        "https://api.baichuan-ai.com/v1": "baichuan",
        "https://api.lingyiwanwu.com/v1": "yi",
        "https://api.stepfun.com/v1": "stepfun",
        "https://api.siliconflow.cn/v1": "siliconflow",
        "https://api.hunyuan.cloud.tencent.com/v1": "hunyuan",
        "https://qianfan.baidubce.com/v2": "qianfan",
    }

    for base_url, expected in cases.items():
        assert resolve_openai_compat_profile(base_url).id == expected


def test_domestic_provider_profile_detection_by_model_name() -> None:
    assert resolve_openai_compat_profile("", "qwen-max-latest").id == "qwen"
    assert resolve_openai_compat_profile("", "deepseek-reasoner").id == "deepseek"
    assert resolve_openai_compat_profile("", "doubao-pro-256k").id == "doubao"
    assert resolve_openai_compat_profile("", "MiniMax-M2").id == "minimax"
    assert resolve_openai_compat_profile("", "glm-4.6").id == "glm"


def test_profile_catalog_includes_main_domestic_providers() -> None:
    ids = {profile.id for profile in known_openai_compat_profiles()}
    assert {
        "deepseek",
        "kimi",
        "qwen",
        "glm",
        "doubao",
        "minimax",
        "hunyuan",
        "baichuan",
        "yi",
        "stepfun",
        "siliconflow",
    }.issubset(ids)


def test_kimi_coding_payload_omits_sampling_and_thinking_extensions() -> None:
    profile = resolve_openai_compat_profile("https://api.kimi.com/coding/v1")
    payload = normalize_openai_compat_payload(
        {
            "model": "kimi-k2.7-code",
            "messages": [],
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 128,
            "reasoning_effort": "high",
            "thinking": {"type": "enabled"},
        },
        profile=profile,
    )

    assert payload["model"] == "kimi-k2.7-code"
    assert payload["max_tokens"] == 128
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert "reasoning_effort" not in payload
    assert "thinking" not in payload


def test_kimi_general_clamps_temperature_but_keeps_tools() -> None:
    profile = resolve_openai_compat_profile("https://api.moonshot.cn/v1")
    payload = normalize_openai_compat_payload(
        {
            "model": "moonshot-v1-128k",
            "messages": [],
            "temperature": 1.7,
            "tools": [{"type": "function", "function": {"name": "read"}}],
            "tool_choice": "auto",
        },
        profile=profile,
    )

    assert payload["temperature"] == 1.0
    assert payload["tools"]
    assert payload["tool_choice"] == "auto"


def test_minimax_thinking_uses_adaptive_payload() -> None:
    profile = resolve_openai_compat_profile("https://api.minimaxi.com/v1")
    payload = normalize_openai_compat_payload(
        {
            "model": "MiniMax-M2",
            "messages": [],
            "reasoning_effort": "high",
            "thinking": {"type": "enabled"},
        },
        profile=profile,
    )

    assert "reasoning_effort" not in payload
    assert payload["thinking"] == {"type": "adaptive"}


def test_retry_payloads_drop_incompatible_fields_incrementally() -> None:
    profile = resolve_openai_compat_profile("https://dashscope.aliyuncs.com/compatible-mode/v1")
    payload = {
        "model": "qwen-plus",
        "messages": [],
        "temperature": 0.3,
        "max_tokens": 8,
        "tool_choice": "auto",
        "reasoning_effort": "high",
        "thinking": {"type": "enabled"},
    }

    variants = retry_payloads_after_openai_compat_error(
        payload,
        status_code=400,
        body='{"error":{"message":"unsupported max_completion_tokens or tool_choice"}}',
        profile=profile,
    )

    assert variants[0]["model"] == payload["model"]
    assert "reasoning_effort" not in variants[0]
    assert "thinking" not in variants[0]
    assert any("tool_choice" not in variant for variant in variants)
    assert any("max_completion_tokens" in variant for variant in variants)


def test_tool_schema_retry_strips_additional_properties() -> None:
    profile = resolve_openai_compat_profile("https://api.hunyuan.cloud.tencent.com/v1")
    variants = retry_payloads_after_openai_compat_error(
        {
            "model": "hunyuan-large",
            "messages": [],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "additionalProperties": True,
                        },
                    },
                },
            ],
        },
        status_code=400,
        body="tool schema additionalProperties is not supported",
        profile=profile,
    )

    strict = variants[-1]["tools"][0]["function"]["parameters"]
    assert "additionalProperties" not in strict
    assert strict["properties"]["path"]["type"] == "string"


def test_extract_reasoning_from_common_domestic_response_shapes() -> None:
    assert extract_openai_compat_reasoning({"reasoning_content": "deepseek"}) == "deepseek"
    assert extract_openai_compat_reasoning({"reasoning": "glm"}) == "glm"
    assert extract_openai_compat_reasoning({"thinking": "minimax"}) == "minimax"
    assert (
        extract_openai_compat_reasoning({
            "reasoning_details": [{"text": "step 1"}, {"content": "step 2"}],
        })
        == "step 1\nstep 2"
    )


def test_extract_usage_from_nonstandard_usage_keys() -> None:
    assert extract_openai_compat_usage({
        "choices": [{"usage": {"input_tokens": "12", "output_tokens": 7}}],
    }) == (12, 7)


def test_parse_tool_call_arguments_accepts_json_and_python_repr() -> None:
    assert parse_tool_call_arguments('{"path":"README.md"}') == {"path": "README.md"}
    assert parse_tool_call_arguments("{'path': 'README.md'}") == {"path": "README.md"}
    assert parse_tool_call_arguments({"path": "README.md"}) == {"path": "README.md"}
    assert parse_tool_call_arguments("not-json") == {}

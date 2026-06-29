from __future__ import annotations

import os

import pytest

from runtime.sensing.model_router import Message, ModelRequest, OpenAIModelRouter
from runtime.sensing.model_router.models import ToolSpec

pytestmark = pytest.mark.skipif(
    os.environ.get("OCTOPUS_LIVE_MODEL_SMOKE") != "1",
    reason="set OCTOPUS_LIVE_MODEL_SMOKE=1 and provider API keys to run live smoke tests",
)


PROVIDERS = [
    {
        "id": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": ("DEEPSEEK_API_KEY",),
        "model_env": "DEEPSEEK_SMOKE_MODEL",
        "default_model": "deepseek-chat",
    },
    {
        "id": "kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "api_key_env": ("MOONSHOT_API_KEY", "KIMI_API_KEY"),
        "model_env": "KIMI_SMOKE_MODEL",
        "default_model": "moonshot-v1-8k",
    },
    {
        "id": "kimi_coding",
        "base_url": "https://api.kimi.com/coding/v1",
        "api_key_env": ("KIMI_CODING_API_KEY", "KIMI_API_KEY"),
        "model_env": "KIMI_CODING_SMOKE_MODEL",
        "default_model": "K2.7-Code",
    },
    {
        "id": "qwen",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": ("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
        "model_env": "QWEN_SMOKE_MODEL",
        "default_model": "qwen-plus",
    },
    {
        "id": "glm",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": ("ZHIPU_API_KEY", "GLM_API_KEY"),
        "model_env": "GLM_SMOKE_MODEL",
        "default_model": "glm-4-flash",
    },
    {
        "id": "doubao",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key_env": ("ARK_API_KEY", "DOUBAO_API_KEY", "VOLCENGINE_API_KEY"),
        "model_env": "DOUBAO_SMOKE_MODEL",
        "default_model": "doubao-pro-32k",
    },
]


@pytest.mark.parametrize("provider", PROVIDERS, ids=[item["id"] for item in PROVIDERS])
def test_openai_compat_live_chat_smoke(provider: dict[str, object]) -> None:
    api_key = _first_env(provider["api_key_env"])
    if not api_key:
        pytest.skip(f"missing API key env for {provider['id']}")

    model = os.environ.get(
        str(provider["model_env"]),
        str(provider["default_model"]),
    )
    router = OpenAIModelRouter(
        base_url=str(provider["base_url"]),
        api_key=api_key,
        default_model=model,
        timeout_seconds=30.0,
    )

    response = router.call(
        ModelRequest(
            model=model,
            messages=[Message(role="user", content="Reply with exactly: pong")],
            max_tokens=12,
            temperature=0.0,
        ),
    )

    assert response.text.strip()
    assert response.provider == "openai_compat"


@pytest.mark.skipif(
    os.environ.get("OCTOPUS_LIVE_MODEL_TOOL_SMOKE") != "1",
    reason="set OCTOPUS_LIVE_MODEL_TOOL_SMOKE=1 to run live tool-call probes",
)
@pytest.mark.parametrize("provider", PROVIDERS, ids=[item["id"] for item in PROVIDERS])
def test_openai_compat_live_tool_shape_smoke(provider: dict[str, object]) -> None:
    api_key = _first_env(provider["api_key_env"])
    if not api_key:
        pytest.skip(f"missing API key env for {provider['id']}")

    model = os.environ.get(
        str(provider["model_env"]),
        str(provider["default_model"]),
    )
    router = OpenAIModelRouter(
        base_url=str(provider["base_url"]),
        api_key=api_key,
        default_model=model,
        timeout_seconds=30.0,
    )

    response = router.call(
        ModelRequest(
            model=model,
            messages=[
                Message(
                    role="user",
                    content=(
                        "Use the diagnostic_echo tool exactly once with "
                        'value "pong". Do not answer directly.'
                    ),
                ),
            ],
            tools=[
                ToolSpec(
                    name="diagnostic_echo",
                    description="Echo a short value for compatibility probing.",
                    input_schema={
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                ),
            ],
            max_tokens=48,
            temperature=0.0,
        ),
    )

    assert response.provider == "openai_compat"
    assert response.text.strip() or response.tool_calls


def _first_env(names: object) -> str:
    if not isinstance(names, tuple):
        return ""
    for name in names:
        value = os.environ.get(str(name), "").strip()
        if value:
            return value
    return ""

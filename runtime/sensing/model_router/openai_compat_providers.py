"""Provider profiles for OpenAI-compatible chat-completion gateways.

The OpenAI-compatible label hides a few practical differences across
domestic model providers: some reject OpenAI-only thinking fields, some
prefer stricter sampling payloads, and several expose reasoning text
through provider-specific response keys.  This module keeps those rules
data-driven so ``OpenAIModelRouter`` can stay a normal chat-completions
transport instead of accumulating provider-specific branches.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

ThinkingRequestStyle = Literal["openai", "none", "minimax_adaptive"]


@dataclass(frozen=True)
class OpenAICompatProviderProfile:
    id: str
    display_name: str
    base_url_markers: tuple[str, ...] = ()
    model_markers: tuple[str, ...] = ()
    thinking_request_style: ThinkingRequestStyle = "none"
    omit_sampling_parameters: bool = False
    drop_tool_choice: bool = False
    max_temperature: float | None = None
    unsupported_request_fields: tuple[str, ...] = field(default_factory=tuple)
    retry_without_tool_choice: bool = True
    retry_without_sampling: bool = True
    retry_max_tokens_as_completion_tokens: bool = True


@dataclass(frozen=True)
class OpenAICompatRetryPayload:
    payload: dict[str, Any]
    reason: str
    removed_fields: tuple[str, ...] = ()
    added_fields: tuple[str, ...] = ()
    changed_fields: tuple[str, ...] = ()


GENERIC_OPENAI_PROFILE = OpenAICompatProviderProfile(
    id="openai_compat",
    display_name="OpenAI-compatible",
    thinking_request_style="openai",
)


_PROFILES: tuple[OpenAICompatProviderProfile, ...] = (
    OpenAICompatProviderProfile(
        id="kimi_coding",
        display_name="Kimi Coding",
        base_url_markers=(
            "api.kimi.com/coding",
            "api.moonshot.ai/coding",
            "api.moonshot.cn/coding",
            "/coding/v1",
        ),
        model_markers=("kimi-code", "kimi-for-coding", "k2-code"),
        omit_sampling_parameters=True,
    ),
    OpenAICompatProviderProfile(
        id="deepseek",
        display_name="DeepSeek",
        base_url_markers=("api.deepseek.com",),
        model_markers=("deepseek-", "deepseek/", "deepseek_"),
    ),
    OpenAICompatProviderProfile(
        id="kimi",
        display_name="Kimi / Moonshot",
        base_url_markers=(
            "api.moonshot.cn",
            "api.moonshot.ai",
            "platform.moonshot",
            "api.kimi.com",
        ),
        model_markers=("kimi", "moonshot"),
        max_temperature=1.0,
    ),
    OpenAICompatProviderProfile(
        id="qwen",
        display_name="Alibaba Cloud Qwen / DashScope",
        base_url_markers=("dashscope.aliyuncs.com", "bailian.aliyuncs.com"),
        model_markers=("qwen", "qwq", "qvq", "tongyi"),
    ),
    OpenAICompatProviderProfile(
        id="glm",
        display_name="Zhipu / Z.AI GLM",
        base_url_markers=("open.bigmodel.cn", "api.z.ai"),
        model_markers=("glm-", "chatglm", "zai/", "z.ai/"),
    ),
    OpenAICompatProviderProfile(
        id="doubao",
        display_name="Volcano Engine Doubao / Ark",
        base_url_markers=("ark.cn-beijing.volces.com", "volces.com/api/v3"),
        model_markers=("doubao",),
    ),
    OpenAICompatProviderProfile(
        id="minimax",
        display_name="MiniMax",
        base_url_markers=("api.minimaxi.com", "api.minimax.io", "api.minimax.chat"),
        model_markers=("minimax", "abab"),
        thinking_request_style="minimax_adaptive",
    ),
    OpenAICompatProviderProfile(
        id="hunyuan",
        display_name="Tencent Hunyuan",
        base_url_markers=("api.hunyuan.cloud.tencent.com",),
        model_markers=("hunyuan",),
    ),
    OpenAICompatProviderProfile(
        id="baichuan",
        display_name="Baichuan",
        base_url_markers=("api.baichuan-ai.com", "platform.baichuan-ai.com"),
        model_markers=("baichuan",),
    ),
    OpenAICompatProviderProfile(
        id="yi",
        display_name="01.AI Yi",
        base_url_markers=("api.lingyiwanwu.com", "platform.01.ai"),
        model_markers=("yi-", "yi_", "yi/"),
    ),
    OpenAICompatProviderProfile(
        id="stepfun",
        display_name="StepFun",
        base_url_markers=("api.stepfun.ai", "api.stepfun.com"),
        model_markers=("step-", "stepfun"),
    ),
    OpenAICompatProviderProfile(
        id="siliconflow",
        display_name="SiliconFlow",
        base_url_markers=("api.siliconflow.cn", "api.siliconflow.com"),
        model_markers=("siliconflow/",),
    ),
    OpenAICompatProviderProfile(
        id="qianfan",
        display_name="Baidu Qianfan",
        base_url_markers=("qianfan.baidubce.com",),
        model_markers=("ernie", "wenxin", "qianfan"),
    ),
)


def known_openai_compat_profiles() -> tuple[OpenAICompatProviderProfile, ...]:
    return _PROFILES


def openai_compat_profile_ids() -> tuple[str, ...]:
    return tuple(profile.id for profile in (GENERIC_OPENAI_PROFILE, *_PROFILES))


def resolve_openai_compat_profile(
    base_url: str,
    model: str | None = None,
) -> OpenAICompatProviderProfile:
    base = (base_url or "").strip().lower()
    model_probe = (model or "").strip().lower()

    for profile in _PROFILES:
        if profile.base_url_markers and any(
            marker in base for marker in profile.base_url_markers
        ):
            return profile
    for profile in _PROFILES:
        if profile.model_markers and any(
            marker in model_probe for marker in profile.model_markers
        ):
            return profile
    return GENERIC_OPENAI_PROFILE


def apply_custom_openai_compat_profile(
    entry: dict[str, Any] | None,
    *,
    base_profile: OpenAICompatProviderProfile,
) -> OpenAICompatProviderProfile:
    if not isinstance(entry, dict):
        return base_profile

    profile = _profile_by_id(entry.get("compat_profile")) or base_profile
    updates: dict[str, Any] = {}

    thinking_style = entry.get("thinking_request_style")
    if thinking_style in ("openai", "none", "minimax_adaptive"):
        updates["thinking_request_style"] = thinking_style

    for field_name in (
        "drop_tool_choice",
        "retry_without_tool_choice",
        "retry_without_sampling",
        "retry_max_tokens_as_completion_tokens",
    ):
        value = entry.get(field_name)
        if value is not None:
            updates[field_name] = bool(value)

    omit_sampling = entry.get("omit_sampling_parameters")
    if omit_sampling is not None and (
        omit_sampling is True or _has_explicit_compat_override(entry)
    ):
        updates["omit_sampling_parameters"] = bool(omit_sampling)

    max_temperature = _coerce_float(entry.get("max_temperature"))
    if max_temperature is not None:
        updates["max_temperature"] = max_temperature

    unsupported_fields = _coerce_string_tuple(entry.get("unsupported_request_fields"))
    if unsupported_fields is not None:
        updates["unsupported_request_fields"] = unsupported_fields

    if not updates:
        return profile
    return replace(profile, **updates)


def normalize_openai_compat_payload(
    payload: dict[str, Any],
    *,
    profile: OpenAICompatProviderProfile,
) -> dict[str, Any]:
    normalized = dict(payload)

    for field_name in profile.unsupported_request_fields:
        normalized.pop(field_name, None)

    _normalize_thinking_fields(normalized, profile)

    if profile.omit_sampling_parameters:
        _remove_sampling_parameters(normalized)
    elif profile.max_temperature is not None and "temperature" in normalized:
        value = normalized.get("temperature")
        if isinstance(value, int | float) and value > profile.max_temperature:
            normalized["temperature"] = profile.max_temperature

    if profile.drop_tool_choice:
        normalized.pop("tool_choice", None)

    return normalized


def retry_payloads_after_openai_compat_error(
    payload: dict[str, Any],
    *,
    status_code: int,
    body: str = "",
    profile: OpenAICompatProviderProfile = GENERIC_OPENAI_PROFILE,
) -> list[dict[str, Any]]:
    return [
        item.payload
        for item in plan_openai_compat_retries(
            payload,
            status_code=status_code,
            body=body,
            profile=profile,
        )
    ]


def plan_openai_compat_retries(
    payload: dict[str, Any],
    *,
    status_code: int,
    body: str = "",
    profile: OpenAICompatProviderProfile = GENERIC_OPENAI_PROFILE,
) -> list[OpenAICompatRetryPayload]:
    if status_code not in (400, 422):
        return []

    variants: list[OpenAICompatRetryPayload] = []
    seen: set[str] = {_payload_fingerprint(payload)}
    cascade = dict(payload)
    cascade_reasons: list[str] = []

    def add(reason: str, candidate: dict[str, Any]) -> None:
        fp = _payload_fingerprint(candidate)
        if fp in seen:
            return
        seen.add(fp)
        removed, added, changed = _payload_delta(payload, candidate)
        variants.append(OpenAICompatRetryPayload(
            payload=candidate,
            reason=reason,
            removed_fields=removed,
            added_fields=added,
            changed_fields=changed,
        ))

    lower = (body or "").lower()

    if "reasoning_effort" in payload or "thinking" in payload:
        candidate = dict(payload)
        candidate.pop("reasoning_effort", None)
        candidate.pop("thinking", None)
        add("drop_thinking_fields", candidate)
        cascade.pop("reasoning_effort", None)
        cascade.pop("thinking", None)
        cascade_reasons.append("drop_thinking_fields")

    if profile.retry_without_tool_choice and "tool_choice" in payload:
        candidate = dict(payload)
        candidate.pop("tool_choice", None)
        add("drop_tool_choice", candidate)
        cascade.pop("tool_choice", None)
        cascade_reasons.append("drop_tool_choice")

    if (
        profile.retry_without_sampling
        and _payload_has_sampling(payload)
        and (
            _mentions_any(lower, ("temperature", "top_p", "sampling", "presence_penalty", "frequency_penalty"))
            or profile.omit_sampling_parameters
        )
    ):
        candidate = dict(payload)
        _remove_sampling_parameters(candidate)
        add("drop_sampling_parameters", candidate)
        _remove_sampling_parameters(cascade)
        cascade_reasons.append("drop_sampling_parameters")

    if (
        profile.retry_max_tokens_as_completion_tokens
        and "max_tokens" in payload
        and "max_completion_tokens" not in payload
        and _mentions_any(lower, ("max_completion_tokens", "max_tokens", "max token"))
    ):
        candidate = dict(payload)
        candidate["max_completion_tokens"] = candidate.pop("max_tokens")
        add("rename_max_tokens", candidate)
        if "max_tokens" in cascade and "max_completion_tokens" not in cascade:
            cascade["max_completion_tokens"] = cascade.pop("max_tokens")
        cascade_reasons.append("rename_max_tokens")

    if "tools" in payload and _mentions_any(
        lower,
        ("additionalproperties", "additional properties", "tool schema", "parameters"),
    ):
        candidate = dict(payload)
        candidate["tools"] = _strict_tools(candidate.get("tools"))
        add("strict_tool_schema", candidate)
        cascade["tools"] = _strict_tools(cascade.get("tools"))
        cascade_reasons.append("strict_tool_schema")

    if len(cascade_reasons) > 1:
        add("combined_compatibility_fallback", cascade)

    return variants


def extract_openai_compat_reasoning(message: dict[str, Any]) -> str:
    pieces: list[str] = []
    for key in (
        "reasoning_content",
        "reasoning",
        "thinking",
        "reasoning_text",
        "thought",
    ):
        value = message.get(key)
        rendered = _render_reasoning_value(value)
        if rendered:
            pieces.append(rendered)

    details = _render_reasoning_value(message.get("reasoning_details"))
    if details:
        pieces.append(details)

    return "\n".join(piece for piece in pieces if piece)


def extract_openai_compat_usage(data: dict[str, Any]) -> tuple[int, int]:
    usage = _coerce_usage(data.get("usage"))
    if usage is None:
        choices = data.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                usage = _coerce_usage(choice.get("usage"))
                if usage is not None:
                    break
    if usage is None:
        return 0, 0
    return (
        _int_from_any(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or usage.get("promptTokens")
            or usage.get("inputTokens")
        ),
        _int_from_any(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or usage.get("completionTokens")
            or usage.get("outputTokens")
        ),
    )


def parse_tool_call_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    if not text:
        return {}

    parsed: Any
    try:
        parsed = json.loads(text)
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    try:
        parsed = ast.literal_eval(text)
        return parsed if isinstance(parsed, dict) else {}
    except (SyntaxError, ValueError, TypeError):
        return {}


def _normalize_thinking_fields(
    payload: dict[str, Any],
    profile: OpenAICompatProviderProfile,
) -> None:
    if "reasoning_effort" not in payload and "thinking" not in payload:
        return
    if profile.thinking_request_style == "openai":
        return
    if profile.thinking_request_style == "minimax_adaptive":
        payload.pop("reasoning_effort", None)
        payload["thinking"] = {"type": "adaptive"}
        return
    payload.pop("reasoning_effort", None)
    payload.pop("thinking", None)


def _remove_sampling_parameters(payload: dict[str, Any]) -> None:
    for key in (
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "logit_bias",
        "seed",
    ):
        payload.pop(key, None)


def _payload_has_sampling(payload: dict[str, Any]) -> bool:
    return any(
        key in payload
        for key in (
            "temperature",
            "top_p",
            "presence_penalty",
            "frequency_penalty",
            "logit_bias",
            "seed",
        )
    )


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def _payload_delta(
    original: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    original_keys = set(original)
    candidate_keys = set(candidate)
    removed = tuple(sorted(original_keys - candidate_keys))
    added = tuple(sorted(candidate_keys - original_keys))
    changed = tuple(
        sorted(
            key
            for key in original_keys & candidate_keys
            if original.get(key) != candidate.get(key)
        )
    )
    return removed, added, changed


def _profile_by_id(value: Any) -> OpenAICompatProviderProfile | None:
    if not isinstance(value, str) or not value.strip():
        return None
    target = value.strip().lower().replace("-", "_")
    if target == GENERIC_OPENAI_PROFILE.id:
        return GENERIC_OPENAI_PROFILE
    for profile in _PROFILES:
        if profile.id == target:
            return profile
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_string_tuple(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        return None
    return tuple(item for item in items if item)


def _has_explicit_compat_override(entry: dict[str, Any]) -> bool:
    if _profile_by_id(entry.get("compat_profile")) is not None:
        return True
    return any(
        entry.get(field_name) is not None
        for field_name in (
            "thinking_request_style",
            "drop_tool_choice",
            "retry_without_tool_choice",
            "retry_without_sampling",
            "retry_max_tokens_as_completion_tokens",
            "max_temperature",
            "unsupported_request_fields",
        )
    )


def _mentions_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle in haystack for needle in needles)


def _strict_tools(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    tools: list[Any] = []
    for tool in value:
        if not isinstance(tool, dict):
            tools.append(tool)
            continue
        copied = dict(tool)
        fn = copied.get("function")
        if isinstance(fn, dict):
            fn_copy = dict(fn)
            params = fn_copy.get("parameters")
            if isinstance(params, dict):
                fn_copy["parameters"] = _strip_additional_properties(params)
            copied["function"] = fn_copy
        tools.append(copied)
    return tools


def _strip_additional_properties(schema: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if isinstance(value, dict):
            out[key] = _strip_additional_properties(value)
        elif isinstance(value, list):
            out[key] = [
                _strip_additional_properties(item)
                if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            out[key] = value
    return out


def _render_reasoning_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, int | float | bool):
        return str(value)
    if isinstance(value, list):
        pieces = [_render_reasoning_detail(item) for item in value]
        return "\n".join(piece for piece in pieces if piece)
    if isinstance(value, dict):
        return _render_reasoning_detail(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def _render_reasoning_detail(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return _render_reasoning_value(value)
    for key in ("text", "content", "reasoning", "summary", "delta"):
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
    return json.dumps(value, ensure_ascii=False, default=str)


def _coerce_usage(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _int_from_any(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(value or ""))
        return int(match.group(0)) if match else 0


__all__ = [
    "GENERIC_OPENAI_PROFILE",
    "OpenAICompatProviderProfile",
    "OpenAICompatRetryPayload",
    "apply_custom_openai_compat_profile",
    "extract_openai_compat_reasoning",
    "extract_openai_compat_usage",
    "known_openai_compat_profiles",
    "normalize_openai_compat_payload",
    "openai_compat_profile_ids",
    "parse_tool_call_arguments",
    "plan_openai_compat_retries",
    "resolve_openai_compat_profile",
    "retry_payloads_after_openai_compat_error",
]

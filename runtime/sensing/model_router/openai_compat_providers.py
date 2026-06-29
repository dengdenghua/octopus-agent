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
    strict_tool_schema: bool = False
    max_temperature: float | None = None
    unsupported_request_fields: tuple[str, ...] = field(default_factory=tuple)
    retry_without_tool_choice: bool = True
    retry_without_sampling: bool = True
    retry_max_tokens_as_completion_tokens: bool = True
    compatibility_notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OpenAICompatRetryPayload:
    payload: dict[str, Any]
    reason: str
    removed_fields: tuple[str, ...] = ()
    added_fields: tuple[str, ...] = ()
    changed_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpenAICompatProfileProbe:
    profile_id: str
    base_url: str
    model: str
    smoke_provider_configured: bool
    base_url_resolves_to: str
    model_resolves_to: str


GENERIC_OPENAI_PROFILE = OpenAICompatProviderProfile(
    id="openai_compat",
    display_name="OpenAI-compatible",
    thinking_request_style="openai",
)

REQUIRED_DOMESTIC_PROFILE_IDS: tuple[str, ...] = (
    "kimi_coding",
    "kimi",
    "deepseek",
    "qwen",
    "glm",
    "doubao",
    "minimax",
    "hunyuan",
    "baichuan",
    "yi",
    "stepfun",
    "siliconflow",
    "qianfan",
)

_OPTIONAL_REQUEST_FIELD_FALLBACKS = (
    "parallel_tool_calls",
    "response_format",
    "stream_options",
    "logprobs",
    "top_logprobs",
)

_TOOL_REQUEST_FIELDS = ("tools", "tool_choice", "parallel_tool_calls")

_STRICT_SCHEMA_DROPPED_KEYS = frozenset({
    "$anchor",
    "$comment",
    "$id",
    "$schema",
    "default",
    "deprecated",
    "discriminator",
    "example",
    "examples",
    "externalDocs",
    "format",
    "nullable",
    "readOnly",
    "title",
    "writeOnly",
    "xml",
})


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
        model_markers=(
            "kimi-code",
            "kimi-for-coding",
            "kimi-coding",
            "k2-code",
            "k2 code",
            "k2.7-code",
            "k2.7 code",
            "k2.7code",
            "k2.7_code",
        ),
        omit_sampling_parameters=True,
        unsupported_request_fields=("parallel_tool_calls",),
        compatibility_notes=(
            "coding endpoint rejects sampling knobs",
            "drops OpenAI reasoning/thinking extensions",
        ),
    ),
    OpenAICompatProviderProfile(
        id="deepseek",
        display_name="DeepSeek",
        base_url_markers=("api.deepseek.com",),
        model_markers=("deepseek-", "deepseek/", "deepseek_"),
        compatibility_notes=(
            "reasoning text may arrive as reasoning_content",
            "some deployments prefer max_completion_tokens on retry",
        ),
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
        compatibility_notes=("temperature is clamped to 1.0",),
    ),
    OpenAICompatProviderProfile(
        id="qwen",
        display_name="Alibaba Cloud Qwen / DashScope",
        base_url_markers=("dashscope.aliyuncs.com", "bailian.aliyuncs.com"),
        model_markers=("qwen", "qwq", "qvq", "tongyi"),
        strict_tool_schema=True,
        unsupported_request_fields=("parallel_tool_calls",),
        compatibility_notes=(
            "DashScope-compatible mode may reject OpenAI-only fields",
            "max_tokens can be retried as max_completion_tokens",
            "tool schemas are normalized for stricter compatible-mode validation",
        ),
    ),
    OpenAICompatProviderProfile(
        id="glm",
        display_name="Zhipu / Z.AI GLM",
        base_url_markers=("open.bigmodel.cn", "api.z.ai"),
        model_markers=("glm-", "chatglm", "zai/", "z.ai/"),
        strict_tool_schema=True,
        unsupported_request_fields=("parallel_tool_calls",),
        compatibility_notes=(
            "GLM reasoning may arrive as reasoning",
            "legacy function_call responses are accepted",
            "parallel_tool_calls is removed for OpenAI-compatible strict mode",
        ),
    ),
    OpenAICompatProviderProfile(
        id="doubao",
        display_name="Volcano Engine Doubao / Ark",
        base_url_markers=("ark.cn-beijing.volces.com", "volces.com/api/v3"),
        model_markers=("doubao",),
        strict_tool_schema=True,
        unsupported_request_fields=("parallel_tool_calls",),
        compatibility_notes=(
            "Ark OpenAI-compatible endpoint uses strict request validation",
            "tool schemas are normalized before the first request",
        ),
    ),
    OpenAICompatProviderProfile(
        id="minimax",
        display_name="MiniMax",
        base_url_markers=("api.minimaxi.com", "api.minimax.io", "api.minimax.chat"),
        model_markers=("minimax", "abab"),
        thinking_request_style="minimax_adaptive",
        strict_tool_schema=True,
        unsupported_request_fields=("parallel_tool_calls",),
        compatibility_notes=(
            "thinking requests are translated to MiniMax adaptive style",
            "parallel tool-call hints are removed for stricter gateways",
        ),
    ),
    OpenAICompatProviderProfile(
        id="hunyuan",
        display_name="Tencent Hunyuan",
        base_url_markers=("api.hunyuan.cloud.tencent.com",),
        model_markers=("hunyuan",),
        strict_tool_schema=True,
        unsupported_request_fields=("parallel_tool_calls",),
        compatibility_notes=("tool schemas may require additionalProperties stripping",),
    ),
    OpenAICompatProviderProfile(
        id="baichuan",
        display_name="Baichuan",
        base_url_markers=("api.baichuan-ai.com", "platform.baichuan-ai.com"),
        model_markers=("baichuan",),
        strict_tool_schema=True,
        unsupported_request_fields=("parallel_tool_calls",),
        compatibility_notes=("falls back by removing strict OpenAI-only fields",),
    ),
    OpenAICompatProviderProfile(
        id="yi",
        display_name="01.AI Yi",
        base_url_markers=("api.lingyiwanwu.com", "platform.01.ai"),
        model_markers=("yi-", "yi_", "yi/"),
        strict_tool_schema=True,
        unsupported_request_fields=("parallel_tool_calls",),
        compatibility_notes=("falls back by removing strict OpenAI-only fields",),
    ),
    OpenAICompatProviderProfile(
        id="stepfun",
        display_name="StepFun",
        base_url_markers=("api.stepfun.ai", "api.stepfun.com"),
        model_markers=("step-", "stepfun"),
        strict_tool_schema=True,
        unsupported_request_fields=("parallel_tool_calls",),
        compatibility_notes=("falls back by removing strict OpenAI-only fields",),
    ),
    OpenAICompatProviderProfile(
        id="siliconflow",
        display_name="SiliconFlow",
        base_url_markers=("api.siliconflow.cn", "api.siliconflow.com"),
        model_markers=("siliconflow/",),
        strict_tool_schema=True,
        unsupported_request_fields=("parallel_tool_calls",),
        compatibility_notes=("proxy-hosted models vary; diagnostics surface normalized payloads",),
    ),
    OpenAICompatProviderProfile(
        id="qianfan",
        display_name="Baidu Qianfan",
        base_url_markers=("qianfan.baidubce.com",),
        model_markers=("ernie", "wenxin", "qianfan"),
        strict_tool_schema=True,
        unsupported_request_fields=("parallel_tool_calls",),
        compatibility_notes=("falls back by removing strict OpenAI-only fields",),
    ),
)


def known_openai_compat_profiles() -> tuple[OpenAICompatProviderProfile, ...]:
    return _PROFILES


def openai_compat_profile_ids() -> tuple[str, ...]:
    return tuple(profile.id for profile in (GENERIC_OPENAI_PROFILE, *_PROFILES))


def sample_openai_compat_profile_probe(
    profile: OpenAICompatProviderProfile,
) -> OpenAICompatProfileProbe:
    smoke = _smoke_provider_by_id().get(profile.id)
    base_url = (
        smoke.base_url
        if smoke is not None
        else _sample_base_url_from_profile_markers(profile)
    )
    model = (
        smoke.default_model
        if smoke is not None
        else _sample_model_from_profile_markers(profile)
    )
    return OpenAICompatProfileProbe(
        profile_id=profile.id,
        base_url=base_url,
        model=model,
        smoke_provider_configured=smoke is not None,
        base_url_resolves_to=resolve_openai_compat_profile(base_url).id,
        model_resolves_to=resolve_openai_compat_profile("", model).id,
    )


def audit_openai_compat_profile_catalog(
    required_profile_ids: tuple[str, ...] = REQUIRED_DOMESTIC_PROFILE_IDS,
) -> dict[str, Any]:
    profiles = list(known_openai_compat_profiles())
    profile_ids = [profile.id for profile in profiles]
    smoke_provider_ids = list(_smoke_provider_by_id())
    probes = [sample_openai_compat_profile_probe(profile) for profile in profiles]
    resolver_mismatches = [
        {
            "profile_id": probe.profile_id,
            "base_url": probe.base_url,
            "model": probe.model,
            "base_url_resolves_to": probe.base_url_resolves_to,
            "model_resolves_to": probe.model_resolves_to,
        }
        for probe in probes
        if probe.base_url_resolves_to != probe.profile_id
    ]
    model_alias_mismatches = [
        {
            "profile_id": probe.profile_id,
            "base_url": probe.base_url,
            "model": probe.model,
            "model_resolves_to": probe.model_resolves_to,
            "reason": "model_id_looks_like_upstream_model_on_aggregator",
        }
        for probe in probes
        if probe.model_resolves_to != probe.profile_id
    ]
    missing_required = [
        profile_id for profile_id in required_profile_ids if profile_id not in profile_ids
    ]
    missing_smoke = [
        profile_id for profile_id in profile_ids if profile_id not in smoke_provider_ids
    ]
    orphan_smoke = [
        provider_id for provider_id in smoke_provider_ids if provider_id not in profile_ids
    ]
    smoke_mismatches = [
        {
            "profile_id": probe.profile_id,
            "base_url": probe.base_url,
            "model": probe.model,
            "base_url_resolves_to": probe.base_url_resolves_to,
            "model_resolves_to": probe.model_resolves_to,
        }
        for probe in probes
        if probe.smoke_provider_configured
        and probe.base_url_resolves_to != probe.profile_id
    ]
    contract_probes = [
        probe_openai_compat_request_contract(
            _profile_by_id(probe.profile_id) or GENERIC_OPENAI_PROFILE,
            probe.model,
        )
        for probe in probes
    ]
    contract_mismatches = [
        {
            "profile_id": probe["profile_id"],
            "model": probe["model"],
            "risk_level": probe["risk_level"],
            "reason": "core_request_contract_changed",
        }
        for probe in contract_probes
        if not probe["contract_ready"]
    ]
    catalog_ready = (
        not missing_required
        and not missing_smoke
        and not orphan_smoke
        and not resolver_mismatches
        and not contract_mismatches
    )
    return {
        "schema": "octopus.openai_compat_profile_audit.v1",
        "catalog_ready": catalog_ready,
        "profile_count": len(profile_ids),
        "profile_ids": profile_ids,
        "required_profile_ids": list(required_profile_ids),
        "missing_required_profile_ids": missing_required,
        "smoke_provider_ids": smoke_provider_ids,
        "missing_smoke_provider_ids": missing_smoke,
        "orphan_smoke_provider_ids": orphan_smoke,
        "resolver_mismatches": resolver_mismatches,
        "model_alias_mismatches": model_alias_mismatches,
        "smoke_resolver_mismatches": smoke_mismatches,
        "request_contract_mismatches": contract_mismatches,
        "request_contract_probes": contract_probes,
        "sample_probes": [
            {
                "profile_id": probe.profile_id,
                "base_url": probe.base_url,
                "model": probe.model,
                "smoke_provider_configured": probe.smoke_provider_configured,
                "base_url_resolves_to": probe.base_url_resolves_to,
                "model_resolves_to": probe.model_resolves_to,
            }
            for probe in probes
        ],
    }


def sample_openai_compat_contract_payload(model: str) -> dict[str, Any]:
    """Representative dry-run request covering common compat edge-fields."""
    return {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "temperature": 0.7,
        "top_p": 0.9,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "max_tokens": 8,
        "stream": True,
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": "high",
        "thinking": {"type": "enabled"},
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "diagnostic_ping",
                    "description": "No-op compatibility probe.",
                    "parameters": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "title": "Diagnostic ping input",
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
                },
            },
        ],
        "tool_choice": "auto",
        "parallel_tool_calls": True,
    }


def probe_openai_compat_request_contract(
    profile: OpenAICompatProviderProfile,
    model: str,
) -> dict[str, Any]:
    """Dry-run request contract probe for a provider/profile pair.

    This never calls the provider. It normalizes a representative request,
    plans retries for a representative strict-validation error, and reports
    which capabilities are preserved, normalized, or likely degraded.
    """
    original = sample_openai_compat_contract_payload(model)
    normalized = normalize_openai_compat_payload(original, profile=profile)
    removed, added, changed = _payload_delta(original, normalized)
    retry_plan = plan_openai_compat_retries(
        normalized,
        status_code=400,
        body=(
            "unsupported reasoning_effort thinking tool_choice "
            "temperature top_p max_completion_tokens stream_options "
            "response_format additionalProperties extra inputs are not "
            "permitted unsupported parameter"
        ),
        profile=profile,
    )
    summary = _request_contract_summary(
        normalized=normalized,
        removed_fields=removed,
        changed_fields=changed,
        retry_plan=retry_plan,
        compat_score=_compatibility_score(profile),
    )
    core_fields_ready = {"model", "messages"}.issubset(normalized)
    return {
        "schema": "octopus.openai_compat_request_contract_probe.v1",
        "profile_id": profile.id,
        "model": model,
        "dry_run": True,
        "contract_ready": bool(core_fields_ready),
        "risk_level": summary["risk_level"],
        "risk_reasons": summary["risk_reasons"],
        "capability_matrix": summary["capability_matrix"],
        "original_fields": sorted(original),
        "normalized_fields": sorted(normalized),
        "removed_fields": list(removed),
        "added_fields": list(added),
        "changed_fields": list(changed),
        "normalized_payload": normalized,
        "fallback_retries": [
            {
                "reason": item.reason,
                "removed_fields": list(item.removed_fields),
                "added_fields": list(item.added_fields),
                "changed_fields": list(item.changed_fields),
                "payload_fields": sorted(item.payload),
            }
            for item in retry_plan
        ],
    }


def describe_openai_compat_profile(
    profile: OpenAICompatProviderProfile,
) -> dict[str, Any]:
    """Machine-readable summary for UI/API compatibility diagnostics."""
    normalization_hints: list[str] = []
    if profile.thinking_request_style != "openai":
        normalization_hints.append(f"thinking:{profile.thinking_request_style}")
    if profile.omit_sampling_parameters:
        normalization_hints.append("drop_sampling_parameters")
    if profile.drop_tool_choice:
        normalization_hints.append("drop_tool_choice")
    if profile.strict_tool_schema:
        normalization_hints.append("strict_tool_schema")
    if profile.max_temperature is not None:
        normalization_hints.append(f"max_temperature:{profile.max_temperature:g}")
    for field_name in profile.unsupported_request_fields:
        normalization_hints.append(f"drop:{field_name}")
    if profile.retry_without_tool_choice:
        normalization_hints.append("retry_without_tool_choice")
    if profile.retry_without_sampling:
        normalization_hints.append("retry_without_sampling")
    if profile.retry_max_tokens_as_completion_tokens:
        normalization_hints.append("retry_max_tokens_as_completion_tokens")
    score = _compatibility_score(profile)
    return {
        "id": profile.id,
        "display_name": profile.display_name,
        "compat_score": score,
        "normalization_hints": normalization_hints,
        "notes": list(profile.compatibility_notes),
    }


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
        "strict_tool_schema",
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

    if profile.strict_tool_schema and "tools" in normalized:
        normalized["tools"] = _strict_tools(normalized.get("tools"))

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
    strict_validation = _mentions_any(
        lower,
        (
            "unsupported parameter",
            "unsupported field",
            "unsupported request",
            "unrecognized field",
            "unknown field",
            "unknown parameter",
            "extra inputs are not permitted",
            "extra_forbidden",
            "invalid parameter",
        ),
    )

    if "reasoning_effort" in payload or "thinking" in payload:
        candidate = dict(payload)
        candidate.pop("reasoning_effort", None)
        candidate.pop("thinking", None)
        add("drop_thinking_fields", candidate)
        cascade.pop("reasoning_effort", None)
        cascade.pop("thinking", None)
        cascade_reasons.append("drop_thinking_fields")

    optional_fields = _mentioned_payload_fields(
        lower,
        payload,
        _OPTIONAL_REQUEST_FIELD_FALLBACKS,
    )
    if optional_fields:
        candidate = dict(payload)
        for field_name in optional_fields:
            candidate.pop(field_name, None)
            cascade.pop(field_name, None)
        add(f"drop_unsupported_fields:{','.join(optional_fields)}", candidate)
        cascade_reasons.append("drop_unsupported_fields")

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
            or strict_validation
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

    if (
        profile.retry_max_tokens_as_completion_tokens
        and "max_completion_tokens" in payload
        and "max_tokens" not in payload
        and _mentions_any(lower, ("max_completion_tokens", "max_tokens", "max token"))
    ):
        candidate = dict(payload)
        candidate["max_tokens"] = candidate.pop("max_completion_tokens")
        add("rename_max_completion_tokens", candidate)
        if "max_completion_tokens" in cascade and "max_tokens" not in cascade:
            cascade["max_tokens"] = cascade.pop("max_completion_tokens")
        cascade_reasons.append("rename_max_completion_tokens")

    if "tools" in payload and _mentions_any(
        lower,
        ("additionalproperties", "additional properties", "tool schema", "parameters"),
    ):
        candidate = dict(payload)
        candidate["tools"] = _strict_tools(candidate.get("tools"))
        add("strict_tool_schema", candidate)
        cascade["tools"] = _strict_tools(cascade.get("tools"))
        cascade_reasons.append("strict_tool_schema")

    if "tools" in payload and _mentions_tool_use_unsupported(lower):
        candidate = dict(payload)
        for field_name in _TOOL_REQUEST_FIELDS:
            candidate.pop(field_name, None)
            cascade.pop(field_name, None)
        add("drop_tools", candidate)
        cascade_reasons.append("drop_tools")

    if len(cascade_reasons) > 1:
        add("combined_compatibility_fallback", cascade)

    return variants


def _compatibility_score(profile: OpenAICompatProviderProfile) -> int:
    score = 100
    if profile.thinking_request_style != "openai":
        score -= 6
    if profile.omit_sampling_parameters:
        score -= 10
    if profile.drop_tool_choice:
        score -= 8
    if profile.strict_tool_schema:
        score -= 3
    if profile.max_temperature is not None:
        score -= 3
    score -= min(12, len(profile.unsupported_request_fields) * 3)
    if profile.retry_without_tool_choice:
        score -= 2
    if profile.retry_without_sampling:
        score -= 2
    if profile.retry_max_tokens_as_completion_tokens:
        score -= 2
    return max(60, score)


def _request_contract_summary(
    *,
    normalized: dict[str, Any],
    removed_fields: tuple[str, ...],
    changed_fields: tuple[str, ...],
    retry_plan: list[OpenAICompatRetryPayload],
    compat_score: int,
) -> dict[str, Any]:
    retry_removed: set[str] = set()
    retry_changed: set[str] = set()
    retry_reasons: list[str] = []
    for retry in retry_plan:
        retry_reasons.append(str(retry.reason or ""))
        retry_removed.update(str(v) for v in retry.removed_fields or ())
        retry_changed.update(str(v) for v in retry.changed_fields or ())

    removed = set(removed_fields)
    changed = set(changed_fields)
    matrix = [
        _compat_capability_row(
            "chat_completion",
            "pass" if {"model", "messages"}.issubset(normalized) else "warn",
            [
                "model preserved" if "model" in normalized else "model missing",
                (
                    "messages preserved"
                    if "messages" in normalized
                    else "messages missing"
                ),
            ],
            ["dry_run_request_shape_only"],
        ),
        _compat_capability_row(
            "streaming",
            "warn" if "stream_options" in retry_removed else "unverified",
            [
                (
                    "stream flag preserved"
                    if normalized.get("stream") is True
                    else "stream flag not preserved"
                ),
                (
                    "stream_options preserved"
                    if "stream_options" in normalized
                    else "stream_options absent"
                ),
            ],
            [
                "dry_run_does_not_open_stream",
                *(
                    ["strict fallback may drop stream_options"]
                    if "stream_options" in retry_removed
                    else []
                ),
            ],
        ),
        _compat_capability_row(
            "tool_calling",
            "warn" if {"tools", "tool_choice"} & (removed | retry_removed) else "pass",
            [
                "tools preserved" if "tools" in normalized else "tools removed",
                (
                    "tool_choice preserved"
                    if "tool_choice" in normalized
                    else "tool_choice absent"
                ),
            ],
            [
                *(
                    ["parallel_tool_calls removed"]
                    if "parallel_tool_calls" in removed
                    else []
                ),
                *(["tool schema normalized"] if "tools" in changed else []),
                *(
                    ["fallback may drop tool_choice"]
                    if "tool_choice" in retry_removed
                    else []
                ),
                *(
                    ["fallback may drop tools"]
                    if "tools" in retry_removed
                    else []
                ),
            ],
        ),
        _compat_capability_row(
            "structured_output",
            "warn" if "response_format" in retry_removed else "unverified",
            [
                (
                    "response_format preserved"
                    if "response_format" in normalized
                    else "response_format absent"
                ),
            ],
            [
                "dry_run_does_not_validate_response_schema",
                *(
                    ["strict fallback may drop response_format"]
                    if "response_format" in retry_removed
                    else []
                ),
            ],
        ),
        _compat_capability_row(
            "reasoning_request",
            "warn"
            if {"reasoning_effort", "thinking"} & (
                removed | changed | retry_removed | retry_changed
            )
            else "pass",
            [
                (
                    "reasoning_effort preserved"
                    if "reasoning_effort" in normalized
                    else "reasoning_effort absent"
                ),
                "thinking preserved" if "thinking" in normalized else "thinking absent",
            ],
            [
                *(
                    ["reasoning request normalized"]
                    if {"reasoning_effort", "thinking"} & (removed | changed)
                    else []
                ),
                *(
                    ["fallback may drop reasoning fields"]
                    if {"reasoning_effort", "thinking"} & retry_removed
                    else []
                ),
            ],
        ),
        _compat_capability_row(
            "usage_accounting",
            "warn" if "stream_options" in retry_removed else "unverified",
            [
                (
                    "stream usage requested"
                    if normalized.get("stream_options", {}).get("include_usage") is True
                    else "stream usage not requested"
                ),
            ],
            [
                "response_usage_shape_not_called_in_dry_run",
                *(
                    ["strict fallback may drop stream usage"]
                    if "stream_options" in retry_removed
                    else []
                ),
            ],
        ),
        _compat_capability_row(
            "fallback_retries",
            "pass" if retry_plan else "unverified",
            [
                f"{len(retry_plan)} retry variants planned",
                *retry_reasons[:4],
            ],
            ["dry_run_representative_400"],
        ),
    ]

    risk_reasons: list[str] = []
    risk_points = 0

    def add_risk(reason: str, points: int = 1) -> None:
        nonlocal risk_points
        if reason not in risk_reasons:
            risk_reasons.append(reason)
        risk_points += points

    if compat_score < 80:
        add_risk(f"compat_score:{compat_score}", 2 if compat_score < 70 else 1)
    if {"reasoning_effort", "thinking"} & (removed | changed):
        add_risk("reasoning_request_normalized", 1)
    if {"temperature", "top_p", "presence_penalty", "frequency_penalty"} & removed:
        add_risk("sampling_parameters_removed", 1)
    if "parallel_tool_calls" in removed:
        add_risk("parallel_tool_calls_removed", 1)
    if "tool_choice" in removed:
        add_risk("tool_calling_control_removed", 2)
    if "tools" in changed:
        add_risk("tool_schema_normalized", 1)
    if {"tool_choice", "tools"} & retry_removed:
        add_risk("tool_calling_fallback_degrades_control", 1)
    if {"response_format", "stream_options"} & retry_removed:
        add_risk("strict_provider_may_drop_optional_features", 0)
    if {"model", "messages"} & removed:
        add_risk("core_request_field_removed", 3)
    if "tools" in removed:
        add_risk("tool_calling_removed", 2)

    if risk_points >= 5:
        risk_level = "high"
    elif risk_points >= 2:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "risk_level": risk_level,
        "risk_reasons": risk_reasons,
        "capability_matrix": matrix,
    }


def _compat_capability_row(
    capability: str,
    status: str,
    evidence: list[str],
    notes: list[str],
) -> dict[str, Any]:
    return {
        "capability": capability,
        "status": status,
        "evidence": [item for item in evidence if item],
        "notes": [item for item in notes if item],
    }


def _smoke_provider_by_id() -> dict[str, Any]:
    try:
        from runtime.sensing.model_router.openai_compat_smoke_matrix import (
            openai_compat_smoke_providers,
        )
    except Exception:  # pragma: no cover - optional module import guard
        return {}
    return {provider.id: provider for provider in openai_compat_smoke_providers()}


def _sample_model_from_profile_markers(profile: OpenAICompatProviderProfile) -> str:
    markers = tuple(profile.model_markers or ())
    marker = str(markers[0] if markers else profile.id).rstrip("-_/ ")
    return marker or profile.id


def _sample_base_url_from_profile_markers(profile: OpenAICompatProviderProfile) -> str:
    markers = tuple(profile.base_url_markers or ())
    marker = str(markers[0] if markers else "example.com/v1")
    if marker.startswith("http://") or marker.startswith("https://"):
        return marker.rstrip("/")
    if marker.startswith("/"):
        return f"https://api.example.com{marker}".rstrip("/")
    return f"https://{marker.rstrip('/')}"


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
            "strict_tool_schema",
            "retry_without_tool_choice",
            "retry_without_sampling",
            "retry_max_tokens_as_completion_tokens",
            "max_temperature",
            "unsupported_request_fields",
        )
    )


def _mentions_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle in haystack for needle in needles)


def _mentioned_payload_fields(
    haystack: str,
    payload: dict[str, Any],
    field_names: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        field_name
        for field_name in field_names
        if field_name in payload and _mentions_field(haystack, field_name)
    )


def _mentions_field(haystack: str, field_name: str) -> bool:
    needle = re.escape(field_name)
    return re.search(rf"(^|[^a-z0-9_]){needle}([^a-z0-9_]|$)", haystack) is not None


def _mentions_tool_use_unsupported(haystack: str) -> bool:
    return _mentions_any(
        haystack,
        (
            "tools is not supported",
            "tools are not supported",
            "tool calls are not supported",
            "tool calling is not supported",
            "function calling is not supported",
            "function calls are not supported",
            "unsupported parameter: tools",
            "unsupported field: tools",
            "unknown field: tools",
            "unrecognized field: tools",
        ),
    )


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
                fn_copy["parameters"] = _normalize_strict_json_schema(params)
            copied["function"] = fn_copy
        tools.append(copied)
    return tools


def _normalize_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "additionalProperties" or key in _STRICT_SCHEMA_DROPPED_KEYS:
            continue
        if isinstance(value, dict):
            out[key] = _normalize_strict_json_schema(value)
        elif isinstance(value, list):
            out[key] = [
                _normalize_strict_json_schema(item)
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
    "OpenAICompatProfileProbe",
    "OpenAICompatRetryPayload",
    "REQUIRED_DOMESTIC_PROFILE_IDS",
    "apply_custom_openai_compat_profile",
    "audit_openai_compat_profile_catalog",
    "describe_openai_compat_profile",
    "extract_openai_compat_reasoning",
    "extract_openai_compat_usage",
    "known_openai_compat_profiles",
    "normalize_openai_compat_payload",
    "openai_compat_profile_ids",
    "parse_tool_call_arguments",
    "plan_openai_compat_retries",
    "resolve_openai_compat_profile",
    "retry_payloads_after_openai_compat_error",
    "sample_openai_compat_profile_probe",
]

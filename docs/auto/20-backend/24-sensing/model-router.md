---
type: "SensingSubsystem"
title: "Sensing · Model Router"
description: "ModelRouter 抽象 · Anthropic / OpenAI / Molili / Mock / MultiModelRouter (multi-provider fallback)。"
tags: ["backend", "sensing"]
tier: "standard"
---
# Sensing · Model Router

> ModelRouter 抽象 · Anthropic / OpenAI / Molili / Mock / MultiModelRouter (multi-provider fallback)。

**Source**: `runtime/sensing/model_router/`

## Exports

- `AllKeysExhausted`
- `CredentialPool`
- `DispatchRecord`
- `EventType`
- `KeyStats`
- `ModelDispatchRouter`
- `GeminiModelRouter`
- `GeminiRouterError`
- `LLMResponseFormatError`
- `MAX_BREAKPOINTS`
- `MIN_CACHE_CHARS`
- `Message`
- `MockModelRouter`
- `ModelRequest`
- `ModelResponse`
- `ModelRouter`
- `ModelStrength`
- `ModelStreamEvent`
- `MultiModelRouter`
- `OllamaModelRouter`
- `OllamaRouterError`
- `OpenAIModelRouter`
- `OpenAIRouterError`
- `PooledModelRouter`
- `PoolReport`
- `Provider`
- `ProviderCapabilities`
- `RouteAttempt`
- `budget_breakpoints`
- `clear_capability_cache`
- `estimate_cache_savings`
- `get_cached_capabilities`
- `mark_cache_breakpoint`
- `molili_current_actor`
- `prepare_cached_system`
- `prepare_cached_tools`
- `probe_provider`

## Modules

| Module | Summary |
| --- | --- |
| `_providers_data.py` | Provider profile data and data-layer accessors for OpenAI-compatible gateways. |
| `_response_parsers.py` | Response-parsing helpers for OpenAI-compatible providers. |
| `actor_context.py` | Actor context for model-router calls — a provider-neutral home. |
| `anthropic_router.py` | — |
| `capability_probe.py` | Provider Capability Auto-Detection. |
| `credential_pool.py` | — |
| `custom_model_flags.py` | Operator-declared capability flags from ``custom_models.json``. |
| `dispatch_router.py` | — |
| `gemini_router.py` | — |
| `hf_catalog.py` | Live local-model catalog from the HuggingFace Hub (GGUF), with offline fallback. |
| `hwfit.py` | Local-model cookbook: recommend which model to run on THIS machine. |
| `models.py` | Model router types and the mock implementation. |
| `multi_router.py` | — |
| `oct_router.py` | — |
| `ollama_router.py` | — |
| `openai_compat_providers.py` | Provider profiles for OpenAI-compatible chat-completion gateways. |
| `openai_compat_smoke_matrix.py` | Live-smoke metadata for OpenAI-compatible provider profiles. |
| `openai_compat_stream.py` | Shared OpenAI-compatible SSE stream parser. |
| `openai_router.py` | — |
| `pooled_router.py` | — |
| `prompt_cache.py` | Anthropic prompt-cache hint helpers. |
| `provider.py` | — |
| `rescue_policy.py` | Compatibility exports for the canonical platform model-rescue policy. |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `_providers_data.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class OpenAICompatProviderProfile` |  |
| class | `class OpenAICompatRetryPayload` |  |
| class | `class OpenAICompatProfileProbe` |  |
| func | `def known_openai_compat_profiles()` |  |
| func | `def openai_compat_profile_ids()` |  |
| func | `def resolve_openai_compat_profile(base_url, model)` |  |
| func | `def describe_openai_compat_profile(profile)` | Machine-readable summary for UI/API compatibility diagnostics. |

### `_response_parsers.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def extract_openai_compat_reasoning(message)` |  |
| func | `def extract_openai_compat_usage(data)` |  |
| func | `def parse_tool_call_arguments(value)` |  |
| func | `def split_inline_reasoning(text)` | Split ``<think>``-wrapped reasoning out of a content string. |
| class | `class InlineReasoningSplitter` | Streaming counterpart to :func:`split_inline_reasoning`. |

### `anthropic_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class AnthropicModelRouter(Provider, ModelRouter)` |  |

### `capability_probe.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_cached_capabilities(provider_key)` | Return in-memory cached capabilities for ``provider_key``, or None. |
| func | `def clear_capability_cache()` | Flush the in-memory capability cache (useful in tests). |
| func | `def probe_provider(router, model, timeout_s, force)` | Probe ``router`` and return its runtime capabilities. |

### `credential_pool.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class KeyStats(BaseModel)` |  |
| class | `class PoolReport(BaseModel)` |  |
| class | `class CredentialPool` |  |
| class | `class AllKeysExhausted(RuntimeError)` |  |

### `custom_model_flags.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def read_custom_models()` |  |
| func | `def entry_matches_model(entry, model)` |  |
| func | `def custom_model_entry_for(model)` |  |
| func | `def model_supports_tool_use(model)` | Return False when ``custom_models.json`` (or per-model env overrides) marks this model id as not supporting native function calling. |
| func | `def model_omits_sampling_parameters(model)` | Return True for strict OpenAI-compatible coding endpoints. |
| func | `def custom_model_supports_thinking(model)` |  |
| func | `def model_context_window(model)` | Return the operator-declared input window for a custom model. |

### `dispatch_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ModelDispatchRouter(ModelRouter)` |  |

### `gemini_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class GeminiRouterError(LLMResponseFormatError)` |  |
| class | `class GeminiModelRouter(Provider, ModelRouter)` |  |

### `hf_catalog.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def dynamic_catalog()` | Live ModelSpecs if cached/fresh, else None (caller falls back to static). |

### `hwfit.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class Hardware` |  |
| class | `class ModelSpec` |  |
| class | `class Recommendation` |  |
| func | `def default_catalog()` |  |
| func | `def detect_hardware()` | Best-effort hardware snapshot. Never raises — worst case is a CPU verdict. |
| func | `def estimate_mem_gb(params_b, quant)` | Approx RAM/VRAM (GB) to load + run a model at a given quant. |
| func | `def estimate_tps(active_params_b, quant, bandwidth_gbps)` | Roofline generation speed: tokens/s ≈ bandwidth ÷ active-weight-bytes. |
| func | `def recommend(hardware, catalog, installed, quant, top_k)` | Rank the catalog for this hardware at ``quant`` (ollama's default pull). |
| func | `def installed_models()` | Tags ollama already has locally (``/api/tags``); empty if ollama is down. |
| func | `def ollama_available()` |  |
| func | `def pull_model(tag, timeout)` | Trigger an ollama pull of ``tag`` (blocking; ollama streams progress). |
| func | `def start_pull(tag)` | Kick an ollama pull in the background and return immediately. Poll ``cookbook_snapshot()['pulls']`` (or ``installed`` flags) for progress. |
| func | `def pull_states()` |  |
| func | `def cookbook_snapshot()` | Everything the UI needs in one call: hardware + ranked recommendations, with installed flags, ollama availability, in-flight pulls, and the  |

### `models.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class MockModelRouter(ModelRouter)` |  |
| class | `class UnconfiguredModelRouter(ModelRouter)` | Last-resort dispatch fallback when no model is configured. |

### `multi_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class EmptyModelStreamError(RuntimeError)` | Provider ended a streaming request without producing any event. |
| class | `class RouteAttempt` |  |
| class | `class DispatchRecord` |  |
| class | `class MultiModelRouter(ModelRouter)` |  |

### `oct_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class OctCredentialsRequired(RuntimeError)` |  |
| class | `class OctModelRouter(Provider, ModelRouter)` | 走 oct 账号网关(api.octoapk.com)/v1/chat/completions 的模型路由。 |
| class | `class OctFallbackRouter(ModelRouter)` | actor 感知的 dispatcher fallback。 |

### `ollama_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class OllamaRouterError(LLMResponseFormatError)` |  |
| class | `class OllamaModelInfo` |  |
| class | `class OllamaModelRouter(Provider, ModelRouter)` |  |

### `openai_compat_providers.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def sample_openai_compat_profile_probe(profile)` |  |
| func | `def audit_openai_compat_profile_catalog(required_profile_ids)` |  |
| func | `def sample_openai_compat_contract_payload(model)` | Representative dry-run request covering common compat edge-fields. |
| func | `def probe_openai_compat_request_contract(profile, model)` | Dry-run request contract probe for a provider/profile pair. |
| func | `def apply_custom_openai_compat_profile(entry, base_profile)` |  |
| func | `def normalize_openai_compat_payload(payload, profile)` |  |
| func | `def retry_payloads_after_openai_compat_error(payload, status_code, body, profile)` |  |
| func | `def plan_openai_compat_retries(payload, status_code, body, profile)` |  |

### `openai_compat_smoke_matrix.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class OpenAICompatSmokeProvider` |  |
| func | `def openai_compat_smoke_providers()` |  |
| func | `def openai_compat_smoke_provider_ids()` |  |
| func | `def openai_compat_smoke_readiness()` | Secret-safe local readiness for optional live provider smoke tests. |

### `openai_compat_stream.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def iter_openai_sse(response, model, provider, cost_usd)` | Parse an httpx streaming response of OpenAI-compat SSE chunks. |

### `openai_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class OpenAIRouterError(LLMResponseFormatError)` |  |
| class | `class OpenAIModelRouter(Provider, ModelRouter)` |  |
| func | `def build_fallback_router_from_custom_models(prefer)` | Build a ModelRouter from the user's custom_models.json — a self-configured upstream usable as the dispatch *fallback*. |

### `pooled_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class PooledModelRouter(ModelRouter)` |  |

### `prompt_cache.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def prepare_cached_system(system_text, min_chars)` | Wrap ``system_text`` in a cache-enabled block list if large enough. |
| func | `def prepare_cached_tools(tools, min_total_chars)` | Attach a cache breakpoint to the *last* tool in ``tools``. |
| func | `def budget_breakpoints(has_system_cache, has_tools_cache, messages_remaining)` | Return how many cache breakpoints are still available for conversation messages given what's already been spent. |
| func | `def mark_cache_breakpoint(message)` | Add a ``cache_control: ephemeral`` to the last content block of ``message``. |
| func | `def estimate_cache_savings(input_tokens, cache_read_tokens, cache_creation_tokens)` | Compute what a single turn's cache usage saved vs. the uncached equivalent. Costs are relative (1.0 = one un-cached input token), not absolu |

### `provider.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ProviderCapabilities` | Declarative flags describing what an LLM adapter can do. |
| class | `class Provider` | Mixin: opt-in capability declaration for ``ModelRouter`` subclasses. |


## Who imports this

**38** file(s) reference this package:

- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_reflect.py/`** · 1 file(s)
  - `runtime/cli_reflect.py`
- **`runtime/cli_serve.py/`** · 1 file(s)
  - `runtime/cli_serve.py`
- **`runtime/execution/`** · 2 file(s)
  - `runtime/execution/suckers/computer_use_loop.py`
  - `runtime/execution/suckers/ephemeral_runner.py`
- **`runtime/platform/`** · 7 file(s)
  - `runtime/platform/config/builder.py`
  - `runtime/platform/lifecycle/demo.py`
  - `runtime/platform/llm_infra/llm_caller.py`
  - `runtime/platform/process/session.py`
  - `runtime/platform/ui/_app_fallback_routers.py`
  - _… and 2 more_
- **`runtime/projectos/`** · 1 file(s)
  - `runtime/projectos/llm_hooks.py`
- **`runtime/research/`** · 2 file(s)
  - `runtime/research/pipeline.py`
  - `runtime/research/query_rewrite.py`
- **`runtime/sensing/`** · 23 file(s)
  - `runtime/sensing/gateway/_config_endpoints_custom_models.py`
  - `runtime/sensing/gateway/_config_endpoints_models.py`
  - `runtime/sensing/gateway/_config_helpers.py`
  - `runtime/sensing/gateway/_evolution_helpers.py`
  - `runtime/sensing/gateway/_openai_gateway_router_helpers.py`
  - _… and 18 more_


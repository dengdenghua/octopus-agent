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

## Who imports this

**25** file(s) reference this package:

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
  - `runtime/platform/ui/app.py`
  - _… and 2 more_
- **`runtime/projectos/`** · 1 file(s)
  - `runtime/projectos/llm_hooks.py`
- **`runtime/research/`** · 2 file(s)
  - `runtime/research/pipeline.py`
  - `runtime/research/query_rewrite.py`
- **`runtime/sensing/`** · 10 file(s)
  - `runtime/sensing/gateway/android_router.py`
  - `runtime/sensing/gateway/completion_router.py`
  - `runtime/sensing/gateway/config_router.py`
  - `runtime/sensing/gateway/evolution_router.py`
  - `runtime/sensing/gateway/openai_gateway/context_manager.py`
  - _… and 5 more_


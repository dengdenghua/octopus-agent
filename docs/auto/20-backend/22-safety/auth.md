---
type: "SafetySubsystem"
title: "Safety · Auth"
description: "TrustEngine · allow/quarantine/reject · IMM-I1~I6 不变量守护。"
tags: ["backend", "safety"]
tier: "core"
---
# Safety · Auth

> TrustEngine · allow/quarantine/reject · IMM-I1~I6 不变量守护。

**Source**: `runtime/safety/auth/`

## Exports

- `ANONYMOUS_ACTOR`
- `FileWriteVerdict`
- `GuardrailConfig`
- `GuardrailDecision`
- `Identity`
- `IdentityStore`
- `JWTError`
- `MODEL_FORBIDDEN_ARGS`
- `PathVerdict`
- `ToolCallGuardrailController`
- `ToolCallSignature`
- `TrustEngine`
- `URLVerdict`
- `check_file_write`
- `check_path`
- `check_url`
- `classify_tool`
- `classify_tool_failure`
- `encode_jwt_hs256`
- `hash_api_key`
- `is_safe_path`
- `is_safe_url`
- `is_safe_write`
- `strip_model_controlled_overrides`
- `verify_jwt_hs256`

## Modules

| Module | Summary |
| --- | --- |
| `adaptive_immunity.py` | Adaptive immunity — the immunity protocol's behavioural-anomaly tier. |
| `arg_guard.py` | Strip model-controllable privilege-escalation kwargs before dispatch. |
| `attack_memory.py` | Antibody memory — the immunity protocol's Memory tier. |
| `file_safety.py` | — |
| `identity.py` | — |
| `path_denylist.py` | User-defined path denylist — Marvis-style "不可读取文件夹". |
| `path_guard.py` | — |
| `tool_guardrails.py` | — |
| `trust_engine.py` | — |
| `url_guard.py` | — |

## Who imports this

**25** file(s) reference this package:

- **`runtime/adapters/`** · 2 file(s)
  - `runtime/adapters/integrations/local_auth/router.py`
  - `runtime/adapters/integrations/oct/router_auth.py`
- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/execution/`** · 13 file(s)
  - `runtime/execution/subagents/bridge.py`
  - `runtime/execution/suckers/browser_skills.py`
  - `runtime/execution/suckers/builtins.py`
  - `runtime/execution/suckers/computer_skills.py`
  - `runtime/execution/suckers/crawler_skills.py`
  - _… and 8 more_
- **`runtime/platform/`** · 3 file(s)
  - `runtime/platform/config/builder.py`
  - `runtime/platform/ui/app.py`
  - `runtime/platform/ui/browser_router.py`
- **`runtime/sensing/`** · 4 file(s)
  - `runtime/sensing/gateway/config_router.py`
  - `runtime/sensing/gateway/meta_router.py`
  - `runtime/sensing/gateway/observability_router.py`
  - `runtime/sensing/gateway/stub_router.py`
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`


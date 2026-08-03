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
| `arg_guard.py` | Strip model-controllable privilege escalation before dispatch. |
| `attack_memory.py` | Antibody memory — the immunity protocol's Memory tier. |
| `file_safety.py` | — |
| `identity.py` | — |
| `path_denylist.py` | User-defined path denylist — Marvis-style "不可读取文件夹". |
| `path_guard.py` | — |
| `tool_guardrails.py` | — |
| `trust_engine.py` | — |
| `url_guard.py` | — |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `adaptive_immunity.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class AdaptiveImmunity` | Per-sucker behavioural baselines + risk scoring. |

### `arg_guard.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def is_model_protected_context_key(key)` |  |
| func | `def strip_model_controlled_overrides(args)` | Return ``args`` with model-forbidden privilege escalation removed. |

### `attack_memory.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class AttackPattern` |  |
| class | `class AttackMemory` | Thread-safe antibody store with sliding-window crystallization. |

### `file_safety.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class FileWriteVerdict` |  |
| func | `def check_file_write(path)` |  |
| func | `def is_safe_write(path)` |  |
| func | `def denied_basenames()` |  |
| func | `def denied_home_subdirs()` |  |

### `identity.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class Identity` |  |
| class | `class IdentityStore` |  |
| func | `def hash_api_key(plaintext)` |  |
| class | `class JWTError(Exception)` |  |
| func | `def encode_jwt_hs256(claims, secret, header_extra)` |  |
| func | `def verify_jwt_hs256(token, secret, leeway_seconds, required_issuer, required_audience, now)` |  |

### `path_denylist.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_user_denylist()` | User-facing list of denied paths (raw, unexpanded form). |
| func | `def add_user_denylist_entry(path)` | Append a path to the user denylist; returns the new list. |
| func | `def remove_user_denylist_entry(path)` | Remove a path; returns the new list. |
| func | `def push_turn_denylist(extra)` | Add extra denied paths for the duration of a context. |
| func | `def pop_turn_denylist(token)` |  |
| func | `def is_blocked(resolved)` | Whether a *resolved* (canonical absolute) path is blocked. |

### `path_guard.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class PathVerdict` |  |
| func | `def check_path(path, sandbox_dir, allow_sensitive, must_exist)` |  |
| func | `def is_safe_path(path, sandbox_dir, allow_sensitive)` |  |

### `tool_guardrails.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def classify_tool(tool_name)` |  |
| class | `class ToolCallSignature` |  |
| class | `class GuardrailDecision` |  |
| class | `class GuardrailConfig` |  |
| class | `class ToolCallGuardrailController` |  |
| func | `def classify_tool_failure(tool_name, result)` |  |

### `trust_engine.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TrustEngine` |  |

### `url_guard.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class URLVerdict` |  |
| func | `def check_url(url, allow_private, resolve_dns)` |  |
| func | `def is_safe_url(url, allow_private)` |  |
| func | `def safe_urlopen(url, timeout, read_cap_bytes, allow_private)` | Fetch ``url`` with rebinding-proof host pinning. |
| func | `def safe_httpx_get(url, timeout, allow_private, follow_redirects)` | Rebinding-proof GET via httpx when the dep is available. |


## Who imports this

**27** file(s) reference this package:

- **`runtime/adapters/`** · 2 file(s)
  - `runtime/adapters/integrations/local_auth/router.py`
  - `runtime/adapters/integrations/oct/router_auth.py`
- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/execution/`** · 14 file(s)
  - `runtime/execution/subagents/bridge.py`
  - `runtime/execution/suckers/_delegation_skills_common.py`
  - `runtime/execution/suckers/_ephemeral_tool_exec.py`
  - `runtime/execution/suckers/_write_skills_common.py`
  - `runtime/execution/suckers/browser_skills.py`
  - _… and 9 more_
- **`runtime/platform/`** · 4 file(s)
  - `runtime/platform/config/builder.py`
  - `runtime/platform/ui/_app_setup.py`
  - `runtime/platform/ui/_browser_helper_nav.py`
  - `runtime/platform/ui/browser_router.py`
- **`runtime/sensing/`** · 4 file(s)
  - `runtime/sensing/gateway/_config_endpoints_security.py`
  - `runtime/sensing/gateway/_observability_rollback_panels.py`
  - `runtime/sensing/gateway/meta_router.py`
  - `runtime/sensing/gateway/stub_router.py`
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`


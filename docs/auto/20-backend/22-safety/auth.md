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
- `CurrentPrincipal`
- `TenantScope`
- `URLVerdict`
- `check_file_write`
- `check_path`
- `check_url`
- `classify_tool`
- `classify_tool_failure`
- `encode_jwt_hs256`
- `hash_api_key`
- `is_safe_path`
- `require_operator`
- `require_roles`
- `resolve_principal`
- `scope_from_principal`
- `scope_from_request`
- `is_safe_url`
- `safe_httpx_request`
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
| `principal.py` | Request principal resolution and role gates for shared deployments. |
| `scope.py` | Small, framework-independent tenant scope primitives. |
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

### `principal.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class CurrentPrincipal` | Verified request identity used by authorization decisions. |
| func | `def resolve_principal(request, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, jwt_leeway_seconds)` | Resolve a principal from a known API key or a registered JWT subject. |
| func | `def require_roles(request, identity_store, require_auth, allowed_roles, jwt_secret, jwt_issuer, jwt_audience, jwt_leeway_seconds)` | Require one of *allowed_roles* when shared authentication is active. |
| func | `def require_operator(request, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, jwt_leeway_seconds)` | Require an ``operator`` or ``admin`` role for control-plane changes. |

### `scope.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TenantScope` | The minimum ownership context required by a tenant-aware store. |
| func | `def scope_from_principal(principal, allow_cross_tenant)` |  |
| func | `def scope_from_request(request, allow_cross_tenant)` | Read only the server-resolved principal from request state. |
| func | `def require_scope(scope)` |  |
| func | `def row_visible(row, scope, owner_field)` | Return whether a persisted row may be returned to ``scope``. |
| func | `def tenant_scoped_path(base_path, scope)` | Return a filesystem partition for one tenant/owner scope. |

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
| func | `def safe_httpx_request(method, url, json, data, headers, timeout, allow_private, follow_redirects)` | Make one rebinding-resistant HTTP request. |


## Who imports this

**78** file(s) reference this package:

- **`runtime/adapters/`** · 5 file(s)
  - `runtime/adapters/integrations/local_auth/router.py`
  - `runtime/adapters/integrations/oct/router_auth.py`
  - `runtime/adapters/mcp_client/oauth.py`
  - `runtime/adapters/mcp_client/oauth_discovery.py`
  - `runtime/adapters/web_auth.py`
- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/core/`** · 3 file(s)
  - `runtime/core/nerves/reflex/actions.py`
  - `runtime/core/nerves/reflex/broadcast.py`
  - `runtime/core/nerves/reflex/tiers.py`
- **`runtime/execution/`** · 15 file(s)
  - `runtime/execution/subagents/bridge.py`
  - `runtime/execution/suckers/_delegation_skills_common.py`
  - `runtime/execution/suckers/_ephemeral_tool_exec.py`
  - `runtime/execution/suckers/_write_skills_common.py`
  - `runtime/execution/suckers/agent_meta_skills.py`
  - _… and 10 more_
- **`runtime/memory/`** · 9 file(s)
  - `runtime/memory/diagnostics/_trace_store_replay_storage.py`
  - `runtime/memory/diagnostics/_trace_store_storage.py`
  - `runtime/memory/journal/_journal_base.py`
  - `runtime/memory/journal/journal.py`
  - `runtime/memory/learning/experience_ledger.py`
  - _… and 4 more_
- **`runtime/platform/`** · 7 file(s)
  - `runtime/platform/config/builder.py`
  - `runtime/platform/io/lease.py`
  - `runtime/platform/ui/_app_setup.py`
  - `runtime/platform/ui/_browser_helper_nav.py`
  - `runtime/platform/ui/browser_router.py`
  - _… and 2 more_
- **`runtime/projectos/`** · 2 file(s)
  - `runtime/projectos/engine.py`
  - `runtime/projectos/store.py`
- **`runtime/safety/`** · 1 file(s)
  - `runtime/safety/evolution/proposal_ledger.py`
- **`runtime/sensing/`** · 30 file(s)
  - `runtime/sensing/gateway/_agent_trace_router_stores.py`
  - `runtime/sensing/gateway/_config_endpoints_security.py`
  - `runtime/sensing/gateway/_observability_rollback_panels.py`
  - `runtime/sensing/gateway/account_usage_router.py`
  - `runtime/sensing/gateway/agent_trace_dependencies.py`
  - _… and 25 more_
- **`runtime/tentacle/`** · 2 file(s)
  - `runtime/tentacle/coordinator.py`
  - `runtime/tentacle/dashboard.py`
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`
- **`runtime/workspace/`** · 1 file(s)
  - `runtime/workspace/store.py`


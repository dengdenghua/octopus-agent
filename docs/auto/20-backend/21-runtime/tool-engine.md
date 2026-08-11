---
type: "RuntimeSubsystem"
title: "Tool Engine · 执行器"
description: "把每步 tool call 串起整套治理 · Auth / Budget / Journal / Hooks · 同时做 OTel span。"
tags: ["backend", "runtime"]
tier: "core"
---
# Tool Engine · 执行器

> 把每步 tool call 串起整套治理 · Auth / Budget / Journal / Hooks · 同时做 OTel span。

**Source**: `runtime/execution/tool_engine/`

## Exports

- `NormalizedToolCall`
- `NormalizedToolLifecycleEvent`
- `NormalizedToolResult`
- `StepExecutionError`
- `ToolCallOrigin`
- `ToolKind`
- `ToolLifecycleKind`
- `ToolTaxonomy`
- `ToolExecutor`
- `classify_skill`
- `normalize_tool_lifecycle_event`
- `normalize_step_tool_result`
- `normalize_tool_result`
- `normalize_task_node_tool_call`
- `normalize_tool_call`
- `output_signals_error`
- `register_taxonomy`
- `render_tool_output`
- `reset_overrides`
- `taxonomy_to_audit_dict`
- `tool_lifecycle_event_to_react_event`
- `tool_lifecycle_event_to_trace_payload`

## Modules

| Module | Summary |
| --- | --- |
| `_executor_fileops.py` | — |
| `_executor_helpers.py` | — |
| `effect_receipts.py` | Crash-safe tool effect receipts for durable agent turns. |
| `effect_store.py` | Transactional cross-process coordination for tool side effects. |
| `executor.py` | — |
| `redis_effect_store.py` | Redis-backed, cross-host tool-effect receipts. |
| `skill_gate.py` | Shared pre-execution safety gate for direct skill dispatch. |
| `tool_protocol.py` | — |
| `tool_taxonomy.py` | Unified tool identity layer · stable taxonomy for audit & grouping. |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `_executor_helpers.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class StepExecutionError(RuntimeError)` |  |
| class | `class ReadBeforeWriteRequired(RuntimeError)` |  |

### `effect_receipts.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def args_fingerprint(args)` |  |
| func | `def effect_key(task_id, step_id, sucker_id, args)` |  |
| func | `def is_side_effecting(affinity)` | Fail closed for unknown affinity; known read-only tags may retry. |
| class | `class EffectResolution` |  |
| class | `class EffectLeaseLost(RuntimeError)` | The caller lost its fenced claim before entering the handler. |
| class | `class ToolEffectReceiptIndex` | Journal-backed receipts plus optional cross-process coordination. |
| func | `def indeterminate_step(step_id, node_id, call, effect_key, fencing_token, reason)` |  |

### `effect_store.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class StoreDecision` |  |
| class | `class EffectReceipt` | Operator-safe view of one durable tool-effect receipt. |
| class | `class EffectStore(Protocol)` | Shared contract for local and cluster receipt planes. |
| class | `class SQLiteEffectStore` | A fork-safe SQLite receipt store. |

### `executor.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ToolExecutor` | Skill-step executor with read-before-write + diff/rollback wiring. |

### `redis_effect_store.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RedisEffectStore` |  |

### `skill_gate.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def current_trust_engine()` |  |
| func | `def use_trust_engine(engine)` | Bind ``engine`` as the ambient trust engine for the dynamic extent of the ``with`` block (and any nested meta-skill dispatch within it). |
| func | `def canonical_tool_path(args)` |  |
| func | `def file_safety_target(skill, args)` | Write target to vet against the credential-file denylist. |
| func | `def antigen_for(skill)` |  |
| class | `class GateBlock` | A definitive block verdict from :func:`gate_inner_dispatch`. |
| func | `def gate_inner_dispatch(skill, args, caller, defer_taint_if_handled)` | Apply the executor's pre-execution safety gates to a skill that a meta-skill is about to dispatch DIRECTLY (``use_capability``, a forged com |

### `tool_protocol.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class NormalizedToolCall` | Provider-agnostic tool invocation used at executor boundaries. |
| class | `class NormalizedToolResult` | Provider-agnostic result envelope for a completed tool call. |
| class | `class NormalizedToolLifecycleEvent` | Shared tool lifecycle event before surface-specific rendering. |
| func | `def normalize_tool_call(call, origin)` | Convert supported tool-call shapes into ``NormalizedToolCall``. |
| func | `def normalize_tool_lifecycle_event(kind, payload, origin)` | Normalize native/ReAct tool lifecycle payloads. |
| func | `def tool_lifecycle_event_to_react_event(event)` | Render a lifecycle event using the existing ReAct stream shape. |
| func | `def tool_lifecycle_event_to_trace_payload(event)` | Render a durable trace payload while preserving legacy aliases. |
| func | `def output_signals_error(output)` | Return True when structured tool output reports failure. |
| func | `def render_tool_output(output, max_chars)` | Render arbitrary tool output into a bounded string. |
| func | `def normalize_tool_result(call, output, is_error, status, error_type, origin, max_chars)` | Convert tool output into the shared result envelope. |
| func | `def normalize_step_tool_result(step, origin, max_chars, fallback_call)` | Convert an execution ``Step`` into the shared result envelope. |
| func | `def normalize_task_node_tool_call(node, resolved_args, node_index)` | Convert a planner ``TaskNode`` into the common tool-call protocol. |

### `tool_taxonomy.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ToolTaxonomy` | Stable identity metadata for a single tool invocation. |
| func | `def register_taxonomy(skill_name, taxonomy)` | Register an explicit taxonomy override for ``skill_name``. |
| func | `def reset_overrides()` | Clear all registered overrides. Mainly for tests. |
| func | `def classify_skill(skill)` | Derive a :class:`ToolTaxonomy` from a ``Skill`` instance. |
| func | `def taxonomy_to_audit_dict(taxonomy)` | Serialize taxonomy for journal/audit payloads. |


## Who imports this

**17** file(s) reference this package:

- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/core/`** · 4 file(s)
  - `runtime/core/cerebrum/_react_execution_dispatch.py`
  - `runtime/core/cerebrum/_react_execution_phase6d.py`
  - `runtime/core/cerebrum/react_parallel_dispatch.py`
  - `runtime/core/graph_runtime/runtime.py`
- **`runtime/execution/`** · 4 file(s)
  - `runtime/execution/suckers/_ephemeral_tool_exec.py`
  - `runtime/execution/suckers/agent_meta_skills.py`
  - `runtime/execution/suckers/capability_skills.py`
  - `runtime/execution/suckers/forged_persistence.py`
- **`runtime/platform/`** · 1 file(s)
  - `runtime/platform/config/builder.py`
- **`runtime/safety/`** · 1 file(s)
  - `runtime/safety/recovery/skill_forge.py`
- **`runtime/sensing/`** · 5 file(s)
  - `runtime/sensing/gateway/_observability_rollback_panels.py`
  - `runtime/sensing/gateway/_realtime_react_stream_helpers.py`
  - `runtime/sensing/gateway/_tool_bridge_exec.py`
  - `runtime/sensing/gateway/realtime_react_policy.py`
  - `runtime/sensing/gateway/realtime_turn_outcome.py`


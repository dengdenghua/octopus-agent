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
| `native_tool_execution.py` | Execute a model-native tool call through the Octopus executor boundary. |
| `redis_effect_store.py` | Redis-backed, cross-host tool-effect receipts. |
| `session_metadata.py` | Project caller context into the metadata trusted by tool sessions. |
| `session_projection.py` | Byte-bounded projection of a session's conversation surface. |
| `session_reference.py` | Octopus Native cross-session reference resolver. |
| `session_reference_uri.py` | Canonical Octopus session URI and inline mention encoding. |
| `skill_gate.py` | Shared pre-execution safety gate for direct skill dispatch. |
| `tool_output_pruner.py` | Deterministic head/middle/tail pruning for over-budget tool results. |
| `tool_output_spill.py` | Session-scoped spill storage for oversized plain-text tool results. |
| `tool_protocol.py` | — |
| `tool_shadow_price.py` | Shadow-price accounting for tool-result pruning. |
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
| func | `def not_executed_effect_receipt(call_id, tool_name, reason)` | Return the server-owned proof used by pre-dispatch rejection paths. |
| func | `def build_server_effect_receipt(skill, call_id, handler_executed, result_status, resolution, receipt_rewrite_source)` | Seal one conservative execution-effect classification. |
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

### `native_tool_execution.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def execute_native_tool_call(stack, call, max_chars, prune_middle, spill_oversized, task_id, step_id, arm_id, budget)` | Run one native tool request through the normal executor chokepoint. |

### `redis_effect_store.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RedisEffectStore` |  |

### `session_metadata.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def project_tool_session_metadata(user_context)` | Return the allowlisted context that may survive tool-thread hops. |

### `session_projection.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ProjectedItem` | One projected conversation unit (user or assistant text). |
| class | `class ReferencedSessionData` | Snapshot data serialized into the model-facing reference. |
| class | `class ReferenceRetentionStats` | Retention facts beside the projected snapshot. |
| class | `class TruncatedText` | One message shortened to a byte budget with an exact omission count. |
| func | `def is_compact_checkpoint_source(source)` | Whether a persisted message source identifies a compaction checkpoint. |
| func | `def project_session_conversation(events)` | Project the user/assistant surface, excluding tools and injected context. |
| func | `def stringify_tag_safe_json(value)` | Compact JSON with every ``<`` escaped as ``\u003c``. |
| func | `def truncate_with_notice(text, max_output_bytes)` | Binary-search a head/tail truncation of ``text`` that fits the budget. |
| func | `def retain_session_reference(events, session_id, label, max_bytes, cwd, captured_through_seq)` | Fit one projected session snapshot into an exact byte cap. |

### `session_reference.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SessionReferenceError(RuntimeError)` | Typed session-reference failure suitable for host protocol error mapping. |
| class | `class SessionReferenceRecord` | One durable session surfaced to candidate discovery. |
| class | `class SessionReferenceCandidate` | One host-facing candidate from exact session metadata. |
| class | `class SessionReferenceInput` | One source session selected by a host (dsh ``SessionReferenceInput``). |
| class | `class PreparedReferencedMessage` | Detached content plus the optional referenced-session context. |
| func | `def candidate_rank(candidate_cwd, target_cwd)` | Working-directory affinity rank (dsh ``candidateRank``). |
| func | `def normalize_references(target_id, references, max_references)` | Validate, dedupe, and cap source references (dsh ``normalizeReferences``). |
| func | `def render_reference_prompt(data)` | Render the aggregated untrusted snapshot frame (dsh ``renderPrompt``). |
| func | `def extract_session_mentions(prompt)` | Distinct referenced session ids from host mention tokens. |
| class | `class SessionReferenceResolver` | Resolve session references into an aggregated durable context. |

### `session_reference_uri.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ParsedSessionReferenceText` | Result of extracting canonical mentions from plain text. |
| func | `def encode_session_reference_uri(session_id)` | Encode any session id as a canonical lossless Octopus session URI. |
| func | `def decode_session_reference_uri(uri)` | Decode a current or legacy session URI with strict payload checks. |
| func | `def format_session_reference_mention(session_id, label)` | Render a host-neutral Markdown mention carrying the canonical URI. |
| func | `def parse_session_reference_text(text)` | Extract Markdown mentions and bare canonical URIs from one text value. |

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

### `tool_output_pruner.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def set_shadow_price_sink(sink)` | Install the shadow-price sink (``None`` disables emission). |
| class | `class ToolResultPrunePolicy` | Character budgets for tool-result pruning. |
| func | `def validate_prune_budgets(threshold_chars, head_chars, tail_chars, marker)` | Validate prune budgets the way dsh's ``resolveConfig`` does. |
| func | `def prune_tool_result_text(text, policy, threshold_chars, head_chars, tail_chars, marker, tool_name, call_id)` | Return a pruned copy of ``text``, or ``None`` when it is within budget. |

### `tool_output_spill.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SpillRef` | A saved spill artifact: locator, byte length, and retrieval guidance. |
| func | `def encode_segment(raw)` | Encode an arbitrary string as one safe path segment, injectively. |
| func | `def session_spill_dir(root, session_key)` | The session-scoped directory: ``<root>/session-<sha256-prefix>``. |
| func | `def default_spill_root()` | The default spill root: a private (0700) per-process temp directory. |
| func | `def save_text_spill(session_key, content, suggested_name, root)` | Persist ``content`` to a session-scoped spill file and return its ref. |
| func | `def is_current_session_spill_path(path)` | Return whether ``path`` is an exact spill owned by the active session. |
| func | `def head_tail_preview(text, budget_bytes)` | Return ``(preview, omitted_bytes)`` splitting budget across both ends. |
| func | `def head_tail_preview_bytes(text, head_bytes, tail_bytes)` | Return ``(preview, omitted_bytes)`` keeping ``head_bytes + tail_bytes``. |
| func | `def spill_notice(omitted_bytes, ref)` | The one-line spill notice (no preview, no leading blank line). |
| func | `def maybe_spill_text(text, max_inline_bytes, session_key, tool_name, suggested_name, root, enabled)` | Spill ``text`` and return a bounded replacement, or ``None`` to keep inline. |

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
| func | `def render_tool_output(output, max_chars, prune_middle, prune_policy, spill_oversized, tool_name, call_id)` | Render arbitrary tool output into a bounded string. |
| func | `def normalize_tool_result(call, output, is_error, status, error_type, origin, max_chars, prune_middle, prune_policy, spill_oversized, tool_name, call_id)` | Convert tool output into the shared result envelope. |
| func | `def normalize_step_tool_result(step, origin, max_chars, fallback_call, prune_middle, prune_policy, spill_oversized, tool_name)` | Convert an execution ``Step`` into the shared result envelope. |
| func | `def normalize_task_node_tool_call(node, resolved_args, node_index)` | Convert a planner ``TaskNode`` into the common tool-call protocol. |

### `tool_shadow_price.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class PruneShadowPrice` | One shadowed prune: what the model no longer sees, heuristically priced. |
| func | `def estimate_shadowed_tokens(chars_removed)` | Heuristic token price of a shadowed span (dsh fixed density). |
| class | `class ShadowPriceLedger` | Process-level accumulation of shadow-price records (thread-safe). |
| func | `def default_shadow_price_sink(price)` | Default sink: accumulate into the process ledger (never bills). |
| func | `def shadow_price_ledger()` | The process-level shadow ledger used by the default sink. |

### `tool_taxonomy.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ToolTaxonomy` | Stable identity metadata for a single tool invocation. |
| func | `def register_taxonomy(skill_name, taxonomy)` | Register an explicit taxonomy override for ``skill_name``. |
| func | `def reset_overrides()` | Clear all registered overrides. Mainly for tests. |
| func | `def classify_skill(skill)` | Derive a :class:`ToolTaxonomy` from a ``Skill`` instance. |
| func | `def taxonomy_to_audit_dict(taxonomy)` | Serialize taxonomy for journal/audit payloads. |


## Who imports this

**26** file(s) reference this package:

- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/core/`** · 7 file(s)
  - `runtime/core/cerebrum/_react_execution_dispatch.py`
  - `runtime/core/cerebrum/_react_execution_phase6d.py`
  - `runtime/core/cerebrum/_react_execution_results.py`
  - `runtime/core/cerebrum/react_action_outcomes.py`
  - `runtime/core/cerebrum/react_execution_receipts.py`
  - _… and 2 more_
- **`runtime/execution/`** · 6 file(s)
  - `runtime/execution/codex_backend/dynamic_tools.py`
  - `runtime/execution/subagents/sessions.py`
  - `runtime/execution/suckers/_ephemeral_tool_exec.py`
  - `runtime/execution/suckers/agent_meta_skills.py`
  - `runtime/execution/suckers/capability_skills.py`
  - `runtime/execution/suckers/forged_persistence.py`
- **`runtime/platform/`** · 1 file(s)
  - `runtime/platform/config/builder.py`
- **`runtime/safety/`** · 2 file(s)
  - `runtime/safety/auth/path_guard.py`
  - `runtime/safety/recovery/skill_forge.py`
- **`runtime/sensing/`** · 8 file(s)
  - `runtime/sensing/gateway/_observability_rollback_panels.py`
  - `runtime/sensing/gateway/_realtime_react_stream_helpers.py`
  - `runtime/sensing/gateway/_tool_bridge_exec.py`
  - `runtime/sensing/gateway/_tool_bridge_policy.py`
  - `runtime/sensing/gateway/_tool_bridge_session.py`
  - _… and 3 more_


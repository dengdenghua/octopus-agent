---
type: "SafetySubsystem"
title: "Safety · Hooks"
description: "Tool lifecycle hooks · 6 个事件 · sync + async handler · ESLint rules-of-hooks=error 静态守护。"
tags: ["backend", "safety"]
tier: "core"
---
# Safety · Hooks

> Tool lifecycle hooks · 6 个事件 · sync + async handler · ESLint rules-of-hooks=error 静态守护。

**Source**: `runtime/safety/hooks/`

## Package summary

Agent runtime hooks · lifecycle events for the agent loop.

## Exports

- `HookEvent`
- `PreToolUseEvent`
- `PostToolUseEvent`
- `UserPromptSubmitEvent`
- `StopEvent`
- `SessionStartEvent`
- `NotificationEvent`
- `HookDecision`
- `HookRegistry`
- `get_global_registry`
- `register_hook`
- `dispatch_pre_tool`
- `dispatch_post_tool`
- `dispatch_user_prompt`
- `dispatch_stop`
- `dispatch_session_start`
- `dispatch_notification`

## Modules

| Module | Summary |
| --- | --- |
| `events.py` | Hook event dataclasses · one per lifecycle point. |
| `external_bridge.py` | Industry ``hooks.json`` bridge — dsh hook-protocol + dialect bridges. |
| `registry.py` | Hook registry · where handlers register · and dispatch resolves. |
| `runner.py` | Dispatch helpers · the runtime calls these at lifecycle points. |
| `tool_edge_hooks.py` | Declarative tool-edge hooks (``preToolUse`` / ``postToolUse`` hooks that live in config files, not source code). |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `events.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class HookEvent` | Base · carries session + a name for logging. |
| class | `class PreToolUseEvent(HookEvent)` | Fired just before a skill handler is called. |
| class | `class PostToolUseEvent(HookEvent)` | Fired just after a skill handler returns. |
| class | `class UserPromptSubmitEvent(HookEvent)` | Fired before the planner sees a new user turn. |
| class | `class StopEvent(HookEvent)` | Fired when a full agent turn completes · successfully or not. |
| class | `class SessionStartEvent(HookEvent)` | Fired once at ``bind_thread_session`` time · useful for loading per-user context (preferences · feature flags). |
| class | `class NotificationEvent(HookEvent)` | Generic runtime notification · budget warnings · rate limits · provider outages. Informational · decision is always pass_through. |

### `external_bridge.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ExternalHookSpec` | One normalized command hook from a dialect config file. |
| class | `class ExternalHookOutput` | Neutral decoded outcome of one hook run (dsh ``HookOutput``). |
| func | `def summarize_stderr(stderr, max_chars)` | Trimmed stderr for ``hook/result``; ``None`` when blank, capped with an ellipsis when over (dsh ``summarizeStderr``). |
| func | `def matcher_diagnostic(matcher, dialect)` | Stable diagnostic for an invalid matcher, ``None`` when valid. |
| func | `def matches_matcher(matcher, query, dialect)` | Whether a matcher selects ``query``; invalid regexes never match. |
| func | `def parse_hook_output(exit_code, stdout, stderr)` | Decode one hook process outcome into the neutral ``HookOutput``. |
| func | `def run_external_hook(command, payload, dialect, cwd, env, timeout_s, plugin_root, project_dir)` | Run one command hook. Never raises — infra faults pass through. |
| func | `def parse_external_hooks(raw, dialect)` | Normalize one dialect ``hooks.json`` payload. |
| func | `def load_external_hooks(path, dialect)` | Read one ``hooks.json``. Missing / unparsable → empty, never raises. |
| func | `def build_payload(event, event_name)` | One per-event stdin payload (dsh bridge payload builder). |
| func | `def discover_external_hook_paths()` | Default discovery order: explicit env → home → process cwd. |
| func | `def register_external_hooks(registry, paths)` | Load every discovered (or given) ``hooks.json`` into the registry. |

### `registry.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class HookDecision` | Structured handler response. |
| class | `class HookRegistry` | In-memory handler registration · one registry per app. |
| func | `def get_global_registry()` | Process-global HookRegistry · used by ``register_hook`` decorator + runtime dispatch points. Tests needing isolation should call ``.clear()` |
| func | `def register_hook(event_type)` | Decorator · register ``handler`` for ``event_type`` on the global registry. Community hooks in ``~/.octopus/hooks/*.py`` use this to plug in |

### `runner.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def dispatch_pre_tool(sucker_id, args, caller, session)` |  |
| func | `def dispatch_post_tool(sucker_id, args, output, success, session)` |  |
| func | `def dispatch_user_prompt(prompt_text, thread_id, session)` |  |
| func | `def dispatch_stop(thread_id, success, step_count, session)` |  |
| func | `def dispatch_session_start(thread_id, session)` |  |
| func | `def dispatch_notification(kind, details, session)` |  |

### `tool_edge_hooks.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RegressionCheck` |  |
| class | `class RegressionMatrix` |  |
| func | `def post_write_diagnostics(tool_name, args, result, workspace_path)` | Run lightweight per-file diagnostics after a successful write. |
| func | `def post_write_diagnostic_record(tool_name, args, result, workspace_path)` | Return an auditable diagnostic decision for every post-write attempt. |
| func | `def post_write_regression_matrix(tool_name, args, result, workspace_path)` | Recommend targeted verification commands for a successful write. |
| func | `def regression_matrix_for_path(target, workspace_path)` |  |
| class | `class ToolEdgeHookSpec` |  |
| class | `class ToolEdgeHookConfig` |  |
| class | `class ToolEdgeHookOutcome` |  |
| func | `def load_tool_edge_hook_config(path)` | Read the declarative config file. Missing → empty. |
| class | `class ToolEdgeHookRunner` | Executes declarative hooks at the tool boundary. |


## Who imports this

**8** file(s) reference this package:

- **`runtime/core/`** · 1 file(s)
  - `runtime/core/cerebrum/_react_execution_phase6d.py`
- **`runtime/execution/`** · 3 file(s)
  - `runtime/execution/suckers/plan_mode.py`
  - `runtime/execution/tool_engine/_executor_helpers.py`
  - `runtime/execution/tool_engine/executor.py`
- **`runtime/platform/`** · 1 file(s)
  - `runtime/platform/ui/app.py`
- **`runtime/sensing/`** · 3 file(s)
  - `runtime/sensing/gateway/realtime_turn_lifecycle.py`
  - `runtime/sensing/gateway/realtime_turn_outcome.py`
  - `runtime/sensing/model_router/anthropic_router.py`


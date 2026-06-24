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
| `registry.py` | Hook registry · where handlers register · and dispatch resolves. |
| `runner.py` | Dispatch helpers · the runtime calls these at lifecycle points. |
| `tool_edge_hooks.py` | Declarative tool-edge hooks (``preToolUse`` / ``postToolUse`` hooks that live in config files, not source code). |

## Who imports this

**6** file(s) reference this package:

- **`runtime/core/`** · 1 file(s)
  - `runtime/core/cerebrum/react_loop.py`
- **`runtime/execution/`** · 2 file(s)
  - `runtime/execution/suckers/plan_mode.py`
  - `runtime/execution/tool_engine/executor.py`
- **`runtime/sensing/`** · 3 file(s)
  - `runtime/sensing/gateway/realtime_turn_lifecycle.py`
  - `runtime/sensing/gateway/realtime_turn_outcome.py`
  - `runtime/sensing/model_router/anthropic_router.py`


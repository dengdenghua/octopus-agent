---
type: "Graph"
title: "Hook surface"
description: "每个 lifecycle-hook 的 dispatch 调用点 · 社区 handler 通过 `@register_hook(EventType)` 订阅。"
tags: ["hooks"]
tier: "standard"
---
# Hook surface

> 每个 lifecycle-hook 的 dispatch 调用点 · 社区 handler 通过 `@register_hook(EventType)` 订阅。

## `notification` · 11 处

- `runtime/execution/suckers/plan_mode.py:205`
- `runtime/execution/tool_engine/executor.py:784`
- `runtime/execution/tool_engine/executor.py:787`
- `runtime/execution/tool_engine/executor.py:822`
- `runtime/execution/tool_engine/executor.py:825`
- `runtime/execution/tool_engine/executor.py:1180`
- `runtime/execution/tool_engine/executor.py:1184`
- `runtime/sensing/model_router/anthropic_router.py:218`
- `runtime/sensing/model_router/anthropic_router.py:229`
- `runtime/sensing/model_router/anthropic_router.py:516`
- `runtime/sensing/model_router/anthropic_router.py:521`

## `post_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:1220`

## `pre_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:893`

## `user_prompt` · 1 处

- `runtime/sensing/gateway/realtime_turn_lifecycle.py:360`

## Defined but never dispatched

- `session_start`
- `stop`


---
type: "Graph"
title: "Hook surface"
description: "每个 lifecycle-hook 的 dispatch 调用点 · 社区 handler 通过 `@register_hook(EventType)` 订阅。"
tags: ["hooks"]
tier: "standard"
---
# Hook surface

> 每个 lifecycle-hook 的 dispatch 调用点 · 社区 handler 通过 `@register_hook(EventType)` 订阅。

## `notification` · 10 处

- `runtime/execution/suckers/plan_mode.py:205`
- `runtime/execution/tool_engine/_executor_helpers.py:788`
- `runtime/execution/tool_engine/executor.py:408`
- `runtime/execution/tool_engine/executor.py:411`
- `runtime/execution/tool_engine/executor.py:446`
- `runtime/execution/tool_engine/executor.py:449`
- `runtime/sensing/model_router/anthropic_router.py:218`
- `runtime/sensing/model_router/anthropic_router.py:229`
- `runtime/sensing/model_router/anthropic_router.py:516`
- `runtime/sensing/model_router/anthropic_router.py:521`

## `post_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:818`

## `pre_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:517`

## `session_start` · 2 处

- `runtime/sensing/gateway/realtime_turn_lifecycle.py:443`
- `runtime/sensing/gateway/realtime_turn_lifecycle.py:451`

## `stop` · 2 处

- `runtime/sensing/gateway/realtime_turn_lifecycle.py:159`
- `runtime/sensing/gateway/realtime_turn_lifecycle.py:166`

## `user_prompt` · 2 处

- `runtime/sensing/gateway/realtime_turn_lifecycle.py:444`
- `runtime/sensing/gateway/realtime_turn_lifecycle.py:453`


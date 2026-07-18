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
- `runtime/execution/tool_engine/executor.py:560`
- `runtime/execution/tool_engine/executor.py:563`
- `runtime/execution/tool_engine/executor.py:598`
- `runtime/execution/tool_engine/executor.py:601`
- `runtime/execution/tool_engine/executor.py:894`
- `runtime/execution/tool_engine/executor.py:898`
- `runtime/sensing/model_router/anthropic_router.py:218`
- `runtime/sensing/model_router/anthropic_router.py:229`
- `runtime/sensing/model_router/anthropic_router.py:516`
- `runtime/sensing/model_router/anthropic_router.py:521`

## `post_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:934`

## `pre_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:669`

## `user_prompt` · 1 处

- `runtime/sensing/gateway/realtime_turn_lifecycle.py:359`

## Defined but never dispatched

- `session_start`
- `stop`


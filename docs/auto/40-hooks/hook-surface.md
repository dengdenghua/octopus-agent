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
- `runtime/execution/tool_engine/executor.py:498`
- `runtime/execution/tool_engine/executor.py:501`
- `runtime/execution/tool_engine/executor.py:536`
- `runtime/execution/tool_engine/executor.py:539`
- `runtime/execution/tool_engine/executor.py:815`
- `runtime/execution/tool_engine/executor.py:819`
- `runtime/sensing/model_router/anthropic_router.py:218`
- `runtime/sensing/model_router/anthropic_router.py:229`
- `runtime/sensing/model_router/anthropic_router.py:516`
- `runtime/sensing/model_router/anthropic_router.py:521`

## `post_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:855`

## `pre_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:607`

## `user_prompt` · 1 处

- `runtime/sensing/gateway/realtime_turn_lifecycle.py:352`

## Defined but never dispatched

- `session_start`
- `stop`


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
- `runtime/execution/tool_engine/_executor_helpers.py:860`
- `runtime/execution/tool_engine/executor.py:527`
- `runtime/execution/tool_engine/executor.py:530`
- `runtime/execution/tool_engine/executor.py:565`
- `runtime/execution/tool_engine/executor.py:568`
- `runtime/sensing/model_router/anthropic_router.py:220`
- `runtime/sensing/model_router/anthropic_router.py:231`
- `runtime/sensing/model_router/anthropic_router.py:525`
- `runtime/sensing/model_router/anthropic_router.py:530`

## `post_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:990`

## `pre_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:639`

## `session_start` · 2 处

- `runtime/sensing/gateway/realtime_turn_lifecycle.py:665`
- `runtime/sensing/gateway/realtime_turn_lifecycle.py:673`

## `stop` · 2 处

- `runtime/sensing/gateway/realtime_turn_lifecycle.py:206`
- `runtime/sensing/gateway/realtime_turn_lifecycle.py:213`

## `user_prompt` · 2 处

- `runtime/sensing/gateway/realtime_turn_lifecycle.py:666`
- `runtime/sensing/gateway/realtime_turn_lifecycle.py:675`


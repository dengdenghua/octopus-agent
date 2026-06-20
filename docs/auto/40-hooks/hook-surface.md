# Hook surface

> 每个 lifecycle-hook 的 dispatch 调用点 · 社区 handler 通过 `@register_hook(EventType)` 订阅。

## `notification` · 11 处

- `runtime/execution/suckers/plan_mode.py:204`
- `runtime/execution/tool_engine/executor.py:279`
- `runtime/execution/tool_engine/executor.py:281`
- `runtime/execution/tool_engine/executor.py:316`
- `runtime/execution/tool_engine/executor.py:318`
- `runtime/execution/tool_engine/executor.py:753`
- `runtime/execution/tool_engine/executor.py:756`
- `runtime/sensing/model_router/anthropic_router.py:215`
- `runtime/sensing/model_router/anthropic_router.py:225`
- `runtime/sensing/model_router/anthropic_router.py:509`
- `runtime/sensing/model_router/anthropic_router.py:513`

## `post_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:791`

## `pre_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:377`

## `user_prompt` · 1 处

- `runtime/sensing/gateway/realtime_turn_lifecycle.py:217`

## Defined but never dispatched

- `session_start`
- `stop`


# Hook surface

> 每个 lifecycle-hook 的 dispatch 调用点 · 社区 handler 通过 `@register_hook(EventType)` 订阅。

## `notification` · 11 处

- `runtime/execution/suckers/plan_mode.py:204`
- `runtime/execution/tool_engine/executor.py:245`
- `runtime/execution/tool_engine/executor.py:247`
- `runtime/execution/tool_engine/executor.py:282`
- `runtime/execution/tool_engine/executor.py:284`
- `runtime/execution/tool_engine/executor.py:664`
- `runtime/execution/tool_engine/executor.py:667`
- `runtime/sensing/model_router/anthropic_router.py:215`
- `runtime/sensing/model_router/anthropic_router.py:225`
- `runtime/sensing/model_router/anthropic_router.py:509`
- `runtime/sensing/model_router/anthropic_router.py:513`

## `post_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:702`

## `pre_tool` · 1 处

- `runtime/execution/tool_engine/executor.py:343`

## `user_prompt` · 1 处

- `runtime/sensing/gateway/realtime_cerebrum.py:1463`

## Defined but never dispatched

- `session_start`
- `stop`


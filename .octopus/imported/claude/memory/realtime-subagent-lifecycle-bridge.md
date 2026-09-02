---
name: realtime-subagent-lifecycle-bridge
description: run_orchestration 子代理已能上工作台(9530afd9 per-turn journal bridge);journal 镜像此前是死代码
metadata: 
  node_type: memory
  type: project
  originSessionId: cd66e82a-76c5-4876-8fd5-b367091f4f61
  modified: 2026-08-12T09:41:34.837Z
---

audit.ultracode(run_orchestration fan-out)的子代理此前在右侧工作台只显示一条不透明的 run_orchestration 行,不渲染成 agent tiles。

**根因三层(2026-08-12 确诊):**
1. `_call_agent_parallel` → `call_subagent` 不传 `event_emitter`,in-memory 生命周期事件被丢弃;
2. journal 镜像(`_ephemeral_events._emit_subagent_lifecycle_event`)要 `session.metadata["journal"]`/`["stack"]` 注入,而全仓无生产代码注入 → 死代码;
3. realtime WS(工作台唯一数据源)没有 journal→WS consumer。前端 `mcpItemToLiveEvent`(use-thread-stream-realtime.ts)本就翻译 `__subagent_spawned__`/`__subagent_finished__` marker,是后端从未发。

**修复(9530afd9,零前端改动):** `_realtime_react_stream_drive.py` 加 per-turn journal 订阅桥:
- producer 把 stack journal `session_metadata.setdefault("journal", ...)` 注入;
- react_started 时把 task_id 写入 turn session metadata(sub-agent journal 事件带可过滤键);
- 订阅 journal,按 task_id+marker 过滤,合成 McpToolCallItem 用 `asyncio.run_coroutine_threadsafe` 发到 driver loop(no-race 规则同 `_start_orchestrator_bridge`)。

测试:`tests/test_realtime_subagent_lifecycle_bridge.py`(19 绿)。守卫 `subscribe is not _JournalBase.subscribe` 镜像 `stream_handler._has_live_subscribe`。journal 注入的基类 `Journal.subscribe` 是文档化 no-op(返回 lambda),别误判为活着。

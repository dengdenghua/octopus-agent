# 子代理卡片在主对话区显示的修复

## 问题描述

`run_orchestration` 启动的并行子代理只在右侧工作台（Agent Workbench）显示，不在主对话区显示子代理卡片。用户需要在主对话流中直接看到这些子代理的执行情况。

## 根本原因

1. **数据结构差异**：
   - 旧的单个子代理调用（`task` tool）：信息存储在 `AIMessage.tool_calls` 中
   - `run_orchestration` 批量调用：子代理信息通过 `SubagentItem` 类型存储，是独立的 item，不在 message 的 `tool_calls` 中

2. **检测逻辑缺陷**：
   - `hasSubagent()` 函数只检查 `toolCall.name === "task"`
   - 无法检测到通过 `SubagentItem` 传递的子代理信息

3. **分组和渲染问题**：
   - 消息不会被 `groupMessages` 分组为 `assistant:subagent` 类型
   - `ParallelSubtasksGrid` 只在 `assistant:subagent` 分组中渲染
   - 普通的 `assistant` 分组不会检查和显示子代理卡片

## 解决方案

### 修改的文件

1. **`frontend/src/components/workspace/messages/message-list.tsx`**
   - 添加 `allToolEvents` 参数接收所有历史 turn 的工具事件
   - 在 `assistant` 类型消息组渲染时，检查是否有子代理 spawn 事件
   - 根据 turn 的 iteration 匹配对应的子代理事件
   - 渲染 `ParallelSubtasksGrid` 或 `SubtaskCard`

2. **`frontend/src/app/workspace/realtime/[thread_id]/page.tsx`**
   - 将 `allToolEvents` 传递给 `MessageList` 组件

### 核心逻辑

```typescript
// 在渲染 assistant 消息组时
const subagentEventsInTurn = (() => {
  // 优先使用 liveToolEvents（当前 turn），回退到 allToolEvents（历史 turn）
  const eventsToSearch = liveToolEvents && liveToolEvents.length > 0
    ? liveToolEvents
    : allToolEvents ?? [];

  // 对于历史 turn，计算当前 group 属于第几个 iteration
  const currentIteration = (() => {
    const turns = partitionMessageGroupsIntoTurns(groupedMessages);
    const groupIndex = groupedMessages.indexOf(group);
    for (let i = 0; i < turns.length; i++) {
      if (turns[i]!.groupIndexes.includes(groupIndex)) {
        return i;
      }
    }
    return -1;
  })();

  // 过滤出当前 turn 的子代理 spawn 事件
  return eventsToSearch.filter((event) => {
    if (event.name !== "subagent") return false;
    if (!event.lifecycle || event.lifecycle !== "spawned") return false;
    // live 事件包含所有，历史事件按 iteration 匹配
    return isLive || event.iteration === currentIteration;
  });
})();

// 如果有子代理，渲染卡片
{hasSubagentsInTurn && group.type === "assistant" && (
  <div className="mt-4 ml-11">
    <div className="text-muted-foreground font-normal pt-2 text-sm mb-2">
      {t.subagents.executing(subagentEventsInTurn.length)}
    </div>
    {subagentEventsInTurn.length > 1 ? (
      <ParallelSubtasksGrid taskIds={...} />
    ) : (
      <SubtaskCard taskId={...} />
    )}
  </div>
)}
```

## 技术细节

### SubagentItem vs tool_calls

- **SubagentItem**：后端的一级 item 类型（`runtime/protocol/items.py`）
  - 存储：独立的 item，与 message 平级
  - 包含：`subagent_id`, `role`, `codename`, `avatar`, `iteration_count`, `files_touched` 等完整信息

- **tool_calls**：旧的 tool 调用方式
  - 存储：在 `AIMessage.tool_calls` 数组中
  - 通过 `name === "task"` 识别

### LiveToolEvent 的来源

1. **当前/最后 turn**：`liveToolEvents` / `lastTurnToolEvents`
   - 由 `useThreadStream` 提供
   - 只包含最近一个 turn 的事件

2. **所有历史 turn**：`allToolEvents`
   - 包含整个对话历史的所有工具事件
   - 每个事件带有 `iteration` 字段（turn 索引）

3. **转换流程**：
   ```
   SubagentItem (backend)
     → mcpItemToLiveEvent / subagentItemToLiveEvent (realtime stream)
     → LiveToolEvent (frontend)
     → 渲染为 SubtaskCard / ParallelSubtasksGrid
   ```

### Iteration 匹配机制

- `iteration` = turn 在对话中的索引（从0开始）
- `partitionMessageGroupsIntoTurns` 将 message groups 分组为 turns
- 通过查找 group 在哪个 turn 中，得到其 iteration
- 用 `event.iteration === currentIteration` 精确匹配子代理事件

## 测试验证

1. **类型检查**：`pnpm typecheck` ✓ 通过
2. **单元测试**：`pnpm test -- message-list` ✓ 236个测试文件通过

## 效果

- ✅ 当前 turn 的子代理卡片显示在主对话区
- ✅ 历史 turn 的子代理卡片也能正确显示
- ✅ 支持单个子代理（SubtaskCard）和多个子代理（ParallelSubtasksGrid）
- ✅ 与右侧工作台的显示保持一致

## 后续优化建议

1. **性能优化**：
   - 当前每次渲染 group 都会调用 `partitionMessageGroupsIntoTurns`
   - 可以在外层计算一次，传入 iteration 映射

2. **代码复用**：
   - `assistant:subagent` 和新增的子代理渲染逻辑有重复
   - 可以提取为共享组件

3. **更精确的匹配**：
   - 目前依赖 iteration 索引匹配
   - 如果后端能在 SubagentItem 中添加 `parentMessageId`，匹配会更准确

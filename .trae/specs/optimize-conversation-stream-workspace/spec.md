# 对话模式 / 流式 / 工作区 / 工作栏 优化 Spec

## Why

上一轮深度走查发现四个维度的切实问题：模式自动检测形同虚设（`modeFromProjectKind` 恒返回 `develop`，audit/uxui 永远无法被自动推荐）、流式状态下每次 token delta 都全量重建顶层消息状态（长对话下的性能热点）、工作区双栏 resize 逻辑高度重复、工作栏 collapsed/expanded 两套结构重复。这些属于可维护性 + 性能 + 一处功能正确性问题，价值明确、边界清晰。

## What Changes

- **模式自动检测真正生效**：`modeFromProjectKind` 不再恒返回 `develop`，让后端检测结果（builder/coder/architect）真正参与推荐，并扩展检测类型以支持 audit/uxui 的自动推荐。
- **模式切换失败回滚**：`setModeOnServer` 失败时回滚 UI 模式，保持前后端一致。
- **手动覆盖持久化**：`manualOverride` 写入 localStorage，刷新后不被自动检测抢占。
- **流式增量重算**：`conversationToAgentThreadState` 与 `liveToolEventsFromConversation` 只重算受影响的部分，避免每次 delta 全量遍历所有 turns/items。
- **工作区 resize 逻辑抽取**：将 sidebar 与 secondary 两套几乎相同的 drag/resize/keyboard/clamp 逻辑抽象为 `useResizablePanel` hook。
- **工作栏折叠态合并**：collapsed/expanded 两套结构合并为数据驱动渲染。

## Impact

- Affected specs：无（新建 spec，与既有 conversation/stream 相关 spec 边界独立）。
- Affected code：
  - `frontend/src/components/workspace/mode-selector.tsx`
  - `frontend/src/core/threads/realtime-adapter.ts`
  - `frontend/src/core/threads/use-thread-stream-realtime.ts`
  - `frontend/src/components/workspace/chat-page-layout.tsx`（新增 hook）
  - `frontend/src/components/workspace/workspace-header.tsx`

## ADDED Requirements

### Requirement: 模式自动检测生效

系统 SHALL 根据后端检测结果推荐模式，不再恒返回 `develop`。

#### Scenario: 检测推荐 audit
- **WHEN** 后端 `recommended_mode` 为已有映射的检测类型
- **THEN** `onModeChange` 收到非 `develop` 的推荐模式，automatic 模式生效

#### Scenario: 手动覆盖优先
- **WHEN** 用户已手动切换过模式（含刷新后恢复的覆盖标记）
- **THEN** 检测结果不覆盖用户选择

### Requirement: 模式切换失败回滚

系统 SHALL 在向服务端同步模式失败时回滚已变更的 UI 模式。

#### Scenario: PUT 失败
- **WHEN** `setModeOnServer` 请求失败
- **THEN** 模式回滚到原值，并提示错误

## MODIFIED Requirements

### Requirement: 流式状态增量更新

前：每次 `state` 变化全量遍历所有 turns 重建 `messages` 数组。
后：系统 SHALL 只重算受 delta 影响的 turn/item，未变化的 turn 复用既有映射结果，降低长对话下的渲染开销。

#### Scenario: 单 token delta
- **WHEN** 只有最后一轮的 agentMessage 追加了一个 token
- **THEN** 历史 turns 的消息引用不变，仅最后一轮对应消息更新

## REMOVED Requirements

无。
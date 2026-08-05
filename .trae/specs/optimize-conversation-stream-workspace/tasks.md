# Tasks

## Delta 1 · 对话模式优化

- [x] Task 1.1: 模式自动检测生效
  - [x] 修改 `modeFromProjectKind`：不再恒返回 `develop`，建立 DetectedProjectKind → AgentModeName 映射（builder→develop / coder→develop / architect→audit）
  - [x] 扩展检测类型以支持 audit/uxui 自动推荐（architect→audit 复用现有映射；uxui 无后端信号，仅手动选择）
  - [x] 补充单测：`modeFromProjectKind` 各检测类型的映射结果
- [x] Task 1.2: 模式切换失败回滚
  - [x] `handleToggle` 中 catch `setModeOnServer` 失败，回滚 `onModeChange` 到原值
  - [x] 失败时给出轻量提示（reuse 现有 toast）
  - [x] 补充 `mode-selector` 相关测试（映射/持久化纯逻辑；回滚经代码走查验证）
- [x] Task 1.3: 手动覆盖持久化
  - [x] `manualOverride` 状态写入 localStorage（key `octopus:modeOverride`，按 workspace 路径存储）
  - [x] 初始化时读取持久化覆盖标记，避免刷新后被自动检测抢占
  - [x] 补充测试：持久化读写与刷新后覆盖仍生效的存储结构

## Delta 2 · 流式增量重算

- [x] Task 2.1: 顶层消息数组增量更新
  - [x] `conversationToAgentThreadState` 缓存并复用未变化 turns 的 `Message[]`，仅重算 delta 影响的 turn（新增基于 `conv.turns` 引用的 conversation 级缓存）
  - [x] 保持 WeakMap 身份缓存语义（React.memo 依赖引用相等）
  - [x] 更新 `realtime-adapter.test.ts`：验证单 delta 时历史消息引用不变
- [x] Task 2.2: live tool events 增量重算
  - [x] `liveToolEventsFromConversation` / `liveToolEventsFromLastTurn` 避免每次全量 flatMap 所有 turns（新增基于 turns/last turn + pendingApprovals 引用的缓存）
  - [x] 复用既有 `LiveEventScopeCache`，仅重算受影响的事件
  - [x] 补充测试：验证事件数组在无相关变化时保持引用稳定

## Delta 3 · 工作区 resize 逻辑抽取

- [x] Task 3.1: 抽取 `useResizablePanel` hook
  - [x] 新建 `useResizablePanel`：封装 drag/RAF 节流/keyboard/clamp/persist 逻辑
  - [x] 迁移 `chat-page-layout.tsx` 中 sidebar 与 secondary 两套重复逻辑到该 hook
  - [x] 保持现有行为与 localStorage 持久化不变
  - [x] 走查验证拖拽/键盘调宽行为不回退（`tsc --noEmit` 通过）

## Delta 4 · 工作栏折叠态合并

- [x] Task 4.1: 工作栏渲染数据驱动
  - [x] 合并 `workspace-header.tsx` collapsed/expanded 两套结构为共享渲染逻辑（`logoItem` / `newChatItem` 数据驱动）
  - [x] 保持折叠态双 icon tile 与展开态 logo+按钮的现有视觉一致
  - [x] 走查确认侧栏折叠/展开行为不回退（`tsc --noEmit` 通过）

# Task Dependencies

- Delta 1 / Delta 2 / Delta 3 / Delta 4 相互独立，可并行处理（已并行实施）
- Task 1.2 依赖 Task 1.1 的模式回滚逻辑无硬依赖，紧随其后
- Delta 2 的 Task 2.2 依赖 2.1 的增量语义确立（事件重算基于同一身份缓存原则）
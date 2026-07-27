# 流式体验协同优化：前后端协议打通 + 对话感收尾 Spec

## Why

经过端到端审计，Octopus 与 Codex/Kimi 的真实差距不是"功能没做"，而是**协议断层 + 体验最后一公里未打通**：

1. **后端协议断层**：`ReasoningItem` 无耗时字段、`AgentPhaseSnapshot` 无业务 phase 枚举、commentary 依赖模型自觉，导致前端能感知差距但无权修
2. **前端体验断层**：9 项"看着做了实际有硬伤"的体验项（Inputs 未渲染、验收事件被静默过滤、当前帧聚焦仅 live、businessAgentPhaseKey 未启用等），spec 已定义但代码未接通
3. **协议脆弱性**：`INTERNAL_PROCESS_BLOCK_RE` 正则兜底是模型泄漏的必要防御，但后端未在 `text_delta` 路径 strip，两端都在为同一模型行为打补丁

本轮优化目标：**后端补齐协议字段，前端接通已有能力，一次性把"假完成"变"真完成"**。

## What Changes

### 后端（runtime/）

1. **ReasoningItem 增加耗时字段**：`duration_ms`（int，可选），`_emit_completed` 时计算并填充
2. **AgentPhaseSnapshot 增加业务 phase 枚举**：`phase_kind`（planning/exploring/implementing/testing/deploying/other），从 todo 文本映射
3. **强制 commentary fallback**：非 commentary 路径也注入语义角色字段（或强制启用 runtime fallback），不依赖模型守 `Update:` 协议
4. **text_delta 路径 strip 协议标签**：在 `text_delta` emit 前 strip `<ReasoningBlock>` 等泄漏标签，与 checkpoint 路径行为对齐

### 前端（frontend/src/）

5. **Inputs 区渲染**：`AgentSummaryPage` 消费 `userInput` prop，渲染用户原始请求 + 上传文件 + 附件列表
6. **验收事件不再静默过滤**：`process-trace-events.ts` 改 filter 逻辑，成功的 auto_verification 改为折叠展示而非过滤
7. **当前帧聚焦扩展到历史**：`message-group.tsx:762` 条件改为"流式结束后默认折叠，用户展开才展开"
8. **businessAgentPhaseKey 启用**：`agent-phases.ts` 的 `businessAgentPhaseKey` 接通 UI，phase 标题用业务可读名
9. **aggregatedToolGroup 加 FlipDisplay**：聚合行 count 变化走翻转动画，与 reasoningGroup/toolCall 体验对齐
10. **Workbench 内子 agent 实体化**：`AgentSummaryPage` 子 agent 区复用对话区 `SubtaskHoverPreview` 组件，头像 + popover + 跳转
11. **反向联动视觉聚焦强化**：sidebar→chat 高亮加边框/缩放，命中聚合组时可展开子项
12. **timelineExpanded 死代码处理**：决定删除或接通 `leadInTimelineItems/replayTimelineItems/currentTimelineItem` 三分支
13. **移动端 72vh drawer 过渡**：加 handle/延迟展开，避免视觉冲击
14. **思考耗时持久化展示**：流式中 live 显示，结束后从 `ReasoningItem.duration_ms` 读取回放显示

### 联动

- 后端 `phase_kind` 启用后，前端 `businessAgentPhaseKey` 降级为 fallback（后端优先）
- 后端 `duration_ms` 启用后，前端 live 计时降级为 fallback（后端优先）

## Impact

- Affected specs：`stream-ux-dialogue-feel`、`stream-ux-timeline-narrative`（本 spec 吸收其 P1/P2 未落地项）
- Affected code：
  - 后端：`runtime/protocol/items.py`、`runtime/sensing/gateway/realtime_event_bridge.py`、`runtime/sensing/gateway/realtime_workbench.py`、`runtime/sensing/gateway/tool_bridge.py`、`runtime/core/cerebrum/react_loop.py`
  - 前端：`frontend/src/components/workspace/messages/message-group.tsx`、`frontend/src/components/workspace/agent-workbench-pages.tsx`、`frontend/src/core/threads/process-trace-events.ts`、`frontend/src/components/workspace/agent-phases.ts`、`frontend/src/components/workspace/agent-workbench-panel.tsx`、`frontend/src/components/workspace/chat-page-layout.tsx`
- Tests：
  - 后端：protocol schema 测试、phase_kind 映射测试、commentary fallback 测试
  - 前端：Inputs 区渲染测试、验收事件折叠测试、当前帧聚焦历史折叠测试、businessAgentPhaseKey UI 消费测试、聚合行 FlipDisplay 测试、Workbench 子 agent popover 测试、反向联动强化测试

## ADDED Requirements

### Requirement: 思考耗时持久化

系统 SHALL 在 `ReasoningItem` 上持久化思考耗时，流式中 live 显示，结束后回放可读。

#### Scenario: 流式中
- **WHEN** 模型开始 thinking_delta
- **THEN** 前端 live 显示"思考中…"（spinner），思考结束时显示"思考了 N 秒"

#### Scenario: 结束后回放
- **WHEN** 用户查看历史对话或 run review
- **THEN** 思考块显示持久化的耗时（"思考了 N 秒"），从 `ReasoningItem.duration_ms` 读取

#### Scenario: 后端未给耗时
- **WHEN** 后端未返回 `duration_ms`（旧数据）
- **THEN** 前端 live 显示"思考中…"，结束后不显示耗时（不编造）

### Requirement: 业务 phase 结构化命名

系统 SHALL 在 `AgentPhaseSnapshot` 上提供业务 phase 枚举，UI 显示业务可读名。

#### Scenario: 有 todo 的场景
- **WHEN** 后端从 `todo_write` 推导 phase
- **THEN** `phase_kind` 映射到 planning/exploring/implementing/testing/deploying 之一，UI 显示"分析需求中…/了解代码结构…/开始修改代码…/验证修改…/部署中…"

#### Scenario: 无 todo 的场景
- **WHEN** 模型未调用 `todo_write`
- **THEN** `phase_kind` 为 other，UI 显示"进行中"

#### Scenario: 后端未给 phase_kind
- **WHEN** 后端未返回 `phase_kind`（旧数据）
- **THEN** 前端 fallback 到 `businessAgentPhaseKey` 本地映射

### Requirement: commentary 不依赖模型自觉

系统 SHALL 确保 commentary item 存在，不依赖模型守 `Update:` 协议。

#### Scenario: 模型守协议
- **WHEN** 模型产出 `Update:` 标签
- **THEN** commentary item 正常生成，协议字段齐全

#### Scenario: 模型不守协议
- **WHEN** 模型未产出 `Update:` 标签
- **THEN** 后端强制启用 runtime fallback 生成 commentary，协议字段齐全，前端正常渲染

### Requirement: Inputs 区渲染

系统 SHALL 在 Workbench 概要 tab 显示用户原始输入。

#### Scenario: 有用户输入
- **WHEN** 用户发起任务
- **THEN** Inputs 区显示原始请求文本 + 上传文件列表 + 附件列表

#### Scenario: 无附件
- **WHEN** 用户仅输入文本
- **THEN** Inputs 区仅显示文本，不显示空文件列表

### Requirement: 验收事件可见

系统 SHALL 不再静默过滤成功的 auto_verification 事件。

#### Scenario: 成功的验收
- **WHEN** auto_verification 通过（status=done）
- **THEN** 在过程追踪中折叠展示（而非过滤），点击可展开查看

#### Scenario: 失败的验收
- **WHEN** auto_verification 失败
- **THEN** 保持现有展开展示行为

### Requirement: 当前帧聚焦历史默认折叠

系统 SHALL 在流式结束后默认折叠历史 phase，用户展开才展开。

#### Scenario: 流式结束后
- **WHEN** agent 完成本轮任务
- **THEN** 历史 phase 默认折叠为"✓ 完成了 N 件事"摘要，当前 phase 保持展开

#### Scenario: 用户展开历史
- **WHEN** 用户点击已折叠的历史 phase
- **THEN** 展开显示完整动作行，且不自动收回

### Requirement: businessAgentPhaseKey UI 消费

系统 SHALL 在 UI 显示业务 phase 名，而非 todo 原文或通用桶。

#### Scenario: 后端给了 phase_kind
- **WHEN** 后端返回 `phase_kind=implementing`
- **THEN** UI 显示"开始修改代码…"

#### Scenario: 后端未给 phase_kind
- **WHEN** 后端未返回 `phase_kind`
- **THEN** UI 用 `businessAgentPhaseKey` 本地映射 todo 文本为业务 phase 名

### Requirement: 聚合行翻转动画

系统 SHALL 在聚合行 count 变化时使用翻转动画，与 reasoningGroup/toolCall 体验对齐。

#### Scenario: 进行中聚合
- **WHEN** 流式进行中聚合计数变化（"编辑了 2 个文件…" → "编辑了 3 个文件…"）
- **THEN** 数字翻转动画，不重建 DOM，不闪烁

### Requirement: Workbench 子 agent 实体化

系统 SHALL 在 Workbench 内提供与对话区一致的子 agent 实体化体验。

#### Scenario: Workbench 内查看子 agent
- **WHEN** 用户在 Workbench 概要 tab 查看子 agent 列表
- **THEN** 每个子 agent 显示头像 + 角色 + 状态 + 进度条，hover/点击展开 popover（prompt + 跳转按钮）

### Requirement: 反向联动视觉聚焦

系统 SHALL 在 sidebar→chat 联动时提供明确的视觉聚焦。

#### Scenario: 侧边栏点击事件
- **WHEN** 用户点击 Workbench 事件
- **THEN** 对话区滚动定位 + 高亮边框/缩放 2s，命中聚合组时可展开子项

### Requirement: timelineExpanded 死代码处理

系统 SHALL 移除或接通 `timelineExpanded = false` 导致的死代码分支。

#### Scenario: 决定删除
- **WHEN** 确认三个分支（leadInTimelineItems/replayTimelineItems/currentTimelineItem）不再需要
- **THEN** 移除相关代码，减少维护负担

#### Scenario: 决定接通
- **WHEN** 确认三个分支有产品价值
- **THEN** 接通逻辑，使分支可渲染

### Requirement: 移动端 drawer 过渡

系统 SHALL 在移动端 Workbench drawer 提供平滑过渡，避免 72vh 冲击。

#### Scenario: 首次打开
- **WHEN** 用户首次打开 Workbench
- **THEN** drawer 从底部 handle 状态展开，而非直接 72vh 全屏

## MODIFIED Requirements

### Requirement: 时间线语义角色

系统 SHALL 为对话区时间线的每个可见条目赋予显式语义角色（`intent / execution / fact / answer`），且推断优先级为：后端结构化协议字段 > 消息类型与位置 > 正则启发式（fallback，须标记 `inferred`）。

**修改点**：`public_progress` 字段不再依赖模型守 `Update:` 协议，后端强制启用 runtime fallback 确保 commentary item 存在。

#### Scenario: 模型不守协议
- **WHEN** 一轮对话只有工具调用与普通 content、模型未守 `Update:` 协议
- **THEN** 后端强制启用 runtime fallback 生成 commentary，时间线仍按"意图→执行→最终回答"顺序呈现，协议字段齐全，无 `inferred` 标记

## REMOVED Requirements

无。

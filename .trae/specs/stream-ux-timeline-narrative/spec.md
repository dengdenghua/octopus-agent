# 流式 UX 时间线叙事与侧边栏联动优化 Spec

## Why

当前流式对话在执行密集的长任务中，对话区退化为「工具调用行堆叠」，缺少 Codex / Kimi 式的叙事节奏：**简短意图 → 实际执行 → 已确认事实 → 继续行动 → 最终回答**。右侧边栏与对话区数据同源但无双向联动，「进展」面板停留在 step 平铺，不能承担「叙事大纲」角色。

## 审核发现（现状基线）

代码事实（frontend/ 下，行号为审核时快照）：

1. **渲染管线**：[message-group.tsx](../../../frontend/src/components/workspace/messages/message-group.tsx) 的 `convertToSteps`（L2453）按消息顺序产出 `CoTStep[]`（reasoning / toolCall / commentary / actionCallback），`groupConsecutiveReasoningSteps`（L1951）将连续同类步骤折叠成组。时间线顺序本身保留，**但叙事角色（意图/事实确认）完全依赖后端协议字段**（`additional_kwargs.public_progress`、`phase_id`、`progress_sequence` 与 `extractPublicReasoningSummary`）；模型未按协议输出时，普通 content 不进时间线，对话区只剩工具调用堆叠 —— 这正是「只堆执行步骤」的根因。
2. **脆弱启发式**：`INTERNAL_PROCESS_BLOCK_RE`（message-group.tsx L91）用正则从 content 文本猜 `ReasoningBlock / ToolCallBlock / ToolResultBlock`，是后端缺少结构化事件契约时的补偿手段，误判会产生重复旁白或丢失段落。
3. **紧凑模式**：`selectCompactTimelineItems`（L2032）长跑时仅保留 4 个均匀采样的 commentary 锚点 + 最近 thinking + 每区间 1 个执行锚点，采样不考虑叙事语义，可能把「意图」和「事实确认」都裁掉。
4. **执行行信息贫瘠**：toolCall 行只展示工具名 + 参数 + 原始结果，没有「这一步确认了什么」的一句话事实摘要，用户无法快速跟上 Agent 的推进逻辑。
5. **侧边栏联动缺口**：侧边栏（[sidebar-footer.tsx](../../../frontend/src/components/workspace/sidebar-footer.tsx) + [core/threads/sidebar.ts](../../../frontend/src/core/threads/sidebar.ts)）与对话区共享同一 store（单一数据源，优点保留），但「进展」面板为 step 平铺、无 iteration 分组、无意图/结论摘要；对话区 ↔ 侧边栏无稳定的双向定位（点击时间线项 → 侧边栏展开对应详情的路径不完整，侧边栏 → 对话区滚动定位/高亮缺失）。

## What Changes

- **P0 时间线语义层**：在 timeline 构建层引入显式语义角色（`intent / execution / fact / answer`），结构化协议字段优先推断，正则启发式降级为 fallback 且输出标记 `inferred=true` 便于后续治理。
- **P0 执行行事实摘要**：工具调用完成后，从结构化 result 中提取一句话「已确认事实」附在执行行（弱显示样式），无结构化结果时不编造。
- **P1 对话区 ↔ 侧边栏双向联动**：点击对话区时间线项 → 侧边栏定位并展开对应详情；侧边栏条目点击/hover → 对话区滚动定位 + 短暂高亮同一时间线项。
- **P1 「进展」面板升级为叙事大纲**：按 iteration 分组，每轮显示意图摘要、执行计数、已确认事实，替代 step 平铺。
- **P2 紧凑模式叙事保真**：压缩采样改为语义感知（意图/事实锚点必留），不再纯均匀采样。
- **P2 最终回答视觉分层**：流式结束后最终回答与过程段落在视觉上有明确分界（不改变弱显示原则）。

非目标（明确排除）：

- 不改后端事件协议（结构化事件契约推动另立 spec；本 spec 只在前端层做语义归一与兜底）。
- 不改弱显示设计原则（默认折叠、透明背景、小字 —— 用户既定偏好）。
- 不重构 message-group.tsx 的组件拆分（已有独立排期）。

## Impact

- Affected specs：无既有 spec 直接冲突；与 `release-acceptance` 的 UX 验收项有交集。
- Affected code：
  - `frontend/src/components/workspace/messages/message-group.tsx`（convertToSteps / groupConsecutiveReasoningSteps / selectCompactTimelineItems / TimelineItem 渲染）
  - `frontend/src/components/workspace/messages/message-grouping.ts`（语义分类工具函数落点）
  - `frontend/src/components/workspace/messages/process-trace.tsx`（执行行事实摘要渲染）
  - `frontend/src/core/threads/sidebar.ts`、`frontend/src/components/workspace/sidebar-footer.tsx`（侧边栏大纲与联动）
  - 「进展」面板组件（进展 store selector）
  - 相关单测：messages 分组测试、sidebar 测试

## ADDED Requirements

### Requirement: 时间线语义角色

系统 SHALL 为对话区时间线的每个可见条目赋予显式语义角色（`intent` 简短意图 / `execution` 实际执行 / `fact` 已确认事实 / `answer` 最终回答），且推断优先级为：后端结构化协议字段 > 消息类型与位置 > 正则启发式（fallback，须标记 `inferred`）。

#### Scenario: 协议字段齐全的流式过程

- **WHEN** 后端流式事件带 `public_progress` / `phase_id` / `progress_sequence`
- **THEN** 时间线条目的语义角色全部来自结构化字段，不触发正则 fallback，无 `inferred` 标记

#### Scenario: 模型未按协议输出

- **WHEN** 一轮对话只有工具调用与普通 content、无任何协议字段
- **THEN** 时间线仍按「意图(content 首段) → 执行(工具调用) → 最终回答(content 尾段)」顺序呈现，且由 fallback 推断的条目标记 `inferred=true`，不产生重复旁白

### Requirement: 执行行事实摘要

系统 SHALL 在工具调用完成（result 已返回）时，从结构化结果提取一句话「已确认事实」附于该执行行之下，样式遵循弱显示原则（小字、text-muted-foreground、无气泡）。

#### Scenario: 结构化结果可提取

- **WHEN** 工具 result 为可解析 JSON 且含可用摘要字段（如 path / count / status / title 等）
- **THEN** 执行行下方出现一句话事实（例：「已确认：找到 12 个匹配文件」），点击可在侧边栏查看完整结果

#### Scenario: 结果不可解析

- **WHEN** 工具 result 为空或非结构化文本
- **THEN** 不显示事实摘要（不编造），执行行保持现状

### Requirement: 对话区与侧边栏双向联动

系统 SHALL 支持对话区时间线项与侧边栏「进展/上下文」条目的双向定位：任一侧激活某项，另一侧滚动定位并短暂高亮同一项（共享同一时间线 item id，单一数据源）。

#### Scenario: 对话区 → 侧边栏

- **WHEN** 用户点击对话区某时间线项（执行行/意图行）
- **THEN** 右侧边栏展开对应详情条目并滚动至可见区域

#### Scenario: 侧边栏 → 对话区

- **WHEN** 用户点击侧边栏「进展」面板某条目
- **THEN** 对话区滚动至对应时间线项并短暂高亮（≤2s 的 outline/背景脉冲，随后恢复）

### Requirement: 进展面板叙事大纲

系统 SHALL 将「进展」面板从 step 平铺升级为按 iteration 分组的叙事大纲：每轮显示意图摘要（一行）、执行计数（如「3 个动作」）、已确认事实列表（各一行）。

#### Scenario: 多轮长任务

- **WHEN** 一次运行包含 ≥3 轮「意图→执行」循环
- **THEN** 进展面板按轮分组展示，每轮可折叠，默认展开最近一轮

### Requirement: 紧凑模式叙事保真

系统 SHALL 在紧凑模式下优先保留语义锚点（每轮至少 1 个意图条目 + 最新事实条目），再按均匀采样补足，替代现有纯均匀采样。

#### Scenario: 长任务压缩

- **WHEN** 时间线条目超过紧凑阈值触发压缩
- **THEN** 每个 iteration 至少保留一个 intent 条目，最近一个 fact 条目必保留，用户仍能读出「意图→执行→确认」的完整节奏

## MODIFIED Requirements

### Requirement: 过程弱显示（既有用户偏好）

既有偏好：thinking/执行过程默认折叠、透明背景、小字，点击后在右侧边栏展开。本 spec 修改其为：弱显示原则不变，但每个执行行允许新增一行事实摘要（同属弱显示层级），且点击行为从「仅展开侧边栏」升级为「展开侧边栏并双向定位高亮」。

## REMOVED Requirements

无（`INTERNAL_PROCESS_BLOCK_RE` 不删除，仅降级为 fallback；待后端结构化契约落地后再行移除，另立 spec 跟踪）。

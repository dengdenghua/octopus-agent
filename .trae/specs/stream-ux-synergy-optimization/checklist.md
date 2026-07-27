# Checklist

> 最后核查：2026-07-27（代码级 grep + 文件读取验证）

## 后端协议（4 项）

- [x] `ReasoningItem` 含 `duration_ms` 字段，完成时填充，旧数据 None 兼容
  - 证据：`runtime/protocol/items.py:136-143` ReasoningItem 增加 `duration_ms: int | None = None`（alias `durationMs`）；`runtime/sensing/gateway/realtime_event_bridge.py:198-201` 记录 `reasoning_started_monotonic`，`:345` 首次 append 时填充，`:841-853` finalize 时计算 duration_ms 并 emit；测试 `tests/test_delta_coalescing.py:282-345` 覆盖 happy path + 无 reasoning + 旧数据兼容 + round-trip
- [x] `AgentPhaseSnapshot` 含 `phase_kind` 字段，5 种业务 phase 正确映射，无 todo 时为 other
  - 证据：`runtime/protocol/items.py:172-175` AgentPhaseSnapshot 增加 `phase_kind: str = "other"` 字段；`runtime/sensing/gateway/realtime_workbench.py:200-217` 定义 `_PHASE_KIND_PATTERNS` 5 类正则（deploying/testing/implementing/planning/exploring），`:223-235` `_phase_kind()` 函数映射，`:57` 在 `_phases_from_todo_preview` 中调用
  - 测试：`tests/test_phase_kind_mapping.py` 56 个用例覆盖 EN/CN 关键词 + 优先级 + 子串陷阱 + 默认值 + round-trip + `_phases_from_todo_preview` 集成
- [ ] 模型不守 `Update:` 协议时 commentary item 仍生成，协议字段齐全
  - 状态：**未实装**。`runtime/core/cerebrum/react_loop.py` 有 8 处 `commentary_delta` emit 点，但 grep `commentary.*fallback|_commentary_fallback` 零匹配，无 runtime fallback 机制
- [ ] text_delta 路径 strip `<ReasoningBlock>` 等泄漏标签，正常文本不受影响
  - 状态：**未实装**。grep `INTERNAL_PROCESS_BLOCK_RE|ReasoningBlock.*strip` 在 `runtime/` 零匹配；strip 逻辑只在前端 `frontend/src/components/workspace/messages/message-group.tsx:163`，后端 `realtime_event_bridge.py` 的 text_delta 路径未 strip

## 前端体验（9 项）

- [x] Inputs 区渲染用户原始请求 + 上传文件 + 附件列表，i18n 4 语言
  - 证据：`frontend/src/components/workspace/agent-workbench-pages.tsx:802-903` 已消费 `userInput` prop，渲染 `inputText` + `inputUploadedFiles` + `inputAttachments`
- [x] 成功的 auto_verification 事件折叠展示而非过滤，失败事件保持展开
  - 证据：`frontend/src/components/workspace/process-trace-events.ts:20-24` 已有 `isCollapsibleAutoVerificationEvent`（`status === "done"` 时折叠而非过滤）
- [x] 流式结束后历史 phase 默认折叠为"✓ 完成了 N 件事"，用户展开后不收回
  - 证据：`frontend/src/components/workspace/messages/message-group.tsx:505-526` 注释明确"streaming 结束后历史 phase 默认折叠"，`expandedHistoryPhases[phaseId]` 持久化用户展开选择
- [ ] phase 标题优先用后端 `phase_kind`，fallback 到 `businessAgentPhaseKey` 本地映射
  - 状态：**半完成**。`frontend/src/components/workspace/agent-phases.ts:125,300` 前端已在用 `businessAgentPhaseKey`，但因后端 Task 2（phase_kind）未实装，前端无法"优先用后端"——目前只有 fallback 路径，无后端优先路径
- [x] 聚合行 count 变化走 FlipDisplay 翻转动画，DOM 不重建
  - 证据：`frontend/src/components/workspace/messages/message-group.tsx:42` import FlipDisplay，`:900-904` 在 aggregatedToolGroup 渲染中使用 `<FlipDisplay uniqueKey={item.id}>`
- [x] Workbench 子 agent 区复用 SubtaskHoverPreview，头像 + popover + 跳转
  - 证据：`frontend/src/components/workspace/agent-workbench-pages.tsx:50` import `SubtaskHoverPreview`，`:712` 注释"头像 + hover popover（复用 SubtaskHoverPreview）+ 点击/按钮跳转"，`:782` 实际使用
- [x] sidebar→chat 高亮加边框/缩放，命中聚合组可展开子项
  - 证据：`frontend/src/core/threads/timeline-linkage.ts:1-80` 已实现双向联动 reducer，`:39` `TIMELINE_ITEM_HIGHLIGHT_CLASS` 高亮样式 class，`:64` sidebar 来源时设置 `highlightedTimelineItemId`
- [x] timelineExpanded 死代码已删除或接通
  - 证据：grep `timelineExpanded|leadInTimelineItems|replayTimelineItems|currentTimelineItem` 在 `frontend/src/` 完全零匹配，死代码已删除
- [x] 移动端 drawer 首次打开非全屏，可手动展开
  - 证据：`frontend/src/components/workspace/chat-page-layout.tsx:153-159` 注释"Narrow-viewport workbench drawer opens in a collapsed 'peek' state and only grows to its full 72vh height after an explicit tap / swipe-up on the grab handle"，`mobileDrawerExpanded` state 控制

## 联动（2 项）

- [ ] 后端给了 phase_kind 时前端优先用后端，businessAgentPhaseKey 降级为 fallback
  - 状态：**阻塞**。依赖后端 Task 2（phase_kind）实装后才能联调
- [ ] 流式中 live 显示思考耗时，结束后从 `ReasoningItem.duration_ms` 读取回放显示
  - 状态：**阻塞**。依赖后端 Task 1（ReasoningItem.duration_ms）实装后才能联调

## 回归（3 项）

- [ ] 简单对话（无工具调用）渲染不变
- [ ] markdown 渲染、ToolApprovalCard、message-output-summary 不受影响
- [ ] 4 语言 i18n 无缺失词条

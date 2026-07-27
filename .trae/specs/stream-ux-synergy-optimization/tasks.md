# Tasks

> 最后核查：2026-07-27（代码级 grep + 文件读取验证）

## 后端协议打通（4 项）

- [x] Task 1: ReasoningItem 增加耗时字段
  - [x] SubTask 1.1: `runtime/protocol/items.py:136-143` 的 `ReasoningItem` 增加 `duration_ms: int | None = None` 字段（alias `durationMs`）
  - [x] SubTask 1.2: `runtime/sensing/gateway/realtime_event_bridge.py:198-201,345,841-853` 的 `_ReactBridgeState` 记录 `reasoning_started_monotonic`，finalize 时计算并填充 `duration_ms`
  - [x] SubTask 1.3: 单测覆盖：`tests/test_delta_coalescing.py:282-345` 4 个用例（happy path + 无 reasoning + 旧数据兼容 + round-trip）全部通过

- [x] Task 2: AgentPhaseSnapshot 增加业务 phase 枚举
  - [x] SubTask 2.1: `runtime/protocol/items.py:172-175` 的 `AgentPhaseSnapshot` 增加 `phase_kind: str = "other"` 字段
  - [x] SubTask 2.2: `runtime/sensing/gateway/realtime_workbench.py:200-217,223-235,57` 定义 `_PHASE_KIND_PATTERNS` + `_phase_kind()` 函数，在 `_phases_from_todo_preview` 中调用
  - [x] SubTask 2.3: 单测覆盖：`tests/test_phase_kind_mapping.py` 56 个用例（EN/CN 关键词 + 优先级 + 子串陷阱 + 默认值 + round-trip + 集成）全部通过
  - **核查修正**：首次核查误判为未实装（grep 只匹配 `_phases_from_todo` 未显示 `_phase_kind`）。代码实际已完整实装

- [ ] Task 3: 强制 commentary fallback
  - [ ] SubTask 3.1: `runtime/core/cerebrum/react_loop.py` 的 commentary 生成逻辑：模型未守 `Update:` 协议时强制启用 runtime fallback
  - [ ] SubTask 3.2: 单测覆盖：模型不守协议时 commentary item 仍生成，协议字段齐全
  - **核查状态**：未实装。react_loop.py 有 8 处 `commentary_delta` emit 点，但 grep `commentary.*fallback|_commentary_fallback` 零匹配

- [ ] Task 4: text_delta 路径 strip 协议标签
  - [ ] SubTask 4.1: `runtime/sensing/gateway/realtime_event_bridge.py` 的 text_delta emit 前 strip `<ReasoningBlock>` 等泄漏标签
  - [ ] SubTask 4.2: 单测覆盖：泄漏标签被 strip，正常文本不受影响
  - **核查状态**：未实装。grep `INTERNAL_PROCESS_BLOCK_RE|ReasoningBlock.*strip` 在 `runtime/` 零匹配；strip 逻辑只在前端 `message-group.tsx:163`

## 前端体验收尾（9 项）

- [x] Task 5: Inputs 区渲染
  - [x] SubTask 5.1: `frontend/src/components/workspace/agent-workbench-pages.tsx:802-903` 已消费 `userInput` prop，渲染 `inputText` + `inputUploadedFiles` + `inputAttachments`
  - [x] SubTask 5.2: i18n 4 语言词条补充
  - [x] SubTask 5.3: 单测覆盖：有附件/无附件两种场景

- [x] Task 6: 验收事件不再静默过滤
  - [x] SubTask 6.1: `frontend/src/components/workspace/process-trace-events.ts:20-24` 已有 `isCollapsibleAutoVerificationEvent`（`status === "done"` 时折叠而非过滤）
  - [x] SubTask 6.2: 单测覆盖：done 事件被折叠而非过滤，非 done 事件保持展开

- [x] Task 7: 当前帧聚焦扩展到历史
  - [x] SubTask 7.1: `frontend/src/components/workspace/messages/message-group.tsx:505-526` 注释明确"streaming 结束后历史 phase 默认折叠"，`expandedHistoryPhases[phaseId]` 持久化用户展开选择
  - [x] SubTask 7.2: 单测覆盖：结束后历史 phase 折叠，用户展开后不收回

- [ ] Task 8: businessAgentPhaseKey UI 消费
  - [ ] SubTask 8.1: `frontend/src/components/workspace/agent-phases.ts` 的 phase 标题渲染逻辑：优先用后端 `phase_kind`，fallback 到 `businessAgentPhaseKey`
  - [ ] SubTask 8.2: 单测覆盖：后端给了 phase_kind 时用后端，没给时用本地映射
  - **核查状态**：半完成。`agent-phases.ts:125,300` 前端已在用 `businessAgentPhaseKey`，但因后端 Task 2 未实装，前端只有 fallback 路径，无后端优先路径

- [x] Task 9: aggregatedToolGroup 加 FlipDisplay
  - [x] SubTask 9.1: `frontend/src/components/workspace/messages/message-group.tsx:42` import FlipDisplay，`:900-904` 在 aggregatedToolGroup 渲染中使用 `<FlipDisplay uniqueKey={item.id}>`
  - [x] SubTask 9.2: 单测覆盖：count 变化时数字翻转，DOM 不重建

- [x] Task 10: Workbench 内子 agent 实体化
  - [x] SubTask 10.1: `frontend/src/components/workspace/agent-workbench-pages.tsx:50` import `SubtaskHoverPreview`，`:712,782` 实际使用，注释"头像 + hover popover + 点击/按钮跳转"
  - [x] SubTask 10.2: 单测覆盖：头像 + popover + 跳转按钮渲染

- [x] Task 11: 反向联动视觉聚焦强化
  - [x] SubTask 11.1: `frontend/src/core/threads/timeline-linkage.ts:39` `TIMELINE_ITEM_HIGHLIGHT_CLASS` 高亮样式 class，`:64` sidebar 来源时设置 `highlightedTimelineItemId`
  - [x] SubTask 11.2: 命中聚合组时可展开子项
  - [x] SubTask 11.3: 单测覆盖：高亮样式 + 聚合组展开

- [x] Task 12: timelineExpanded 死代码处理
  - [x] SubTask 12.1: 确认 `leadInTimelineItems/replayTimelineItems/currentTimelineItem` 三分支的去留（删除或接通）
  - [x] SubTask 12.2: 执行决定：grep 确认死代码已删除（`frontend/src/` 完全零匹配）

- [x] Task 13: 移动端 drawer 过渡
  - [x] SubTask 13.1: `frontend/src/components/workspace/chat-page-layout.tsx:153-159` 已实现 peek state + grab handle + `mobileDrawerExpanded` state，首次打开非全屏
  - [x] SubTask 13.2: 单测覆盖：首次打开非全屏，可手动展开

## 联动与验证（2 项）

- [ ] Task 14: 后端 phase_kind 与前端 businessAgentPhaseKey 联动
  - [ ] SubTask 14.1: 后端给了 phase_kind 时前端优先用后端，businessAgentPhaseKey 降级为 fallback
  - [ ] SubTask 14.2: 单测覆盖：联动优先级正确
  - **核查状态**：阻塞。依赖 Task 2 实装后才能联调

- [ ] Task 15: 思考耗时持久化展示
  - [ ] SubTask 15.1: 流式中 live 显示（前端计时），结束后从 `ReasoningItem.duration_ms` 读取回放显示
  - [ ] SubTask 15.2: 单测覆盖：live + 回放两种路径
  - **核查状态**：阻塞。依赖 Task 1 实装后才能联调

# Task Dependencies

- Task 5/6/7/8/9/10/11/12/13（前端 9 项）**无依赖**，可并行
- Task 14 依赖 Task 2（后端 phase_kind）和 Task 8（前端 businessAgentPhaseKey 启用）
- Task 15 依赖 Task 1（后端 duration_ms）
- Task 4（text_delta strip）不阻塞前端，但完成后前端 INTERNAL_PROCESS_BLOCK_RE 可降级为 fallback

# 当前状态总结（2026-07-27 核查）

- 已完成：Task 1, 2, 5, 6, 7, 9, 10, 11, 12, 13（10 项）
- 半完成：Task 8（前端就绪，后端 phase_kind 已实装，可联调）
- 未实装：Task 3, 4（2 项后端协议）
- 阻塞中：Task 14（已解锁，可联调）、Task 15（已解锁，等前端实装回放读取）
- **下一步优先级**：实装 Task 3 + Task 4（最后两项后端协议），然后联调 Task 8/14/15

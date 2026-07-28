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

- [x] Task 3: 强制 commentary fallback
  - [x] SubTask 3.1: `runtime/core/cerebrum/react_loop.py:555-580,4844-4862` `_runtime_fallback_public_update()` 函数 + 检测 `_model_supplied_update=False` 时调用
  - [x] SubTask 3.2: 单测覆盖：`tests/test_react_loop.py:1221-1242` `test_missing_public_update_emits_runtime_fallback_commentary` 验证 fallback 触发 + 字段齐全
  - **核查修正**：首次核查 grep `commentary.*fallback|_commentary_fallback` 零匹配误判。实际函数名是 `_runtime_fallback_public_update`，grep 关键词过窄

- [x] Task 4: text_delta 路径 strip 协议标签
  - [x] SubTask 4.1: `runtime/sensing/gateway/tool_bridge.py:146-170,173` 三层正则 + `strip_leaked_protocol_tags()` 函数；`realtime_event_bridge.py:55,312` 在 text_delta 路径调用
  - [x] SubTask 4.2: 单测覆盖：`tests/test_realtime_event_bridge.py:62-141` 25+ 用例（成对块/单标签/正常文本/CJK/代码块/JSON）
  - **核查修正**：首次核查 grep `ReasoningBlock.*strip` 要求同行匹配误判。实际正则定义、函数、调用分三处，grep 关键词过窄

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

- [x] Task 8: businessAgentPhaseKey UI 消费
  - [x] SubTask 8.1: `frontend/src/components/workspace/agent-phases.ts:124-125` 的 phase 标题渲染逻辑：`normalizeBusinessPhaseKey(record.phaseKind ?? record.phase_kind) ?? businessAgentPhaseKey(displayTitle)` — 优先用后端 `phase_kind`，fallback 到 `businessAgentPhaseKey`
  - [x] SubTask 8.2: 单测覆盖：`frontend/src/components/workspace/agent-phases.test.ts:490-506` `tolerates snake_case phase_kind when the adapter does not camelCase` 验证后端给了 phase_kind 时用后端；`:368-385` 验证没给时用本地映射
  - **核查修正**：2026-07-27 核查误判为"半完成"（认为后端 Task 2 未实装）。实际 Task 2 后端已实装（`runtime/protocol/items.py:172-175` + `realtime_workbench.py:200-235`），前端联动路径完整

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

- [x] Task 14: 后端 phase_kind 与前端 businessAgentPhaseKey 联动
  - [x] SubTask 14.1: `agent-phases.ts:124` `normalizeBusinessPhaseKey(record.phaseKind ?? record.phase_kind)` 优先用后端，`?? businessAgentPhaseKey(displayTitle)` 降级为 fallback
  - [x] SubTask 14.2: 单测覆盖：`agent-phases.test.ts:490-506` 验证 snake_case phase_kind 联动优先级正确
  - **核查修正**：2026-07-27 标记为"阻塞依赖 Task 2"，实际 Task 2 已实装，联动代码 + 单测均完整

- [x] Task 15: 思考耗时持久化展示
  - [x] SubTask 15.1: `message-group.tsx:736-748` 完成态从 `additional_kwargs.reasoning_duration_ms` 读取；`:497-516` 进行中态从 `reasoning_started_at`（`ReasoningItem.createdAt` 经 `realtime-adapter.ts:370-376` 传播）启动 live 计时
  - [x] SubTask 15.2: `message-group.test.tsx` `reasoning duration replay` (3 用例) + `reasoning live timer from backend timestamp` (2 用例) 覆盖回放 + live 路径，60 passed

# Task Dependencies

- Task 5/6/7/8/9/10/11/12/13（前端 9 项）**无依赖**，可并行
- Task 14 依赖 Task 2（后端 phase_kind）和 Task 8（前端 businessAgentPhaseKey 启用）
- Task 15 依赖 Task 1（后端 duration_ms）
- Task 4（text_delta strip）不阻塞前端，但完成后前端 INTERNAL_PROCESS_BLOCK_RE 可降级为 fallback

# 当前状态总结（2026-07-28 更新）

- 已完成：Task 1-15（全部 15 项，含 Task 8/14/15，checklist.md 全绿佐证）
- **核查失误记录**：Task 2/3/4 首次核查均误判为未实装，根因是 grep 关键词过窄（要求多个关键词同行匹配）。实际代码均已完整实装且有测试覆盖
- **下一步**：全部任务已完成，无剩余工作

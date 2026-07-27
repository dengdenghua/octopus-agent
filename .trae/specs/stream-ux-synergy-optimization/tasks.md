# Tasks

## 后端协议打通（4 项）

- [ ] Task 1: ReasoningItem 增加耗时字段
  - [ ] SubTask 1.1: `runtime/protocol/items.py` 的 `ReasoningItem` 增加 `duration_ms: int | None = None` 字段
  - [ ] SubTask 1.2: `runtime/sensing/gateway/realtime_event_bridge.py` 的 `_emit_completed` 在 ReasoningItem 完成时计算耗时并填充
  - [ ] SubTask 1.3: 单测覆盖：duration_ms 计算逻辑 + 旧数据兼容（None 不报错）

- [ ] Task 2: AgentPhaseSnapshot 增加业务 phase 枚举
  - [ ] SubTask 2.1: `runtime/protocol/items.py` 的 `AgentPhaseSnapshot` 增加 `phase_kind: str = "other"` 字段（planning/exploring/implementing/testing/deploying/other）
  - [ ] SubTask 2.2: `runtime/sensing/gateway/realtime_workbench.py` 的 `_phases_from_todo_preview` 从 todo 文本映射 phase_kind
  - [ ] SubTask 2.3: 单测覆盖：5 种 phase_kind 映射 + other fallback

- [ ] Task 3: 强制 commentary fallback
  - [ ] SubTask 3.1: `runtime/core/cerebrum/react_loop.py` 的 commentary 生成逻辑：模型未守 `Update:` 协议时强制启用 runtime fallback
  - [ ] SubTask 3.2: 单测覆盖：模型不守协议时 commentary item 仍生成，协议字段齐全

- [ ] Task 4: text_delta 路径 strip 协议标签
  - [ ] SubTask 4.1: `runtime/sensing/gateway/realtime_event_bridge.py` 的 text_delta emit 前 strip `<ReasoningBlock>` 等泄漏标签
  - [ ] SubTask 4.2: 单测覆盖：泄漏标签被 strip，正常文本不受影响

## 前端体验收尾（9 项）

- [ ] Task 5: Inputs 区渲染
  - [ ] SubTask 5.1: `frontend/src/components/workspace/agent-workbench-pages.tsx` 的 `AgentSummaryPage` 消费 `userInput` prop，渲染文本 + 上传文件 + 附件列表
  - [ ] SubTask 5.2: i18n 4 语言词条补充
  - [ ] SubTask 5.3: 单测覆盖：有附件/无附件两种场景

- [ ] Task 6: 验收事件不再静默过滤
  - [ ] SubTask 6.1: `frontend/src/core/threads/process-trace-events.ts` 的 filter 逻辑改为：成功的 auto_verification 折叠展示而非过滤
  - [ ] SubTask 6.2: 单测覆盖：done 事件被折叠而非过滤，非 done 事件保持展开

- [ ] Task 7: 当前帧聚焦扩展到历史
  - [ ] SubTask 7.1: `frontend/src/components/workspace/messages/message-group.tsx:762` 条件改为"流式结束后默认折叠，用户展开才展开"
  - [ ] SubTask 7.2: 单测覆盖：结束后历史 phase 折叠，用户展开后不收回

- [ ] Task 8: businessAgentPhaseKey UI 消费
  - [ ] SubTask 8.1: `frontend/src/components/workspace/agent-phases.ts` 的 phase 标题渲染逻辑：优先用后端 `phase_kind`，fallback 到 `businessAgentPhaseKey`
  - [ ] SubTask 8.2: 单测覆盖：后端给了 phase_kind 时用后端，没给时用本地映射

- [ ] Task 9: aggregatedToolGroup 加 FlipDisplay
  - [ ] SubTask 9.1: `frontend/src/components/workspace/messages/message-group.tsx` 的聚合行渲染：count 变化走 FlipDisplay 翻转动画
  - [ ] SubTask 9.2: 单测覆盖：count 变化时数字翻转，DOM 不重建

- [ ] Task 10: Workbench 内子 agent 实体化
  - [ ] SubTask 10.1: `frontend/src/components/workspace/agent-workbench-pages.tsx` 的子 agent 区复用对话区 `SubtaskHoverPreview` 组件
  - [ ] SubTask 10.2: 单测覆盖：头像 + popover + 跳转按钮渲染

- [ ] Task 11: 反向联动视觉聚焦强化
  - [ ] SubTask 11.1: `frontend/src/core/threads/timeline-linkage.ts` 的高亮样式加边框/缩放
  - [ ] SubTask 11.2: 命中聚合组时可展开子项
  - [ ] SubTask 11.3: 单测覆盖：高亮样式 + 聚合组展开

- [ ] Task 12: timelineExpanded 死代码处理
  - [ ] SubTask 12.1: 确认 `leadInTimelineItems/replayTimelineItems/currentTimelineItem` 三分支的去留（删除或接通）
  - [ ] SubTask 12.2: 执行决定：删除死代码或接通逻辑

- [ ] Task 13: 移动端 drawer 过渡
  - [ ] SubTask 13.1: `frontend/src/components/workspace/chat-page-layout.tsx` 的移动端 drawer 加 handle/延迟展开
  - [ ] SubTask 13.2: 单测覆盖：首次打开非全屏，可手动展开

## 联动与验证（2 项）

- [ ] Task 14: 后端 phase_kind 与前端 businessAgentPhaseKey 联动
  - [ ] SubTask 14.1: 后端给了 phase_kind 时前端优先用后端，businessAgentPhaseKey 降级为 fallback
  - [ ] SubTask 14.2: 单测覆盖：联动优先级正确

- [ ] Task 15: 思考耗时持久化展示
  - [ ] SubTask 15.1: 流式中 live 显示（前端计时），结束后从 `ReasoningItem.duration_ms` 读取回放显示
  - [ ] SubTask 15.2: 单测覆盖：live + 回放两种路径

# Task Dependencies

- Task 5/6/7/8/9/10/11/12/13（前端 9 项）**无依赖**，可并行
- Task 14 依赖 Task 2（后端 phase_kind）和 Task 8（前端 businessAgentPhaseKey 启用）
- Task 15 依赖 Task 1（后端 duration_ms）
- Task 4（text_delta strip）不阻塞前端，但完成后前端 INTERNAL_PROCESS_BLOCK_RE 可降级为 fallback

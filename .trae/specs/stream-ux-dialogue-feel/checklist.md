# Spec: stream-ux-dialogue-feel — Checklist

> 最后核查：2026-07-28（代码级 grep + 文件读取验证，对照 action-display.ts / message-group.tsx / activity-aggregator.ts / agent-workbench-pages.tsx / timeline-linkage.ts / 4 语言 i18n）

## Requirement: 工具调用渲染为人话动作行
- [x] 所有工具调用不再显示原始工具名（edit_file/run_command 等），统一显示为人话动词
  - 证据：`action-display.ts:272-526` `getActionDisplay()` 返回结构化 `verb/object/iconName`；`message-group.tsx:744-756` 消费 `getActionDisplay()` + `localizedActionVerb(display, t)` 替换原始工具名；`message-group.tsx:98-100` `PROCESS_TEXT_RAW_TOOL_RE` 再脱敏泄漏到正文的工具名
- [x] 文件操作类：编辑/创建/修改/删除 + 文件名
  - 证据：`action-display.ts:279-301`（WRITE→"创建"、EDIT→"编辑"）；`action-display.ts:450-477`（delete→"删除"、rename/move→"移动/重命名"）；`extractPath()` 提取文件名；i18n `createFile/editFile/deleteFile/moveFile` 4 语言齐全
- [x] 命令类：运行 + 命令摘要
  - 证据：`action-display.ts:345-355`（SHELL→`run_command`/verb="运行"）；`extractCommandSummary()` 提取首行并截断 35 字符，过滤含 `~/.ssh`/`token`/`secret` 等敏感串
- [x] 搜索类：搜索 + 查询词摘要
  - 证据：`action-display.ts:303-324`（glob/grep/find→`search_files`）；`action-display.ts:357-367`（web_search→`search_web`）；`extractQuery()` 从 query/pattern/keyword 键提取并截断 40 字符
- [x] 浏览器类：操作浏览器 + 动作
  - 证据：`action-display.ts:381-409` 按 click/type/screenshot/navigate/action 拆分动词；`extractUrl()` 提取 hostname+pathname
- [x] 每个动作行下方有弱显示事实摘要（复用升级后的 fact-summary）
  - 证据：`message-group.tsx:759-766` 调用 `formatFactSummary(narrative.fact ?? extractFactSummary(...), t)`；`message-group.tsx:1018-1022` `text-xs text-muted-foreground/60` 弱显示；`fact-summary.ts:359-471` 返回 11 种结构化 kind
- [x] 未映射工具不报错，fallback 到拆词显示
  - 证据：`action-display.ts:510-525` 终兜底 `camelToWords(toolName)` 拆词，返回 `labelKey: "raw"`，绝不抛错；`localizedActionVerb` 对 `raw` 直接返回 `display.verb`
- [ ] 每个动作行有"展开详情"按钮，点击跳转右侧 Workbench
  - 状态：**部分实装**。整行 button 已绑 `emitOpenAgentWorkbench(...)`（`message-group.tsx:847-871`），任意动作行点击都跳 Workbench。但独立 `PanelRightOpenIcon` 按钮只在 `isLastOverall && showTimelineToggle` 时渲染（`message-group.tsx:1004-1016`），并非每行都有可见按钮

## Requirement: 同类动作聚合
- [x] 同一 phase 内连续同类型工具聚合成一行摘要
  - 证据：`activity-aggregator.ts:114-169` `aggregateSimilarToolCalls()` 按 `toolCallEvidenceKind` + `samePhase()` 分组；非 toolCall 项打断聚合；count≥2 才打包成 `aggregatedToolGroup`
- [x] 文件写聚合："编辑了 N 个文件"
  - 证据：`message-group.tsx:1746-1747` `case "file_write": return labels.aggregateFileWrite(count)`；`zh-CN.ts:619` `aggregateFileWrite: "编辑了 ${count} 个文件"`；4 语言齐全
- [x] 文件读聚合："查看了 N 个文件"
  - 证据：`message-group.tsx:1748-1749` `case "file_read": return labels.aggregateFileRead(count)`；`zh-CN.ts:620` `aggregateFileRead: "查看了 ${count} 个文件"`；4 语言齐全
- [x] 命令聚合："运行了 N 条命令"
  - 证据：`message-group.tsx:1750-1751` `case "command": return labels.aggregateCommand(count)`；`zh-CN.ts:621` `aggregateCommand: "运行了 ${count} 条命令"`；4 语言齐全
- [x] 搜索聚合："搜索了 N 次"
  - 证据：`message-group.tsx:1752-1753` `case "web_search": return labels.aggregateWebSearch(count)`；`zh-CN.ts:622` `aggregateWebSearch: "搜索了 ${count} 次"`；4 语言齐全
- [x] 混合类型不聚合
  - 证据：`activity-aggregator.ts:154-158` 仅当 `currentKind === kind && samePhase(...)` 才追加到当前组；kind 变化触发 `flush()` 后开新组；单条不打包
- [x] 聚合行点击展开看详情
  - 证据：`message-group.tsx:974-1003` ChevronDown button 切换 `expandedAggregatedGroups[item.id]`；展开时 `renderCompactTimelineItems(item.items, ..., { nested: true })` 渲染子项
- [x] 进行中计数实时更新，不闪烁
  - 证据：`message-group.tsx:926-931` 实时聚合行用 `<FlipDisplay uniqueKey={item.id}>` 包裹，flip 动画避免数字跳变；verb 由 `localizedAggregateVerb(kind, item.count, t)` 实时计算
- [x] 聚合逻辑不改变原始事件顺序（仅视觉聚合）
  - 证据：`activity-aggregator.ts:146-167` 顺序遍历 `items`，`flush()` 时按遇到顺序 push，不重排

## Requirement: 思考块显示耗时
- [x] 进行中显示 spinner + "思考中…"
  - 证据：`message-group.tsx:889-910` reasoning 行渲染双圆点，外圈 `agentRunStatusLightPulseClass(state)` 在 running 时 `animate-ping`；`zh-CN.ts:629` `thinking: "思考中"`
- [x] 完成后显示 "思考了 N 秒"
  - 证据：`message-group.tsx:946-955` 在 `hasStoredDuration && groupDurationMs > 0` 时显示 `t.messageGrouping.thinkingDuration(formatDuration(groupDurationMs))`；`step.durationMs` 从 `additional_kwargs.reasoning_duration_ms` 读取
- [ ] 深度思考 vs 普通思考图标区分
  - 状态：**未实装**。grep `deep.?think|reasoning_depth|isDeepThinking|SparklesIcon` 在 `messages/` 目录下无命中。思考行仅按 running/waiting/done 染色，无 deep/normal 维度
- [ ] 默认折叠，展开看完整内容
  - 状态：**部分实装**。思考行显示 `compactReasoningSummary(text, 120)` 截断到 120 字（默认折叠摘要 ✓）。但行内**无 Collapsible 展开按钮**，点击行触发 `emitOpenAgentWorkbench({ view: "summary" })` 跳到右侧 Workbench 查看完整内容，展开发生在 Workbench 而非对话区行内
- [ ] 计时器准确（从第一个 reasoning token 到最后一个）
  - 状态：**部分实装**。完成态用 backend 的 `reasoning_duration_ms`（精度由后端保证 ✓）；进行中态用前端 `Date.now()` 计时，起点是 React 首次检测到 `isCurrentlyThinking=true` 的渲染帧，并非真正的第一个 reasoning token 到达时刻，存在数十到数百毫秒误差

## Requirement: 当前帧聚焦
- [x] 流式进行中，当前 phase 展开，已完成 phase 收敛为摘要行
  - 证据：`message-group.tsx:510-557` 计算 `activePhaseId`（最后一个 item 的 phaseId），其余 phaseId 的 item 收集到 `historicalPhaseItems`；首个历史 item 渲染为 `<button data-testid="collapsed-history-phase">` 显示"完成了 N 步"
- [ ] 历史轮次默认收敛为 "✓ 完成了 N 件事"
  - 状态：**部分实装**。`message-group.tsx:535` `t.message.completedSteps(phaseItems.length)` 输出"完成了 N 步/N steps"，视觉有 emerald 圆点作"✓"语义。但文案是"N 步"而非"完成了 N 件事"，且按 phaseId 折叠而非按"轮次"折叠
- [x] 用户手动展开的块不被自动收回
  - 证据：`message-group.tsx:542-548` `setExpandedHistoryPhases` 只把 phase 设为 true，从不自动 reset 回 false；`expandedHistoryPhases` 状态在组件生命周期内持续
- [x] 流式结束后所有 phase 自动展开
  - 证据：`message-group.tsx:524-538` `historicalPhaseItems` 构建逻辑加 `isLiveTimeline` 守卫——流式进行中默认折叠历史 phase（只展开活跃 phase），流式结束后（isLiveTimeline=false）跳过折叠逻辑，所有 phase 自动展开；引入 `collapsedHistoryPhases` 状态支持用户手动折叠（点击 `collapsed-history-phase` 按钮重新展开）；53 测试全绿
- [ ] 收敛摘要行包含 phase 名称 + 关键统计（如"查看了 12 个文件"）
  - 状态：**未实装**。`message-group.tsx:535` 仅 `t.message.completedSteps(phaseItems.length)`，输出"完成了 3 步"，**没有 phase 名称**，也**没有"查看了 12 个文件"之类的关键统计**

## Requirement: 动作行与右侧 Workbench 联动
- [x] 文件编辑行 → Workbench Files/diff tab + 定位对应文件
  - 证据：`action-display.ts:286, 298` 文件写/编辑 `workbenchTab: "diff"`；`message-group.tsx:756-757` `actionWorkbenchTab = narrative.evidenceRefs[0]?.tab ?? display.workbenchTab`；`message-group.tsx:850-870` `emitOpenAgentWorkbench({ tab: actionWorkbenchTab, ... })`
- [x] 命令行 → Workbench Terminal tab + 定位对应输出
  - 证据：`action-display.ts:352` SHELL `workbenchTab: "terminal"`；同上 emitOpenAgentWorkbench 路径
- [x] 搜索行 → Workbench 对应 tab + 定位搜索结果
  - 证据：`action-display.ts:321, 331, 341, 364, 376, 406` 按搜索类型分别映射到 `agent`/`browser`；`message-group.tsx:850-870` 统一 emit
- [x] 右侧事件点击 → 对话区滚动到对应动作行 + 2s 高亮
  - 证据：`agent-workbench-panel.tsx:1883` `activateTimelineItem(block.event.id || block.id, "sidebar")`；`timeline-linkage.ts:63-67` reducer 在 source=sidebar 时设 `highlightedTimelineItemId`；`message-list.tsx:782-810` `scrollIntoView({behavior:"smooth", block:"center"})` + `classList.add(TIMELINE_ITEM_HIGHLIGHT_CLASS)`；`TIMELINE_HIGHLIGHT_DURATION_MS = 2000` 2s 后自动清除
- [x] 高亮使用 CSS transition，一次性消退（复用 timeline-linkage 现有机制）
  - 证据：`globals.css:3319-3325` `[data-timeline-item-id]` 挂 `transition: ... var(--motion-duration-slow, 300ms) ease-out`；`globals.css:3327-3335` `.timeline-item-linkage-highlight` 一次性应用底色+outline+box-shadow+scale，无 keyframes 循环；`prefers-reduced-motion` 下保留底色去掉 scale
- [x] 联动不影响 Workbench 其他 tab 的正常使用
  - 证据：`agent-workbench-panel.tsx:584-593` 仅做 `scrollIntoView({block:"nearest"})`，不调用 `setActivityView`/`onSelectTab`，不改 tab；对话行点击 `emitOpenAgentWorkbench` 携带 `tab` 参数由用户既有点击意图驱动

## Requirement: Workbench 概要 tab 增强
- [x] Progress 区：当前 phase + X/Y 任务进度
  - 证据：`agent-workbench-pages.tsx:1064-1152` Progress section；显示 `${donePhaseCount}/${phases.length}` + phase 进度条 + 每个 phase 状态图标+名称；还支持 `progressOutline`（按 iteration 分组）回退
- [x] Subagents 区：子 agent 状态（复用现有 parallel-subtasks-grid）
  - 证据：`agent-workbench-pages.tsx:50` `import { SubtaskHoverPreview }`；`agent-workbench-pages.tsx:1311-1407` Subagents section；`SummaryAgentRow` 复用 `SubtaskHoverPreview`；显示 done/failed/running/pending 统计
- [x] Inputs 区：用户请求 + 上传文件
  - 证据：`agent-workbench-pages.tsx:1154-1233` Inputs section；渲染 `inputText`（用户请求）+ `inputUploadedFiles`（FileTextIcon + filename）+ `inputAttachments`（PaperclipIcon + filename）
- [x] Outputs 区：产物清单（artifacts）
  - 证据：`agent-workbench-pages.tsx:1235-1309` Outputs/Artifacts section；`artifactDiffEntries = diffEntries.filter(entry => entry.created)`；每个 entry 可点击 `onOpenArtifact`
- [x] Files Changed 区：变更文件列表
  - 证据：`agent-workbench-pages.tsx:834-837` `changedFileEntries = diffEntries.filter(entry => !entry.created)`；在 Artifacts section 内并列渲染"Changed Files"子列表（独立 header + SummaryDiffEntryList）
- [x] Sources 区：引用来源（如有）
  - 证据：`agent-workbench-pages.tsx:1409-1579` References/Sources section；`buildObservedReferenceTabs` 分 files/plans/web/memory/other 五个 tab；渲染来源列表含 favicon/thumbnail/title/subtitle/url
- [x] 不破坏现有终端/预览/diff/计划/产物 tab 功能
  - 证据：`AgentSummaryPage` 与 `AgentDiffPage`/`WorkbenchEmptyPage` 并列存在；`onSelectTab` prop 允许外部 tab 切换；`openDiffEntry` 根据类型调用 `onOpenArtifact` 或 `onSelectTab("diff")`，不替换其它 tab 渲染逻辑

## Design/Style
- [ ] 动作行图标统一 lucide，尺寸 14px，颜色 text-muted-foreground
  - 状态：**部分实装**。图标全部 lucide ✓；`message-group.tsx:912` `size-3.5` = 14px ✓；但颜色是父 button 的 `text-muted-foreground/60` 叠加 icon 自身 `opacity-70`，等效 ~42% muted-foreground，非裸 `text-muted-foreground`
- [ ] 动作动词用正常字重 text-foreground，对象用 text-muted-foreground
  - 状态：**部分实装**。`message-group.tsx:920-924` 动词 `text-foreground/80`（80% 而非 100%）；对象 `text-muted-foreground/70`（70% 而非 100%）+ `font-mono text-[11px]`。视觉分层存在但与 spec 字面值有偏差
- [x] 事实摘要 text-xs text-muted-foreground/60，无气泡无阴影
  - 证据：`message-group.tsx:1019` `text-xs leading-[18px] text-muted-foreground/60`，无 `bg-*`/`shadow-*`/`border-*` 类
- [ ] 聚合行用 text-sm text-muted-foreground，hover 时 text-foreground
  - 状态：**部分实装**。聚合行与普通行共用 className：`text-xs leading-[18px] text-muted-foreground/60 hover:text-muted-foreground`。是 `text-xs` 而非 `text-sm`；hover 是 `text-muted-foreground` 而非 `text-foreground`
- [ ] 展开/折叠动画用 Collapsible 组件，150ms
  - 状态：**部分实装**。项目内 `Collapsible`（`@radix-ui/react-collapsible`）存在并被其他组件使用。但 `message-group.tsx:1023-1034` 的聚合组展开是简单条件渲染 `{aggregatedExpanded && ...}`，**未用 Collapsible**；历史 phase 折叠也是 `<button>` 切换，无 Collapsible 动画。`--motion-duration-fast: 150ms` 变量存在但本场景未消费
- [x] 高亮动画复用现有 .timeline-item-linkage-highlight CSS
  - 证据：`timeline-linkage.ts:39` `TIMELINE_ITEM_HIGHLIGHT_CLASS = "timeline-item-linkage-highlight"`；`message-list.tsx:792, 808` add/remove class；`globals.css:3327-3335` 定义底色+outline+box-shadow+scale
- [x] 全量 i18n：4 语言（中/英/日/韩）
  - 证据：4 文件均含 `actionLabels`（22 个 labelKey + 8 个聚合函数）+ `thinkingDuration` + `factSummary*`（11 种）+ `completedSteps`
- [x] 深色/浅色/liquid glass 主题兼容
  - 证据：全部使用语义 token（`text-foreground`/`text-muted-foreground`/`bg-muted` 等），无硬编码颜色；`text-amber-700 dark:text-amber-300` 显式 dark 变体；liquid glass 主题变量被通用样式正常继承

## Non-regression
- [x] 简单对话（无工具调用）行为完全不变
  - 证据：`message-group.tsx:1544-1546` `selectCompactTimelineItems` 在 `executionCount=0` 时走 `visibleCommentary = commentary` 全量保留；短对话语义不变
- [x] 用户消息样式不变
  - 证据：`message-list-item.tsx` 仍按 `message.type === "human"` 走 `isHuman` 分支；`message-group.tsx` 只处理 AI 消息的过程时间线，未触碰 human 消息渲染路径
- [x] 最终回答 markdown 渲染不变
  - 证据：`message-group.tsx:1089-1094` `<MarkdownContent content={streamingAnswerText} .../>` 与既有渲染路径一致；`showFinalAnswerBoundary` 仅加细分割线，不改 markdown 本身
- [x] 审批卡片（ToolApprovalCard）交互不变
  - 证据：`tool-approval-card.tsx` 存在且被 `message-group.tsx:17` `import { isApprovalRequest }` 引用；仅用于判定 `stepIsWaiting` 状态，不改卡片本身渲染
- [x] 产物 summary 卡片（message-output-summary）位置和功能不变
  - 证据：`message-output-summary.tsx` 文件存在且测试存在；`message-group.tsx` 未 import 且未触碰其渲染逻辑，它在 message-list 层独立渲染
- [x] 紧凑模式（selectCompactTimelineItems）语义保真升级，不丢 intent/fact 锚点
  - 证据：`message-group.tsx:1471-1533` `representativeNarrativeAnchors` 实现"每 iteration 必留 ≥1 个 intent 锚点"+"最新 fact 锚点必留"+"剩余按均匀采样补足"；`MAX_SEMANTIC_PROGRESS_ANCHORS=6` 兜底放宽
- [x] message-group.tsx 不拆文件，在现有结构内改造
  - 证据：`message-group.tsx` 仍是单文件 2289 行，包含 `MessageGroup` 组件 + 辅助函数 + `convertToSteps` + `selectCompactTimelineItems` + 类型定义；仅纯函数模块拆出去（`action-display.ts`/`activity-aggregator.ts`/`fact-summary.ts` 等），主体渲染逻辑未拆

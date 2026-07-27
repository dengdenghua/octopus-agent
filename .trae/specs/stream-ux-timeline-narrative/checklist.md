# Checklist

## 时间线语义角色（Task 1）

- [x] `TimelineRole` 类型与 `roleInference` 纯函数存在，推断优先级为：结构化协议字段 > 消息类型与位置 > 正则 fallback（`inferred=true`）（timeline-role.ts：roleForStep/assignTimelineRoles）
- [x] `CoTStep` / `TimelineItem` 携带 `role` 与 `inferred` 字段，渲染层可消费（message-group.tsx L1886-1949 四变体 + convertToSteps 出口填充）
- [x] 协议字段齐全时：无任何 `inferred` 标记条目（roleForStep 中 inferred = !structured；单测已编写，执行见 Task 7）
- [x] 无协议字段（裸工具调用+普通 content）时：时间线仍按 意图→执行→确认→回答 顺序呈现，fallback 条目标记 `inferred=true`，无重复旁白（seenNarrativeRoles Map 保证同一 fingerprint 角色唯一；单测已编写，执行见 Task 7）
- [x] 单测覆盖上述两场景并通过（timeline-role.test.ts 13 用例全绿，2026-07-28 执行确认）

## 执行行事实摘要（Task 2）

- [x] `extractFactSummary` 纯函数：可解析 JSON → 一句话事实；非结构化/空结果 → null（不编造）（fact-summary.ts，返回 FactSummary{kind,value} 由渲染层 i18n 拼句）
- [x] 执行行下方事实摘要符合弱显示：小字、`text-muted-foreground`、无气泡/背景/阴影（message-group.tsx L787-793：`text-xs text-muted-foreground/60`，仅单工具行附加）
- [x] 可解析/不可解析/空结果三分支单测通过（fact-summary.test.ts 24 用例全绿，2026-07-28 执行确认）
- [x] i18n 四语言（zh-CN/en-US/ja-JP/ko-KR）条目齐全（factSummaryPath/Count/Status/Title/Text × 4 语言 + types.ts，已逐文件核对）

## 对话区 ↔ 侧边栏双向联动（Task 3）

- [x] store 中存在 `activeTimelineItemId` 与 `activateTimelineItem(id, source)`，两侧共用同一时间线 item id（单一数据源）（timeline-linkage.ts 模块级 store，只存 id）
- [x] 点击对话区时间线项 → 侧边栏展开对应详情并 scrollIntoView（message-group.tsx onClick + agent-workbench-panel.tsx L561-572 lane 限定定位 + 既有 emitOpenAgentWorkbench 展开流）
- [x] 点击侧边栏条目 → 对话区滚动定位对应项并短暂高亮（≤2s，CSS transition，无动画库、无装饰效果）（message-list.tsx L763-775；globals.css L3324-3328 color-mix var(--primary)；TIMELINE_HIGHLIGHT_DURATION_MS=2000 + nonce 防竞态）
- [x] 联动 reducer/高亮生命周期有测试覆盖（timeline-linkage.test.ts 19 用例全绿，2026-07-28 执行确认）

## 进展面板叙事大纲（Task 4）

- [x] 进展面板按 iteration 分组展示：每轮意图摘要一行 + 执行计数 + 事实列表
- [x] 分组可折叠（shadcn Collapsible），默认仅展开最近一轮
- [x] ≥3 轮场景分组与默认折叠态单测通过；i18n 四语言（progress-outline.test.ts 9 用例全绿 + agent-workbench-panel.test.tsx 4 用例；i18n roundTitle/roundActionCount × 4 语言已核对；2026-07-28 执行确认）
- [x] 进展/上下文面板不默认自动折叠（既有硬约束不破环）

## 紧凑模式叙事保真（Task 5）

- [x] `selectCompactTimelineItems` 语义感知：每个 iteration 必留 ≥1 个 intent 条目、最新 fact 条目必留
- [x] 长任务压缩后单测通过，时间线仍可读「意图→执行→确认」节奏（message-group.test.tsx selectCompactTimelineItems 语义保真采样 3 用例全绿，2026-07-28 执行确认）

## 最终回答视觉分层（Task 6）

- [x] 流式结束后最终回答与过程段落有细分界（分隔线/留白，无装饰元素）
- [x] 亮/暗主题与 liquid glass 主题下走查无违和（静态走查：liquid 主题不覆盖 `--border`，`border-border/50` 四模式对比度成立）

## 全局约束与回归（Task 7）

- [x] `tsc --noEmit` 通过（我们改动文件 0 错误；browser-home.tsx 存在 1 个与本 spec 无关的预存在 i18n key 缺失）
- [x] eslint 通过（我们改动文件 0 error；globals.css 被 eslint 忽略属正常配置）
- [x] 受影响单测（messages 分组、sidebar、process-trace）全绿 + 新增测试全绿（共 60 新用例；受影响域 message-group/agent-workbench-panel/i18n 等全绿）
- [x] 全量 vitest 回归：1505 用例 / 1501 pass；4 fail 全部落在本 spec 未触碰的文件中（agent-progress-pill × 2、settings-dialog × 1、message-output-summary × 1），为工作区其他预存在失败，与本次改动无关
- [ ] Playwright 流式 e2e：基建存在（frontend/e2e/，需起后端栈），本轮跳过待环境就绪后补跑
- [x] 全部 UI 改动使用 shadcn 组件与语义 token（无 text-slate-*/bg-slate-* 硬编码色值）（已静态核对：globals.css 用 color-mix var(--primary)；组件全部 text-muted-foreground 等语义类）
- [x] 弱显示设计原则未破坏（默认折叠、透明背景、小字；hover 才有反馈）（事实行 text-xs muted；高亮一次性 2s 消退；面板默认展开约束保持）
- [x] `INTERNAL_PROCESS_BLOCK_RE` 已从主路径降级为 fallback（未删除）（保留于 L99 原文本剥离用途；角色推断主路径为结构化字段，不经过该正则）
- [x] 未改动后端事件协议、未做 message-group.tsx 组件拆分（非目标项未越界）

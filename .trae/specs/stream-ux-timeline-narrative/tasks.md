# Tasks

- [x] Task 1: 时间线语义角色层（P0）— 在 timeline 构建层引入显式语义角色
  - [x] SubTask 1.1: 在 `message-grouping.ts`（或同层新模块）定义 `TimelineRole = 'intent' | 'execution' | 'fact' | 'answer'` 与 `roleInference` 纯函数：结构化协议字段（`public_progress` / `phase_id` / `progress_sequence` / `extractPublicReasoningSummary`）优先，其次消息类型与位置（content 首段→intent、尾段→answer），正则 fallback 标记 `inferred=true`
  - [x] SubTask 1.2: `convertToSteps` 输出的 `CoTStep` 与 `groupConsecutiveReasoningSteps` 的 `TimelineItem` 携带 `role` 与 `inferred` 字段；保证无协议字段时仍按 意图→执行→确认→回答 顺序产出且不重复旁白
  - [x] SubTask 1.3: 单测：协议齐全场景无 `inferred`；裸工具调用+content 场景 fallback 顺序正确且无重复
- [x] Task 2: 执行行事实摘要（P0）— toolCall 完成后一句话「已确认事实」
  - [x] SubTask 2.1: 新增纯函数 `extractFactSummary(toolName, result): string | null`：仅处理可解析 JSON 结果（提取 path/count/status/title 等字段拼一句话），不可解析返回 null（不编造）
  - [x] SubTask 2.2: `process-trace.tsx`（或 toolCall 行渲染处）在执行行下方渲染事实摘要行：小字、`text-muted-foreground`、无气泡无背景，遵循弱显示 token
  - [x] SubTask 2.3: 单测覆盖：可解析/不可解析/空结果三分支；i18n 四语言（zh-CN/en-US/ja-JP/ko-KR）条目
- [x] Task 3: 对话区 ↔ 侧边栏双向联动（P1）
  - [x] SubTask 3.1: 在共享 store（threads/sidebar 域）建立 `activeTimelineItemId` 状态与 `activateTimelineItem(id, source: 'chat' | 'sidebar')` action，两侧共用同一时间线 item id
  - [x] SubTask 3.2: 对话区时间线项点击 → 侧边栏定位并展开对应详情条目（scrollIntoView）
  - [x] SubTask 3.3: 侧边栏条目点击 → 对话区滚动定位对应时间线项 + ≤2s 短暂高亮（CSS transition，无动画库），随后恢复
  - [x] SubTask 3.4: 单测/组件测试覆盖联动 reducer 与高亮生命周期
- [x] Task 4: 「进展」面板叙事大纲（P1）— 按 iteration 分组替代 step 平铺
  - [x] SubTask 4.1: 新增 selector：由时间线数据派生「轮次大纲」（每轮：意图摘要一行、执行计数、事实列表各一行）
  - [x] SubTask 4.2: 进展面板 UI 改为分组可折叠列表（shadcn Collapsible），默认仅展开最近一轮；遵循弱显示与圆角 token
  - [x] SubTask 4.3: 单测：≥3 轮场景分组正确、默认折叠态正确；i18n 四语言
- [x] Task 5: 紧凑模式叙事保真（P2）— 语义感知采样替代纯均匀采样
  - [x] SubTask 5.1: 修改 `selectCompactTimelineItems`：每个 iteration 必留 ≥1 个 intent 条目 + 最新 fact 条目，剩余名额再均匀采样 commentary
  - [x] SubTask 5.2: 单测：长任务压缩后每轮意图可读、最新事实保留
- [x] Task 6: 最终回答视觉分层（P2）
  - [x] SubTask 6.1: 流式结束后最终回答区与过程段落加分界（细分隔线/留白，无装饰元素），回答正文不受弱显示影响
  - [x] SubTask 6.2: 视觉走查（亮/暗主题 + liquid glass 主题）— 静态走查完成：liquid 主题不覆盖 `--border`，`border-border/50` 四模式对比度均成立，无需微调 class
- [x] Task 7: 验证与回归
  - [x] SubTask 7.1: `tsc --noEmit`：我们改动的所有文件 0 类型错误（预存在 1 个无关错误在 browser-home.tsx closeFolderAria i18n key 缺失）。eslint 0 error
  - [x] SubTask 7.2: 新增测试 4 文件 60 用例全绿（timeline-role 13、fact-summary 19、timeline-linkage 19、progress-outline 9）；受影响域回归 message-group 49/agent-workbench-panel 52/message-list/message-grouping/process-trace/i18n 全绿
  - [x] SubTask 7.2 全量回归：194 文件 / 1505 用例，1501 pass，4 fail 全部在本 spec 未修改的文件中（agent-progress-pill × 2、settings-dialog × 1、message-output-summary × 1，均为工作区其他预存在改动引入，与本 spec 无关）
  - [ ] SubTask 7.3: Playwright e2e 基建存在（frontend/e2e/ + playwright.config.ts），但依赖后端 GATEWAY_PORT/FRONTEND_PORT 起完整栈；本轮未起后端，跳过，待 e2e 环境就绪后补跑。建议 spec：新建 `frontend/e2e/stream-timeline-narrative.spec.ts`，注入意图→工具→事实→回答 SSE 序列，断言「已确认：…」事实行存在、进展面板第 N 轮可展开、双侧点击 scrollIntoView 触发

# Task Dependencies

- [Task 2] depends on [Task 1]（事实摘要挂在 execution 行，依赖 role 标记）
- [Task 3] depends on [Task 1]（联动 id 基于时间线 item id 稳定化）
- [Task 4] depends on [Task 1]（大纲按 role/iteration 派生）
- [Task 5] depends on [Task 1]（语义锚点依赖 role）
- [Task 6] depends on [Task 1]（answer 角色分界）
- [Task 7] depends on [Task 2, Task 3, Task 4, Task 5, Task 6]
- [Task 2, Task 3] 之间无依赖，可并行；[Task 4, Task 5, Task 6] 可并行

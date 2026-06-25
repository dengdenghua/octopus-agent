# Kimi Replay 流式 UX/UI 走查

素材来源：`/Users/dangbei/Public/octopus/octopus-agent/kimi_replay_capture/`

- 录制方式：网页回放，60 秒，每秒 2 帧，共 120 帧。
- 关键总览：`contact_sheet_5s.jpg`
- 重点帧：15.0s agent 弹层、37.0s 预览接管、40.0s 修复执行、43.0s 思考空状态、51.5s 规格与预览并行、最终完成态。
- 补充截图：`notes/subagent-computer-activity-view.png`、`notes/subagent-computer-terminal-view.png`、`notes/subagent-role-card.png`、`notes/subagent-role-description.png`

## 一句话结论

Kimi 这套回放最值得学的不是某个视觉样式，而是它把 agent 执行拆成了两条可同时被理解的流：

1. 左侧是“叙事流”：告诉用户目标、计划、判断、修复、验收。
2. 右侧是“证据流”：展示终端、文件、代码、预览、阶段、结果。

用户不会只看到“AI 正在想”，而是持续知道：谁在做、现在第几步、依据是什么、结果在哪里、能否立刻接管。

## 时间节奏

### 0-12s：建立任务可信度

左侧先给出任务拆解、需求理解、计划与技能读取，右侧进入 Kimi's Computer。右侧标题区一直稳定显示“当前进度 7/7 / Phase ...”，即便内容区是空白或终端，也不丢失任务大局。

可学点：

- 任务开始后不要只显示 spinner，要立刻给出 phase 标题。
- phase 文案要是业务可读的，例如 `Phase 7: Merge, build & deploy`，不要只写 `running tools`。
- 右侧工作区标题要像“机器桌面”，不是普通日志抽屉。

### 12-30s：并发 agent 变成可点实体

左侧出现 Agent 集群卡片，Reid / Galli 等子 agent 以列表形式出现，每个卡片有头像、名字、任务摘要和微型进度。15s 点击子 agent 后，浮出详情卡：头像、角色、负责页面、当前任务、具体命令。

可学点：

- 并发任务不要只在日志里滚，要有“人/角色/工单”的实体感。
- 子 agent 卡片默认紧凑，点击后展开为 popover，不打断主流。
- 卡片上要显示“当前正在做什么”，而不是只显示完成百分比。

### 22-35s：结果先出现，随后补足验收

左侧开始出现访问地址、页面表格、组件清单、生成资源、技术栈、下一步预览。右侧仍然停留在机器面板或等待态。这里的关键是：完成不是一句话，而是一组可审计 artifact。

可学点：

- 完成态应包含 URL、变更表、验证状态、文件入口、预览入口。
- 表格是非常好的完成态容器，能让用户扫视“哪些页面/模块完成了”。
- “下一步可预览”比“任务完成”更能引导用户继续检查。

### 37-43s：预览接管，用户进入验收

37s 右侧切到网页预览，左侧继续写问题判断。40s 左侧指出视频文字错误，并同步触发修复任务；右侧预览继续可见。43s 右侧出现浅色空状态，左侧给出重新生成视频的明确 prompt。

可学点：

- 预览出现后，不要把它再藏回日志后面；预览应成为右侧主舞台。
- 修复时左侧解释原因，右侧保留现场，这能让用户理解“为什么又跑了一轮”。
- 预览加载或等待时，用安静空状态，不要大量占位骨架扰乱视觉。

### 51.5-59.5s：规格说明与结果同屏

51.5s 左侧给出具体实现规格：竖排、字号规则、按钮要求、禁止事项，右侧展示最终视觉。最后完成态显示“两项修复全部验证通过”、线上链接、修复表、预览 v27、全部文件、任务已结束。

可学点：

- agent 的最终解释要具体到“我改了什么规则”，不是只说“已修复”。
- 验收表格要把“修复项”和“验证方式”并列。
- 最后的主 CTA 应从“看结果”变成“看回放 / 做同款”等延续动作。

## 组件模式拆解

### 1. 双轨布局

Kimi 左侧宽度约为主阅读列，右侧为固定机器面板。右侧容器稳定，内容在 terminal / file / preview / code 之间切换。

对 Octopus 的映射：

- `ChatPageLayout` 已支持 `secondaryPanel` 和 `bottomBar`，适合承接这个结构。
- `agent-workbench-panel` 已有阶段、终端、预览、文件、diff 的基础能力，可以作为右侧“Octopus Computer”。
- 需要减少右侧作为“抽屉”的感觉，让它在执行态成为一等主面板。

建议：

- 新增或强化 `AgentRunWorkbench` 级别壳层，固定标题区、phase 区、内容 tabs。
- 左侧 message list 保持叙事，右侧不要跟随左侧滚动。
- 桌面端优先双栏，移动端切为底部/顶部 tabs：对话、机器、预览、文件。

### 2. Phase 进度模型

Kimi 同时用了两层进度：

- 右侧大任务阶段：`当前进度 7/7 / Phase 7: Merge, build & deploy`
- 底部执行卡阶段：`当前进度 1/4 / Phase 2: Hall VI 银信局 ...`

这让用户知道“总任务在哪里”和“当前修复在哪里”。

对 Octopus 的映射：

- `agent-phases.ts`、`agent-progress-pill.tsx` 已有基础。
- `chat-streaming-footer.tsx` 现在能显示 running/done/error 和事件数，但缺少强业务 phase 标题的前后贯通。

建议：

- 统一 phase schema：`id/title/description/status/progress/currentBlock/artifacts`。
- 顶部/右侧/底部都读取同一份 phase snapshot，避免三个地方各说各话。
- phase 标题使用业务动作：读取需求、搭建脚手架、并行生成页面、合并构建、部署验收。

### 3. 运行指示灯

Kimi 在 `Kimi's Computer` 标题下方用了一个很小的绿色指示灯，配合“执行任务中...”表达机器正在正常工作。这个点很克制，但信息量偏少：它只有“活着/在跑”的含义。

Octopus 可以保留这个形式，但升级成红黄绿状态语义：

- 绿色：正常运行，工具调用/agent 步骤持续推进。
- 黄色：等待用户确认、等待外部资源、排队、重试、速率限制、部分阻塞。
- 红色：工具失败、构建失败、权限拒绝、不可恢复错误、agent 异常退出。

视觉建议：

- 指示灯放在父级电脑标题、子 agent 电脑标题、agent 状态卡、紧凑 agent 卡片四个位置。
- 绿色可以轻微 pulse，表示进程心跳；黄色用慢闪或静态 amber，表示需要注意但不是崩溃；红色不闪或短促闪，避免制造持续焦虑。
- 不只靠颜色表达状态，旁边必须有短文案：`执行任务中...`、`等待确认`、`重试中`、`执行失败`。
- 点阵进度可以作为“活跃度/子步骤推进”，红黄绿圆点作为“健康状态”；两者不要混成一个含义。

对 Octopus 的映射：

- 建议增加统一组件 `RunStatusLamp`，输入为 `status = running | waiting | blocked | error | done | idle`。
- `running/done` 可映射绿，`waiting/blocked` 映射黄，`error` 映射红，`idle` 映射灰。
- `waiting_approval` 不应显示成普通 running，应显示黄色，并给出需要用户动作的文案。

### 4. 父电脑与子电脑层级

补充截图里有一个关键细节：Kimi 不是只有一个 `Kimi's Computer`。它把执行现场分成了父级总电脑和子 agent 独立电脑。

父级总电脑负责：

- 显示全局身份：`Kimi's Computer`。
- 显示全局进度：`当前进度 7/7`。
- 显示全局 phase：`Phase 7: Merge, build & deploy`。
- 承载全局预览、总任务证据、全局回放入口。

子 agent 电脑负责：

- 显示子 agent 的编号和身份，例如 `Agent 01`。
- 在顶部提供上下文切换，例如 `Agent 01 | Kimi's Computer`。
- 显示该 agent 自己的活动轨迹、终端输出、文件读取、待办完成状态。
- 底部有独立 agent 状态卡：头像、编号、状态，例如 `01 / 已完成`。

这个设计的本质是“总控台 + 分机房”。用户既能看总任务，也能钻进某个 agent 的执行现场。这样多 agent 不会被压扁成一条混合日志。

对 Octopus 的映射：

- `agent-workbench-panel` 可以作为父级 `Octopus Computer`。
- `parallel-agents-panel` 或 `messages/parallel-subtasks-grid` 的单个 agent 选中后，应切换右侧为 `SubAgentComputerView`。
- `live-tool-timeline` 需要支持 `scope = global | agent:{id}`，否则没法干净地区分总轨迹和子轨迹。

建议：

- 右侧工作台建立两层导航：`总电脑` 与 `Agent 01/02/...`。
- 父级 phase 保持全局，子 agent 内显示该 agent 自己的 step/checklist/progress。
- 点击左侧 agent 卡片时，不只打开 popover，也应把右侧 workbench 切到这个 agent 的电脑。
- 子电脑顶部提供返回总电脑的 breadcrumb 或 segmented control。
- 子电脑底部保留 agent 状态卡，告诉用户当前看的不是全局视角。

### 5. Agent 集群卡片

Kimi 的 agent 卡片很克制：头像、名字、任务摘要、微型进度条；点击后是 hover card/popover 展示当前命令和职责。

对 Octopus 的映射：

- `parallel-agents-panel.tsx` 已有 grid/list 和 agent card，但更像管理后台。
- `messages/parallel-subtasks-grid.tsx` 可以承接“嵌入聊天流的 agent 集群摘要”。

建议：

- 聊天流中只放紧凑 agent cluster 摘要：最多 2-4 个，更多折叠。
- 点击 agent 后有两种层级：轻点弹出 popover，进入/双击切换右侧子 agent 电脑。
- popover 展示角色、目标、当前步骤、最近工具、产物链接。
- 卡片状态分为 pending/running/blocked/done/error，颜色克制，主要靠图标和文字。

### 6. 子 Agent 身份卡

Kimi 还有一层很有意思的“角色实体化”：创建助手时，右侧出现类似工牌/吊牌的角色卡。卡片包含头像、名字、角色名、短人格文案和“角色说明”按钮；进入说明后，展示这个 agent 的系统角色/能力边界。

这不是装饰，它解决了多 agent 产品里的一个常见问题：用户不知道这些子 agent 为什么存在、擅长什么、接下来会按什么身份行动。

可学点：

- 子 agent 创建时，给一个短暂但清楚的身份展示，而不是只在日志里写“created agent”。
- 角色卡可以像工牌：头像、名字、角色、使命、角色说明。
- “角色说明”里展示可审计的职责边界，帮助用户判断委派是否合理。
- 角色卡不需要长期占屏，但应该能从 agent 卡片或详情里再次打开。

对 Octopus 的映射：

- 现有 `agents/agent-role-profile-dialog.tsx` 可以复用为角色说明详情。
- agent 创建事件可以渲染成 `AgentIdentityCard`，嵌入右侧 workbench 或消息流。
- 子 agent popover 应包含“角色说明”入口。

### 7. 机器证据面板

Kimi 的右侧不是“日志”，而是一个可以切换证据类型的工作台；并且这个工作台同时支持父级总电脑和子 agent 电脑：

- 读文件：文件名 + 内容 + copy。
- 终端：命令和输出。
- 预览：站点真实视觉。
- 代码：与预览并列的替代视图。
- 活动轨迹：某个子 agent 的 step/checklist/tool timeline。

对 Octopus 的映射：

- `terminal-panel.tsx`、`browser-preview-panel.tsx`、`live-preview-panel.tsx`、`diff-viewer.tsx` 都已经存在。
- 关键不是缺组件，而是需要统一到一个稳定容器里。

建议：

- 右侧顶部固定：agent 名称、运行状态、phase、展开/关闭、刷新、复制、打开。
- 中部使用 segmented tabs：预览、代码、终端、文件、变更。
- 底部或空状态显示“返回最新”/“正在等待下一帧”等轻提示。
- 子 agent 视图额外显示：`活动轨迹`、`电脑视图`、`返回总电脑`。

### 8. 流式文字行为

Kimi 左侧的流式不是纯 token 打字，而是“块级追加”：

- 思考块、工具块、文件块、agent 块、结果表格分别出现。
- 每块都有图标和右箭头，可展开。
- 长解释先用灰底文本块承载，再接具体执行卡。

对 Octopus 的映射：

- `streamdown-host.tsx` 适合正文。
- `live-tool-timeline.tsx` 和 `execution-timeline.tsx` 适合工具块。

建议：

- 不要把工具执行混在 markdown 正文里，要渲染成 typed blocks。
- 每个 block 的最小字段：`kind/icon/title/summary/status/detail/artifactRefs`。
- 流式时优先追加完整语义块，减少半句话抖动。

### 9. 持久底部控制

Kimi 底部控制条非常稳定：左侧显示“Kimi Agent 正在回放/回放完成”，右侧给“看结果/看回放”和“做同款”。执行中还会出现一张“执行任务中...”的小卡，并带展开图标。

对 Octopus 的映射：

- `chat-streaming-footer.tsx` 已经接近，但现在更像消息流内部 footer。
- `ChatPageLayout` 已有 `bottomBar`，可做真正持久的 run footer。

建议：

- 把执行状态从 message list 内移到持久底栏：`任务进行中 / 当前阶段 / 查看机器 / 停止 / 复制结果`。
- 完成后 CTA 切换：`查看结果`、`复盘过程`、`复用此流程`。
- 底栏不要太高，默认 48-64px，展开后才显示 timeline。

### 10. 完成态与验收

Kimi 最终完成态由五件事组成：

- 明确的成功结论。
- 线上 URL。
- 修复/页面/资源表格。
- 预览 vN。
- 全部文件入口。

对 Octopus 的映射：

- `message-output-summary.tsx`、`diff-summary-card.tsx`、`live-run-feedback-panel.tsx` 可以承接。

建议：

- 建立标准 `CompletionReceipt` UI：结果、证据、变更、验证、后续操作。
- 让每个完成态可复制、可下载、可打开预览、可回放。
- 失败态也按同样结构展示：失败原因、已完成部分、可恢复入口、建议下一步。

## 值得直接照搬的点

1. 双轨布局：左叙事，右证据。
2. 右侧机器面板固定，不被聊天滚动破坏。
3. phase 进度始终可见，且文案业务化。
4. 小型运行指示灯常驻标题区，告诉用户进程是否健康。
5. 父级电脑和子 agent 电脑分层，而不是一个混合日志。
6. agent 子任务有实体卡片，而不是日志行。
7. agent 卡片点击看详情，进入后能看独立子电脑。
8. 子 agent 有身份卡和角色说明，用户知道它为什么存在。
9. 预览一旦出现就成为主舞台。
10. 完成态用表格和 artifact，而不是长段总结。
11. 底部 CTA 持久存在，执行中和完成后语义切换。
12. 回放不是录像，而是可点击的事件时间线。
13. 修复过程把“问题判断、修复动作、验证结果”放在同一条叙事里。

## 不建议照搬的点

1. Kimi 左侧在长任务中信息密度偏高，容易造成扫读压力；Octopus 可以用更强分组和折叠。
2. 右侧预览加载空白时缺少明确 skeleton 或状态文案；Octopus 可以加轻量状态。
3. 代码/预览切换入口较小，专业用户可能需要更明显的 diff/terminal 快捷入口。
4. agent popover 信息很实用，但可操作性弱；Octopus 可以补“查看日志 / 打开产物 / 停止此 agent”。
5. 最终结果区域右侧有时空白，完成态可以自动切到最终预览或 receipt 面板。

## Octopus 优先级建议

### P0：把执行态骨架立住

- `ChatPageLayout.bottomBar` 承载持久执行 footer。
- `secondaryPanel` 固定为 Agent Workbench，而不是临时抽屉。
- phase snapshot 贯通 header、workbench、footer。
- workbench 需要支持父级总电脑和子 agent 电脑两个 scope。

### P1：让 agent 集群可理解

- 在消息流中加入紧凑 `AgentClusterCard`。
- 每个子 agent 支持 hover/click detail。
- 支持按 agent 过滤右侧 timeline。
- 点击子 agent 后，右侧切换到该 agent 的独立电脑。

### P1：子 Agent 身份与角色说明

- 创建子 agent 时展示 `AgentIdentityCard`。
- 角色卡包含头像、名字、角色、使命短句、角色说明入口。
- 角色说明可复用现有 agent profile dialog，并保留回到活动轨迹的入口。

### P1：完成态 receipt

- 标准完成卡：结果 URL、变更表、验证表、文件入口、复用按钮。
- 支持“查看回放”和“做同款/复用流程”。

### P2：回放体验

- 将 live tool events 存成 replay frames。
- 回放时底栏显示进度、结果入口、复用入口。
- 点击左侧任一 tool/agent block，右侧跳到对应机器证据。

### P2：预览优先

- 网站/前端任务中，右侧默认最终落到 Preview tab。
- 当 agent 发现视觉问题时，左侧显示问题判断，右侧保持问题现场。

## 可以转成组件任务的清单

- `PersistentRunFooter`
  - 状态：idle/running/replaying/completed/error。
  - CTA：查看机器、查看结果、复盘过程、复用流程、停止。

- `RunStatusLamp`
  - 绿色：正常运行/完成。
  - 黄色：等待确认、阻塞、重试、排队、外部资源等待。
  - 红色：失败、异常、权限拒绝、不可恢复错误。
  - 灰色：空闲或未启动。
  - 必须搭配短状态文案，不单靠颜色。

- `AgentComputerPanel`
  - Header：名称、状态、phase、进度、操作按钮。
  - Tabs：Preview / Code / Terminal / Files / Changes。
  - Body：绑定当前 selected event。
  - Scope：global computer / sub-agent computer。

- `SubAgentComputerView`
  - 顶部：`Agent 01 | Octopus Computer` 切换。
  - 主区：活动轨迹、终端、文件、产物。
  - 底部：agent 状态卡，显示头像、编号、运行/完成/失败。

- `AgentClusterInlineCard`
  - 紧凑展示并发 agent。
  - 点击 agent 弹出详情。
  - 支持跳转到对应 workbench event。

- `AgentIdentityCard`
  - 创建 agent 时展示角色工牌。
  - 支持“角色说明”详情。
  - 可从 agent popover 重新打开。

- `CompletionReceipt`
  - URL、变更表、验证表、artifact 列表、复用按钮。
  - 支持失败/部分完成版本。

- `ReplayTimelineController`
  - 播放/暂停/倍速/跳到最新。
  - 事件块与右侧证据面板双向联动。

## 视觉语言建议

- Kimi 的强点是“浅、克制、边界轻、信息块清楚”。Octopus 当前文档说短期 Dark only，但也可以学结构，不必学浅色。
- 在暗色主题里避免大面积发光和装饰，把状态色限制在 icon、pill、progress 上。
- 卡片半径 6-8px，边框低对比，强调信息层级而非装饰。
- 对 agent/phase/status 用一致图标语言：Bot、Terminal、File、Globe、Check、Alert、Loader。
- 文字尺寸建议：主叙事 14px，工具块 12-13px，辅助状态 11px，避免工具面板里标题过大。

## 最小落地路径

1. 先用现有 `ChatPageLayout.secondaryPanel` 固定右侧 `agent-workbench-panel`。
2. 将 `chat-streaming-footer` 提升为 `bottomBar` 的持久执行条。
3. 从 `liveToolEvents` 派生统一 `phaseSnapshot`。
4. 给 workbench 增加 `scope`：全局电脑或指定子 agent 电脑。
5. 在消息流里把 tool/agent 事件渲染成 typed blocks。
6. 完成时追加 `CompletionReceipt`，并让右侧自动切到 Preview 或 Changes。

这五步做完，Octopus 的 agent 流式体验会从“日志在跑”变成“一个可审计、可接管、可复盘的工作现场”。

# Kimi Replay 流式 UX/UI 走查

素材来源：仓库内的 `kimi_replay_capture/`。

> 勘误 / 修正说明
>
> 本文档早期版本对素材来源的边界说明不够醒目，可能让人误以为底部状态栏属于 Kimi 常规实时对话流式界面。已按用户提示重新核对 Kimi 官方文档：
>
> - 官方文档站点 `https://platform.kimi.com/docs`（canonical `https://platform.moonshot.cn/docs`）的导航仅包含「欢迎 / 使用手册 / 模型列表 / 快速上手 / 下一步」等 API、模型与开发指南，**没有**客户端聊天 UI、底部状态栏、回放/分享页控件等界面描述。
> - 本走查中观察到的「Kimi Agent 正在回放 / 回放完成 / 做同款 / 看回放」等**底部持久控制条**，仅出现在**已分享的 Agent 回放/分享页**（如「做同款」分享链接），**不属于** Kimi 常规 K2.6 Agent / Agent Swarm 实时对话流式界面（live chat）。常规 live chat 底部应保持输入区域。
> - 因此，Octopus 在普通 agent 流式对话中**不应引入**持久底部状态栏，仅在后续构建回放/分享页时，才需要在 `ChatPageLayout` 中新增 `bottomBar` 插槽作为回放控制条。当前 `ChatPageLayout` 组件**并未实现** `bottomBar` prop，普通 live chat 的底部区域仍是 `inputArea`。
>
> **2026-07-05 实现勘误**：本文部分建议中的 tabs 描述（如"预览、代码、终端、文件、变更"）与实际实现有出入，已按当前代码修正：
>
> - 右侧工作台顶级 tabs 为：概要（含"活动轨迹/电脑视图"子切换）、计划、产物、变更(Diff)、终端、浏览器预览；没有独立的"文件"tab（文件浏览统一由左侧文件树承担）和"代码"tab。
> - "电脑视图"是概要页内的子视图（summary/screen 切换），不是独立顶级 tab。电脑视图的层级规则：主 agent 未选中子 agent 时展示子 agent 选择列表或空状态；选中子 agent 后展示 SubagentProcessView（子 agent 独立操作轨迹）；选中协作成员时展示协作成员占位。

- 录制方式：网页回放，60 秒，每秒 2 帧，共 120 帧。
- 关键总览：`contact_sheet_5s.jpg`
- 重点帧：15.0s agent 弹层、37.0s 预览接管、40.0s 修复执行、43.0s 思考空状态、51.5s 规格与预览并行、最终完成态。
- 补充截图：`notes/subagent-computer-activity-view.png`、`notes/subagent-computer-terminal-view.png`、`notes/subagent-role-card.png`、`notes/subagent-role-description.png`
- 重要区分：本素材是对一次 **已分享的 Agent 回放/分享案例** 的网页录屏。Kimi 在**回放/分享页**（如分享链接打开的页面）才会出现“Kimi Agent 正在回放 / 回放完成 / 做同款 / 看回放”等**底部持久控制条**；Kimi 常规 K2.6 Agent / Agent Swarm 的实时对话流式界面（live chat）底部没有这种持久状态/控制条，仍然保持输入区域。
- 官方文档范围：已核对 Kimi 开放平台官方文档索引（`https://platform.moonshot.cn/docs`，canonical URL `https://platform.kimi.com/docs`）。2026-07-04 再次抓取 `https://platform.kimi.com/docs/overview`，页面导航仅包含「欢迎 / 使用手册 / 模型列表 / 快速上手 / 下一步」等 API、模型与开发指南；**未包含**客户端聊天 UI、实时对话流式界面、底部状态栏或回放/分享页控件的相关描述。搜索页面可见文本亦未命中任何 UI/底部状态栏关键词。因此，本文关于“底部状态栏为回放/分享页专属、常规 live chat 不存在”的结论来自对网页录屏（分享页）与正常对话页交互形态的对照，并非来自官方 UI 设计文档。

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

- `ChatPageLayout` 已支持 `secondaryPanel`；当前底部固定区域是 `inputArea`，**没有** `bottomBar` prop。若后续需要回放/分享页，可在 `ChatPageLayout` 新增 `bottomBar` 插槽。
- `agent-workbench-panel` 已有阶段、终端、浏览器预览、变更(diff)、产物(artifacts)、计划(plan)的基础能力；文件浏览统一由左侧文件树承担，右侧面板不再单独提供文件tab，可以作为右侧“Octopus Computer”。
- 需要减少右侧作为“抽屉”的感觉，让它在执行态成为一等主面板。

建议：

- 新增或强化 `AgentRunWorkbench` 级别壳层，固定标题区、phase 区、内容 tabs。
- 左侧 message list 保持叙事，右侧不要跟随左侧滚动。
- 桌面端优先双栏，移动端切为底部/顶部 tabs：对话、概要、电脑、变更、终端、预览。

### 2. Phase 进度模型

Kimi 同时用了两层进度（本素材来自分享/回放页，底部执行卡阶段在该场景下出现）：

- 右侧大任务阶段：`当前进度 7/7 / Phase 7: Merge, build & deploy`（在常规 live chat 中仍然存在）
- 底部执行卡阶段：`当前进度 1/4 / Phase 2: Hall VI 银信局 ...`（仅在回放/分享页可见，常规 live chat 不引入）

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

对 Octopus 的映射（当前实现状态）：

- `agent-workbench-panel` 作为父级 `Octopus Computer`，顶级 tabs 为：概要（含"活动轨迹/电脑视图"子切换）、计划、产物、变更(Diff)、终端、浏览器预览。
- **电脑视图的层级规则**（已实现）：父级电脑的"电脑视图"子页面中，未选中子 agent 时展示子 agent 选择列表卡片（点击可进入对应子 agent 电脑）；选中子 agent 后展示 `SubagentProcessView`（即该子 agent 的独立电脑操作轨迹）；选中协作成员时展示协作成员占位。
- 子 agent 电脑视图顶部显示 agent 编号、状态灯、进度计数、角色信息和 dock 状态，底部提供"返回总电脑"入口。
- 左侧 agent 摘要页(AgentSummaryPage)中点击子 agent 卡片会切换到该子 agent 的电脑视图。
- 文件浏览统一由左侧文件树承担，右侧面板不单独提供文件 tab，避免功能重复。

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
- 顶级 tabs：概要（含活动轨迹/电脑视图子切换）、计划、产物、变更(diff)、终端、浏览器预览。文件浏览统一由左侧文件树承担，不在右侧重复提供文件tab。
- 电脑视图的层级规则：主 agent（未选中子 agent）时，电脑视图显示子 agent 选择入口或空状态提示；选中子 agent 后，电脑视图显示该子 agent 的独立电脑操作轨迹（工具调用、终端命令等）；选中协作成员时显示协作成员占位。
- 底部或空状态显示"返回最新"/"正在等待下一帧"等轻提示。

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

### 9. 持久底部控制（回放/分享页专属）
> 已核对 Kimi 开放平台官方文档索引（`https://platform.moonshot.cn/docs`，canonical URL `https://platform.kimi.com/docs`）：该文档集涵盖 API、模型、定价、开发指南与协议，**没有**关于客户端聊天 UI、底部状态栏或回放/分享页控件的描述。本节观察到的“底部控制条”仅出现在**回放/分享页**（例如“做同款”分享链接），不是 Kimi 常规 K2.6 Agent / Agent Swarm 实时对话流式界面（live chat）的必需结构；常规 live chat 底部应保持输入区域。

Kimi 回放/分享页底部控制条非常稳定：左侧显示“Kimi Agent 正在回放/回放完成”，右侧给“看结果/看回放”和“做同款”。执行中还会出现一张“执行任务中...”的小卡，并带展开图标。

对 Octopus 的映射：

- 常规 live chat 不需要复制这个底部控制条；应保留现有输入区域作为底部。
- 若未来构建回放/分享页，可在 `ChatPageLayout` 新增 `bottomBar` 插槽，作为真正的回放控制条。

建议：

- 普通 agent 流式：把执行状态收敛到 workbench 标题区、phase pill、消息流中的 typed block 里，不额外占用底部。
- 回放/分享页专用：再在 `ChatPageLayout` 新增 `bottomBar` 插槽，语义为“回放中 / 回放完成 / 查看结果 / 复盘过程 / 复用此流程”。
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
11. 回放/分享页底部 CTA 持久存在，执行中和完成后语义切换；常规 live chat 不适用。
12. 回放不是录像，而是可点击的事件时间线。
13. 修复过程把“问题判断、修复动作、验证结果”放在同一条叙事里。

## 不建议照搬的点

1. Kimi 左侧在长任务中信息密度偏高，容易造成扫读压力；Octopus 可以用更强分组和折叠。
2. 右侧预览加载空白时缺少明确 skeleton 或状态文案；Octopus 可以加轻量状态。
3. 代码/预览切换入口较小，专业用户可能需要更明显的 diff/terminal 快捷入口。
4. agent popover 信息很实用，但可操作性弱；Octopus 可以补“查看日志 / 打开产物 / 停止此 agent”。
5. 最终结果区域右侧有时空白，完成态可以自动切到最终预览或 receipt 面板。

## Octopus 优先级建议

> **状态核查 2026-07-17。** 本节的勾此前严重滞后：P1/P2 里至少 7 项早已落地却没标，
> 于是被当成待办反复讨论。下面每条 ✅ 都附了 `文件:行` 证据。
>
> **核查这份清单时踩过的两个坑，后来者请避开：**
> 1. **按名字搜会漏掉换名实现。** 完成态 receipt 就活在 `message-output-summary.tsx`
>    里，搜 `CompletionReceipt` 一无所获；`AgentComputerPanel` 实为
>    `agent-workbench-panel.tsx`。按**能力**找，别按提案里的名字找。
> 2. **grep 空结果 ≠ 功能不存在。** 「预览优先」一度被误判为唯一缺口，实际
>    `page.tsx:2309` 早就实现了——只是当时那条 grep 因路径含 `[thread_id]` 方括号
>    而静默读空。下结论前先用一个**已知存在的符号**验证命令本身能出结果。

### P0：把执行态骨架立住

- ~~`secondaryPanel` 固定为 Agent Workbench，而不是临时抽屉。~~ ✅ 已实现。
- ~~phase snapshot 贯通 header、workbench、消息流中的状态块。~~ ✅ 已实现，且是
  **服务端快照优先、事件重算兜底**的正确形态：后端发 `turn/plan/updated` +
  `workbench/snapshot`（`realtime_event_bridge.py:635/645`）→ 快照搭在事件上 →
  `agent-workbench-snapshot.ts:108` 的
  `serverSnapshotToAgentPhases(serverSnapshot, …) ?? derived.phases`
  取快照，没有才回退 `deriveAgentPhases(events)`；`currentPhase`(`:116`)、
  `currentBlock`(`:122`)、`focusedTab`(`:143`) 同样是快照优先。消息流侧走
  `use-thread-stream-realtime.ts:384` 的 todo 事件。三处同源，符合
  `WorkbenchSnapshotV2` docstring “实时与回放共用同一当前帧”的初衷。
  > 注：面板里搜不到 `AgentPhaseSnapshot` 这个类型名——它经
  > `useAgentWorkbenchSnapshot`/`WorkbenchSnapshotV2` 消费。**这正是本节顶部第 1 条
  > 坑的活例**，别据此误判成“没接快照”。
- **仍存在的真实约束（不是本条的欠债，但决定了右栏何时有内容）**：整条计划链的源头是
  模型调 `todo_write`（`_phases_from_todo_preview`）。不调 todo_write 的 turn 没有
  phases 可发，右栏就只有空壳——这才是「右栏空白」的根因，也是与 Kimi
  「一开跑就有 Phase 1..7」的真实差距：Kimi 的 planner 架构上必出计划，我们的计划是
  某个工具的副产品。要追平得让 planner 对实质任务强制先出计划（产品决策，非 UI 修补）。
- ~~workbench 需要支持父级总电脑和子 agent 电脑两个 scope。~~ ✅ 已实现（通过 `selectedAgent`/`selectedRosterSeat` 切换；电脑视图含子 agent 选择列表、子 agent 操作轨迹、协作成员占位）。
- 移除右侧面板"文件"tab（与左侧文件树功能重复），文件操作统一通过左侧文件树。 ✅ 已实现。
- `ChatPageLayout` 的 `bottomBar` 插槽（持久回放控制条）。**未实现，且属有意不做**——
  本条自述“只在回放/分享页*考虑*，常规 live chat 不引入底部执行 footer”。不是欠债。

### P1：让 agent 集群可理解

- ~~在消息流中加入紧凑 `AgentClusterCard`。~~ ✅ 已实现（`messages/process-trace.tsx:232` 定义，158 使用）。
- ~~每个子 agent 支持 hover/click detail。~~ ✅ 已实现（hover=`SubtaskHoverPreview`，click=`AgentIdentityCard`；`messages/parallel-subtasks-grid.tsx:214`）。
- ~~支持按 agent 过滤右侧 timeline。~~ ✅ 已实现（`agent-workbench-panel.tsx:911` “Agent filter chip row”，可在主进程与各子 agent 间切换）。
- 点击子 agent 后，右侧切换到该 agent 的独立电脑（电脑视图中的 SubagentProcessView）。 ✅ 已实现。

### P1：子 Agent 身份与角色说明

- ~~创建子 agent 时展示 `AgentIdentityCard`。~~ ✅ 已实现（`messages/parallel-subtasks-grid.tsx:369`）。
- ~~角色卡包含头像、名字、角色、使命短句、角色说明入口。~~ ✅ 五项俱全（大头像 `:405`、
  `displayName :377`、`roleName :378`、`motto :381`、`brief`(=task.prompt) `:385`）。
- 角色说明可复用现有 agent profile dialog，并保留回到活动轨迹的入口。**未按此机制做**：
  改为卡内内联 brief 段，未复用 profile dialog。意图（角色说明可读）已满足，
  除非要统一入口，否则不必再动。

### P1：完成态 receipt

- ~~标准完成卡：结果 URL、变更表、验证表、文件入口、复用按钮。~~ ✅ 已实现，
  **组件名是 `messages/message-output-summary.tsx`**（`artifacts` 文件入口、`changes` 变更表、
  `verifications` 验证表、`diffCounts`、`extractResultUrl :342` 且 `:563` 渲染成链接、
  `makeSimilar`/`retryTask` 复用按钮）。
- 支持“查看回放”和“做同款/复用流程”。**只做了一半**：`makeSimilar`（做同款）已在
  `message-output-summary.tsx:588`；但**完成卡内没有“查看回放”入口**，回放目前只
  挂在分享菜单里。

### P2：回放体验

- ~~将 live tool events 存成 replay frames。~~ ✅ 已实现，但形态不同：
  `replay-from-blocks.ts` 的 `buildReplayFromBlocks` + `core/sharing/replay-html.ts` 的
  `buildReplayHtml`，产出**自包含 HTML 导出**，从统一分享菜单触发（`page.tsx:85/86/2008`），
  而非站内回放播放器。
- 回放时底栏显示进度、结果入口、复用入口。**未实现**（与上面的 `bottomBar` 同一条，有意不做）。
- ~~点击左侧任一 tool/agent block，右侧跳到对应机器证据。~~ ✅ 已实现
  （`emitAgentWorkbenchFocus`：`live-tool-timeline.tsx:1474`、`parallel-subtasks-grid.tsx:93/252`、
  `swarm-run-overview.tsx:357`）。

### P2：预览优先

- ~~网站/前端任务中，右侧默认最终落到 Preview tab。~~ ✅ 已实现
  （`page.tsx:2309-2336` 的 effect：跑完且有 `previewBlocks || resultPreviewUrl` 时
  `setAgentWorkbenchTab("browser")`，并由 `agentWorkbenchTabTouched` 守门——用户手动
  选过 tab 就不抢视图，移动端也不自动展开）。手动入口是 `openPreviewPanel`（`:2646`）。
- 当 agent 发现视觉问题时，左侧显示问题判断，右侧保持问题现场。**未核查**——这是个
  跨左右栏的联动行为，不是单个符号，没法靠 grep 定论；要判断得实跑一个视觉修复任务。

## 可以转成组件任务的清单

- `PersistentRunFooter`（回放/分享页专用）
  - 状态：idle/running/replaying/completed/error。
  - CTA：查看机器、查看结果、复盘过程、复用流程、停止。
  - 注意：常规 live chat 不使用持久底部状态栏。

- `RunStatusLamp`
  - 绿色：正常运行/完成。
  - 黄色：等待确认、阻塞、重试、排队、外部资源等待。
  - 红色：失败、异常、权限拒绝、不可恢复错误。
  - 灰色：空闲或未启动。
  - 必须搭配短状态文案，不单靠颜色。

- `AgentComputerPanel`
  - Header：名称、状态、phase、进度、操作按钮。
  - 顶级 Tabs：概要(含"活动轨迹/电脑视图"子切换)、计划、产物、变更(Diff)、终端、浏览器预览。文件浏览不在右侧重复提供。
  - Body：绑定当前 selected event。
  - Scope：global computer / sub-agent computer / roster seat computer。
  - 电脑视图子视图规则：主 agent 无选中子 agent 时展示子 agent 选择列表或空状态；选中子 agent 后展示其独立操作轨迹（SubagentProcessView）。

- `SubAgentComputerView`（即 `SubagentProcessView`，已实现）
  - 顶部：agent 编号、状态灯、进度计数(如 3/7)、角色信息、dock 状态。
  - 主区：该子 agent 的工具调用时间线（编辑文件、运行终端、浏览器操作等块级记录），支持展开查看命令详情和输出。
  - 底部：提供"返回总电脑"入口。

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

1. ~~先用现有 `ChatPageLayout.secondaryPanel` 固定右侧 `agent-workbench-panel`。~~ ✅ 已实现。
2. ~~从 `liveToolEvents` 派生统一 `phaseSnapshot`。~~ ✅ 已实现（通过 `useAgentWorkbenchSnapshot`）。
3. ~~给 workbench 增加 `scope`：全局电脑或指定子 agent 电脑。~~ ✅ 已实现（通过 `selectedAgent`/`selectedRosterSeat` 切换 scope；电脑视图支持子 agent 选择列表、子 agent 操作轨迹、协作成员占位三种状态）。
4. 在消息流里把 tool/agent 事件渲染成 typed blocks。
5. 完成时追加 `CompletionReceipt`，并让右侧自动切到 Preview 或 Changes。
6. ~~移除右侧面板中与左侧文件树重复的“文件”tab，文件操作统一通过左侧文件树进行。~~ ✅ 已实现。
7. （仅当构建回放/分享页时）将 `chat-streaming-footer` 提升为 `ChatPageLayout` 的 `bottomBar` 插槽，作为持久回放控制条。

完成以上步骤后，Octopus 的 agent 流式体验会从“日志在跑”变成“一个可审计、可接管、可复盘的工作现场”。

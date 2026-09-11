# ChatGPT / Codex 前端解包对照报告

日期：2026-09-08。对象：Echo 当前工作区（HEAD c5dcd39a，包含尚未提交的本地改动）。本次是本地打包资源与项目代码对照，不是另一轮全窗口视觉走查，也未修改业务代码。

## 结论

最值得借鉴的是：明确的用户意图、稳定的阅读位置、围绕任务组织的信息，以及局部可恢复的错误状态。Echo 已有草稿恢复、历史消息虚拟化、活动折叠、来源引用、代码块和会话定位，不应再叠加一套同类基础设施。优先收敛现有交互和状态，再做必要的组件拆分。

## 1. 解包来源和可信边界

- 本机包管理查询仅发现 `OpenAI.Codex 26.901.6511.0`，未发现独立 ChatGPT 安装包。
- 原始文件：`C:/Program Files/WindowsApps/OpenAI.Codex_26.901.6511.0_x64__2p2nqsd0c76g0/app/resources/app.asar`。
- 包内 package.json 标识：`openai-codex-electron`，productName 为 Codex，内部版本 `26.901.51231`。安装包版本与内部版本分别记录，不混用。
- ASAR：299,109,787 字节；SHA-256：`e75bae2b8a02f174c7ceeed6d631aaff355e44f8af5c798fa3628089f11d659e`。
- 已提取 package.json 和 webview 下的 JS/CSS/HTML/JSON 等文本资源：7,162 个文件，190,958,371 字节。并非提取整个安装包的原生二进制、图片或所有主进程文件。
- 未提取到 source map。部分 JS 尾部存在 sourceMappingURL 注释，但对应 map 不在提取内容中。
- 18 个选定 JS/CSS 已格式化以便阅读；这是构建产物，不是恢复了原始 TypeScript 源码。
- 包内确有 `chatgpt-conversation-page`、`chatgpt-sources-side-panel-tab`、`use-chatgpt-composer-controller` 等模块。因此以下严格区分 ChatGPT 模块与桌面共享模块，不能据此宣称独立 ChatGPT 网站/客户端全部采用相同实现，亦不能推断功能对所有账号可见。

本地证据：[解包清单](</D:/echo agent/.codex-run/frontend-reference/extraction.json>)、[包内标识](</D:/echo agent/.codex-run/frontend-reference/unpacked/package.json>)、[格式化文件](</D:/echo agent/.codex-run/frontend-reference/readable>)。

## 2. 值得学习的八个方面

| 方面 | 打包代码中实际观察到什么 | Echo 已有基础 | 建议与优先级 |
|---|---|---|---|
| 输入框意图表达 | 共享首页模式控件使用 Chat/Work 文本、解释性提示、aria-pressed，并处理减少动画偏好 | ChatComposer 有聊天模式图标、运行设置、模型、权限；ChatInputBox 有工作目录和模式条 | **优先 1**：把聊天/执行意图变得可读。保留一处模式入口；研究、开发、设计作为任务预设；引擎放入运行设置。不要再加一排互相重叠的模式按钮 |
| 局部错误恢复 | ChatGPT 来源面板把加载、空、错误分开；错误附近带重试。会话创建、编辑、重新生成失败分别处理 | 草稿失败恢复、断线禁止提交等逻辑已存在 | **优先 1**：给各区域统一 empty/loading/error/ready 规则；失败只影响相关区域。权限、未安装和暂时性服务错误使用不同动作 |
| 内容与工作台分工 | ChatGPT 会话摘要明确区分 Progress、Outputs、Inputs、Subagents，以及云浏览器入口 | AgentWorkbenchPanel 已有活动、产物、浏览器、终端等，并延迟加载和控制打开的标签 | **优先 1**：收敛为当前任务的进度、来源、产物；终端、差异和浏览器按任务需要打开。维护一个面板选择状态，避免重复面板各自管理同一选择 |
| 阅读位置与长会话性能 | 共享 virtualizer 有测量高度、范围计算、overscan、稳定 turnKey，以及布局变化前后的锚点补偿；共享 composer 与滚动控制器协同管理底部空间 | MessageList 已有 HistoricalTurnBoundary、IntersectionObserver、ResizeObserver、高度缓存、memo、正常文档流和历史内容可见性优化 | **优先 2，先测量**：借鉴锚点不变量和验收场景，保留当前策略。不要因为对方有虚拟列表就替换现有实现 |
| 长会话定位 | 共享导航轨包含跳转、摘要预览、预览加载失败、书签和辅助标签 | Echo 已有 TurnLocatorRail、当前轮定位、首尾跳转 | **优先 2**：先提高可发现性和有效点击面积，增加可选的用户提问摘要。普通轮标记按钮目前 h-2.5，视觉小圆点不应同时决定命中高度；移动端提供目录入口 |
| 语义样式与宽内容 | CSS 区分文本/边框/表面等语义变量，正文宽度与 markdown 宽块上限分开；存在多个作用域覆写 | globals.css 已有文字尺度、密度、边框、阴影、圆角变量 | **优先 2**：统一变量使用，不再造新主题体系。正文保持阅读宽度，表格/代码/图表允许更宽；不能把提取的变量列表最后一个值当成全局设计规范 |
| 引用和来源 | ChatGPT 来源面板按来源类型组织，包含无来源、记忆加载失败、重试、展开更多及删除内容的不可用状态 | CitationLink 已有链接和悬浮卡；workbench 有 groundingSources | **优先 2**：把行内引用和任务来源列表关联到同一来源 ID。保留网页与工作区文件的区别；触屏支持点击查看。引用卡仍有硬编码英文 Visit source，可纳入本地化收尾 |
| 代码和产物操作 | ChatGPT 代码模块按上下文提供代码/预览、运行/停止、下载，以及预览/下载失败反馈 | Echo 代码块已有流式轻量渲染、复制、换行切换；已有 artifact panel | **优先 3**：复用已有能力统一操作位置和状态。只在有实际运行环境时显示运行；不要为了复刻把所有操作常驻每个代码块 |

这里的优先级是本项目改造顺序，不是已测得的性能收益或线上事故等级。

## 3. 关键证据映射

| 结论 | 外部包证据（本地格式化副本） | Echo 对应文件 |
|---|---|---|
| Chat/Work 语义与选中态 | [home-composer-mode-toggle](</D:/echo agent/.codex-run/frontend-reference/readable/home-composer-mode-toggle-419a558469fc.js:86>) | [ChatComposer](</D:/echo agent/frontend/src/components/workspace/chat-input-box/ChatComposer.tsx:1932>)、[ChatInputBox](</D:/echo agent/frontend/src/components/workspace/chat-input-box.tsx:225>) |
| 编辑器按能力配置 | [use-chatgpt-composer-controller](</D:/echo agent/.codex-run/frontend-reference/readable/use-chatgpt-composer-controller-dcc0598cc72c.js:32>) | [ChatComposer 草稿恢复](</D:/echo agent/frontend/src/components/workspace/chat-input-box/ChatComposer.tsx:171>) |
| 来源错误和空状态 | [sources 面板](</D:/echo agent/.codex-run/frontend-reference/readable/chatgpt-sources-side-panel-tab-60272b91c05e.js:923>) | [CitationLink](</D:/echo agent/frontend/src/components/workspace/citations/citation-link.tsx:16>) |
| 任务摘要的信息分区 | [conversation page](</D:/echo agent/.codex-run/frontend-reference/readable/chatgpt-conversation-page-d431ebf7521c.js:1146>) | [AgentWorkbenchPanel](</D:/echo agent/frontend/src/components/workspace/agent-workbench-panel.tsx:427>) |
| 锚点与高度变化 | [thread-virtualizer](</D:/echo agent/.codex-run/frontend-reference/readable/thread-virtualizer-4f61d89b50be.js:67>)、[composer-provider](</D:/echo agent/.codex-run/frontend-reference/readable/composer-provider-4037608dc581.js:40>) | [HistoricalTurnBoundary](</D:/echo agent/frontend/src/components/workspace/messages/message-list.tsx:197>) |
| 对话摘要预览和定位 | [navigation rail](</D:/echo agent/.codex-run/frontend-reference/readable/thread-user-message-navigation-rail-app-3b2a67daad6b.js:415>) | [TurnLocatorRail](</D:/echo agent/frontend/src/components/workspace/messages/message-list.tsx:3394>) |
| 正文/宽块分离 | [thread-scroll-layout CSS](</D:/echo agent/.codex-run/frontend-reference/readable/thread-scroll-layout-26a32b412ec3.css:1>) | [全局语义变量](</D:/echo agent/frontend/src/styles/globals.css:274>) |
| 代码预览及能力动作 | [ChatGPT code block](</D:/echo agent/.codex-run/frontend-reference/readable/chatgpt-code-block-7e6be1d52811.js:1671>) | [Echo code block](</D:/echo agent/frontend/src/components/ai-elements/code-block.tsx:148>) |

## 4. 我建议 Echo 采用的前端组织方式

以下是改造建议，不是对对方内部源码结构的还原。

```text
应用壳：路由 / 系统窗口适配 / 侧栏 / 全局搜索
└─ 当前任务
   ├─ 输入区：草稿、附件、用户意图、发送与停止
   ├─ 对话区：答案、必要进度、引用、错误恢复
   └─ 工作台：当前任务的来源 / 产物 / 工具详情

引擎适配层 → 统一任务事件与能力 → 上述三个区域
共享基础组件 → 字体、间距、按钮、菜单、弹窗、状态反馈
```

- 角色回答“谁协助我”，任务预设回答“做什么”，权限回答“可以做什么”，引擎回答“如何执行”。数据模型可以分开，界面不必把四个维度都作为同等突出的主入口。
- Octopus 与 Codex 的运行事件先适配到统一前端模型，再交给会话和工作台显示。前端不要发展成两套聊天 UI。
- ChatComposer 后续可逐步拆出草稿/提交控制、附件与提及、意图选择、运行设置、底部操作。沿用现有公开 props，分批迁移，避免一次性重写。
- MessageList 后续可拆出历史轮次边界、滚动与定位、时间线归并和渲染器；先固定滚动行为再移动代码。
- 桌面窗口控件继续归宿主所有。此前已清理的返回桌面/全屏按钮无需重新引入。

## 5. 三批可验收的工作

### 第一批：用户看得懂且出错能恢复

1. 用明确文案呈现聊天/执行，合并重复的运行入口；切换不丢草稿、附件或目录。
2. 为来源、产物、插件、模型连接统一局部加载和错误状态；重试不重复创建任务或重复安装。
3. 对齐工作台和会话中的任务选择；打开结果后切换任务，不应显示上个任务的来源或文件。

验收：普通用户不必理解两个引擎也能开始任务；可见控件明确可点；失败时能判断原因与下一步；恢复后不会重复提交。

### 第二批：长会话与界面一致性

1. 使用 200 轮代表性会话，覆盖持续输出、代码块增高、图片延迟加载、加载更早历史和切换线程，记录帧时间、DOM 数及阅读位置偏移。当前尚未做此基准，不能声称需要更换虚拟化库。
2. 保留正在阅读的轮次位置；用户向上阅读时，新输出不抢回底部；回到底部与轮次跳转都有明确入口。
3. 增大轮次导航命中区、增加摘要预览，检查键盘和触屏路径。
4. 将首批高频界面统一到已有文字/边框/阴影 token，并验证窄屏、深色和宽内容。

### 第三批：产物和高级功能

统一来源详情、代码预览、下载、运行等上下文操作。只补真实业务需求，不照搬云端账户/工作任务生命周期或复杂书签能力。

## 6. 不建议照搬

- 不把打包 JS 复制到 Echo 运行：其中依赖共享 chunk、桌面桥接、内部状态及服务端能力，无法当成独立组件直接接入。
- 不照搬编译器生成的 memo 缓存代码；它不等于适合手写维护的组件结构。
- 不因文件名出现 subagent 或 cloud 就推断后台一定并发执行或存在某种引擎架构。
- 不照搬所有细小图标和隐藏入口。用户已明确反馈点击区域和可发现性，我们应保留克制的外观，同时确保可点击。
- 不把本次打包资源分析当成性能跑分或全平台实机验收。

## 7. 完成状态

解包与重点模块对照已完成；生成报告和证据索引。所有解包产物留在 `.codex-run/frontend-reference`，没有修改安装包，也没有向业务代码复制打包实现。没有运行或执行解包的应用代码。

本次未做业务改动，因此没有额外运行 Echo 测试。后续实施时按上述三批分别验证，不把上一轮主页测试当作本报告建议的验收结果。

## 8. 补充：布局、画中画与浏览器悬浮聊天

补充日期：2026-09-08。再格式化 12 个相关资源。以下是打包代码证据与 Echo 设计建议；没有把文件名当作已启用功能，也没有依据代码推断所有用户的实屏布局。

### 已确认的实现

- **浏览器由缩略预览进入大面板**：cloud-browser-preview 的 compact 形态为 16:10；激活预览会打开更大的浏览器侧面板。支持活动时间线、截图加载失败状态，加载指示延后 0.5 秒显示。桌面 hover/focus 显示控制项，触屏无 hover 时控制项保持可见。
  - [预览交互](</D:/echo agent/.codex-run/frontend-reference/readable/cloud-browser-preview-d8f38ddb119a.js:388>)、[预览 CSS](</D:/echo agent/.codex-run/frontend-reference/readable/cloud-browser-preview-37854eb6b805.css>)。
- **悬浮聊天是可变形的会话视图**：local-conversation-quick-chat-overlay 接收 conversationId，读取 hostId/threadId 和 activeBrowserTabId；renderTranscript 使用同一 conversationId。控件包含展开、紧凑、横向/纵向调整、拖动、收起到角落、恢复。监听容器和窗口尺寸变化并处理窗口缩放坐标。
  - [位置及尺寸控制](</D:/echo agent/.codex-run/frontend-reference/readable/local-conversation-quick-chat-overlay-6a4fa8756bcf.js:454>)、[当前会话与浏览器绑定](</D:/echo agent/.codex-run/frontend-reference/readable/local-conversation-quick-chat-overlay-6a4fa8756bcf.js:1242>)。
- **还存在独立 Quick Chat 窗口路径**：quick-chat-window-page 使用窗口服务、会话 ID、window variant 和关闭生命周期。它与上面的当前任务悬浮聊天不是可以随意混称的同一入口；不能据此保证所有小窗都使用当前主任务。
  - [独立窗口页](</D:/echo agent/.codex-run/frontend-reference/readable/quick-chat-window-page-3c20930fb2c9.js:33>)。
- **画中画有位置协调**：remote-hosted-pip-anchor-bridge 计算四角锚点，考虑 obstacleRects、容器边界、滚动和缩放；悬浮聊天标记 data-pip-obstacle。说明位置不是简单写死在右下角。当前证据尚不足以确认每种画中画承载什么内容，或是否调用浏览器原生 documentPictureInPicture API。
  - [锚点与避让](</D:/echo agent/.codex-run/frontend-reference/readable/remote-hosted-pip-anchor-bridge-4f45838df2bd.js:2>)。
- **能力可能受开关控制**：unified-floating-composer.electron 同时检查 local-thread/client-local-thread 范围与功能开关，不能把包里存在的代码等同于全量发布。

### Echo 应该学习的布局原则

**让当前操作对象占据主画布，聊天根据需要停靠、浮动或收起。** 以下是建议的三种状态，不是声称对方精确采用这些分栏比例。

| 状态 | 主画布 | 辅助区域 | 适用场景 |
|---|---|---|---|
| 对话为主 | 答案与消息 | 可展开的浏览器/文件预览 | 问答、研究、查看执行进度 |
| 浏览器为主 | 大面积网页或作品预览 | 侧边停靠聊天，或可收起的悬浮聊天 | 边看网页边要求修改、选择元素、验收结果 |
| 临时小窗 | 当前其他工作内容 | 当前任务的紧凑聊天或预览 | 暂时切走但仍需关注任务，不应自动开启 |

我们已有两个方向的入口：浏览器页的 AssistantPanel 占固定侧栏宽度，工作台有 BrowserPreviewPanel。最值得补的是二者之间的布局切换与上下文连续性，不是再做第三套对话逻辑。

建议状态：`docked → floating → minimized`，桌面宿主具备能力时再增加 `detached`。这些是呈现状态，不是新任务、权限或引擎模式。

### 必须保持的规则

1. 当前任务浮窗共享 threadId、消息、草稿、附件和运行状态；明确显示所绑定的浏览器标签，避免把指令发给错误页面。
2. 停靠转浮动后保留一个输入焦点和一条提交路径，不同时复制两个可提交的输入区。
3. 浮窗有可识别的拖动区、合理的点击面积、展开/收起和返回停靠入口；不要把所有控制藏到 hover。
4. 选元素/截图时临时收起或避让；实际可点击区域之外不吞掉网页点击，停止拖动后可靠释放捕获。
5. 窗口缩小、DPI/缩放或多屏位置变化后把浮窗约束回可见范围；移动端优先底部面板或全屏切换，而非缩小的桌面浮窗。
6. 停止任务不等于关闭小窗；关闭小窗不应取消后台任务，若需停止要有明确动作。
7. 不同进程的弹出窗口要通过统一会话服务同步，不能各自建立重复提交或重复执行链路。

### 实施顺序

第一步：为现有浏览器 AssistantPanel 增加停靠/悬浮/收起，并继续使用同一个当前任务。
第二步：打通会话中的预览与浏览器大画布，保留返回位置、草稿与所选元素上下文。
第三步：有实际使用需求再做系统级独立小窗，验证 Windows/macOS/Linux 的焦点、DPI、置顶和生命周期。

验收重点：切换形态不丢草稿、不重发任务、不挡选取、不抢焦点、窗口变化后不漂出屏幕。本次仅给出布局设计与证据，没有实现这些新增状态。

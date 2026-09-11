# Echo × 本机 Codex：客户端资源静态分析

日期：2026-09-09。范围：只读检查本机安装包、提取前端资源、对照 Echo 工作区源码和本轮已有截图。未修改 Codex 安装文件，未修改 Echo 产品代码。没有进行 Codex 原生界面的交互验收，因此以下区分“包内实现证据”和“Echo 设计建议”；资源存在不等于所有账户都已启用。

## 版本与方法

- Windows 安装包：OpenAI.Codex_26.901.6511.0_x64__2p2nqsd0c76g0。
- app.asar 内 package.json 版本：26.901.51231。两种版本号来自不同层级，不能混称。
- app.asar：299,109,787 字节；索引包含 8,829 个文件。
- 读取 ASAR 索引与偏移，选择性提取前端 JS/CSS；首批 142 个文件，补提取 3 个队列/折叠相关文件。格式化部分压缩资源以便检查控制逻辑。
- 临时证据目录：C:/Users/Administrator/AppData/Local/Temp/codex-ux-26.901.6511/。未把第三方整包代码加入 Echo 仓库。
- 官方入口 https://developers.openai.com/codex/app/features 本次重定向至 https://learn.chatgpt.com/docs/features ，不将其当成本机版本行为的证据。

## 最值得借鉴的六点

### 1. P0：过程按状态展开，完成后让结果成为视觉中心

包内 tool-activity-disclosure-adf1d041e8ba.js:78 起有 defaultExpanded、summary、status 参数。defaultExpanded 未传时为 false；运行状态默认展开，并允许用户主动收起；结束后采用独立的展开状态。折叠内容设置 aria-hidden 与 inert，并测量内容高度以过渡。

Echo 已有过程回放和分组能力，不应再叠加一套。建议把同轮工具、模型标记、恢复信息合并为一条“已完成 · 11 步 · 查看过程”，回答正文优先；未解决异常与待确认请求保持展开。

落点：frontend/src/components/workspace/messages/message-group.tsx、collapsible-activity-group.tsx、process-trace.tsx。
验收：20 次工具调用不会形成 20 个常驻过程块；手动展开后不被新消息随意折叠；隐藏内容不进入键盘焦点顺序。

### 2. P0：右侧面板跟随具体结果，空状态不要占据主工作区

包内存在 artifact-preview-header、open-artifact-side-panel-tab、thread-side-panel-tab-content，以及摘要面板的 preview/expanded/collapsed 高度状态。能确认有面向具体内容的面板结构；不能仅据此断言 Codex 所有空面板都会自动关闭。

Echo 本轮截图中，右侧长期显示“看板概览”，占用了较大阅读宽度；EmptyShellView 也有显式空产物和空工作台分支。建议无内容时首次进入默认收起，提供“查看工作台”；点击文件、网页或差异时打开对应内容。尊重用户手动固定，不在流式更新时反复开关。

落点：frontend/src/components/workspace/agent-workbench-panel.tsx、agent-workbench-panel/empty-shell-view.tsx。
验收：首次普通聊天没有空看板；点击产物直接定位；用户手动固定的面板不会自动消失。

### 3. P1：输入框负责表达意图，复杂配置渐进显示

包内 composer-utility-bar-cddbdfb015e1.js 中，运行位置、起始代码状态、现有工作区分别拥有上下文说明和 tooltip；不是把所有配置变成一行无解释的术语。此处确认组件实现，不推断所有模式下的可见组合。

Echo 的 ChatComposer 同时组织权限、模型、引擎、协作与技能入口。建议常驻“附件、当前模式/模型、发送”，引擎和协作细项进入有摘要的配置菜单。非默认权限仍明确显示，不能为了简洁隐藏权限风险。保留 Echo 多引擎与多成员特色，但降低第一次发消息前需要理解的概念数量。

落点：frontend/src/components/workspace/chat-input-box/ChatComposer.tsx:1870、model-picker.tsx、coder-engine-control.tsx。
验收：桌面与窄屏不挤出主要发送操作；当前配置始终可查询；异常配置可直接修正。

### 4. P1：任务列表按“需要我做什么”排序

包内 app-primary-428a0a65766f.js:144282 附近定义 Priority，并明确描述 Needs input and unread chats first；同处还有更新时间、创建时间、手动排序。

Echo workspace-sidebar.tsx:198 使用 updated_at，并有按 updatedAt 排列的逻辑。建议增加可选“需要处理优先”，将待用户输入置顶，未读结果次之；完成记录安静保留。已有运行状态聚合不能直接等同于列表优先级。

落点：frontend/src/components/workspace/workspace-sidebar.tsx、frontend/src/core/threads/sidebar.ts。
验收：切换排序不丢失置顶/项目归属；用户阅读后清除未读；不因每个流式 token 更新而让列表跳动。

### 5. P1：运行中补充指令有可见去向，失败能恢复

queued-message-list-6971c0f01904.js:148 有“用户中断导致队列暂停”及 Resume；:427 起有发送失败提示、重试/编辑/删除指引。包内 local-conversation-turn 也有 steeringStatus 分支。

Echo 已有 chat-steer-button，不能说完全缺少中途补充。建议审查其与队列、停止、重试的衔接：输入框附近明确显示“立即补充”或“下一条执行”，失败保留原文，并提供直接修复动作。具体是否缺少完整队列状态机仍需单独行为测试。

落点：frontend/src/components/workspace/chat-input-box/ChatComposer.tsx:1994、frontend/src/core/realtime/。
验收：停止不会静默丢弃排队文字；失败重试不重复提交；补充指令的接收状态可见。

### 6. P1：阅读位置稳定，比动画丰富更重要

thread-scroll-layout-99b3ea3429c1.js 有 distanceFromBottomPx、wheelDistanceFromBottomPx、scrollTopPx、wheel 监听和底部回归判断；还有独立 footer padding 与“回到底部”入口。说明其滚动与输入框布局作为专门系统处理。

Echo message-list.tsx 已有锚点、滚动监听和 ResizeObserver。建议补行为验收，不贸然重写：用户上翻时停止跟随；在底部时新内容继续跟随；展开过程、加载图片与输入框增高时保持阅读位置。

落点：frontend/src/components/workspace/messages/message-list.tsx、相关滚动测试。
验收：流式输出、图片延迟加载、过程展开、窄屏输入框增高四种情形都不抢走阅读位置。

## 配色方面的结论

Codex CSS 将 surface、user-message、composer、execution-output 与 secondary/tertiary text 分开命名，而不是仅有一个背景色和一个主色。Echo 目前已改成纯白背景，继续收益更大的方向是维护语义层次：正文深色、辅助标签灰色、过程更轻、状态颜色仅表达真实状态。柔彩主题可保留品牌个性，无需把整体外观完全做成 Codex。

## 建议实施顺序

第一批：过程折叠 + 空面板默认策略。第二批：输入框渐进配置 + 任务优先级。第三批：补充/排队恢复与滚动场景验收。

这轮仅完成客户端资源分析和建议；未声称实现以上功能，也未从本机前端推断服务端或模型内部实现。

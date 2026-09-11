# Echo 前端完整走查记录

日期：2026-09-08。环境：本地前端 3310 / 后端 8310，已登录账号，Windows 内置浏览器。

本轮覆盖当前数据和权限下可到达的页面、菜单、设置分区及创建前窗口。主对话已较克制，优先要补齐的是滚动与焦点、跨模块导航、可信状态和错误恢复。没有改动业务代码。

本轮捕获 **289** 个屏幕状态，保留 **259** 个可复核记录（包括明确标注的错误状态），排除 **30** 个加载中、重复或错位记录；整理 **20** 项优化发现和 **3** 组功能阻塞。这些数量不是测试通过数。

[全部逐步截图和说明](<D:/echo agent/docs/audits/full-ui-2026-09-08/steps.md>) · [可筛选截图画廊](<D:/echo agent/docs/audits/full-ui-2026-09-08/gallery.html>) · [结构化证据清单](<D:/echo agent/docs/audits/full-ui-2026-09-08/accepted-manifest.json>)

## 逐项覆盖

|步骤|页面/流程|范围|当前健康度|
|---|---|---|---|
|1|对话与输入|输入插入菜单、权限、引擎、模型、模式、工作区、协作、侧栏、助手、历史任务、回放和五类右侧面板；800px 与 390px|入口可用，状态提示需优化|
|2|设置|账号、订阅与用量、通用、对话、模型、记忆、通知、编码、工具、浏览器自动化、桌面自动化、执行与安全、个人空间与安全、诊断、关于；API/Connector/多模型/重置确认窗口|15 类均已查看；滚动及深链接需修复|
|3|HUB 与插件|角色、应用、Skills；推荐/全部/已安装/远程 Agent；新建菜单、角色生成、团队、远程注册和角色详情|目录可达，技能详情和标识需优化|
|4|角色与 HUD|切换、档案、成长、雷达、技能树、基础配置、ARM、白名单、权限、路由和预算；手机布局|配置可达，头像及信息密度需优化|
|5|项目管理|列表空态、创建、成员高级配置；桌面和手机|空态和创建表单可达；已有项目流程未验证|
|6|设计画布|创作首页、指南、模型菜单、工作流/自由画布、节点菜单、设置/帮助/快捷键、资产、添加资产、技能详情、ComfyUI、环境和导入；手机布局|页面可达，浮层和窄屏需修复|
|7|叙事工坊|首页、能力面板、新建项目；手机布局|空态和创建窗口可达；实际创作未验证|
|8|模拟炒股|首页及当前部署的认证限制状态|当前认证部署阻塞|
|9|订阅与自动化|任务、已配置、历史、面板、新建自动化；手机布局|列表和创建表单可达；调度执行未验证|
|10|自进化与治理|实验、候选、部署、治理、策略、技能/模型/MCP、课程、框架、漂移、A/B、反射和运行设置；手机布局|面板可达；指标语义需优化|
|11|社区与集市|发现、信息流、评论、发布、集市、商品详情、上架；手机布局|可达；示例数据、封面和发布表单需优化|
|12|存储与知识|存储、知识图谱、记忆、Wiki；图片视频依赖另列|部分可达；存储及权限阻塞|
|13|渠道配置|总览、26 个独立渠道配置窗口、响应对象选择；手机布局|26 个窗口可达；未连接或保存|
|14|本机助手与桌面整理|设备/控制工作区、动作菜单、桌面整理；手机布局|只读检查；原生动作未执行|
|15|架构文档|目录 13 份文档入口、正文和图形；两份图示未稳定，单独列入限制|目录可达；Mermaid 缺字，2 份图示未验|
|16|可观测性与诊断|总览、事件、资源、系统；运行、流式、开关、建议、远程和不变量；诊断直达与手机布局|部分权限阻塞；窄屏布局需修复|
|17|反射规则|监控、编辑器、源码读取失败态|监控可达，编辑器文件读取阻塞|
|18|浏览器与桌面|独立桌面/浏览器、下载、历史、书签、更多、外部网页、AI 侧栏、编辑态、图标、文件夹、组件、主题、壁纸、娱乐、应用和设置；手机布局|入口可达；设置语义及窄屏浮层需修复|
|19|图片与视频|图片和视频索引的稳定错误状态|索引服务阻塞|
|20|公共入口与路由|介绍、条款、隐私、已登录下登录/注册跳转、无邀请团队入口、无 URL 网页应用、无效分享、15 条重定向别名|已登录跳转可达；设置深链接失败、分享错误态需优化|

## 优先修复顺序

1. 恢复核心配置和任务路径：F02、F03、F04，并排查 B01–B03 对应服务状态。
2. 修复功能语义与可读性：F01、F05、F06、F11、F12、F18。
3. 完成共用移动布局、弹窗与可访问性：F07–F10、F14、F16。
4. 收敛视觉密度、头像、封面和说明：F13、F15、F17、F19、F20。

P1 表示直接打断关键配置流程；P2 表示明显影响理解、操作或一致性。优先级是本轮体验判断，不是安全漏洞等级。

## 具体发现

### F01 · P2 · 桌面设置的“布局同步”指向重置布局

**观察：** 设置列出默认搜索、图标尺寸、打开方式、布局同步；源码按数组索引处理，第 4 项调用 onResetLayout。该函数已有重置确认对话框，并非单击立即清空。第 2 项实际切换编辑态，第 3 项打开主页，均与设置名称不一致。

**影响：** 用户以为在同步，却会进入重置流程。此次没有触发该按钮，也没有重置布局。

**建议：** 为每项设置绑定明确的独立行为；尚未实现的设置显示不可用及原因。重置布局单独命名，保留已有确认。

**验收：** 同步入口不再进入重置流程；重置入口明确可辨认；搜索、尺寸、打开方式能改变其所描述的偏好。

**证据强度：** 界面与完整回调源码交叉确认；未执行重置。

代码定位：[browser-home.tsx:1396](<D:/echo agent/frontend/src/components/browser/browser-home.tsx:1396>) · [browser-home.tsx:2885](<D:/echo agent/frontend/src/components/browser/browser-home.tsx:2885>) · [browser-home.tsx:3121](<D:/echo agent/frontend/src/components/browser/browser-home.tsx:3121>) · [zh-CN.ts:4724](<D:/echo agent/frontend/src/core/i18n/locales/zh-CN.ts:4724>)

证据：[234-browser-settings-pointer](<D:/echo agent/docs/audits/full-ui-2026-09-08/234-browser-settings-pointer.png>)

![浏览器桌面设置](<D:/echo agent/docs/audits/full-ui-2026-09-08/234-browser-settings-pointer.png>)

### F02 · P1 · API 接入使设置弹窗标题、关闭按钮滚出可视区

**观察：** 点击接入 API 后，外层设置容器也发生滚动，顶部标题和关闭按钮消失，底部出现大块空白。DOM 检查确认存在内外两层滚动；代码调用 scrollIntoView。

**影响：** 核心配置流程中容易迷失位置，取消或返回变得困难。

**建议：** 固定弹窗头部、底部，只让内容区滚动；以内容区为滚动目标；新增 API 使用清晰的局部表单层级。

**验收：** 桌面和 390px 下，进入表单、展开高级项、滚到底部时关闭和返回入口始终可达。

**证据强度：** 已复现；滚动链路已定位。

代码定位：[model-settings-page.tsx:1366](<D:/echo agent/frontend/src/components/workspace/settings/model-settings-page.tsx:1366>)

证据：[27-api-connect-dialog](<D:/echo agent/docs/audits/full-ui-2026-09-08/27-api-connect-dialog.png>) · [28-api-connect-form-bottom](<D:/echo agent/docs/audits/full-ui-2026-09-08/28-api-connect-form-bottom.png>)

![模型接入表单](<D:/echo agent/docs/audits/full-ui-2026-09-08/27-api-connect-dialog.png>)

### F03 · P1 · 目录选择器延迟失败后打断其他操作

**观察：** 系统选择请求等待很久后，回退窗口或失败提示在设置页出现；工作区输入框重新获得焦点。源码在 await 完成后直接开菜单并 focus，没有检查用户是否已离开该操作。

**影响：** 用户不能判断选择器是否仍在等待，迟到结果会抢焦点。

**建议：** 显示可取消的等待状态、限定等待时间；用请求代次或取消信号丢弃过期结果；浏览器缺少桥接时及时进入手动目录选择。

**验收：** 点选择后立即转去设置，不再弹出旧选择器或抢焦点；取消、失败、无桥接分别有稳定反馈。

**证据强度：** 浏览器流程已复现；原生系统弹窗未验证。

代码定位：[workdir-selector.tsx:513](<D:/echo agent/frontend/src/components/workspace/workdir-selector.tsx:513>) · [workdir-selector.tsx:533](<D:/echo agent/frontend/src/components/workspace/workdir-selector.tsx:533>)

证据：[13-workspace-selector-ready](<D:/echo agent/docs/audits/full-ui-2026-09-08/13-workspace-selector-ready.png>) · [196-mobile-dark-settings](<D:/echo agent/docs/audits/full-ui-2026-09-08/196-mobile-dark-settings.png>)

![工作区选择失败回退](<D:/echo agent/docs/audits/full-ui-2026-09-08/13-workspace-selector-ready.png>)

### F04 · P2 · 设置及 MCP 深链接跳转后没有打开设置

**观察：** /settings 与 /workspace/mcp 跳转到新任务页，稳定后仍没有设置弹窗。SettingsRoute 导航后用 setTimeout 发事件，组件卸载清理会取消定时器；设置弹窗另有路由变化关闭逻辑，存在时序竞争。

**影响：** 复制链接、旧入口和配置跳转无法稳定抵达目标设置。

**建议：** 通过路由状态或查询参数表达目标设置，目标页挂载后消费；避免依赖被卸载组件发出的瞬时事件。

**验收：** 冷启动、热导航、后退分别验证 /settings、/workspace/settings?section=models、/workspace/mcp，均打开正确分区。

**证据强度：** 失败已复现；时序原因属于源码支持的定位假设。

代码定位：[router.tsx:56](<D:/echo agent/frontend/src/router.tsx:56>) · [settings-dialog.tsx:201](<D:/echo agent/frontend/src/components/workspace/settings/settings-dialog.tsx:201>)

证据：[240-settings-deeplink-settled](<D:/echo agent/docs/audits/full-ui-2026-09-08/240-settings-deeplink-settled.png>)

![设置深链接最终状态](<D:/echo agent/docs/audits/full-ui-2026-09-08/240-settings-deeplink-settled.png>)

### F05 · P2 · Skills 提示可查看详情，但卡片没有详情入口

**观察：** 多张卡片说明为“打开详情查看技能内容”，名称和说明实际为静态内容，只提供安装按钮。手机上标题和描述还被单行截断。

**影响：** 安装前无法判断用途、依赖和具体内容。设计画布的技能已有详情，跨模块体验不一致。

**建议：** 增加卡片详情页或侧栏，展示用途、来源、权限、依赖和内容预览；保留独立安装按钮。

**验收：** 点击卡片或键盘 Enter 能打开详情；手机能读完整名称及说明；查看详情不会自动安装。

**证据强度：** 界面操作与源码确认。

代码定位：[cloud-skills-panel.tsx:210](<D:/echo agent/frontend/src/components/store/cloud-skills-panel.tsx:210>) · [display-value.ts:20](<D:/echo agent/frontend/src/core/utils/display-value.ts:20>)

证据：[67-skill-detail](<D:/echo agent/docs/audits/full-ui-2026-09-08/67-skill-detail.png>) · [203-skills-mobile](<D:/echo agent/docs/audits/full-ui-2026-09-08/203-skills-mobile.png>)

![67-skill-detail](<D:/echo agent/docs/audits/full-ui-2026-09-08/67-skill-detail.png>)

### F06 · P2 · 架构 Mermaid 图的节点文字丢失

**观察：** 图形和连线已出现，但节点无文字；DOM 中节点标签为空。共享渲染器经过 Mermaid 与 DOMPurify 处理，尚不能仅凭截图断定哪一步清掉了文字。

**影响：** 架构图无法传递流程含义。

**建议：** 核对渲染后、净化后的 SVG 标签内容与配置；提供失败后的源码视图，并保留安全净化。

**验收：** 当前架构图的中英文节点均可读；含 HTML 标签与纯 SVG 文本的样例都验证；不关闭安全过滤来修复。

**证据强度：** 缺字已复现；具体根因待调试。

代码定位：[mermaid-block.tsx:44](<D:/echo agent/frontend/src/components/workspace/messages/mermaid-block.tsx:44>) · [mermaid-block.tsx:74](<D:/echo agent/frontend/src/components/workspace/messages/mermaid-block.tsx:74>)

证据：[138-architecture-mermaid](<D:/echo agent/docs/audits/full-ui-2026-09-08/138-architecture-mermaid.png>)

![架构 Mermaid 图](<D:/echo agent/docs/audits/full-ui-2026-09-08/138-architecture-mermaid.png>)

### F07 · P2 · 部分窄屏页面缺少全局导航入口

**观察：** 390px 下渠道、本机助手、架构、可观测性页面看不到工作区侧栏或打开侧栏按钮；HUB 和对话有对应入口。架构正文按纵向堆叠，但目录很长。

**影响：** 用户进入这些页面后难以切回其他模块。

**建议：** 统一使用含移动导航按钮的工作区标题栏；开发工具页同样提供返回和模块切换。

**验收：** 390px 下任一页面都可在一次操作内打开全局导航，长目录不遮住正文入口。

**证据强度：** 截图及可访问树确认；未验证所有中间宽度。

代码定位：[workspace-container.tsx:5](<D:/echo agent/frontend/src/components/workspace/workspace-container.tsx:5>)

证据：[221-channels-mobile](<D:/echo agent/docs/audits/full-ui-2026-09-08/221-channels-mobile.png>) · [222-computer-mobile](<D:/echo agent/docs/audits/full-ui-2026-09-08/222-computer-mobile.png>) · [223-architecture-mobile](<D:/echo agent/docs/audits/full-ui-2026-09-08/223-architecture-mobile.png>) · [224-observability-mobile](<D:/echo agent/docs/audits/full-ui-2026-09-08/224-observability-mobile.png>)

![221-channels-mobile](<D:/echo agent/docs/audits/full-ui-2026-09-08/221-channels-mobile.png>)

### F08 · P2 · 可观测性窄屏页签与内容卡片重叠

**观察：** 四个页签换成两行，第二行侵入下方事件流卡片；首屏还堆叠了较长的介绍卡。

**影响：** 页签难点选，状态与正文层级不清晰。

**建议：** 按实际两行高度保留空间，检查 Tabs 公共样式和外层布局约束；折叠首次说明，优先展示当前状态。

**验收：** 390px、800px 下页签和内容无重叠，切换四个页签不引发布局跳动。

**证据强度：** 已复现；具体 CSS 冲突待定位。

代码定位：[page.tsx:203](<D:/echo agent/frontend/src/app/workspace/observability/page.tsx:203>)

证据：[224-observability-mobile](<D:/echo agent/docs/audits/full-ui-2026-09-08/224-observability-mobile.png>)

![手机宽度可观测性](<D:/echo agent/docs/audits/full-ui-2026-09-08/224-observability-mobile.png>)

### F09 · P2 · 画布浮层在窄屏被裁切并改变页面滚动

**观察：** 390px 的设置浮层右侧越界；打开节点或帮助菜单后，底部工具栏位置变化并露出大块空白。画布节点可平移本身不算缺陷。

**影响：** 设置项难读，用户容易失去当前画布位置。

**建议：** 浮层相对可视容器碰撞检测，必要时改底部面板；菜单使用独立覆盖层，不参与画布内容滚动。

**验收：** 390px 打开任意浮层，所有项及关闭操作可达，画布视点和滚动位置不变。

**证据强度：** 交互及截图确认。

证据：[85-design-node-menu](<D:/echo agent/docs/audits/full-ui-2026-09-08/85-design-node-menu.png>) · [212-canvas-settings-mobile](<D:/echo agent/docs/audits/full-ui-2026-09-08/212-canvas-settings-mobile.png>) · [213-canvas-help](<D:/echo agent/docs/audits/full-ui-2026-09-08/213-canvas-help.png>)

![85-design-node-menu](<D:/echo agent/docs/audits/full-ui-2026-09-08/85-design-node-menu.png>)

### F10 · P2 · 浏览器桌面控制面板按窗口而非容器计算宽度

**观察：** 窄屏浏览器内的主题、组件和应用面板右边缘被裁切。源码固定 360px 且 max-width 使用 100vw，而面板所在容器比整个窗口窄。

**影响：** 右侧操作和关闭区域可能在可视边界外。

**建议：** 用宿主容器宽度约束面板，窄屏改全宽抽屉；关闭按钮固定在可视区。

**验收：** 390px 嵌入视图中面板完整可见，目录可滚动，关闭按钮始终可点。

**证据强度：** 界面与尺寸约束源码确认。

代码定位：[browser-home.tsx:2910](<D:/echo agent/frontend/src/components/browser/browser-home.tsx:2910>)

证据：[226-browser-theme-ready](<D:/echo agent/docs/audits/full-ui-2026-09-08/226-browser-theme-ready.png>) · [227-browser-widget-catalog](<D:/echo agent/docs/audits/full-ui-2026-09-08/227-browser-widget-catalog.png>) · [230-browser-app-catalog](<D:/echo agent/docs/audits/full-ui-2026-09-08/230-browser-app-catalog.png>)

![226-browser-theme-ready](<D:/echo agent/docs/audits/full-ui-2026-09-08/226-browser-theme-ready.png>)

### F11 · P2 · 社区示例内容和互动计数缺少清楚标识

**观察：** 社区卡片评论数与打开后的少量评论不匹配。源码在列表为空时回退到 SEED，并为帖子合成 2–4 条默认评论；种子帖包含 88 条评论计数。不能把这些数据当成真实用户活跃度。

**影响：** 损害社区内容和指标的可信度。

**建议：** 示例内容标注演示；无真实数据时显示空态；真实互动计数与服务返回保持一致。

**验收：** 空库时不会出现未标记的模拟用户互动；卡片计数与实际评论数据一致或说明分页总量。

**证据强度：** 可见数据差异与源码确认。

代码定位：[community-data.ts:212](<D:/echo agent/frontend/src/components/workspace/community/community-data.ts:212>) · [community-data.ts:504](<D:/echo agent/frontend/src/components/workspace/community/community-data.ts:504>) · [community-data.ts:1110](<D:/echo agent/frontend/src/components/workspace/community/community-data.ts:1110>)

证据：[119-community](<D:/echo agent/docs/audits/full-ui-2026-09-08/119-community.png>) · [121-community-comments](<D:/echo agent/docs/audits/full-ui-2026-09-08/121-community-comments.png>)

![119-community](<D:/echo agent/docs/audits/full-ui-2026-09-08/119-community.png>)

### F12 · P2 · 未运行、已完成和估算评分的含义混淆

**观察：** 新任务的右侧面板已显示“已完成”；产物空态出现协作现场文案。自进化没有实验数据时仍展示高完成度指标；可观测性有竞品估算分数与真实对比表述并列。

**影响：** 用户难判断当前任务是否运行成功，或数字代表能力覆盖还是实际效果。

**建议：** 任务状态由真实生命周期驱动；空态对应当前面板；分开实现覆盖率、运行成功率、离线估算，标注口径和样本。

**验收：** 新任务显示尚未开始；无实验不显示已验证效果；每项评分能看到来源、样本和时间。

**证据强度：** 状态和文案可见；不评价算法实际能力。

证据：[15-right-panel](<D:/echo agent/docs/audits/full-ui-2026-09-08/15-right-panel.png>) · [18-artifact-panel](<D:/echo agent/docs/audits/full-ui-2026-09-08/18-artifact-panel.png>) · [103-evolution](<D:/echo agent/docs/audits/full-ui-2026-09-08/103-evolution.png>) · [141-observability-overview](<D:/echo agent/docs/audits/full-ui-2026-09-08/141-observability-overview.png>) · [145-diagnostics-streaming](<D:/echo agent/docs/audits/full-ui-2026-09-08/145-diagnostics-streaming.png>)

![15-right-panel](<D:/echo agent/docs/audits/full-ui-2026-09-08/15-right-panel.png>)

### F13 · P2 · 部分角色头像缺少稳定的加载失败替代

**观察：** 部分角色在切换列表或默认成员位置出现空白头像；其他角色卡片可正常显示头像，不能归纳为全部头像失效。

**影响：** 角色辨认和成员选择不够稳定。

**建议：** 统一头像组件的加载失败图像或姓名缩写、固定尺寸与替代文字。

**验收：** 断图、慢加载与无头像三种状态都能辨认角色，列表不跳动。

**证据强度：** 特定状态已观察；资产故障原因未定位。

证据：[68-agent-switcher](<D:/echo agent/docs/audits/full-ui-2026-09-08/68-agent-switcher.png>) · [207-project-create-mobile](<D:/echo agent/docs/audits/full-ui-2026-09-08/207-project-create-mobile.png>)

![角色切换菜单](<D:/echo agent/docs/audits/full-ui-2026-09-08/68-agent-switcher.png>)

### F14 · P2 · 部分纯图标按钮和开关缺少可访问名称

**观察：** 远程 Agent 顶部两枚图标、资产视图切换、桌面整理开关等在可访问树中缺少明确名称；部分输入依赖占位文字。

**影响：** 键盘和读屏用户无法准确辨认操作；悬停提示也不一定能被触屏用户发现。

**建议：** 补全 aria-label、关联 label 和状态说明；统一图标按钮可点击区域及可见焦点。

**验收：** Tab 顺序合理，每个控件能读出用途和状态；在触屏上不依赖悬停理解操作。

**证据强度：** 可访问树抽查；不是完整 WCAG 合规认证。

证据：[64-remote-agent](<D:/echo agent/docs/audits/full-ui-2026-09-08/64-remote-agent.png>) · [86-design-assets](<D:/echo agent/docs/audits/full-ui-2026-09-08/86-design-assets.png>) · [130-channels](<D:/echo agent/docs/audits/full-ui-2026-09-08/130-channels.png>) · [136-desktop-organizer](<D:/echo agent/docs/audits/full-ui-2026-09-08/136-desktop-organizer.png>)

![64-remote-agent](<D:/echo agent/docs/audits/full-ui-2026-09-08/64-remote-agent.png>)

### F15 · P2 · 错误和功能说明需要统一产品语言

**观察：** 面向普通用户的入口夹杂工具 ID、API 路径、环境变量与英文错误；无效分享页只有“重新加载”，没有返回工作区。开发者架构文档保留术语是合理的。

**影响：** 用户知道失败了，却不知道下一步可做什么。

**建议：** 主文案说明当前状态和可执行下一步，把原始诊断放进展开详情；分享失效时提供返回入口。

**验收：** 主要错误页有中文原因、恢复或退出路径；技术明细仍可复制用于排障。

**证据强度：** 文案与恢复入口已检查。

证据：[05-insert-commands](<D:/echo agent/docs/audits/full-ui-2026-09-08/05-insert-commands.png>) · [118-governance-runtime-bottom](<D:/echo agent/docs/audits/full-ui-2026-09-08/118-governance-runtime-bottom.png>) · [133-computer](<D:/echo agent/docs/audits/full-ui-2026-09-08/133-computer.png>) · [142-observability-resources](<D:/echo agent/docs/audits/full-ui-2026-09-08/142-observability-resources.png>) · [242-share-invalid](<D:/echo agent/docs/audits/full-ui-2026-09-08/242-share-invalid.png>)

![05-insert-commands](<D:/echo agent/docs/audits/full-ui-2026-09-08/05-insert-commands.png>)

### F16 · P2 · 长表单需要统一滚动和字段层级

**观察：** 成员高级配置出现内外滚动，手机上底部提交区没有在此次截图中确认可达；资产及社区表单有较多占位提示，层级弱。

**影响：** 填写和取消成本偏高，字段一旦输入后提示消失。

**建议：** 统一弹窗头部、单一内容滚动区和底部操作；持久显示字段名，将高级配置渐进展开。

**验收：** 最长表单在 390px 下能明确到达取消与提交；聚焦末尾字段不遮挡操作。

**证据强度：** 嵌套滚动已观察；成员表单最终提交区需修复后专测。

证据：[79-project-members](<D:/echo agent/docs/audits/full-ui-2026-09-08/79-project-members.png>) · [87-design-add-asset](<D:/echo agent/docs/audits/full-ui-2026-09-08/87-design-add-asset.png>) · [122-community-publish](<D:/echo agent/docs/audits/full-ui-2026-09-08/122-community-publish.png>) · [125-market-create](<D:/echo agent/docs/audits/full-ui-2026-09-08/125-market-create.png>) · [208-project-members-bottom](<D:/echo agent/docs/audits/full-ui-2026-09-08/208-project-members-bottom.png>)

![79-project-members](<D:/echo agent/docs/audits/full-ui-2026-09-08/79-project-members.png>)

### F17 · P2 · 部分入口的名称承诺超过实际行为

**观察：** 设计指南入口目前只弹出简短提示；无待审项仍显示审核全部；“添加小组件”直接新增默认组件，用户可能以为会打开目录。

**影响：** 点击后的反馈与预期不符，增加试错。

**建议：** 指南打开完整帮助；空批处理入口禁用；组件入口明确区分浏览组件与新增默认组件。

**验收：** 每个按钮的结果符合标题；空批处理不能提交；创建行为在点击前可预期。

**证据强度：** 已观察；审计误新增的默认组件已删除撤回。

证据：[81-design-guide](<D:/echo agent/docs/audits/full-ui-2026-09-08/81-design-guide.png>) · [82-design-model-guide](<D:/echo agent/docs/audits/full-ui-2026-09-08/82-design-model-guide.png>) · [111-governance-mcp](<D:/echo agent/docs/audits/full-ui-2026-09-08/111-governance-mcp.png>) · [166-browser-widget-menu](<D:/echo agent/docs/audits/full-ui-2026-09-08/166-browser-widget-menu.png>)

![81-design-guide](<D:/echo agent/docs/audits/full-ui-2026-09-08/81-design-guide.png>)

### F18 · P2 · 历史工具详情与预览输出的关联不清楚

**观察：** 历史工具明细可展开，但预览最终显示 no_actions_recorded；用户无法明确知道该工具是否生成浏览器操作、结果在哪。未将预览加载中的截图判为故障。

**影响：** 执行过程难复核，容易将空浏览器预览误解为工具失败。

**建议：** 按工具结果类型展示正文、文件、网页和操作回放；无浏览器操作时给出对应说明和原始结果入口。

**验收：** 历史 fetch、聚合与浏览器操作各自打开正确结果视图；无回放时说明原因。

**证据强度：** 当前历史记录的体验已复现；不断言所有工具回放失败。

证据：[176-thread-replay](<D:/echo agent/docs/audits/full-ui-2026-09-08/176-thread-replay.png>) · [179-preview-final](<D:/echo agent/docs/audits/full-ui-2026-09-08/179-preview-final.png>) · [180-thread-tool-details](<D:/echo agent/docs/audits/full-ui-2026-09-08/180-thread-tool-details.png>)

![176-thread-replay](<D:/echo agent/docs/audits/full-ui-2026-09-08/176-thread-replay.png>)

### F19 · P2 · 跨模块的视觉密度和命名仍不一致

**观察：** 主对话已较克制，但创建角色、设计、诊断等页面仍有不同的卡片密度与标题尺度；侧栏“订阅”进入“自动化”，同一功能有多个称呼。

**影响：** 切换模块时需要重新理解页面层级，整合感不足。

**建议：** 沿用现有主题统一页面标题、间距、表单尺寸、空态和错误组件；确定面向用户的功能名称，技术别名放说明中。

**验收：** 对照相同视口检查各模块首屏，主操作、标题、面包屑和表单层级一致。

**证据强度：** 设计判断；不建议为统一而重做所有页面。

证据：[01-new-task](<D:/echo agent/docs/audits/full-ui-2026-09-08/01-new-task.png>) · [80-design](<D:/echo agent/docs/audits/full-ui-2026-09-08/80-design.png>) · [98-intelligence](<D:/echo agent/docs/audits/full-ui-2026-09-08/98-intelligence.png>) · [134-computer-controls](<D:/echo agent/docs/audits/full-ui-2026-09-08/134-computer-controls.png>) · [187-public-about](<D:/echo agent/docs/audits/full-ui-2026-09-08/187-public-about.png>) · [241-agent-create-route](<D:/echo agent/docs/audits/full-ui-2026-09-08/241-agent-create-route.png>)

![新任务首屏](<D:/echo agent/docs/audits/full-ui-2026-09-08/01-new-task.png>)

### F20 · P2 · 社区与集市的大封面和失败图片占用过多空间

**观察：** 大封面把标题与正文推到较低位置；多个失败封面仍保留大面积空框，手机上更明显。

**影响：** 内容浏览效率低，首屏缺少判断价值所需的信息。

**建议：** 限制封面比例和最大高度；图片失败时收缩或使用与内容有关的替代；标题、摘要和来源置于稳定区域。

**验收：** 断图时首屏仍可识别条目；390px 下标题和主要操作无需跨多屏寻找。

**证据强度：** 已观察稳定失败占位；未把壁纸待加载状态算作断图。

证据：[120-community-feed](<D:/echo agent/docs/audits/full-ui-2026-09-08/120-community-feed.png>) · [124-market-detail-ready](<D:/echo agent/docs/audits/full-ui-2026-09-08/124-market-detail-ready.png>) · [220-community-mobile](<D:/echo agent/docs/audits/full-ui-2026-09-08/220-community-mobile.png>)

![120-community-feed](<D:/echo agent/docs/audits/full-ui-2026-09-08/120-community-feed.png>)

## 功能阻塞，不能记为通过

### B01 · 历史任务恢复与终端连接受阻

历史正文可读取，但出现连接恢复失败；终端明确显示连接失败。未重试执行或发送消息，因此本轮不能验证模型响应、任务续跑和终端命令。需结合运行日志定位服务状态。

[175-existing-thread](<D:/echo agent/docs/audits/full-ui-2026-09-08/175-existing-thread.png>) · [184-terminal](<D:/echo agent/docs/audits/full-ui-2026-09-08/184-terminal.png>)

![历史研究任务](<D:/echo agent/docs/audits/full-ui-2026-09-08/175-existing-thread.png>)

### B02 · 存储、图片及视频库依赖不可用

存储显示 octopus-storage 依赖问题，图片和视频索引出现服务 502。当前只能检查错误状态，不能验证真实文件浏览、上传和预览。

[126-storage](<D:/echo agent/docs/audits/full-ui-2026-09-08/126-storage.png>) · [169-photos-ready](<D:/echo agent/docs/audits/full-ui-2026-09-08/169-photos-ready.png>) · [170-media-ready](<D:/echo agent/docs/audits/full-ui-2026-09-08/170-media-ready.png>)

![126-storage](<D:/echo agent/docs/audits/full-ui-2026-09-08/126-storage.png>)

### B03 · 认证、管理员权限或运行配置限制

模拟炒股在当前认证部署被限制；知识图谱及部分诊断返回管理员权限问题；反射监控有 7 条规则，编辑器无法找到规则文件。没有修改权限、认证或运行配置来绕过这些限制。

[96-paper-trading](<D:/echo agent/docs/audits/full-ui-2026-09-08/96-paper-trading.png>) · [127-knowledge](<D:/echo agent/docs/audits/full-ui-2026-09-08/127-knowledge.png>) · [140-observability-events](<D:/echo agent/docs/audits/full-ui-2026-09-08/140-observability-events.png>) · [142-observability-resources](<D:/echo agent/docs/audits/full-ui-2026-09-08/142-observability-resources.png>) · [152-reflex-source-blocked](<D:/echo agent/docs/audits/full-ui-2026-09-08/152-reflex-source-blocked.png>)

![96-paper-trading](<D:/echo agent/docs/audits/full-ui-2026-09-08/96-paper-trading.png>)

## 路由跳转复核

|输入路径|实际落点|结果|
|---|---|---|
|`/`|`/workspace/realtime/new`|跳转方向符合当前路由定义|
|`/workspace`|`/workspace/realtime/new`|跳转方向符合当前路由定义|
|`/workspace/realtime`|`/workspace/realtime/new`|跳转方向符合当前路由定义|
|`/plugins`|`/workspace/agents?surface=chat&tab=plugins`|跳转方向符合当前路由定义|
|`/workspace/skills`|`/workspace/agents?surface=chat&tab=skills`|跳转方向符合当前路由定义|
|`/workspace/plugins`|`/workspace/agents?surface=chat&tab=plugins`|跳转方向符合当前路由定义|
|`/workspace/store`|`/workspace/agents?surface=chat`|跳转方向符合当前路由定义|
|`/workspace/workflows`|`/workspace/agents?surface=chat&tab=skills`|跳转方向符合当前路由定义|
|`/workspace/nas`|`/workspace/storage?surface=company`|跳转方向符合当前路由定义|
|`/workspace/database`|`/workspace/storage?surface=company`|跳转方向符合当前路由定义|
|`/workspace/replay`|`/workspace/observability`|跳转方向符合当前路由定义|
|`/workspace/mobile`|`/workspace/computer`|跳转方向符合当前路由定义|
|`/workspace/mcp`|`/workspace/realtime/new`|未打开应有设置弹窗（F04）|
|`/settings`|`/workspace/realtime/new`|未打开应有设置弹窗（F04）|
|`/workspace/browser`|`/browser`|跳转方向符合当前路由定义|

## 渠道窗口明细

- 设置 Telegram 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-bot-config.png>)
- 设置 Slack 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-1.png>)
- 设置 Discord 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-2.png>)
- 设置 Signal 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-3.png>)
- 设置 WhatsApp 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-4.png>)
- 设置 Mattermost 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-5.png>)
- 设置 Matrix 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-6.png>)
- 设置 LINE 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-7.png>)
- 设置 SimpleX 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-8.png>)
- 设置 IRC 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-9.png>)
- 设置 Twitch 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-10.png>)
- 设置 微信 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-11.png>)
- 设置 钉钉 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-12.png>)
- 设置 飞书 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-13.png>)
- 设置 企业微信 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-14.png>)
- 设置 QQ 机器人 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-15.png>)
- 设置 腾讯元宝 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-16.png>)
- 设置 Email 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-17.png>)
- 设置 SMS (Twilio) 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-18.png>)
- 设置 Home Assistant 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-19.png>)
- 设置 ntfy 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-20.png>)
- 设置 Microsoft Teams 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-21.png>)
- 设置 BlueBubbles (iMessage) 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-22.png>)
- 设置 Webhooks 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-23.png>)
- 设置 Google Chat 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-24.png>)
- 设置 Open WebUI 机器人：已打开字段配置，未连接或保存。[截图](<D:/echo agent/docs/audits/full-ui-2026-09-08/131-channel-25.png>)

## 验证边界与恢复

- 本轮检查菜单、选项、表单和最终可见状态，没有发任务、重跑历史任务、安装/卸载插件、接入外部账号、发布、下单、部署或创建业务数据。插件权限确认链路不能保证只读：源码中部分市场安装按钮会直接安装，故未点击；需要后续专门验证安装与授权完整闭环。
- 已登录态下登录/注册会回到工作区；未退出当前账号。因此未验证登录表单、密码恢复、新用户引导和注册提交。无有效分享或团队邀请 token，仅验证缺失/失效状态。
- 项目和叙事没有现成数据可进入编辑及详情；未为审计创建项目。ComfyUI 的本地依赖不可用，未跑生成。存储、模型任务恢复、交易和管理员数据按 B01–B03 记录。
- Windows 原生桌面窗口控制、macOS/Linux 原生边框、系统目录选择器、原生权限和真实触屏设备未实测；此轮结论只覆盖浏览器及其回退界面。
- 架构 Cerebrum 与 Chromatophores 已访问正文，但对应两张图示截图未稳定；这两份文档的图示渲染未验证。未把加载中或抓错窗口的图片作为完成证据。
- 视口包括 1280×720、800×700、390×844，以及恢复后的实际浏览器尺寸；按每张 PNG 的真实尺寸记录。深浅主题做了代表页面检查，并非所有窗口均穷举两种主题及所有宽度。
- 可访问性通过可见焦点、部分 Escape 行为和可访问树抽查；未做完整读屏、色差仪或 WCAG 合规测试。
- 临时主题已恢复为跟随系统/蔷薇粉/舒适 15px；画布恢复工作流及创作首页；审计误新增的默认小组件已删除，仅关闭审计新开的外部网页。原用户浏览器标签未被操作。视口覆盖已重置。
- 只新增本审计目录的文档与截图，没有改动应用代码、重启服务或提交代码。已有工作区修改保留。

## 证据排除清单

- 13-workspace-selector：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 17-preview-panel：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 17-preview-panel-ready：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 23-settings-usage：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 25-settings-conversation-bottom：重复或名称不准确的中间截图，已有其他有效证据。
- 41-reset-confirmation：重复或名称不准确的中间截图，已有其他有效证据。
- 50-model-connectors：目标窗口未真正打开或名称与实际视图不一致；后续已补拍对应实际入口。
- 54-multi-model：目标窗口未真正打开或名称与实际视图不一致；后续已补拍对应实际入口。
- 54-multi-model-form：目标窗口未真正打开或名称与实际视图不一致；后续已补拍对应实际入口。
- 62-plugins-all：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 63-plugins-installed：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 89-design-skill-detail：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 99-subscriptions-configured：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 100-subscriptions-history：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 124-market-detail：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 139-architecture-cerebrum：正文已访问，但截图内代码或图示仍未稳定；不将该两份文档的图示渲染算作通过。
- 139-architecture-chromatophores：正文已访问，但截图内代码或图示仍未稳定；不将该两份文档的图示渲染算作通过。
- 154-desktop-local-apps：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 160-browser-extensions：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 161-browser-ai：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 167-browser-themes：目标窗口未真正打开或名称与实际视图不一致；后续已补拍对应实际入口。
- 168-browser-home-settings：目标窗口未真正打开或名称与实际视图不一致；后续已补拍对应实际入口。
- 169-photos：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 177-thread-tools：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 181-tool-output：瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。
- 186-project-space：目标窗口未真正打开或名称与实际视图不一致；后续已补拍对应实际入口。
- 199-model-connectors-dark：目标窗口未真正打开或名称与实际视图不一致；后续已补拍对应实际入口。
- 231-browser-settings：目标窗口未真正打开或名称与实际视图不一致；后续已补拍对应实际入口。
- 232-browser-settings-desktop：目标窗口未真正打开或名称与实际视图不一致；后续已补拍对应实际入口。
- 233-browser-settings-ready：目标窗口未真正打开或名称与实际视图不一致；后续已补拍对应实际入口。

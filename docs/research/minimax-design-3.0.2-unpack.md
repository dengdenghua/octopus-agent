# MiniMax Design 3.0.2 解包与 Octopus 迁移结论

日期：2026-08-23  
样本：`/Applications/MiniMax Design.app`（macOS arm64）

> 本文只记录可验证的产品结构与工程模式。Octopus 复用自身设计系统、数据模型和执行基座，不复制 MiniMax 的品牌资产或专有代码。

## 1. 产品不是“一个画板”

MiniMax Design 的核心是一个以画布为主视图的创作操作系统：

1. **画布层**：自由画布与工作流双模式，共享节点、资产与视口。
2. **能力层**：Agent、Skill、Plugin、媒体模型与 ComfyUI 工作流均可成为画布能力。
3. **资产层**：图片、视频、音频、文本、文件、表格等均有稳定资产身份和依赖关系。
4. **执行层**：节点关系转成可执行任务，运行结果回写为新资产和新节点。
5. **工作区层**：画布、聊天、文件、版本、插件状态都绑定到 workspace，而不是散落在单次会话里。

## 2. 解包证据

### 应用构成

- `app.asar`：约 43 MB，Electron 主进程与 React 渲染器。
- `gateway`：约 50 MB，本地 API、SQLite 和资产服务。
- `opencode`：约 138 MB，Agent 执行基座。
- `bundled-plugins`：约 43 MB，内置网页插件。
- `project-templates`：约 80 MB，工作区模板。
- `ffmpeg`：媒体处理运行时。

### 无限画布

渲染器主包使用 React Flow，关键结构包括：

- `CanvasMode.Freeform` / `CanvasMode.Workflow`
- 节点类型：Image、Video、Audio、Text、File、Placeholder、Table、Group、Sticker
- 可视区域裁剪：`onlyRenderVisibleElements`
- 背景：dots / grid / solid
- MiniMap、边隐藏、框选、手型拖拽、滚轮缩放、节点连线
- 快捷键：N 添加、V 选择、H 手型、C 评论、M 小地图、F1 帮助
- 自动整理：网格、横向、纵向，并支持按连接或媒体类型排序
- 自由模式和工作流模式分别保存节点位置

### 持久化与防护

- 画布 API：`/api/canvas`、`/api/canvas/add-node`、`/api/canvas/search`
- 通过 revision header 处理并发保存。
- 有破坏性保存和非法保存拒绝码，避免 Agent 错误覆盖整张画布。
- 资产关系单独建表，支持输入顺序、操作类型、父子来源和软删除恢复。
- 文本文档采用内容寻址版本库，版本属于资产而不是节点。

### 插件与技能

- Skill API 同时覆盖运行时、本地、市场、安装、卸载、白名单和 fork。
- Plugin manifest 包含多语言名称、描述、标签、入口、显示模式、尺寸、按需 Skill 和 Agent methods。
- 插件节点状态不再塞进画布 JSON，而是存入 workspace SQLite 的节点级 KV：
  `plugin_node_storage_scopes` + `plugin_node_storage_entries`。
- 内置示例包括 ComfyUI、Clip Studio 和 3D 导演台；插件既是 UI，也可以向 Agent 暴露结构化方法。

## 3. 值得学习的关键决策

### 双模式共用数据

自由画布用于探索、参考收集和并行创作；工作流用于表达依赖与执行顺序。两者不应成为两个互相跳转的产品，也不应复制两份节点。

### 资产先于消息

图片或文件不是聊天附件的临时副产物，而是带身份、依赖、版本和来源的工作区资产。聊天只是创建、解释和调度资产的入口之一。

### 插件节点是隔离运行单元

插件拥有独立 manifest、UI、方法和存储空间。画布只保留引用与布局，插件数据按节点隔离并设置配额，能显著降低画布保存成本与故障半径。

### Agent 写画布必须有门禁

Agent 可新增和修改节点，但保存应带 revision，并拒绝大面积误删。用户编辑、Agent 编辑与后台生成需要统一冲突模型。

## 4. Octopus 对应设计

| MiniMax Design | Octopus 基座                        |
| -------------- | ----------------------------------- |
| Workspace      | 项目 + 项目群 + 工作目录            |
| Agent          | 白幽灵角色与云端职业角色            |
| Skill          | 现有 `/api/skills` 与角色技能包     |
| Plugin         | 现有 PluginHub / Codex Plugin / MCP |
| Workflow run   | 实时会话执行、团队模式与项目里程碑  |
| Asset graph    | 本地数据库、工作区文件、产物面板    |
| Canvas         | 新增 Octopus Design 双模式画布      |

## 5. 落地阶段

### M1：平台骨架（已开始）

- 新增 `/workspace/design` 与侧边栏入口。
- 自由画布 / 工作流双模式。
- 无限平移、缩放、节点拖拽、连线、适应视口、自动整理。
- 接入真实本地 Skill / Plugin 列表，点击即可生成能力节点。
- 画布本地持久化。
- “交给 AI 执行”将画布编译成任务，进入现有实时执行基座。

### M2：项目与资产（进行中）

- [x] 项目详情提供“创作画布”入口，画布按 project id 隔离持久化并显示项目归属。
- [x] 项目画布保存到后端共享文档，带 revision 乐观锁、原子写入、项目权限作用域和 2 MB 上限。
- [ ] 项目群直接展示同一 Canvas document，并支持实时多人光标与增量合并。
- 将工作区文件、消息产物和媒体素材拖入画布。
- 运行结果回写输出节点，并保留来源边。
- 保存画布版本和撤销历史。

### M3：可执行编排

- 节点端口、条件分支、并发、重试和人工确认。
- Agent / Skill / Plugin 参数面板。
- 画布 revision、冲突合并、破坏性保存保护。
- 运行状态、耗时、成本与错误沿节点和边可视化。

### M4：插件工作台

- 插件 manifest 声明 editor surface、尺寸、方法与按需技能。
- 插件 iframe/webview 沙箱和权限门禁。
- 节点级 KV 存储、配额和迁移。
- ComfyUI、3D 导演台、视频剪辑等垂类工作台接入。

## 6. 原生视觉走查记录

本次直接操作 MiniMax Design 3.0.2，而不是只读代码。关键尺寸与交互如下：

- 创作首页使用点阵无限画布背景，品牌区居中；主输入器约 760 px 宽、24 px 圆角，模型与 Skill 入口位于输入器底部，下面直接承接项目选择、胶囊分类和四列案例卡。
- 一级侧栏宽约 264 px；画布占主区域，对话面板默认约 300 px。
- 工作区支持四种布局：对话 + 画布、对话在左、仅对话、仅画布，均在当前页面内切换。
- 画布为白色点阵背景；底部中央是紧凑工具胶囊，右上是视口控制胶囊。
- 添加节点是约 330 px 的按需菜单，而不是常驻能力库。原生入口包括文本、表格、图片、视频、音频、3D 导演台、视频剪辑与 ComfyUI 工作流。
- 节点设置、项目资产和帮助都按需出现；常态画布尽量不被面板占用。
- Skill 与 ComfyUI 使用相同的市场页范式：标题和一句说明、主操作、分类/搜索、四列视觉卡片。
- Skill 市场不是单层卡片库：顶部为“Skill / 我的 Skill”，下方依次是官方精选、用户精选与其他 Skill；卡片悬浮出现详情和下载动作，并显示官方认证与下载量。实机可见的官方精选覆盖 3D 动画、极简产品广告、纸拼贴、微表情、FPV、多语言配音、B-roll、数字产品宣传与动态海报等。
- ComfyUI 市场使用“精选工作流 / 我的工作流”双标签与四列模板卡。每张模板有预览、说明、来源和下载动作；导入或新建后仍在 Design 当前工作区打开，不跳到外部产品。
- 资产中心以角色、场景、风格包、道具和自定义为稳定分类，同时提供网格/列表视图。

### 6.1 主包视觉 token（3.0.2）

从 `app.asar/out/renderer/assets/index-BGYdCymP.css` 可直接验证：

- 浅色/深色画布底色分别为 `#fafafa` / `#0a0a0a`。
- 节点底色分别为 `#ffffff` / `#1a1a1a`，边框为 `#e3e3e3` / `#4a4a4a`。
- 媒体节点外圆角 16 px、内圆角 14 px；主控件背景为白色/`#1a1a1a`。
- 普通连线为 `#c4c4c4` / `#525252`，流程高亮为 `#8B72FF`，光晕为 `#C996FF`。
- 面板阴影为 `0 2px 5px`；菜单阴影为 `0 8px 32px` + `0 2px 8px`，比常见的重浮层更克制。
- 首页输入框半径 24 px、编辑区最小高度 90 px；场景快捷标签高 52 px、最小宽 148 px、圆角 14 px。

Octopus Design 的画布底色、节点圆角/边框、连线、控制胶囊和菜单阴影已按这些 token 校正。

这些结论已用于重构 Octopus Design：移除左右常驻能力库和检查器，换成按需节点菜单、浮动节点设置、项目资产面板和四种工作区布局。

## 7. 解包能力与许可边界

### 可验证能力

- 创作 Skill：动画游戏 PV、品牌广告、电影片头、音乐 MV、教育视频、视觉设计、KOC 视频、UI 动效、视频拆解。
- 工作流：广告 TVC、短剧、通用视频、MV，以及共享资产/音频/字幕/视频合并管线。
- 3D 导演台方法：场景读取与批量编辑、程序化模型生成与对比、多视角快照、诊断、相机路径与动作 DSL。
- 剪辑方法：项目读取/编辑/预览/历史/快照/诊断，覆盖轨道、片段、字幕、转场、效果和调色。
- ComfyUI：完整节点编辑器、本地后端连接、工作流导入和运行队列。

当前方法级覆盖（以解包 manifest 为证据，不把相似命名算作完成）：

| 插件 | 已有真实闭环 | 仍未完成 |
|---|---|---|
| 3D 导演台 | `scene.get/edit/history/snapshot/diagnostics`、安全声明式 `model.generate/capture/compare`、`motion.read`、`campath.read` | 不执行 MiniMax 的任意 JavaScript 模型代码；改用可审计声明式几何 |
| AI 剪辑工坊 | `project.get/edit/view/history/snapshot/diagnostics`，含真实媒体抽帧、真实音频静音分析与波纹切除、字幕与基础效果合成、范围编辑、SRT、转场和调色 | 完整转场中间态和全部高级效果合成 |
| ComfyUI | 本地状态、模型/扩展只读盘点、`object_info` 动态节点规格、工作流列表/读取/导入、原生 API-prompt 节点编辑、坐标与 revision 持久化、按 ID 排队、结果轮询与输出预览 | 托管后端安装、依赖自动下载与版本更新 |

“仍未完成”项保留为明确验收缺口；不以结构 JSON、占位图、静态模板或自动下载未知模型代替。

### 迁移规则

- MiniMax 自有 Skill 文本、工作流文本和 3D 插件未提供可分发许可证，因此只迁移能力结构与交互范式，不复制源码或提示词。
- Clip Studio 包附带 OpenReel MIT 许可。Octopus 当前先提供原创轻量剪辑插件，并保留后续对接 OpenReel 上游的兼容方向；未复制解包产物。
- ComfyUI 采用本地服务桥接：只允许 `localhost` / loopback 地址，支持状态探测、工作流 JSON 持久化和队列提交，不自动下载模型权重。
- 大模型资源可能达到约 40 GB，必须由用户明确选择后再下载，不能作为应用默认迁移内容。

## 8. 当前已落地

- 画布视觉结构与工作区布局已按原生走查结果重构。
- 节点菜单已覆盖文本、表格、图片、视频、音频、3D 导演台、视频剪辑、ComfyUI 和交付物。
- 30 个 Octopus 原创创作 Skill 已进入 `all_skills`。在原有 19 类基础上，按当前应用走查补齐多模态视频提示词、拼贴科普、唇部彩妆广告、丝印插画、线条图解、躲避游戏、点阵品牌字效、数字产品宣传片、品牌流线 MG、实景手绘显影和 IP 潮玩六宫格；全部通过 Skill 结构校验。
- Skill 市场已按实机结构加入分类、搜索、市场/已安装标签、四列卡片、官方标记、悬浮详情与加入画布动作。
- 新增本地 ComfyUI 桥接 API：状态、内置/用户工作流列表、工作流详情、导入、版本化保存和运行队列。内置三份只使用 ComfyUI 核心节点的原创模板：基础文生图、参考图重绘和潜空间高清放大；模型文件仍由用户本机选择。
- Design 内置深色无限节点工作台：可拖动节点、编辑参数、建立/解除连线、新增/删除节点、保存画布坐标并直接提交队列；在线时从本机 `object_info` 读取真实节点目录，离线时降级到核心节点；默认不再依赖离线时空白的 iframe，同时保留切换本机 ComfyUI 原生界面的入口。
- ComfyUI 市场明确区分“已内置”和“需依赖”：三份核心模板可直接导入，其余七类高级工作流仅作为能力目录展示，在本地模型或扩展就绪前不会伪装成可运行模板。
- 项目详情已接入项目专属 Design 入口；同一浏览器中的不同项目使用独立画布存储，标题栏持续显示项目归属并可返回项目管理。
- 项目画布现以本地存储作为离线缓存，并自动同步到 `/api/design/projects/{project_id}/canvas`；标题栏显示载入、保存、已同步、冲突或仅本地状态。后端以 revision 拒绝静默覆盖其他成员的新版本。
- 3D 导演台、AI 剪辑工坊和 ComfyUI 桥接均已提供 PluginHub manifest，可在插件市场被发现；三个插件同时注册 Agent 可发现的结构化 Skill，不再只有网页入口。
- 新增内置 AI 剪辑工坊插件：本地媒体预览、三轨编排、字幕片段与项目 JSON 导出。
- AI 剪辑工坊新增 `project.get/edit/history/view/diagnostics` 五类真实接口；批量操作原子提交，失败整批回滚，支持撤销/重做、轨道/媒体/字幕/片段/标记操作与黑场、重叠诊断。内嵌编辑器已读取同一项目并展示 Agent 写入的时间线。
- 剪辑原子操作继续覆盖到可实际编排的范围：复制片段、关闭间隙、波纹删除、范围切除、SRT 导入、统一字幕样式、转场、效果与调色；诊断新增短片段、媒体丢失和字幕越界。未实现依赖真实音频分析的“自动剪静音”，也未把静态占位图伪装成快照渲染。
- 剪辑 `project.snapshot` 已改为真实媒体渲染：PyAV 定位视频源帧，Pillow 完成画布适配、字幕、亮度/对比度/饱和度/模糊/锐化/颗粒和色温/色调合成，返回可供视觉工具读取的本地 PNG；不支持的效果与转场中间态显式返回 warning。
- 剪辑 `cut_silences` 使用 PyAV 解码真实音轨并按 RMS/dB 聚合连续静音，在同一事务内反向波纹切除；切分后同步维护 `sourceInSec/sourceOutSec`，保证后续快照仍读取正确源帧。
- 新增原创 3D 导演台：场景树、WebGL 视口、三种角色素体、19 种姿态、场景属性、可见运镜片段、路径/动画时间线和图片导出均为可操作状态。后端提供 `scene.get/edit/history/snapshot/diagnostics`、`motion.read` 与 `campath.read`，批量编辑失败整体回滚；新增 14 类可审计道具目录、对象移动路径、重命名、环境设置与通用移除，Agent 写入的道具会在 Three.js 场景树和真实预览中呈现。前端的素体、姿态、位置、天空色和相机路径已按项目自动保存并可在刷新后恢复。`scene.snapshot` 读取前端同步的真实 WebGL PNG；编辑器未打开时返回 `PREVIEW_NOT_READY`，不再把结构 JSON 冒充视觉快照。
- 导演台时间线不再只是静态色块：播放与拖动播放头会真实插值相机路径和角色/道具/模型移动路径，角色动画片段驱动标准姿态、循环步态及 Octopus 动作 DSL；暂停或定位后把对应 WebGL 帧同步给 Agent 视觉快照。配套原创 Skill 已补齐镜头语言、动作设计、动作 DSL、运镜路径 DSL 与声明式模型搭建参考。
- 导演台加入安全声明式 `model.generate/capture/compare`：Agent 用盒、球、圆柱和圆锥部件生成可持久化模型，Three.js 画布读取同一数据，服务端生成 front/side/top/iso 多视角 PNG，并可输出参考图像素差异图。该实现不执行任意 JavaScript，避免把解包插件的代码执行面直接迁入主进程。
- Agent 可直接调用 `clip_studio.project_get/edit/history/view/snapshot/diagnostics`、`director_stage.scene_get/edit/history/snapshot/diagnostics`、`director_stage.model_generate/capture/compare`、`director_stage.motion_read/campath_read` 与 `comfyui_bridge.status/dependencies/workflows/workflow_get/workflow_save/queue/result`；测试已验证写入、撤销、播放头定位、工作流节点坐标和 revision 持久化，ComfyUI 队列仍只接受本机地址。
- ComfyUI 执行链已延伸为 `workflow_get → queue → result`：Agent 和 Design 市场都可按工作流 ID 运行，无需手工拼接 prompt JSON；市场显示排队、生成、完成/失败和真实输出预览，结果查询仍只访问 loopback 本机服务。
- 资产中心不再固定空白：读取 Octopus 真实角色资产，支持分类、搜索、网格/列表切换并可绑定到项目画布节点。
- 画布右侧“创作协作”已接入真实实时对话线程：发送后在当前 Design 布局内运行，不再整页跳往普通对话；嵌入态复用现有 Agent 执行、消息流和项目参数，同时隐藏重复的全局侧栏。

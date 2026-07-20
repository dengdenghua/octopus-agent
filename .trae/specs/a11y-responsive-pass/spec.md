# 无障碍与响应式走查 Spec

## Why

按用户指定的走查顺序（侧栏 → 消息区 → 文件 → Agent 团队 → 浏览器/桌面 → 渠道 → 次级工作台 → 国际化 → **无障碍与响应式** → 发布验收），前 8 站已完成。本站聚焦 WCAG/ARIA 合规与移动端可用性：盘点扫描发现 41 处 a11y 缺陷（10 处图标按钮无 aria-label、12 处 button 缺 type、12 处 input 缺 aria-label、3 处可交互 div/span 不规范、2 处焦点不可见）和 60+ 处响应式缺陷（表格硬宽度、DialogFooter 丢失 sm:flex-row、agent-operator-panel 内 12 处 grid-cols-3/4/5 无断点、断点切换不统一导致孤儿中间态）。

## What Changes

### P0（必修，阻断键盘/移动端可用性）

- **焦点可见性**：`deploy-panel.tsx:293` textarea `focus:outline-none` 无替代焦点环 → 移除 outline-none 或补 `focus-visible:ring-2 focus-visible:ring-ring`。
- **可交互元素键盘可达**：`editor-tabs.tsx:134-146` 关闭标签 span 改 `<button type="button" aria-label>`；`browser-home.tsx:2239-2241` 关闭文件夹按钮补 aria-label+type；`mobile/page.tsx:1244-1246` 占位麦克风按钮补 disabled/aria-label。
- **表格移动端溢出**：`runtime-self-check-panel.tsx:446` `min-w-[720px]` 与 `stream-telemetry-panel.tsx:101` `min-w-[680px]` → `min-w-[480px] md:min-w-0`，父级加 `max-w-full`。
- **断点孤儿态**：`workspace-layout.tsx` modeSwitcher `md:` vs rightPanel `lg:` 统一为 `lg:`；`sidebar.tsx` rail `sm:flex` 与 sidebar `md:block` 统一为 `md:flex`。

### P1（应修，影响可用性）

- **图标按钮 aria-label**：terminal-input(2)、live-preview-panel(4)、copilot-panel(1)、copy-button(1) 共 8 处补 aria-label。
- **input/textarea aria-label**：registry-plugins/roles/skills-panel(3)、browser-preview-panel(2)、app/browser/page(1)、app/desktop/page(2)、webview-tab(1)、copilot-panel(2)、terminal-input(1) 共 12 处补 aria-label（使用现有 i18n placeholder 文案）。
- **button type="button"**：terminal-input(2)、live-preview-panel(4)、browser-home(1)、mobile/page(1)、copilot-panel(1)、personality-selector(1)、knowledge-graph-panel(2) 共 12 处补 type。
- **DialogFooter 丢失响应式**：11 处 `flex-row justify-end` 改回 shadcn 默认 `flex flex-col-reverse gap-2 sm:flex-row sm:justify-end`。
- **agent-operator-panel.tsx grid-cols 无断点**：12 处 `grid-cols-3/4/5` 改 `grid-cols-2 sm:grid-cols-3 lg:grid-cols-{N}`。
- **CardHeader flex-row 在小屏挤压**：4 处 CardHeader 改 `flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between`。
- **plugins/agent 卡片 flex-row 无 col 兜底**：2 处 `flex flex-row` 改 `flex flex-col gap-3 sm:flex-row sm:items-center`。
- **浮层硬编码 w-[Npx]**：url-bar(3)、webview-tab(2)、browser-home(2)、file-activity-indicator(1) 共 8 处补 `max-w-[calc(100vw-1rem)]` 兜底。

### P2（建议改进，体验优化）

- **focus:outline-none + focus: 改 focus-visible:**：arms-editor.tsx:934。
- **file-tree.tsx aria-label**：补 `aria-label={isDir ? '打开文件夹 X' : '打开文件 X'}`（用 i18n key）。
- **browser-home.tsx:697 backdrop**：补 `aria-hidden="true"` 或 `role="presentation"`。
- **overflow-x-auto 容器加 max-w-full**：9 处表格/代码块容器。
- **同文件 flex-row 断点统一为 md:**：agent-operator-panel(10)、agent-world-unified(6)、storage/page(1 异常)、settings/appearance(2 w-[220px] 加 w-full sm:w-[220px])、reflex/page(1)、intelligence-panel(3)、model-settings-page(1)、store/*-panel(6)。
- **observability/page 同页 grid 节奏统一**：3 处统一为 `md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4`。
- **case-study-section px-20**：改 `px-4 sm:px-8 lg:px-20`。
- **evolution-dashboard/index.tsx:273 异常 `xl:grid-cols-1`**：复核产品意图，疑似 bug。

### 不在本次范围

- P3 大文件拆分（agent-operator-panel 3707 行、intelligence-panel、evolution-control-panel 等）留后续。
- `text-[7/8/17/22px]` 等超出 9-15px 映射范围的字号需用户确认。
- 装饰性 backdrop/overlay 的 Esc 关闭逻辑改造（属于功能增强，非 a11y 缺陷）。
- 颜色对比度审计（需要 design token 级别改造，留后续）。

## Impact

- **Affected specs**: 无（无前置 spec 依赖）。
- **Affected code**:
  - a11y: `terminal-input.tsx`、`live-preview-panel.tsx`、`browser-home.tsx`、`mobile/page.tsx`、`copilot-panel.tsx`、`copy-button.tsx`、`editor-tabs.tsx`、`file-tree.tsx`、`deploy-panel.tsx`、`arms-editor.tsx`、`personality-selector.tsx`、`knowledge-graph-panel.tsx`、`browser-preview-panel.tsx`、`app/browser/page.tsx`、`app/desktop/page.tsx`、`webview-tab.tsx`、`store/registry-{plugins,roles,skills}-panel.tsx` 共 ~18 个文件。
  - 响应式: `runtime-self-check-panel.tsx`、`stream-telemetry-panel.tsx`、`workspace-layout.tsx`、`sidebar.tsx`、`agent-operator-panel.tsx`、`agent-world-unified.tsx`、`storage/page.tsx`、`observability/page.tsx`、`intelligence-panel.tsx`、`model-settings-page.tsx`、`reflex/page.tsx`、`evolution-dashboard/index.tsx`、`channels/page.tsx`、`case-study-section.tsx`、`appearance-settings-page.tsx`、`store/*-panel.tsx`、`plugins/page.tsx`、`url-bar.tsx`、`webview-tab.tsx`、`file-activity-indicator.tsx`、`CardHeader 4 文件`、`DialogFooter 11 文件` 共 ~40 个文件。
- **i18n**: 需新增少量 aria-label key（file-tree 文件/文件夹打开标签），其余复用现有 placeholder/title i18n key。
- **测试**: `remote-backends-panel.test.tsx` 可能受 CardHeader 改造影响需复核；其余 a11y 改造不破坏现有交互测试。
- **风险评估**: P0/P1 改造均为 className 属性补全与元素语义替换，无逻辑变更，回归风险低；P2 flex 断点统一可能改变中等宽度（768~1023px）的视觉布局，需目测确认。

## ADDED Requirements

### Requirement: 键盘可达与焦点可见

每个可交互元素（button/div[@role="button"]/a）必须满足：
1. 键盘可聚焦（`tabIndex >= 0` 或使用原生 `<button>`/`<a>`）
2. 焦点可见（不能 `focus:outline-none` 后无替代样式；优先 `focus-visible:ring-2`）
3. 可通过 Enter/Space 触发（`<button>` 原生支持；`<div role="button">` 需补 `onKeyDown`）

#### Scenario: 键盘用户 Tab 导航
- **WHEN** 用户使用 Tab 键在 workspace 内导航
- **THEN** 每个可交互元素都能获得焦点且焦点环可见
- **AND** Enter/Space 能触发与鼠标点击相同的操作

#### Scenario: 标签页关闭
- **WHEN** 键盘用户聚焦到 editor-tabs 的关闭按钮
- **THEN** 元素为 `<button type="button" aria-label="关闭标签页：{label}">`
- **AND** Enter/Space 可触发关闭

### Requirement: 表单控件可访问名

所有 `<input>`/`<textarea>`/`<select>` 必须满足以下之一：
1. 显式 `<label htmlFor>` 关联
2. `aria-label` 属性（优先使用现有 i18n placeholder 文案）
3. `aria-labelledby` 指向可见标签元素

`placeholder` 不作为唯一可访问名。

#### Scenario: 屏幕阅读器读取搜索框
- **WHEN** 屏幕阅读器聚焦到 registry-plugins-panel 的搜索 input
- **THEN** 朗读"搜索插件"（来自 aria-label）
- **AND** 不依赖 placeholder（输入后消失）

### Requirement: 图标按钮可访问名

`<button>` 仅含图标（无文本节点）时必须声明 `aria-label`。`title` 属性不作为唯一可访问名（触屏/部分屏幕阅读器不可靠）。

#### Scenario: 屏幕阅读器读取图标按钮
- **WHEN** 屏幕阅读器聚焦到 terminal-input 的停止按钮
- **THEN** 朗读 i18n 文案"停止"（来自 `aria-label={t.codeMode.stop}`）
- **AND** 非朗读"按钮"无标签

### Requirement: 响应式断点策略统一

项目断点分界约定（文档化）：
- **sm: (640px)** —— 表单字段行内切换、对话框宽度
- **md: (768px)** —— 桌面/移动主分界（sidebar、modeSwitcher、双栏布局 flex-row 切换）
- **lg: (1024px)** —— 次级面板显隐（rightPanel）
- **xl:/2xl:** —— 网格列扩展

同一布局区域的断点切换必须统一，禁止出现孤儿中间态（如 sidebar `md:` 但 rail `sm:`）。

#### Scenario: 768~1023px 中等宽度无孤儿态
- **WHEN** 视口宽度为 900px
- **THEN** modeSwitcher 与 rightPanel 都不显示（统一 `lg:`）或都显示（统一 `md:`）
- **AND** 不出现"有 modeSwitcher 但没右面板"的中间态

#### Scenario: 表格在移动端不溢出
- **WHEN** 视口宽度为 375px
- **THEN** runtime-self-check-panel 表格 `min-w-[480px]` 触发 `overflow-x-auto` 横向滚动
- **AND** 不撑破父容器导致整页横向滚动

#### Scenario: DialogFooter 在移动端堆叠
- **WHEN** 视口宽度 < 640px
- **THEN** DialogFooter 内按钮垂直堆叠（`flex-col-reverse`）
- **AND** 仅在 sm: 以上才水平排列

### Requirement: 浮层宽度兜底

所有 `w-[Npx]`（N >= 320）的浮层（Sheet/HoverCard/Popover/dropdown）必须配合 `max-w-[calc(100vw-1rem)]` 兜底，避免在 < N px 视口下溢出。

#### Scenario: 360px 浮层在 320px 视口
- **WHEN** 视口宽度为 320px
- **THEN** url-bar dropdown 浮层宽度为 `calc(100vw - 1rem)` ≈ 304px
- **AND** 不溢出视口

## MODIFIED Requirements

### Requirement: workspace 布局响应式

[原 `workspace-layout.tsx` modeSwitcher 在 md: 显示，rightPanel 在 lg: 显示。修改后：modeSwitcher 与 rightPanel 统一在 lg: 显示，避免 768~1023px 中间态。]

### Requirement: sidebar rail 响应式

[原 `sidebar.tsx` rail 在 sm: 显示，sidebar 容器在 md: 显示。修改后：统一为 md: 显示，避免 640~767px 孤儿 rail。]

## REMOVED Requirements

无（本站为增量修复，不删除现有功能）。

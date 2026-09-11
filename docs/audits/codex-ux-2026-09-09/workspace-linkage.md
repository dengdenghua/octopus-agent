# 浏览器、右工作台、悬浮输入框与画中画联动

基于本机 Codex Windows 安装包 26.901.6511.0 的静态资源分析。没有操作原生 Codex 窗口做拖拽验收；以下常量与分支是源码证据，不代表所有账户都启用，尤其悬浮输入存在功能开关。所有行号指临时目录中格式化后的 JS。

证据根目录：C:/Users/Administrator/AppData/Local/Temp/codex-ux-26.901.6511/webview/assets/

## 已确认的布局机制

### 1. 右工作台宽度不是单一百分比

app-initial-f87238153a19.js:200327–200386 定义宽度计算与保存：
- 右面板最小宽度 320。
- regular 模式最大宽度为工作区宽度减 352；unified 模式减 320；full 模式允许占满工作区。
- 使用 app-shell:right-panel-width:v3 保存合法范围内归一化后的 0–1 比例，并兼容旧像素值。
- 默认宽度为 600 的分支，还根据窗口高度、16/10 比例、640 参考值和剩余内容宽度计算初值，不能简单描述为固定 600px。
- 窄窗口时最小宽度策略会限制上述公式，352/320 不是任意窗口下绝对保证。

app-initial:371263 起 BXa 明确将 isContentFullWidth 转成 full；否则按 isUnifiedWorkspace 使用 unified 或 regular。全宽时面板目标宽度等于工作区宽度；有 isMainPaneExiting 过渡状态。因此“左侧对话消失”有专门模式，不等于普通拖动一路挤到零。

后续已确认拖拽吸附链：见 learning-spec.md。352px 是 regular 预留量；拖拽剩余小于 160 且越过普通上限等条件共同决定全宽吸附，两者不能混淆。

### 2. 悬浮输入框是带状态的交互层

app-primary-428a0a65766f.js:320908 起有 expanded in-app browser 的 Hide composer / Show composer 菜单。
:325180 起组合浏览器 activeTab、会话 ID、焦点、浏览器是否 ready、是否收起、功能开关等状态。
:325247：紧凑模式启用时，强制展开、输入焦点或待用户交互状态会将 compact 切换至 expanded；后续在 i$t 定义中确认 userInput、optionPicker、mcpServerElicitation 等分支。
:326134：显隐还有 entering/visible/exiting/hidden 四态。
:325583：注册浏览器宿主底边感应，activationHeightPx 为 48 乘界面缩放比例，事件按 browserTabId 与 conversationId 匹配。
:324805：存在可聚焦的 floating-composer-reveal-handle；支持 hover、focus-visible 与 reduced-motion。

启示：浏览内容时保留短输入入口；点入写作时展开；隐藏后提供明确恢复把手；不能仅依赖鼠标悬停，键盘也需能唤出。

### 3. 悬浮输入框与原生浏览器协同

包内 Ulr 检查 tab 类型、空 URL、suspended、securityState、loading，并区分 ready/loading/unavailable。
存在 --right-panel-composer-overlay-height 与 --right-panel-composer-overlay-reserve 两个独立变量；说明“看起来悬浮的高度”和“内容应预留的空间”分开管理。
存在 hasComposerFocus、interactiveContentRef、composerGestureSurfaceRef，以及宿主消息 setFloatingComposerRevealTracking。

启示：不能只给输入框 position:fixed。Electron 内嵌浏览器有自己的宿主区域，需协调覆盖层、点击命中、焦点、底部感应和网页可用区域；网页工具栏、底部确认按钮不能被持续遮挡。

### 4. 画中画有避障与宿主同步

remote-hosted-pip-anchor-bridge-4f45838df2bd.js：
- 标记 data-pip-anchor-host、data-pip-home-surface、data-pip-obstacle。
- 四角候选位置，默认边距 24；该桥接算法使用 250×250 的候选矩形。
- 评分综合重叠面积、方向优先级与移动距离，最多 6 轮处理障碍。
- 监听 resize、scroll 和 DOM/元素变化，将宿主矩形和候选锚点传给 electronBridge。
- 悬浮左导航也标注为 pip obstacle。

限制：这证实的是 remote-hosted PiP 的定位桥接，不足以断言所有浏览器视频画中画、所有悬浮卡片都使用 250×250 或相同算法。

启示：Echo 应统一管理悬浮输入框、画中画、侧栏抽屉的安全区域。浮窗应尽量避开输入框、弹窗和用户刚操作的控件，而非各自固定到右下角。

## Echo 现状与真正差距

frontend/src/components/workspace/chat-page-layout.tsx：MIN_CHAT_COLUMN_PX=620，右侧辅助面板最小 360、最大 800；不足时切换桌面覆盖抽屉，移动端另有 peek/展开逻辑。已经存在可调整宽度、持久化与抽屉，不应再重做一套。

当前优先保护对话可读性，所以无法仅靠拉大面板自然得到“网页占满 + 同一任务悬浮输入”。差距主要是缺少统一的内容优先模式以及跨容器输入状态协调。

## 建议给 Echo 的状态设计（建议值，不是 Codex 事实）

| 状态 | 对话 | 右工作台 | 输入框 |
|---|---|---|---|
| 对话优先 | 正常阅读宽度 | 关闭或窄栏 | 对话底部 |
| 分栏工作 | 保持可读，允许适度变窄 | 可拖拽 | 对话底部 |
| 内容优先 | 隐藏，保留返回入口 | 占满可用工作区 | 内容底部悬浮 |
| 内容专注 | 隐藏 | 占满 | 收成把手，可键盘唤回 |

画中画为独立附加状态，服从所有面板的避障规则；不要把它与内容优先模式混成一个开关。

第一次进入内容优先应通过明确的“展开工作台”操作；如果增加拖拽吸附，需有预览、回退和滞回区间，避免边界附近抖动。退出后恢复原分栏比例与聊天阅读位置。

## 实现约束与验收

1. 一个任务只有一份草稿状态；输入框换位置不能丢文字、附件、输入法组合状态，不能产生两个可同时发送的实例。
2. 会话切换与浏览器标签切换绑定正确；草稿不串任务，页面标注上下文不串 tab。
3. 恢复分栏后还原历史阅读位置；后台输出不能强拉回底部。
4. 浏览器底部按钮仍可操作；浮层之外命中网页，浮层之内命中输入框。
5. PiP 避让输入区和抽屉；缩小窗口后不留在屏幕外。
6. 验证宽度建议为 1440/1280/1024/768/390，覆盖拖拽、全宽、返回、焦点、中文输入法和附件上传。
7. full 模式不等于移动端；窄屏仍可沿用现有底部抽屉，避免把桌面悬浮布局硬套过去。

建议先实现“分栏 ↔ 内容优先 + 同一任务悬浮输入”，随后接浏览器命中区域和状态预览，再加 PiP 避障。本轮仅分析，未修改 Echo 布局。

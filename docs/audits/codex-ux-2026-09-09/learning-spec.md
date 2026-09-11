# Echo 多面板联动：完整学习规格

日期：2026-09-09。承接 review.md 与 workspace-linkage.md。本文件固化已追踪的客户端机制、Echo 差距、实施约束和验收路线。完成的是本轮指定联动范围的静态机制梳理；没有声称完整还原 Codex 全部源码，也没有做原生桌面的动态验证。未修改 Echo 产品代码。

## 1. 证据定位

本机 ASAR 的已格式化资源位于 C:/Users/Administrator/AppData/Local/Temp/codex-ux-26.901.6511/webview/assets/。
A = app-initial-f87238153a19.js；B = app-primary-428a0a65766f.js。

| 机制 | 定位 | 已确认内容 |
|---|---|---|
| 宽度与归一化持久化 | A:200327 | minimum 320；regular 留 352，unified 留 320，full 可占满；保存 0–1 比例 |
| 拖拽跨界与吸附 | A:371100 | allowPointerOverflow；越过普通最大宽度且剩余主区小于 Nj(320)，满足面板条件后全宽；Nj(x)=x×0.5 |
| 收起阈值 | A:371123 | 拖拽尺寸小于 160 时进入收起分支；非全宽且未收起才更新合法宽度比例 |
| 全宽入口 | A:299319、363125 | UGi 统一设置全宽，按钮/命令及拖拽共用；进入时调用 tabType.onEnterFullWidth |
| 拖拽结束 | A:371130 | 全宽时通知 active tab；普通状态存储宽度比例 |
| 全宽动画 | A:371263 | regular/unified/full 独立模式；isMainPaneExiting；同布局上下文才延续切换动画 |
| 主动关闭与自动收起 | A:200697 | closeReason=window-resize 分支；可选择 restoreFullWidthOnNextOpen |
| 窗口缩放 | A:371665 | 960 与另一个窄窗阈值参与侧栏/工作台适配；不可把 960 单独当成全宽断点 |
| 输入呈现 | B:325180 | full 面板、当前 tab、ready、焦点、待交互、开关共同影响悬浮状态 |
| 必须回答时展开 | B:89031 | 待 userInput、optionPicker、mcpServerElicitation 等请求参与强制展开条件 |
| 输入隐藏/显示 | B:320908、326134 | 菜单入口；entering/visible/exiting/hidden 状态 |
| 底边唤回 | B:325583 | 48×界面缩放比例感应区，绑定 browserTabId+conversationId |
| 高度与内容占位 | B:92851、92905 | overlay-height 和 overlay-reserve 分开；120ms 过渡，新的过渡取消旧计时 |
| 滚轮冲突处理 | B:324838 | 仅输入手势区域接管纵向手势，排除最新回复内容区；输入自身有滚动空间时不抢滚动 |
| 焦点恢复 | A:299337、363127 | 调用布局切换后 requestAnimationFrame 聚焦布局按钮，preventScroll |
| 浏览器标签生命周期 | A:490228 | tab 类型提供 open/restore/serialize/sync/transfer/onEnterFullWidth 等钩子 |
| 面板拓扑保存 | A:490212 | tabs、active、tabId、panel、rightPanelOpen/fullWidth、focusArea、bottomPanelOpen |
| 新任务绑定 | A:199963 | clientThreadId 到 conversationId 的绑定与迁移回调，含 draftThreadLocationId |
| PiP 避障 | remote-hosted-pip-anchor-bridge:1 | 四角候选、障碍矩形、重叠优先惩罚、边界限制、最多 6 次迭代 |
| PiP 更新 | 同文件:245 | resize/scroll/DOM 与元素变化更新锚点，向宿主发送 |

这些常量来自当前版本，不应当作跨版本规范。尤其 160 是吸附条件中的几何值，不是通用聊天最小宽度。

## 2. 状态模型：不能用一个 isExpanded 包办

建议 Echo 保持互相独立的四组状态：

- 布局：chat / split / contentFull。
- 输入呈现：docked / compact / expanded / peek。过渡 separately 为 stable / entering / exiting。
- 浏览内容：tabId、类型、loading/ready/unavailable、viewport、面板归属。
- PiP：任务归属、visible、anchor、用户拖拽偏好、obstacleRects。

输入呈现从布局、浏览器可用性、焦点、待处理确认与用户隐藏偏好派生。不要把“聊天隐藏”误认为“任务关闭”，也不要把“输入隐藏”误认为“停止执行”。

## 3. 关键事件与转换

| 事件 | 期望转换与副作用 |
|---|---|
| 打开右工作台 | 恢复已有标签和上次合法比例；按可用宽度进入 split |
| 点击展开 | split → contentFull；通知标签进入全宽；保持任务连续 |
| 拖向内容全宽 | 允许越过普通上限；满足吸附条件后进入 full；释放时只通知一次 |
| 拖向关闭 | 尺寸过小收起；不把非法尺寸写成下次默认值 |
| 点击恢复分栏 | 恢复上次 split 比例；焦点可达，阅读位置不跳 |
| 浏览器未加载完成 | 输入与覆盖策略不假定宿主已 ready；安全提示不能被浮层盖住 |
| 输入框获得焦点 | compact → expanded；中文组合输入期间禁止重挂载 |
| 用户收起输入 | expanded → peek；提供可点击、可键盘操作的恢复把手 |
| 待用户回答/确认 | 保证交互入口可见；即使先前收起也能到达请求 |
| 鼠标靠近底边 | 显示唤回把手，不能把整个网页底部变成拦截区 |
| 窗口变窄 | 自动适配应可逆，不覆盖用户保存的展开偏好 |
| 切换任务/标签 | 分别切换任务状态与网页上下文，禁止混用旧 tab 事件 |
| PiP 遇到输入框/侧栏 | 重算候选位置；尽量最小移动且不越界 |

## 4. 浏览器覆盖与焦点契约

Echo 同时存在 Electron webview 与 iframe 路径，见 browser-preview-panel.tsx 和 electron/main.cjs。不能照搬 Codex 的 browserHost 消息协议。

为 Echo 设计统一宿主适配接口：报告可见边界、缩放、输入覆盖高度、可点击区域、tab ready 状态；向 UI 发出底边靠近、导航、焦点变化事件。所有事件附带 threadId/tabId，过期事件丢弃。

覆盖层只在自身控件区域接管指针；网页滚动和网页底部 CTA 保持可操作。输入菜单、附件弹层和确认卡片应与输入框一同确定 stacking 与焦点范围；不能只抬高输入框 z-index。

## 5. 输入状态：利用 Echo 已有能力

Echo ChatComposer.tsx:171 已有按任务恢复草稿，:189 有 300ms 防抖持久化；不是从零实现草稿。ChatPageLayout 已有 inputOverlayRef 与高度测量，固定覆盖输入不等同于内容全宽悬浮输入。

优先保持一个挂载的编辑器实例，通过布局容器移动其视觉位置。若框架无法避免重挂载，需先验证：光标、选区、输入法组合、撤销历史、附件上传句柄与焦点能否可靠保留。单纯把字符串存 localStorage 不足以保证这些体验。

客户端新任务变成服务器任务时迁移草稿、附件和布局所属关系；避免发送成功后草稿重新出现，也避免发送失败丢原文。Codex 包内有任务绑定机制，但其全部编辑器状态迁移并未在本轮逐字段证明，这是 Echo 的设计约束而非逆向事实。

## 6. 画中画范围与约束

本轮确认的是 remote-hosted PiP 定位桥接，不混称视频 PiP。候选矩形 250×250、24 边距只是该实现输入。Echo 应按真实浮窗尺寸计算；把 composer、抽屉、确认弹层和用户指定区域注册成障碍。

先最小化遮挡，再保持锚点偏好与移动距离。用户拖拽时不要与自动避障争抢；结束后重新约束边界。布局动画期间限频更新，结束时精确对齐，避免浮窗抖动。

## 7. Echo 实施分层与顺序

1. 在 chat-page-layout/use-resizable-panel 之上增加独立 layout state，保留现有移动抽屉路径。
2. 实现 split ↔ contentFull 和可逆宽度保存；先做好显式按钮，再接拖拽吸附。
3. 让同一 inputArea 在 full 模式进入浮层，并接 compact/expanded/peek 与待确认状态。
4. 接 Electron webview/iframe 适配，处理焦点、底部空间与页面命中。
5. 接回复摘要、队列和审批入口；确保全宽时仍可看到需要处理的事。
6. 最后接 PiP 避障与跨窗口变化，不先做花哨动画。

## 8. 验收矩阵

覆盖 1440、1280、1024、768、390 宽度，浅/深主题、100%/125% 缩放、减少动态效果。每个场景至少执行：

- 拖拽吸附进入/退出全宽，边界来回移动不来回闪烁。
- 窗口缩小再放大，恢复原比例；用户主动关闭则保持关闭。
- 输入中文到组合阶段切换布局，不误发送、不丢字；恢复后能继续撤销。
- 多附件上传中切换布局与 tab，进度不中断、归属不串任务。
- 网页滚动、滚动输入框、展开最新回复，三者不会互相抢滚轮。
- 全宽期间收到待确认、排队失败，用户能直接处理。
- 收起输入后用键盘唤回；Esc、Tab、布局切换后的焦点可预测。
- 关闭/恢复网页、切换任务、刷新页面，标签身份和草稿匹配。
- PiP 与展开输入、侧栏、确认弹层重叠时能避障；缩窗不越界。
- webview 与 iframe 分别验证；不存在底部操作区被透明浮层挡住。

## 9. 本轮完成与待验证

已完成：指定交互范围的状态、宽度、拖拽、全宽、悬浮、焦点、底边唤回、恢复、PiP 避障、Echo 能力对照及落地规格。
尚未完成且不冒充：Codex 原生 UI 实测、功能开关在当前账户的实际取值、完整的编辑器重挂载路径与每个附件字段迁移、Echo 新布局实现。

后续从此文件和 workspace-linkage.md 继续即可，不需要重新全盘解包。第三方资源仅放临时证据目录，报告不嵌入整段第三方源码。

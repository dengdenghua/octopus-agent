---
name: octopus-agent-design-a11y-audit-2026-07-18
description: 2026-07-18 design 插件实机走查前端：两实锤 bug（设置弹窗关不掉/主题切换 composer 不跟随）+ a11y 清单；浅色对比度全绿
metadata: 
  node_type: memory
  type: project
  originSessionId: 89894e60-85e8-40e0-b22a-0622c82b227a
---

2026-07-18 用 design 插件（design-critique + accessibility-review）对 frontend/ 实机走查（本地 dev + 本地登录 stub，浏览器面板实测），结论：

**两个实锤 bug（已挂 spawn_task 卡）：**
1. 设置弹窗关不掉：Esc 无效；点 X 后 overlay 卸载但 content 层 data-state=closed、exit 动画 animationPlayState 永远 running，opacity:1 + pointer-events:auto + z-50 僵尸层挡页面，仅刷新可清。自定义 resizable DialogContent（含「拖动调整大小」separator）的 Presence 处理有问题——overlay 能正常退出说明动画系统本身没坏。
2. 主题实时切换 composer 不跟随：跟随系统模式下运行中切 light↔dark，全页换肤唯独 chat-input-box 残留旧主题表面色（残留态实测「默认确认」1.05:1、「Octopus Mix」1.00:1）；fresh load 两主题都正常 → 是切换传导问题非配色问题。

**其余要点：** 浅色稳态对比度全绿（抽样均 ≥8:1）；「选择模型」按钮和 4 个建议 chip 聚焦无可见指示（其余 1.5px/50% 半透明 ring 偏弱）；设置弹窗初始焦点落「退出登录」；X 按钮 15px + 英文 "Close"、"Toggle Sidebar" 英文；无 nav landmark、可见大标题非 heading、无 skip link、document.title 不随路由变（一直「新对话 - Octopus」）；移动端 375px 首屏上半 ~50% 空白（内容沉底）；自进化页数据口径矛盾（沉淀 110 技能 vs 自动形成 0/占比 0%、平均耗时 0ms）；自动化页测试数据泄漏（e2e-ui-* 订阅）；Hub 空计数 chip（金融 0/可加入 0）。**存疑待 VoiceOver 复核**：read_page AX 树里侧栏三个 icon+文本链接和设置导航多个按钮无名，但 DOM 检查文本可见且无 aria-hidden，可能是提取怪癖。

**方法备忘：** axe-core 本机未装（在另一 worktree）；改手动：focusin 监听器记录 Tab 序 + canvas fillStyle 转色算对比度 + resize_window 双主题双端。Radix 弹窗 JS .click() 不触发关闭（监听 pointerdown），要用真实鼠标事件。浏览器面板 computer 坐标是截图像素空间（需按缩放折算），ref 点击不受影响。

相关：[[octopus-agent-frontend-ux-streaming-audit]]、[[octopus-agent-frontend-optimization]]

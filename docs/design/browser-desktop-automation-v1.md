# Octopus 浏览器 / 桌面自动化 v1

> 状态：已实现，等待集成提交与最终视觉签收  
> 版本：v1.0 · 2026-08-23  
> 参考：[ChatGPT 桌面端解包对比](../../ChatGPT解包-浏览器与电脑自动化对比.md)

## 产品目标

1. 用户可以在设置中看清浏览器和桌面自动化是否启用、连接及系统权限是否就绪。
2. Agent 操作真实浏览器时，目标页面显示不阻挡交互的 Agent 光标。
3. 普通内容链接统一经过 `openTarget`，由用户偏好决定外部打开或进入应用内浏览器。
4. 自动化控制面采用一致的低侵入胶囊样式，并保留暂停、接管和证据回看能力。

## 范围

本版本包含设置页、relay 状态流、Chrome 扩展光标、链接路由、胶囊工具条，以及支撑它们的能力门禁、目标租约和回归测试。

本版本不包含 Electron webContents 跨进程无损迁移、完整 `stage/reveal` 动画、独立原生 CUA 守护服务、锁屏操作、密码/Profile 导入和云浏览器。这些属于后续桌面端项目，不是 v1 验收项。

## 交付计划与当前进度

| 里程碑 | 范围 | 退出条件 | 状态 |
|---|---|---|---|
| M1 · 可发现与可控 | FR-1 设置页、FR-5 胶囊控制条 | 两个设置入口可独立访问；能力开关落盘并在下一次工具执行前生效；三档对话展示不回退；控制条不拦截页面点击 | 已完成 |
| M2 · 可见与可诊断 | FR-2 relay 状态、FR-3 Agent 光标 | relay 在断开后 10 秒内进入离线；扩展命令开始/结束均驱动光标；导航后能在新文档恢复；reduced-motion 可降级 | 已完成，等待最终视觉签收 |
| M3 · 链接统一路由 | FR-4 `openTarget`、文案收敛 | 普通 Web 链接消费 `external \| in_app` 偏好；下载、OAuth 和显式外开保持原语义；存储或应用内浏览器不可用时安全外开 | 已完成 |
| M4 · 桌面端深化 | webContents adoption、原生 CUA 守护、锁屏运行、Profile/密码导入、云浏览器 | 单独立项、单独威胁建模与发布门禁 | 暂缓，不属于 v1 |

执行顺序固定为“门禁与状态 → 可视反馈 → 链接入口 → 视觉签收”。任何阶段失败都必须保留上一条可用路径：relay 退回 HTTP 轮询，应用内打开失败尝试退回外部浏览器，权限探测不可用时只回显而不伪造已授权状态。Electron 桌面桥可以可靠外开；纯 Web 环境仍可能被浏览器弹窗策略拦截，此时 `openTarget` 返回 `blocked`，不把失败伪报成成功。

## 需求与实现证据

### FR-1 设置页

- 设置导航包含独立的“通用 / 对话 / 浏览器自动化 / 桌面自动化”目的地。
- 浏览器页包含总开关、relay 在线/重连中/离线三态、扩展版本、离线重连指引、网站允许/阻止记忆和链接打开偏好。
- 桌面页包含总开关、屏幕录制与辅助功能权限状态；macOS 桌面端可直达对应系统设置，Web 端只做能力回显。
- 对话页继续单独承载三档细节级别，不受自动化设置改版影响。
- 开关双向热生效：关闭时执行硬门禁立即拒绝并从后续目录移除；重新开启时原进程热注册对应工具组，无需重启后端。

实现：

- `frontend/src/components/workspace/settings/settings-dialog.tsx`
- `frontend/src/components/workspace/settings/conversation-settings-page.tsx`
- `frontend/src/components/workspace/settings/automation-capability-settings.tsx`
- `frontend/electron/main.cjs`
- `frontend/electron/preload.cjs`
- `runtime/sensing/gateway/_agents_endpoints_system.py`
- `runtime/platform/runtime_policy/capabilities.py`
- `runtime/execution/tool_engine/executor.py`

### FR-2 Relay 连接状态

- `/api/browser/relay/status/ws` 每秒推送一次只读状态；前端断线后指数退避重连，HTTP 两秒轮询保留为降级路径。
- 只以应用层心跳判断在线，不把半开 push socket 当作存活证明。心跳六秒内在线、随后进入重连，八秒离线；HTTP 两秒轮询降级仍可在十秒产品预算内显示红灯。
- WebSocket 使用与 Realtime 相同的 bearer 子协议认证约定。

实现：

- `runtime/platform/ui/browser_router.py`
- `runtime/safety/auth/principal.py`
- `frontend/src/core/settings/automation-status-api.ts`

### FR-3 Agent 光标

- 每个 relay 命令由后台脚本发送 `start/end` 光标事件。
- `document_start` content script 在独立 Shadow DOM overlay 中渲染；宿主固定、`pointer-events:none`，不污染业务元素样式。
- 状态采用 `Map + subscribe` 外部存储，渲染以 `requestAnimationFrame` 节流，并尊重 `prefers-reduced-motion`。
- 活跃光标状态同时保存在扩展 service worker；页面跳转完成后会恢复到新文档，动作结束再隐藏。

实现：

- `extensions/octopus-browser-relay/background.js`
- `extensions/octopus-browser-relay/cursor-overlay.js`
- `extensions/octopus-browser-relay/manifest.json`
- `runtime/execution/suckers/browser_act_skills.py`
- `runtime/execution/suckers/browser_backends.py`

`live_browser_*` 会先探测 Electron 内置浏览器；存在活跃 webview 时始终由 Electron 执行，动作失败也不向扩展重复投递。仅在没有可用 webview 时，点击、输入、滚动、等待、导航、提取、截图和状态查询才降级到扩展；任意脚本执行保持 Electron-only。扩展路径继续复用 capability、站点策略、目标标签租约和人工接管门禁。

### FR-4 openTarget

- `openTarget` 是普通 Web 内容链接的统一二元路由。
- 偏好保存为 `external | in_app`，支持同窗口和跨窗口更新通知。
- 应用内打开通过带请求 ID 的持久信封进入内置浏览器；浏览器壳必须回执。存储失败或 1.5 秒内未收到回执时，清理信封、恢复原路由并尝试降级到外部浏览器；纯 Web 弹窗被拦时显式返回 `blocked`。
- 下载、OAuth、明确“外部打开”和新任务窗口继续使用显式外部语义。
- Markdown、引用、研究证据、项目资料和 Artifact 普通 Web 链接统一消费该偏好；相对路径、修饰键点击和下载仍保留原生语义。

实现：

- `frontend/src/core/navigation/open-target.ts`
- `frontend/src/core/settings/automation-preferences.ts`
- `frontend/src/components/ui/routed-web-link.tsx`
- `frontend/src/app/browser/page.tsx`

### FR-5 悬浮胶囊

浏览器 webview、浏览器预览和会话自动化控制条统一采用：

```text
rounded-[12px] + bg-secondary/90 + backdrop-blur-sm
+ ring-[0.5px] + shadow-[0px_8px_16px_-4px_rgba(0,0,0,.12)]
```

覆盖容器为 `pointer-events-none`，真实控件为 `pointer-events-auto`。

实现：

- `frontend/src/components/ui/automation-capsule.ts`
- `frontend/src/components/browser/webview-tab.tsx`
- `frontend/src/components/workspace/browser-preview-panel.tsx`
- `frontend/src/components/workspace/automation-control-dock.tsx`

## 非功能约束

- 能力默认启用；关闭会在下一次工具执行前动态拒绝，不依赖 UI 隐藏。
- 浏览器标签页与桌面窗口使用稳定目标租约；目标变化时失败关闭，避免误操作其他页面或应用。
- 人工输入或切换标签页会触发接管事件并暂停 Agent 控制。
- 光标和控制边光均不拦截页面点击，并提供 reduced-motion 降级。
- relay、权限探测和应用内浏览器不可用时均有可理解的降级状态。

## 自动验收

| 验收项 | 证据 |
|---|---|
| 设置两节及三档对话设置共存 | `settings-dialog.test.tsx`、`conversation-settings-page.test.tsx` |
| 开关双向热生效且执行门禁生效 | `test_capabilities_gate.py`、`test_capabilities_hot_reload.py` |
| Relay 断线十秒内离线 | `test_browser_router.py` 的正常断线与半开 push socket 验收 |
| Relay WebSocket 三态与重连 | `automation-status-api.test.ts`、`test_browser_router.py` |
| live browser 命令显示光标 | `test_chrome_extension_e2e.py` 通过 `SkillRegistry` 调用字面 `live_browser_click` / `live_browser_wait`，驱动真实 Chromium 扩展 |
| 页面跳转后恢复光标 | `test_chrome_extension_e2e.py` 的 fixture → destination 场景 |
| Electron 优先且扩展降级不双投 | `test_live_browser_extension_fallback.py`、`test_browser_backends.py` |
| openTarget 消费偏好与失败外开 | `open-target.test.ts`、`routed-web-link.test.tsx`、`artifact-link.test.tsx` |
| 胶囊样式与点击穿透 | `automation-control-dock.test.tsx`、扩展静态/真实回归 |

最终发布签收要求：前端类型检查、完整 Vitest、后端完整 pytest、扩展真实 Chromium 场景和设置页视觉走查全部通过。

截至 2026-08-23 的本轮验证：前端 291 个测试文件共 2320 项通过、2 项按环境跳过，TypeScript 与完整 ESLint 通过；浏览器后端聚焦回归 78 项通过（包含真实 Chromium）；官方分片快速后端矩阵共 14005 项通过，发现的唯一代码层门禁（3 条 import-direction 反向依赖）已下沉修复并由 128 项聚焦回归及严格依赖检查复验；slow / integration 矩阵 16 项通过、1 项按平台跳过；异步阻塞、自动文档和可选文档插件门禁为 18 项通过、4 项按缺失可选能力跳过；Ruff、扩展脚本语法和相关 diff 检查通过。当前仅剩两条 `HEAD` / `git archive` 完整性检查按设计失败：共享工作树中的发布必需文件尚未形成集成提交，候选工作树构建本身已通过。设置页与胶囊的运行时视觉签收仍需在 **设置 → Browser** 中解除 `localhost:3000` 的已保存 Block 权限后执行。

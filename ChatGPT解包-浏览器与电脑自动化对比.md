# ChatGPT 桌面端 vs octopus：浏览器自动化 / 电脑自动化 对比报告

> 解包对象：`/Applications/ChatGPT.app`（v26.814.41407，Electron，2026-08-19 构建）
> 解包方式：`app.asar` 提取 + 原生 Resources（`cua_node`、`codex`）分析 + 语言包文案提取（380 条设置文案）

## 2026-08-23 落地进度

本报告下文的“octopus 现状”保留的是解包当日基线。当前工作树已经完成第一轮迁移：

- 浏览器自动化、桌面自动化独立设置节，包含真实能力状态、relay 三态、macOS 权限入口与链接打开偏好。
- 原生 macOS 截屏、鼠标、键盘、应用/窗口枚举和辅助功能快照；不可用能力以降级状态展示。
- Appshot（截图 + 目标窗口 + 可访问性元素索引）及元素级 preview-confirm-execute 契约。
- 输入框稳定自动化目标选择已贯穿执行链：Chrome 目标进入标签页租约并在不匹配时拒绝，macOS 目标在执行前自动激活对应应用/窗口；不再只是 UI 选择。
- 可暂停/接管的胶囊控制条、最近操作回执与证据时间线。
- Chrome relay 光标 overlay、站点允许/阻止记忆、普通内容链接统一消费 `openTarget` 二元路由。
- 隐藏 webview 常驻与稳定 adoption lease 标识，页面切换不再销毁浏览上下文。
- Teach & Repeat 已接入输入框 `/record`、`/replay` 与录制库入口，不再是未挂载组件。

仍值得继续学习、但不属于本轮 Web/Electron 范围的能力：独立原生 CUA 服务、锁屏守卫、应用级白名单、逐动作三态审批、点击音效、OCR/PDF 视觉栈和云浏览器。

---

## 一、架构总览

### ChatGPT 的浏览器自动化（三条通路）

| 通路 | 实现 | 定位 |
|---|---|---|
| **内置浏览器**（Codex Browser） | Electron 内嵌 Chromium webview，完整浏览器 UI（侧边栏、评论标注、下载管理、历史） | 默认主力，agent 在内嵌浏览器里干活，用户可实时围观 |
| **浏览器扩展**（Chrome/Edge） | 商店扩展，接管用户真实浏览器 | "added control"，可 `@browser` 引用，操控用户自己的 Chrome/Edge |
| **云浏览器**（Cloud Browser） | 服务端远程浏览器，live view 投流 | 免安装场景 / 移动端 |

### ChatGPT 的电脑自动化（Computer Use / CUA）

```
ChatGPT.app
└─ Resources/
   ├─ codex                    (212MB Rust 二进制，agent 主进程)
   └─ cua_node/                (自带 Node 24.19 运行时，121MB)
      └─ lib/node_modules/
         └─ @oai/sky/          (v0.6.16, CUA 核心)
            ├─ "Codex Computer Use.app"   ← 独立原生 app！
            │   ├─ SkyComputerUseService   (服务端)
            │   ├─ SkyComputerUseClient    (客户端)
            │   ├─ CUALockScreenGuardian   (锁屏守卫)
            │   └─ "Codex Computer Use Installer.app"
            │       └─ CodexComputerUseAuthorizationPlugin  (授权插件)
            └─ playwright / sharp / tesseract.js / pdfjs-dist
```

**关键点：电脑操控不是塞在 Electron 主进程里，而是一个独立的原生 .app + 独立 Node 运行时。** 服务/客户端双进程架构，通过 macOS 辅助功能授权插件拿系统权限，锁屏时由 LockScreenGuardian 守护。

### Sky 桌面 API（21 个动作，窗口级）

```
list_windows / get_window / list_apps / launch_app
get_window_state (含截图 + 可访问性文本 + 元素索引)
click / press_key / type_text / scroll / set_value / drag
perform_secondary_action (辅助功能操作)
activate_window (前台切换逃生舱)
start_audio_recording / stop_audio_recording
```

特色：**窗口级绑定**（每个动作指定目标 Window）、**截图+可访问性文本+元素索引**三态捕获、点击可点"索引元素"而非裸坐标、输入前自动激活目标窗口。

### octopus 现状对照

| | ChatGPT | octopus |
|---|---|---|
| 浏览器 | 内置 + 扩展 + 云 三通路 | Chrome 扩展 relay（`live_browser_*`）单通路 |
| 扩展形态 | 商店分发，装完即用 | 本地 unpacked 扩展（`chrome://extensions` 手动 Load unpacked） |
| 电脑操控 | 独立原生 app + Node 运行时 + 授权插件 + 锁屏守卫 | `desktop_automation` 开关 + Electron 桌面端内实现（`computer_use_loop`） |
| 桌面动作 | 21 个窗口级 API | 截图/点击/键盘为主 |
| 视觉栈 | sharp + tesseract.js（OCR）+ pdfjs | 无独立 OCR/pdf 栈 |

---

## 二、设置界面对比（解包实测文案）

### ChatGPT「Computer use」设置页（`settings.computerUse.*`）

**副标题：** "Manage how ChatGPT uses other applications on your computer"

| 设置区块 | 功能 | 文案示例 |
|---|---|---|
| **Any App** | 总开关 | "Let ChatGPT control apps on your computer" |
| **Always-allowed apps** | 白名单管理（列表/移除/空态/加载态/错误态全套） | "Remove {displayName} from always allowed apps?" / "ChatGPT will ask to use {displayName} in the next computer use session" |
| **Locked use** | 锁屏后台操控 | "Let ChatGPT use your Mac when it's locked" / 启停反馈文案齐全 |
| **Browser（Chrome/Edge/Safari）** | 每个浏览器一张卡片：已装/未装/装扩展/重装/移除 | "Use a browser extension for added control" / "Show @browser in the composer" / Safari 卡片 "coming soon" |
| **More browsers** | 引导装更多浏览器扩展 | "Set up extensions for more browsers" |
| **Microsoft Excel / PowerPoint** | Office 加载项实时操控开关 | "Let ChatGPT use Microsoft Excel add-in for additional control" |
| **Messages** | 读写+发送消息权限 + "Always allowed to send" 聊天白名单 | "Let ChatGPT read and send messages" |
| **Sounds** | 操控音效（前台点击/前后台点击/关） | "Play sounds for foreground clicks" |
| **Install（Control）** | 插件安装器 | "Computer Use plugins unavailable"（空态兜底） |

**Agent Mode 完整访问确认弹窗**（开启时逐类授权）：
- 终端命令（"运行命令、安装软件、更改系统设置"）
- 文件和文件夹（"读取、创建、修改、上传"）
- 互联网和已连接的应用
- 分模型风险提示（Cyber 模型有额外安全警告）

### ChatGPT「Browser」设置页（`settings.browserUse.*`）

| 设置区块 | 功能 |
|---|---|
| **Approval** | 打开网站前询问：Always ask / Always allow（后者标注 elevated risk） |
| **Downloads / Uploads approval** | 下载/上传前询问（同上三态） |
| **History approval** | 访问浏览历史的许可：询问/禁止/免询问 |
| **Site permissions** | **站点级权限覆盖**：每站点 Browse/Download/Upload/Debug(CDP) 四维权限，预设 Allow/Block/Custom |
| **Full CDP access** | 全量 CDP（高危开关，可被组织策略禁用） |
| **WebMCP（Enable site tools）** | 站点暴露 MCP 工具 |
| **Extensions manager** | 浏览器扩展管理器 |
| **Autofill / Passwords / Contact info** | 自动填充、密码管理器、联系人 |
| **Profile import** | 从其他浏览器导入 Cookie/历史/密码 |
| **Browsing/Download history** | 历史/下载管理（含分页、搜索、清空） |
| **Clear browsing data** | 逐类清理（缓存/Cookie/历史/下载/站点数据） |
| **Local URL open target** | localhost 默认在哪个浏览器打开 |
| **Developer mode** | 开发者模式 |

### octopus 对照

| 能力面 | ChatGPT | octopus 现状 |
|---|---|---|
| 电脑操控总开关 | 设置页 "Any App" 开关 + always-allowed 白名单 + 移除确认弹窗 | `capabilities.py` 的 `desktop_automation: True`（代码级开关，**无 UI**） |
| 浏览器连接状态 | 每浏览器卡片显示 Installed/Not installed，一键装/重装/移除扩展 | `/api/browser/relay/status` 返回 JSON（**无 UI 呈现**），扩展需手动 Load unpacked |
| 站点权限 | 站点级四维权限管理 UI + 预设 | `site_policy` JSON + `allowed_hosts/blocked_hosts`（**无 UI**） |
| 操作审批 | 打开/下载/上传/读历史 四类审批三态可调 | `immune_reject` 类硬拦截（策略文件级，**无 UI**） |
| 权限确认 | Agent Mode 逐类授权弹窗（终端/文件/网络分开确认） | 门禁体系（默认不拦/可降级/可关/长任务豁免，为代码级） |
| 锁屏操控 | "Locked use" 开关 + LockScreenGuardian 守护进程 | 无 |
| 消息读写 | Messages 权限 + 聊天白名单 | 无 |
| 音效反馈 | 点击音效三档 | 无 |
| Office 联动 | Excel/PPT 加载项开关 | 无 |
| 空态/错误态/加载态 | 每个区块全套（emptyTitle/loading/loadError/saveError） | — |

---

## 三、核心差距与可抄作业清单

### 差距 1：设置 UI 缺失（最大差距）
octopus 的能力开关几乎都在代码/配置层（capabilities.py、site_policy、.env），ChatGPT 把同样的东西做成了**一页结构化设置**（Any App 总开关 → 分能力卡片 → 白名单管理 → 逐类审批）。380 条设置文案里，仅 computerUse 就有约 60 条，且空态/加载态/错误态/确认弹窗全覆盖。

### 差距 2：权限粒度
- ChatGPT：站点级（4 维度×3 态）+ 应用级（白名单）+ 动作级（打开/下载/上传/读历史分开审批）+ 场景级（锁屏、发消息）。
- octopus：会话级 + 策略文件级。粒度差一个数量级，但方向一致（octopus 的门禁四原则其实对标的就是 Agent Mode 的分级授权）。

### 差距 3：安装体验
- ChatGPT 扩展走商店，设置页一键 Install/Reinstall/Remove。
- octopus 需手动 `chrome://extensions` → Developer mode → Load unpacked。可优化：设置页给图文引导 + relay 状态实时反馈（数据已有，缺展示）。

### 差距 4：进程架构
- ChatGPT 电脑操控 = 独立原生 app + 独立 Node 运行时（隔离崩溃域，Electron 挂了 CUA 不死；辅助功能授权走系统插件；锁屏有专门守护进程）。
- octopus 电脑操控在 Electron 桌面端进程内。隔离性/权限申请/锁屏场景都弱一档。

### 值得直接抄的（按性价比排序）
1. **设置页"Browser / Computer use"两卡片**：relay 连接状态 + 扩展安装引导 + desktop_automation 开关（数据全部现成，纯 UI 工作）。
2. **Always-allowed apps 白名单**：octopus 已有 site_policy 的 allowed_hosts 机制，泛化到应用级 + UI。
3. **动作审批三态**（询问/允许/禁止）：把 immune_reject 从硬拦改成可配置三态，正好符合门禁四原则的"可降级"。
4. **点击音效**：极小的活，存在感极强（用户听到点击声才知道 agent 在动他的电脑）。
5. **窗口级 API 设计**（list_windows + 索引元素点击 + 输入自动激活窗口）：octopus 的 computer_use_loop 可参考这套契约。

---

## 附：本次解包产物位置

- 解包目录：`/tmp/chatgpt-unpack/extracted/`（301M，webview + node_modules）
- 设置文案提取源：`webview/assets/_virtual_settings-search-documents-*.js`
- CUA 核心：`/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/@oai/sky/`
- Sky API 文档：`@oai/sky/docs/sky-window2-api.md`（未压缩源码自带，含完整 TS 接口定义）

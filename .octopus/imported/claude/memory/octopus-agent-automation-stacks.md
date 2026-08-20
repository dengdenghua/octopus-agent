---
name: octopus-agent-automation-stacks
description: 电脑自动化/浏览器自动化两栈的实证成熟度 + 子代理 env 混淆教训
metadata:
  node_type: memory
  type: project
  originSessionId: 73dba696-f7dc-4ee6-899f-63f46a601f05
---

77 代理评测两栈(map→对抗核实→评分),**但子代理犯了 env 混淆错**,亲验纠正:

**承重教训**:评测子代理用 **系统 `python3`**(无 pyautogui)判定"dep 缺/maturity 0",但运行时是项目 **`.venv`**——`.venv/bin/python` 里 `pyautogui 0.9.54` 装着、`PYAUTOGUI_AVAILABLE=True`、`register_computer_skills` 真注册 **13 个技能**。→ **任何"已装/未装"判断必须用 `.venv/bin/python`**,别信子代理的 `python3`。playwright 则**真没装**(.venv 也 import 失败)。

**电脑自动化(比报告所称强)**:
- pyautogui 坐标控制(screen_capture/mouse_click/move/keyboard_type/press/screen_info,`computer_skills.py`)**真注册+可跑**(macOS 需授屏录+辅助功能权限);代码质量高(边界校验、FAILSAFE、preview→execute token 流)。成熟度 ~4。
- `computer_use_loop.py`:vision planner(带图 router.call)真;但**循环包装器不在主 `_CATALOG`**(`register_computer_use_loop` 未接进 all_skills)→ 生产不可达,scaffold。
- UIA(`computer_uia_skills.py`)Windows-only 且**不喂进 vision loop**(语义接地缺口)。
- `tentacle/desktop.py` DesktopDevice.execute() 两分支都返 `[DESKTOP-MOCK]/[DESKTOP-WIRED]` 假串(真 execute 注释掉)=mock。
- Android 链(`android_router.py` 204 行)scaffold:app.py 从不 include_router、ws 缺 websockets 会炸、`d.model` 未定义。
- device_lock/lease:router 是 sync def 用不了 async ctx mgr → **只追踪元数据不强制互斥**。

**浏览器自动化(报告基本对)**:
- playwright 真没装 → `register_browser_skills` 返 0 → 10 个 `browser_*` skill **运行时根本不在注册表**(调用 SkillNotFound,不是错误 dict)。
- 唯一真路径:`browser_act`/`live_browser_*`(`browser_act_skills.py`,无条件注册)经 **Electron 桥**(需 Octopus 桌面 app 跑 + bridge.json:18345)。
- `BrowserBackend` 统一抽象(Protocol+resolve_backend+Playwright/Electron/Extension 三 adapter,`browser_backend.py`/`browser_backends.py`)**生产零调用**(docstring 自承 testable seam);三轨降级是 aspirational。
- DOM 质量高(`browser_dom_js.py`:selectorUnique 唯一性、密码 property-first 脱敏、aria-disabled)但唯 Electron 路可达,且 selectorUnique 标志**无 agent 代码消费**。
- 两处安全洞:`browser_router.py:415` SSRF guard import 失败 `except: return url`(fail-open);25 个 browser 端点**零 approval/auth**(能驱动表单/凭据)。

**已修(playwright 真浏览器 + 持久会话)**:用户选"装 playwright"。`uv pip install playwright`(1.60)+ `playwright install chromium`(在 .venv;**pyproject 的 `browser` extra 早有声明**,无需改 pyproject;.venv 不入 git)→ 10 个 browser_* skill 运行时注册(之前 absent)、45 浏览器测试从 skip 转跑、live chromium 实跑通。**持久 agent 浏览器会话(commit `5575263`)**:agent skill 此前无状态(每次新开浏览器→多步流程断)。playwright sync **线程亲和**,故建 `browser_session_worker.py`:**专用线程独占 browser+page**(launch/op/close 全在该线程,队列+Future 跨线程提交),`BrowserSessionPool` 按 session keyed + idle reaper + cap;`_with_page` 单点改:**有 agent session→走持久 worker(thread_id keyed),无 session→保持旧无状态**(测试/直调不变)。**并发加固(commit `3f68f26`,19代理对抗审查 confirmed 11/驳4)**:submit 检查+入队移进锁内(修 blocker 丢操作竞态)、op 超时退役 worker(防脏 page 复用)、`_with_page` 对被 reap 的 worker 重试一次、atexit close_all。20 测(假 factory 测并发原语 + 真 chromium 多步)。

**已修(commit `606b279`,语义接地 macOS)**:vision loop 此前纯像素。新 `desktop_grounding.window_grounding()`——macOS 经 Quartz `CGWindowListCopyWindowInfo` 列出屏上窗口(app/标题/bounds,滤掉 Window Server+<40px,封顶),非 mac/缺 pyobjc/任何错→返 ""**绝不抛**;`ModelRouterVisionPlanner` 加可选 `grounding` hook(每步重算,因窗口会动),文本注入 prompt(None/""=纯像素不变);app.py serve 期挂上。**实测本机 .venv 真出列表**(如 `Claude: Claude @ (292,190) 1200x800`)。UIA 仍 Windows-only(本机无用)——正因如此 macOS Quartz 路才是要补的缺口。4 测。**Quartz(pyobjc)在 .venv 有**(系统 python3 无,勿混淆)。

**已修(commit `430d62f`)**:browser_router 接进共享 auth —— 25 个 `/api/browser/*` 端点此前**零鉴权**(create_browser_router 无参、裸挂),而 agents/system 等兄弟 router 都接 `require_auth`。改:create_browser_router 收 identity_store/require_auth/jwt_*,加 router 级依赖调 `web_auth._resolve_actor`;app.py 传同款 cocoloop/molili auth 上下文。**默认保持**(auth 关→`_resolve_actor` 返 None 不抛,本地 preview 不变;auth 开→全端点 401)。2 测。**第一手又纠 eval**:device_lock"不强制"是误——桌面 lease(computer_router)已用 HTTP 409 强制互斥;`device_lock.py` 是 Android 锁,唯一消费者 android_router 是已 defer 的未接线 scaffold,非桌面并发洞。

**已修(commit `de9586a`,resolve_backend 三轨接线——用户选"重写")**:browser_* skill 此前全走 headless PW;现经 `_with_page` 单咽喉接入 `resolve_backend([Extension,Electron])`——可用则在该轨上 **navigate-then-act**(保无状态语义、全程同一浏览器、不 split-brain),否则落 PW(我的持久会话)。6 动词路由(navigate/click/type/wait/state + scroll-to-selector),get/extract/find/screenshot/scroll-to-y 留 PW。**默认保持**:无桌面 app 时 EXT/ELEC `available()=False`→resolver 返 None→照走 PW(本机/CI 行为不变);真浏览器仅 bridge 在跑时介入。fake-transport 单测路由(navigate-then-act/高轨优先/不可用跳过/无轨→None→PW);真 Electron 端到端需桌面 app(BrowserBackend docstring 当年 defer 的 seam,现已接)。

**已修+实测端到端(commit `80af6ba`,"启动 electron")**:桌面 app 此前 dev 启动**整个坏掉**——app 被挪进 `extras/desktop/` 后,main.cjs 的 4 个 dev 路径解析器(desktopDataDir/bundledAgentsRoot/backendConfigTemplatePath/backendConfigPath)只 `__dirname,"..",".."` 上 2 级到 `extras/`(应上 3 级到仓库根),全落到不存在的 `extras/{data,agents,packaging,config.local.yaml}`→`prepareDesktopRuntime()` 在 app.whenReady 抛 "config template not found"→DOA。修:4 个 isDev 分支各补一个 `".."`(打包构建走 process.resourcesPath 不动)。**关键**:dev 模式 `startBackend()` 直接 `if(isDev)return`(复用用户 :8000,不 spawn、无端口冲突),`migrateDesktopConfig` 也 isDev-return(不改用户 config),`startBridgeServer()` 在 whenReady 里**不依赖登录**就起。launch 用 `frontend/node_modules/.bin/electron`(extras/desktop deps 不用装,main.cjs 只依赖 electron+node 内置)。**亲验三轨真打通**:bridge 起在随机端口写 `data/bridge.json`(仓库根,正是 ElectronBackend 读处)→ `ElectronBackend.available()=True`(整 session 第一次)→ `resolve_backend([EXT,ELEC,PW])→electron`(PW 已装仍正确按优先级选 ELEC)→ 真 `_bridge_call("state")` 往返收到 bridge 应用层 `503 "no active tab in browser shell"`(非连接错=HTTP+Bearer token 鉴权都通了;真 DOM op 只差桌面浏览器视图开个 tab 设 activeWebContentsId)。退出 app 自动 unlink bridge.json→available()回 False→PW 回退恢复(并发会话零影响)。这是 [[octopus-agent-improvement-roadmap]] 里 de9586a 三轨接线从"仅 fake-transport 断言"到**真桥端到端确认**的收口。

**已修(commit `e2e2deb`,AX 控件级语义接地 macOS)**:`装 pyobjc-framework-ApplicationServices`(AX 框架,之前的拦路;系统级 focused-app API 返 -25204,改 **NSWorkspace 前台 pid→AXUIElementCreateApplication** 路径 err=0 实测可用,`AXIsProcessTrusted=True`)。`desktop_grounding.ax_control_grounding()`:遍历前台 app 窗口/子元素(深度+数量封顶),actionable role(AXButton/TextField…)+ label(title→desc→value→help)+ AXPosition/AXSize 经 `AXValueGetValue` 取中心坐标;`combined_grounding()=window+AX` 接进 vision loop planner(app.py)。实测产出真控件坐标(如 `Button 'Send' @ (331,206)`)——这是缩小与 Anthropic computer-use 差距的控件接地。best-effort 非 mac/untrusted/出错返 ""。**OCR / android_router 不做(用户确认)**:OCR 需 tesseract 二进制(本机无 brew,Apple Silicon Homebrew 装 `/opt/homebrew` 需 sudo 交互密码→我装不了);**且 OCR 对这个 vision loop 冗余**——`ModelRouterVisionPlanner.next_action` 已 `images_b64=[截图]` 把图发给视觉模型,模型自己读屏上字,再 OCR 同图喂回是重复+加延迟。真有价值的是 window+AX 的**结构化坐标/身份**(像素提取不出),已做。android_router 需真机。别再重启 OCR/android。

**已修(commit `1f2a42f`)**:① computer_use_loop 在 serve 期接线(app.py router-available 块,用 `ModelRouterVisionPlanner(router)`;非原子、pyautogui exec 期门控、router 缺则 non-fatal)→ desktop_operator_arm 的 `computer_use_loop` 引用现可解析(此前只 demo_server 注册)。② browser open-extension-folder 的 xdg-open 在 macOS 改 `open`(跨平台 bug)。2 测;193 浏览器测试绿(3 playwright skip)。**第一手推翻**:`_page_title_for_url` 的 `except: return url` **非 SSRF fail-open**(返 url 当标题、不发起抓取),撤销该"修复"。`ALL_SKILL_IDS=frozenset(_CATALOG)` 无外部消费者→非硬校验门,allowed_skills 是惰性 allowlist,故无需 _CATALOG 条目。

**codex_gap.py 自评是文件存在性清单(别信分,信 next_actions)**:`compute_codex_gap_report()` 输出 `parity/advantage/combined=1.0 verdict=differentiated`——但打分逻辑是**逐路径 `path.exists()`**,不验证是否真跑。正中 [[octopus-agent-audit-verification-lesson]] 的"存在=假信心"雷。**有用的是它每个 capability 的 `next_actions`**(真 backlog):如 "Turn successful replay cases into reusable skills automatically"、"Turn repeated browser replay failures into deterministic repair recipes"。亲验过 computer_use_loop 生产接线用**真** `ModelRouterVisionPlanner`(app.py:324,非 Mock)、`combined_grounding()` 实时返回本机窗口——这两个是真活的,非骨架。

**已做(commit `3b61ede`,record→skill 闭环)**:成功的 computer_use_loop 运行→`computer_use_record.record_successful_loop` 写一条 journal `Trajectory`(steps 映射到注册技能 mouse_click/keyboard_type/keyboard_press/mouse_move,wait/未知丢弃,<2 步不录),既有 SkillForge 自动聚类重放→锻技能,**零新 forge 代码**。关键安全语义:**4 个 GUI 原语全 `is_dangerous_tool=True`**,故 forge 免疫闸拒绝自动转公开;run() 此前把 `UnsafeSkillPromotionError`(ValueError 子类)走通用 catch **静默 retired**,现**单独捕获→治理隔离**(`SkillForgeResult.quarantined` 新字段 + journal `skill_proposal_decision(decision=quarantined)` 待人工审批)。所以闭环=录制→forge→免疫闸→审批,绝不录制→自动放行。evolution_demo 把 quarantine 计入有效进化结果。14 测 + 1113 回归绿。**未来别期望 GUI 锻技能自动 promote——它们进审批队列**。

**已做(commit `e7cc798`,对称的失败→修复闭环)**:`record_failed_loop`——循环失败(max_iterations/planner_gave_up/error/timeout)写 ReviewQueue 行(**复用既有 `computer_activity_replay_case` kind + `browser_desktop_replay` 桶**),既有 1231 行 `browser_desktop_repair_recipes` 引擎**零改动**聚类成修复 recipe。每次失败独立行(text 带唯一 fingerprint)但按 (status,last-action) 同 cluster_key,故 3 次"max_iterations 点击失败"→ 1 个 recipe occurrences=3→引擎升 P0。循环 handler 现按 journal-presence 闸同时录成功(→forge)和失败(→repair)。**关键背景**:此前 computer_use_loop 的结果**除我加的 record 外零下游消费**,失败全丢;现接上。codex_gap 那条 "repeated failures→deterministic repair recipes" 的 computer-use 侧补齐。

**裁决**:原语与单点实现质量不弱(基建如 lease/preview/risk 甚至更细),差距在**编排/接线层**(loop 未入 catalog、BrowserBackend 零调用、Android 不 include)+ **语义接地**(纯像素 vision,无 DOM/AX/OCR 进 planner)+ **浏览器安全门**。与 [[octopus-agent-multiagent-gap]]/[[octopus-agent-integration-debt-audit]] 同源(强原语弱编排)。最高杠杆:装 pyautogui 已满足→只差把 computer_use_loop 接进 catalog;装 playwright + 把 resolve_backend 接到 skill 调用点。

相关:[[octopus-agent-integration-debt-audit]]、[[octopus-agent-audit-verification-lesson]]、[[octopus-agent-dev-environment]]

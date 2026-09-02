---
name: octopus-agent-evaluation-2026-08-15
description: 2026-08-15 前后端一体审计+同类对比 7.2/10；tip 门禁全红；4 个确证 P1（replan/chunk打包/跨租户会话/Landlock报告）；优化已全部落地
metadata: 
  node_type: memory
  type: project
  originSessionId: 95b630e7-4eb6-4c73-9b9e-c430bbdcae71
  modified: 2026-08-15T14:36:57.584Z
---

**2026-08-15 优化已全部落地（未提交，工作区）**：4 P1 + 门禁收口 + 前端 18→1 红测。
- P1 修复：replan（StaticPlanner.plan 加 model 参数 + 测试 fake 同步）；chunk_rows 打包 session_id 加进 _EXTRA_KEYS + 跨会话断 run 测试；跨租户会话隔离（store get/list/mention 按 thread_id scope + resolver known 空集=限制全 + bridge 续会话 scope_thread_id）；Landlock enforcement→partial（同 Seatbelt 判据）。
- 门禁全绿：ruff（E713 修）、mypy（8 新错全修注解：guard steps→list[Any]/_normalize_tool_args→dict|str/_reasoning_effort:str|None/default_reasoning_effort→str|None/steering setattr ignore）、import-direction（注入反转：sessions 加线程级 injector 注册表，steering 活跃回合注册/注销）、orphan（删 realtime_schema.py 死代码 + worker.py 进 baseline）、openapi/auto-docs 重生成、protocol 契约加 COMPONENT_NOTIFICATIONS(workflow/completed)、test_thread_state_router_p2 修 fixture（加 client/sample_thread）+ 加 search/feedback enabled 属性（501 判断）、exception_audit 9 个吞异常加 noqa 说明。
- 前端：重做 streaming-polish（子代理身份渲染 + toggle 重构）+ 实现推理披露设计（17→1）。关键实现：`groupConsecutiveReasoningSteps` 同 phase 跨工具合并（flush 判重防双 push）、phase 边界断组、isDeepThinking 加 groupDurationMs≥10s（原生单块深度）、thinkingDisclosureLabel 三态（深度/静音"思考过程"/内容）、静音检测=chat 模式+非深+非 live+无 duration+单消息 messageId+无 commentary。
- 残留预存 flaky 已修：**chats-drawer "角色"链接失败根因 = zh-CN `navHR: "HUB"` 占位符残留**（28776caf 引入，与测试期望"角色"同提交矛盾；en-US=Agents/ja=人材/ko=인재）。改为"角色"后全量 229 文件 1885 全过。
- god_file 12 个 ≥1000 行文件 baseline 化（13 个，含故意单体 react_loop；escrow 4000 仍防失控增长），分裂留 follow-up。
- 已提交 9 个语义提交（本地未 push）：replan/chunk/session-scope+inject-invert/sandbox/gate-cleanup/feedback-enabled/frontend-redesign/i18n-navHR/godfile-baseline。
- 全量验证：后端 98 分片 0 失败、前端 229 文件 1885 过、tsc/eslint 绿、全部 8 个 lint 棘轮绿（ruff/mypy/invariant/import-dir/orphan/god_file/exception_audit/fixtures）。

**推送+合并（2026-08-15 下午）**：9 提交推 origin/codex/subagent-streaming-polish（新建远端分支）→ main 快进合并推送（4036eee0..593c5541，443 提交含 dsh 移植）。用户在 main 上改。注意：**zh-CN navHR 应为 "HUB"（用户拍板，测试期望"角色"是我改错的方向）**，已把测试改成期望 HUB、翻译保留 HUB。

**桌面端 E2E（6.2→6.4，已推 main f69690a5）**：审计发现 Electron 两轨无 E2E。补 Playwright `_electron` smoke：main.cjs 加 `--smoke-test` 强制未打包也加载 dist；`frontend/playwright.electron.config.ts` + `e2e/electron/desktop-smoke.spec.ts` 断言窗口启动/preload `window.octopus` 桥/#root 挂载/desktop organizer IPC 往返；package.json `e2e:desktop`。**未覆盖**：打包态后端 spawn（main.cjs `if(app.isPackaged)` 守卫，未打包不启后端；端口硬编码 8000；后端健康由浏览器 full-stack 车道覆盖）。

**桌面端拉回（f8f63ace，已推 main）**：main.cjs 零单测 + move 桥真实缺口（trash 校验源是直接桌面项但 move 没有，相对 destDir 可 `../` 逃逸）。提取 `desktop-shell-core.cjs`（纯函数：isDirectDesktopItem/resolveMoveTarget/buildDesktopItem/readJournalFile/writeJournalFile）+ 20 个 vitest 单测（含穿越拒绝/.app 分类/journal 往返）+ move 用与 trash 相同的直接项+桌面内校验。**桌面分 6.2→6.5（按壳评 ~7.6）**。

**webview 桥加固（22e7e949，已推 main）**：`browser:*` IPC（executeJS/capturePage/extractText/click/type/navigate）接受渲染进程任意 webContentsId，被攻破的渲染进程可对主窗口/任意 webContents 执行 JS 或截图。修 `wc()` 校验 `getType()==="webview"`，Electron smoke 加断言（主窗口 id 的 executeJS 返回 "not a webview"）。

**打包态后端 spawn E2E（a29bdde5，已推 main）**：main.cjs `if(app.isPackaged)` 守卫的 spawn 路径无 E2E。加 `--smoke-test-backend` 强制未打包也 spawn；backend-runtime 支持 `OCTOPUS_DESKTOP_BACKEND_ROOT` 复用已有 venv（跳过首启下载）+ 端口从 `OCTOPUS_BACKEND_URL` 推导（renderer baseURL 一致）。smoke 测真实 spawn → 轮询 `/api/health` 200 → 断言 preload 同 URL。测试不泄漏（app.close→before-quit→killBackend 生效，18000 无残留）。**桌面端三项已全清，仅剩 Windows UIA 接地（macOS 上无法做）**。误杀过一次用户 dev 后端（config.local.yaml:8000，非测试进程，留意）。

**hooks 事件集补齐（0ccc0795，已推 main）**：对照 Claude Code 契约补 5 个事件——SubagentStart/SubagentStop（call_subagent 每次 spawn/finish 触发）、PostToolUseFailure（executor 工具失败）、PermissionRequest/PermissionDenied（approval_gate：PermissionRequest hook 可在询问人前 grant/deny，replace 审批决策）。全部暴露给外部 hooks.json 桥（`_EVENT_TYPES` 现在 11 个）+ 模块 docstring 契约化 + 5 新测试。全量 98 分片绿（唯一失败=auto-docs 过期，重生成修复）。**坑**：改 hooks docstring 会让 `docs/auto/` 过期需重生成；测试的 `@register_hook` 在函数体内注册（运行时），别在函数里 import 同名事件类会 UnboundLocalError。

**MCP 工具搜索（4221f563，已推 main）**：用户质疑"MCP/skills 都有还打磨啥"→ 核实后确认机制全有（MCP client+OAuth+CLI mcp add+trust；skills public 目录+market_skills+codex 兼容），真实差距只有三件 UX：tool search 延迟加载/三 scope 呈现/skills 市场。做 #2：`build_anthropic_tool_specs` 原本 max_skills 截断按注册顺序取前 N，registry 超预算时 MCP/server 工具淹没上下文。加 goal 相关性评分（关键词重叠，name 加权 2/description 1，无嵌入依赖），超预算时选最相关 Top-N（确定性 tiebreak=注册序），无 goal/全零分回落原序。4 测试（停用词过滤/排名/预算存活/回落）。**ex extensibility 7.5→7.8，octopus 整体 ≈7.8 与 Claude Code 持平（模型拉平）**。剩余 UX：MCP 三 scope 呈现 + OAuth 登录 UI（mcp-settings-page 有配置/状态无 scope/登录入口）、skills 商城搜索/版本/详情。并发会话活跃推 main（6ceda90a/ad5cd3cb），用显式 pathspec 提交避开。

**ultracode 改软（ff7532fd，已推 main）**：用户问 octopus ultracode 与 Claude Code ultracode 的区别（前者=确定性强制编排预算，后者=软行为指令），"就留你这种"→ 改软。去掉 react_loop 的强制 `run_orchestration` 预启动（-89 行块 + 删死 helper `_orch_launch_announcement` + json/uuid 未用 import）；`_react_context_code` 的 audit.ultracode 提示词改为 Claude 式（详尽/可并行就扇出/对抗性自检/不抬 spawn 上限）；`delegation_budget` 加 `_effective_flat_limit()`（ultracode 模式平局上限 5→20，仍受 OCTOPUS_ORCH_TOKEN_BUDGET 约束）；前端 mode-selector/presets 注释更新。测试：删 4 个 `_orch_launch_announcement` 测试 + 改写 2 个旧断言（软行为：无注入编排、模型自主 router.calls==1）。react_loop 339 过、定向 391 过。**mypy 棘轮当前红是并发会话未提交 subagents_router.py 的 wait_for 错（非我引入，别动）**。auto-docs 需重生成（提示词改动）。

**教训**：前端测试描述的设计意图要从多条测试交叉提取（静音 vs 内容靠"单条消息 messageId"判别）；分组器合并已入 items 的组会双 push（flush 需判重）；resolver 的 known 空集=None 会让陈旧检查失效（sessions=[] 应=限制全）。

**教训**：Workflow 脚本里 `.then` 必须挂在对的位置（`parallel(...).then` vs `[...].map(...).then` 数组没有 .then）；pipeline stage2 返回二维数组要 `.flat()` 再聚合；`sed`/`git ls-tree` 前确认 cwd（cd 漂移会导致误判 docs 跟踪状态）。

2026-08-15 对 `codex/subagent-streaming-polish` 分支（434 提交，dsh 58 点移植）做前后端一体审计：6 路测绘 + 6 维探查 + 34 条对抗验证（28 确认/6 驳回）+ 4 对手对比。综合 **7.2/10**。完整报告在 `reports/audit-2026-08-15-fullstack.md`。

**四个确证 P1（本人亲自复现/追链路）**：
- **replan 静默失效**：`graph_runtime/runtime.py:776` 无条件传 `model=` kwarg，`StaticPlanner.plan`（planner.py:92）不接受 → TypeError 被宽 except 吞 → static planner replan 永不执行。commit 28776caf 引入。两回归测试正确抓到。
- **chunk 打包丢 session_id + 可跨会话合并**：`_chunk_rows.py:56` `_EXTRA_KEYS["sub_text_delta"]` 不含 session_id，classify 静默丢弃（违反 docstring "never data loss"）；不同会话同 role/round/parent 可打包进一行。复现跨会话 count=2。修：session_id 加进 extra。
- **跨租户子代理会话枚举+可读写**：`sessions.py:289` 无 owner 隔离；`/api/subagents/sessions` actor-agnostic；continue_session_id/@session mention 无属主校验。同档于已修 control-session/terminal IDOR。
- **Landlock enforcement()="full" 报告误导**：sandbox.py:716 只约束文件写，读全放、网络不受限。报 "full" 会误导 strict 部署。

**tip 门禁全红（实测）**：make lint 红（ruff E713 _config_helpers.py:97 + mypy 8 新错）+ import-direction 红（sessions.py:994 execution→gateway 懒导入）+ orphan 2 + openapi 漂移（/api/subagents/sessions）+ protocol 契约多出 workflow/completed + auto-docs 过期 + test_thread_state_router_p2 13 ERROR+5 FAILED（fixture 从未定义）。后端 98 分片 8 片失败。前端 tsc/eslint 绿、vitest 6 红（WIP 相关）。

**未提交 WIP（streaming-polish 三件套）评估**：方向正确、契约吻合（spawn marker arguments 带 role_display_name/codename/avatar、finish marker result 带 codename/ok/output）；**HEAD 时 message-group.test.tsx 18 红 → 工作区已修到 6 红**（worktree 实测）；残留 6 红根因 = 新接线的 summarizeReasoningGroup 把 thinking 标签从元数据换成推理原文（行为回归）。另：isSubagentMarker includes 过宽、toggle 无 focus-visible、spawn/finish 命名不一致。**`frontend/frontend/` 是误生成嵌套目录应删**（含过时 bug 报告 + 孤儿 workbench-cache.test.ts）。

**同类对比（4 评测员，claude-code-guide 权威事实 + gh api 拉 dsh 真实包清单）**：octopus 对 Claude Code/Agent SDK 7.1、对 dsh 7.0、对 Codex/Qoder/Kimi 6.9、对通用框架(Swarm/LangGraph) 7.8。评分卡 agentLoop 7.5 / multiAgent 7.8 / streamingUX 8.0 / memorySession 7.3 / safety 7.3 / extensibility 6.8 / productSurface 8.0 / tooling 6.3 / maturity 6.0。定位"编排原语最全的自托管实验性运行时，能力面领先、成熟度落后一个量级"。dsh 未覆盖：ACP/e2b 远端 SpillStore/credential/identity/detached quiescence/tool-ralph。

**教训**：Workflow 脚本里 `.then` 必须挂在对的位置（`parallel(...).then` vs `[...].map(...).then` 数组没有 .then）；pipeline stage2 返回二维数组要 `.flat()` 再聚合；`sed`/`git ls-tree` 前确认 cwd（cd 漂移会导致误判 docs 跟踪状态）。

关联：[[octopus-agent-scorecard-audit-2026-07-18]]（上次自评网格教训）[[octopus-agent-evaluation-2026-07-09]]（上次 7.8 分）[[octopus-audit-false-positives]]

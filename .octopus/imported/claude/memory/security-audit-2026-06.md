---
name: security-audit-2026-06
description: Security audit (2026-06-19) of octopus-mobile + which findings were fixed vs deferred; safe-default behaviors introduced
metadata: 
  node_type: memory
  type: project
  originSessionId: aa494889-9cf1-4899-a403-3e5977c80b7a
---

A 12-dimension security audit ran 2026-06-19; full report saved at repo root `AUDIT_REPORT.md` (70 verified findings). Fixes landed on branch `ui-fixes-and-tokens` (uncommitted as of audit).

**Fixed + verified (assembleDebug + 423/424 unit tests):** R7 Shizuku injection (per-arg `sanitizeShellArg` in `ShizukuShellService.searchByContent/putSetting`), R8 `browser_evaluate` reclassified DANGEROUS/HIGH_RISK + JSON-encoded selectors, R9 extension-install UrlGuard+https+AMO-allowlist, R10 relay `JWT_SECRET` no longer a hardcoded placeholder (ephemeral random), R2 `PathGuard`/`UrlGuard` wired into file/url tools, secret-log redaction (`FileLoggingInterceptor`, `QBotApiClient`), WebView debug gated to DEBUG, BootReceiver `exported=false`.

**New safe-default security mechanisms (default-on):**
- **Channel sender ACL** — `channel/ChannelAccessControl.kt` + `KVUtils.isChannelAclEnabled()` (default true). TOFU: first sender per channel auto-binds as owner, others rejected. Enforced in `ChannelSetup.onMessageReceived` via `ChannelManager.getLastSenderId()`. FeiShu now tracks `open_id` for this. **Settings UI now exists** (2026-06-26): `ui/featurescreens/ChannelAclActivity.kt` — per-channel allowlist view/remove/重新配对 + ACL master switch; reached from TrustCenter "访问与审计" → "通道访问控制".
- **High-risk tool source gate** — `ToolRegistry.withUntrustedSource{}` + `isRemoteHighRiskAllowed()` (default false). Blocks HIGH_RISK tools from WS `tool/execute`, LAN debug-execute, and ProactiveRuleEngine (R12). **As of 2026-06-26 the gate's CONFIRM branch now actually consumes both `highRiskConfirmer` and `isRemoteHighRiskAllowed`** (was a dead setting before — only referenced in a docstring): precedence = highRiskConfirmer?.invoke ?: (isRemoteHighRiskAllowed → allow) : ApprovalFlow dialog. The toggle is exposed in `ChannelAclActivity`. See `ToolRegistry.kt` CONFIRM branch ~line 306.

**Advanced Automation Mode (满血模式)** — `KVUtils.isAdvancedAutomationMode()` (default false), toggle in TrustCenterActivity ("高级 · 专用自动化设备"). The project is meant for idle/dedicated phones doing automation, so this master switch lifts the agent-CAPABILITY guardrails when on: bypasses the high-risk source gate (`ToolRegistry.executeTool`), the proactive high-risk block, and the file-tool `/sdcard` sandbox (`PathGuard.underSdcard` returns allow). It deliberately does NOT touch external-attack hardening (channel ACL, secret redaction, WebView debug). The Trust Center "一键收回" button also resets it to off. `isAdvancedAutomationMode()` is guarded against uninitialized MMKV (safe in unit tests).

**Deferred (need product/UX or protocol work — NOT done):** R3 full mother-WS hardening (force wss, server identity, reject pre-handshake `tool/execute`); R6 ConfigServer loopback binding (would break the opt-in LAN console feature); R9 real install-prompt confirmation + CRX3 signature verification (`GeckoViewEngine.onInstallPromptRequest` still auto-approves); KVUtils secret-at-rest encryption. R5 token-broadcast is opt-in-gated already; registry-poisoning half fixed (uses UDP source IP). **Done 2026-06-26:** ~~settings UI for the ACL + remote-high-risk toggle~~ (ChannelAclActivity) + audit-log viewer (`AuditLogActivity`) + `SetupReadiness` 就绪度聚合 + readiness card in TrustCenter. Still open: local (non-untrusted-source) HIGH_RISK agent calls still auto-pass in APPROVAL mode — confirming them is a UX/policy decision; audit-log `clear()` still has no auth guard.

**2026-06-29 批次修复(审计 Codex WIP 后,均已 commit+push main;详见 repo `AUDIT_FIXES.md`):**
- **R9 扩展 drive-by 自动安装 —— 已修**(上面 Deferred 里"onInstallPromptRequest still auto-approves"已过时):`GeckoViewEngine` 现 `extensionsWebAPIEnabled = false`(砍网页触发路径)+ `onInstallPromptRequest` 仅放行 App 主动发起的安装(install 入口打开 120s 静态窗口,非窗口内一律拒绝)。
- **高影响开关远程翻不动**:`isRemoteHighRiskAllowed`(`KEY_REMOTE_HIGH_RISK_ALLOWED`)与 `isAdvancedAutomationMode`(`KEY_ADVANCED_AUTOMATION_MODE`)都在 `DualConfigWriter.SYNC_BLOCKED_EXACT`,`handleIncomingMessage` 应用入站配置时 `if (isSyncBlocked(key)) continue`——母体/远程无法改写,只有本地 UI 能翻。**纠正 AUDIT/分析里"FULL_POWER 可远程配置翻转"的说法。** 翻动 `isRemoteHighRiskAllowed` 现写审计(`ToolAuditLog.recordSecuritySetting`);FULL_POWER 切换早已在 `PermissionModeManager.switchMode` 审计。
- **审计日志结果脱敏**:`ToolRiskPolicy.summarizeResult/summarizeParams` 现调 `SecretRedactor.redact`(此前工具结果只截断不脱敏,验证码/token 明文入库);`AuditLogActivity` 现显示 `tampered` 篡改标志。`SecretRedactor` 已扩展 OTP/手机号/邮箱。
- **evalJs 重写**:`GeckoViewEngine.evaluateJs` 此前拼出非法 JS(`alert(__OCTOPUS...: + ...)`)致 eval 恒超时失效——已修(JSONObject.quote)+ 每调用随机 nonce(防页面伪造结果)+ per-call holder(防并发串线)。
- **心跳 ACK 重连**:`HeartbeatReporter` 的 ACK 超时→forceReconnect 改 `KVUtils.isHeartbeatAckReconnectEnabled()` 默认关(母体 `../octopus-agent` 实测不回 `heartbeat/ack`,开了会重连风暴)。
- **短信验证码自动复制 —— 端到端已实现(opt-in)**:修规则逻辑(`set_clipboard`→`clipboard`+提取验证码)+ 新增 `SmsReceiver`(`RECEIVE_SMS`,manifest 以 `BROADCAST_SMS` 保护)+ TrustCenter「验证码短信自动复制」开关。三重前提默认关。⚠️ `RECEIVE_SMS` 经 Play 分发会触发政策审查。
- **Agent 崩溃恢复**:修 resume 重放悬空 tool_call(致恢复即崩)+ `resumeTask`/`executeTask` 改 `compareAndSet`。
- 测试 423 → 590。仍 deferred:母体 WS TLS、ConfigServer loopback、KVUtils 静态加密、审计日志 HMAC 密钥同库/无链式(删行不可检测,需重设计)、`AuditLogActivity.clear()` 无鉴权、群聊 ACL 按会话非按人。

**2026-07-01 深度审计(多 agent workflow)确认项修复(commit `74d5c3a` on main):** 41-agent 审计确认 19 项 + 验证中另发现 1 处 CRITICAL,均已修 + 加回归测试。
- **HIGH — 小程序 JS 桥来源闸门缺失**:`OctopusBridge.callTool/deviceAutomate` 是唯一未包 `withUntrustedSource` 的不可信入口(WS/MCP/agent/proactive/DeviceRoute 都包了),恶意 registry mini-app 声明 `allow_tools:["*"]` 即零审批调高危工具。两入口现均 `ToolRegistry.withUntrustedSource { executeTool }`。
- **HIGH — Rhino 沙箱 `fetch()` 无 SSRF 防护**:新增 `octopus_mobile/safety/SsrfSafeHttp.kt`(逐跳 `UrlGuard` + 禁自动重定向 + 手动跟随 + 可选 per-hop 白名单谓词)+ `SsrfSafeDns.kt`(okhttp3.Dns,连接期对实际解析结果再过 `UrlGuard.isDisallowedAddress`,堵 DNS rebinding TOCTOU)。`ScriptSandbox.HTTP` 与 `DeclarativePluginTool.NO_REDIRECT_CLIENT` 都 `.dns(SsrfSafeDns)` 且走 SsrfSafeHttp。**新增任何"出站到不可信 URL 的 HTTP"都应复用这两者,别直接 OkHttp。**(commit `12f7484`)
- **HIGH — 声明式插件重定向 SSRF**:`DeclarativePluginTool` allowHost 只校首跳→改逐跳重跑 allowHost(SsrfSafeHttp 的 hopAllowed 谓词)。
- **HIGH — config-sync 投毒 `KEY_SCRIPT_WORKSPACE`**:母体可把沙箱白名单改 "/"。加进 `DualConfigWriter.SYNC_BLOCKED_EXACT` + 子串 `WORKSPACE`/`SANDBOX`;`ScriptSandbox.isSafePath` 加 `FORBIDDEN_WORKSPACE_ROOTS` + 分隔符边界(防御纵深)。
- **HIGH — `UrlGuard` IPv4-mapped IPv6 绕过**:`[::ffff:169.254.169.254]` 等绕过。`isPrivateIp` 改为 `InetAddress` 规范化 + 内建 `isLoopback/LinkLocal/SiteLocal/AnyLocal/Multicast` + 拆内嵌 IPv4;compat `::a.b.c.d` 仅当首八位组非 0(排除 `::`/`::1`)。
- **HIGH — 服务端 `n`/`best_of` 成本放大**(`server/app.py`):透传致上游 n× 计费、用户扣费封顶单份。钳 `n` 到 `[1,MAX_COMPLETIONS=4]` 并计入 hold,丢弃 `best_of`。
- **CRITICAL(审计外新发现)— `server/app.py` 整个模块 import 即 NameError**:上一批新增的 `/admin/api/plugins*`、`/admin/api/profit/timeseries` 路由的 `Depends(admin_guard)` 早于 `admin_guard` 定义(装饰器求值时求值默认参)→ 服务端起不来。**已把 `admin_guard` 定义上移到首个 admin 路由之前。教训:新增 admin 路由必须在 admin_guard 定义之后。**
- MED/LOW/INFO:`DebugRouteHandler` 路径穿越(absolutePath→canonicalPath);`PrivacyScanner` 单列 `sk-proj-/sk-svcacct-/sk-admin-`(别放宽通用 `sk-` 否则误吞 `sk-ant-` 破测试);`ScreenStreamer` 屏幕树过 `SecretRedactor`;`RemoteConsoleGateway` 上报 `RemoteControlIndicator`+input_text 走 withUntrustedSource;`ScreenHandler` MJPEG 卡死看门狗;`ToolRegistry.registerPluginTool` 拒覆盖内置;`OctopusBridge.pay()` latch 超时;`PathGuard.checkSensitive` 接通死代码;profit timeseries `ts`→`created_at`。
- **测试**:app 全量单测通过;server 112/116 通过 —— **4 失败为本地未配 agnes provider 的既有环境依赖(`test_list_models`/`test_billing_estimate`/`test_chat_insufficient_credits_402`/USD settle),非回归**。server 单测跑法:`server/.venv/bin/python -m pytest server/test_app.py`(venv 里 pytest 需先 `python -m ensurepip` + `pip install pytest`)。

**2026-07-01 后续加固(用户逐条复核后拍板;commit `28e459c` 等):**
- **审计日志哈希链(取代旧"逐条 HMAC")** `octopus_mobile/AuditChain.kt`:`ToolAuditLog` 与 `RemoteAccessLog` 统一改用哈希链(`signature = HMAC(payload|prevHash)` + 持久化 `headAnchor`),检测**改内容 / 删条目 / 调序 / 删最新条**。此前 `RemoteAccessLog` 完全无签名(报告漏项,用户发现);现两者对齐。旧条目 `prevHash==null` 走 legacy `HMAC(payload)` 兼容,不误判。**局限**:删最旧条(trim 边界)不可测;密钥与日志同存 KVUtils,能读密钥的本地攻击者可重算整条链(需 Android Keystore 硬件密钥,仍 deferred)。用 `java.util.Base64`(minSdk28,输出等价 android NO_WRAP)以便纯 JVM 单测。
- **用户复核结论(未改代码,合理兜底/需产品方向)**:① WS 强制 wss —— 明文只在 `KEY_OCTOPUS_ALLOW_INSECURE_RUNTIME` 开时允许 + loopback 豁免,是知情选择;真做也只该给正式托管服务器加 pinning、保留自建开关。② KVUtils 明文兜底 —— 敏感 key 默认 EncryptedSharedPreferences(AES-256-GCM),仅 Keystore 设备级损坏才退化,不该做成崩溃;顶多加降级告警。③ 群聊 ACL 按人非按会话 —— 产品决策非漏洞,要接各平台成员 API,单人设备无所谓。

Pre-existing unrelated red test: `MobileToolsTest > TapTool returns error when x missing` (requireInt throws before the a11y check; benign — `ToolRegistry` wraps execute in try/catch). Not introduced by the audit fixes.

Related: [[build-and-release]], [[web-control-console]], [[tentacle-mother-control]].

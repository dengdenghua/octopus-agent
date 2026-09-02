---
name: octopus-optimization-scan
description: "2026-06-18 agent+mobile 多代理优化扫描结果:已落地/被 Codex 挡住/待办,+ 无 JDK 约束"
metadata: 
  node_type: memory
  type: project
  originSessionId: 1d6d27c3-dc6a-43a7-97bf-65acc5304019
---

**2026-06-18 多代理优化扫描(Workflow wlg93kke9)**:对 octopus-agent + octopus-mobile 跑 12 维度只读探查 + 逐条对抗验证。**72 候选 → 34 值得做**(对抗验证杀掉一半:伪优化或刻意设计,如 `cancel_all` 无竞态、GeckoView libxul 已懒加载、`enable_adaptive` 默认关是刻意 opt-in)。报告全文:`tasks/wlg93kke9.output`。

**⚠️ 关键:Codex WIP 已扩张到 agent 核心文件**(此前还干净):`react_loop.py`(+12)、`prompt_evolver.py`(**近重写 +402−399,正在删/改 `guard_digest_provider`/`trust_score_provider` 机制 = Codex 在自己做"进化层接线"那件事**)、`react_context.py`、`bootstrap.py` 全进 WIP。→ **agent 的快赢全被挡**(A4 checkpoint 静默失败改日志、A3/A6 evolver 接 guard/trust provider、A5 judge 全路径、A8 context 同步摘要异步化),**别碰这些文件,等 Codex 收工**。剩 agent 待办(在干净文件、等树稳):A7(6 处 frontmatter 解析器合一,skill_library/skill_curator 等)、A11(Genome 定性:删 or 接进化闭环)。

**✅ mobile 已落地**(独立仓库,但也有他人 15 文件 WIP=UI/compose,已避开):
- **M2**(commit `839fb9f`):`OctopusMobileClient.onClosed/onFailure` 加 `failPendingTasks()` 清在途任务——消除跨连接泄漏 + 60s 挂起。
- **M1**(commit `ea15ad3`):`MpvController` 加 `IS_AVAILABLE=false`;`MediaTools` 对 11 个播放类操作(mpv 是 stub)返回明确 `ToolResult.error` 而非假成功 + 描述标 `[EXPERIMENTAL]`。scan/网盘列举不依赖 mpv 保留可用。

**🔧 环境约束:本机无 JDK / 无 Android Studio**(SDK 在 `~/Library/Android/sdk` 但无 java runtime)→ **无法本地编译 Android/跑 gradle**。mobile 改动靠逐行审 diff(确认合法 Kotlin + 只用已有符号 + 无新 import + 无 `-Werror`)+ CI(JDK21:assembleDebug+lintDebug+test)兜底验证。

**mobile 续作(2026-06-18,用户「继续 M3-M10」又落地)**:**M10+M11**(commit `670a709`:ChannelManager 每通道 try-catch 隔离 reinit 失败 + ShizukuShellService.exec 超时 destroyForcibly 后 join reader 线程)、**M3 安全收口**(commit `d76fefa`:`PluginManager.loadAndRegister` fail-closed 只信 `source=assets` 插件,拒绝 `installFromFile` 外部 dex——堵住 DexClassLoader 以 app 全权限执行未验证代码的 RCE 面;插件系统当前休眠;proper APK 签名校验+能力白名单待 build 环境)。**M8 跳过**:读代码发现 `buildNodeTree` 已 null-guard(入口 + child!=null),report 这条过头,只剩 stale-node try-catch 边际收益,不值得盲改。**剩待办(需 build 环境/较大,本机编不了不盲改)**:M4 Shizuku 真提权(`IUserService` bindUserService 替 `Runtime.exec` app UID)、M5/M6 浏览器 JS(GeckoView 151 删 evaluateJavascript → WebExtension / 回退 SystemWebViewEngine,`supportsEval` 字段已建未检查)、M7 BrowserTools `Thread.sleep(50)` 忙等改 Future、M9 TurnScorer executionQuality 细粒度、M12 VisionAnalyzer 去重。**本会话 mobile 共 4 commit:`839fb9f`(M2)/`ea15ad3`(M1)/`670a709`(M10+M11)/`d76fefa`(M3),全部未 push。**

相关:[[octopus-agent-ci-baseline-state]](Codex WIP 纪律 + immunity/evolution 现状)、[[octopus-ecosystem-and-os-fork]]。

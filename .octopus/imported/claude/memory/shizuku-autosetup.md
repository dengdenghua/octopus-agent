---
name: shizuku-autosetup
description: "Full-auto Shizuku pairing feature — in-app wireless-ADB (libadb) + a11y-driven pairing; stages, deps, the relocated-package gotcha"
metadata: 
  node_type: memory
  type: project
  originSessionId: 900aad5a-9593-4b2a-ac1a-12cea9e9d8da
---

正在做「**全自动配置 Shizuku**」——用户在 2026-07-04 从三档里选了最激进的「**无障碍全自动 pair**」(把十几步手动无线调试配对压成点一下+可能填个6位码)。本质=内置一个 LADB(连本机回环 ADB)+ 用 octopus 自己的无障碍服务去刮/点系统「无线调试」界面。代码在 `app/src/main/java/com/apk/claw/android/shizuku/autosetup/`。

**分 5 阶段(截至 2026-07-04):**
1. ✅ **配对信息解析** `PairingDialogParser.kt` —— 无障碍读到的一屏文本 → `PairingInfo{host,port,code}` 纯函数;7 个单测过(AOSP 中英/全角冒号/带中缝码/单行,且不会把端口误当6位码)。
2. ✅ **ADB 传输层** —— `OctopusAdbManager.kt`(`AbsAdbConnectionManager` 具体实现,RSA2048+X509 自签证书**持久化到 filesDir/adb/**,否则每次重启要重新配对)+ `ShizukuAdbStarter.kt`(挂起门面:`pair()`/`autoConnectAndStartShizuku()`/`connectAndStartShizuku()`/`disconnect()`)。编译过。
3. ✅ **技能 + 工具(替代原「硬编码无障碍编排」)** —— 用户点子:不写死各 OEM 无障碍节点,而是让**视觉 Agent** 照剧本用 look_at_screen 自适应任何 ROM。`ShizukuAutoSetupTool.kt`(工具 `shizuku_auto_setup`,action=pair/start/status,登记 HIGH 风险,过覆盖测试)+ `ShizukuAutoSetupSkill.kt`(内置技能「自动配置 Shizuku」,startup `seedIfAbsent()` 种入 PromptSkillStore,关键词命中注入系统提示词)。已在 ToolRegistry.registerSystemTools 注册。**编译+单测过,端到端需真机(登录+装Shizuku+11+)。**
4. ⏳ **向导 UI**(可选)—— `AdvancedPermissionDialog` 加个「让管家帮我开」按钮触发上面技能。**接 UI/走 release 时补 R8 keep**(`android.sun.security.**`、`io.github.muntashirakon.adb.**`、conscrypt、spake2),否则被裁/反射断。
5. ⏳ **重启善后** —— 开机检测 Shizuku 掉线一键重跑(无线调试开机失效,非 root 逃不掉)。

**依赖(JitPack,已在 settings 配好):** `com.github.MuntashirAkon:libadb-android:3.1.1`(传递 `spake2-android:2.2.1`)+ `sun-security-android:1.1` + `org.conscrypt:conscrypt-android:2.5.3`。
**关键坑:** sun-security-android 把类**重定位到 `android.sun.security.x509.*`**(不是 `sun.security.x509`),否则和 JDK java.base 撞包、编译报 "does not export"。证书生成照搬 libadb README 示例(X509CertInfo.set 反射字段名)。
**Shizuku 启动命令:** `sh /sdcard/Android/data/moe.shizuku.privileged.api/start.sh`(官方 setup 指南)。minSdk=28 → 免 PRNGFixes;单机无线配对仅 Android 11+,9/10 仍要插一次电脑。

关联 [[octopus-code-exec-feature]](Shizuku 也是设备编程的 shell 增强来源)、[[build-and-release]](R8/release 注意)。

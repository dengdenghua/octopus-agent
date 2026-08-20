---
name: accessibility-keepalive-truth
description: "无障碍\"侧滑就掉线\"排查结论:fd5d83a(enableOnBackInvokedCallback)嫌疑已证伪;confirmed 根因=af10887 双前台降级分支违反 FGS 契约(RemoteServiceException 崩溃环);发布版另有 FGS 门禁问题"
metadata: 
  node_type: memory
  type: project
  originSessionId: 900aad5a-9593-4b2a-ac1a-12cea9e9d8da
---

**排查史(三次修正,别再重蹈):** ①最早断言"ROM 级绞杀不是代码 bug"→被用户反证驳倒;②改嫌疑 fd5d83a `enableOnBackInvokedCallback`→2026-07-05 多 agent 证伪(MainActivity 无任何 BackHandler 回调,flag 前后任务根返回默认行为零差量;且侧滑清任务根本不走返回分发)。

**2026-07-05 工作流结论(6 假设独立证伪,详见该 session):**

**CONFIRMED — af10887 的双前台降级分支是确定性崩溃环(路径 B):**
`ClawAccessibilityService.onServiceConnected` 先置 `instance=this`(:45)再"双保险"调 `ForegroundService.start()`(:59)→ API26+ 走 `startForegroundService` → `onStartCommand` 见 `isRunning()==true` 进降级分支 `stopForeground(DETACH)+stopSelf`,**从不调 startForeground**(ForegroundService.kt:123-132)→ 违反 FGS 契约,AMS 发 SERVICE_FOREGROUND_CRASH_MSG → `RemoteServiceException`(异步,runCatching 拦不住)→ 进程死 → 系统重绑无障碍 → 再崩 → 反复崩溃系统自动禁用无障碍开关。KeepAliveJobService 恢复 job(:82)同样中招。修法:降级分支先 `startForeground` 再停;或 a11y 在跑时压根别 `startForegroundService`。

**PLAUSIBLE — 发布版(≤versionCode 9)的病因不同(路径 A 使能):** 初始版 `ForegroundService.start()` 被 POST_NOTIFICATIONS 门禁挡死(83b1448→429e319),A13+ 未授通知权限则 FGS 从不启动 → ROM 眼里是无 FGS 普通后台 app → 侧滑升级 force-stop 扳关开关。这解释"别的 app 不掉"(它们有真 FGS/加白);"最开始不掉"可能是早期设备授过通知权限或 ROM 差异,未完全闭合。

**已排除:** 路径 C(disableSelf/写关设置)全历史零命中;fd5d83a 预测性返回;"重度保活画像招 ROM 反制"(症状先于保活补丁存在);af10887 前的裸 startForeground 崩溃窗口(全套机器 day-one 就有,窗口仅 3h 无发布)。

**✅ 已修复并验证(2026-07-05,commit main `00eb2bd` / feat/script-sandbox-upgrade `a7f588c`):**
① 降级分支先 `startForeground` 履约再 `stopForeground(REMOVE)`+`stopSelf(startId)`(startId 防并发 start 重新武装 fgRequired);② 新增 `ClawAccessibilityService.isConnected()`(纯 instance 判断),保活决策(降级/重启闹钟/KeepAliveJob 巡检/A11ySelfHeal)全部改用它,`isRunning()` 的 enabled 列表回退只留 UI;③ onDestroy 不再停 ConfigServer(:9527 归启动方);④ ClawVpnService 通知 ID 1001→1003 防降级 REMOVE 误伤。
**模拟器实证:** 旧包(11:47 安装,含 af10887)开无障碍 10 秒内必抛 `ForegroundServiceDidNotStartInTimeException` 两连崩、重绑被罚 30 分钟(`restart in 1800000ms`);新包连接/启动/降级弹回全链路零崩溃,a11y FGS(1002)稳定在岗,`am kill` 都杀不动(BFGS 优先级)。
**How to apply:** 真机若仍复现,看掉线瞬间 logcat:`force_stop` = 路径 A(发布版 FGS 门禁病因,靠保活体检弹窗引导加白);再见 RemoteServiceException 则说明装的是未修复包。验证手法:模拟器 `settings put secure enabled_accessibility_services <组件>` + `dumpsys activity services` 看 isForeground。[[build-and-release]] 有 429e319 时代的门禁病因记录。

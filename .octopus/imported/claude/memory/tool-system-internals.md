---
name: tool-system-internals
description: 工具层关键约束:BaseTool.execute 不能改 suspend(33个Java子类+ThreadLocal取消);风险分类有漂移守护测试
metadata: 
  node_type: memory
  type: project
  originSessionId: 45bbd084-4ec6-4184-a053-49ba7472f66c
---

octopus-mobile 工具层(`tool/`)的两条关键约束,影响任何"优化/重构"决策:

**1. `BaseTool.execute()` 不能改成 `suspend`(放弃此重构)。** 三个硬约束:
- **48 个工具实现中 33 个是 Java**(`tool/impl/*.java`,如 `TapTool`/`SendSmsTool`/`InputTextTool`/全套 `tv/Dpad*`)。Java 无法 override Kotlin 的 `suspend fun`(编译成 `Continuation` 参数)→ 必须先把 33 个 Java 工具全改 Kotlin。
- **取消机制是 ThreadLocal 的**:`BaseTool.threadCancelToken` + `withCancellationToken`/`currentCancellationToken`/`checkCancelled`/`sleepInterruptible`。suspend 跨挂起点不保留 ThreadLocal,整套取消令牌要重设计成 CoroutineContext 元素。
- **`executeTool` 所有调用方本就在后台线程**(DefaultAgentService agent 循环 / ToolCallDispatcher WS / NanoHTTPD handler / ProactiveRuleEngine / BrainModeSelector),没有一个在 UI 主线程。所以"26 处 runBlocking → ANR"基本是理论风险:阻塞的是 worker 线程。给定 Java 子类 + ThreadLocal 契约,工具内 runBlocking 是合理的。AUDIT/分析报告对这一项的建议被高估。

**Why:** 看似简单的"消除 runBlocking"实为多日重写+高回归,且解决的问题不成立。

**2. 工具风险分类有「漂移守护」(2026-06-29 新增)。** `ToolRiskPolicy.riskOf()` 对未列入 HIGH/MEDIUM 的工具静默返回 LOW,而 LOW 不审计(`shouldAudit`=false)也不过高危来源闸门 → "新工具忘了分类=悄悄变低危"。`ToolRiskPolicyCoverageTest`(Robolectric)断言:每个注册工具必须显式出现在 `HIGH_RISK_TOOLS`∪`MEDIUM_RISK_TOOLS`∪`KNOWN_LOW_RISK_TOOLS`,且名单无未注册死条目(`INTENTIONAL_UNREGISTERED` 除外,目前只有 `install_app`)。**加新工具必须同步分类,否则 CI 失败。** 后续(同日)已把 9 个状态变更/外部写入工具从 LOW 上调 **MEDIUM(纳入审计,不新增拦截)**:navigate、tap_by_vision、repeat_actions、browser_navigate/click/type、create_pm_task、echo_act、echo_bind。TV 遥控键(dpad/volume/press_*)判定为真低危+高频,保留 LOW。注意:MEDIUM 只是审计;若要对远程/LAN 不可信源真正拦截(走来源闸门),需进 HIGH——那是[[security-audit-2026-06]]更大的安全 track。

**How to apply:** 改工具层先查这两点。需要异步工具时,在工具内部用 runBlocking 包 suspend 调用(现状),不要动 `execute()` 签名。新增工具记得进 ToolRiskPolicy 分类。相关:[[testing-jvm-stores]](Robolectric/JVM 测法)。

---
name: knowledge-trust-center-suite
description: 信任中心为控制台的「可控/可信/可迁移 Agent」知识管理套件（#2-#14 一整套的地图）
metadata:
  type: project
  originSessionId: 900aad5a-9593-4b2a-ac1a-12cea9e9d8da
---

2026-07 Opus 单人连做 14 根、全部单测+真机验证+已上 origin/main。信任中心(TrustCenterActivity)是控制台,`am start ...TrustCenterActivity` 可绕登录直接拉起(adb root 或 debug 可 am start 非导出 Activity)。

**知识三账本(都在 octopus_mobile,KVUtils/文件持久化,纯 JVM 可测):**
- **规矩** = `InteractionLedger` 的 manual Lesson(#7):`addManualRule` 幂等+近似去重、`removeManualRule`、`clearLessons` 保留 manual、score 对 manual 返 MANUAL_SCORE 恒最高注入。见 [[self-evolution-layer]]。
- **记忆** = `MemoryStore`(.memory 子包):`addUserFact`/`removeMemory`/`clearAll`/`getMemories`;`buildPromptSection(taskHint)` 相关性排序(#5);`addMemory` 去重含 `isSameOrSimilar`。
- **GUI 经验** = InteractionLedger 自动学的(非 manual,#2)。

**共用件:** `TextRelevance`(词项:ASCII≥4词+中文2gram+停用词)· `TextSimilarity.isNearDuplicate`(Jaccard≥0.5 或 包含度≥0.8,**保守**:淘宝/京东同结构不误合并,#14)· `KnowledgeBundle`(export/parse JSON)· `KnowledgeLocal`(gather/restore,三模态共用)。

**迁移三模态(#10-12,全走 KnowledgeLocal):** 剪贴板 · 文件(getExternalFilesDir/octopus-knowledge.json)· 局域网(`KnowledgeRouteHandler` GET /api/knowledge 发布 + `KnowledgeSync.pullFrom` 拉取,ConfigServer handlers 列表注册、Bearer 分发层统一鉴权)。

**安全/效率开关(KVUtils bool + 门):** UndoWindow 撤销窗(#3,不可逆动作 IrreversibleActions,本地在场才弹)· FrugalPerception 省流(#4,DefaultAgentService:807 每轮树优先)· DryRunGate 演示只读(#9,ToolRegistry 早挂门,改动型跳过、fail-safe 只增拦截)· ModelChain 故障转移(fallback 模型)。

**度量:** `EvolutionMetrics`(自进化)· `UsageStats`(#13,累计任务+token)· 并行加的 `AgentMetrics`(主循环计数,别重复)。都在信任中心「自进化引擎·实测效果」卡展示。

**并发同仓铁律**(这仓常有并行进程且会把树改坏):只 `git add` 自己文件、构建被并行坏文件挡住就 `git worktree add --detach <path> HEAD` + 拷未提交文件 + 拷 local.properties 隔离编译。见 [[concurrent-agent-repo-workflow]]。

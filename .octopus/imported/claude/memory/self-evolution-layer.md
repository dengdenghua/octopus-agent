---
name: self-evolution-layer
description: Agent 自进化/可靠性层的结构、有意留白的坑、接线点、已加的效果埋点
metadata: 
  node_type: memory
  type: project
  originSessionId: 900aad5a-9593-4b2a-ac1a-12cea9e9d8da
---

octopus_mobile 包下的 Agent 自进化层(母体 octopus-os 协议移植),2026-07 由并行进程起，Opus 接手补完接线+埋点+测试。**动它前先读这条，避免重复我踩的坑。**

6 模块(代码本就完整，坑在"接线"和"看走眼"):
- **ReflexArc** 反射快路径(regex→缓存)；**ImmuneSystem** 风险预检/基线(z-score)；**ExperienceLedger** 经验账本(错误→缓解注入 prompt)；**TurnScorer**(新，generate_app 质量分)；**ModelChain** 多模型故障转移；**InteractionLedger**(Opus 加，GUI 域姊妹账本，见下)。

**InteractionLedger = ExperienceLedger 的 GUI 域版**(33b5ef4)：ExperienceLedger 只管代码错误(TypeError/CSP…)+代码缓解，漏了核心的手机 GUI 自动化。InteractionLedger 收 9 类界面失败模式(找不到节点/弹窗遮挡/加载超时/输入没焦点…)→GUI 缓解。**关键:失败入账按工具域路由**(`isGuiTool` 判定)——GUI 工具→InteractionLedger、代码类→ExperienceLedger,别再把 GUI 失败塞回代码账本(那是我修掉的串味 bug)。它 `init(filesDir)` 留存目录、save 复用,**不依赖 ClawApplication.instance,故纯 JVM 可测**(区别于 ExperienceLedger)。可视化在信任中心「操作经验」卡(2d918c5,snapshot() 读、clearLessons() UI 安全清空≠测试用 reset)。

**InteractionLedger 里的用户手动规矩(3218896)**:Lesson 有 `manual` 字段。用户在信任中心「教它一条规矩」→`addManualRule`,存为 manual 规矩,`score()` 对 manual **返固定高分 MANUAL_SCORE**(永远最高优先注入 + evict 不淘汰),`getMitigationsSection` 给它加【用户规矩】前缀让 LLM 当最高指令。**注意:`clearLessons()`(UI「重置经验」)`retainAll{manual}` 只清自动学的、保留用户规矩;改 clearLessons/evict 别误删 manual**。这条完全复用已有注入钩子,零改 agent 模块。

**别踩的坑(都是"有意为之"，不是漏/错):**
- **ModelChain 是 0 引用但不是死代码** —— 注释自陈"当前单模型、架构预留多模型"。**别删**。
- **有两个 TurnScorer**：`octopus_mobile.TurnScorer`(generate_app 打分) vs `octopus_mobile.evolution.TurnScorer`(通用工具调用打分，class，AppViewModel 在用)。**领域不同，别合并**。
- **自进化层接在轻路径是设计**：`BrainModeSelector` 在 `TaskOrchestrator`(重/远程) 和 `LightweightReAct`(轻/端侧) 之间选路。

接线点(Opus 补的)：`TaskOrchestrator.onToolResult` 喂 ImmuneSystem.postResult + 失败按域 record(观测钩子，无 preCheck 因回调是事后)；`LightweightReAct` system prompt 注入 ExperienceLedger+InteractionLedger 的 getMitigationsSection() + 失败按域 record。**重路径 GUI 经验注入口 = `DefaultAgentService.buildInitialMessages`(约:807,fullSystemPrompt 末尾追加,每任务重算)**——此前重路径根本没接任何经验注入,只有轻路径和 generate_app 有。各 Ledger 是单例,同路径 record 进同一账本。

**效果埋点 = [[EvolutionMetrics]]**（新单例）：命中率/告警率/记错注入次数，logcat 搜「EvolutionMetrics:」看；TaskOrchestrator 每任务完成 persist+打印。**冲 8 分靠这个跑真机收数据**；冲 9 还缺真记忆(Room+向量，本仓无端侧ML/Room)+Skill Forge 正向回路。

**记忆相关性召回(77c98c2,Opus 加)**:`MemoryStore.buildPromptSection` 原本不吃当前任务、无差别注入(记忆多了污染 prompt)。加了 `taskHint` 参数——FACT/CONTEXT 按与任务的词项重叠排序、confidence 次之、相关的顶进有限预算;taskHint 空则完全保持原行为(向后兼容),PREFERENCE 恒在前。相关性用新的纯本地 `octopus_mobile.memory.TextRelevance`(ASCII 词+中文2-gram+停用词,照 PromptSkillStore 手法),**不走网络**(区别于走母体网关的 SemanticSkillRanker,后者离线返 null)。对话路径 ChatAgentBridge 已传 taskHint=prompt;渠道/恢复路径不传=原样。这是"真记忆"缺口的务实一刀(没上 Room+向量)。MemoryStore 靠 KVUtils 内存回退可纯 JVM 测。

测试：ImmuneSystem/ReflexArc/EvolutionMetrics 纯 JVM 可测(returnDefaultValues=true 处理 Log)；ExperienceLedger 用 org.json+ClawApplication.instance，要 Robolectric。detekt：这些新文件在带下划线的 octopus_mobile 包，非 baseline 豁免，改动会激活一堆存量样式告警，就地 `@file:Suppress` 兜底。参见 [[concurrent-agent-repo-workflow]]。

# 🧠 Cerebrum · 中枢脑

**生物原型**：章鱼的中枢脑，只占全部神经元的 1/3，专注总体规划。

## 职责
- 把用户目标分解成 `ArmTask` 序列
- 路由决策：哪条 Arm 最合适、预算分配
- 仲裁：Arm 间冲突由此裁决

## 不做
- 不直接调工具（那是 Beak 的活）
- 不读具体文件（那是 Arm 的活）

## 输入输出
- **输入**：Eyes（用户意图）+ Skin（环境信号）+ Genome（历史记忆）→ Hemolymph 打包
- **输出**：`TaskGraph`（nerves/graph 格式）+ 路由表

## 接口（草案）
```python
class Cerebrum:
    def plan(self, goal: Goal, context: ContextPacket) -> TaskGraph: ...
    def arbitrate(self, conflict: ArmConflict) -> Decision: ...
```

## 进化关联
承载 **① 长任务引擎** 的规划层（与 Ganglia、Genome/Checkpoint 协作）。

## 模型策略
用最强模型（opus-tier）— 这是省钱的"不能省"位。

## 结构图

```mermaid
flowchart TB
    intent([ParsedIntent<br/>user_context + goal])
    llmPlanner[<b>LLMPlanner</b><br/>planner_model=opus-tier<br/>prompt cache 开启]
    staticPlanner[<b>StaticPlanner</b><br/>规则驱动 / 零 LLM 依赖 / 兜底]
    learnedRules[(learned_rules_section<br/>来自 RuleExtractor)]
    learnedMems[(learned_memories_section<br/>来自 MemoryConsolidator)]
    soul[(agent.soul<br/>人格 prompt)]
    kg[(kg_section<br/>从 KnowledgeGraph 抽顶 N)]
    taskGraph([<b>TaskGraph</b><br/>DAG: nodes + edges + budget])

    intent --> llmPlanner
    intent --> staticPlanner
    learnedRules -.系统 prompt 注入.-> llmPlanner
    learnedMems -.系统 prompt 注入.-> llmPlanner
    soul -.系统 prompt 前置.-> llmPlanner
    kg -.系统 prompt 注入.-> llmPlanner
    llmPlanner --> taskGraph
    staticPlanner --> taskGraph
    taskGraph -. downstream .-> ganglia[🧬 Ganglia.run]

    classDef main fill:#4a154b,stroke:#333,color:#fff
    classDef prompt fill:#f59e0b,stroke:#333,color:#000
    class llmPlanner,staticPlanner main
    class learnedRules,learnedMems,soul,kg prompt
```

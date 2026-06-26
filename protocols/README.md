# Protocols · 协议规范索引

> 从**器官命名**下探到**可实现的协议层**：数据模型 + 伪代码 + 集成点 + 不变量。

## 现有协议（15 份规范已就位 · 实现进度见 [implementation-status.md](../docs/implementation-status.md)）

每份协议顶部 frontmatter 的 `implementation_status` 字段标记实装程度:`implemented`(已接线)/ `partial`(可选后端)/ `spec_only`(仅文档)/ `dormant`(休眠代码)。

| 协议 | 对应原则 | 核心内容 | 实装 |
|---|---|---|---|
| [digestion.md](digestion.md) | ⑥ Pipeline | 7 阶段消化流水线（INGEST → STORE）+ 阶段契约 + 回放语义 | ✅ |
| [reflex.md](reflex.md) | ① Reactive | Spinal Cord 规则格式（yaml）+ Meta-Control 决策 + Cache key 设计 | ✅ |
| [swarm.md](swarm.md) | ② Decentralized | Boids 三原则（Separation/Alignment/Cohesion）+ 优先级冲突解决 | ✅ |
| [immunity.md](immunity.md) | ③ 内生安全 | 4 层判决（Tolerance/Innate/Memory/Adaptive）+ 在线学习闭环 | ⚠️ partial |
| [evolution.md](evolution.md) | ④ 进化（行为层）| 3 条回路（正向/负向/策略）+ 夜间 Batch + Shadow→Canary→Public | ✅ |
| [distribution.md](distribution.md) | ⑤ Edge+Cloud | 三维度路由（latency/privacy/compute）+ 降级回退 + 跨 tier 消息分级 | 📄 spec_only |
| [budget.md](budget.md) | ⑥ 成本治理 | 三层护栏（Budget/Breaker/Profile）+ EMA 异常告警 + 吐墨级联 | ✅ |
| [genome.md](genome.md) | ⑦ 架构自进化 | DNA 热更新 + CRDT 合并 + Blast Zone 分级 + Registry 版本化 | ✅ |
| [skill_testing.md](skill_testing.md) | ★ 自进化保险丝 | 三层测试（Golden/Regression/Synthesized）+ 五触发点 + Critic 降档 | ✅ |
| [recipe.md](recipe.md) | ★ 上下文配方进化 | F-Recipe 层（方差+鲁棒性）+ per-task_type Thompson + Crossover 白名单 | ✅ |
| [workflow_rewrite.md](workflow_rewrite.md) | ★ 工作流自改写 | 三机制（A/B · 热替换 · 失败改写）+ 四类故障归因 + 六种改写动作 + 双证据 Shadow | ✅ |
| [conflict_resolution.md](conflict_resolution.md) | **★ 冲突消解底座** | 6 类冲突 × 6 策略 × 固定优先级 + Trust EMA + 推理 trust 上限 | 💤 dormant |
| [knowledge_graph.md](knowledge_graph.md) | **★ KG 升级** | 三元组 + 元信息 + 简化本体（3 类推理）+ Kùzu/Neo4j 可替换 | ✅ |
| [memory_consolidation.md](memory_consolidation.md) | **★ 记忆巩固（睡眠）** | 4 层分工 + 轻/重巩固 + REM 合成 + 程序性规则注入 | ✅ |
| [realtime_workbench.md](realtime_workbench.md) | **★ Realtime Workbench** | workbench snapshot current-frame 事件 + replay / refresh 恢复语义 | ✅ |

## 规范结构（每份协议统一七段）

1. **整体流程图**
2. **数据模型**（TypedDict 风格）
3. **核心算法**（伪代码）
4. **集成点**（其他器官如何调用）
5. **配置契约**（与 config.yaml 对齐）
6. **不变量**（Must-hold 性质）
7. **反模式**（明令禁止）

## 六大原则 × 核心协议覆盖矩阵

| 原则 | 协议 |
|---|---|
| ① Reactive + Deliberative | reflex.md |
| ② Swarm + Blackboard | swarm.md（+ digestion 的 DISPATCH 阶段）|
| ③ 内生安全 | immunity.md |
| ④ Variation + Selection | evolution.md |
| ⑤ Edge + Cloud | distribution.md |
| ⑥ Pipeline + 成本 | digestion.md + budget.md |

**六大原则全部落到协议层，无一缺口**。

---

## 阅读顺序建议

1. 先读 [PRINCIPLES.md](../PRINCIPLES.md) 建立原则认知
2. 再读 [ARCHITECTURE.md](../ARCHITECTURE.md) 建立器官认知
3. 再读这里的协议文档建立**可编码认知**
4. 最后 [NAMING.md](../NAMING.md) 确保写代码时名字不越界

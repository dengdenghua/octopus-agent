# 🧬 Genome · 基因组（DNA + 长时记忆）

**生物原型**：Genome 是 DNA —— 遗传信息的载体，决定个体的**结构与能力**；长时记忆是脑里的"经验刻痕"。
本模块承载两类异构数据，用子目录清晰分开。

---

## 双重内容

### 🧬 Part 1 · DNA（可编辑遗传密码）
**这是 Agent OS 最关键的一层** —— 让系统结构本身可进化，而不只是行为。

```
genome/
└── dna/
    ├── registry/     版本化 DNA 库（CRDT-backed）
    ├── mutator/      变异引擎（单字段随机调整）
    ├── crossover/    交叉引擎（多亲本合成）
    ├── selector/     选择引擎（Thompson + 精英）
    ├── patch/        Runtime 热更新（Hot/Warm/Cold/Nuclear 分级）
    └── expression/   DNA → 运行时行为的翻译层
```

📜 详见：
- [genome.md](../../genome.md) — 理论模型
- [protocols/genome.md](../protocols/genome.md) — 工程协议（CRDT / Patch / Shadow / Canary）

### 💾 Part 2 · 长时经验（"海马体"角色）
存放 trajectories、checkpoint、知识 —— 给 Regeneration 喂原料。

```
genome/
├── checkpoint/     [fork]  SQLite 分布式检查点
├── journal/        [fork]  执行事件日志
├── memory/                 长时经验（Teach-Repeat 录像带）
└── knowledge/      [fork]  Wiki + 知识图谱 + FTS5
```

---

## 为什么放一起

生物上 DNA 和记忆确实分属不同组织（细胞核 vs 脑）。
但工程上二者高度耦合：
- Genome Evolution 的 shadow 验证**需要** journal 的 trajectory 做回放
- Mutation 的 fitness 评估**需要** memory 里的长期用户满意度数据
- Regeneration 的结果既可能产新 skill（进 suckers）也可能产新 DNA（进 dna/registry）

所以按"持久化家园"统一管，用子目录清晰分类。

---

## 对外接口

```python
class Genome:
    # DNA 侧
    dna: DNAManager              # registry + mutator + crossover + selector + patch + expression

    # 记忆侧
    ckpt: Checkpointer
    journal: Journal
    memory: MemoryStore
    knowledge: KnowledgeStore
```

---

## 接入层级

| 调用方 | 用 DNA 还是记忆 |
|---|---|
| `ganglia.LocalRuntime` 断点续跑 | `ckpt` |
| `arms.Worker` 执行每步后 | `journal` |
| `cerebrum.Planner` 拉历史 | `memory` + `knowledge` |
| `regeneration.Evolver` 读素材 | `journal` + `memory` |
| `regeneration.Evolver` 写新 skill | `suckers/custom/`（不是这里）|
| `regeneration.Evolver` 写新 DNA | `dna/registry/` |
| 所有组件读当前配置 | `dna/expression/` |

---

## 进化关联

- **① 长任务引擎**：checkpoint 层
- **④ 上下文/记忆**：memory + knowledge 层
- **⑤ 反思/自进化**：journal 是原料、dna/ 是产物
- **"第七层"——架构自进化**：DNA 层（超越六大原则）

---

## 铁律

1. **DNA 侧**：任何写入必经 Schema + Shadow + Canary 三门（见 protocols/genome.md）
2. **记忆侧**：只追加、不覆盖（journal / memory）
3. **checkpoint 支持分布式 key** `(task_id, arm_id)`
4. **敏感数据（personal）** 在 memory/knowledge 存储前端加密
5. **Registry 保留最近 N=10 代 production Genome** 防雪崩无法回滚

---

## 一句话

> DNA 决定系统**能做什么**，记忆决定系统**做得好不好**。
> Genome 模块一手握 DNA，一手握记忆，共同决定这只章鱼**下一代长什么样**。

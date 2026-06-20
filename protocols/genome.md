# Protocol · Genome (DNA 热更新 · CRDT · Runtime Patch)

> 配套 [GENOME.md](../GENOME.md) 的**工程实现协议**。
> 核心挑战：**怎么让"活着的系统"吞下 DNA 更新而不死**。
> 核心不变量：**Schema 合法 + Shadow 验证 + Patch 分级 + 可回滚**。

---

## ⚠️ 代码与文档对齐说明

> 本文档描述的进化机制（Mutator / Crossover / Selector）在当前代码中由两个独立模块实现：
>
> - **Genome Registry**（`runtime/safety/recovery/genome_registry.py`）：版本化 JSON 快照存储，支持 commit / rollback / diff。**不包含**进化算法。
> - **Prompt Evolver**（`runtime/safety/experiments/prompt_evolver.py`）：实际的进化引擎，实现变异（mutation）、交叉（crossover）、Pareto 前沿选择和淘汰逻辑，操作对象为 prompt 变体。
>
> Registry 是"被进化的配置"的持久层，Evolver 是"执行进化"的计算层。两者协作但职责不同。

---

## 热更新的三道门

任何 DNA 变更必须依次通过：

```
 Schema Gate     →    Shadow Gate    →    Canary Gate    →   Production
 结构合法性           影子环境跑分         5% 灰度            全量
```

一道不过，打回 Registry 挂 `rejected` 标签。

---

## 数据模型

```python
# DNA 是 CRDT 友好的 JSON 文档；每个字段有独立 CRDT 语义
GenomeDoc = {
    "genome_id": uuid,
    "parent_ids": list[uuid],
    "fields": {
        # 标量 / 枚举：LWW Register
        "scheduler_policy": LWWRegister[str],
        "learning_rate": LWWRegister[float],

        # 集合：OR-Set
        "arm_registry": ORSet[ArmSpec],

        # 映射：LWW-Map
        "tool_affinity_map": LWWMap[str, list[str]],

        # 嵌套策略：按字段递归 CRDT
        "cortex_policy": CRDTDoc,
        "scheduler_policy_params": CRDTDoc,
        ...
    },
    "vector_clock": VectorClock,    # 分布式因果顺序
    "metadata": {
        "origin": "human" | "mutation" | "crossover" | "import",
        "created_at": datetime,
        "schema_version": str,
    },
}

PatchOp = {
    "op": "set" | "add" | "remove" | "merge",
    "path": str,                    # JSON Pointer，如 "/scheduler_policy"
    "value": Any | None,
    "vclock": VectorClock,
}

Patch = {
    "patch_id": uuid,
    "genome_from": uuid,
    "genome_to": uuid,
    "ops": list[PatchOp],
    "blast_zone": BlastZone,        # 见下
    "created_by": "mutator" | "crossover" | "human",
    "created_at": datetime,
}

BlastZone = Literal[
    "hot",        # 无感热更（learning_rate、阈值）
    "warm",       # 需 drain in-flight（scheduler_policy）
    "cold",       # 需重启部分组件（arm_registry 增删）
    "nuclear",    # 需全停重建（schema_version 升级）
]
```

---

## 1) Schema Gate（结构合法性）

每个 DNA 字段有 JSON Schema，校验不过直接拒：

```python
def schema_gate(patched: GenomeDoc) -> Verdict:
    for field, value in patched.fields.items():
        schema = FIELD_SCHEMAS[field]
        if not schema.validate(value):
            return Verdict.reject(f"schema_fail:{field}")
    # 跨字段约束
    if patched.fields["arm_registry"].contains("code") and \
       "code" not in patched.fields["tool_affinity_map"]:
        return Verdict.reject("orphan_arm_without_tools")
    return Verdict.pass_()
```

**禁止**：schema 校验放在 Shadow 之后 —— 浪费 shadow 资源。

---

## 2) Shadow Gate（影子验证）

Shadow = 拿生产最近 1000 条 trajectory 回放，用新 Genome 跑，对比 fitness。

```python
def shadow_gate(new_genome: GenomeDoc) -> ShadowReport:
    trajs = journal.sample_recent(n=1000, diverse=True)
    current_fitness = fitness_of(production_genome, trajs)
    new_fitness = fitness_of(new_genome, trajs, mode="replay")

    # 必须严格优于现有 + 显著性
    if new_fitness - current_fitness < cfg.min_fitness_gain:
        return ShadowReport.fail("no_gain")
    if p_value(current_fitness, new_fitness) > cfg.significance_threshold:
        return ShadowReport.fail("not_significant")

    # 成本上限
    if new_fitness.cost_ratio > cfg.max_cost_ratio:
        return ShadowReport.fail("too_expensive")

    return ShadowReport.pass_(delta_fitness=new_fitness - current_fitness)
```

Shadow 用 Batch API 跑，夜间集中评。

---

## 3) Canary Gate（灰度）

通过 Shadow → 进入 canary。灰度按 blast_zone 分档：

| Blast Zone | 初始灰度 | 升级步长 | 观察窗口 |
|---|---|---|---|
| hot | 5% | 10% / 次 | 1 小时 |
| warm | 1% | 2% / 次 | 6 小时 |
| cold | 0.5% | 1% / 次 | 24 小时 |
| nuclear | **禁止自动** | 必须人工审批 | — |

```python
def canary_rollout(patch: Patch):
    if patch.blast_zone == "nuclear":
        await_human_approval(patch)

    ratio = initial_ratio(patch.blast_zone)
    while ratio < 1.0:
        apply(patch, traffic_ratio=ratio)
        stats = observe_window(patch.blast_zone.window)
        if stats.fitness_delta < 0 or stats.error_rate > threshold:
            rollback(patch)
            return RolloutResult.rolled_back(stats)
        ratio = min(1.0, ratio + step(patch.blast_zone))

    return RolloutResult.promoted()
```

---

## 4) Runtime Patch（应用到活着的系统）

### Blast Zone 分级处理

```python
def apply_patch(patch: Patch, ratio: float):
    match patch.blast_zone:
        case "hot":
            hot_apply(patch, ratio)
        case "warm":
            drain_apply(patch, ratio)
        case "cold":
            rolling_restart(patch, ratio)
        case "nuclear":
            full_stop_upgrade(patch)  # 需人工
```

### Hot：无感热更（learning_rate / 阈值）

```python
def hot_apply(patch, ratio):
    # 对灰度 Arm 直接改内存值
    for arm in sample_arms(ratio):
        for op in patch.ops:
            arm.dna.apply(op)
    # 对非灰度 Arm 不动
```

### Warm：drain + 应用

```python
def drain_apply(patch, ratio):
    arms = sample_arms(ratio)
    for arm in arms:
        arm.stop_accepting_tasks()
        arm.wait_inflight_complete(timeout=60)
        for op in patch.ops:
            arm.dna.apply(op)
        arm.reload_affected_components()  # 只 reload 受影响的
        arm.resume()
```

### Cold：rolling restart

```python
def rolling_restart(patch, ratio):
    arms = sample_arms(ratio)
    for arm in arms:
        spawn_replacement(arm, new_dna=merged(arm.dna, patch))
        wait_replacement_healthy()
        retire(arm)
```

### Nuclear：禁止自动（必须人工）

---

## 5) CRDT 语义（多节点并发编辑）

Edge + Cloud 都可能独立变异。CRDT 让合并无冲突：

| DNA 字段类型 | CRDT | 合并规则 |
|---|---|---|
| `scheduler_policy` (string) | LWW Register | 最新 vclock 胜 |
| `learning_rate` (float) | LWW Register | 最新胜（不做加权平均，避免失真）|
| `arm_registry` (set) | OR-Set | 并集 + 显式 remove 记录 |
| `tool_affinity_map` (map) | LWW-Map | 按 key 独立 LWW |
| `cortex_policy.prompt_sections` | RGA (list) | 可排序序列 |

```python
def merge(local: GenomeDoc, remote: GenomeDoc) -> GenomeDoc:
    merged = {}
    for field in FIELD_SCHEMAS:
        crdt_type = CRDT_TYPE_OF[field]
        merged[field] = crdt_type.merge(local.fields[field], remote.fields[field])
    # 合并后必须过 Schema Gate
    if not schema_gate(merged).passed:
        raise CRDTMergeError("invalid after merge")
    return merged
```

**禁止**：用手写的"最新时间戳覆盖"替代 CRDT —— 跨 tier 时钟偏移必翻车。

---

## 6) Registry（版本仓库）

```
genome/dna/registry/
├── v0000_genesis.json        # 启动时从 config.yaml 生成
├── v0001_abcd.json           # mutator 产出
├── v0002_ef12.json           # crossover 产出
├── HEAD.json → v0001_abcd    # 当前 production
├── CANARIES/
│   └── v0002_ef12 → 5%        # 当前灰度中
└── RETIRED/
    └── v0000_genesis.json    # 归档
```

**操作**：
- `registry.commit(genome)` — 写入新版本
- `registry.head()` — 当前 production
- `registry.rollback(target)` — 一键回滚（必须 vclock ≤ HEAD）
- `registry.diff(v1, v2)` — 字段级 diff

---

## 7) Mutator / Crossover / Selector（进化引擎）

### Mutator

```python
def mutate(parent: GenomeDoc, rng: Random) -> GenomeDoc:
    # 只动一个字段，便于归因
    field = rng.weighted_choice(MUTABLE_FIELDS, weights=FIELD_MUTATION_PRIORS)
    operator = FIELD_MUTATION_OPERATORS[field]
    new_value = operator.sample(current=parent.fields[field], rng=rng)
    child = parent.copy()
    child.fields[field] = new_value
    child.genome_id = uuid4()
    child.parent_ids = [parent.genome_id]
    child.metadata.origin = "mutation"
    return child
```

### Crossover

```python
def crossover(a: GenomeDoc, b: GenomeDoc, rng: Random) -> GenomeDoc:
    child = empty_genome()
    for field in MUTABLE_FIELDS:
        src = rng.choice([a, b])
        child.fields[field] = src.fields[field].clone()
    child.parent_ids = [a.genome_id, b.genome_id]
    child.metadata.origin = "crossover"
    return child
```

### Selector

```python
def select_next_generation(candidates: list[GenomeDoc]) -> list[GenomeDoc]:
    scored = [(g, fitness_of(g)) for g in candidates]
    scored.sort(key=lambda x: -x[1])

    # 精英策略：top-K 直接进
    elites = [g for g, _ in scored[:cfg.elite_k]]

    # 锦标赛：其余按 Thompson Sampling 选
    rest = thompson_sample([g for g, _ in scored[cfg.elite_k:]], n=cfg.tournament_n)

    return elites + rest
```

---

## 集成点

| 时机 | 调用方 | API |
|---|---|---|
| 启动 | `config.yaml` → `registry` | 写入 v0000_genesis |
| 夜间回路 | `regeneration` → `mutator` + `crossover` | 产出候选 |
| 影子评估 | `regeneration` → `shadow_gate` | Batch 跑分 |
| 灰度 | `regeneration` → `canary_gate` | 按 blast_zone 放量 |
| 运行时应用 | `canary_gate` → `expression` | apply_patch |
| 回滚 | admin / fitness regression → `registry` | rollback |
| 跨节点合并 | `nerves.bus` → `crdt.merge` | 各 Edge 节点的本地变异合并 |

---

## 配置契约

```yaml
genome:
  mutation:
    per_generation_count: 10
    field_priors:
      learning_rate: 0.3
      scheduler_policy: 0.1
      memory_policy: 0.1
      arm_registry: 0.05              # 少变，风险大
  crossover:
    parents: 2
    per_generation_count: 5
  shadow:
    sample_size: 1000
    min_fitness_gain: 0.03            # 3% 提升起步
    significance_threshold: 0.05
    max_cost_ratio: 1.2
  canary:
    initial_ratio:
      hot: 0.05
      warm: 0.01
      cold: 0.005
      nuclear: 0                      # 禁止自动
    window_hours:
      hot: 1
      warm: 6
      cold: 24
  registry:
    max_history: 500
    retired_kept: 50
  crdt:
    vector_clock_pruning_days: 30
```

---

## 不变量

1. **I1 · 三门必过**：Schema → Shadow → Canary 缺一不可
2. **I2 · Nuclear 不自动**：schema_version 升级必须人工批准
3. **I3 · 回滚永远可行**：上一代 production Genome 不得被删
4. **I4 · CRDT 合并后必 Schema 校验**：避免合并出畸形 DNA
5. **I5 · 变异一次一字段**：多字段变异不可归因，禁用
6. **I6 · Genome 变更必入 Journal**：完整可审计
7. **I7 · Patch 不可逆操作标 nuclear**：比如 `arm_registry` 的 remove 是 nuclear，不是 cold
8. **I8 · Production 至少保留 N 代**：默认 N=10，防雪崩回滚不回

---

## 可观测性

| Metric | 用途 |
|---|---|
| `genome.active_version` | 当前 HEAD |
| `genome.canary_count` | 灰度中版本数 |
| `genome.fitness_history` | 代际 fitness 曲线 |
| `genome.shadow_pass_rate` | Shadow 通过率 |
| `genome.canary_rollback_count` | 灰度失败次数 |
| `genome.crdt_merge_conflicts` | CRDT 合并冲突数（应极少）|
| `genome.patch_latency_p99{blast_zone}` | 各档应用延迟 |
| `genome.nuclear_approval_pending` | 待人工审批的 nuclear 变更数 |

### 警戒线
- `shadow_pass_rate < 5%` → mutation 操作器太激进，缩小步长
- `canary_rollback_count / canary_count > 30%` → fitness 函数可能有漏洞
- `crdt_merge_conflicts > 0` → 必排查（理论应为 0）

---

## 反模式

- ❌ 把用户的 API key 放进 Genome（不可变异的密钥属于 config，不是 DNA）
- ❌ Nuclear 变更自动灰度（schema 升级必须人工）
- ❌ 多字段同时变异（不可归因，像"进化遗传病"）
- ❌ 回滚时丢弃 canary 观察数据（这些是学习素材）
- ❌ CRDT 用"最后写入赢"替代向量时钟（跨 Edge 时钟偏移翻车）
- ❌ 把 Fitness 权重写死成常量（权重自己也应该进化）
- ❌ Shadow 用实时 API 评分（成本爆炸）

---

## 从"可进化行为"到"可进化架构"的断层

| 维度 | Regeneration (已有) | Genome Evolution (本协议) |
|---|---|---|
| 动的对象 | skill / rule / prompt | scheduler / topology / registry |
| 变化速度 | 日级 | 周级 |
| 风险 | 单 sucker 崩 | 整个系统重排 |
| 验证粒度 | 单 skill shadow | 全系统 trajectory 重放 |
| 回滚 | retire 单 skill | 版本化 HEAD 回退 |

两者通过 `regeneration/evolver/` 主流水线协同：每晚先跑 Regeneration（便宜、风险低），再跑 Genome Evolution（贵、谨慎）。

---

## 一句话总结

> **Genome 是把"系统设计决策"做成"可版本化、可变异、可回滚的数据"。**
> 这一层做到了，Agent OS 才算跨过"工程产品 → 可进化实体"的门槛。

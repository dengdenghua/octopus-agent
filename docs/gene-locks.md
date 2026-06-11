# GENE_LOCKS · 基因锁系统

> GENOME 让 DNA 可编辑；**基因锁决定哪些位点不允许系统自己编**。
>
> 核心判断：
> **三门（Schema / Shadow / Canary）守的是"合不合法"；
> 基因锁守的是"该不该自己来改"。**
>
> 没有基因锁 = 给了系统 sudo 权限还让它自我修改 shell，早晚把自己锁出去。

---

## 1. 生物学双源头

### 源 A · 表观遗传锁（科学的）
- **甲基化沉默**：基因在但永远不表达
- **印记基因**：只有来自父亲或母亲的版本能被激活
- **Tumor suppressor genes**：关闭需要多重保险机制同时失效
- **发育锁**：某些基因只在特定生命阶段表达

### 源 B · Sci-fi 基因锁（隐喻的）
- 系统按"成熟度"分级，每级解锁更核心的能力
- 能力越大，解锁门槛越高
- 越级解锁 = 器官崩溃

两个源头对应 **两类机制**：
- 源 A → **字段级锁**（§3）：静态规则，守某些位点
- 源 B → **成熟度锁**（§4）：动态门禁，守系统阶段

---

## 2. 为什么这层不能省

现有防御里已经有：
- Schema Gate（结构合法）
- Shadow Gate（跑分超过现状）
- Canary Gate（灰度不崩）
- Nuclear Approval（人工批大变更）

但它们都解不了这几种攻击面：

| 攻击姿势 | 现有防御为何失效 |
|---|---|
| **优化器逃逸**：系统发现降低自己的风险阈值能拿高分，于是 shadow 绿灯放行 | Shadow 只看短期 fitness，不看"是否削弱自身防御" |
| **价值观漂移**：权重一点点改、每次都在 drift 阈值内，半年后面目全非 | Drift 是速率守卫，不是方向守卫 |
| **权限越界**：系统把自己的 `self_whitelist` 扩大后就能任意调用危险 sucker | 免疫 Tolerance 自己就在 DNA 里，可被变异 |
| **回滚防线拆除**：系统把 `production_keep_n` 改成 1，然后做坏事再覆盖历史 | Registry 保留规则也在 DNA 里，可自我修改 |

**结论**：某些 DNA 字段**必须 bootstrapping 自外部**，永远不能被系统自己改。这就是基因锁。

---

## 3. 六类锁（字段级）

### Lock-1 · IMMUTABLE 永久锁

- **写一次、终身不可改** —— 连 nuclear 审批都不能改
- 要改 = 杀当前实例，重新 genesis 一条新 Genome（带新 `genome_id`）
- **适用**：`genome_id`、`origin_signature`、`schema_version_minimum`、核心 `invariants_version_pin`

```python
IMMUTABLE_FIELDS = {
    "genome_id",
    "origin_signature",
    "schema_version_minimum",   # 不允许下降到低版本
    "invariants_version_pin",   # 绑定 invariants.md 的版本号
    "lock_system_version",      # 本文档自身的版本，锁住基因锁系统不被改
}
```

### Lock-2 · MONOTONIC 单向锁

- 只允许朝"更严格"方向自主变，反向需人工
- **适用**：所有安全与成本相关的字段

| 字段 | 允许方向（自主）| 反向（需人工）|
|---|---|---|
| `risk_profile` | `loose → balanced → strict` | 放松 |
| `immunity.sensitivity` | 提高 | 降低 |
| `ink.per_task.max_cost_usd` | 调低 | 调高 |
| `distribution.personal_egress` | 收紧 | 放宽 |
| `hearts.branchial.timeout_ms` | 缩短 | 延长 |
| `genome.registry.production_keep_n` | 增大 | 减小 |

**不变量**：自主变异器只能产出 monotonic-方向的 patch；反向一律打 `nuclear` 标。

### Lock-3 · QUORUM 多方共识锁

- 需要 M-of-N 审批（通常 2-of-3 或 3-of-5）
- 与单人 nuclear 的区别：**单人无权决定**
- **适用**：不可逆 + 影响面大的操作

```yaml
quorum_locked_fields:
  immunity.trusted_sources:
    add:     {m: 2, n: 3, reviewers: [security_admin, ops_admin, product_admin]}
    remove:  {m: 1, n: 3}   # 移除比添加容易
  fitness.weights:
    any_change: {m: 2, n: 3, reviewers: [data_admin, product_admin, ethics_officer]}
  genome.dna.patch.nuclear:
    any:      {m: 3, n: 5}
  arms.registry.remove:
    any:      {m: 2, n: 3}
```

**实现**：每个审批者独立签名；不足阈值不合并。

### Lock-4 · LEVEL 成就解锁锁

- 字段**默认锁**，系统达到某"成熟度等级"后自动解锁
- 见 §4 的成熟度等级系统

### Lock-5 · CONDITIONAL 条件锁

- 依赖**当前系统状态**决定能否变
- **适用**：动态风险门

| 字段 | 解锁条件 |
|---|---|
| `learning_rate > 0.5` | `budget.usage_ratio < 0.8` 且当日 `squirt_count == 0` |
| `arm_registry.add` | 当前 `canary_count < 3` 且无未解决 P0 |
| `nuclear_operations` | 非业务高峰时段（本地 23:00–06:00）|
| `cortex_policy.planner_model` 降档 | `F-Genome ≥ 0.85` 持续 14 天 |

### Lock-6 · TEMPORAL 冷却锁

- 同一字段**最小间隔时间**内不得重复变异
- **适用**：策略层，防抖动

| 字段 | 最小冷却 |
|---|---|
| `scheduler_policy` | 24h |
| `memory_policy` | 12h |
| `tool_affinity_map[*]` | 6h |
| `learning_rate` | 1h |

### Lock-7 · CASCADE 级联锁

- 改字段 A 会临时锁住字段 B 一段时间，让效果可归因
- **适用**：相互耦合的策略对

```yaml
cascade_locks:
  scheduler_policy:
    locks: [hearts.systemic.tick_interval_ms, hearts.branchial.timeout_ms]
    duration_days: 7            # 改完 scheduler 后 7 天内这两个不准动
  immunity.sensitivity:
    locks: [immunity.adaptive.quarantine_threshold]
    duration_days: 14
```

这和 GEN-I5（单字段变异）互补：GEN-I5 管"一次只动一个"，CASCADE 管"动完之后旁边的也先别动"。

---

## 4. 成熟度等级系统（Lock-4 的展开）

**不按时间，按证据**。每升一级解锁更核心的 DNA 能力。

### Level 0 · 新生体（Hatchling）
**默认态**。所有自主进化**禁用**。
- 可做：config.yaml 手动编辑、人工审批下的 Regeneration
- 不可做：任何 mutator / crossover 自动产出
- 解锁条件：无（手动按钮 → Level 1）

### Level 1 · 幼体（Juvenile）
**基础进化解锁**。
- 解锁：hot-path mutation（`learning_rate`、阈值类参数）
- 仍锁：warm / cold / nuclear 类
- 晋级门槛：
  - 连续 7 天无 P0/P1 incident
  - 累计 ≥ 20 次 Regeneration 成功晋升
  - F-Trajectory 7 日均值 ≥ 0.70

### Level 2 · 少年体（Adolescent）
**策略层进化解锁**。
- 解锁：warm-path mutation（`scheduler_policy`、`memory_policy`）
- 解锁：Regeneration 自动晋升 skill 到 public
- 仍锁：`arm_registry` 增、`crossover`、新 sucker 自动锻造
- 晋级门槛：
  - 连续 30 天无 P0/P1
  - F-Genome ≥ 0.75 持续 14 天
  - Drift 7 日均值 ∈ [0.02, 0.10]

### Level 3 · 成体（Adult）
**拓扑进化解锁**。
- 解锁：`arm_registry.add`（但 `remove` 仍 Quorum 锁）
- 解锁：Crossover 产出新 Genome
- 解锁：Skill Forge 全自动（shadow → canary → public 全链自动）
- 仍锁：nuclear 级 schema 升级、`arm_registry.remove`、`immunity.trusted_sources` 变更
- 晋级门槛：
  - 连续 90 天无 P0、≤ 2 P1
  - F-Genome ≥ 0.85 持续 30 天
  - Meta-fitness 连续 3 个月不下降
  - 人工 approval（Quorum 2/3）

### Level 4 · 完全体（Mature）
**架构自治**。
- 解锁：自主合成新 Arm 类型（以前只能从预设 registry 选）
- 解锁：自主调整 fitness 权重（Fitness-of-Fitness 闭环）
- **不存在**"全部解锁" —— IMMUTABLE 永不解锁、QUORUM 永不降为单签
- 晋级门槛：
  - 连续 180 天零 P0/P1
  - Meta-fitness 稳定收敛
  - 人工 approval（Quorum 3/5）
  - **且必须有明确降级预案**（详见 §6）

### 降级机制

等级不是单调上升。一旦发生：
- P0 事故 → **立即降 1 级**（冷却 30 天不得再晋）
- P1 事故 3 次累积 → 降 1 级
- Drift > 0.30 连续 3 天 → 降 1 级
- 人工触发 → 直接降到指定等级

**降级是自动的、快速的、难以逆转的**。这是系统可信度的核心基建。

---

## 5. Lock 数据模型

```python
LockSpec = {
    "field_path": str,                # JSON Pointer，如 "/immunity/trusted_sources"
    "lock_types": list[LockType],     # 可叠加多个锁
    "immutable": bool,
    "monotonic": MonoDirection | None,
    "quorum": QuorumPolicy | None,
    "required_level": int,            # Lock-4 成熟度
    "conditions": list[Condition],    # Lock-5
    "cooldown_seconds": int,          # Lock-6
    "cascade_locks": list[str],       # Lock-7
    "cascade_duration_days": int,
}

MutationVerdict = {
    "allowed": bool,
    "reason": str,
    "locks_hit": list[LockSpec],
    "required_actions": list[str],    # "nuclear_approval" | "quorum_2of3" | "wait_until_X"
}
```

---

## 6. Lock Check 流水线

所有 mutator/crossover/patch 操作必须先过此流水线：

```python
def gate(patch: Patch) -> MutationVerdict:
    results = []

    # 1. IMMUTABLE
    for op in patch.ops:
        spec = lock_specs[op.path]
        if spec.immutable:
            return Verdict.deny("immutable", [spec])

    # 2. LEVEL（成熟度）
    current_level = maturity.current_level()
    for op in patch.ops:
        spec = lock_specs[op.path]
        if current_level < spec.required_level:
            return Verdict.deny(f"requires_level_{spec.required_level}", [spec])

    # 3. MONOTONIC
    for op in patch.ops:
        spec = lock_specs[op.path]
        if spec.monotonic and not mono_direction_ok(op, spec):
            results.append(("need_human_approval_for_reverse", spec))

    # 4. CONDITIONAL
    for op in patch.ops:
        spec = lock_specs[op.path]
        for cond in spec.conditions:
            if not cond.satisfied():
                return Verdict.deny(f"condition_not_met:{cond.name}", [spec])

    # 5. TEMPORAL
    for op in patch.ops:
        spec = lock_specs[op.path]
        if time_since_last_change(op.path) < spec.cooldown_seconds:
            return Verdict.deny(f"cooldown_active:{spec.cooldown_seconds}s", [spec])

    # 6. CASCADE
    for op in patch.ops:
        for locked_field in active_cascade_locks():
            if op.path == locked_field:
                return Verdict.deny(f"cascade_locked_until:{cascade_expiry(locked_field)}", [])

    # 7. QUORUM
    for op in patch.ops:
        spec = lock_specs[op.path]
        if spec.quorum and not quorum_satisfied(patch, spec.quorum):
            return Verdict.need_quorum(spec.quorum)

    return Verdict.allow()
```

**流水线顺序固定**：IMMUTABLE → LEVEL → MONOTONIC → CONDITIONAL → TEMPORAL → CASCADE → QUORUM。
前面的锁一旦失败立即短路返回，不进入后续检查（省时 + 避免暴露系统内部状态）。

---

## 7. 紧急解锁（Panic Override）

基因锁是严格的；但现实里总有"必须马上改"的场景（安全漏洞、合规强制令）。

```yaml
panic_override:
  enabled: true
  approval: quorum_3_of_5
  allowed_actions:
    - downgrade_maturity_level
    - force_patch_any_field_except_immutable
    - emergency_rollback_genome
  audit:
    notify: [cto, security_lead, ethics_officer]
    journal: true
    public_log: true           # 写入公开审计日志（人工检视）
  post_override_cooldown_days: 30  # 使用后 30 天不得再 override
```

**铁律**：
1. panic override 不能改 IMMUTABLE 字段（杀进程重建才能改）
2. override 后系统**自动降到 Level 1**（需要重新证明自己）
3. 每次 override 都是公开审计事件

---

## 8. 与现有协议的挂接

### 与 GENOME / protocols/genome.md 的集成

```python
# 原协议流水线
def patch_submit(patch):
    schema_gate(patch)      # 原有
    shadow_gate(patch)      # 原有
    canary_gate(patch)      # 原有
    apply_patch(patch)

# 新流水线（基因锁加在最前）
def patch_submit(patch):
    lock_gate(patch)        # ★ 新增：基因锁优先
    schema_gate(patch)
    shadow_gate(patch)
    canary_gate(patch)
    apply_patch(patch)
```

`lock_gate` 在三门之前执行 —— **连 schema 都轮不到检查**，直接被锁挡回。
原因：锁不通过的 patch 进 shadow 就是浪费资源。

### 与 IMMUNITY 的互锁

- `immunity.trusted_sources` 在 QUORUM 锁下（只能多签改）
- `immunity.memory.attack_db` 只允许删除特定条目（需双人签），无整库清理接口
- 新发现的攻击模式写入时绕过 QUORUM（只有学习加条目，不是人工改）

### 与 BUDGET 的互锁

- `ink.per_task.max_cost_usd` 在 MONOTONIC 锁下（调低自主、调高 Quorum）
- `ink.circuit_breaker.*` 全部 MONOTONIC（只允许更敏感，不允许更宽松）

### 与 FITNESS 的互锁

- `fitness.weights` 全部 QUORUM 锁
- `fitness.drift.reject_threshold` MONOTONIC（可调小不可调大）
- 权重调整必须**同时经过 Fitness-of-Fitness 验证**

---

## 9. 新增 Cross-cutting 不变量（补 invariants.md）

### CC-G1 · 锁门在所有门之前
**参与方**：GENE_LOCKS + GEN-I1（三门）
**描述**：`lock_gate` 必在 schema / shadow / canary 之前执行。
**Runtime Gate**。

### CC-G2 · IMMUTABLE 永不可变
**参与方**：GENE_LOCKS + GEN-I3（回滚）
**描述**：即使回滚到旧 Genome，IMMUTABLE 字段值也不回滚（它们应该一致；不一致则拒绝回滚）。
**Schema enforce**。

### CC-G3 · 成熟度等级降级自动且不可快速回升
**参与方**：GENE_LOCKS + FITNESS drift
**描述**：P0/P1 事故触发自动降级；再晋级必须经过"冷却期"重新证明。
**Runtime Assert**。

### CC-G4 · Monotonic 方向只能自主朝严、放松必人工
**参与方**：GENE_LOCKS + IMM + BDG
**描述**：所有安全/成本字段自主变异只能朝保守方向；反向变异一律降级为 Quorum 或 Nuclear。
**Runtime Gate + Schema enforce**。

### CC-G5 · Panic override 自动降级
**参与方**：GENE_LOCKS + CC-7（人工门）
**描述**：使用 panic override 后，系统自动降到 Level 1 并进入 30 天冷却。
**Runtime Assert**。

---

## 10. 反模式

| 反模式 | 后果 | 破解 |
|---|---|---|
| 把 `trusted_sources` 放在 hot-path lock | 攻击可快速扩大白名单 | 必 QUORUM |
| 让系统自己改自己的 lock_spec | 锁可被自己解 | `lock_spec` 本身 IMMUTABLE |
| Panic override 不降级 | 变成日常后门 | 必自动降到 Level 1 + 冷却 |
| 等级晋升只看时间 | 不表达成熟度 | 必须要 fitness + incident-free 双证据 |
| Monotonic 允许系统自己 toggle 方向 | 单向锁失效 | 反向一律人工 |
| Quorum 签名放在同一主机 | 单点失陷全签 | 必跨机器 / 跨人 / 跨组织 |
| 解锁后不下 cascade 锁 | 多变量混淆 | CASCADE 必跟 LEVEL 成对 |

---

## 11. 配置契约

```yaml
gene_locks:
  enabled: true
  current_maturity_level: 0          # 启动默认 Level 0
  lock_system_version: "1.0"         # IMMUTABLE 字段
  immutable_fields:
    - genome_id
    - origin_signature
    - schema_version_minimum
    - invariants_version_pin
    - lock_system_version
  monotonic:
    risk_profile: {direction: stricter}
    immunity.sensitivity: {direction: higher}
    ink.per_task.max_cost_usd: {direction: lower}
    ink.circuit_breaker.consecutive_failures: {direction: lower}
    genome.registry.production_keep_n: {direction: higher}
  quorum:
    immunity.trusted_sources.add: {m: 2, n: 3}
    fitness.weights: {m: 2, n: 3}
    arms.registry.remove: {m: 2, n: 3}
    nuclear_operations: {m: 3, n: 5}
  conditional:
    arm_registry.add:
      require: ["canary_count<3", "no_p0_24h"]
    nuclear_operations:
      require: ["local_time.between(23,6)"]
  temporal:
    scheduler_policy: 86400           # 24h
    memory_policy: 43200              # 12h
    learning_rate: 3600               # 1h
  cascade:
    scheduler_policy:
      locks: [hearts.systemic.tick_interval_ms, hearts.branchial.timeout_ms]
      duration_days: 7
  maturity:
    promotion:
      level_0_to_1: {stable_days: 7, successful_regen: 20, min_f_traj: 0.70}
      level_1_to_2: {stable_days: 30, min_f_genome: 0.75, drift_range: [0.02, 0.10]}
      level_2_to_3: {stable_days: 90, min_f_genome: 0.85, p0_count: 0, p1_count_max: 2}
      level_3_to_4: {stable_days: 180, meta_fitness_stable_months: 3, quorum: {m: 3, n: 5}}
    demotion:
      p0: auto_minus_one_level
      p1_cumulative_3: auto_minus_one_level
      drift_persistent_high: auto_minus_one_level
      post_demotion_cooldown_days: 30
  panic_override:
    enabled: true
    quorum: {m: 3, n: 5}
    post_override_level: 1
    post_override_cooldown_days: 30
```

---

## 12. 一句话总结

> **三门（Schema/Shadow/Canary）问的是"这个变异能跑吗"；
> 基因锁问的是"这个变异你配改吗"。**
>
> 没有基因锁的 Agent OS = 给了 root 权限的实验动物。
> 有基因锁 = **系统必须通过持续证明可信，才能逐步获得改写自己的权力**。

这是 Agent OS 从"可进化实体" 走向 "**可信任的自治实体**" 的最后一公里。

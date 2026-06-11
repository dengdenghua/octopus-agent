# Protocol · Swarm (群体协作 · Boids 三原则)

> **原则 ② 去中心协作** 的具体算法。
> Chromatophores 的第二层语义：**腕间涌现秩序**，不靠中枢仲裁。
> 核心不变量：**所有 Boids 规则纯函数 + 本地执行 + 无全局锁**。

---

## Boids 三原则简述

| 原则 | 生物原型 | 触发条件 | 动作 |
|---|---|---|---|
| **Separation 避撞** | 鱼群防碰撞 | 同一资源被多腕宣称 | 低优先级腕退让 + 本地回滚 |
| **Alignment 对齐** | 鸟群同向 | 多腕收到相同目标 | 按 affinity 分片，同 tick 启动 |
| **Cohesion 聚合** | 蜂群向后蜂靠拢 | 腕连续 idle | 主动向最忙任务簇靠拢 |

三规则互斥又互补：Separation > Alignment > Cohesion（冲突时前者胜）。

---

## 数据模型

```python
ResourceClaim = {
    "claim_id": uuid,
    "arm_id": str,
    "resource_uri": str,              # "file://...", "mcp://..", "shared_state://blackboard/k"
    "priority": int,                  # 0..100，越大越优先
    "ttl_ms": int,
    "claimed_at": datetime,
}

ResourceVerdict = Literal["win", "lose", "coexist"]

Goal = {
    "goal_id": uuid,
    "description": str,
    "affinity_tags": list[str],       # 决定分片维度
    "broadcast_ts": datetime,
}

GoalAssignment = {
    "goal_id": uuid,
    "arm_id": str,
    "shard_key": str,
    "sync_tick": int,                 # 统一 tick 对齐启动
}

TaskPointer = {
    "task_id": uuid,
    "busy_cluster_id": str,           # 当前最忙的任务簇
    "suggested_role": str,            # "helper" | "learner" | "watcher"
}
```

---

## 1) Separation 避撞

```python
def separation(claim: ResourceClaim) -> ResourceVerdict:
    existing = blackboard.get_claims(claim.resource_uri)

    # 无冲突
    if not existing:
        blackboard.put_claim(claim)
        return "win"

    # 完全相同的 arm 重复宣称 → 幂等
    if any(c.arm_id == claim.arm_id for c in existing):
        return "win"

    # 优先级决策
    winner = max(existing + [claim], key=lambda c: (c.priority, c.claimed_at))
    if winner.arm_id == claim.arm_id:
        # 新晋赢家：通知老赢家回滚
        for c in existing:
            chromatophores.publish("claim.preempt", arm_id=c.arm_id, resource=c.resource_uri)
        blackboard.put_claim(claim, replace=True)
        return "win"
    else:
        # 对资源类型决定 coexist 可行性
        if is_readonly_resource(claim.resource_uri):
            blackboard.add_coexisting_claim(claim)
            return "coexist"
        return "lose"
```

### 优先级计算
```python
def priority_of(arm, task) -> int:
    # 影响因子（各占权重，sum = 100）
    return int(
        30 * task.urgency                      # 0..1
        + 25 * (1 - arm.current_load)          # 空闲腕优先
        + 25 * arm.affinity_match(task)        # 匹配度
        + 20 * arm.recent_success_rate
    )
```

### 退让动作
```python
def on_preempt(resource_uri):
    # 1. 停止相关步骤
    current_step.cancel()
    # 2. 回滚本地状态（sandbox 层面）
    mantle.rollback_last_checkpoint()
    # 3. 广播 idle，进入 Cohesion 阶段
    chromatophores.publish("arm.idle", arm_id=self.id)
```

---

## 2) Alignment 对齐

多腕收到同一目标（如 Cerebrum 广播"索引整个仓库"）时，避免**串行重复劳动**。

```python
def alignment(goal: Goal, arms_available: list[Arm]) -> list[GoalAssignment]:
    # 按 affinity 分片
    shards = shard_by_affinity(goal, arms_available)

    # 计算下一个统一的 sync_tick（所有腕同 tick 启动）
    sync_tick = hearts.systemic.current_tick() + cfg.sync_window_ticks

    assignments = []
    for shard_key, arm in shards.items():
        a = GoalAssignment(
            goal_id=goal.goal_id,
            arm_id=arm.id,
            shard_key=shard_key,
            sync_tick=sync_tick,
        )
        blackboard.put_assignment(a)
        chromatophores.publish("goal.aligned", assignment=a)
        assignments.append(a)
    return assignments


def on_sync_tick(tick):
    # 每腕各自在 sync_tick 启动自己的 shard
    for a in blackboard.assignments_for_arm(self.id):
        if a.sync_tick == tick:
            self.start_shard(a)
```

### 分片策略
```python
def shard_by_affinity(goal, arms) -> dict[str, Arm]:
    # 例：index whole repo → 按目录分片
    # 例：scrape 1000 URLs → 按 hash 分片
    shards = auto_shard(goal)         # LLM 或规则决定分法
    arms_sorted = sorted(arms, key=lambda a: -a.affinity_match(goal))
    return {shards[i]: arms_sorted[i % len(arms_sorted)] for i in range(len(shards))}
```

---

## 3) Cohesion 聚合

腕连续 idle 时主动"靠拢"最忙任务簇 —— 帮忙 or 学习。

```python
def cohesion(arm: Arm) -> TaskPointer | None:
    # 空闲不足 N 个 tick，继续待命
    if arm.idle_ticks < cfg.idle_threshold_ticks:
        return None

    # 找出当前最忙任务簇
    clusters = blackboard.current_task_clusters()
    if not clusters:
        return None
    busy = max(clusters, key=lambda c: c.active_arms_count)

    # 决定角色
    if busy.can_accept_helper() and arm.affinity_match(busy.primary_task) > 0.5:
        role = "helper"
    elif busy.primary_task.allow_observation:
        role = "learner"
    else:
        role = "watcher"

    pointer = TaskPointer(task_id=busy.primary_task.id,
                         busy_cluster_id=busy.id,
                         suggested_role=role)
    chromatophores.publish("arm.cohered", arm_id=arm.id, pointer=pointer)
    return pointer
```

### Helper 行为
当腕作为 helper 加入现有任务簇：
- 不重新规划（复用 cluster 的现有 TaskGraph）
- 只领剩余未认领 shard
- 失败不升级为簇级失败（隔离爆炸半径）

### Learner 行为
当腕作为 learner：
- 只读 observe 簇的 trajectory
- 结果直接落 genome/memory（供 Evolution）
- 不影响簇本身

---

## 优先级与冲突解决

```
冲突场景：
  A: Separation 让我退让
  B: Alignment 说我该启动
  C: Cohesion 说我该去帮忙

解决顺序：
  Separation (硬约束) > Alignment (协同约束) > Cohesion (软约束)
```

```python
def decide_next_action(arm):
    if arm.has_preempt_signal():
        return on_preempt(arm.resource_uri)
    if assignment := blackboard.get_assignment(arm.id):
        if hearts.systemic.current_tick() >= assignment.sync_tick:
            return arm.start_shard(assignment)
    if pointer := cohesion(arm):
        return arm.follow_pointer(pointer)
    return arm.wait_tick()
```

---

## 集成点

| 时机 | 调用方 | API |
|---|---|---|
| 资源使用前 | `arms.Worker` → `chromatophores` | `separation(claim)` → `Verdict` |
| 收到 Preempt 事件 | `chromatophores` → `arms.Worker` | `on_preempt()` |
| 目标广播 | `cerebrum` → `chromatophores` | `alignment(goal, arms)` |
| Sync tick | `hearts.systemic` → `arms.Worker` | `on_sync_tick(tick)` |
| 每 tick idle 检查 | `arms.Worker` → `chromatophores` | `cohesion(arm)` |

---

## 配置契约

```yaml
chromatophores:
  boids:
    separation:
      resource_claim_ttl_ms: 5000
      preempt_cooldown_ms: 1000
    alignment:
      sync_window_ticks: 2           # 分片后多少 tick 对齐启动
      shard_strategy: auto           # auto | hash | manual
    cohesion:
      idle_threshold_ticks: 10
      max_helpers_per_cluster: 3
      learner_mode: observe_only
```

---

## 不变量

1. **I1 · 纯函数 + 无全局锁**：Boids 决策只读取 Blackboard 当前快照，不获取锁
2. **I2 · Separation 最高优先**：资源冲突永远比 Alignment/Cohesion 优先处理
3. **I3 · Alignment 必同 tick**：分片后所有腕必须等 sync_tick 一起启动，防竞争
4. **I4 · Cohesion 软约束**：helper/learner 失败不影响原簇
5. **I5 · Claim 必设 TTL**：幽灵 claim 会阻塞后续腕
6. **I6 · 决策必经 Blackboard**：不得在腕内本地做私决策（否则涌现秩序失效）

---

## 可观测性

| Metric | 用途 |
|---|---|
| `boids.separation_win_rate` | 冲突中赢的比例，反映优先级合理性 |
| `boids.alignment_shard_balance` | 各分片负载均衡度 |
| `boids.cohesion_helper_count` | Cohesion 触发频率（太低说明腕普遍忙）|
| `boids.preempt_cancel_count` | 被抢占的中断次数（过高说明优先级不稳）|

---

## 反模式

- ❌ 在中枢做 Boids 决策 —— 违反去中心化
- ❌ Separation 用全局锁 —— 性能死
- ❌ Alignment 不对齐 tick 各自立即启动 —— 出现 thundering herd
- ❌ Cohesion 的 learner 干预原簇决策 —— learner 只读
- ❌ Claim 无 TTL —— 崩腕留下幽灵 claim

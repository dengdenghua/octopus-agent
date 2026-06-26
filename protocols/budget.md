---
implementation_status: implemented
implemented_in:
  - runtime/safety/budget_breaker/breaker.py
  - runtime/platform/llm_infra/budget_tracker.py
last_verified: 2026-06-25
---

# Protocol · Budget (墨囊 · 成本治理)

> **原则 ⑥ 成本治理** 的具体协议。
> 三层护栏：**预算硬顶（Per-task Budget）+ 熔断器（Circuit Breaker）+ 成本画像（Skill Cost Profile）**。
> 核心不变量：**预算单向递减；熔断即停，不可自愈**。

---

## 三层护栏总览

```
┌─ 每次 LLM/Tool 调用前 ─────────────┐
│                                   │
│  1. Budget.reserve(cost_estimate) │──→ 超限 → squirt("budget")
│  2. CircuitBreaker.check(arm)     │──→ 熔断态 → squirt("breaker")
│  3. ImmunityGate (已过)            │
│                                   │
└───────────────┬───────────────────┘
                │
                ▼
            执行调用
                │
                ▼
┌─ 每次 LLM/Tool 调用后 ─────────────┐
│                                   │
│  1. Budget.commit(actual_cost)    │
│  2. CircuitBreaker.observe(outcome)│
│  3. CostProfile.update(sucker, actual)│
│                                   │
└───────────────────────────────────┘
```

---

## 数据模型

```python
Budget = {
    "task_id": uuid,
    "tokens_limit": int,
    "usd_limit": float,
    "latency_limit_ms": int,
    "tokens_spent": int,              # 单调递增
    "usd_spent": float,               # 单调递增
    "latency_spent_ms": int,
    "tokens_reserved": int,           # 发出但未 commit 的
    "usd_reserved": float,
    "freeze_at": float,               # 0.9 = 90% 时预警
    "hard_stop_at": float,            # 1.0 = 100% 硬停
    "status": "active" | "frozen" | "exceeded",
}

BreakerState = {
    "arm_id": str,
    "state": "closed" | "open" | "half_open",
    "consecutive_failures": int,
    "zero_gain_steps": int,
    "loop_hash_window": deque[str],   # 近 N 步的 (sucker, args_hash)
    "opened_at": datetime | None,
    "retry_after": datetime | None,
}

CostProfile = {
    "sucker_id": str,
    "window_size": int,               # 默认 100 次
    "ema_tokens_in": float,           # 指数移动平均
    "ema_tokens_out": float,
    "ema_latency_ms": float,
    "ema_usd": float,
    "baseline_usd_7d": float,          # 7 天基线
    "trend_delta_ratio": float,        # 相对基线的倍率
    "alert_threshold": float,          # 默认 2.0
    "last_alerted_at": datetime | None,
}

SquirtReason = Literal[
    "budget_tokens",
    "budget_usd",
    "budget_latency",
    "breaker_fail",
    "breaker_loop",
    "breaker_zero_gain",
    "cost_anomaly",
]
```

---

## 核心算法

### 1) Budget Reserve / Commit（必须原子）

```python
def reserve(task_id, sucker, estimated_cost) -> bool:
    with budget_lock(task_id):
        b = budgets[task_id]
        if b.status != "active":
            return False
        # 含预估 + 已用，检查是否撞顶
        projected_usd = b.usd_spent + b.usd_reserved + estimated_cost.usd
        projected_tokens = b.tokens_spent + b.tokens_reserved + estimated_cost.tokens
        if (projected_usd >= b.usd_limit
            or projected_tokens >= b.tokens_limit):
            squirt("budget_usd" if projected_usd >= b.usd_limit else "budget_tokens", task_id)
            b.status = "exceeded"
            return False
        if projected_usd / b.usd_limit >= b.freeze_at:
            chromatophores.publish("alert.budget", task_id=task_id, ratio=projected_usd / b.usd_limit)
        b.usd_reserved += estimated_cost.usd
        b.tokens_reserved += estimated_cost.tokens
        return True


def commit(task_id, actual_cost):
    with budget_lock(task_id):
        b = budgets[task_id]
        b.usd_spent += actual_cost.usd
        b.tokens_spent += actual_cost.tokens
        b.latency_spent_ms += actual_cost.latency_ms
        # 预留归零对账
        b.usd_reserved = max(0, b.usd_reserved - actual_cost.usd)
        b.tokens_reserved = max(0, b.tokens_reserved - actual_cost.tokens)
```

### 2) Circuit Breaker 三种触发

```python
def observe(arm_id, step, result):
    s = breakers[arm_id]

    # (a) 连续失败
    if result.status == "failed":
        s.consecutive_failures += 1
        if s.consecutive_failures >= cfg.consecutive_failures:
            trip(arm_id, "breaker_fail")
            return
    else:
        s.consecutive_failures = 0

    # (b) 零信息增益：无新内容进入下一步的 context
    if is_zero_gain(step, result):
        s.zero_gain_steps += 1
        if s.zero_gain_steps >= cfg.zero_gain_steps:
            trip(arm_id, "breaker_zero_gain")
            return
    else:
        s.zero_gain_steps = 0

    # (c) 死循环：短窗口内同一 (sucker, args_hash) 重复
    key = f"{step.sucker_id}:{blake3(canonical(step.args)).hexdigest()[:16]}"
    s.loop_hash_window.append(key)
    if len(s.loop_hash_window) > cfg.loop_window:
        s.loop_hash_window.popleft()
    if s.loop_hash_window.count(key) >= cfg.loop_repeat_threshold:
        trip(arm_id, "breaker_loop")


def trip(arm_id, reason):
    s = breakers[arm_id]
    s.state = "open"
    s.opened_at = now()
    s.retry_after = now() + timedelta(seconds=cfg.breaker_cooldown_s)
    chromatophores.publish("alert.loop", arm_id=arm_id, reason=reason)
    squirt(reason, arm_id=arm_id)


def check(arm_id) -> bool:
    s = breakers[arm_id]
    if s.state == "closed":
        return True
    if s.state == "open":
        if now() >= s.retry_after:
            s.state = "half_open"     # 放一个试探流量
            return True
        return False
    # half_open：下一次 observe 决定 close/open
    return True
```

#### 零信息增益定义

```python
def is_zero_gain(step, result) -> bool:
    # 三个信号之一命中即算 zero gain：
    # 1. result 的输出摘要与上一步完全相同
    if step.result_hash == last_step(arm).result_hash:
        return True
    # 2. result 没有新实体 / 新工具返回值
    if extract_entities(result.output) <= extract_entities(last_step.output):
        return True
    # 3. LLM 返回的 next_action 与上一步相同
    if result.next_action == last_step.next_action:
        return True
    return False
```

### 3) Skill Cost Profile（EMA + 异常告警）

```python
def update(sucker_id, actual_cost):
    p = profiles[sucker_id]
    alpha = 2 / (p.window_size + 1)   # EMA 系数

    p.ema_tokens_in   = alpha * actual_cost.tokens_in + (1 - alpha) * p.ema_tokens_in
    p.ema_tokens_out  = alpha * actual_cost.tokens_out + (1 - alpha) * p.ema_tokens_out
    p.ema_latency_ms  = alpha * actual_cost.latency_ms + (1 - alpha) * p.ema_latency_ms
    p.ema_usd         = alpha * actual_cost.usd + (1 - alpha) * p.ema_usd

    # 相对 7 天基线的漂移
    p.trend_delta_ratio = p.ema_usd / max(p.baseline_usd_7d, 1e-6)

    # 告警（带防抖：同一 sucker 每日最多 1 次）
    if (p.trend_delta_ratio >= p.alert_threshold
        and (p.last_alerted_at is None
             or now() - p.last_alerted_at > timedelta(hours=24))):
        p.last_alerted_at = now()
        squirt("cost_anomaly", sucker_id=sucker_id, delta=p.trend_delta_ratio)
        chromatophores.publish("alert.budget",
                               sucker_id=sucker_id,
                               reason=f"cost_{p.trend_delta_ratio:.1f}x")


# 每日凌晨重算基线
def recompute_baseline():
    for p in profiles.values():
        p.baseline_usd_7d = mean(p.usd for call in last_7d_calls(p.sucker_id))
```

### 4) Squirt（吐墨）

```python
def squirt(reason: SquirtReason, **ctx):
    # 冻结当前受影响范围
    if "task_id" in ctx: budgets[ctx["task_id"]].status = "frozen"
    if "arm_id" in ctx:  arms[ctx["arm_id"]].freeze()

    # 广播
    chromatophores.publish("alert.budget", reason=reason, ctx=ctx)

    # 写入免疫/进化的 Journal（供后续 rule 学习）
    genome.journal.write_squirt_event(reason, ctx)

    # 不自动恢复 —— 必须人工或 Cerebrum 显式 clear_freeze()
```

---

## 集成点

| 时机 | 调用方 | API |
|---|---|---|
| 创建 task 时 | `cerebrum` → `ink` | `Budget.create(task_id, limits)` |
| 每次 LLM/tool 调用前 | `beak` / `eyes` → `ink` | `reserve() + breaker.check()` |
| 每次调用后 | `beak` / `eyes` → `ink` | `commit() + observe() + profile.update()` |
| 熔断触发 | `ink` → `chromatophores` | `publish("alert.budget" / "alert.loop")` |
| 人工 clear | admin → `ink` | `clear_freeze(task_id)` |
| 夜间基线重算 | scheduler → `ink` | `recompute_baseline()` |

---

## 配置契约

```yaml
ink:
  per_task:
    max_tokens: 200_000
    max_cost_usd: 2.00
    max_latency_ms: 600_000        # 10 min
    freeze_at_ratio: 0.9
  circuit_breaker:
    consecutive_failures: 3
    zero_gain_steps: 5
    loop_window: 10
    loop_repeat_threshold: 4
    cooldown_seconds: 300
  skill_cost_profile:
    enabled: true
    window_size: 100
    baseline_window_days: 7
    alert_threshold: 2.0           # 2x 涨价告警
    alert_suppress_hours: 24
```

---

## 不变量

1. **I1 · 预算单向**：`tokens_spent` / `usd_spent` 严格单调递增，任何"补血"必须显式记账
2. **I2 · Reserve 必须原子**：并发调用不得绕过 reserve，否则超支不可避免
3. **I3 · Reserve/Commit 成对**：reserve 后 30s 未 commit 视为调用丢失，自动归还预留
4. **I4 · 熔断不自愈**：状态只能 open → half_open → closed，不得直接 open → closed
5. **I5 · 熔断触发必广播**：不能静默熔断 —— Cerebrum 必须知道
6. **I6 · Cost profile 防抖**：同 sucker 24h 内最多 1 次告警，防噪音
7. **I7 · 熔断后写 Journal**：每次 squirt 是进化系统的学习素材

---

## 可观测性

| Metric | 标签 | 用途 |
|---|---|---|
| `ink.budget_utilization` | task_id | 当前任务预算消耗比例 |
| `ink.squirt_count` | reason | 吐墨频次（越多越警示）|
| `ink.breaker_state_count` | arm_id, state | 各腕熔断状态分布 |
| `ink.cost_profile_delta_ratio` | sucker_id | 成本漂移倍率 |
| `ink.reserve_commit_delta` | - | reserve 未 commit 的泄漏量 |
| `ink.zero_gain_step_rate` | arm_id | 死循环前兆 |

### 报警阈值建议

| 指标 | 警告 | 严重 |
|---|---|---|
| `squirt_count / hour` | >10 | >50 |
| `breaker_open_arms / total_arms` | >20% | >50% |
| `reserve_commit_delta` | >5% | >15% |

---

## 反模式

- ❌ 预算"软限制"（警告但不停）—— 预算必须是硬墙
- ❌ 熔断自动恢复到 closed 不做探测 —— 必须 half_open 试探
- ❌ Cost profile 用算术平均而非 EMA —— 长尾污染基线
- ❌ 把 squirt 做成抛异常而不广播 —— 其他器官感知不到
- ❌ 熔断冻结状态无需人工确认就自动解冻 —— 失去护栏意义
- ❌ 基线用固定窗口天数无 rollover —— 节假日流量会误伤

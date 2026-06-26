---
implementation_status: partial
implemented_in:
  - runtime/safety/auth/trust_engine.py
  - runtime/safety/auth/attack_memory.py
  - runtime/safety/auth/adaptive_immunity.py
last_verified: 2026-06-25
---

# Protocol · Immunity (免疫系统协议)

> **原则 ③ 内生安全** 的具体协议。
> 三层防线：先天（Innate）+ 记忆（Memory）+ 适应（Adaptive）+ 自我耐受（Tolerance）。
> 核心不变量：**每次工具调用都必须过免疫；免疫参与决策而非事后拦截**。

---

## 整体判决流程

```
  ToolCall
     │
     ▼
┌─────────────┐
│ Tolerance   │ ──→ allow  (白名单直通)
│ 自我耐受     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Innate      │ ──→ reject (未知来源 + strict 策略)
│ 先天屏障     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Memory      │ ──→ reject (命中攻击模式库)
│ 抗体记忆     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Adaptive    │ ──→ quarantine (风险分超阈)
│ 适应性评分   │ ──→ allow       (正常)
└─────────────┘
```

---

## 数据模型

```python
# 抗原签名：对每个"外来物"的身份卡
AntigenSignature = {
    "entity_id": str,             # "mcp://anthropic/filesystem" | "skill://public/run_sql"
    "entity_type": str,           # "mcp_server" | "skill" | "webhook_source"
    "content_hash": str,          # 脚本/定义的 hash，变更即重评估
    "provider_sig": str | None,   # 来源签名（可选，用于高强度场景）
    "first_seen": datetime,
    "origin": "builtin" | "public" | "custom" | "external",
}

# 攻击模式：免疫记忆的最小单元
AttackPattern = {
    "pattern_id": uuid,
    "match_rule": {
        "caller_pattern": str,      # regex for (arm_id, sucker_id)
        "args_pattern": dict,       # JSON matcher on args
        "outcome_signature": str,   # e.g. "exec_timeout" | "shell_injection_detected"
    },
    "severity": int,                 # 1..10
    "hit_count": int,
    "last_hit": datetime,
    "mitigation": str,               # 自然语言，给 Cerebrum 读的
}

# 行为基线：每个 Sucker 的"正常长什么样"
BehaviorBaseline = {
    "sucker_id": str,
    "avg_latency_ms": float,
    "avg_tokens": float,
    "avg_cost_usd": float,
    "typical_args_schema": dict,    # 常见 args 的分布
    "success_rate": float,
    "updated": datetime,
}

# 在线风险分：滑动窗口上的异常程度
RiskScore = {
    "sucker_id": str,
    "z_score_latency": float,
    "z_score_tokens": float,
    "z_score_cost": float,
    "arg_outlier_score": float,     # 当前 args 偏离 typical 多远
    "composite": float,             # 0..1
}

ImmuneVerdict = Literal["allow", "quarantine", "reject"]
```

---

## 核心算法

### 判决入口（必须在 EXECUTE 前调用）

```python
def check(call: ToolCall) -> ImmuneVerdict:
    # 1) Tolerance: 自己人直通（防自身免疫病）
    if is_self(call):
        return "allow"

    # 2) Innate: 来源签名
    sig = resolve_antigen(call.sucker_id)
    if sig.origin == "external" and sig.entity_id not in innate.trusted_sources:
        if innate.unknown_policy == "reject":
            _alert("innate_unknown", call)
            return "reject"
        # quarantine 策略：落到更严的 Mantle
        return "quarantine"

    # 3) Memory: 攻击模式
    for pattern in memory.attack_db.matching(call):
        pattern.hit_count += 1
        pattern.last_hit = now()
        _alert("memory_hit", call, pattern)
        return "reject"

    # 4) Adaptive: 行为异常评分
    score = adaptive.compute_risk(call)
    if score.composite >= adaptive.quarantine_threshold:
        _alert("adaptive_anomaly", call, score)
        return "quarantine"

    return "allow"
```

### 自我识别（Tolerance）

```python
def is_self(call: ToolCall) -> bool:
    # 明确白名单：cerebrum / ganglia / arms/* 内部调用互相不攻击
    return any(
        fnmatch(call.caller, pattern)
        for pattern in tolerance.self_whitelist
    )
```

### 风险分（Adaptive · 每次调用在线更新）

```python
def compute_risk(call: ToolCall) -> RiskScore:
    baseline = adaptive.baselines[call.sucker_id]
    if baseline is None:  # 冷启动
        return RiskScore(composite=0.5, reason="no_baseline")

    # z-score: 距均值多少个标准差
    z_lat = z_score(call.predicted_latency, baseline.avg_latency_ms)
    z_tok = z_score(call.predicted_tokens, baseline.avg_tokens)
    arg_out = arg_outlier(call.args, baseline.typical_args_schema)

    composite = sigmoid(
        0.3 * z_lat + 0.3 * z_tok + 0.4 * arg_out
    )
    return RiskScore(z_score_latency=z_lat, ..., composite=composite)
```

### 学习闭环（Execute 后触发）

```python
def learn(call: ToolCall, result: ExecutionResult):
    # 更新基线（滑动窗口均值 / 方差）
    adaptive.baselines[call.sucker_id].update(result.latency, result.tokens, result.cost)

    # 攻击识别
    if is_attack_like(result):
        pattern = derive_pattern(call, result)
        memory.attack_db.upsert(pattern)
        chromatophores.publish("alert.immune", pattern=pattern)

    # 不攻击不代表全对 —— 失败也进 Journal 供 Evolution 学习
    genome.journal.write_immune_event(call, result)
```

### 攻击识别启发式

```python
def is_attack_like(result: ExecutionResult) -> bool:
    signals = [
        result.status == "sandbox_violation",
        result.exit_code in {124, 137, 139},          # timeout/kill/segfault
        "shell_injection" in result.stderr_tags,
        "path_traversal" in result.audit_log,
        result.network_egress > budget.egress_limit,
        result.files_modified_outside_workdir > 0,
        result.llm_response_contains_prompt_injection,
    ]
    return sum(signals) >= 2   # 双信号确认，降低误报
```

---

## 集成点（其他器官如何用）

| 触发点 | 调用方 | API |
|---|---|---|
| EXECUTE 前 | `beak.ToolExecutor` | `immunity.check(call)` → `Verdict` |
| EXECUTE 后 | `beak.ToolExecutor` | `immunity.learn(call, result)` |
| Sucker 注册时 | `suckers.SkillRegistry` | `immunity.resolve_antigen(sucker_id)` |
| 攻击广播 | `immunity` → Chromatophores | `publish("alert.immune", pattern)` |
| 熔断联动 | `ink.CircuitBreaker` | 订阅 `alert.immune`，高频则触发熔断 |
| 反思入库 | `regeneration.Evolver` | 读 `genome.journal.immune_events` |

---

## 配置契约（与 config.yaml 对齐）

```yaml
immunity:
  innate:
    signature_check: true
    trusted_sources: [mcp://anthropic/*, skill://public/*]
    unknown_policy: quarantine   # quarantine | reject | allow
  adaptive:
    quarantine_threshold: 0.7
    baseline_window_size: 200    # 滑动窗口样本数
    cold_start_score: 0.5        # 无基线时的默认分
  memory:
    attack_db: ./immunity/memory/attacks.db
    deduplicate_window_hours: 24
    max_patterns: 10000
    eviction: lru
  tolerance:
    self_whitelist: [cerebrum, ganglia, arms/*]
```

---

## 不变量

1. **I1 · 每次 Beak.bite 前必过 immunity.check**；绕过即 bug（静态 lint 可查）
2. **I2 · Tolerance 白名单是最短路径**：自己人绝不走 Memory/Adaptive，防自身免疫
3. **I3 · Memory 只追加**：攻击模式只新增 + LRU 淘汰，不可手动删除（除非人工审核）
4. **I4 · Adaptive 冷启动保守**：无基线时返回中值 0.5，避免早期误判
5. **I5 · 攻击识别需要双信号**：`is_attack_like ≥ 2 signals` 防误报
6. **I6 · 免疫事件必入 Journal**：供 Evolution 和审计

---

## 可观测性

| Metric | 含义 |
|---|---|
| `immunity.verdict_count{result}` | allow/quarantine/reject 比例 |
| `immunity.memory_hit_rate` | 记忆命中率（高=已知攻击多） |
| `immunity.adaptive_quarantine_rate` | 在线评分触发的隔离率 |
| `immunity.false_positive_feedback` | 用户反馈被误杀的工具（喂给 Evolution 调权） |
| `immunity.db_size` | 攻击模式库大小 |

---

## 与主流框架的差异

| 能力 | 主流（LangChain/AutoGPT/Dify）| 本协议 |
|---|---|---|
| 权限白名单 | ✅ | ✅（Tolerance + Innate）|
| 沙箱 | △ | ✅（Mantle 独立）|
| 攻击模式记忆 | ❌ | ✅（Memory）|
| 在线行为评分 | ❌ | ✅（Adaptive）|
| 攻击广播联动熔断 | ❌ | ✅（Chromatophores + Ink）|
| 免疫事件回馈进化 | ❌ | ✅（Journal → Evolver）|

---

## 反模式

- ❌ 把 immunity 实现成"静态 ACL 检查" —— 失去 Adaptive 能力
- ❌ 把 immunity 放在 gateway 层做统一拦截 —— 离执行点太远，信号不准
- ❌ Memory 数据库无限增长 —— 必须 LRU + 去重
- ❌ 自动执行 mitigation 建议 —— 任何结构化缓解动作必须先经 Cerebrum 审阅

# Protocol · Reflex (反射快路径)

> **原则 ① Reactive + Deliberative** 的具体协议。
> Spinal Cord 不经 Cerebrum 完成低成本响应。**规则优先、缓存其次、小模型兜底**。
> 核心不变量：**反射短路了 PLAN，但绝不短路 IMMUNITY 和 STORE**。

---

## Meta-Control 决策流

```
ParsedIntent
     │
     ▼
┌─────────────────────┐
│ 1. 用户显式 --deep │ ──→ deliberative (skip reflex)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 2. 强制规划类型      │ ──→ deliberative
│   (plan/refactor)   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 3. Reflex 管道顺序   │
│   regex → cache →   │
│   rule_engine → slm │
└──────────┬──────────┘
           │
           ├─→ hit (confidence ≥ τ)  → REFLEX
           └─→ miss / low-confidence → DELIBERATIVE
```

---

## 数据模型

```python
ReflexRule = {
    "rule_id": str,
    "kind": "regex" | "cache" | "deterministic" | "slm",
    "matcher": dict,                # 形如 {"pattern": "^undo$"} 或 {"intent_eq": "volume_up"}
    "response": str | dict,         # 直出响应 / 脚本引用
    "cost_profile": "zero" | "low",
    "hit_count": int,
    "hit_rate": float,              # (hit / try_count)
    "confidence_prior": float,      # 0..1
    "created_by": "human" | "evolution",
    "promoted_at": datetime | None, # 从 Cerebrum 沉降为反射的时间
    "retired_at": datetime | None,
}

ReflexAttempt = {
    "rule_id": str,
    "matched": bool,
    "confidence": float,
    "latency_ms": float,
}

ReflexMatch = {
    "rule_id": str,
    "confidence": float,
    "response": Any,
    "cost": {"tokens": 0, "usd": 0.0, "latency_ms": float},
}
```

---

## 规则文件格式（`spinal_cord/rules.yaml`）

```yaml
# 反射规则库。顺序即优先级。
reflexes:
  # —— regex ——
  - id: r_undo
    kind: regex
    matcher:
      pattern: "^(撤销|undo|回退)$"
    response:
      action: emit
      payload: {type: command, cmd: undo}
    confidence_prior: 0.99

  - id: r_volume
    kind: regex
    matcher:
      pattern: "^音量([+-]\\d+)$"
    response:
      action: emit_template
      template: {type: command, cmd: volume_delta, delta: "${1}"}
    confidence_prior: 0.98

  # —— cache ——
  - id: c_default
    kind: cache
    matcher:
      key_fn: semantic_hash
      ttl_seconds: 3600
    confidence_prior: 0.95     # 命中即高置信

  # —— deterministic rule ——
  - id: d_greeting
    kind: deterministic
    matcher:
      intent_eq: "greeting"
    response:
      action: canned
      payload: "在的。"
    confidence_prior: 0.99

  # —— edge SLM ——（可选，本地小模型做意图分类）
  - id: s_intent_classify
    kind: slm
    matcher:
      model_ref: edge_slm_0_5b
      task: intent_classification
    response:
      action: route_by_intent
    confidence_prior: 0.80      # 小模型置信相对低
```

---

## 核心算法

### 入口：try_reflex

```python
def try_reflex(intent: ParsedIntent) -> ReflexMatch | None:
    # 用户或任务类型强制走慢路径
    if _force_deliberative(intent):
        telemetry.count("reflex.skipped_forced")
        return None

    # 按配置顺序串联尝试
    for rule in rules_pipeline:
        attempt = _try_one(rule, intent)
        telemetry.record("reflex.attempt", rule_id=rule.rule_id, matched=attempt.matched)
        if attempt.matched and attempt.confidence >= rule.threshold:
            return ReflexMatch(
                rule_id=rule.rule_id,
                confidence=attempt.confidence,
                response=_materialize(rule, intent),
                cost={"tokens": 0, "usd": 0.0, "latency_ms": attempt.latency_ms},
            )
    return None


def _force_deliberative(intent: ParsedIntent) -> bool:
    if intent.flags.get("deep"): return True
    if intent.intent_type in {"plan", "refactor", "debug", "design"}: return True
    if intent.modalities and "image" in intent.modalities: return True
    return False
```

### Cache Key 设计（最容易踩雷的地方）

```python
def semantic_hash(intent: ParsedIntent) -> str:
    # ⚠️ 必须包含：语义、用户上下文、工具版本
    # ⚠️ 必须排除：时间戳、会话 id、可变的系统状态
    components = [
        normalize_text(intent.normalized_goal),
        intent.intent_type,
        intent.user_context.get("locale", ""),
        intent.user_context.get("role", ""),
        tool_version_fingerprint(),
    ]
    return blake3("|".join(components).encode()).hexdigest()
```

**反面教训**：把 `ts` 或 `session_id` 纳入 key → cache 永远不命中；
**反面教训**：把环境相关的 flag 排除 → 不同环境拿到同一答案。

### SLM（可选）

```python
def try_slm(intent: ParsedIntent) -> ReflexAttempt:
    # 只做低延迟分类，不做生成
    t0 = time.monotonic()
    pred = edge_slm.classify(intent.normalized_goal, labels=cfg.intent_labels)
    lat = (time.monotonic() - t0) * 1000
    return ReflexAttempt(
        rule_id="s_intent_classify",
        matched=pred.confidence >= cfg.slm_threshold,
        confidence=pred.confidence,
        latency_ms=lat,
    )
```

---

## 与 Evolution 的双向通道

### 沉降（从思考层 → 反射层）

```python
# 在 Evolution 的每晚回路里
def demote_to_reflex(scored_trajs):
    # 找稳定且低变化的任务模式
    for pattern, cluster in find_demotable_patterns(scored_trajs):
        if (len(cluster) >= 20
            and variance(cluster) < 0.05
            and mean_score(cluster) >= 0.9):
            # 从多条 trajectory 抽出一条参数化 rule
            rule = synthesize_rule(pattern, cluster)
            rule.created_by = "evolution"
            rule.status = "shadow"
            write_rule_yaml(rule)
```

### 退化（反射不灵 → 回到思考层）

```python
def retire_stale_reflex():
    for rule in rules_pipeline:
        if rule.hit_count > 100 and rule.hit_rate < 0.2:
            rule.retired_at = now()
            chromatophores.publish("reflex.retired", rule_id=rule.rule_id)
```

---

## 集成点

| 时机 | 调用方 | 动作 |
|---|---|---|
| 流水线 CLASSIFY 阶段 | `digestion` | `try_reflex(intent)` → 决定 reflex/deliberative |
| 反射命中后 | `spinal_cord` → `ganglia` | 仍进 EXECUTE（为了 immunity + store） |
| 免疫事件广播 | `immunity` → `spinal_cord` | 命中攻击 → 暂时禁用该 cache key |
| 夜间回路 | `regeneration` → `spinal_cord` | 沉降新规则 + 退化冷规则 |
| 用户反馈差 | `siphon` → `spinal_cord` | 标记该反射 "user_thumbs_down"，降其 threshold |

---

## 配置契约（对齐 config.yaml）

```yaml
spinal_cord:
  enabled: true
  tryfirst: true
  default_threshold: 0.85       # 超过才算命中
  pipeline:                     # 顺序即优先级
    - regex
    - cache
    - rule_engine
    - edge_slm
  cache:
    backend: redis
    ttl_seconds: 3600
    max_entries: 100_000
  edge_slm:
    enabled: false
    model_path: ./models/qwen-0.5b.gguf
    max_latency_ms: 50
  force_deliberative_intents: [plan, refactor, debug, design]
```

---

## 不变量

1. **I1 · 反射不绕免疫**：命中后仍进 EXECUTE 让 `immunity.check` 跑（见 digestion I3）
2. **I2 · 反射必入 Journal**：反射响应也是 trajectory，Evolver 需要它
3. **I3 · 规则顺序即优先级**：不得有"乱序命中" —— 靠前的低置信 vs 靠后的高置信，选前者
4. **I4 · Cache key 稳定性**：同语义 intent 必须算出同一 key（否则命中率作假）
5. **I5 · SLM 只分类不生成**：绝不让小模型在反射层做开放生成
6. **I6 · Reflex 冷启动空库**：上线初期反射命中率低是正常的；禁止为凑命中率塞垃圾规则

---

## 可观测性

| Metric | 标签 | 用途 |
|---|---|---|
| `reflex.try_count` | rule_id | 规则被尝试次数 |
| `reflex.hit_count` | rule_id | 规则命中次数 |
| `reflex.hit_rate` | rule_id | 核心健康指标 |
| `reflex.saved_tokens` | - | 估算的节省的 LLM tokens |
| `reflex.saved_usd` | - | 核心 ROI 指标 |
| `reflex.cache_miss_rate` | - | cache key 设计是否正确 |
| `reflex.force_deliberative_count` | reason | 观察什么样的任务被强制走慢路径 |

---

## 反模式

- ❌ 反射做任何"生成" —— 反射应只出"决定性响应"
- ❌ 反射里写 LLM 调用兜底（矛盾）
- ❌ 规则库无限膨胀不退化（hit_rate 是硬指标）
- ❌ 反射响应直接写文件 / 调工具（应 emit 事件让 Beak 咬）
- ❌ Cache TTL 设成永久（数据/工具更新会让 cache 中毒）

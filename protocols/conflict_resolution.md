# Protocol · Conflict Resolution (冲突消解 · 共享算法底座)

> **知识图谱**和**长时记忆**的共同痛点。
> 两者存不同类型的信息，但"新旧信息矛盾时怎么办"是**同一个算法问题**。
>
> 本文是底座；[knowledge_graph.md](knowledge_graph.md) 和 [memory_consolidation.md](memory_consolidation.md) 各自复用。
>
> 核心判断：**冲突不是 bug，是信息系统的常态**。关键不是避免冲突，是**有序消解**。

---

## 1. 六种冲突类型

| 类型 | 描述 | 例 |
|---|---|---|
| **Direct** | 直接矛盾 | (X 是 A) vs (X 不是 A) |
| **Value** | 同属性不同值 | (X.age = 30) vs (X.age = 35) |
| **Type** | 实体分类不同 | (X 是 Person) vs (X 是 Company) |
| **Relational** | 关系存在性冲突 | (X 拥有 Y) vs (X 不拥有 Y) |
| **Temporal** | 时间段重叠冲突 | (X 在 Y 公司 2020-2022) vs (X 在 Z 公司 2021) |
| **Inferred** | 本体推理矛盾 | (X is Dog) ∧ (Dog ⊂ Animal) ∧ (X is not Animal) |

**分类决定策略**：Temporal 冲突很多**不是真冲突**（两者都对，只是时段不同），而 Direct 冲突必须二选一。

---

## 2. 数据模型

```python
Assertion = {
    "assertion_id": uuid,
    "subject": str,                    # 实体 ID 或值
    "predicate": str,                   # 关系 / 属性名
    "object": Any,                      # 实体 / 值
    "confidence": float,                # 0..1
    "source": Source,
    "evidence_refs": list[str],         # 原始轨迹/文档的引用
    "valid_from": datetime | None,      # Temporal validity
    "valid_until": datetime | None,
    "ts": datetime,                     # 写入时间戳
    "status": "active" | "archived" | "disputed" | "superseded",
    "superseded_by": uuid | None,
}

Source = {
    "source_id": str,                   # "tool:mcp_filesystem" / "user:alice" / "doc:abc" / "inference"
    "source_type": "user" | "tool" | "doc" | "trajectory" | "inference",
    "trust_score": float,               # 0..1，动态更新
}

ConflictRecord = {
    "conflict_id": uuid,
    "assertions": list[uuid],           # 涉及的所有 assertion
    "conflict_type": ConflictType,
    "detected_at": datetime,
    "resolution": Resolution | None,    # 未消解为 None
    "escalated": bool,
}

Resolution = {
    "strategy": str,                    # 用了哪种策略
    "winner": uuid | None,              # 赢家 assertion
    "merged_assertion": uuid | None,    # 若是合并而非选一
    "rationale": str,                   # 人类可读
    "resolved_at": datetime,
    "resolved_by": "auto" | "human",
}
```

---

## 3. 六种消解策略

按**优先级顺序**尝试。前面的通过就不走后面。

### Strategy-1 · Temporal Split（时段分割）
**适用**：Temporal 类冲突里**两者都对，只是时段不同**。

```python
def strategy_temporal_split(assertions):
    # 若每个 assertion 都带 valid_from/valid_until 且无重叠 → 不冲突
    intervals = [(a.valid_from, a.valid_until, a) for a in assertions]
    if no_overlap(intervals):
        return Resolution(strategy="temporal_split",
                         rationale="different time windows")

    # 若重叠但可压缩（如 2020-2022 和 2021 → 2021 部分冲突）
    if can_infer_true_timeline(intervals):
        merged = merge_timelines(intervals)
        return Resolution(strategy="temporal_split", merged_assertion=merged)

    return None  # 不适用
```

### Strategy-2 · Evidence Weight（证据加权）
**适用**：有明确证据链的情况。

```python
def strategy_evidence(assertions):
    for a in assertions:
        a.evidence_score = sum(
            evidence_strength(ref) for ref in a.evidence_refs
        )
    winner = max(assertions, key=lambda a: a.evidence_score)
    if winner.evidence_score >= 2 * second_best.evidence_score:
        return Resolution(strategy="evidence", winner=winner.assertion_id)
    return None  # 证据差距不足 2 倍不适用
```

### Strategy-3 · Source Trust（来源信任）
**适用**：无明确证据，但 source 信任分差距大。

```python
def strategy_source_trust(assertions):
    winner = max(assertions, key=lambda a: a.source.trust_score)
    if winner.source.trust_score >= second_best.source.trust_score + 0.3:
        return Resolution(strategy="source_trust", winner=winner.assertion_id)
    return None
```

### Strategy-4 · Confidence Weighted（置信度加权）
**适用**：内部确信度差距大。

```python
def strategy_confidence(assertions):
    winner = max(assertions, key=lambda a: a.confidence)
    if winner.confidence >= 0.85 and second_best.confidence < 0.5:
        return Resolution(strategy="confidence", winner=winner.assertion_id)
    return None
```

### Strategy-5 · Recency Bias（新信息优先）
**适用**：前几条都不适用，用户说的"新信息优先"兜底。

```python
def strategy_recency(assertions):
    newest = max(assertions, key=lambda a: a.ts)
    # 但要求新 assertion 不能只靠"新" —— 至少得有一个支持信号
    if newest.confidence >= 0.7 or newest.source.trust_score >= 0.7:
        return Resolution(strategy="recency", winner=newest.assertion_id,
                         rationale="recency tiebreaker + baseline support")
    return None
```

### Strategy-6 · Human Escalation（人工升级）
**适用**：前五种都不适用。

```python
def strategy_escalate(assertions):
    conflict_record.escalated = True
    mark_all_disputed(assertions)
    chromatophores.publish("alert.conflict_unresolved",
                          conflict_id=conflict_record.id)
    return Resolution(strategy="human_escalation", resolved_by="human")
```

---

## 4. 决策树

```python
def resolve(conflict: ConflictRecord) -> Resolution:
    # 1. 先看类型：Temporal 冲突很多不是真冲突
    if conflict.conflict_type == "Temporal":
        r = strategy_temporal_split(conflict.assertions)
        if r: return r

    # 2. 证据 > 信任 > 置信 > 新鲜
    for strategy in [strategy_evidence, strategy_source_trust,
                     strategy_confidence, strategy_recency]:
        r = strategy(conflict.assertions)
        if r: return r

    # 3. 兜底升级
    return strategy_escalate(conflict.assertions)
```

**顺序硬约束**（Evidence → Trust → Confidence → Recency）是为了**抗 Goodhart**：
- 若 Recency 在前 → 系统会"不断覆盖"旧事实（哪怕新的很弱）
- 若 Confidence 在前 → LLM 给出的高置信幻觉可以覆盖真实证据

---

## 5. Source Trust Score 动态维护

来源信任分不是静态。每次该来源产出的 assertion 被采用/驳回 → 分数更新：

```python
def update_trust(source_id, outcome):
    s = sources[source_id]
    alpha = 0.05   # EMA 系数，慢变
    delta = +0.1 if outcome == "accepted" else -0.2   # 错误惩罚更重
    s.trust_score = clamp(s.trust_score + alpha * delta, 0, 1)
```

### 初始值

| Source Type | 初始 trust |
|---|---|
| user (direct input) | 0.80 |
| tool (structured return) | 0.75 |
| doc (文档解析) | 0.60 |
| trajectory (系统自产) | 0.55 |
| inference (本体推理) | 0.50 |

### 红线
- `trust_score < 0.2` 的 source 产出**默认进 disputed**，需证据链才被接纳
- `trust_score < 0.1` 持续 30 天 → 该 source 进黑名单

---

## 6. 本体辅助检测（Inferred 冲突）

简化版 SPARQL-like 推理：

```python
def detect_inferred_conflicts(new_assertion, ontology):
    # 基于子类继承推理
    # 例：(X is Dog), 本体有 (Dog ⊂ Animal), 若库里已有 (X is not Animal) → 冲突
    implicit_facts = ontology.infer_from(new_assertion)
    for implied in implicit_facts:
        contradictions = find_assertions_contradicting(implied)
        if contradictions:
            yield ConflictRecord(
                conflict_type="Inferred",
                assertions=[new_assertion.id] + [c.id for c in contradictions],
                inference_chain=ontology.explain(new_assertion, implied),
            )
```

**不变量**：推理本身产出的 assertion **trust_score 上限 0.5** —— 推理结论不能超过人类/工具直接断言。

---

## 7. 不变量（CFR-I 系列）

| ID | 内容 | 执行 |
|---|---|---|
| CFR-I1 | 所有 assertion 必带 source + confidence + ts | Schema enforce |
| CFR-I2 | 策略顺序固定：Temporal → Evidence → Trust → Confidence → Recency → Escalate | **Runtime Assert** |
| CFR-I3 | Recency 不得单独定胜负（必须 ≥ 0.7 辅助信号）| Runtime Assert |
| CFR-I4 | 被驳回的 assertion 归档不删除（审计）| Schema enforce |
| CFR-I5 | 推理产出的 trust 上限 0.5 | Runtime Assert |
| CFR-I6 | Source trust 更新用 EMA，不允许大幅跳变 | Runtime Assert |
| CFR-I7 | 无法自动消解的 conflict 必广播 + Journal | Runtime Assert |
| CFR-I8 | 消解历史不可改写（append-only） | Schema enforce |

### Cross-cutting

**CC-C1 · 所有知识写入经冲突消解**
- 参与方：CFR-I1..I2 + KG 写入 + Memory 写入
- 描述：KG 写新三元组、Memory 存新事实前，必先走 `detect + resolve` 流水线。
- Lint + Runtime Gate。

**CC-C2 · Trust score 漂移守卫**
- 参与方：CFR-I6 + FITNESS drift guard
- 描述：Source trust 一周内漂移 > 0.3 → 告警（系统被喂错数据的前兆）。
- Runtime Alert。

---

## 8. 集成点

| 场景 | 调用方 | API |
|---|---|---|
| KG 写新三元组 | `genome.knowledge.graph` → `conflict_resolver` | `resolve_before_write(assertion)` |
| Memory 存新事实 | `genome.memory.semantic` → `conflict_resolver` | 同上 |
| 事后审计 | `regeneration.evolver` | `list_unresolved_conflicts(since)` |
| Trust 更新 | KG/Memory 消费后 | `update_trust(source_id, outcome)` |
| 本体推理触发 | KG 写入后 | `detect_inferred_conflicts(new, ontology)` |

---

## 9. 配置契约

```yaml
conflict_resolution:
  enabled: true
  strategies:
    temporal_split: {enabled: true}
    evidence: {min_ratio: 2.0}
    source_trust: {min_delta: 0.3}
    confidence: {winner_min: 0.85, loser_max: 0.5}
    recency: {winner_min_support: 0.7}
  trust_dynamics:
    ema_alpha: 0.05
    accept_delta: +0.1
    reject_delta: -0.2
    blacklist_threshold: 0.1
    blacklist_duration_days: 30
  inference:
    trust_cap: 0.5
  escalation:
    disputed_retention_days: 90
    notify_channels: [ops_channel]
```

---

## 10. 可观测性

| Metric | 用途 |
|---|---|
| `cfr.conflicts_detected_count` | 冲突检出率 |
| `cfr.auto_resolved_ratio` | 自动消解占比 |
| `cfr.strategy_usage{strategy}` | 各策略命中分布 |
| `cfr.escalated_count` | 升级人工 |
| `cfr.trust_score{source_id}` | 各来源信任分 |
| `cfr.trust_drift_7d` | 信任分周漂移 |

### 警戒线
- `auto_resolved_ratio < 60%` → 策略权重需调
- `escalated_count > 20/天` → 上游数据源质量差，先查来源
- `trust_drift_7d > 0.3` → 有系统被误导的征兆

---

## 11. 反模式

| 反模式 | 后果 | 破解 |
|---|---|---|
| 只用 Recency | 新的弱信息覆盖旧的强证据 | 策略顺序固定 CFR-I2 |
| 不记 source | 驳回/采纳无法审计 | CFR-I1 必带 source |
| 推理结论当事实 | 推理错误滚雪球 | CFR-I5 trust 上限 0.5 |
| 删除被驳回 assertion | 审计断链 | CFR-I4 归档不删 |
| Trust 跳变 | 单次异常直接降权 | EMA 平滑 CFR-I6 |
| 升级无去向 | 人工永远看不到 | 必 Chromatophores 广播 + Journal |

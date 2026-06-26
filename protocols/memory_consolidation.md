---
implementation_status: implemented
implemented_in:
  - runtime/safety/recovery/memory_consolidator.py
last_verified: 2026-06-25
---

# Protocol · Memory Consolidation (记忆巩固 · "睡眠"机制)

> 缺口 5（SIX_MODULES §4）的完整规范。
> 中心反思引擎的**第四条产出**。
>
> 核心判断：**没有巩固的记忆就是日志**。日志只长不消化 = 冷存储仓库 = 死数据。
>
> 冲突消解复用 [conflict_resolution.md](conflict_resolution.md)，本协议只讲记忆专属。

---

## 1. 四层记忆（回顾 + 定位）

| 层 | 职责 | 容量 | 落位 |
|---|---|---|---|
| **Working** | 本轮会话 scratch pad | tokens 级 | `hemolymph/` Blackboard |
| **Episodic** | 过往对话/任务轨迹 | 事件级 | `genome/journal/` |
| **Semantic** | 提炼过的模糊事实 | 事实级 | `genome/memory/semantic/` |
| **Procedural** | "此 skill 对 X 有效/无效"等元经验 | 规则级 | `cerebrum` prompt 的 `learned_mitigations` 段（由 Evolution 注入）|

**四层不独立进化** —— 本协议定义它们之间的**流动**：
```
Working ──┐
          ├─→ Episodic ──→ Semantic ──→ KG（部分晋升）
Working ──┤                      ↓
          └─→ Procedural ←──── Evolution
```

---

## 2. 三大机制

对应原始六边形描述：**衰减 / 巩固 / 冲突消解**。

### 2.1 Decay · 衰减

旧且未被召回的记忆降权。**不删除**（审计需要），只降优先级。

```python
def decay_tick(mem: SemanticMemory, now: datetime):
    age_days = (now - mem.last_accessed).days
    half_life = mem.half_life_days             # 可随类型调（事实类 365d，临时类 30d）
    mem.priority *= 2 ** (-age_days / half_life)
```

**分级半衰期**：

| 记忆类型 | half_life |
|---|---|
| Fact / Definition | 365 天 |
| Preference / Personal | 180 天 |
| Task context | 30 天 |
| Ephemeral / Session | 7 天 |
| Error note | 90 天 |

低优先级记忆**不参与 Hemolymph 召回**，但保留物理存储。达到 priority < 0.01 且 3 年未被访问才进冷存档（可离线文件）。

### 2.2 Consolidation · 巩固（"睡眠"）

本协议的**主体**。Regeneration 夜间流水线的一环。

```
Light 巩固（每小时）： Working → Episodic（append-only）
Deep 巩固（夜间）：    Episodic → Semantic + KG 候选
REM-like 合成（夜间）： Semantic × Semantic → 新关联 / 新 skill 候选
```

#### 2.2.1 Light 巩固（轻量 · 每小时）

```python
def light_consolidation():
    # 把 Working 区超过 1h 未活动的记录固化成 Episodic
    expired = hemolymph.blackboard.scan(age_gt_minutes=60)
    for entry in expired:
        genome.journal.append(convert_to_episode(entry))
        hemolymph.blackboard.remove(entry)
```

#### 2.2.2 Deep 巩固（重量 · 夜间 Batch）

```python
def deep_consolidation():
    # 挑近 7 天高频访问 + 高分 trajectory
    episodes = journal.filter(
        access_count_min=3,
        f_trajectory_min=0.75,
        since_days=7,
    )

    # 按主题聚类（避免同类重复提炼）
    clusters = cluster_by_topic(episodes)

    for cluster in clusters:
        # 用 Haiku 抽取语义（结构化总结）
        summary = eyes.call_model("haiku-batch",
            prompt=SEMANTIC_EXTRACT_PROMPT.fill(episodes=cluster)
        )

        # 产出三类物件
        facts = summary.facts           # → Semantic + KG 候选
        rules = summary.rules           # → Procedural
        skills = summary.skill_candidates  # → skill_forge 复用

        for f in facts:
            # 走 conflict_resolver 写入
            result = conflict_resolver.resolve_before_write(f)
            if result.accepted:
                semantic_memory.write(f)
                # 结构化程度高的直接晋升 KG
                if f.is_structured_triple() and f.confidence >= 0.7:
                    kg.ingest([f.as_triple()])

        for r in rules:
            # 走 Evolution 的 rule_extraction → planner prompt 注入
            evolution.submit_rule_candidate(r)

        for s in skills:
            # 走 skill_forge 流水线
            evolution.submit_skill_candidate(s)
```

#### 2.2.3 REM-like 合成

```python
def rem_synthesis():
    # 随机选 2 个语义记忆对，让 LLM 找"它们之间有什么关联"
    pairs = semantic_memory.random_pairs(n=20)
    for a, b in pairs:
        hypothesis = eyes.call_model("haiku",
            prompt=SYNTHESIS_PROMPT.fill(a=a, b=b))
        if hypothesis.confidence >= 0.7 and hypothesis.novel:
            # 作为"待验证假设"写入，trust 上限 0.4（推理级）
            semantic_memory.write(hypothesis.as_memory(trust_cap=0.4))
```

REM 阶段产出的都是**弱记忆**（trust_cap 0.4）—— 必须后续被真实证据支持才能升档。

### 2.3 Conflict Resolution

复用 [conflict_resolution.md](conflict_resolution.md)。记忆层专属的两个细节：

#### 2.3.1 Episodic 不做冲突消解
Journal 是 append-only 历史，**两段记录矛盾不是 bug** —— 2022 说的和 2024 说的都保留。
消解在 Semantic 层发生。

#### 2.3.2 记忆消解后的"原版保留"
Semantic 冲突消解时，败者 `status = "superseded"` + `superseded_by = winner_id`。
前端展示只给 active；后端（debugging / 复盘）能看到完整历史。

---

## 3. 数据模型

```python
SemanticMemory = {
    "memory_id": uuid,
    "content": str,                     # 自然语言事实
    "structured": dict | None,          # 可选的结构化表达
    "tags": list[str],
    "priority": float,                  # 0..1，随时间衰减
    "half_life_days": int,
    # 复用 Assertion 字段
    "confidence": float,
    "source": Source,
    "evidence_refs": list[str],
    "ts": datetime,
    "last_accessed": datetime,
    "access_count": int,
    "status": "active" | "superseded" | "archived",
    "superseded_by": uuid | None,
}

ProceduralMemory = {
    "rule_id": uuid,
    "pattern": str,                     # "when X happens"
    "action": str,                      # "do Y (not Z)"
    "confidence": float,
    "sample_evidence": list[uuid],      # 支持 trajectory
    "injected_to_planner": bool,
    "last_validated": datetime,
}
```

---

## 4. Hemolymph 召回策略（给 Context Composer）

依赖 `recipe.memory_recall` 配置（见 [recipe.md](recipe.md)）：

```python
def recall(task, recipe) -> list[SemanticMemory]:
    strategy = recipe.memory_recall.strategy
    top_k = recipe.memory_recall.top_k

    if strategy == "recency":
        return by_recency_with_priority(task, top_k)
    if strategy == "similarity":
        return by_embedding_similarity(task.goal, top_k)
    if strategy == "hybrid":
        return rrf_merge(by_recency(...), by_similarity(...), top_k)
    if strategy == "episodic_only":
        return by_episodic_lookup(task.goal, top_k)
```

**召回也会更新 `last_accessed` 和 `access_count`** —— 召回反馈成为 decay 的反制。

---

## 5. 程序性记忆的独特路径

Procedural memory 不走 Hemolymph 召回，而是**直接注入 Cerebrum system prompt**：

```
trigger: 新规则产出 / 旧规则失效
    ↓
evolution.inject_into_planner(rules)
    ↓
cerebrum.prompt.set_section("learned_mitigations", rules)
    ↓
eyes.models.flush_prompt_cache_hint()       ← CC-3 触发
```

**防膨胀**：
- `max_rules_in_prompt = 30`（见 evolution.md EVO-I6）
- 超限 LRU 淘汰
- 每月一次全量 re-validation：让 LLM 判断哪些规则仍有效

---

## 6. 与 KG 的双向通道

Semantic Memory 和 KG 相互渗透：

```
Semantic → KG：Deep 巩固中，结构化程度高 + confidence ≥ 0.7 的 semantic 写成 KG triple
KG → Semantic：KG 推理产出的高可信结论可以回写为 Semantic（带 source_type=inference，trust 上限 0.5）
```

**不变量**：KG 和 Semantic 里的同一事实必须保持同步 —— 通过 `semantic_memory.structured` 里的 `kg_triple_id` 绑定。

```python
def sync(semantic: SemanticMemory, triple: Triple):
    semantic.structured = {**semantic.structured, "kg_triple_id": triple.id}
    triple.evidence_refs.append(f"semantic:{semantic.id}")
```

---

## 7. 不变量（MEM-I 系列）

| ID | 内容 | 执行 |
|---|---|---|
| MEM-I1 | Episodic 永不修改，只 append | Schema enforce |
| MEM-I2 | Semantic 写入必经 conflict_resolver | Runtime Gate |

> ⚠️ **MEM-I2 待 KG 接入后成立**:conflict_resolver 已实装(`runtime/safety/conflict_resolution/resolver.py`),但 KG 的 `add()` 尚未切换到调用 `resolve()`。
| MEM-I3 | Decay 只降 priority 不删除 | Runtime Assert |
| MEM-I4 | REM 产出 trust 上限 0.4 | Runtime Assert |
| MEM-I5 | Procedural 规则上限 30 条（在 Cerebrum prompt）| Runtime Assert（复用 EVO-I6）|
| MEM-I6 | Procedural 规则变更必 flush prompt cache | Runtime Assert（复用 CC-3）|
| MEM-I7 | Semantic ↔ KG 同步：同一事实双写必绑定 id | Schema enforce |
| MEM-I8 | 召回必更新 last_accessed（防错误衰减）| Runtime Assert |
| MEM-I9 | Personal 级记忆不出 Edge（DIS-I1 复用）| Lint |

### Cross-cutting

**CC-M1 · 睡眠不在业务时段跑**
- 参与方：MEM-I + GEN nuclear-time
- 描述：Deep consolidation + REM 只在业务低峰跑（默认 02:00-06:00），避免占 Branchial Heart 的 API 配额
- Runtime Gate。

**CC-M2 · 记忆召回 ↔ Recipe 绑定**
- 参与方：MEM-I + RCP-I1
- 描述：不同 recipe 配同 task_type 下应该产生**可对照的召回统计**
- Runtime Assert。

---

## 8. 集成点

| 时机 | 调用方 | API |
|---|---|---|
| Working → Episodic（轻）| scheduler 每小时 | `light_consolidation()` |
| Episodic → Semantic（重）| scheduler 夜间 | `deep_consolidation()` |
| REM 合成 | scheduler 夜间 | `rem_synthesis()` |
| Semantic 召回 | hemolymph.ContextComposer | `recall(task, recipe)` |
| Procedural 注入 | evolution.rule_extractor | `inject_rules(rules)` |
| KG ↔ Semantic 同步 | KG ingest + memory write | `sync(semantic, triple)` |

---

## 9. 配置契约

```yaml
memory_consolidation:
  enabled: true

  decay:
    tick_interval_hours: 1
    half_lives_days:
      fact: 365
      preference: 180
      task_context: 30
      ephemeral: 7
      error_note: 90
    priority_floor: 0.01
    cold_archive_after_years: 3

  light_consolidation:
    idle_threshold_minutes: 60
    schedule: "0 * * * *"              # 每小时

  deep_consolidation:
    enabled: true
    schedule: "0 2 * * *"              # 02:00
    episode_access_count_min: 3
    f_trajectory_min: 0.75
    since_days: 7
    extract_model: claude-haiku-4-5-20251001  # Batch API

  rem_synthesis:
    enabled: true
    schedule: "0 4 * * *"              # 04:00
    pairs_per_night: 20
    synthesis_model: claude-haiku-4-5-20251001
    trust_cap: 0.4

  procedural:
    max_rules_in_prompt: 30
    lru_eviction: true
    monthly_revalidation: true

  recall:
    default_strategy: hybrid
    update_access_on_recall: true

  kg_sync:
    structured_confidence_min: 0.7
    bidirectional: true
```

---

## 10. 可观测性

| Metric | 用途 |
|---|---|
| `mem.episodic_append_rate` | 写入速率 |
| `mem.semantic_active_count` | 活跃语义记忆数 |
| `mem.decay_to_floor_count` | 降到地板的记忆数 |
| `mem.consolidation_duration_ms` | 夜间巩固耗时 |
| `mem.rem_novel_rate` | REM 产出新 hypothesis 的比例 |
| `mem.procedural_hit_rate_in_planner` | 规则注入后的实际命中 |
| `mem.kg_semantic_sync_lag` | 双写同步延迟 |

### 警戒线
- `consolidation_duration_ms > 3h` → Batch API 任务阻塞，次日推迟 REM
- `rem_novel_rate < 5%` → REM 合成器失效（全是老调重弹）
- `procedural_hit_rate_in_planner < 10%` → 规则没用，LRU 阈值应降

---

## 11. 反模式

| 反模式 | 后果 | 破解 |
|---|---|---|
| 删除低优先级记忆 | 审计断链 + 召回失效 | MEM-I3 只降权 |
| Episodic 做冲突消解 | 历史被改写 | MEM-I1 append-only |
| REM 产出直接采纳 | 幻觉污染语义库 | MEM-I4 trust cap |
| Procedural 规则无上限 | prompt 爆表 + cache miss | MEM-I5 / EVO-I6 |
| Semantic 和 KG 各写各的 | 同事实两份不一致 | MEM-I7 双写绑定 |
| 召回不更新访问 | 常用记忆被衰减掉 | MEM-I8 |
| 业务时段跑巩固 | 挤占生产 API 配额 | CC-M1 限夜间 |
| 规则永不回测 | 过时规则误导 planner | 每月 revalidation |

---

## 12. 反思引擎完成度

| 信号 | 协议 | 状态 |
|---|---|---|
| 新 skill 候选 | [evolution.md](evolution.md) | ✅ |
| Workflow 改写建议 | [workflow_rewrite.md](workflow_rewrite.md) | ✅ |
| KG 新增三元组 | [knowledge_graph.md](knowledge_graph.md) | ✅ |
| **记忆巩固指令** | **本协议** | ⚠️ |
| 上下文配方打分 | [recipe.md](recipe.md) | ✅ |

**进度 5/5 文件已创建,完整协议语义实装进行中。**

> ⚠️ **memory_consolidator.py 当前仅实装轨迹模式聚类**。4 层记忆分工、衰减机制、Light/Deep/REM 三级巩固、KG 双向同步为设计愿景。conflict_resolver 已实装但 KG 未接入。

---

## 13. 一句话总结

> **Episodic 是日记，Semantic 是笔记，Procedural 是心得，Working 是便签。**
>
> 不会做巩固的记忆 = 一本永远写不完的日记 = 没人看的冷存储。
> 会做巩固 = 日记被周期性翻出来提炼成笔记和心得 = **系统越用越通透**。
>
> 睡眠不是奢侈品。**不睡觉的 agent 是会累死的**（cache 爆炸 + 召回失效 + 语义漂移）。

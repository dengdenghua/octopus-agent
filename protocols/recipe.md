---
implementation_status: implemented
implemented_in:
  - runtime/safety/recovery/recipe_evaluator.py
last_verified: 2026-06-25
---

# Protocol · Context Recipe (上下文配方评估与进化)

> **最被低估的一层。**
> 同样的模型、同样的记忆、同样的知识 —— **拼装方式不同，成功率能差两倍**。
>
> 核心判断：**模型难优化、技能难迭代，但"怎么拼"每次都在重新决定，是最大的低悬果实**。

---

## 1. 核心观察

三个同样的"原料"：
- 同一模型（如 Sonnet）
- 同一记忆库（同样的过去对话）
- 同一 skill 池

两种"配方"（Context Composer 的参数组合）：

| 配方 A | 配方 B |
|---|---|
| memory_quota = 30% | memory_quota = 15% |
| recall top-5 近期 | recall top-10 相似度 + KG 两跳 |
| skill 注入: 名字+一句话 | skill 注入: 全文 |

**同样任务**，A 可能 50% 成功率 + 0.02 USD；B 可能 85% 成功率 + 0.08 USD。
"谁更好"**取决于任务类型**。代码补丁任务可能 A 够用；多步推理任务 B 才行。

---

## 2. Recipe 数据模型

```python
Recipe = {
    "recipe_id": uuid,
    "name": str,                        # "code_fix_light" / "research_deep" / ...
    "task_type": str,                   # 绑定任务类别（对应 F-Recipe 的分层）
    "arm_affinity": list[str],          # 哪些 Arm 会用
    "parent_recipe_id": uuid | None,    # 支持 crossover

    # ── 配方核心：八大可调参数 ──

    "quotas": {                         # 预算分配，必和 == 1.0
        "system": 0.15,
        "suckers": 0.10,
        "memory": 0.30,
        "history": 0.45,
    },

    "memory_recall": {
        "strategy": "recency" | "similarity" | "hybrid" | "episodic_only",
        "top_k": int,
        "time_window_days": int,
        "min_similarity": float,
    },

    "kg_recall": {
        "enabled": bool,
        "depth": int,                    # 从任务实体出发的跳数
        "max_triples": int,
        "confidence_min": float,
    },

    "skill_injection": {
        "policy": "affinity" | "all" | "recent_success",
        "detail_level": "name_only" | "name_desc" | "full_md",
        "max_skills": int,
    },

    "compression": {
        "strategy": "summarize" | "drop_oldest" | "none",
        "trigger_ratio": 0.9,
        "compressor_model": "haiku" | "local_slm",
    },

    "cache_key_policy": {
        "include": list[str],            # 哪些字段进 cache key
        "exclude": list[str],            # 哪些绝不进
        "normalize_text": bool,
    },

    "history_window": {
        "strategy": "last_n_turns" | "sliding_summary" | "layered",
        "last_n": int,
        "summary_after": int,
    },

    "critic_injection": {                # 程序性记忆中的规避规则
        "enabled": bool,
        "max_rules": int,
    },

    # ── 统计 ──
    "stats": {
        "sample_count": int,
        "success_rate": float,
        "avg_cost_usd": float,
        "avg_latency_ms": float,
        "f_recipe": float,
        "variance": float,                # 方差高 = 不稳定
    },

    "status": "shadow" | "canary" | "active" | "retired",
    "created_by": "human" | "mutation" | "crossover",
}
```

---

## 3. Recipe Registry（版本化配方库）

每个 `task_type` 独立维护一个 Registry —— 配方不跨任务类型通用：

```
genome/memory/recipes/
├── code_fix/
│   ├── v001_light.yaml
│   ├── v002_deep_kg.yaml (active)
│   ├── v003_hybrid_memory.yaml (canary 5%)
│   └── RETIRED/v000_baseline.yaml
├── data_query/
│   └── ...
└── research/
    └── ...
```

**task_type 枚举**（初始）：
- `code_fix` / `code_review` / `code_design`
- `data_query` / `data_analysis` / `data_viz`
- `web_research` / `doc_qa`
- `multi_step_reasoning`
- `quick_lookup` / `chitchat`

Arm 接到任务 → 先识别 task_type → 从对应 Registry 选 recipe。

---

## 4. F-Recipe 层（Fitness 分层扩展）

FITNESS.md 原有 4 层 hierarchy，现扩展为 **5 层**：

```
F-Skill  ≤  F-Trajectory.avg  ≤  F-Recipe  ≤  F-Arm.avg  ≤  F-Genome
                                   ↑
                                 NEW
```

### F-Recipe 公式

```python
def f_recipe(recipe: Recipe) -> float:
    traces = journal.filter(recipe_id=recipe.id, since_days=7)
    if len(traces) < cfg.min_samples: return None   # 样本不足

    W = {
        "success":   0.35,
        "cost_eff":  0.20,
        "latency":   0.15,
        "variance":  -0.15,    # ★ 方差越大越扣分（不稳定的配方风险高）
        "robust":    0.15,     # ★ 对输入噪声的鲁棒性
    }

    c = {
        "success":  mean_success(traces),
        "cost_eff": efficiency(mean_cost(traces), median_cost_same_task_type()),
        "latency":  efficiency(mean_latency(traces), median_latency_same_task_type()),
        "variance": std_dev(successes(traces)),
        "robust":   robustness_score(traces),        # 见 §5
    }
    return sigmoid(sum(W[k] * c[k] for k in W))
```

**两个独特维度**：

### 4.1 方差惩罚（variance penalty）
高分 + 高方差 = 偶然运气。一个配方平均 0.8 但有时 0.3 有时 1.0，不如稳定 0.7 的配方。
```python
variance = std([1 if t.success else 0 for t in traces])
```

### 4.2 鲁棒性（robustness）
同一 task_type 下不同 input 表述、不同用户、不同时段的分数标准差越小越好。
```python
def robustness_score(traces):
    buckets = group_by_input_signature(traces)
    per_bucket_means = [mean_success(b) for b in buckets]
    return 1.0 / (1.0 + std(per_bucket_means))  # 越均匀得分越高
```

> 这两个维度是 trajectory 层没有的 —— **配方评估天然需要看"跨样本稳定性"**。

---

## 5. 选择算法（Per task_type Thompson）

每次新任务：
```python
def pick_recipe(task_type: str) -> Recipe:
    registry = recipe_registry[task_type]

    # 仅在 active + canary 里选
    candidates = registry.active_and_canary()

    # Thompson Sampling（按 F-Recipe posterior 抽样）
    posteriors = {r.id: beta_posterior(r.stats) for r in candidates}
    chosen = thompson_sample(posteriors)

    # canary 强制限流
    if chosen.status == "canary":
        if random() > cfg.canary_ratio:     # 默认 5%
            return registry.active_default()

    return chosen
```

**铁律**：同一 arm 在同一 task_type 下短时间内不频繁切配方（配方切换本身有开销 + 污染统计）。
→ `sticky_recipe_duration = 10 次调用`，10 次内不切。

---

## 6. Mutation 操作器

每个字段都有对应的变异算子。**GEN-I5（单字段变异）仍然铁律 —— 一次只动一个**：

| 字段 | 操作器 | 步长 |
|---|---|---|
| `quotas.*` | shift ±5% 到邻居 | 5% |
| `memory_recall.top_k` | ±2 | 2 |
| `memory_recall.strategy` | enum 切换 | 整跳 |
| `kg_recall.enabled` | toggle | bool |
| `kg_recall.depth` | ±1 | 1 |
| `skill_injection.detail_level` | 升降一档 | 1 档 |
| `compression.trigger_ratio` | ±0.05 | 0.05 |
| `history_window.last_n` | ±3 | 3 |

```python
def mutate_recipe(parent: Recipe, rng: Random) -> Recipe:
    field = rng.weighted_choice(MUTABLE_FIELDS, weights=FIELD_PRIORS)
    operator = FIELD_OPERATORS[field]
    new_value = operator.apply(current=get_field(parent, field), rng=rng)

    child = parent.copy()
    set_field(child, field, new_value)
    child.recipe_id = uuid4()
    child.parent_recipe_id = parent.recipe_id
    child.status = "shadow"
    child.created_by = "mutation"
    return child
```

---

## 7. Crossover（跨任务学习）

**重要差异**：不同 task_type 的配方不能直接交叉（语义不同），但**结构相似的任务对**可以：

```python
COMPATIBLE_PAIRS = {
    ("code_fix", "code_review"),
    ("data_query", "data_analysis"),
    ("web_research", "doc_qa"),
}

def crossover_recipe(a: Recipe, b: Recipe) -> Recipe:
    if (a.task_type, b.task_type) not in COMPATIBLE_PAIRS:
        raise IncompatibleCrossover()
    # 按字段各取一半
    child = empty_recipe()
    for field in MUTABLE_FIELDS:
        child[field] = rng.choice([a, b])[field]
    child.parent_recipe_id = None  # 双亲记到 metadata
    child.metadata.parents = [a.recipe_id, b.recipe_id]
    return child
```

---

## 8. Shadow + Canary 晋升（复用 evolution.md 模式）

Recipe 晋升沿用已有的 Shadow → Canary → Public 模式（[evolution.md](evolution.md)）：

```
new_recipe (status=shadow)
    ↓  run_shadow_eval: 取 100 条同 task_type 历史 trajectory 回放
    ↓  F-Recipe_shadow > F-Recipe_current * 1.03 ?
    ↓  variance < threshold ?
    ↓  全部通过
canary (5% 流量)
    ↓  观察 7 天
    ↓  F-Recipe_live ≥ shadow 预测值的 90%?
    ↓  无事故
active (100%)
```

**特殊约束**：
- Shadow 评估必须跑 ≥ 100 条 trajectory 回放（样本少方差大不可信）
- Canary 观察 **7 天**（比 skill 的 1 小时长，因为方差是关键指标）
- Active 晋升后，**老 active 降为 backup**（不 retire）—— 方便快速回滚

---

## 9. 与既有模块的集成

### 与 hemolymph/ContextComposer
```python
# hemolymph 入口，每轮调用前
def compose(task, arm, context_inputs):
    task_type = classify_task_type(task)
    recipe = recipe_registry.pick_recipe(task_type)
    packet = build_context(context_inputs, recipe)
    telemetry.record("context.recipe_used", recipe_id=recipe.id)
    return packet
```

### 与 camouflage/StrategySelector
Camouflage 原本做**策略**级 A/B（planner model / executor model）。
Recipe 做**配方**级 A/B（Context 拼装方式）。
两者是**独立维度**，可以叠加（2×2×... 配置空间）。
Thompson Sampling 分别在各自 posterior 上跑，互不干扰。

### 与 regeneration/
新增子目录 `regeneration/recipe_evaluator/`（SIX_MODULES 缺口 4）：
- 夜间跑 F-Recipe 更新
- Mutator 产 10 个新候选 / 夜
- Crossover 在兼容 task_type 对之间合成
- 淘汰 `retired_if`：30 天无调用 + F-Recipe < median

### 与 spinal_cord/
Reflex 命中的请求**不走 recipe** —— 直接返回 cache。
但 Reflex 规则也有"配方"概念（cache key 策略、matcher 顺序），本协议不管 Reflex 那套，归 [reflex.md](reflex.md)。

### 与 genome/dna/
Recipe Registry 是**任务级 DNA**，不是全局 DNA。
但 `recipe_task_type_taxonomy` 本身（有哪些 task_type）归入全局 DNA，MONOTONIC 锁 —— 只增不删。

---

## 10. 不变量（RCP-I 系列）

| ID | 内容 | 执行层级 |
|---|---|---|
| RCP-I1 | Recipe 绑 task_type，不可跨类型直接用 | Runtime Assert |
| RCP-I2 | 同 arm 在同 task_type 下 10 次内不切配方（sticky）| Runtime Assert |
| RCP-I3 | F-Recipe 样本数 < 阈值时不得参与 Thompson | Runtime Assert |
| RCP-I4 | Shadow 评估必须 ≥ 100 条 trajectory 回放 | **Runtime Gate** |
| RCP-I5 | 高方差配方不得晋升 active（即使均值高）| Runtime Gate |
| RCP-I6 | Active 晋升时老 active 保留为 backup，不 retire | Runtime Assert |
| RCP-I7 | 跨 task_type crossover 限白名单（COMPATIBLE_PAIRS）| Schema enforce |
| RCP-I8 | Recipe 变更必入 Journal | Runtime Assert |
| RCP-I9 | Quota 字段总和 = 1.0 | Schema enforce |

### Cross-cutting

**CC-R1 · "Recipe 插入 Fitness 对齐链"**
- 参与方：RCP-I* + CC-F1（4 层对齐不等式升级为 5 层）
- 公式：`F-Skill ≤ F-Trajectory.avg ≤ F-Recipe ≤ F-Arm.avg ≤ F-Genome`
- Runtime Assert。

**CC-R2 · "Task_type 分类器必须独立于 Recipe"**
- 参与方：RCP-I1 + digestion INGEST
- 描述：task_type 分类发生在 INGEST / CLASSIFY 阶段，**先于** recipe 选择。不能让 recipe 影响分类（自证循环）。
- Lint 规则。

**CC-R3 · "方差是配方的一票否决"**
- 参与方：RCP-I5 + FITNESS 的 drift guard
- 描述：高均值 + 高方差 = 运气好，非真好。variance > threshold 直接拒晋升。
- Runtime Gate。

---

## 11. 配置契约

```yaml
recipe:
  enabled: true
  task_type_taxonomy:
    - code_fix
    - code_review
    - code_design
    - data_query
    - data_analysis
    - data_viz
    - web_research
    - doc_qa
    - multi_step_reasoning
    - quick_lookup
    - chitchat

  selection:
    algorithm: thompson
    sticky_calls: 10
    canary_ratio: 0.05
    fallback_to_default_if_no_data: true

  evolution:
    mutation:
      per_task_type_per_night: 10
      field_priors:
        quotas: 0.25
        memory_recall: 0.20
        kg_recall: 0.10
        skill_injection: 0.15
        compression: 0.10
        history_window: 0.15
        critic_injection: 0.05
    crossover:
      compatible_pairs:
        - [code_fix, code_review]
        - [data_query, data_analysis]
        - [web_research, doc_qa]
    gates:
      shadow_min_samples: 100
      shadow_min_fitness_gain: 0.03
      shadow_max_variance: 0.20
      canary_duration_days: 7
      canary_live_vs_shadow_min: 0.90

  retirement:
    unused_days: 30
    f_recipe_below_median: true
    keep_backup_active: true

  f_recipe:
    weights:
      success: 0.35
      cost_eff: 0.20
      latency: 0.15
      variance: -0.15
      robust: 0.15
    min_samples_required: 30
```

---

## 12. 可观测性

| Metric | 用途 |
|---|---|
| `recipe.active_count{task_type}` | 每类任务现活配方数 |
| `recipe.canary_count{task_type}` | 灰度中 |
| `recipe.f_recipe{recipe_id}` | 各配方健康度 |
| `recipe.variance{recipe_id}` | 稳定性 |
| `recipe.crossover_attempt_count` | 交叉尝试次数 |
| `recipe.crossover_success_rate` | 交叉产出通过 shadow 的比例 |
| `recipe.thompson_exploration_ratio` | Thompson 在探索 vs 利用的分配 |
| `recipe.task_type_misclassification_rate` | 分类错误率（核心质量信号）|

### 警戒线
- `f_recipe{active}` 单月下降 > 10% → 排查环境变化（依赖 / 模型版本）
- `task_type_misclassification_rate > 15%` → 分类器需要重训
- `canary_rollback_count / canary_count > 50%` → mutator 步长太大

---

## 13. 反模式

| 反模式 | 后果 | 破解 |
|---|---|---|
| 全局一个 recipe 通吃所有任务 | 不同任务最优配方差异被抹平 | 按 task_type 独立 Registry |
| 只看均值选 recipe | 高方差碰运气的假赢家 | 必减方差项（RCP-I5）|
| Recipe 频繁切换 | 统计污染 + 切换本身有开销 | Sticky（RCP-I2）|
| Shadow 样本数 < 30 | 统计不显著 | ≥ 100 条（RCP-I4）|
| 跨不兼容 task_type crossover | 产生畸形配方 | 白名单（RCP-I7）|
| Retire 无 backup | 回滚失败 | 保留 backup（RCP-I6）|
| Task_type 分类依赖 recipe | 自证循环 | 必在 INGEST 阶段完成（CC-R2）|
| Quota 不标准化 | context 预算不守恒 | Schema 强制 sum==1.0（RCP-I9）|

---

## 14. 一句话总结

> **Skill 让你会做事，Recipe 让你会"做这件事时怎么想"。**
>
> 前者改变能力边界，后者改变能力发挥。
> 模型/记忆/知识都难动 —— **recipe 是每次 LLM 调用之前都在重新决定的、最大的、几乎免费的优化面**。
>
> 不做 Recipe Evolution = 每次都用手写的固定上下文拼装方式 = **把 2× 成功率的低悬果实扔在地上**。

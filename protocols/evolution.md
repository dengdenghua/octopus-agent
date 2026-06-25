---
implementation_status: implemented
implemented_in:
  - runtime/safety/evolution/fitness.py
  - runtime/safety/evolution/drift_monitor.py
last_verified: 2026-06-25
---

# Protocol · Evolution (再生 / 自进化协议)

> **原则 ④ Variation + Selection** 的具体协议。
> 三条回路：**正向** (成功路径 → Skill)、**负向** (失败路径 → 规避规则)、**策略** (A/B → 最优参数)。
> 核心不变量：**所有进化离线跑、走 Batch API、新产物隔离验证后才上线**。

---

## 三条回路总览

```
Journal (Trajectory 落盘)
    │
    ▼
┌──────────────┐
│ Trajectory   │ ──→ sample & cluster
│ 采集          │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Evaluator    │ Batch API 打分（夜间）
└──────┬───────┘
       │
       ├─→ 高分 + 高频 ──→ SkillForge (正向)  ──→ suckers/custom/
       ├─→ 低分模式   ──→ RuleExtractor (负向) ──→ Cerebrum planner prompt
       └─→ 策略成本曲线 ──→ Camouflage 权重更新  ──→ 下周期路由
```

---

## 数据模型

```python
Trajectory = {
    "trajectory_id": uuid,
    "task_id": uuid,
    "arm_id": str,
    "strategy_id": str,             # Camouflage 当前策略
    "steps": list[Step],
    "outcome": {
        "success": bool,
        "user_rating": int | None,   # 1..5
        "cost_usd": float,
        "tokens": int,
        "latency_ms": int,
        "degraded": bool,
    },
    "immune_events": list[ImmuneEvent],
    "started_at": datetime,
    "completed_at": datetime,
}

Step = {
    "step_id": int,
    "action": {"sucker_id": str, "args": dict},
    "result": {"status": str, "output_hash": str, "cost": CostEntry},
    "context_hash": str,             # 上下文摘要哈希，用于去重
}

Score = {
    "trajectory_id": uuid,
    "composite": float,               # 0..1
    "components": {
        "success": float,
        "cost_efficiency": float,
        "latency_efficiency": float,
        "user_rating": float,
        "loop_penalty": float,        # 负项：循环步数检测
        "failed_step_penalty": float, # 负项
    },
    "eval_model": str,
    "eval_cost_usd": float,
}

ForgedSkill = {
    "skill_id": uuid,
    "name": str,
    "description": str,
    "affinity": list[str],
    "cost_profile": "low" | "mid" | "high",
    "script": str,                    # 从高分路径抽出的通用脚本
    "source_trajectories": list[uuid],
    "shadow_test_stats": {"runs": int, "success_rate": float},
    "status": "shadow" | "canary" | "public" | "retired",
}

LearnedRule = {
    "rule_id": uuid,
    "pattern": str,                   # "when X + Y, avoid Z"
    "reason": str,
    "mitigation": str,
    "source_failures": list[uuid],
    "injected_into_prompt": bool,
}
```

---

## 调度

```yaml
regeneration:
  trajectory:
    sample_rate: 1.0                # 先全采，稳定后可 <1
  evaluator:
    mode: batch                     # Anthropic Batch API
    schedule: "0 2 * * *"           # 每日 02:00
    eval_model: claude-haiku-4-5-20251001
  skill_forge:
    min_hits: 5
    min_success_rate: 0.7
    shadow_runs_required: 10
    shadow_success_threshold: 0.8
  reflection:
    inject_into_planner_prompt: true
    prompt_section_name: "learned_mitigations"
    max_rules_in_prompt: 30         # 超限 LRU 淘汰
```

---

## 评分算法

```python
def score(traj: Trajectory) -> Score:
    W = {  # 可 Camouflage 做 A/B
        "success": 0.40,
        "cost_efficiency": 0.20,
        "latency_efficiency": 0.10,
        "user_rating": 0.15,
        "loop_penalty": -0.10,
        "failed_step_penalty": -0.05,
    }

    c = {
        "success": 1.0 if traj.outcome.success else 0.0,
        "cost_efficiency": efficiency(traj.outcome.cost_usd, category_median_cost(traj)),
        "latency_efficiency": efficiency(traj.outcome.latency_ms, category_median_latency(traj)),
        "user_rating": (traj.outcome.user_rating or 3) / 5,
        "loop_penalty": detect_loops(traj.steps),
        "failed_step_penalty": count_failed_steps(traj.steps) / max(len(traj.steps), 1),
    }
    composite = sigmoid(sum(W[k] * c[k] for k in W))
    return Score(trajectory_id=traj.trajectory_id, composite=composite, components=c, ...)


def efficiency(actual, median):
    if median == 0: return 1.0
    return clamp(median / max(actual, 1e-6), 0, 2) / 2   # median 水平得 0.5，越省越接近 1
```

---

## 正向回路：Skill Forge

### 路径聚类

```python
def find_forgeable_patterns(scored_trajs):
    # 只挑高分
    high = [t for t in scored_trajs if score_of(t).composite >= 0.75]

    # 按 (sucker_sequence, arm_affinity) 做哈希聚类
    clusters = defaultdict(list)
    for t in high:
        key = path_signature(t.steps)
        clusters[key].append(t)

    # 门槛过滤
    return [
        (key, cluster) for key, cluster in clusters.items()
        if len(cluster) >= cfg.min_hits
        and success_rate(cluster) >= cfg.min_success_rate
        and mean_cost(cluster) < 1.2 * median_cost(same_category(cluster))
    ]
```

### 技能锻造

```python
def forge_skill(pattern_key, cluster) -> ForgedSkill:
    # 1. 用 LLM 抽象化：把 N 条具体 trajectory 合并成参数化脚本
    abstraction = call_model(
        FORGE_PROMPT.fill(
            trajectories=cluster,
            instruction="Extract the invariant pattern + parameterize variables"
        )
    )

    skill = ForgedSkill(
        name=abstraction.suggested_name,
        description=abstraction.one_line_intent,
        affinity=detect_affinity(cluster),
        cost_profile=classify_cost(mean_cost(cluster)),
        script=abstraction.script,
        source_trajectories=[t.trajectory_id for t in cluster],
        status="shadow",
    )

    write_skill_md(skill, path=f"suckers/custom/forged/{skill.skill_id}.md")
    return skill
```

### 影子验证（必须，防污染）

```python
def shadow_validate(skill: ForgedSkill):
    # 从历史 trajectory 抽 10 条类似的作为测试集，回放
    test_cases = sample_similar_trajectories(skill.source_trajectories, n=10)

    results = []
    for tc in test_cases:
        r = beak.bite(skill, tc.args, mantle=local_sandbox())
        results.append(r.status == "success")

    success_rate = mean(results)
    skill.shadow_test_stats = {"runs": len(results), "success_rate": success_rate}

    if success_rate >= cfg.shadow_success_threshold:
        skill.status = "canary"      # 进入 5% 流量灰度
        chromatophores.publish("skill.forged", skill_id=skill.skill_id)
    else:
        skill.status = "retired"
        log("shadow_failed", skill=skill, success_rate=success_rate)
```

### 灰度晋升

```python
# 灰度中的 canary skill 只对 5% 的匹配任务暴露
def canary_rollout(skill):
    if skill.status != "canary": return
    stats = collect_last_7d_stats(skill)
    if stats.runs >= 50 and stats.success_rate >= 0.85:
        skill.status = "public"
        move_to(skill, "suckers/public/")
    elif stats.success_rate < 0.5:
        skill.status = "retired"
```

---

## 负向回路：Rule Extraction

```python
def extract_rules(scored_trajs) -> list[LearnedRule]:
    low = [t for t in scored_trajs if score_of(t).composite <= 0.25]

    # 按失败类型聚类
    clusters = cluster_by_failure_signature(low, k="auto")

    rules = []
    for cluster in clusters:
        # LLM 归纳
        analysis = call_model(
            RULE_PROMPT.fill(
                failures=cluster,
                ask="What common precondition led to failure? How to avoid next time?"
            )
        )
        rules.append(LearnedRule(
            pattern=analysis.precondition,
            reason=analysis.root_cause,
            mitigation=analysis.mitigation,
            source_failures=[t.trajectory_id for t in cluster],
        ))
    return rules


def inject_into_planner(rules: list[LearnedRule]):
    # 更新 Cerebrum 的 system prompt 的 learned_mitigations 段
    current = cerebrum.prompt.get_section("learned_mitigations")

    merged = dedupe_and_lru(current + rules, limit=cfg.max_rules_in_prompt)

    cerebrum.prompt.set_section("learned_mitigations", format_as_bullets(merged))
    cerebrum.prompt.invalidate_cache()       # 前缀变了必须重 warm
    eyes.models.flush_prompt_cache_hint()
```

---

## 策略回路：Camouflage 反馈

```python
def update_strategy_weights():
    # 按 strategy_id 聚合 7 日评分均值
    by_strategy = groupby(recent_trajs, key="strategy_id")
    stats = {
        sid: {
            "mean_score": mean(score_of(t) for t in ts),
            "mean_cost": mean(t.outcome.cost_usd for t in ts),
            "sample": len(ts),
        }
        for sid, ts in by_strategy.items()
    }
    # Thompson Sampling 更新 prior
    for sid, s in stats.items():
        camouflage.posteriors[sid].update(s.mean_score, s.sample)

    # 日志播报
    chromatophores.publish("evolution.strategy_update", stats=stats)
```

---

## 调度器入口

```python
# 每晚 02:00 触发
def nightly_evolve():
    since = now() - timedelta(hours=24)
    trajs = genome.journal.trajectories_since(since)

    # 1) 评分（Batch API）
    batch = evaluator.submit_batch(trajs)
    wait_until(batch.complete, timeout=hours=3)
    scored = evaluator.collect(batch)

    # 2) 正向：Skill Forge
    for key, cluster in find_forgeable_patterns(scored):
        skill = forge_skill(key, cluster)
        shadow_validate(skill)

    # 3) 负向：Rule Extraction
    rules = extract_rules(scored)
    inject_into_planner(rules)

    # 4) 策略：Camouflage 权重更新
    update_strategy_weights()

    # 5) 指标上报
    report_evolution_metrics(scored)
```

---

## 集成点

| 时机 | 调用方 | 作用 |
|---|---|---|
| 每步执行后 | `arms.Worker` → `genome.journal` | 写 Step（原料）|
| 任务结束 | `ganglia.Runtime` → `genome.journal` | 写 Trajectory 封口 |
| 每晚 02:00 | scheduler → `regeneration.Evolver` | 跑三条回路 |
| Skill 产出 | `regeneration` → `suckers.SkillRegistry` | 热加载（先 shadow）|
| Rule 产出 | `regeneration` → `cerebrum.Prompt` | 注入 learned_mitigations 段 |
| 策略反馈 | `regeneration` → `camouflage.StrategySelector` | 更新 posterior |

---

## 不变量

1. **I1 · 评分只用 Batch API**：实时 API 跑评分 = 成本失控
2. **I2 · 新 Skill 必 shadow 后上线**：未通过 shadow 不得进 canary
3. **I3 · Canary 限 5% 流量**：失败立即 retire
4. **I4 · Prompt 段注入后必失效缓存**：learned_mitigations 变更 = 前缀变更 = 必须重 warm
5. **I5 · Memory × Evolution 双写隔离**：免疫事件和进化 trajectory 分表存（避免互相污染）
6. **I6 · Rule 数量上限 + LRU**：注入到 Cerebrum prompt 的规则不得无限增长
7. **I7 · Evolver 自身不直接改 Cerebrum 权重**：只改 prompt，不触碰模型参数

---

## 可观测性

| Metric | 含义 |
|---|---|
| `evolution.trajectories_per_day` | 原料量 |
| `evolution.eval_cost_usd` | 每晚评估的 Batch API 花费 |
| `evolution.forged_skill_count` | 新产出技能数 |
| `evolution.shadow_pass_rate` | 锻造出的 skill 通过影子验证的比例 |
| `evolution.canary_promotion_rate` | 从 canary 升到 public 的比例 |
| `evolution.rules_injected_count` | 注入 planner prompt 的规则数 |
| `evolution.roi_ratio` | 反思成本 vs 节省成本的 ratio |

### ROI 警戒线

前 2–4 周预计 ROI < 1（反思在烧钱），但**曲线必须拐头**：
- 第 4 周 ROI < 0.5 → 重评权重设定
- 第 8 周 ROI < 1 → 考虑暂停 Evolution，优先优化成本

---

## 反模式

- ❌ 评分走实时 API（成本失控）
- ❌ 新 Skill 不 shadow 就上 canary（污染 public 库）
- ❌ Rule 无限追加到 prompt（前缀膨胀，cache miss 暴涨）
- ❌ Evolver 改底层 LLM 权重（那是 Fine-tune，不是本协议）
- ❌ 在用户响应链路上等 Evolver（必须纯异步夜间跑）

# Protocol · Skill Testing (技能回归测试)

> **自进化系统不塌方的唯一保险。**
>
> 核心判断：**任何 skill 改写前必须先跑通它自己的回归测试集；不过则不落盘**。
>
> 不是 fitness、不是 shadow、不是 canary —— 这三个都在"事后"，只有回归测试能在"事前"硬拦。

---

## 1. 为什么这层和其他防线不可互相替代

| 防线 | 时机 | 能挡住什么 | 挡不住什么 |
|---|---|---|---|
| Schema Gate | 写入前 | 结构错误 | 语义错误 |
| Skill Regression Tests | **写入前** | **行为回归** | — |
| Shadow Eval | 写入后 | 与历史 trajectory 的 fitness 对比 | 未见过的关键场景 |
| Canary | 生产灰度 | 规模化失败 | 小样本漏 |
| Fitness | 长周期 | 慢性退化 | 即时行为 bug |

**缺了回归测试，你的 shadow 就是用"生产数据测试生产数据"** —— 看不见新 skill 改坏了的关键边界用例（因为那些用例在生产里本来就很少发生）。

---

## 2. 三层测试金字塔

每个 Sucker 必须有三类测试，各自门槛不同：

```
           ┌──────────────┐
           │   Golden     │   人工策展 · 10–30 条 · 100% 必过
           │   (IMMUTABLE)│   相当于"skill 的宪法"
           └──────────────┘
         ┌──────────────────┐
         │   Regression     │   自动从成功 trajectory 抓 · 100–500 条 · ≥ 95% 必过
         │   (append-only)  │   相当于"skill 的历史"
         └──────────────────┘
       ┌────────────────────────┐
       │   Synthesized Edge     │   LLM 基于失败模式生成 · 50+ · ≥ 80% 必过
       │   (evolving)           │   相当于"skill 的疫苗"
       └────────────────────────┘
```

### 2.1 Golden · 人工策展
- **数量**：每个 skill 10–30 条
- **来源**：skill 作者 + code review 补充
- **特征**：覆盖 skill 的**定义性行为**（"这个 skill 之所以叫这个名字，就是因为它会这样做"）
- **IMMUTABLE**：纳入基因锁的 IMMUTABLE 范围 —— 系统无权修改，只有人工 PR 能改
- **通过率**：**100%**。少一条都算失败。

### 2.2 Regression · 历史回放
- **数量**：每个 skill 100–500 条（依流量而定）
- **来源**：从 `genome/journal/` 自动挑 F-Trajectory ≥ 0.85 的轨迹，采样后入库
- **特征**：反映 skill 在**真实生产**里的常见路径
- **Append-only**：只能新增（历史永远是历史），不能删
- **通过率**：**≥ 95%**

### 2.3 Synthesized Edge · 合成疫苗
- **数量**：每个 skill ≥ 50（会持续增长）
- **来源**：
  - 从失败 trajectory 反推（`regeneration/reflection/` 产出的规避规则 → 转成测试）
  - LLM 根据 SKILL.md 描述合成对抗样本
  - 从免疫事件（IMM-I6）转化来的"攻击样本"
- **特征**：覆盖**历史上翻过车**或**理论上会翻车**的边界
- **Evolving**：会被 Regeneration 扩充
- **通过率**：**≥ 80%**（允许少量失败但需带理由）

---

## 3. 数据模型

### 3.1 测试文件结构

每个 skill 的测试放在 `suckers/<category>/<skill_id>/tests/`：

```
suckers/public/run_pytest/
├── SKILL.md
├── skill.py                      # 实现
└── tests/
    ├── golden/
    │   ├── 001_basic.yaml
    │   ├── 002_no_tests_found.yaml
    │   └── ...
    ├── regression/
    │   ├── auto_<uuid>.yaml
    │   └── ...
    └── synthesized/
        ├── edge_<uuid>.yaml
        └── ...
```

### 3.2 单条测试的 schema

```yaml
# tests/golden/001_basic.yaml
test_id: golden_001
tier: golden                        # golden | regression | synthesized
description: "pytest 跑通一个 simple pass case"

# 输入
input:
  args:
    repo_path: "${FIXTURE:simple_repo}"
    pattern: "test_*.py"
  context:
    arm_id: code_arm
    mantle: docker                  # 指定沙箱类型

# 期望
expect:
  # (1) 结构校验：输出必须匹配此 schema
  output_schema:
    status: "pass" | "fail"
    tests_run: int
    failures: list

  # (2) 行为校验：以下断言必须为真
  assertions:
    - "output.tests_run >= 1"
    - "output.status == 'pass'"
    - "output.failures == []"

  # (3) 交互校验：必须调用 / 必须不调用某些底层工具
  must_call: ["bash:pytest"]
  must_not_call: ["bash:rm", "network:*"]

  # (4) 成本边界
  max_tokens: 5000
  max_latency_ms: 30000
  max_cost_usd: 0.02

  # (5) 语义校验（对 LLM 输出型 skill 用）
  semantic_match: null              # 或 "output should describe test results"
  critic_threshold: null            # 或 0.8

# 元信息
metadata:
  created_by: "human" | "evolution" | "journal_capture"
  created_at: 2026-04-18T...
  source_trajectory: null | uuid
  immutable: true                   # golden 级 = true
```

### 3.3 Fixtures

测试共用的资源（样例 repo、mock response、种子数据）：

```
suckers/public/run_pytest/tests/
└── fixtures/
    ├── simple_repo/               # 一个 mock repo
    ├── empty_repo/
    └── mocks/
        └── github_api_200.json
```

fixture 可以跨 skill 共用：`suckers/_shared_fixtures/`。

---

## 4. 触发点 · 五处必须跑测试

### Trigger 1 · Skill Forge 产出新版本
```python
def forge_skill(cluster):
    new_skill = synthesize_from_traces(cluster)
    if not run_tests(new_skill, tier="all").passed:
        return ForgeResult.rejected("regression_tests_failed")
    # 通过才允许写盘
    write_to_shadow_dir(new_skill)
```

### Trigger 2 · Shadow → Canary 晋升前
必须再跑一次（防止 shadow 环境与 canary 环境差异）。

### Trigger 3 · Canary → Public 晋升前
跑 full suite（三层都跑），任何失败直接 retire。

### Trigger 4 · 定时回归（夜间）
每晚所有 production skill 全跑一遍，catch 依赖变化导致的 silent 退化。
- MCP server 更新 → 依赖 skill 可能受影响
- LLM 模型版本更新 → 行为可能漂移
- 基础数据 schema 变化 → ...

### Trigger 5 · 依赖变更主动触发
```yaml
# SKILL.md 声明依赖
depends_on:
  - mcp://anthropic/filesystem@1.2
  - bash:pytest
  - llm://claude-sonnet-4-6
```
上述任何依赖升级 → 立即触发该 skill 的 full test。

---

## 5. 通过判定（多维度合成）

一条测试的"通过"不是单一条件，是**多维度全通过**：

```python
def judge(test_result, expect) -> TestVerdict:
    checks = []

    # 1. Schema
    if expect.output_schema:
        checks.append(validate_schema(test_result.output, expect.output_schema))

    # 2. Assertions (eval 表达式)
    for assertion in expect.assertions or []:
        checks.append(eval_assertion(assertion, test_result.output))

    # 3. Must call / must not call
    checks.append(set(expect.must_call or []).issubset(test_result.calls))
    checks.append(set(expect.must_not_call or []).isdisjoint(test_result.calls))

    # 4. 成本上限
    if expect.max_tokens:
        checks.append(test_result.tokens <= expect.max_tokens)
    if expect.max_latency_ms:
        checks.append(test_result.latency_ms <= expect.max_latency_ms)

    # 5. 语义（对 LLM-输出 skill）
    if expect.semantic_match:
        similarity = embedding_cosine(test_result.output, expect.semantic_match)
        checks.append(similarity >= expect.critic_threshold or 0.8)

    return TestVerdict(
        passed=all(checks),
        per_check=checks,
    )
```

### 语义匹配的三种姿势（从便宜到贵）

| 姿势 | 适用 | 代价 |
|---|---|---|
| **精确匹配** | 结构化输出 / 代码补丁 / JSON | 零 |
| **Schema + 断言** | 半结构化（大多数 skill）| 零 |
| **Embedding 相似度** | 自然语言输出 | 低（本地模型）|
| **Critic LLM 打分** | 主观质量评估 | 中（用 Haiku 做裁判）|

**铁律**：禁止用"同样强度的 LLM"做裁判 —— 会有认同偏见。裁判必须比被测 skill 用的模型**小一档或独立供应商**。

---

## 6. Regression Trace 自动采集

每晚从 Journal 挑高分轨迹转为 regression test：

```python
def capture_regression_tests(skill_id):
    # 1. 拉近 7 天、F-Trajectory ≥ 0.85 的轨迹
    traces = journal.filter(
        skill=skill_id,
        f_trajectory_min=0.85,
        since_days=7,
    )

    # 2. 按场景聚类（避免同类用例过多）
    clusters = cluster_by_input_signature(traces)

    # 3. 每簇最多抓 3 条入库
    new_tests = []
    for cluster in clusters:
        for trace in cluster[:3]:
            test = trace_to_test(trace, tier="regression")
            if not exists_similar(test, existing_tests):  # 去重
                new_tests.append(test)

    # 4. 写盘（但不覆盖任何已有）
    for t in new_tests:
        write_test(skill_id, t, path=f"tests/regression/auto_{t.id}.yaml")
```

**不变量**：regression 测试**append-only**，永远不覆盖 / 不删除（对应 IMM-I3 风格）。

---

## 7. Synthesized Edge Cases 的生成

由 Regeneration 夜间流水线驱动：

```python
def synthesize_edge_cases(skill):
    # 来源 1：最近失败的 trajectory
    recent_fails = journal.filter(skill=skill.id, outcome="failed", since_days=7)
    tests_from_fails = [
        failure_to_negative_test(trace) for trace in recent_fails
    ]

    # 来源 2：免疫事件（攻击样本）
    immune_events = journal.immune_events_for(skill.id)
    tests_from_immune = [
        attack_to_adversarial_test(ev) for ev in immune_events
    ]

    # 来源 3：LLM 合成对抗样本
    adversarial = call_model(
        EDGE_SYNTHESIS_PROMPT.fill(
            skill_md=skill.description,
            known_failures=recent_fails[:5],
        ),
        instruction="Generate 5 adversarial test cases that would stress edge cases"
    )

    return tests_from_fails + tests_from_immune + adversarial
```

合成后先进 `tests/synthesized/` 的 **shadow 子目录**，跑当前 skill 确认"真的能跑出不同结果" —— 全都能过的"合成用例"没有防御价值，丢掉。

---

## 8. 集成点

| 时机 | 调用方 | API |
|---|---|---|
| Skill Forge 产出后 | `regeneration.skill_forge` → `skill_testing` | `run_tests(skill, tier="all")` |
| Shadow → Canary | `regeneration.shadow_gate` | `run_tests(skill, tier="all")` (二次)|
| Canary → Public | `regeneration.canary_gate` | `run_tests(skill, tier="full")` |
| 每晚回归 | scheduler → `skill_testing` | `run_nightly_regression()` |
| 依赖变更 | `suckers.registry` → `skill_testing` | `run_tests_for_dependents(dep_id)` |
| Skill 开发 PR | CI → `skill_testing` | Git pre-merge hook |

### 与 Gene Locks 的关系

在 [GENE_LOCKS.md](../GENE_LOCKS.md) 的 Lock Gate 中新增一类条件：
- **CONDITIONAL lock**: skill 写入 public 目录的前置条件 = 本协议的测试全通过

这让测试保险直接嵌入进化权限系统。

### 与 Immunity 的联动

测试失败的 skill 会 penalize 其 Adaptive 信任分（IMM-I 系列）：
```python
if test_result.failed:
    immunity.adaptive.penalize(skill_id, severity=test_result.failure_tier)
```

严重失败（golden tier 不过）直接把 skill 拉黑 24h。

---

## 9. 不变量（SKT-I 系列）

| ID | 内容 | 执行层级 |
|---|---|---|
| SKT-I1 | Golden 测试 IMMUTABLE，系统无权改写 | **Schema enforce** + gene_locks |
| SKT-I2 | Regression 测试 append-only，不得删除 | Schema enforce |
| SKT-I3 | 写盘前必过全层测试 | **Runtime Gate** |
| SKT-I4 | Canary → Public 必再跑一次 full suite | Runtime Gate |
| SKT-I5 | 测试结果必入 Journal（供 Evolution + 审计）| Runtime Assert |
| SKT-I6 | Critic LLM 必比被测 skill 低一档或独立供应商 | **Lint** |
| SKT-I7 | 合成边界用例进库前必须能"区分" —— 跑当前 skill 不全通过 | Runtime Assert |
| SKT-I8 | 依赖变更必触发受影响 skill 的测试 | Runtime Assert |

### 对应 Cross-cutting

**CC-S1 · "无测试不写盘"**
- 参与方：SKT-I3 + GEN-I1（三门）+ EVO-I2（skill shadow）
- Lint + Runtime Gate：禁止 `skill_registry.write_public(...)` 在未经 test pass 的路径调用

**CC-S2 · "Golden 测试是宪法"**
- 参与方：SKT-I1 + IMMUTABLE gene_lock
- Schema Enforce：Golden tests 归入 `lock_system_version` 邻居的不可改区

**CC-S3 · "测试失败降信任"**
- 参与方：SKT-I5 + IMM-I4 + BDG cost profile
- Runtime Assert：测试失败 → 免疫评分下调、skill cost profile 加"风险溢价"

---

## 10. 配置契约

```yaml
skill_testing:
  enabled: true
  tiers:
    golden:
      min_count_per_skill: 10
      pass_threshold: 1.0             # 100%
      immutable: true
    regression:
      min_count_per_skill: 100
      pass_threshold: 0.95
      capture:
        f_trajectory_min: 0.85
        since_days: 7
        per_cluster_max: 3
    synthesized:
      min_count_per_skill: 50
      pass_threshold: 0.80
      generation:
        nightly_batch_size: 10
        from_failures: true
        from_immune_events: true
        from_llm: true
        distinctness_check: true       # SKT-I7
  triggers:
    on_forge: true
    on_shadow_to_canary: true
    on_canary_to_public: true
    on_nightly: true
    on_dependency_change: true
  judge:
    semantic_backend: embedding        # embedding | critic_llm
    critic_model: claude-haiku-4-5-20251001
    embedding_threshold: 0.80
  on_failure:
    write_to_shadow: reject
    canary_rollback: immediate
    immune_score_penalty: 0.2
    public_blacklist_duration_hours: 24
```

---

## 11. 可观测性

| Metric | 用途 |
|---|---|
| `skill_testing.pass_rate{tier}` | 各层通过率 |
| `skill_testing.golden_count_per_skill` | 宪法密度 |
| `skill_testing.forge_reject_rate` | 锻造被测试挡回的比例（高 = 进化质量堪忧）|
| `skill_testing.nightly_regression_failures` | 每晚新发现的退化 |
| `skill_testing.synthesized_distinctness_rate` | 合成用例"有价值"的比例 |
| `skill_testing.critic_llm_cost_usd` | LLM 裁判月度花费 |

### 警戒线

| 指标 | 警告 | 严重 |
|---|---|---|
| `forge_reject_rate > 50%` | mutator 操作器太激进 | —— |
| `golden_pass_rate < 1.0` | ⚠️ 立即 halt skill | P0 事故 |
| `nightly_regression_failures > 10` | 某依赖爆了 | 溯源 |
| `synthesized_distinctness_rate < 0.3` | 合成器失效 | 重新生成 |

---

## 12. 反模式

| 反模式 | 后果 | 破解 |
|---|---|---|
| 没有 golden tests，只有 regression 回放 | 新变异把核心行为改错了没人发现（历史数据里原来就没有那个场景）| 强制每个 skill 至少 10 条 golden |
| 用同等强度 LLM 做 critic | 认同偏见、评分虚高 | SKT-I6：裁判降档或换供应商 |
| Golden 测试允许自动改写 | 宪法可被自己改 = 没宪法 | IMMUTABLE + gene_lock |
| Regression 测试被清理 | 历史盲区 | append-only + LRU 上限但不 delete |
| 合成用例全能过当前 skill | 合成器产出的都是"假难题" | SKT-I7：distinctness check |
| 只在 forge 跑一次 | 依赖变更导致的退化抓不到 | 五个 trigger 齐备 |
| 测试失败 = 跳过不报 | 静默崩溃 | on_failure 强制记账 + 免疫扣分 |

---

## 13. 一句话总结

> **Fitness 告诉你"这个 skill 的平均表现好不好"；
> 回归测试告诉你"这个 skill 的底线守没守住"。**
>
> 前者适合激进优化，后者防止优化走火。
>
> 缺了后者，你的自进化系统就是一个**没安全带的赛车** —— 平时跑得飞快，崩的时候粉身碎骨。

# Protocol · Workflow Rewrite (工作流自改写)

> 中心反思引擎的**第二条产出**（共 5 条）。
> Skill Forge 只会长新技能；Workflow Rewriter 会**改旧组合**。
>
> 核心判断：**失败 trajectory 是最好的教练** —— 每次工作流卡壳都精确指向某个节点该重写。
>
> 铁律：**改工作流比改技能危险**。技能是孤立的，工作流是调用链 —— 改错一个节点可能让下游全崩。

---

## 1. 工作流为什么要自改写

Regeneration 有三条已有能力：
- 产新 skill（skill_forge ✅）
- 产规避规则注入 planner prompt（reflection ✅）
- 调整 Camouflage 策略权重（strategy update ✅）

都是**加法**。但现实里：
- 某个 workflow 在 `fetch_data` 节点反复失败 →  该节点要换 skill 或重写
- `parse_result` 节点的下游断言太严 → 节点要放宽
- 整个子图逻辑过时 → 子图要替换

这些都是**改写**，不是新生。没这一层 → Regeneration 只会让系统**越来越胖**，不会让它**越来越准**。

---

## 2. Workflow 数据模型（回顾 + 扩展）

```python
Workflow = {
    "workflow_id": uuid,
    "name": str,
    "task_type": str,                    # 绑定 Recipe 的 task_type
    "version": int,                      # 单调递增
    "parent_workflow_id": uuid | None,

    # DAG
    "nodes": list[WorkflowNode],
    "edges": list[WorkflowEdge],

    # 外部契约 ★ 绝不可单方改
    "input_schema": JSONSchema,
    "output_schema": JSONSchema,

    # 统计
    "stats": {
        "invocation_count": int,
        "success_rate": float,
        "avg_cost_usd": float,
        "avg_latency_ms": float,
        "per_node_failure_rate": dict[node_id, float],
    },

    "alternatives": list[uuid],          # 可替代路径（A/B 对照组）
    "status": "shadow" | "canary" | "active" | "retired" | "deprecated",
    "replaced_by": uuid | None,
}

WorkflowNode = {
    "node_id": str,
    "kind": "sucker" | "subgraph" | "validator" | "branch" | "merger",
    "skill_ref": str | None,             # 对应 Sucker
    "args_template": dict,
    "input_schema": JSONSchema,
    "output_schema": JSONSchema,
    "failure_retry": int,
    "timeout_ms": int,
}

WorkflowEdge = {
    "from_node": str,
    "to_node": str,
    "kind": "normal" | "branch" | "chromatophore",
    "condition": str | None,             # eval 表达式
}
```

---

## 3. 三种进化机制

对应原始六边形描述的三条：A/B 分流 + 节点热替换 + 失败反向改写。

### 3.1 Mechanism-A · A/B 分流（已部分存在）

两个同 `input_schema` / `output_schema` 的 workflow 对同类任务分流：
```
task → router → [50%] workflow_v1 → stats_A
              → [50%] workflow_v2 → stats_B
              → 胜者 winner_rate > 0.6 → 晋升
```

**归属**：这一机制 **由 camouflage + recipe 共同承担**，不是 workflow_rewriter 的主要职责。本协议不重复写。

### 3.2 Mechanism-B · 节点热替换（Skill upgrade propagation）

当 `suckers/X` 产生新版本 `X@v2`，所有使用 X 的 workflow：

```python
def propagate_skill_upgrade(skill_id, old_version, new_version):
    affected = workflow_registry.using_skill(skill_id, old_version)

    for wf in affected:
        # 1. 检查 I/O 契约：新 skill 和老 skill 的 input_schema / output_schema 必须兼容
        if not schemas_compatible(old_version, new_version):
            log("incompatible_upgrade", wf=wf.id, skill=skill_id)
            notify_human_review(wf, skill_id)
            continue

        # 2. 产出新版 workflow（只改那一个节点）
        new_wf = wf.copy()
        new_wf.version += 1
        new_wf.parent_workflow_id = wf.workflow_id
        for node in new_wf.nodes:
            if node.skill_ref == f"{skill_id}@{old_version}":
                node.skill_ref = f"{skill_id}@{new_version}"

        # 3. 进入 shadow → canary 流程（见 §5）
        submit_for_rollout(new_wf)
```

**铁律**：Schema 不兼容 → 人工审核，不自动替换。

### 3.3 Mechanism-C · 失败反向改写（Failure-driven rewrite）

本协议的**主体部分**。流程：

```
Journal 失败 trajectory
    ↓
Failure Attribution  ← §4
    ↓
Rewrite Planner      ← §5
    ↓
六种改写动作之一     ← §5.2
    ↓
Shadow / Canary     ← §6
    ↓
晋升 or 回滚
```

---

## 4. Failure Attribution（失败归因）

**核心问题**：工作流失败了，该改哪个节点？

### 四种失败类别

| 类别 | 症状 | 责任节点 |
|---|---|---|
| **Direct Fault** | 节点本身抛错 / 超时 / 返回错误 | 该节点 |
| **Semantic Fault** | 节点成功，但输出"错误地对"（格式对但内容错）| 该节点 |
| **Contract Fault** | 下游节点拒收上游输出 | 上游或下游（模糊）|
| **Gap Fault** | 整个 DAG 缺一个必要步骤 | 结构缺陷 |

### 归因算法

```python
def attribute_failure(traj: Trajectory) -> FailureReport:
    report = FailureReport(trajectory_id=traj.id)

    # 1. 先找 Direct Fault
    for step in traj.steps:
        if step.result.status == "failed":
            report.direct_fault_nodes.append(step.node_id)

    # 2. Semantic Fault：下一步骤基于此步骤输出 LLM 调用产出"歧义"/"无用"/"相反"
    for i, step in enumerate(traj.steps[:-1]):
        next_step = traj.steps[i + 1]
        if step.result.status == "success" and next_step.result.status == "failed":
            if semantic_mismatch(step.output, next_step.expected_input):
                report.semantic_fault_nodes.append(step.node_id)

    # 3. Contract Fault：schema 拒收
    for step in traj.steps:
        if step.error_type == "schema_mismatch":
            report.contract_fault_edges.append((step.prev_node_id, step.node_id))

    # 4. Gap Fault：LLM 事后分析 "这里是不是少了一个验证步骤"
    if report.is_empty() and traj.outcome.success is False:
        gap = llm_gap_analysis(traj, critic_model="haiku")
        if gap.confidence >= 0.7:
            report.gap_faults.append(gap)

    return report
```

### 最小样本门槛

**一次失败不归因** —— Regeneration 夜间流水线对同一 workflow 的失败做**聚类**，同簇 ≥ 5 次才触发归因改写（防抖 + 抗偶发）。

---

## 5. Rewrite Planner（改写规划器）

### 5.1 决策路径

```python
def plan_rewrite(wf: Workflow, report: FailureReport) -> RewritePatch | None:
    cluster_size = report.cluster_size
    if cluster_size < cfg.min_cluster_size: return None   # 防抖

    # 优先级：Direct > Semantic > Contract > Gap
    if report.direct_fault_nodes:
        return plan_for_direct_faults(wf, report.direct_fault_nodes, report)
    if report.semantic_fault_nodes:
        return plan_for_semantic_faults(wf, report.semantic_fault_nodes, report)
    if report.contract_fault_edges:
        return plan_for_contract_faults(wf, report.contract_fault_edges, report)
    if report.gap_faults:
        return plan_for_gaps(wf, report.gap_faults, report)

    return None
```

### 5.2 六种改写动作

| 动作 | 适用 | 风险 |
|---|---|---|
| **Replace** 换 skill | Direct Fault · 该 skill 新版本更好 | 低（有 schema 守护）|
| **Repair** 改 args/后处理 | Semantic Fault · 参数化错 | 中（LLM 生成，需验证）|
| **Insert** 加 validator | Contract Fault · 缺中间层 | 低（纯加法）|
| **Remove** 删冗余节点 | 冗余节点反复空跑 | 高（可能漏校验）|
| **Rewire** 改边 | 数据流顺序错 | 中 |
| **Subgraph Replace** | Gap Fault · 整段重写 | 高 |

### 5.3 每种动作的实现（简化版）

```python
def plan_for_direct_faults(wf, faulty_nodes, report):
    for node in faulty_nodes:
        # 先尝试 Replace
        alt_skill = find_alternative_skill(node.skill_ref, same_schema=True)
        if alt_skill and alt_skill.success_rate > node.skill.success_rate * 1.1:
            return RewritePatch.replace(node.node_id, alt_skill)

        # 再尝试 Repair：LLM 分析 args_template 是否有问题
        repair_suggestion = llm_repair(
            node=node,
            failures=report.failed_trajectories_for(node),
            model="haiku",
        )
        if repair_suggestion.confidence >= 0.7:
            return RewritePatch.repair(node.node_id, repair_suggestion)

    return None


def plan_for_gaps(wf, gap_faults, report):
    # Gap 修复风险最高，永远提交 nuclear 标
    patch = llm_gap_fix(wf, gap_faults, model="sonnet")
    patch.risk_level = "nuclear"     # 需人工审批
    return patch
```

### 5.4 改写补丁数据模型

```python
RewritePatch = {
    "patch_id": uuid,
    "workflow_id": uuid,
    "action": "replace" | "repair" | "insert" | "remove" | "rewire" | "subgraph",
    "target_nodes": list[str],
    "target_edges": list[tuple],
    "new_nodes": list[WorkflowNode],
    "new_edges": list[WorkflowEdge],
    "removed_nodes": list[str],
    "rationale": str,                # LLM 给出的改写理由（入 Journal）
    "source_cluster": list[uuid],    # 驱动此改写的失败 trajectory
    "risk_level": "low" | "medium" | "high" | "nuclear",
    "requires_human_approval": bool,
}
```

---

## 6. Shadow + Canary for Workflows

### 6.1 Shadow 要跑"双证据"

Workflow shadow 比 skill shadow 严 —— 必须**双目标达成**：

```python
def shadow_workflow(new_wf: Workflow) -> ShadowReport:
    failure_traces = source_failure_cluster(new_wf)     # 驱动改写的失败样本
    success_traces = sample_success_traces(new_wf, n=100)  # 原工作流的成功样本

    # 目标 1：新工作流必须**真的修好**原失败
    fix_rate = sum(
        run_workflow(new_wf, t.input).success
        for t in failure_traces
    ) / len(failure_traces)
    if fix_rate < cfg.min_fix_rate:     # 默认 0.7
        return ShadowReport.fail("did_not_fix")

    # 目标 2：新工作流必须**不退化**原成功
    preserve_rate = sum(
        run_workflow(new_wf, t.input).success
        for t in success_traces
    ) / len(success_traces)
    if preserve_rate < cfg.min_preserve_rate:   # 默认 0.95
        return ShadowReport.fail("regressed_on_success")

    # 目标 3：成本/延迟不爆
    if mean_cost(new_wf) > mean_cost(old_wf) * 1.5:
        return ShadowReport.fail("too_expensive")

    return ShadowReport.pass_(fix_rate=fix_rate, preserve_rate=preserve_rate)
```

**关键**：preserve_rate 通常是杀手 —— 大量改写在 shadow 层被干掉，因为只看"修没修好"会忽略回归。

### 6.2 Canary

通过 Shadow → 5% 流量 canary → 观察 3 天（比 skill canary 长；比 recipe canary 短）：
- `fix_rate_live` ≥ shadow 预测值 × 0.85
- `preserve_rate_live` ≥ 0.95
- 无 P0/P1 事故

---

## 7. 不变量（WFR-I 系列）

| ID | 内容 | 执行层级 |
|---|---|---|
| WFR-I1 | Workflow 外部 I/O schema 不可单方改 —— 改需 QUORUM | **Schema enforce** + gene_lock |
| WFR-I2 | 单次失败不触发改写 —— 必须聚类 ≥ 5 次 | Runtime Assert |
| WFR-I3 | 改写必双目标：修失败 + 不退成功 | **Runtime Gate** |
| WFR-I4 | 运行中的工作流不可被改写（in-flight immunity）| Runtime Assert |
| WFR-I5 | Gap Fault 改写必标 nuclear，需人工批准 | Runtime Gate + Human Gate |
| WFR-I6 | Skill 升级触发的 workflow 热替换必校验 schema | Runtime Gate |
| WFR-I7 | 改写历史链不可循环（防 A→B→A 无限改）| Runtime Assert |
| WFR-I8 | Rewrite rationale 必入 Journal（人类可审计）| Runtime Assert |
| WFR-I9 | Subgraph Replace 风险最高，强制 Shadow 跑 ≥ 200 条 | Runtime Gate |
| WFR-I10 | Remove 动作必附回滚预案（保留被删节点 30 天）| Schema enforce |

### Cross-cutting

**CC-W1 · Schema 契约铁律**
- 参与方：WFR-I1 + DIG-I1（阶段契约）+ GEN-I7（不可逆 = nuclear）
- 描述：workflow 外部 I/O schema 是"社会契约" —— 改它等于改公共 API。系统无权单方改。

**CC-W2 · 改写必双证据**
- 参与方：WFR-I3 + 对应 FITNESS 的 coverage 维度
- 描述：只看"修没修好"会让系统学会"跳过难题"。必须同时证明成功率不退化。

**CC-W3 · In-flight 不改写**
- 参与方：WFR-I4 + GEN blast_zone warm
- 描述：workflow 正在跑时不得被 patch。必先 drain，再 apply。

**CC-W4 · 改写链不可循环**
- 参与方：WFR-I7 + EVO-I5 + GEN-I5
- 描述：检测改写环 A→B→C→A，发现即停该 workflow 的自改写 7 天（冷却）。

---

## 8. 与既有协议的挂接

### 与 regeneration/ 主流水线
```
夜间 2:00 回路
    ├─ skill_forge              ← 已有
    ├─ reflection.extract_rules ← 已有
    ├─ workflow_rewriter        ← ★ 本协议新增
    ├─ recipe_evaluator         ← 协议 recipe.md
    └─ memory_consolidator      ← 缺口 5 待写
```

### 与 gene_locks
- `workflow.input_schema` / `output_schema`：**QUORUM 锁**（2-of-3 审批）
- `workflow.nodes[].skill_ref`：MONOTONIC（只允许换同 schema 的新版本，反向换 nuclear）
- Subgraph Replace：nuclear 锁

### 与 skill_testing
Workflow Rewrite 后**必须**跑相关 skill 的回归测试 —— 新旧 workflow 可能调用同 skill 但姿势不同，也会暴露 skill 的 edge case。
```python
after_rewrite:
    skills_in_use = extract_skill_refs(new_wf)
    for skill in skills_in_use:
        assert run_tests(skill, tier="all").passed
```

### 与 recipe
Workflow 和 Recipe 相互独立，但**共享 task_type**分类维度。
改写 workflow 会打破该 task_type 下的 recipe 统计（因为执行路径变了）→ **受影响 recipe 的 sample_count 重置为 0**，重新收集样本。

### 与 camouflage
A/B 分流（Mechanism-A）由 camouflage 管，本协议不重复实现。
本协议只提供 `workflow_rewriter.propose_alternative(wf)` API 给 camouflage 调。

---

## 9. 配置契约

```yaml
workflow_rewrite:
  enabled: true

  failure_attribution:
    min_cluster_size: 5                     # 聚类 ≥ 5 次才触发
    llm_gap_analysis: true
    llm_model: claude-haiku-4-5-20251001

  rewrite_planner:
    repair_llm_confidence_min: 0.7
    alternative_skill_improvement_min: 0.1  # 10% 更好才替换
    subgraph_replace_llm: claude-sonnet-4-6

  shadow:
    min_fix_rate: 0.7
    min_preserve_rate: 0.95
    max_cost_multiplier: 1.5
    subgraph_replace_min_samples: 200

  canary:
    ratio: 0.05
    duration_days: 3
    live_fix_rate_min_ratio: 0.85

  cooldown:
    cycle_detection_window: 30              # 看最近 30 次改写
    cycle_freeze_days: 7

  schema_change:
    requires_quorum: true
    quorum: {m: 2, n: 3}

  retention:
    removed_node_retention_days: 30
```

---

## 10. 可观测性

| Metric | 用途 |
|---|---|
| `workflow_rewrite.patches_proposed` | 改写候选产出数 |
| `workflow_rewrite.patches_passed_shadow` | 通过 shadow 的比例（核心质量信号）|
| `workflow_rewrite.fix_rate{workflow_id}` | 每个改写实际修复了多少失败 |
| `workflow_rewrite.preserve_rate{workflow_id}` | 对原成功的保留率 |
| `workflow_rewrite.cycle_detected_count` | 改写环被检测的次数 |
| `workflow_rewrite.gap_fault_nuclear_pending` | 待人工审批的 Gap 改写 |
| `workflow_rewrite.rollback_count` | 灰度回滚次数（高 = 改写质量差）|

### 警戒线
- `patches_passed_shadow / proposed < 20%` → rewriter 信号太弱，先调失败归因再谈改写
- `preserve_rate < 0.90` 持续 → 改写激进，收紧门槛
- `cycle_detected > 3 / 周` → 归因或 planner 有系统性偏差

---

## 11. 反模式

| 反模式 | 后果 | 破解 |
|---|---|---|
| 单次失败即改写 | 偶发事件触发常态性改写，系统抖动 | WFR-I2（≥ 5 次聚类）|
| 只看 fix_rate 不看 preserve_rate | 学会"跳过难题" | 双证据（WFR-I3）|
| 改写中运行 | 调用方与被改方看到不同视图 | In-flight immunity（WFR-I4）|
| Schema 自动修改 | 破坏调用方契约 | QUORUM 锁（WFR-I1）|
| Subgraph Replace 自动执行 | 整段代码被 LLM 重写上线 | Nuclear 级强制人工（WFR-I5）|
| 改写历史无环检测 | A→B→C→A 反复改 | 环检测 + 冷却（WFR-I7）|
| Remove 不保留备份 | 回滚无处可去 | 30 天保留（WFR-I10）|
| Rewrite 不入 Journal | 人类无法追溯 | Rationale 必写（WFR-I8）|

---

## 12. 反思引擎完成度进度

| 信号 | 协议 | 状态 |
|---|---|---|
| 新 skill 候选 | [evolution.md](evolution.md) | ✅ |
| Workflow 改写建议 | **本协议** | ✅ 缺口 1 完成 |
| KG 新增三元组 | 缺口 2 | ⏳ |
| 记忆巩固指令 | 缺口 5 | ⏳ |
| 上下文配方打分 | [recipe.md](recipe.md) | ✅ |

**进度 3/5 = 60%**。反思引擎过半了。

---

## 13. 一句话总结

> **Skill Forge 让系统"长出新能力"，Workflow Rewriter 让系统"改对旧能力"。**
>
> 前者是加法，后者是减法 + 纠错 —— 缺一个，系统只能越来越胖，不会越来越准。
>
> 但 Workflow Rewrite 是**五个反思产出中风险最高**的：技能是原子、配方是参数、规则是文本，
> **只有工作流是"结构"** —— 改结构最容易把下游弄崩。所以本协议里 Gate / 锁 / 审批 加得最多。

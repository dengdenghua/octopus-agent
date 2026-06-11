# Protocol · Digestion (消化流水线)

> **原则 ⑥ Pipeline** 的具体协议。
> 复杂任务 = 七阶段流水线，每阶段有契约、预算、可观测、可回放。

---

## 流水线总览

```
┌───────┐   ┌────────┐   ┌──────┐   ┌──────────┐   ┌────────┐   ┌────────────┐   ┌───────┐
│INGEST │→ │CLASSIFY│→ │ PLAN │→ │ DISPATCH │→ │EXECUTE │→ │ SYNTHESIZE │→ │ STORE │
└───────┘   └────────┘   └──────┘   └──────────┘   └────────┘   └────────────┘   └───────┘
 Eyes       SpinalCord   Cerebrum   Ganglia        Arms+Beak     Cerebrum         Genome
```

Reflex hit 时流水线**短路**：INGEST → CLASSIFY → EXECUTE（直出反射结果）→ STORE。

---

## 阶段契约表

每个阶段**必须**声明：入参类型 / 出参类型 / Owner / 延迟预算 / 失败策略 / 指标。

| # | Stage | Owner | In | Out | Budget | On Fail |
|---|---|---|---|---|---|---|
| 1 | INGEST | `eyes.Perception` | `RawInput` | `ParsedIntent` | 200ms | reject, user-facing error |
| 2 | CLASSIFY | `spinal_cord.ReflexRouter` | `ParsedIntent` | `RouteDecision` | 10ms | fallback → deliberative |
| 3 | PLAN | `cerebrum.Planner` | `ParsedIntent` | `TaskGraph` | 3s | retry 1× 降档模型 |
| 4 | DISPATCH | `ganglia.Router` | `TaskGraph` | `list[ArmAssignment]` | 50ms | partial dispatch + alert |
| 5 | EXECUTE | `arms.Worker` + `beak.ToolExecutor` | `ArmAssignment` | `ArmResult` | 可变 / per-task budget | Ink 熔断 |
| 6 | SYNTHESIZE | `cerebrum.Aggregator` | `list[ArmResult]` | `FinalResponse` | 1s | 返回部分结果 + 标记 degraded |
| 7 | STORE | `genome.Journal` | Full trajectory | `trajectory_id` | 100ms（async）| 退化到本地队列重试 |

---

## 数据模型（跨阶段流动）

```python
RawInput = Union[UserText, File, MultimodalPayload, WebhookEvent]

ParsedIntent = {
    "intent_id": uuid,
    "raw": RawInput,
    "intent_type": str,        # "query" | "task" | "event" | "command"
    "normalized_goal": str,
    "modalities": list[str],
    "user_context": dict,
    "signals": list[AmbientSignal],   # 从 Skin 拉来
    "ts": float,
}

RouteDecision = {
    "path": "reflex" | "deliberative",
    "reflex_match": ReflexRule | None,
    "reflex_cost_estimate": float,
    "reason": str,
}

TaskGraph = {
    "task_id": uuid,
    "nodes": list[TaskNode],
    "edges": list[Edge],           # 含 ChromatophoreEdge
    "budget": {"tokens": int, "usd": float, "latency_ms": int},
    "strategy": str,               # Camouflage 选出的策略名
}

ArmAssignment = {
    "arm_id": str,
    "subgraph": TaskGraph,
    "context_packet": ContextPacket,   # 来自 Hemolymph
    "deadline": datetime,
}

ArmResult = {
    "arm_id": str,
    "status": "success" | "partial" | "failed" | "circuit_broken",
    "outputs": dict,
    "trajectory": list[Step],
    "cost": {"tokens": int, "usd": float, "latency_ms": int},
}

FinalResponse = {
    "task_id": uuid,
    "content": str | dict,
    "sources": list[ArmResult],
    "degraded": bool,
    "cost_total": CostSummary,
}
```

---

## 阶段伪代码

### 1) INGEST

```python
def ingest(raw: RawInput) -> ParsedIntent:
    # 多模态分流
    parsed = {
        "text": raw,
        "file": eyes.parse_file,
        "image": eyes.vision_model,
    }[detect_modality(raw)](raw)

    # 从 Skin 拉当前环境信号（非阻塞，超时 50ms 即 skip）
    signals = skin.recent(window_ms=60_000, timeout_ms=50)

    return ParsedIntent(
        intent_id=uuid4(),
        raw=raw,
        intent_type=classify_intent_type(parsed),
        normalized_goal=normalize(parsed),
        signals=signals,
        ts=now(),
    )
```

### 2) CLASSIFY (Reflex Gate)

```python
def classify(intent: ParsedIntent) -> RouteDecision:
    # 按 config 顺序尝试四种反射
    for matcher in [cache_match, regex_match, rule_engine, edge_slm]:
        hit = matcher.try_match(intent)
        if hit and hit.confidence >= threshold:
            return RouteDecision(path="reflex", reflex_match=hit, ...)
    return RouteDecision(path="deliberative")
```

### 3) PLAN

```python
def plan(intent: ParsedIntent) -> TaskGraph:
    # Camouflage 选策略
    strategy = camouflage.pick(task_type=intent.intent_type)

    # Hemolymph 打包上下文
    ctx = hemolymph.compose(intent, budget=strategy.context_budget)

    # 规划（可重试 1 次，降档模型）
    for attempt, model in [(1, strategy.planner_model), (2, strategy.fallback_model)]:
        try:
            graph = eyes.call_model(model, PLANNER_PROMPT.fill(ctx)).parse_as_graph()
            return graph.validate()
        except PlanningError as e:
            if attempt == 2:
                raise
            telemetry.record("plan.retry", reason=e)
```

### 4) DISPATCH

```python
def dispatch(graph: TaskGraph) -> list[ArmAssignment]:
    assignments = []
    for subgraph in graph.split_by_affinity():
        arm = pick_arm(subgraph.dominant_affinity)
        # 广播资源宣称，触发 Boids Separation 协商
        chromatophores.publish("sucker.grabbed", arm=arm.id, resources=subgraph.resources)
        assignments.append(ArmAssignment(arm_id=arm.id, subgraph=subgraph, ...))
    return assignments
```

### 5) EXECUTE

```python
def execute(assignment: ArmAssignment) -> ArmResult:
    arm = arms[assignment.arm_id]
    traj = []

    for step in assignment.subgraph.topological_steps():
        # ⚠️ 每步执行前必过免疫
        verdict = immunity.check(step.as_tool_call())
        if verdict == "reject": 
            return ArmResult(status="failed", reason="immune_reject")
        sandbox_level = "strict" if verdict == "quarantine" else "normal"

        # 预算闸门
        if ink.check_budget(assignment.task_id).exceeded:
            ink.squirt("budget")
            return ArmResult(status="circuit_broken")

        # 实际执行：Beak 在 Mantle 里咬
        result = beak.bite(step.sucker, step.args, mantle=arm.mantle(sandbox_level))
        traj.append(Step(action=step, result=result))

        # 免疫学习
        immunity.learn(step.as_tool_call(), result)

    return ArmResult(status="success", trajectory=traj, ...)
```

### 6) SYNTHESIZE

```python
def synthesize(results: list[ArmResult]) -> FinalResponse:
    # 失败腕允许被降级成 "部分结果"
    ok = [r for r in results if r.status == "success"]
    degraded = len(ok) < len(results)
    merged = cerebrum.aggregate(ok, strategy="concat" | "vote" | "llm_merge")
    return FinalResponse(content=merged, degraded=degraded, ...)
```

### 7) STORE

```python
def store(task_id, graph, results, response) -> trajectory_id:
    # 异步落 Journal，失败不阻塞用户响应
    asyncio.create_task(
        genome.journal.write(task_id, graph, results, response)
    )
    return task_id
```

---

## 不变量（Invariants）

> 这些是任何实现必须保证的性质；违反即 bug。

1. **I1 · 阶段契约严格**：某阶段的 Out 必须**严格匹配**下阶段的 In 的类型；boundary 处必校验。
2. **I2 · 阶段可回放**：给定阶段 In，重跑应得到语义等价的 Out（除 LLM 随机性外）。
3. **I3 · 反射短路不跳免疫**：即使走反射路径，EXECUTE 步骤的 `immunity.check` 仍必须触发。
4. **I4 · 用户响应不被 STORE 阻塞**：STORE 允许异步；同步的只有到 SYNTHESIZE。
5. **I5 · 预算单向递减**：`ink.budget` 在流水线内只减不增；任何"补血"必须记账。
6. **I6 · 每阶段必发 OTel span**：没有 span 的阶段视为未实现。

---

## 可观测性（每阶段 metrics）

| Metric | 类型 | 标签 |
|---|---|---|
| `stage.latency_ms` | histogram | stage, outcome |
| `stage.success_rate` | counter ratio | stage |
| `stage.input_bytes` / `output_bytes` | histogram | stage |
| `stage.retry_count` | counter | stage, reason |
| `digestion.end_to_end_ms` | histogram | intent_type, path |

---

## 回放与调试

- 每阶段 In/Out 存 Journal 各一份（小体积，哈希+摘要 + 指针到原 blob）
- 调试 CLI：`oa replay <stage> <trajectory_id>` → 从该阶段之后重新消化
- A/B 对照：Camouflage 可并行跑两条流水线，对齐入口分叉出口

---

## 反模式（禁止）

- ❌ 跳过 CLASSIFY 直接进 PLAN（让反射层永远没有成长机会）
- ❌ PLAN 阶段直接调工具（违反 Cerebrum 不碰工具的设计哲学）
- ❌ EXECUTE 阶段在 Mantle 外运行（违反 Beak-Mantle 铁律）
- ❌ SYNTHESIZE 再发起 LLM 大调用做"最终润色"（该在 PLAN 规划好）

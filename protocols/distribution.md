---
implementation_status: spec_only
implemented_in: []
last_verified: 2026-06-25
---

# Protocol · Distribution (端云协同部署)

> **原则 ⑤ Edge + Cloud** 的具体协议。
> Arm 部署拓扑 + 路由决策 + 降级回退。
> 核心不变量：**按三维度路由（latency / privacy / compute）+ Edge 永远能独立活**。

---

## 部署拓扑

```
        ┌──────────────────────┐
        │    Cloud Region      │      (stateful 重推理)
        │  ┌────────────────┐  │
        │  │   Cerebrum     │  │
        │  │   Arms(cloud)  │  │
        │  │   Genome ★      │  │
        │  │   Regeneration │  │
        │  └────────┬───────┘  │
        └───────────┼──────────┘
                    │ Nerves bus (MQTT/NATS over TLS)
                    │
       ─────────────┼─────────────────────────
                    │
        ┌───────────┼──────────┐
        │   Edge Node(s)       │       (低延迟 + 隐私)
        │  ┌────────────────┐  │
        │  │  Spinal Cord   │  │
        │  │  Arms(edge)    │  │
        │  │  Local cache   │  │
        │  │  Local LLM(可选)│  │
        │  └────────────────┘  │
        └──────────────────────┘
```

---

## 数据模型

```python
DeploymentTier = Literal["edge", "regional", "cloud"]

ArmDeployment = {
    "arm_id": str,
    "tier": DeploymentTier,
    "node_id": str,
    "capabilities": {
        "local_llm": bool,
        "local_tools": list[str],
        "network_egress": bool,
    },
    "heartbeat_at": datetime,
    "status": "online" | "degraded" | "offline",
}

LatencyBudget = {
    "p50_ms": int,
    "p99_ms": int,
    "deadline_ms": int,
}

PrivacyClass = Literal["public", "internal", "confidential", "personal"]

ComputeNeed = Literal["light", "medium", "heavy"]

RouteDecision = {
    "task_id": uuid,
    "assigned_arm": str,
    "tier_chosen": DeploymentTier,
    "reason": str,
    "fallback_plan": list[str],     # 候补 tier 顺序
}
```

---

## 三维度路由算法

```python
def route(task: TaskGraph) -> RouteDecision:
    latency = extract_latency_budget(task)
    privacy = classify_privacy(task)
    compute = estimate_compute_need(task)

    # 硬约束先过
    eligible_tiers = filter_by_hard_constraints(latency, privacy, compute)
    if not eligible_tiers:
        raise NoRouteError(task)

    # 软打分
    scored = []
    for tier in eligible_tiers:
        s = score_tier(tier, latency, privacy, compute)
        scored.append((tier, s))

    tier, best_score = max(scored, key=lambda x: x[1])
    arm = pick_arm_in_tier(tier, task)
    fallback = [t for t, _ in sorted(scored, key=lambda x: -x[1]) if t != tier]

    return RouteDecision(
        task_id=task.task_id,
        assigned_arm=arm.id,
        tier_chosen=tier,
        reason=f"lat={latency.deadline_ms}ms privacy={privacy} compute={compute}",
        fallback_plan=fallback,
    )
```

### 硬约束

```python
def filter_by_hard_constraints(lat, priv, comp) -> list[DeploymentTier]:
    tiers = ["edge", "regional", "cloud"]
    # 隐私硬约束
    if priv == "personal":
        tiers = [t for t in tiers if t == "edge"]
    elif priv == "confidential":
        tiers = [t for t in tiers if t in {"edge", "regional"}]
    # 延迟硬约束
    if lat.deadline_ms < 100:
        tiers = [t for t in tiers if t == "edge"]
    elif lat.deadline_ms < 1000:
        tiers = [t for t in tiers if t in {"edge", "regional"}]
    # 算力硬约束
    if comp == "heavy" and not any_tier_has_heavy_compute(tiers):
        tiers = [t for t in tiers if t != "edge"]
    return tiers
```

### 软打分

```python
def score_tier(tier, lat, priv, comp) -> float:
    s = 0.0
    # 延迟预算
    s += 30 * exp_decay(tier_p99_latency(tier) / lat.p99_ms)
    # 隐私匹配
    s += 25 * privacy_match_score(tier, priv)
    # 算力冗余
    s += 25 * compute_fit(tier, comp)
    # 当前负载（反比）
    s += 10 * (1 - current_load(tier))
    # 成本（反比）
    s += 10 * (1 / max(tier_unit_cost(tier), 0.01))
    return s
```

---

## 隐私级别与强制 Tier

| PrivacyClass | 允许 Tier | 示例 |
|---|---|---|
| `public` | edge / regional / cloud | 公开文档摘要 |
| `internal` | edge / regional / cloud | 公司内部问答 |
| `confidential` | edge / regional | 合同、商业数据 |
| `personal` | **仅 edge** | 个人相册、位置 |

---

## 降级回退

### 边端离线（Cloud 不可达）

```python
def on_cloud_unreachable(duration_s):
    hearts.enter_offline_mode()
    # 把所有 pending 任务根据硬约束重路由
    for task in pending_tasks:
        if can_handle_at_edge(task):
            reroute(task, tier="edge")
        else:
            defer(task, resume_when="cloud_back")

    # 降级能力集
    cerebrum.set_planner_model("edge_slm")
    spinal_cord.promote_cache_threshold()   # 更激进地吃反射

    # 用户可见通知
    siphon.broadcast("degraded_mode_active")
```

### 边端崩溃（Edge 不可用）

```python
def on_edge_unreachable(edge_node_id):
    # 非 personal 任务迁至 regional
    tasks_on_edge = arms_on_node(edge_node_id).pending_tasks
    for t in tasks_on_edge:
        if classify_privacy(t) == "personal":
            fail(t, reason="edge_offline_personal_data")
        else:
            reroute(t, tier="regional")
```

### 回归（Cloud 恢复）

```python
def on_cloud_back():
    # 不立即全量迁回 —— 按成本 / 负载逐步迁
    for task in deferred_tasks:
        resume(task)
    hearts.exit_offline_mode()
    # Evolution 批队列也恢复
    regeneration.schedule_nightly()
```

---

## Nerves bus 的跨 Tier 通信

Edge ↔ Cloud 通过 bus 传输，但有限制：

| 消息类型 | 边→云 | 云→边 | 加密 |
|---|---|---|---|
| `task.request` | ✅ | ✅ | TLS |
| `arm.result` | ✅ | ✅ | TLS |
| `chromatophore.*` | ✅（去本地化后）| ✅ | TLS |
| `genome.journal.write` | ✅（批量）| ✅ | TLS + 端加密（personal）|
| `evolution.*` | ❌（只云内）| ❌ | - |
| `alert.budget` | ✅ | ✅ | TLS |

### 消息批量化（省带宽）

```python
# Edge 侧
bus.batch_send("genome.journal.write", buffer_size=100, flush_interval_s=5)
# 敏感字段在 Edge 加密
bus.encrypt_fields_client_side(["user_id", "file_content"], pubkey=cloud_pubkey)
```

---

## 本地 LLM 的使用边界

Edge 可以可选部署本地小模型（Qwen-0.5B / Llama-3.2-1B 等），但严格限制用途：

| 场景 | 允许 | 理由 |
|---|---|---|
| 意图分类 | ✅ | 小模型的强项 |
| 反射兜底 | ✅ | 补 regex/cache 不足 |
| 上下文摘要（压缩）| ✅ | 离线私密场景 |
| 开放生成 | ❌ | 质量不够 |
| 工具调用规划 | ❌ | 会误调工具 |

---

## 集成点

| 时机 | 调用方 | API |
|---|---|---|
| Planner 决定路由 | `cerebrum` → `ganglia.Router` | `route(task)` → `RouteDecision` |
| 定时心跳 | `arms.*` → `ganglia.Registry` | `heartbeat(arm_id)` |
| 网络感知 | `skin` → `hearts` | `network.cloud_reachable` signal |
| 降级触发 | `hearts` → 全局 | `enter_offline_mode()` |
| 敏感数据标记 | `eyes.Perception` | `classify_privacy(intent)` |

---

## 配置契约

```yaml
distribution:
  tiers:
    edge:
      enabled: true
      node_affinity: local
      local_llm:
        enabled: false
        model: qwen-0.5b
    regional:
      enabled: true
      region: "asia-east"
    cloud:
      enabled: true
      provider: anthropic
  routing:
    latency_weights: {p50: 0.3, p99: 0.7}
    privacy_hard_map:
      personal: [edge]
      confidential: [edge, regional]
  offline_mode:
    detect_grace_seconds: 30
    cache_aggressiveness_boost: 2.0
    user_notify_on_degrade: true
  bus:
    encryption: tls_required
    client_side_encrypt_fields: [user_id, file_content]
    batch_journal_size: 100
    batch_journal_interval_s: 5
```

---

## 不变量

1. **I1 · Personal 绝不出 Edge**：这是最硬约束，违反即 data-leak 事故
2. **I2 · Edge 必须能独立活**：Cloud 全挂时，Edge + Spinal Cord + 本地腕仍响应基础任务
3. **I3 · 路由必有 fallback_plan**：主 tier 不可用时自动切换（除非硬约束禁止）
4. **I4 · Evolution 不过边**：进化流水线只在 Cloud 跑，Edge 不参与
5. **I5 · 敏感字段端加密**：跨 tier 传输前在发送方加密，接收方必有 pubkey
6. **I6 · Offline 模式必广播**：系统进入降级必须通知用户（Siphon 广播）

---

## 可观测性

| Metric | 含义 |
|---|---|
| `distribution.route_tier_distribution` | 各 tier 任务占比 |
| `distribution.fallback_invoked_count` | 主 tier 失败触发 fallback 次数 |
| `distribution.offline_mode_duration_s` | 处于降级的总时长 |
| `distribution.cross_tier_latency_p99` | 跨 tier 延迟 p99 |
| `distribution.privacy_violation_blocked` | 被硬约束拦下的次数（应为 0）|
| `distribution.edge_heartbeat_miss_rate` | 边节点心跳缺失率 |

---

## 反模式

- ❌ Personal 数据走 cloud（硬违规）
- ❌ Edge 只做 cache，不具备独立规划能力 → cloud 挂则全死
- ❌ 敏感字段在网关统一加密（应在发源地端加密）
- ❌ 按请求量均分 tier，不看隐私级别
- ❌ Fallback 只有一级；应该是完整的序列
- ❌ Offline 模式无声降级 → 用户以为服务正常但实际阉割

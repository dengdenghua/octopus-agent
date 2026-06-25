# ADR-010 · Swarm Resource Contention（网状编排的争用模型）

Status: Accepted (Phase 1 机制 ✅ · Phase 2 skill 声明+desktop 填充 ✅ · 消费侧避让待做) · Date: 2026-06-25

## Context

`架构.md` 长期声称 octopus 的差异化护城河是 **网状编排（mesh）**——Arm 之间
直接协调，而非中心化的 Lead+Sub-agents 树。底层原语其实早已建好且测过：

- `chromatophores/boids.py` 的 **`BoidsArbitrator`**：完整的资源claim仲裁器——
  优先级抢占、readonly 共存、TTL 过期 GC、`release`，且 **win 时已广播
  `sucker.grabbed`**。
- `arms/base.py` 的 **mailbox**：Worker 构造时订阅 `arm.mailbox.<id>`，有
  `send_to_arm` / `drain_mailbox` / `_on_step`。

但一次全栈核实（2026-06-25）发现:**整个 mesh 协调层休眠**——`arbitrate` /
`send_to_arm` / `_on_step` 的消费**全部没有生产调用方**。根因不是"差一行接
线"，而是 **swarm 按 `per_node` 预分配子图、运行时没有资源争用**：每个 node
只派给一个 Arm，两个 Arm 不会跑同一 node，所以没东西需要仲裁。

真正的争用来自**外部/物理独占资源**，与 node 划分正交：

- 单块**桌面屏幕** / 单台**手机设备**（同一时刻只能一个 Arm 控制）
- `browser_session_worker` —— 注释明言 "exclusively owns one browser + page"
- 同一**文件路径**的并发写
- 同一**限流 API key** 的并发调用

这些资源被并行 Arm 同 tick 触碰时必须**串行**。这正是 `BoidsArbitrator` 为之
而生、却从未被调用的场景。

## Decision

**在 SwarmRuntime 的派发边界（`_run_one`）接入 `BoidsArbitrator`，对声明了
独占资源的 assignment 做 claim → arbitrate → 串行 → release。**

### 1. 资源声明（opt-in，向后兼容）

`ArmAssignment` 新增 `exclusive_resources: list[str] = []`。**默认空 = 不 claim
= 与现状逐字节一致**，所有现有流程零行为变更。只有显式声明资源的 assignment
进入仲裁。

resource_uri 约定（与 `ResourceClaim.is_readonly` 对齐）：

| 形式 | 含义 |
|---|---|
| `device:desktop` / `device:mobile:<id>` / `browser:<ctx>` | 物理/会话独占 |
| `file:<abs-path>` | 文件写锁 |
| `api:<provider>` | 限流 key |
| `<uri>:read` 或 `readonly:<uri>` | 只读 → 多 Arm 共存（`coexist`） |

### 2. 边界逻辑（`_run_one`）

```
claimed = claim(arm_id, assignment.exclusive_resources)   # 仅当 boids 存在且非空
try:
    arm.handle(...)
finally:
    release(arm_id, claimed)
```

- **claim**：对每个 uri `arbitrate()`，`win`/`coexist` → 持有；`lose` → 轮询
  等待（peer 释放后重试），有界超时。
- **超时策略（v1）**：到达超时仍 `lose` → **带 `alert.contention` 告警继续执行**
  （不死锁线程池、不引入新失败态）。即在病态争用下降级为"记一条告警"而非
  阻塞/失败。严格独占（超时即失败）留作可调策略。
- **TTL**：claim 用宽裕 ttl（默认 10min）覆盖 handle 时长；`finally` 在正常/异常
  退出都即时 release，TTL 只兜底硬崩溃。

### 3. 消费侧

`arbitrate` 的 win 已广播 `sucker.grabbed`；Worker 的 `_on_step` 可消费这些
（"peer 已持有 X"）做进一步避让——本 ADR 只落地**claim 侧串行**，消费侧避让
留作 Phase 2。

## Rollout

- **Phase 1（本 ADR，机制）**：`exclusive_resources` 字段 + `_run_one` 接线 +
  claim/release helper + 测试（claim 等待释放、release、空资源不 claim）。**默认
  无人声明 → 零影响**。
- **Phase 2（填充）· 部分 ✅**：`Skill.exclusive_resource` 自声明字段 + splitter
  经 registry 解析填 `assignment.exclusive_resources`（`SwarmRuntime(skill_resources=…)`
  ← `run_swarm(registry=…)` ← team-stream 注入)。已填 **desktop 控制类**
  （`mouse_click/mouse_move/keyboard_type/keyboard_press` → `device:desktop`,单块
  物理屏；读类 `screen_*` 不标,避免过度串行)。**核实后 browser_get/extract/navigate
  各自 `launch()` 独立浏览器、不共享 → 不标**（盲贴会过度串行)。**剩余**：mobile
  设备 / 文件写的逐 skill 资源审计 + `_on_step` 消费侧避让。
- **Phase 3（调度）**：Boids Alignment（同 affinity 分片同 tick 启动）/ Cohesion
  （idle 腕靠拢最忙簇）——真正的"涌现秩序"，依赖本争用底座。

## Consequences

- **正面**：mesh 从"休眠脚手架"变成**真实运行的串行仲裁**（机制层）；`BoidsArbitrator`
  从未被调用 → 有了生产调用方；为 Phase 2/3 铺好底座。
- **负面 + 缓解**：超时降级牺牲了病态争用下的严格独占 → 以 `alert.contention`
  可观测 + 留严格模式可调；TTL 兜底硬崩溃泄漏。
- **风险**：`_run_one` 是热路径 → claim 仅在**声明了资源**时发生，空声明零开销。

## Alternatives considered

- **lose 即失败**（严格独占）：保证不变量但会让正当工作在争用下失败；v1 选降级。
- **lose 即延迟到后续 phase**：改 swarm layer 语义、侵入大；不选。
- **去中心化 gossip / Raft 锁**：远期；当前进程内单 arbiter 足够。
- **不做**：mesh 永久休眠、护城河停留在文档声明——本 ADR 拒绝。

## References

- `runtime/safety/chromatophores/boids.py` — `BoidsArbitrator` / `ResourceClaim`
- `runtime/execution/swarm/runtime.py` — `_run_one` 派发边界
- [vision/biomimetic-architecture.md](../vision/biomimetic-architecture.md) §Chromatophores（⚠️ mesh 休眠说明）
- protocols/swarm.md

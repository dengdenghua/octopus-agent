# Octopus-Agent · 章鱼仿生分布式 Agent 架构

> **本文档已拆分为三层，请按需阅读：**
>
> | 层 | 文档 | 内容 |
> |---|---|---|
> | **工程参考** | [guide/architecture.md](guide/architecture.md) | 只写已实装，纯工程语言，按 runtime/ 实际模块组织 |
> | **工程参考** | [guide/modules.md](guide/modules.md) | 6 大工程模块详解，含文件级索引 |
> | **仿生愿景** | [vision/biomimetic-architecture.md](vision/biomimetic-architecture.md) | 完整仿生架构设计，每段标注实装状态 |
> | **映射表** | [vision/biomimetic-map.md](vision/biomimetic-map.md) | 20 个器官 → 代码路径的一页总表 |
> | **实装状态** | [implementation-status.md](implementation-status.md) | 每个机制的代码证据 |
>
> 本文档保留作为历史参考，不再扩展新内容，仅维护实装状态标签（✅/⚠️/❌）以阻止误读。新内容请写入上述分层文档。

---

> 章鱼是地球上唯一"脑分布在身体里"的高级智能动物。
> 1 中枢 + 8 神经节 + 3 颗心脏 + 2000+ 吸盘 —— 天然的分布式 agent 蓝图。

> 📜 本架构是 [principles.md](principles.md) 中六大仿生设计原则的**一种实现**。
> 原则是 API，章鱼器官是 UI —— 换一套命名（城市交通/工厂流水）同样能搭。

> ⚠️ **本文混合了「已实装」与「设计愿景」两种内容**（例如 Hearts 三心 HA、
> NATS 总线、腕间 gossip 目前并未在默认路径运行）。每个机制的真实状态见
> [implementation-status.md](implementation-status.md) —— 读到任何机制时
> 先查那张表，不要默认本文描述的都已存在。

## 设计哲学

章鱼有约 5 亿神经元，**2/3 不在大脑而在 8 条腕里**。每条腕能独立尝味、抓握、解决局部问题，不必事事请示中枢。断掉的腕仍能执行指令数小时。
我们照抄这套生理学：**中枢只做规划与仲裁，执行智能下沉到腕**。

三条不变量：

1. **去中心智能** — Cerebrum 不直接调工具，吸盘动作由 Ganglion 决定（未实装）
2. **器官分工明确** — 每个模块对应一个生物器官，职责单一且可替换
3. **自适应进化** — 能再生（Regeneration），能拟态（Camouflage），能喷墨逃命（Ink）

---

## ⚠️ 数字是诗意，不是契约

> **biology gives us the PATTERN, not the NUMBER.**

本文档反复出现 "3 心 / 9 脑 / 8 腕 / 2000 吸盘" —— 这些数字**只是助记 + 营销口径**，**绝不允许作为工程约束写入代码**。

| 生物数字 | 真实工程变量 | 默认值 | 可配置 |
|---|---|---|---|
| 3 颗心 | `hearts.count`（多数派仲裁 Raft quorum）| 3 | ✅ 高可靠场景可 5 / 7 |
| 9 个脑 | 派生值 = `1 + ganglia.count` | 9 | ✅ 随腕数变 |
| 8 条腕（类型）| `arms.types[]`（任务专长聚类结果）| 8 类 | ✅ 4–16 都合理 |
| 8 条腕（实例）| `arms.replicas_per_type`（横向扩展）| 1 | ✅ 高并发 >1 |
| 2000 吸盘 | 无硬限制 | 无 | ✅ 随 skill 库增长 |

### 三条硬性红线

1. **禁止 magic number** —— 代码里不得出现 `for i in range(8)` 这种字面量；必须从 config 读
2. **禁止生物纯洁主义** —— 如果任务类型聚类出 6 种或 12 种专长腕，**尊重数据**，不要硬塞成 8
3. **禁止数字约束架构** —— 任何"因为章鱼就是这样所以系统必须这样"的论证都不成立

### 正确的思维顺序

```
观察任务分布 → 聚类得专长数 K → 命名参考章鱼器官（可选）
              ×
                          （不是）
                            ×
章鱼有 8 腕 → 系统就有 8 种 agent → 把任务硬塞进 8 类
```

### 保留"诗意"的价值

软化不等于抛弃。**命名、文化、助记、对外传播**仍用章鱼口径 —— 它比"multi-agent orchestrator with HA scheduler" 好记 100 倍。
只是**工程契约层**一律走数字可配置 + 原则不变量。

> **📐 进阶 · 分层**：20 个器官不是平级的 —— 8 个一等公民 + 8 个辅助器官 + 若干生物名基础设施。
> 完整清单见 [`architecture/organ-tiering.md`](./architecture/organ-tiering.md)。
> **新功能该不该开新器官？** 先过三问（发布节奏 / 依赖边界 / 失败模式），三个都 yes 才新开。

---

## 器官 → 模块映射总表

> 状态列含义：✅ 已接线 · ⚠️ 部分实装/可选后端 · ❌ 未实装。依据见 [implementation-status.md](implementation-status.md) 与 [vision/biomimetic-map.md](vision/biomimetic-map.md)。

| 章鱼器官 | 生物特性 | 模块 | 工程职责 | 状态 |
|---|---|---|---|---|
| Cerebrum 中枢脑 | 1/3 神经元，做总规划（慢路径）| `cerebrum/` | 任务分解、路由、裁决 | ✅ |
| **Spinal Cord 脊髓** | **不过大脑的反射（快路径）**| **`spinal_cord/`** | **规则/cache/小模型，旁路 LLM** | ✅ |
| Ganglia 神经节 × 8 | 每条腕自带小脑 | `ganglia/` | 分布式腕控制器 | ❌ |
| Arms 腕足 × 8 | 半自主，可独立行动 | `arms/` | Worker agent 实例 | ⚠️ |
| Tentacle 触腕 | 伸向端侧设备的执行触点 | `tentacle/` | 移动 / 跨设备连接、锁定、调用与能力上报 | ✅ |
| Suckers 吸盘 | 有味觉与触觉的执行点 | `suckers/` | 技能库（SKILL.md）| ✅ |
| Beak 角质喙 | 唯一硬质工具，咬碎猎物 | `beak/` | 工具执行引擎 | ✅ |
| Mantle 外套膜 | 包裹内脏的保护层 | `mantle/` | 沙箱/安全边界 | ⚠️ |
| Siphon 漏斗 | 喷射推进、呼吸、排废 | `siphon/` | I/O 流水线、SSE、压缩 | ✅ |
| Eyes 眼睛 | W 形瞳孔，广角感知 | `eyes/` | 输入解析、多模态、模型适配 | ✅ |
| Skin 皮肤 | 光感受器，只感不控 | `skin/` | **纯感知层**：只上报信号，禁止决策/路由/调用 | ❌ |
| Nerves 神经 | 连接器官的通路 | `nerves/` | 消息总线、工作流图 | ⚠️ |
| Chromatophores 色素细胞 | 信号 + 肌肉双功能 | `chromatophores/` | **双身份**：状态广播（pub/sub）+ 并行效应器（多 Sucker 同 tick 触发）+ Boids 三原则（避撞/对齐/聚合）| ⚠️ |
| Ink Sac 墨囊 | 紧急喷墨逃命（炎症反应）| `ink/` | 熔断、预算上限、紧急停 | ✅ |
| **Immunity 免疫** | **B/T 细胞、抗体记忆** | **`immunity/`** | **身份识别 + 攻击记忆 + 适应性风控** | ⚠️ |
| Hearts 心脏 × 3 | 体循环 ×1 + 鳃循环 ×2，**物理隔离** | `hearts/` | **双循环隔离**：内部业务 / 外部 I/O 分走两套心跳，外部挂不死主业务 | ⚠️ |
| Genome 基因组 | DNA + 遗传信息 | `genome/` | **双重内容**：① `dna/` 可编辑遗传密码（策略/拓扑/注册表的可版本/可变异/可回滚层）② 长时记忆（checkpoint/journal/memory/knowledge）| ⚠️ |
| Hemolymph 血淋巴 | 铜基蓝血，循环供养 | `hemolymph/` | 每轮循环的上下文流 | ✅ |
| Camouflage 拟态 | 瞬间切换形态伪装 | `camouflage/` | 策略切换、A/B 实验 | ✅ |
| Regeneration 再生 | 腕断可重长 | `regeneration/` | 反思、自进化、技能锻造 | ✅ |

---

## 分布式编排拓扑

> ⚠️ **愿景图** — **未实装**：独立 Ganglia×8 节层、「三心互备调度循环」、完全不经中枢的去中心化腕间 gossip。**已实装（易被误读为未做）**：Hearts HA 机制（fencing 租约 + etcd/redis 选举 + 每通道熔断，可选后端，单机回退 AlwaysLeader）、SwarmRuntime 并行编排、且 **swarm 路径下 Arm 共享同一 SignalBus 互传进度（非"完全隔离"）**。准确状态以 [implementation-status.md](implementation-status.md#分布式与编排) 为准。

```
                            ┌──────────────┐
                            │   Cerebrum   │   中枢脑 — 规划 / 仲裁
                            └──────┬───────┘
                                   │
                         Nerves 神经消息总线
                                   │
         ┌──────────┬──────────┬───┴───┬──────────┬──────────┐
         │          │          │       │          │          │
      Ganglion₁  Ganglion₂  Ganglion₃  …       Ganglion₇  Ganglion₈
         │          │          │                  │          │
        Arm₁       Arm₂       Arm₃     ……        Arm₇       Arm₈      (腕足 = 半自主 agent)
         │          │          │                  │          │
     [Suckers]  [Suckers]  [Suckers]          [Suckers]  [Suckers]     (每条腕的技能吸盘簇)

         └──── Chromatophores 色素广播（腕间 gossip）────┘
                                   │
                    Hearts × 3 (HA 调度 / 心跳节律)
                                   │
              Ink Sac（熔断） ·  Mantle（沙箱包围）
```

### 三条核心通路

1. **纵向命令链**：Cerebrum → Ganglion → Arm → Sucker（规划下行）— ✅ 已接线（Cerebrum → Arm → Sucker，无独立 Ganglia 层）
2. **横向腕间**：Arm ↔ Chromatophores ↔ Arm（腕足可直接互通，不占用中枢）— ⚠️ **部分实装**：swarm 路径下 Arm 共享同一 SignalBus、注册 peer-message handler 可互传进度（`_drive_swarm_mesh` → `build_arm_pool_from_registry(signal_bus=sb)`、`arms/base.py`）；未做的是「完全不经中枢的去中心化 gossip」。详见 [implementation-status.md](implementation-status.md#分布式与编排)
3. **感知上行**：Eyes/Skin → Hemolymph → Cerebrum（环境信号汇聚规划）— ⚠️ 部分实装（Eyes 已接线，Skin 未实装）

### 为什么比 Lead+Sub-agents 更进一步

> ❌ **未实装** — 以下描述是设计方向，当前实装仍为中心化树状编排。网状 Arm 互通是本项目的核心差异化目标，详见 [implementation-status.md](implementation-status.md#分布式与编排)。

Octopus 项目的 Lead+Sub 仍是中心化 —— Lead 必须驱动每一次 Sub 行动。
本架构的 Arm 有自己的 Ganglion，能在 Cerebrum 沉默时继续完成已下发的长任务；
Chromatophores 让 Arm₃ 可以直接告诉 Arm₇ "我已经抓住了"，无需往中枢绕。
**这是从"树状编排"升级到"网状编排"**。

---

## 六大可持续进化模块落点

| 进化层 | 章鱼对应 | 实现模块 | 关键输出 |
|---|---|---|---|
| ① 长任务引擎 | Cerebrum + Ganglia（未实装）+ Genome/Checkpoint | `cerebrum/` + `ganglia/`（未实装）+ `genome/checkpoint/` | 断点续跑、多会话恢复 |
| ② 工作流 | Nerves 神经通路 | `nerves/graph/` | DAG 执行器、节点/边类型 |
| ③ 技能 | Suckers 吸盘 | `suckers/` | SKILL.md + progressive disclosure |
| ④ 上下文/记忆 | Genome + Hemolymph | `genome/` + `hemolymph/` | 长时记忆 + 每轮循环流 |
| ⑤ 反思/自进化 | Regeneration 再生 | `regeneration/` | Trajectory→Eval→Skill Forge |
| ⑥ 成本治理 | Ink Sac + Hearts | `ink/` + `hearts/` | 预算熔断 + 节律节流 |

### 一条具体的进化回路（每晚跑一次）

> ⚠️ **部分实装** — Regeneration 反思闭环已接线，但回路末尾"Hearts 根据成本曲线调节 Ganglion 的调用节律"依赖未实装的 Hearts HA + Ganglia。详见 [implementation-status.md](implementation-status.md#自进化)。

```
Arms 一天的 trajectory
    → Hemolymph 汇入 Genome/Journal
    → Regeneration/Evaluator 用 Batch API 打分
    → Regeneration/Skill Forge 把高频成功路径结晶成新 Sucker
    → 新 Sucker 挂到对应 Arm 下，次日即可复用
    → Hearts 根据成本曲线调节 Ganglion 的调用节律  ❌ 未实装
```

---

## 六大模块 × 章鱼器官双向对照

```
 长任务引擎 ┐                         ┌ Cerebrum   ───── 规划
           ├─ 中枢 + 节 + 基因组 ────│ Ganglia（未实装）───── 驱动
 工作流    ┘                         │ Genome     ───── 续跑

 工作流 ──── 神经通路 ──────────────── Nerves
 技能 ────── 吸盘 ─────────────────── Suckers
 上下文 ──── 基因组 + 血淋巴 ───────── Genome + Hemolymph
 反思 ────── 再生 ─────────────────── Regeneration
 成本治理 ── 墨囊 + 心脏 ───────────── Ink + Hearts
```

---

## 关键模块细节

### Cerebrum 中枢脑

> ✅ **已接线** — ReAct loop + Planner 在默认路径运行。依据 [vision/biomimetic-map.md](vision/biomimetic-map.md)。

- **唯一职责**：把用户目标分解成 Arm 可独立执行的 `ArmTask`
- **不做什么**：不直接调工具、不读具体文件内容
- **输出**：`TaskGraph` (nerves/graph 格式) + 路由策略
- **LLM 分层**：planner 用最强模型，其余层用更便宜的

### Ganglia 神经节

> ❌ **未实装** — 无独立模块存在。当前 Cerebrum 直接驱动 Arm，无腕本地自治层。依据 [vision/biomimetic-map.md](vision/biomimetic-map.md)。

- **每条 Arm 都有一个**，独立进程/线程
- 负责**把 ArmTask 翻译成 Sucker 调用序列**
- 带本地 **Checkpointer**（genome 共享）和本地预算上限（ink 共享）
- **断联自治**：Cerebrum 不可用时，Ganglion 照常跑已接手任务

### Arms 腕足

> ⚠️ **部分实装** — Worker pool 在，但无自治逻辑；腕间 gossip 未建，Arm 之间完全隔离。依据 [implementation-status.md](implementation-status.md#分布式与编排)。

- 一条 Arm = 一个具备某类专长的 agent（比如：代码腕、数据腕、搜索腕、浏览腕、文件腕、通讯腕、部署腕、观测腕 —— 正好 8 条）
- Arm 之间平权，没有 master/slave
- 接入 **Chromatophores** 广播"我正在做什么 / 我抓住了什么" — ❌ 未接线（Worker 不持有 signal_bus 引用）

### Suckers 吸盘

> ✅ **已接线** — SKILL.md + progressive disclosure + 40+ 预装技能。依据 [vision/biomimetic-map.md](vision/biomimetic-map.md)。

- 技能原子单位，**SKILL.md frontmatter**（fork 自 octopus）
- 默认只注入名字 + 一句话（progressive disclosure）
- 每条 Arm 只挂与其专长匹配的 Sucker 子集，上下文不爆
- MCP 工具也当作一类 Sucker（`suckers/mcp/`）

### Nerves 神经

> ⚠️ **已接线（仅进程内）** — TypedEventBus 已接线；NATS/Redis 分布式总线已删除。依据 [implementation-status.md](implementation-status.md#分布式与编排)。

- **graph/**：DAG 执行器，6 节点 + 4 边（fork octopus）
- **bus/**：进程内 TypedEventBus（NATS / Redis Streams 总线已删除）
- **hooks/**：pre/post tool use 钩子（fork octopus）
- 是所有器官之间唯一的通信基础设施

### Chromatophores 色素细胞

> ⚠️ **部分实装** — pub/sub 广播 + Boids Separation 已接线；Alignment/Cohesion 未实装；Worker 未接入 signal_bus。依据 [implementation-status.md](implementation-status.md#分布式与编排)。

- **轻量级 pub/sub**，只传**状态变更**而非数据本身
- 事件类型：`arm.busy` / `arm.idle` / `sucker.grabbed` / `alert.budget` / `alert.loop`
- Arms 订阅感兴趣的话题，避免事事回汇报 — ❌ 当前无 Arm 订阅
- 进程内实现（非 Redis pub/sub 或 NATS subject）

### Ink Sac 墨囊 ★（成本治理核心）

> ✅ **已接线** — 三态 CircuitBreaker + per_task_budget。依据 [implementation-status.md](implementation-status.md#安全治理)。

- `per_task_budget`：每个 task 创建时必带 `max_tokens` + `max_cost_usd`
- `circuit_breaker`：连续 N 次失败 / M 步零信息增益 → 立即吐墨停
- `skill_cost_profile`：每个 Sucker 的成本画像，异常涨价告警 — ⚠️ 未实装（仅 AdaptiveImmunity 内存基线）
- 被触发时：冻结当前腕、广播 Chromatophore `alert.budget`、回到 Cerebrum 等人工确认

### Hearts 心脏 × 3

> ⚠️ **可选后端** — 仅分布式锁，无"三心互备调度循环"。依据 [implementation-status.md](implementation-status.md#分布式与编排)。

- 章鱼有 3 颗心脏：1 颗系统心 + 2 颗鳃心
- **系统心**：主调度循环（每 tick 驱动 Cerebrum）— ❌ 未实装
- **鳃心 × 2**：分管 4 条腕的节律，HA 互备 — ❌ 未实装
- 当前仅用于 Redis 分布式锁（多副本 leader 选举），无"任一心脏停跳另两颗接管"的 HA 互备
- Hearts 也是**成本节律器**：预算紧张时降频，空闲时加速反思流水线 — ❌ 未实装

### Genome 基因组（记忆层）

> ⚠️ **部分实装** — checkpoint/journal/memory/knowledge 已接线；`dna/` 可编辑遗传密码的进化闭环未建。依据 [vision/biomimetic-map.md](vision/biomimetic-map.md)。

- `checkpoint/`：SQLite 检查点（fork）
- `journal/`：事件日志（fork）
- `memory/`：长时记忆，Teach-Repeat 的录像带存在这里
- `knowledge/`：Wiki + 知识图谱 + FTS5（fork octopus 的 knowledge 模块）

### Hemolymph 血淋巴（上下文流）

> ✅ **已接线** — composer 已实装。依据 [vision/biomimetic-map.md](vision/biomimetic-map.md)。

- **铜基蓝血 → 携带"氧"到各器官**，这里的"氧"就是每轮的 context 预算
- 每次调用前：从 Genome 拉相关记忆、从 Skin 拉环境信号、从 Suckers 拉技能摘要
- 按预算比例打包成一个 `ContextPacket` 送进 Eyes
- **硬顶机制**：超限先压缩再喷射

### Regeneration 再生（自进化核心）

> ✅ **已接线** — 反思闭环 + Skill Forge + Camouflage A/B。依据 [implementation-status.md](implementation-status.md#自进化)。

- `trajectory/` — 收集 Arm 执行轨迹
- `evaluator/` — 离线 Batch API 打分（对照你之前的成本优化思路）
- `skill_forge/` — 把高频成功路径锻造成新 Sucker
- `reflection/` — 失败路径 → 规避规则 → 注入到 Cerebrum 的 planner prompt
- **再生不是实时的** —— 大部分反思夜间批跑，便宜

### Camouflage 拟态

> ✅ **已接线** — 提示词 A/B 与变体晋升。依据 [implementation-status.md](implementation-status.md#自进化)。

- 策略切换中枢：同一任务可跑多种 Cerebrum prompt 变体 / 多种模型路由策略
- 灰度 + A/B：按成功率 × 成本收敛最优策略
- 色彩变化 = 参数变化

### Mantle 外套膜（沙箱）

> ⚠️ **部分实装** — local/docker 已接线；ssh/k8s 后端未实装。依据代码核实（`runtime/safety/sandboxing/` 仅含 `sandbox.py` + `container_sandbox.py`）。

- 两种 provider 已实装：`local/` `docker/`（`ssh/` `k8s/` 待实装，非 fork 自 octopus 的四种）
- 每条 Arm 默认进入自己的 Mantle，互不污染
- Beak 的每一次"咬合"（工具执行）都在 Mantle 内发生

### Eyes 与 Skin

> ⚠️ **混合状态** — Eyes ✅ 已接线；Skin ❌ 未实装（无独立模块）。依据 [vision/biomimetic-map.md](vision/biomimetic-map.md)。

- **Eyes** = 显式感知：用户输入、多模态、LLM 响应解析；`models/` fork 自 octopus，10+ Provider — ✅
- **Skin** = 隐式感知：系统指标、环境变量、文件变化、外部事件 webhook — ❌ 未实装
- 二者的信号都汇入 Hemolymph 参与下一轮规划

### Siphon 漏斗

> ✅ **已接线** — JSON-RPC 2.0 over WebSocket + OpenAI-Compat Gateway。依据 [vision/biomimetic-map.md](vision/biomimetic-map.md)。

- 对外流式喷射：SSE / WebSocket / HTTP（当前主通道为 WebSocket，SSE 已退役）
- 内建 **OpenAI-Compat Gateway**（fork）—— 任何 OpenAI SDK 可把本系统当后端
- 压缩与背压控制（像漏斗的肌肉环）

---

## 实时传输层：JSON-RPC 2.0 over WebSocket

**入口：** `/api/realtime`（WebSocket）。所有 IDE / 浏览器 / 桌面客户端与 runtime 的实时通信都通过这一条双向通道。SSE + POST 旧模型已退役。

### 为什么不是 SSE

SSE 单向。`commandExecution` / `fileChange` / `mcpToolCall` 的工具批准需要 **server 向 client 发问、等 client 回应**。过去 `threading.Event + 全局 dict` 的做法在多 worker 部署下死锁,且无法单元测试。JSON-RPC 2.0 的 request/response 配对是内建的,批准在同一条 socket 上 round-trip,`ApprovalManager` 实例绑在连接上,断开自动 cancel 所有 pending future。

### 协议

三种 envelope(见 `runtime/protocol/envelope.py`):
- **Notification**: `{jsonrpc:"2.0", method, params}` — 单向事件
- **Request**: `{jsonrpc:"2.0", id, method, params}` — 等配对 Response
- **Response**: `{jsonrpc:"2.0", id, result|error}`

Server 和 client 都可以发 Request。Server → client 的 Request 目前只有批准类(`item/commandExecution/requestApproval` / `item/tool/requestUserInput` / `mcpServer/elicitation/request`),client 必须在超时前回 Response。

### Item 模型

一个 `Turn` 是一个有序 `items[]`。每个可观察的 agent 输出 —— 用户消息、助手消息、推理、shell 命令、文件修改、MCP 工具调用、错误 —— 都是一个 Item(有稳定 `id`,discriminated-union by `type`)。生命周期:

```
item/started             { threadId, turnId, item: Item }
item/<kind>/delta        { threadId, turnId, itemId, delta }  (多次)
item/completed           { threadId, turnId, item: Item }
```

Client reducer 按 `itemId` 合并,乱序或重复不会破坏状态。对比之前扁平 SSE 事件,Item 抽象让 UI 层可以独立处理每种输出的生命周期,不再靠 `additional_kwargs.octopus.run_status` 这种外挂标记。

### 持久化

每个 thread 对应 `data/threads/<thread_id>.jsonl`,`EventLog` 以 append-only 方式记录 `thread_started` / `turn_started` / `item_started` / `item_delta` / `item_completed` / `turn_completed`。`thread/resume` RPC 从这个文件重建 turn 列表 —— 进程重启、client 重连、跨 worker 切换,状态都在磁盘上,无全局内存依赖。

### Runtime 接口

```python
class RealtimeRuntime(Protocol):
    async def start_turn(self, params, emitter) -> Turn: ...
    async def handle_request(self, method, params, emitter) -> Any: ...
```

- `EchoRuntime` — 零依赖参考实现,用于 headless / minimal demo / unit test。
- `CerebrumRuntime` — 接 `runtime.core.cerebrum.react_loop.stream_react_loop`,在工作线程跑 ReAct 循环,事件翻译成 `item/*`。通过 `GatewayApprovalProvider` 把 react_loop 的同步 `provider.request(...)` 接到 asyncio 的批准通道。

`app.py` 根据 `stack` 是否可用自动选:有 stack → `CerebrumRuntime`,否则 → `EchoRuntime`。

### 前端

`frontend/src/core/realtime/`:
- `envelope.ts` / `items.ts` — 协议类型 mirror
- `reducer.ts` — 纯函数,`reduce(state, event) → {next, changedTurnIds, changedItemIds}`
- `client.ts` — `RealtimeClient`(jittered 指数回退重连 / outbox / 批准 reply tracker)
- `use-realtime-thread.ts` — React hook,暴露 `state / startTurn / resolveApproval / resume`

产品路由 `/workspace/realtime/:threadId` 提供完整的 thread UI,这也是**新协议的单一真相源页面**。旧 `/workspace/chats/:threadId` 仍在,但只作为兼容入口渲染同一个 `ChatPage`；`/workspace/code*` 也只是重定向到 realtime。`/realtime` 保留为开发索引页,`/realtime/:threadId` 会跳回 workspace shell。

---

## 与 Octopus 项目的继承/差异

**继承（通过 forklist.md 直接 fork）**：MCP 客户端、四种沙箱、技能加载器、工作流图执行器、Checkpointer、Journal、模型适配、Hooks、OpenAI-compat gateway。

**重构**：Lead+Sub → 网状 Arm + Chromatophores；Teach-Repeat → 完整 Regeneration 流水线。

**全新**：Ink（预算/熔断）、Hearts（HA + 节律）、Camouflage（策略 A/B）、Ganglion（腕本地自治）（未实装）、Hemolymph（流式上下文）—— 这五个是 octopus 缺失的差异化层。

---

## 进化路线（摘要，详见 ROADMAP.md）

- **第 0 阶段**：Fork 骨架（2 周）—— MCP / 沙箱 / 图执行器 / 模型适配可用
- **第 1 阶段**：单 Cerebrum + 单 Arm 能跑通任务（1 月）
- **第 2 阶段**：多 Arm + Chromatophores + Ink（1.5 月）
- **第 3 阶段**：Regeneration 反思流水线上线（1 月）
- **第 4 阶段**：Hearts HA + Camouflage A/B（1 月）

共约 4–5 个月形成可演示的 MVP。

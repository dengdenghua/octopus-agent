# 器官分层 · 20 不是契约，**分层才是**

> 本文不是推翻 [naming.md](../naming.md) 和 [architecture.md](../architecture.md) ——
> 那两份文档里"数字是诗意不是契约"的原则已经写得很好。
>
> 本文做的是**下一步**：把 20 个器官再切三层，声明清楚**哪些是一等公民**、
> **哪些是辅助器官**、**哪些其实是基础设施只是恰好起了个生物名**。
>
> 目的：新同学上来能一眼看出核心在哪；新增功能知道该不该开新器官。

---

## 为什么需要分层

20 器官 flat 列表会产生两个问题：

1. **规模失衡隐形** —— `sensing/siphon` 10k 行跟 `safety/ink` 300 行在同一张表里并列，
   看不出核心 vs 外围
2. **新功能强塞** —— 每次加新东西都要想"挂到哪个器官"，
   而 gene-locks / RecipeForge 这种**跨器官治理**本来就不该是器官

分层后，上述两个问题变成：
1. 一等公民表 8 行，工程边界 = 叙事边界
2. 新功能先问**三个问题**（见下方），答不过就不开新器官

---

## 三层模型

### 一等公民 · Primary Organs （8 个）

> 领域核心 · 独立演化节奏 · 独立依赖边界 · 独立失败模式。
> 重构这些 = 重构项目。

| 器官 | 路径 | 工程名 | 规模 | 核心职责 |
| :--- | :--- | :----- | :--- | :------- |
| `cerebrum` | `runtime/core/cerebrum/` | `Planner` | ~2.6k LOC | 慢路径规划、LLM 调度 |
| `spinal_cord` | `runtime/core/spinal_cord/` | `ReflexRouter` | ~3.3k LOC | <50ms 快路径反射 |
| `ganglia` | `runtime/core/ganglia/` | `LocalRuntime` | ~0.3k LOC | TaskGraph DAG 执行 |
| `eyes` | `runtime/sensing/eyes/` | `Perception` / `ModelRouter` | ~1.7k LOC | 输入解析 + 模型路由 |
| `suckers` | `runtime/execution/suckers/` | `SkillRegistry` | ~5.8k LOC | 技能库（21 skill） |
| `beak` | `runtime/execution/beak/` | `ToolExecutor` | ~0.8k LOC | 工具参数化执行 |
| `genome` | `runtime/memory/genome/` | `Journal` / `Checkpointer` | ~1.4k LOC | 持久化 / 长时记忆 |
| `hemolymph` | `runtime/memory/hemolymph/` | `ContextComposer` | ~0.3k LOC | 每轮上下文装配 |

**特征**：这 8 个里任意一个被抽掉，项目不成立。

### 辅助器官 · Secondary Organs （8 个）

> 职责清晰、命名合理，但**调用面比一等公民窄**。
> 升级或替换它们不会改变项目的核心形态。

| 器官 | 路径 | 工程名 | 规模 | 当前评估 |
| :--- | :--- | :----- | :--- | :------- |
| `arms` | `runtime/execution/arms/` | `Worker` | ~0.8k LOC | worker 实例层 |
| `mantle` | `runtime/sensing/mantle/` | `Sandbox` | ~1.3k LOC | 执行沙箱 |
| `immunity` | `runtime/safety/immunity/` | `TrustEngine` | ~0.9k LOC | 身份 / 风控 |
| `hearts` | `runtime/core/hearts/` | `SystemicScheduler` | ~1.2k LOC | 双循环调度 |
| `camouflage` | `runtime/safety/camouflage/` | `StrategySelector` | ~1.8k LOC | 策略 A/B |
| `skin` | `runtime/sensing/skin/` | `AmbientSensor` | ~1.1k LOC | 被动环境感知 |
| `nerves` | `runtime/core/nerves/` | `MessageBus` / `GraphExecutor` | ~0.5k LOC | 消息总线 + hooks |
| `tentacle` | `runtime/tentacle/` | `TentaclePool` / `MobileDevice` | ~2.1k LOC | 移动 / 跨设备执行触点 |

**特征**：可以被同功能的实现替换；即使关闭某一个，系统在降级形态下仍能跑。

### 基础设施 · Infrastructure （非器官）

> **这些目录起了生物名只是叙事顺手**，代码本质是基础设施 / 横切关注点 / 治理层。
> **新功能优先塞到这里，而不是开新器官。**

| 目录 | 性质 | 说明 |
| :--- | :--- | :--- |
| `runtime/platform/` | 平台 | config / ui / models / i18n / session —— 没有生物对应物 |
| `runtime/adapters/` | 适配器 | channels / integrations / mcp_client / scheduler —— 外部集成 |
| `runtime/safety/gene_locks/` | 治理 | 基因锁（IMMUTABLE / LEVEL / TEMPORAL / QUORUM / PANIC / MONOTONIC） |
| `runtime/safety/regeneration/` | 治理 | 离线演化流水线（RecipeForge / 变体评估 / 自动提拔） |
| `runtime/safety/constitution/` | 治理 | 宪法 / 边界声明 |
| `runtime/safety/invariants/` | 治理 | 不变量检查器 |
| `runtime/safety/hooks/` | 治理 | 执行前后钩子 |
| `runtime/safety/chromatophores/` | 基础设施 | 实际是 pub/sub + Boids 仲裁，跟"色素细胞"关系弱 |
| `runtime/safety/ink/` | 基础设施 | 实际是 circuit breaker + 预算守卫 |
| `runtime/sensing/siphon/` | 基础设施 | **实际是 FastAPI 路由总线（10k 行）**，跟"漏斗"关系弱 |

**特征**：
- 没有独立的领域概念
- 跨所有器官使用或服务所有器官
- 替换它们不动核心叙事

---

## 新器官准入 · 三问

想新增器官？先回答：

1. **它有独立的发布节奏吗？** 不同贡献者、不同版本演进速度？
2. **它有独立的依赖边界吗？** import 箭头进出清晰，没有循环？
3. **它有独立的失败模式吗？** 可以单独熔断 / 降级 / 重启？

**三个都 yes** → 可以开新器官（走一等公民或辅助的命名规范）
**有一个 no** → 放到现有器官的子模块，或放 `platform/` / `adapters/` / `safety/`

---

## 现存不对齐清单 · Watch List

> 这些是**命名跟实际内容对不齐**的已知问题，**本轮不动**（避免大重构），
> 作为未来迭代的候选。每条注明"什么信号触发动工"。

### WL-1 · `safety/chromatophores` 可能需要并入 `core/nerves`

- **现状**：431 LOC，2 处外部 import，内容是 `SignalBus`（pub/sub）+ `boids.py`（避撞/对齐/聚合）
- **问题**：`core/nerves` 里的 `MessageBus` 职责高度重合；"色素细胞"生物叙事挂不住 pub/sub 代码
- **触发条件**：当 `nerves.MessageBus` 下次大改、或 `chromatophores` 6 个月内无新增功能时合并
- **合并方案**：`runtime/core/nerves/signal_bus.py` + `runtime/core/nerves/boids.py`

### WL-2 · `safety/ink` 可能需要降级为 `safety/circuit_breaker.py`

- **现状**：294 LOC，2 处外部 import，内容是 `CircuitBreaker` + `BreakerModelRouter`
- **问题**：一个文件夹只放熔断器，器官粒度太细
- **触发条件**：如果不再有"预算硬顶"之外的新功能加入，就拍扁成 `safety/circuit_breaker/`（普通子模块命名）
- **合并方案**：保留类名不变，只改文件夹路径；更新 `hearts.py` 和 `tour.py` 的 import

### WL-3 · `sensing/siphon` 需要迁到 `platform/api/`（大动作）

- **现状**：**10,118 LOC**，17 个 `*_router.py`（openai_gateway / channels / fs / mcp / observability / config / …）
- **问题**：全是 FastAPI 路由，属于平台层而非感知层；"漏斗喷水"的生物隐喻跟 HTTP 路由完全错位
- **触发条件**：下次有人要动路由聚合 / OpenAI 兼容层重构时，顺手挪到 `runtime/platform/api/`
- **合并方案**：
  ```
  runtime/platform/api/                ← 新建
      openai_gateway.py                ← 从 siphon/
      routers/
          channels.py
          fs.py
          ... (17 个)
      streaming_journal.py             ← 从 siphon/
  ```
  保留 `runtime/sensing/siphon/__init__.py` 作 1-轮期的 shim（re-export + deprecation warning）

### WL-4 · `memory/hemolymph` 是否合并进 `cerebrum`？

- **现状**：335 LOC，4 处外部 import，只有一个 `ContextComposer`
- **问题**：ContextComposer 永远跟 Planner 一起调用，没见过单独用
- **触发条件**：如果未来一年 Blackboard（共享状态面）没真的落地，就并入 `cerebrum/context_composer.py`
- **反方意见**：目前的分离让 unit test 边界很干净，不强推

---

## 跟现有文档的关系

| 文档 | 角色 | 本文件的关系 |
| :--- | :--- | :----------- |
| [`principles.md`](../principles.md) | 六大原则 | 本文不改原则，只定义落地分层 |
| [`architecture.md`](../architecture.md) | 总架构 + 器官映射 | 本文是其**补充**（tiering 层）|
| [`naming.md`](../naming.md) | 双轨命名契约 | 本文不改命名，只给 20 个名字分**级**|
| [`architecture/organs/*.md`](./organs/) | 每器官详述 | 本文的"基础设施"类目建议**不再**给它们写 organ.md |

---

## 原则一句话

> **20 是叙事数字，不是架构契约。一等公民 8 个，辅助器官 8 个，其余回归基础设施。**
>
> 下次有人问"为什么 siphon 这么大而 hemolymph 这么小"——
> 答案是"它们根本不在一个层"。

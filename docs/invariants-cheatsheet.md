# INVARIANTS 速查卡 · 开发者必背的 30 条

> 完整 139 条见 [invariants.md](invariants.md)。此页是**每天写 PR 前扫一眼**的口袋版。
>
> **P0 = 必查**（lint 自动拦，违反无法合）· **P1 = 强建议**（review 关注点）· **P2 = 已知约束**（架构边界）

---

## 🔴 P0 · LINT 静态强制（10 条 · 违反=CI 红）

| ID | 名字 | 一句话 |
|---|---|---|
| `LINT-01` | NO_BYPASS_IMMUNITY | 调 `ToolExecutor.execute` 前必须过 `immunity.check` |
| `LINT-02` | NO_MAGIC_ORGAN_COUNT | 代码里别写 `range(8)` 凑章鱼 8 腕；全走 config |
| `LINT-03` | BIO_NAME_IN_CODE | `class Cerebrum` ❌ / `class Planner` ✅（生物词只当 import 别名） |
| `LINT-04` | NO_RAW_LLM_CALL | `eyes/` 以外不 import `anthropic` / `openai` / `google.genai` |
| `LINT-05` | TASK_NEEDS_BUDGET | `Task(...)` 构造必须带 `max_tokens` + `max_cost_usd` |
| `LINT-06` | PERSONAL_NO_EGRESS | `@privacy(personal)` 标注的函数不得调 cloud bus |
| `LINT-07` | NO_GENESTUDIO_SHORTCUT | `registry.commit` 必经 schema/shadow/canary 三门 |
| `LINT-08` | MUTATION_SINGLE_FIELD | `mutate()` 每次改 1 个字段（runtime assert） |
| `LINT-09` | REGEX_REFLEX_NO_GENERATE | `reflex/` 里禁止 `llm.generate` |
| `LINT-10` | CRDT_NOT_LWW | Genome 字段用 CRDT 方法 · 不用 `dict.update`/`list.append` |

**本地跑**：`python -m tools.lint.invariant_check runtime/ tests/`

---

## 🟠 P1 · 协议核心不变量（20 条 · review 必 challenge）

### DIG · Digestion 流水线

| ID | 不变量 |
|---|---|
| `DIG-I1` | 阶段 In/Out 严格契约 · boundary 必校验 |
| `DIG-I3` | 反射短路不跳免疫 · `immunity.check` 是最后一道 |
| `DIG-I4` | 用户响应不被 STORE 阻塞（SYNTHESIZE 后可返回） |
| `DIG-I5` | 预算单向递减 · `ink.budget` 只减不增 |

### REF · Reflex 快路径

| ID | 不变量 |
|---|---|
| `REF-I1` | Reflex handler 是确定性 · 同 input → 同 output |
| `REF-I5` | Reflex 里禁止 LLM 调用 |

### IMM · Immunity 免疫

| ID | 不变量 |
|---|---|
| `IMM-I1` | `ImmuneVerdict.deny_reason` 必填（不 allowed 时） |
| `IMM-I2` | skill/path/url 三维独立判定 · 任一拒即拒 |

### GEN · Genome 基因组（持久化）

| ID | 不变量 |
|---|---|
| `GEN-I1` | 基因组写入必经 shadow-test + canary |
| `GEN-I4` | CRDT field only · 无 last-write-wins |
| `GEN-I7` | Journal append-only · 事件 frozen · 改等于删后补 |

### EVO · Evolution 演化

| ID | 不变量 |
|---|---|
| `EVO-I1` | 所有 LLM 生成走 Batch API · 夜间跑 · 降低 10× 成本 |
| `EVO-I3` | Skill 晋升前必过 golden test |
| `EVO-I5` | retire_variant 保 ≥1 · 池永不为空 |

### BDG · Budget 预算

| ID | 不变量 |
|---|---|
| `BDG-I2` | 每 Task 有硬预算顶 · 超 = 停 · 不续 |

### DIS · Distribution 分布

| ID | 不变量 |
|---|---|
| `DIS-I1` | personal tier 数据永不出端 |
| `DIS-I5` | cloud 只收聚合后的 dep/telemetry |

### SWM · Swarm 集群

| ID | 不变量 |
|---|---|
| `SWM-I2` | Arm 并发时共享状态走 signal_bus · 不直接读写彼此内存 |

### CC · Cross-cutting 跨域

| ID | 不变量 |
|---|---|
| `CC-I1` | Journal 事件必带 agent_id + conversation_id（ContextVar 注入） |
| `CC-I3` | Mantle 沙箱决定 · 不走 shell · argv 透传 |

---

## 🟡 P2 · 架构硬边界（常被问的 FAQ）

- **Cerebrum = Planner**；`LLMPlanner` + `StaticPlanner`；中间不夹第三个
- **Ganglia = GraphRuntime**；只编排 DAG · 不做决策 · 不和 LLM 说话
- **Arms = 触手**（细粒度 · 几个 skill）· **Agent = 人设**（wraps ArmPool · 有 soul）
- **Hearts** 同机 HA 靠 FileLockCoordinator；跨机接 Redis/Etcd Coordinator
- **Mantle** 四档：Local < Subprocess < Docker < SSH/K8s（按风险选）
- **Nerves** = TypedEventBus + hooks（单进程）· **不是** 跨机消息队列
- **Skin** = 环境感知（FS/git/process）· 发事件到 TypedEventBus
- **SpinalCord** = 快路径（reflex）· 80% 简单 intent 不走 LLM
- **Immunity** = skill/path/url 三层白名单 · **最后一道防线**
- **Ink** = CircuitBreaker 三态机 · 每 provider/skill 独立 breaker

---

## 🧭 违反后怎么办

1. **CI 红** · 本地跑 `python -m tools.lint.invariant_check runtime/ tests/` 排查
2. **review 挂** · 贴 invariants.md 原文链接 · 说明哪条被踩
3. **想改不变量本身** · 开 issue · 标 `design` label · 同步 PR 改 invariants.md
4. **误报** · tools/lint/invariant_check.py 改 · 带复现样本

---

> 这 30 条占 139 条的 22% · 但覆盖 90% 的日常 review · 记住这些能少踩 80% 坑。
> 完整矩阵见 [invariants.md](invariants.md) · lint 实现见 `tools/lint/invariant_check.py`。

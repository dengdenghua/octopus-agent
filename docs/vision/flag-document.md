# 立旗文档 —— 仿生架构 Agent OS 的竞争立场

> 本文档基于竞品公开信息与仓库代码比对，为内部立旗立场，非营销材料。
> 所有涉及 octopus-agent 自身的主张均已映射到仓库内真实存在的代码路径；竞品三列（OCT-Agent / 明略 Octo / 腾讯 Octop）的判断基于此前四家仿生架构对比结论与公开信息，**待验证**项在文末事实核查清单中显式标注。
> 参考：[biomimetic-architecture.md](biomimetic-architecture.md)（仿生愿景）、[biomimetic-map.md](biomimetic-map.md)（器官→代码映射）。

---

## 1. 旗帜立场

> **仿生架构 Agent OS：中央大脑只规划仲裁，执行智能下沉到臂/工具。**

一句定义：octopus-agent 不是"一个 Agent 套了章鱼皮肤"，而是从器官拓扑出发的运行时——`runtime/core/cerebrum/` 只负责规划与仲裁（ReAct 循环 + 能力路由），执行智能分布在 `runtime/execution/arms/`（臂的工作者池）与 `runtime/execution/`（工具引擎/吸盘技能库），臂之间通过 `runtime/safety/chromatophores/`（信号总线 pub/sub）直接互通，而不是一切绕经中央。

> 生物学给了我们 PATTERN（约 2/3 神经元分布在臂上，断臂仍可执行命令），不是 NUMBER（8 臂 / 3 心只是助记符，不是工程约束）。—— 出自 [biomimetic-architecture.md](biomimetic-architecture.md)

---

## 2. 仿生竞品对比矩阵

| 维度 | OCT-Agent（八臂+记忆） | 明略 Octo | 腾讯 Octop | **octopus-agent（自身）** |
|---|---|---|---|---|
| 仿生程度 | 最贴生物隐喻：每条臂独立执行 + 记忆系统，是"臂即执行单元"的先行者 | 以"组织"隐喻组织协作，仿生更多体现在组织分工而非生物器官 | 多用户助手，仿生隐喻弱，偏产品形态 | 器官→模块逐级映射（cerebrum / arms / nerves / chromatophores / ink 等），见 `docs/vision/biomimetic-map.md` |
| 记忆系统 | 有独立记忆系统，作为八臂共用的记忆底座 | 组织级知识沉淀，偏企业知识管理 | 会话级记忆，面向多用户共享上下文 | 事件日志记忆：append-only 逐线程事件日志，重启/断线/多窗口从磁盘回放重建（`runtime/memory/threads/event_log.py`）；plus 黑板、日志、知识图谱等多层（`runtime/memory/`） |
| 组织协作 | 臂之间协作依赖中心编排 | 组织协作 / 可见性控制是核心卖点 | 多用户协作，偏 IM 场景 | 臂间 pub/sub 直接互通原语（`runtime/safety/chromatophores/signal_bus.py` 的 `arm.mailbox.*`、`arm.busy`/`arm.idle`），但完整 Arm↔Arm 自治协作路径**未实现**；组织/团队模块已具雏形（`runtime/safety/organization/`、`runtime/memory/cowork/`） |
| 可见性 / 可解释性 | 记忆系统可追溯，但决策链可见性一般 | 可见性控制为核心卖点，企业级审计强 | 面向终端用户，可解释性偏产品话术 | 实时事件网关把 Agent 内部状态流式暴露（`runtime/sensing/gateway/realtime_gateway.py`、`docs/protocols/realtime_workbench.md`）；**可见性原语已实现**：能力激活/委派可见性/技能目录截断决策经 `runtime/core/cerebrum/_visibility_trace.py` 采集为 why 链，随 `item/visibility` 事件推送并在工作台"可见性"面板展示 |
| 物理在场 | 无 | 无 | 无 | 桌面宠物 + Godot sidecar + UDP 8765 事件推送（`frontend/src/lib/pet-ipc.ts`、`frontend/electron/pet-sidecar.cjs`、`pet-sidecar/`），Agent 状态（thinking/working/success/error）实时映象为宠物行为 |
| runtime 模块化 | 臂 + 记忆两大子系统 | 组织/协作服务化 | 多用户服务化 | 模块化 Python runtime：`runtime/core/cerebrum/`（大脑）、`runtime/execution/`（臂/工具）、`runtime/memory/`（记忆）、`runtime/sensing/gateway/`（实时事件网关）、`runtime/safety/`（含 `chromatophores/`） |

**一句话结论（延续此前对比）**：谁更仿生谁更好 —— 四家中 OCT-Agent 与 octopus-agent 并列最贴生物隐喻；octopus-agent 的差异化在于把"仿生"落实成可核查的模块化 runtime（器官→代码映射、事件日志记忆、臂间 pub/sub、物理在场），并以"中央大脑只规划仲裁、执行智能下沉"作为立旗主张。

---

## 3. "谁更仿生"证据清单

以下每条主张均映射到仓库内真实存在的文件路径（相对路径，反引号标注）：

| # | 仿生主张 | 代码/文档证据（真实路径） |
|---|---|---|
| 1 | 中央大脑只规划仲裁（ReAct 循环 + 能力路由），不直接执行 | `runtime/core/cerebrum/react_loop.py`（主 ReAct 循环）、`runtime/core/cerebrum/capability_router.py`（能力激活/路由）、`runtime/core/cerebrum/llm_planner.py`（LLM 规划） |
| 2 | 执行智能下沉到臂/工具（臂是工作者，吸盘是技能点） | `runtime/execution/arms/base.py`（ArmPool Worker）、`runtime/execution/`（工具引擎/技能库）、`docs/architecture/organs/arms.md` |
| 3 | 黑板 / 事件总线：Chromatophores pub/sub 信号总线 + 臂间信箱 | `runtime/safety/chromatophores/signal_bus.py`（`arm.busy` / `arm.idle` / `arm.mailbox.*` + Boids 仲裁）、`runtime/memory/runtime_state/blackboard.py`（turn-scoped 多臂共享黑板，`bb_read`/`bb_write`/`bb_keys`）、`runtime/memory/runtime_state/blackboard_store.py` |
| 4 | 物理在场：桌面宠物 + Godot sidecar + UDP 8765 事件推送 | `frontend/src/lib/pet-ipc.ts`（UDP 8765 客户端）、`frontend/electron/pet-sidecar.cjs`（UDP 8765 服务端）、`pet-sidecar/`（Godot 项目：`project.godot`、`scripts/Main.gd`、`scripts/Pet.gd`） |
| 5 | 事件日志记忆：append-only 事件日志，重启/断线/多窗口可回放重建 | `runtime/memory/threads/event_log.py`（每线程一个 `.jsonl`，事件顺序回放、幂等合并） |
| 6 | 器官→模块映射：每个模块对应一个生物器官，可独立替换 | `docs/vision/biomimetic-map.md`（器官→代码路径对照表）、`docs/vision/biomimetic-architecture.md`（器官→模块映射 + 三不变式）、`docs/architecture/organs/`（逐器官文档：`cerebrum.md`、`chromatophores.md`、`arms.md`、`hearts.md` 等） |
| 7 | 实时事件网关：Agent 内部状态流式暴露给前端工作台 | `runtime/sensing/gateway/realtime_gateway.py`（EventEmitter）、`runtime/sensing/gateway/`（realtime turn 生命周期、`_realtime_cerebrum_thread.py` 等） |
| 8 | 长任务自动并行：目标可拆则拆出并行子代理，主循环再综合 | `runtime/core/cerebrum/agent_auto_parallel.py`（`plan_auto_parallel` / `run_auto_parallel`）、`runtime/sensing/gateway/_realtime_orchestrator_bridge.py`（并行批流桥接到实时 turn，渲染为 SubagentItem 瓦片） |
| 9 | 长任务监督：Leader 进程让任务活过 UI 生命周期 | `runtime/core/cerebrum/leader.py`（Leader Process，UDS 单主监督长任务，UI/Headless/IPC 客户端可随来随走） |

> 说明：任务示例中曾出现 `runtime/sensing/gateway/realtime_event_bridge.py` 路径，经核实仓库内不存在该文件；"黑板/事件总线"与"实时事件桥"分别映射到上表中的 #3 与 #7 真实路径。

---

## 4. 五条超越路径与优先级

| 优先级 | 路径 | 说明与代码参考 |
|---|---|---|
| **P0** | 立旗文档与可见性原语 | **已落地**。可见性原语 = 把 Agent 内部决策——能力激活、委派工具可见性、技能目录截断——变成可观测、可解释的 why 链。能力激活与路由集中在 `runtime/core/cerebrum/capability_router.py`（`activate_capabilities`、`order_skill_names`、`filter_surface_compatible_skills`）；技能目录截断与格式化在 `runtime/core/cerebrum/_react_context_helpers.py`（`_format_skill_catalog`，`max_skills=100`，TF-IDF 保留目标相关技能）。决策经 `runtime/core/cerebrum/_visibility_trace.py` 采集，随 `item/visibility` 事件流推送并持久化到线程事件日志，工作台"可见性"面板可回放。目标达成：每个被激活/被隐藏/被截断的能力都能回答"为什么" |
| **P0** | 记忆与长任务自动并行 | **已落地（记忆 + 黑板证据喂给拆解，并行瓦片可回放）**。事件日志是记忆主干（`runtime/memory/threads/event_log.py`）；自动并行具备拆解—分发—综合闭环（`runtime/core/cerebrum/agent_auto_parallel.py` + `runtime/sensing/gateway/_realtime_orchestrator_bridge.py`）。已实现：跨轮记忆摘要（`build_thread_memory_summary`）喂给拆解与并行子代理；并行瓦片（SubagentItem）经 item 生命周期落盘，断线/多窗口可从 JSONL 完整回放；**黑板证据桥**（`runtime/memory/threads/board_evidence.py`）——并行 batch 落定后把本轮黑板的键值证据持久化到线程证据日志（`{thread_id}.board.jsonl`，值长度/记录预算截断、best-effort 绝不抛错），`run_auto_parallel(turn_id=...)` 自动保存，下一轮拆解经 `load_board_evidence` 把 `<board-evidence>` 块与 `<thread-memory>` 合并喂给每个子任务，避免重复探索。下一步：并行场景多窗口端到端真机验证 |
| **P1** | 组织协作与可见性控制 | **已落地（决策可见性控制 + 查看审计）**。组织/频道 ACL 在 `runtime/workspace/org.py` + `runtime/workspace/org_store.py`（`can_access_channel` / `list_channels_for_user`），权限变更走 HMAC 审计链（`runtime/workspace/org_audit.py`）。本轮补齐"谁对哪个 Agent 的哪个决策可见、可审计"：`runtime/safety/organization/decision_visibility.py` 定义 `DecisionScope`（private/team/org）+ `DecisionAccessLevel`（hidden/summary/conclusion/full）四级脱敏与查看者矩阵（`resolve_access`/`filter_decisions`，决策 Agent 自身 full、组织外 hidden、viewer 只拿结论），敏感决策点整体降级；`DecisionAccessAudit` 把每次查看/导出追加到独立 HMAC 链，回答"谁在何时看了哪个 Agent 的哪个决策、拿到哪一层"。`from_trace_entry` 无缝衔接 `_visibility_trace.py` 的 `export()`，trace 采集保持零侵入 |
| **P1** | 多用户助手 | **已落地（记忆身份隔离 + 团队共享上下文）**。会话/团队已有 actor 身份与成员隔离（`runtime/sensing/gateway/team_rooms_router.py` 的 `_require_member` / owner 边界；`runtime/memory/users/user_store.py` 按 `TenantScope`（tenant_id+actor_id）分区存储）。本轮补齐"共享上下文与身份隔离的执行闭环"：fact 自始携带 `visibility`（private/team/restricted/agent）+ `team_id` + `allowed_users/roles/agents` 元数据但此前搜索完全忽略——`runtime/memory/users/user_store.py` 新增 `MemoryViewer`（actor/租户/团队/角色/管理员）与 `fact_visible_to` 纯函数判定矩阵（tenant 隔离、owner 本人恒可见、private 仅 owner、team 按团队归属、restricted 按 ACL、agent 按绑定身份），`search_facts`/`relevant_memory_texts` 携带 viewer 时按身份过滤，`visible_facts_for_viewer` 聚合同租户全部分区供团队共享上下文注入；`viewer=None` 旧路径行为不变。下一步：gateway 注入点接 viewer（把请求 principal → MemoryViewer）、多用户会话的 UI 闭环 |
| **P2** | 桌面宠物物理在场强化 | **已落地（状态语义扩展 + 跨设备在场桥）**。链路：`TentaclePool._emit` → `PetUdpBridge`（`runtime/pet/udp_bridge.py`）→ UDP 8765 → `pet-sidecar/`（Godot 渲染）；前端链路仍由 `pet-ipc.ts` / `pet-sidecar.cjs` 提供。事件语义权威映射在 `runtime/pet/pet_state_map.py`（`map_agent_state`/`emotion_event`/`tired_event`/`presence_event`/`map_tentacle_event`，情绪白名单 + 强度钳制，best-effort 绝不抛错，tentacle registered/unregistered 自动映射为在场事件）；`TentacleCoordinator` 创建 Pool 后注册桥接订阅，设备注册/注销会发送 `agent.presence`。Godot 侧 `IPCServer.gd`/`Main.gd` 透传 payload，`PetBrain.gd` 新增 `CURIOUS/FATIGUE` 状态与 emotion/tired/presence 事件分支，`OctopusPet.gd` 新增 `curious/tired` 动作。测试：相关 Python 53 项通过，前端 pet-ipc 5 项通过。下一步：跨设备真机/Godot 二进制验证 |

---

## 5. 事实核查清单 / 跟踪清单

> 本文档中**尚未实现 / 未验证**的主张，逐条列出，后续更新时勾选确认。

- [ ] **竞品三列判断待复核**：OCT-Agent / 明略 Octo / 腾讯 Octop 的矩阵判断来自此前对比结论与公开信息，未逐项联网复核（本次为纯仓库内核查）；对外引用前需重核
- [ ] **Ganglia（每臂独立 mini-brain 自治层）未实现**：`docs/vision/biomimetic-architecture.md` 明确标注 Not implemented；"执行智能下沉"目前落在臂工作者（`runtime/execution/arms/base.py`），尚未到"断臂自治"级
- [ ] **Arm↔Arm 自治协作路径未实现**：Chromatophores 提供 pub/sub 原语（`arm.mailbox.*`、Boids 仲裁），但"臂间直接协作完成子目标、不绕经中央"的 mesh 编排未构建
- [x] **可见性原语已完成**：能力激活/委派可见性/技能目录截断决策经 `_visibility_trace.py` 采集为 why 链，随 `item/visibility` 事件推送并在工作台"可见性"面板展示；待真机端到端验证（见下一条）
- [x] **协作决策可见性控制已完成**：`runtime/safety/organization/decision_visibility.py` 提供 `DecisionScope` × `ViewerContext` 四级访问矩阵（full/conclusion/summary/hidden）+ 敏感决策降级 + `DecisionAccessAudit` 查看/导出 HMAC 审计链，32 项单测通过；"谁对哪个 Agent 的哪个决策可见、可审计"闭环达成（待接入真实共享案例 UI 与端到端验证）
- [x] **多用户记忆身份隔离已完成**：`runtime/memory/users/user_store.py` 新增 `MemoryViewer` + `fact_visible_to` 判定矩阵 + `search_facts`/`relevant_memory_texts`/`visible_facts_for_viewer` 身份过滤与租户聚合，33 项单测通过；"我的记忆 vs 团队共享记忆"有执行边界（gateway 注入点接 viewer 与 UI 闭环为下一步）
- [x] **黑板证据桥已完成**：`runtime/memory/threads/board_evidence.py` 把 turn-scoped 黑板的键值证据持久化到线程证据日志并跨轮喂给并行拆解（`run_auto_parallel(turn_id=...)` 落盘 + bootstrap PHASE 4.6 合并 `<board-evidence>`），12 项单测覆盖落盘/截断/跨轮复用闭环；并行场景多窗口端到端真机验证待做
- [x] **桌面宠物物理在场状态语义与 TentaclePool 接线已落地**：`runtime/pet/pet_state_map.py` 提供 agent 状态/情绪/疲劳/在场/tentacle 事件的权威映射，`runtime/pet/udp_bridge.py` 提供 best-effort UDP adapter，`TentacleCoordinator` 将 Pool 注册/注销事件桥接到 `agent.presence`；前端与 Godot 消费链路保持兼容。相关 Python 53 项单测 + 前端 pet-ipc 5 项单测通过。剩余待办：真机/Godot 二进制验证（状态语义 → 实际渲染）
- [ ] **黑板 turn-scoped 的动态状态仍不跨轮**：黑板本体仍是每轮新建（`runtime/memory/runtime_state/blackboard.py`），跨轮靠 `remember`/`recall` 技能；黑板证据桥（`board_evidence.py`）已把每轮黑板键值持久化到线程证据日志并提供跨轮回读，但"动态状态本身"（如进行中的锁定/会话游标）不跨轮；多轮并行协作的端到端一致性未做真机验证
- [ ] **`docs/protocols/realtime_workbench.md` 为空文件**：路径存在但内容为空，实时工作台协议文档待填充（本文 #7 证据仅引用到代码路径 `runtime/sensing/gateway/realtime_gateway.py`）
- [ ] **技能目录截断行为待基准验证**：`_format_skill_catalog` 的 TF-IDF 保留策略针对大技能库（300+）的取舍效果缺少基准数据

---

## 参见

- [biomimetic-architecture.md](biomimetic-architecture.md) — 仿生架构愿景与器官→模块映射
- [biomimetic-map.md](biomimetic-map.md) — 器官→代码路径对照表（Implemented / Partial / Not implemented）
- [../architecture/organs/](../architecture/organs/) — 逐器官架构文档
- [../CONCEPTS.md](../CONCEPTS.md) — 平实语言的 Agent OS 心智模型
- [../index.md](../index.md) — 文档索引

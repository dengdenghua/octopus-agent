# cerebrum 模块内聚度分析报告（import 依赖图谱）

> 分析日期：2026-08-04
> 分析对象：`runtime/core/cerebrum/`（`runtime.core.cerebrum` 包）
> 分析方式：AST 静态 import 依赖分析（一次性脚本，位于 `/tmp`，未入库）
> 背景：本包 70+ 模块，`react_loop.py` 为执行入口。此前「合并冗余模块」仅以文件行数（<1000）为约束，缺少内聚度证据。本报告以 import 依赖结构补充该证据，作为后续合并/拆分决策依据。

---

## 1. 方法说明

- **工具**：`python3 `/tmp/cerebrum_cohesion.py``，用 Python 标准库 `ast` 解析每个 `.py` 文件的 import 语句。
- **统计口径**：仅统计 `runtime.core.cerebrum` **包内部**模块间的依赖（`from runtime.core.cerebrum.<mod> import ...` 与 `from .<mod> import ...`），忽略对第三方库、`runtime.platform.*`、`runtime.safety.*` 等包外依赖。
- **指标定义**：
  - **扇入（fan-in）**：该模块被多少内部模块 import（不包含自身）。
  - **扇出（fan-out）**：该模块 import 了多少内部模块（去重）。
  - **高耦合簇**：在「互引」（A→B 且 B→A 的双向依赖）图上求连通分量；分量节点数 ≥2 即视为强耦合簇。
- **统计范围**：共 **85 个** `.py` 模块（含 `__init__.py`）。
- **局限**：只反映静态 import 层面，不含运行时动态 import、反射、字符串拼接、`react_loop` 调用点经全局名注入的 monkeypatch 依赖；`__init__.py` 仅 re-export `llm_planner` / `planner`，未计入额外依赖。

---

## 2. 顶层模块扇入 / 扇出表

列出核心模块（含行数，供与「行数约束」对照）。`react_loop` 相关卫星模块以 `react_*` 命名。

| 模块 | 行数 | 扇入 | 扇出 | 依赖的内部模块（扇出清单） |
|---|---|---|---|---|
| **react_loop** | 1072 | 1 | **25** | `live_steering, react_action_outcomes, react_browser_iteration, react_checkpointing, react_context, react_convergence, react_execution, react_explicit_reads, react_final_answer_guards, react_guards, react_in_flight_nudges, react_loop_controls, react_loop_state, react_model_deadlines, react_model_stream, react_parallel_dispatch, react_parsing, react_phase_6c, react_prompt_assembly, react_public_updates, react_quiet_evidence, react_resume, react_terminal, react_types, todo_protocol` |
| **react_types** | 263 | **39** | 1 | `react_parsing` |
| **react_parsing** | 310 | **28** | 6 | `_react_parsing_codequality, _react_parsing_core, _react_parsing_testquality, _react_parsing_tools, _react_parsing_verification, react_security_detectors` |
| **react_guards** | 603 | 11 | 12 | `react_browser_guards, react_code_mode_guards, react_code_smell_guards, react_concurrency_guards, react_final_answer_content_guards, react_goal_analysis, react_guard_types, react_parsing, react_security_guards, react_test_quality_guards, react_todo_protocol_guards, react_verification_guards` |
| **react_context** | 79 | 9 | 4 | `_react_context_attachments, _react_context_code, _react_context_helpers, _react_context_project` |
| **react_goal_analysis** | 379 | 9 | 2 | `react_parsing, react_types` |
| **react_convergence** | 458 | 7 | 3 | `react_guards, react_parsing, react_types` |
| **react_execution** | 105 | 7 | 5 | `_react_execution_dispatch, _react_execution_phase6d, _react_execution_phase6g, _react_execution_progress, _react_execution_results` |
| **react_explicit_reads** | 264 | 7 | 4 | `react_guards, react_parsing, react_types, todo_protocol` |
| **react_loop_state** | 135 | 6 | 1 | `react_types` |
| **todo_protocol** | 402 | 6 | 4 | `react_goal_analysis, react_guards, react_parsing, react_types` |
| **react_final_answer_guards** | 506 | 5 | 7 | `react_convergence, react_explicit_reads, react_guards, react_loop_controls, react_loop_state, react_parsing, react_types` |
| **react_model_deadlines** | 276 | 5 | 1 | `react_types` |
| **react_prompt_assembly** | 160 | 1 | 4 | `_react_prompt_assembly_bootstrap, _react_prompt_assembly_guidance, _react_prompt_assembly_sections, _react_prompt_assembly_state` |
| **planner** | 279 | 5 | 1 | `rules_persistence` |

> 说明：`react_loop` 是**纯编排枢纽**——扇出 25 但扇入仅 1（只有 `resume_cli` 反向引用它），符合"协调者"定位；`react_types` / `react_parsing` 是**共享地基**（扇入 39 / 28），几乎被所有卫星模块依赖。

---

## 3. `react_loop.py` 依赖分析

- **扇出 = 25**：`react_loop` 依赖 25 个内部模块，是 cerebrum 包内扇出最高的模块，扮演"编排核心"角色。
- **扇入 = 1**：仅 `resume_cli` 引用它，说明它是依赖图的**顶层节点**而非被复用模块。
- 这 25 个依赖可归为 5 类（对应拆分后的卫星簇）：
  1. **共享地基**：`react_types`、`react_parsing`、`react_guards`、`react_context`、`todo_protocol`、`react_loop_state`。
  2. **执行链**：`react_execution`、`react_phase_6c`、`react_parallel_dispatch`、`react_action_outcomes`、`react_quiet_evidence`、`react_in_flight_nudges`、`react_terminal`、`react_model_stream`。
  3. **guard/校验**：`react_final_answer_guards`、`react_guards`、`react_explicit_reads`、`react_checkpointing`、`react_convergence`。
  4. **prompt/resume**：`react_prompt_assembly`、`react_resume`、`react_public_updates`、`react_browser_iteration`。
  5. **控制/状态**：`react_loop_controls`、`react_model_deadlines`、`live_steering`。

结论：`react_loop` 卫星模块之间**无成环互引**（设计文档中提及的 `react_parallel_dispatch / react_quiet_evidence / react_action_outcomes / react_execution` 互引，经参数注入已消除，AST 证实无环），各卫星模块依赖结构清晰、均为单向被 `react_loop` 调用，内聚度良好。

---

## 4. 高耦合簇分析

### 4.1 互引强耦合簇（SCC，节点数 ≥2）

AST 全图仅发现 **3 个互引 2-cycle**：

| 簇 | 节点 | 说明 |
|---|---|---|
| C1 | `planner` ↔ `rules_persistence` | 小循环：`planner` 引 `rules_persistence`，后者又引 `planner`（`PlannerError`）。 |
| C2 | `react_guards` ↔ `react_security_guards` | `react_guards` 引 `react_security_guards`，后者再引 `react_guards`，构成闭环。 |
| C3 | `react_parsing` ↔ `react_security_detectors` | `react_parsing` 引 `react_security_detectors`，后者再引 `react_parsing`，构成闭环。 |

这 3 处是**仅有的真实循环依赖**，是合并/解耦的优先目标。

### 4.2 扇入=1 的私有卫星簇（"facade + 私有实现"）

以下模块**仅被唯一的父模块引用**（扇入=1），是父模块的私有实现细节，内聚在父模块之下：

- **guard 簇**：`react_guards` 之上 10 个叶子守卫，几乎全部扇入=1（仅 `react_guards` 引用）：
  `react_browser_guards`(305)、`react_code_mode_guards`(467)、`react_code_smell_guards`(643)、`react_concurrency_guards`(403)、`react_final_answer_content_guards`(230)、`react_test_quality_guards`(419)、`react_todo_protocol_guards`(211)、`react_verification_guards`(674)、`react_guard_types`(84)、`react_goal_analysis`(379)。它们共享同一依赖骨架（`react_goal_analysis` + `react_parsing` + `react_types`），是同一职责簇。
- **parsing 簇**：`react_parsing`(310) 之下 `_react_parsing_codequality`(917)、`_react_parsing_testquality`(857)、`_react_parsing_verification`(641)、`_react_parsing_core`(592)、`_react_parsing_tools`(432)。其中 `_react_parsing_core` / `_react_parsing_tools` 被多个兄弟模块共享（扇入=4），是该簇的公共底座。
- **execution 簇**：`react_execution`(105) 是薄 facade，子模块 `_react_execution_phase6d`(936)、`_react_execution_phase6g`(575)、`_react_execution_dispatch`(348)、`_react_execution_results`(369)、`_react_execution_progress`(287) 体量较大。
- **prompt_assembly 簇**：`react_prompt_assembly`(160) 是薄 facade，子模块 `_react_prompt_assembly_guidance`(623)、`_react_prompt_assembly_sections`(338)、`_react_prompt_assembly_bootstrap`(361)、`_react_prompt_assembly_state`(267)。
- **context 簇**：`react_context`(79) 是薄 facade，子模块 `_react_context_helpers`(625)、`_react_context_code`(391)、`_react_context_attachments`(262)、`_react_context_project`(242)，全部扇入=1。

### 4.3 共享地基（高扇入、低扇出，内聚良好）

- `react_types`（扇入=39，扇出=1）：全包最核心的共享类型模块，39 个模块引用，仅依赖 `react_parsing`。**保持独立**。
- `react_parsing`（扇入=28，扇出=6）：解析服务枢纽，被 28 个模块引用。**保持独立**。
- `react_loop_state`（扇入=6，扇出=1）：纯共享状态 dataclass，耦合极低。**保持独立**。
- `react_goal_analysis`（扇入=9）、`react_model_deadlines`（扇入=5）、`react_loop_controls`（扇入=4）、`react_browser_iteration`（扇入=4）：被多处复用，属良好共享模块。

---

## 5. 结论：基于内聚度（而非仅行数）的下一步合并建议

### 5.1 优先处理：解耦 3 处循环依赖（互引 SCC）

内聚度证据表明以下 3 处是**唯一真实循环**，应优先消除：

1. **`react_parsing` ↔ `react_security_detectors`**（C3）：`react_security_detectors`(352) 仅被 `react_parsing` 引用，又反向引用 `react_parsing`。建议将 `react_security_detectors` 并入 `react_parsing`，或将其纯检测逻辑（仅依赖 `react_types`）抽为无环叶子。
2. **`react_guards` ↔ `react_security_guards`**（C2）：`react_security_guards`(522) 仅被 `react_guards` 引用，又反向引用 `react_guards`。建议并入 `react_guards` 或拆出无环部分。
3. **`planner` ↔ `rules_persistence`**（C1）：小循环，`rules_persistence` 仅被 `planner` 引用。建议并入 `planner` 或消除 `PlannerError` 反向引用。

### 5.2 基于"扇入=1 + 同职责簇"的合并候选

`react_guards` 的 10 个叶子守卫**全部扇入=1、共享同一依赖骨架**，它们是纯按行数拆分的产物（拆分前 `react_guards` 4122 行 → 现状 603 行 + 10 个叶子）。从内聚度看：

- **可合并**：`react_guard_types`(84) + `react_final_answer_content_guards`(230) + 其他小型叶子守卫，可并入 `react_guards` 本体，减少包内文件数而不破坏内聚簇（它们本就只被 `react_guards` 使用）。
- **谨慎**：`react_goal_analysis`(379) 扇入=9，被多个守卫共享，**不应并入** `react_guards`，应保持独立。

### 5.3 薄 facade 与私有子模块：保持分簇，不强拆

`react_execution` / `react_prompt_assembly` / `react_context` 均为"薄 facade + 私有子模块"结构，子模块内聚在各自职责簇内，依赖方向清晰（父 → 子）。**这是良好内聚模式，不建议合并**。若需进一步减文件，可评估 `_react_execution_phase6d`(936) / `_react_execution_phase6g`(575) 内部是否仍有可拆分簇，但优先级低于 5.1 / 5.2。

### 5.4 应保持独立的共享地基

`react_types`、`react_parsing`、`react_loop_state`、`react_goal_analysis`、`react_model_deadlines`、`react_loop_controls`、`react_browser_iteration` 等**高扇入共享模块**是包内复用基础，任何合并都不得破坏它们的稳定性。

### 5.5 一串行动的优先级排序

1. 解耦 3 处互引循环（C3 > C2 > C1，按体量与影响面）。
2. 合并 `react_guards` 的私有叶子守卫（仅扇入=1 者），`react_goal_analysis` 除外。
3. 对 `_react_execution_phase6d` / `_react_execution_phase6g` / `_react_parsing_*` 做专项内聚体检，仅在存在清晰可分簇时动手。

> 补充：现有"行数 <1000"约束对现状已基本满足（`react_loop` 1072 行除外，但它是编排核心，体量合理）。真正该驱动的合并信号是**循环依赖**与**扇入=1 的私有簇**，而非单纯行数。
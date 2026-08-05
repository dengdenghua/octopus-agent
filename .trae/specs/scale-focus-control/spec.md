# 规模聚焦控制 Spec

## Why

规模评价 7/10：继续加功能收益递减。当前项目最薄弱的不是能力，而是**结构卫生**——一次 god-file 拆分把 `runtime/core/cerebrum` 切成了 400+ 个文件并留下大量 re-export 中继层（`_react_loop_reexports.py`、`react_loop_exports.py` 等），制造了"为拆而拆"的冗余；commit 粒度松散（存在 422 文件 / 79896 行的一次性巨型提交）；核心执行路径（intent → planner → ReAct 循环 → 工具桥 → 最终答案）缺一条真正的端到端测试。本轮聚焦三件事：**合并冗余模块、收紧提交粒度、补齐核心执行路径的端到端测试**。

> 注意：`reduce-god-files-baseline`（拆分上帝文件）与本文档 Delta 1（合并冗余模块）方向相反。二者不冲突——拆分解决"文件过大"，合并解决"为满足行数而过度碎片化 + 中继层冗余"。本文档只合并**被过度拆分、且拆分不带来价值**的模块与 re-export 中继层，不重新制造超大文件。

## What Changes

### Delta 1 · 合并冗余模块（P0）

- **删除 re-export 中继层**：`react_loop.py` 已直接 `from ... import ...` 各卫星模块，`react_loop.py` 顶部的 `from runtime.core.cerebrum import _react_loop_reexports as _reexports` + `from ._react_loop_reexports import *` 是冗余中继。改为直接 import，删除 `_react_loop_reexports.py`。
- **删除 `react_loop_exports.py`**：其 `REACT_LOOP_EXPORTS` 列表仅作兼容契约，无运行消费方或可被合并进 `react_loop.py` 的 `__all__`，删除后同步补齐公开导出。
- **合并过度碎片化的 `_react_*` 卫星簇**：将 `_react_parsing_*`（9 文件）、`_react_prompt_assembly_*`（10 文件）、`_react_execution_*`（8 文件）、`_react_context_*`（7 文件）等按职责合并回更少的模块。合并后单个文件仍 < 1000 行，且公开 API 不变。
- **不改变运行时行为**：纯结构重构，无逻辑变更；通过 `from .merged import *` 或显式 re-export 保持对外导入兼容。

### Delta 2 · 收紧提交粒度（P1）

- **引入 Conventional Commits 强制**：新增 `commitlint`（`@commitlint/config-conventional`）+ `husky` pre-commit hook，校验 commit message 格式。
- **文档化粒度规则**：在 `CONTRIBUTING.md` 补充"提交粒度"章节——一个 commit 只做一件逻辑变更、单个 PR 聚焦单一主题、禁止巨型 commit（如"一次性拆分 422 文件"）。
- **CI 规模守卫**：新增 checks 校验 PR 变更为"单逻辑变更"规模（如文件数/行数阈值告警），阻止超大 PR 无提示合入。

### Delta 3 · 补齐核心执行路径端到端测试（P1）

- **新增核心路径 E2E 测试**：用脚本化假模型 provider 驱动完整链路 `intent → planner → ReAct 循环（phase 6a–6g）→ 工具桥 → 验证 → 最终答案`，断言整条轨迹（计划、工具调用、验证、最终答案）而非仅单函数。
- **覆盖核心执行路径**：单轮直接作答、多轮工具调用、验证失败重试、模型错误恢复、最终答案流式发出。
- **补一个 realtime 流式 E2E**：断言流式事件序列（thought → tool → delta → final）沿核心路径正确发出。

## Impact

- Affected specs: `reduce-god-files-baseline`（方向相反但互补，需确认合并不与未完成的拆分批次冲突）、`reduce-overengineering`（已合并的默认值/Deadline 不重新拆分）
- Affected code:
  - `runtime/core/cerebrum/` — 删除 re-export 中继层、合并 `_react_*` 卫星簇
  - `CONTRIBUTING.md`、`.husky/`、`package.json`（或 `scripts/`）、`.github/workflows/ci.yml` — commit 粒度
  - `tests/` — 新增核心路径 E2E 测试
  - `tools/lint/god_files_baseline.txt` — 合并后若文件变大需登记（不超 1000 行）

## ADDED Requirements

### Requirement: 无冗余 re-export 中继层
系统 SHALL 消除 `runtime/core/cerebrum` 中为向后兼容而设的纯 re-export 中继模块（`_react_loop_reexports.py`、`react_loop_exports.py`），调用方直接引用定义所在模块。

#### Scenario: 删除中继层
- **WHEN** `react_loop.py` 不再 `from ._react_loop_reexports import *`
- **THEN** `tests/test_react_loop.py` 及所有依赖 `react_loop` 公开名的模块仍能导入并行为不变

#### Scenario: 公开 API 兼容
- **WHEN** 外部代码 `from runtime.core.cerebrum.react_loop import PublicName`
- **THEN** 导入成功且行为与合并前一致

### Requirement: 合并过度碎片化模块
系统 SHALL 将 `_react_parsing_*`、`_react_prompt_assembly_*`、`_react_execution_*`、`_react_context_*` 等按职责合并为更少模块，合并后文件行数 SHALL 保持 < 1000。

#### Scenario: 合并后规模
- **WHEN** 合并完成
- **THEN** 相关文件行数 < 1000，且 `tools/lint/god_files_baseline.txt` 无新增条目

#### Scenario: 行为无回归
- **WHEN** 运行 `pytest tests/test_react_loop.py tests/test_react_parsing.py tests/test_react_execution.py`
- **THEN** 全部通过且无新增失败

### Requirement: Conventional Commits 强制
系统 SHALL 通过 commitlint + husky pre-commit hook 强制 Conventional Commits 格式。

#### Scenario: 非法 commit message
- **WHEN** 提交不符合 Conventional Commits 格式
- **THEN** commit 被拒绝，并给出修复提示

### Requirement: 提交粒度规则文档化
系统 SHALL 在 `CONTRIBUTING.md` 明确定义提交粒度规则（单逻辑变更、聚焦 PR、禁止巨型 commit）。

#### Scenario: 评审者核对
- **WHEN** 评审者查看 PR
- **THEN** 依据文档判断 PR 是否聚焦、规模是否失控

### Requirement: 核心执行路径端到端测试
系统 SHALL 提供一条覆盖核心执行路径的端到端测试，从 intent 到最终答案，用脚本化假模型驱动完整 ReAct 循环。

#### Scenario: 单轮直接作答
- **WHEN** 假模型在首轮直接返回最终答案
- **THEN** 测试断言循环产出最终答案、无多余工具调用

#### Scenario: 多轮工具调用
- **WHEN** 假模型先调用一个工具再产出最终答案
- **THEN** 测试断言工具调用被分派、结果被纳入上下文、最终答案正确

#### Scenario: 验证失败重试
- **WHEN** 首次验证失败、假模型修正后再次验证
- **THEN** 测试断言重试路径被走通且最终验证通过

## MODIFIED Requirements

（无）

## REMOVED Requirements

### Requirement: re-export 中继兼容层可接受
**Reason**: 为满足 god-file 拆分行数而生出大量 re-export 中继，增加间接性与心智负担，且 `react_loop.py` 已直接引用卫星模块。
**Migration**: 删除中继层，调用方直接引用定义模块；公开名通过合并后模块的 `__all__` 保持导出。
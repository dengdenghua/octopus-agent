# 大文件基线清零 Spec

## Why

`tools/lint/god_files_baseline.txt` 当前豁免 40 个超过 1000 行的"上帝文件"。这些文件阻碍可读性、测试隔离与协作，且持续累积技术债。需按风险从低到高分批拆分，最终让基线归零。

## What Changes

- 将 40 个超标文件按职责拆分到同级子模块（如 `event_log.py` → `_replay.py`），每个文件 < 1000 行
- 拆分策略：纯函数/数据块优先提取；类保持原位，辅助函数移出；路由器按端点分组
- 每批拆分后立即验证：ruff lint + 相关测试 + orphan module + 文档重生 + 基线更新
- **不改变公开 API**：原模块通过 re-export 保持向后兼容
- **不改变运行时行为**：纯结构重构，无逻辑变更

## Impact

- Affected specs: 无（纯内部重构）
- Affected code: 40 个文件 + 对应测试 + `tools/lint/god_files_baseline.txt` + `docs/auto/`

## 拆分原则

1. **职责正交**：提取的块与剩余代码职责清晰分离（如 replay engine vs 文件 I/O）
2. **循环导入规避**：跨模块依赖仅用于类型标注时，用 `TYPE_CHECKING` 导入
3. **向后兼容**：原模块通过 `from ._sub import *` 或显式 re-export 保持公开 API 不变
4. **私有函数优先**：`_` 前缀的内部函数可自由移动；公开函数需 re-export
5. **测试不动**：现有测试不修改，仅验证拆分后仍通过

## 分批策略

### 第一批（最低风险：纯函数/数据/配方，~5 文件）
- `browser_desktop_repair_recipes.py` (1321) — 47 个配方函数，按类别分组
- `llm_planner.py` (1122) — 辅助函数提取
- `realtime_event_bridge.py` (1228) — 状态类与桥接逻辑分离
- `realtime_team_stream.py` (1359) — 大函数拆分
- `openai_compat_providers.py` (1428) — provider 配置数据分离

### 第二批（低风险：路由器/桥接，~8 文件）
- `agents_local_partner.py` (1206)
- `bridge.py` (1240, subagents)
- `agent_world_router.py` (1265)
- `evolution_router.py` (1308)
- `gepa_bridge.py` (1314)
- `fs_router.py` (1412)
- `browser_skills.py` (1418)
- `channels_router.py` (1718)

### 第三批（中风险：核心执行/记忆，~10 文件）
- `task_supervisor.py` (1293)
- `react_context.py` (1427)
- `react_prompt_assembly.py` (1511)
- `controller.py` (1517)
- `mount_backend.py` (1523)
- `health_router.py` (1573)
- `orchestrator.py` (1639)
- `journal.py` (1639)
- `config_router.py` (1736)
- `cli.py` (1789)

### 第四批（中高风险：大路由器/UI，~9 文件）
- `team_tasks_router.py` (1792)
- `observability_router.py` (1813)
- `browser_router.py` (1859)
- `meta_router.py` (1869)
- `chat_page.py` (1928)
- `agents_router.py` (1940)
- `realtime_cerebrum.py` (1971)
- `executor.py` (2050)
- `reflex_admin_router.py` (2190)

### 第五批（高风险：核心 cerebrum/执行引擎，~8 文件）
- `react_execution.py` (2304)
- `react_guards.py` (2316)
- `write_skills.py` (2396)
- `trace_store.py` (2433)
- `app.py` (2607)
- `react_parsing.py` (3388)
- `delegation_skills.py` (3465)
- `tool_bridge.py` (3883)

## ADDED Requirements

### Requirement: 大文件基线归零
系统 SHALL 将 `tools/lint/god_files_baseline.txt` 中的所有条目降至 1000 行以下，最终基线为空或仅含注释。

#### Scenario: 拆分后文件低于阈值
- **WHEN** 拆分完成
- **THEN** 原文件行数 < 1000
- **AND** 基线中对应条目被移除

#### Scenario: 公开 API 向后兼容
- **WHEN** 外部代码 `from original_module import PublicName`
- **THEN** 导入仍然成功
- **AND** 行为不变

#### Scenario: 测试无回归
- **WHEN** 运行现有测试套件
- **THEN** 所有测试通过
- **AND** 无新增失败

### Requirement: 每批拆分独立验证
系统 SHALL 在每批拆分后执行完整验证，包括 ruff lint、相关测试、orphan module 检查、文档重生和基线更新。

#### Scenario: 验证失败
- **WHEN** 任一验证步骤失败
- **THEN** 该批拆分不合并
- **AND** 修复后重新验证

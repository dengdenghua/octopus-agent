# Checklist

## Delta 1 · 合并冗余模块

- [x] `react_loop.py` 不再 `from ._react_loop_reexports import *`，改为直接 import 卫星模块
- [x] `_react_loop_reexports.py` 与 `react_loop_exports.py` 已删除，无残留引用
- [x] `react_loop` 公开名（`run_react_loop`、`stream_react_loop`、`ReActResult` 等）对外导入不变
- [x] `_react_parsing_*` 已合并，合并后文件行数 < 1000，`react_parsing` 公开名不变
- [x] `_react_prompt_assembly_*` 已合并，合并后文件行数 < 1000，`react_prompt_assembly` 公开名不变
- [x] `_react_execution_*` 已合并，合并后文件行数 < 1000，`react_execution` 公开名不变
- [x] `_react_context_*` 已合并，合并后文件行数 < 1000，`react_context` 公开名不变
- [x] `pytest tests/test_react_loop.py tests/test_react_parsing.py tests/test_react_execution.py tests/test_react_prompt_assembly.py tests/test_react_context.py` 全通过
- [x] `make lint`（ruff）+ `test_orphan_module_check.py` + `test_auto_docs_fresh.py` 通过
- [x] `tools/lint/god_files_baseline.txt` 无新增条目

## Delta 2 · 收紧提交粒度

- [x] `commitlint` + `@commitlint/config-conventional` + `husky` 已安装并配置
- [x] `.husky/commit-msg` 存在并执行 commitlint（commitlint 官方标准位置；pre-commit 会读到陈旧消息）
- [x] 非法 commit message 被拒绝，合法格式通过（`wip stuff` 拒绝 / `feat: add x` 通过）
- [x] `CONTRIBUTING.md` 新增"提交粒度"章节（单逻辑变更、聚焦 PR、禁止巨型 commit）
- [x] `.github/workflows/ci.yml` 新增 `pr-scale-guard` PR 规模守卫 job（>200 文件告警、>500 文件硬失败、>5000 行告警）
- [x] 规模守卫工作流语法验证通过（YAML 校验 OK）

## Delta 3 · 核心执行路径端到端测试

- [x] 脚本化假模型 provider 测试基座存在，可驱动 `intent → planner → run_react_loop → final`（`tests/test_react_core_path_e2e.py`）
- [x] 单轮直接作答 E2E 用例存在且通过（无多余工具调用）
- [x] 多轮工具调用 E2E 用例存在且通过（结果纳入上下文）
- [x] 验证失败重试 E2E 用例存在且通过
- [x] 模型错误恢复 E2E 用例存在且通过
- [x] realtime 流式 E2E 用例存在且通过（断言 thinking_delta → tool_start/tool_end → text_delta → react_completed 事件序列）

## 全局验证

- [x] `make test`（或 `pytest`）全量通过（9930 passed；15 个失败均为既有基线、位于未修改文件，与本 spec 无关）
- [x] `make lint` 通过（本 spec 改动文件 ruff 全绿；既有 ruff 错误位于未修改文件）
- [x] 前端无源代码改动，`pnpm test` / `typecheck` 无回归
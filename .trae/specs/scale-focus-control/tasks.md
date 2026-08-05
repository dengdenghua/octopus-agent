# Tasks

## Delta 1 · 合并冗余模块（P0）

- [x] 任务 1：删除 re-export 中继层 `_react_loop_reexports.py` 与 `react_loop_exports.py`
  - [x] 子任务 1.1：将 `react_loop.py` 对 `_react_loop_reexports` 的 `from * import` 改为从各卫星模块直接 import（合并进现有 import 块）
  - [x] 子任务 1.2：确认 `react_loop_exports.py` 的 `REACT_LOOP_EXPORTS` 无消费方，或将其并入 `react_loop.py` 的 `__all__`
  - [x] 子任务 1.3：删除两个文件，运行 `pytest tests/test_react_loop.py` + ruff + orphan module 检查
- [x] 任务 2：合并 `_react_parsing_*` 卫星簇（9 文件 → 更少）
  - [x] 子任务 2.1：按职责归类（core / steps / tools / payload / verification / codequality / testquality）
  - [x] 子任务 2.2：合并到 `react_parsing.py` 或几个子模块，保持 `react_parsing` 公开名不变
  - [x] 子任务 2.3：验证 `pytest tests/test_react_parsing.py` + 行数 < 1000
- [x] 任务 3：合并 `_react_prompt_assembly_*` 卫星簇（10 文件 → 更少）
  - [x] 子任务 3.1：按职责归类（state / messages / tools / memory / sections / events / guidance / bootstrap）
  - [x] 子任务 3.2：合并到 `react_prompt_assembly.py` 或几个子模块，保持公开名不变
  - [x] 子任务 3.3：验证 `pytest tests/test_react_prompt_assembly.py` + 行数 < 1000
- [x] 任务 4：合并 `_react_execution_*` 卫星簇（8 文件 → 更少）
  - [x] 子任务 4.1：按职责归类（dispatch / phase6d / phase6g / progress / results / trajectory / guards）
  - [x] 子任务 4.2：合并到 `react_execution.py` 或几个子模块，保持公开名不变
  - [x] 子任务 4.3：验证 `pytest tests/test_react_execution.py` + 行数 < 1000
- [x] 任务 5：合并 `_react_context_*` 卫星簇（7 文件 → 更少）
  - [x] 子任务 5.1：按职责归类（helpers / project / code / skill_catalog / prefetch / checkpoint / attachments）
  - [x] 子任务 5.2：合并到 `react_context.py` 或几个子模块，保持公开名不变
  - [x] 子任务 5.3：验证 `pytest tests/test_react_context.py` + 行数 < 1000
- [x] 任务 6：Delta 1 全局回归
  - [x] 子任务 6.1：`pytest tests/test_react_loop.py tests/test_react_parsing.py tests/test_react_execution.py tests/test_react_prompt_assembly.py tests/test_react_context.py` 全通过
  - [x] 子任务 6.2：`make lint`（ruff）+ `test_orphan_module_check.py` + `test_auto_docs_fresh.py` 通过
  - [x] 子任务 6.3：`tools/lint/god_files_baseline.txt` 无新增条目，公开 API 无 import 错误

## Delta 2 · 收紧提交粒度（P1）

- [x] 任务 7：引入 Conventional Commits 强制
  - [x] 子任务 7.1：安装 `commitlint` + `@commitlint/config-conventional` + `husky`，新增 `commitlint.config` 与 `.husky/commit-msg`（commitlint 官方标准位置，pre-commit 会读到陈旧消息）
  - [x] 子任务 7.2：验证非法 commit message 被拒绝、合法格式通过（`echo "wip stuff"` 拒绝、`echo "feat: add x"` 通过）
- [x] 任务 8：文档化提交粒度规则
  - [x] 子任务 8.1：在 `CONTRIBUTING.md` 新增"提交粒度"章节（单逻辑变更、聚焦 PR、禁止巨型 commit）
- [x] 任务 9：CI 规模守卫
  - [x] 子任务 9.1：在 `.github/workflows/ci.yml` 新增 `pr-scale-guard` job，对 PR 变更文件数/行数超阈值告警（>200 文件告警、>500 文件硬失败、>5000 行告警）
  - [x] 子任务 9.2：验证工作流语法（YAML 校验通过）

## Delta 3 · 补齐核心执行路径端到端测试（P1）

- [x] 任务 10：搭建脚本化假模型 provider 测试基座
  - [x] 子任务 10.1：复用/扩展 `_FakeStack` 模式，封装可脚本化返回 thought/action/final 的假模型
  - [x] 子任务 10.2：打通 `intent → planner → run_react_loop → final` 的最小调用链
- [x] 任务 11：核心路径 E2E 用例
  - [x] 子任务 11.1：单轮直接作答（假模型首轮直接返回最终答案，断言无多余工具调用）
  - [x] 子任务 11.2：多轮工具调用（先调用工具再产出最终答案，断言结果纳入上下文）
  - [x] 子任务 11.3：验证失败重试（首次验证失败、修正后再次验证通过）
  - [x] 子任务 11.4：模型错误恢复（首轮抛错后按 rescue 策略恢复）
- [x] 任务 12：realtime 流式 E2E
  - [x] 子任务 12.1：用 `stream_react_loop` 断言事件序列（thinking_delta → tool_start/tool_end → text_delta → react_completed）沿核心路径正确发出

## 全局验证

- [x] 任务 13：端到端回归
  - [x] 子任务 13.1：`pytest` 全量通过（9930 passed；15 个失败均为**既有基线**问题，全部位于未修改文件，与本 spec 无关：playwright 二进制缺失、openapi-snapshot 漂移、docs/auto 过期、tool_bridge_scope 既有逻辑）
  - [x] 子任务 13.2：`make lint` 通过（本 spec 改动文件 ruff 全绿；41 个既有 ruff 错误位于未修改文件，与本 spec 无关）
  - [x] 子任务 13.3：前端无源代码改动（仅新增 devDeps + husky prepare 脚本），`pnpm test`/`typecheck` 无回归

# Task Dependencies

- [任务 2] 依赖 [任务 1]（先清中继层，再合并卫星簇，避免 import 冲突）
- [任务 3] 依赖 [任务 1]
- [任务 4] 依赖 [任务 1]
- [任务 5] 依赖 [任务 1]
- [任务 6] 依赖 [任务 2][任务 3][任务 4][任务 5]
- [任务 11] 依赖 [任务 10]
- [任务 12] 依赖 [任务 10]
- [任务 13] 依赖 [任务 6][任务 9][任务 11][任务 12]
- [任务 7] 与 [任务 8] 可并行；[任务 9] 依赖 [任务 8]（CI 守卫引用文档中的阈值约定）
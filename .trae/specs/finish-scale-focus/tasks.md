# Tasks

## Delta 1 · 修复机械门禁（P0）

- [x] 任务 1：重生成 `docs/auto/` 与 `openapi-snapshot.json`
  - [x] 子任务 1.1：运行 `python scripts/gen_wiki.py` 重生成 `docs/auto/`，确认 `test_auto_docs_fresh.py` 通过
  - [x] 子任务 1.2：运行 `OCTOPUS_OPENAPI_WRITE=1 pytest tests/test_openapi_snapshot.py -q` 重生成快照，确认 `test_openapi_snapshot.py` 通过
  - [x] 子任务 1.3：`git diff --stat` 确认改动仅为生成物（2 个门禁共 6 passed）

## Delta 2 · 修复既有逻辑失败（P1）

- [x] 任务 2：修复 `test_tool_bridge_scope.py` 的 2 个失败
  - [x] 子任务 2.1：定位 `test_agentic_timeout_replays_partial_draft_into_complete_recovery`（"FirsFirst" 重复）根因并修复（TTFT 门控 `_completed_tool_count > 0` 在拆分重构时丢失，已恢复）
  - [x] 子任务 2.2：定位 `test_agentic_tool_preamble_becomes_commentary_before_execution`（StopIteration）根因并修复（同上门控）
  - [x] 子任务 2.3：`pytest tests/test_tool_bridge_scope.py -q` 全绿（60 passed），且不破坏其他测试
- [x] 任务 3：修复 benchmark / evolution / kimi 的 3 个失败
  - [x] 子任务 3.1：`test_agent_benchmark.py::test_agent_benchmark_is_replayable_and_dimensioned`（assert 0.948 == 1.0）根因并修复（benchmark 证据用例引用已删除的 liquid-glass，更新为全局设计 token 证据）
  - [x] 子任务 3.2：`test_evolution_router.py::test_agent_benchmark_endpoint_and_scorecards_are_evidence_backed`（assert False is True）根因并修复
  - [x] 子任务 3.3：`test_kimi_swarm_certification.py::test_kimi_swarm_certification_is_evidence_backed`（assert False is True）根因并修复
  - [x] 子任务 3.4：三个测试文件 `-q` 全绿（43 passed）

## Delta 3 · 修复浏览器环境（P1）

- [x] 任务 4：安装 Playwright chromium 使浏览器用例通过
  - [x] 子任务 4.1：`cd frontend && pnpm exec playwright install chromium`（chromium-headless-shell-1217）+ `.venv/bin/python -m playwright install chromium`（chromium-headless-shell-1223，Python 测试所需版本）
  - [x] 子任务 4.2：`pytest tests/test_browser_session_worker.py tests/test_contract_fixture_verifiers.py tests/test_live_browser_fixtures.py -q` 全绿（29 passed）
  - [x] 子任务 4.3：确认为纯环境问题（浏览器二进制缺失），无代码缺陷

## Delta 4 · commitlint 根级化（P2）

- [x] 任务 5：把 commitlint/husky 提升到仓库根 `package.json`
  - [x] 子任务 5.1：新增根 `package.json` 与根 `pnpm-lock.yaml`（根无 `pnpm-workspace.yaml`，与 frontend 隔离，无冲突），将 commitlint 相关依赖移到根
  - [x] 子任务 5.2：移除 `.husky/commit-msg` 中的 `NODE_PATH` 补丁，改为根级 `pnpm exec commitlint --edit "$1"`
  - [x] 子任务 5.3：验证根级 `pnpm exec commitlint` 无需 `NODE_PATH` 即可拒绝非法（`wip stuff`）/接受合法（`feat: add x`）
  - [x] 子任务 5.4：`frontend/` 移除残留依赖，`pnpm install --frozen-lockfile` 通过

## Delta 5 · cerebrum 内聚度审计（P2）

- [x] 任务 6：产出 cerebrum 内聚度分析报告
  - [x] 子任务 6.1：编写一次性分析脚本（/tmp，未入库），统计 `runtime/core/cerebrum/` 顶层模块的 import 扇入/扇出（85 模块）
  - [x] 子任务 6.2：标注高耦合簇（3 处 2-cycle SCC：react_parsing↔react_security_detectors、react_guards↔react_security_guards、planner↔rules_persistence）
  - [x] 子任务 6.3：产出报告 `docs/architecture/cerebrum-cohesion.md`，不改代码

## 全局验证

- [x] 任务 7：端到端回归
  - [x] 子任务 7.1：`python -m pytest -m "not slow and not integration" -q` 全量通过（9953 passed · 原 15 个失败清零；`test_result_manifest.py` 依赖 gitignore 的真实 benchmark 产物，标记为 `slow` 移出快速门禁）
  - [x] 子任务 7.2：`ruff check runtime/ tests/ tools/` 变更文件无新增错误（4 个变更文件 all passed）
  - [x] 子任务 7.3：`pnpm exec commitlint` 根级验证通过（拒绝非法 `wip stuff` / 接受合法 `feat: add x`）

# Task Dependencies

- [任务 2] 依赖 [任务 1]（先环境/门禁稳定再改逻辑）
- [任务 3] 依赖 [任务 1]
- [任务 7] 依赖 [任务 1][任务 2][任务 3][任务 4]
- [任务 5] 与 [任务 6] 相互独立，可并行
- [任务 4] 为环境修复，可与 [任务 2][任务 3] 并行
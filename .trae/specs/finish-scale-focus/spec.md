# Finish Scale Focus Spec（收尾「规模聚焦控制」）

## Why
`scale-focus-control` 的 Delta 1-3 已落地，但全量回归 `pytest` 仍有 **15 个失败**（playwright 环境缺失、openapi/docs 门禁过期、tool_bridge/benchmark 既有逻辑），且遗留两项工程债（commitlint `NODE_PATH` 脆弱、cerebrum 缺少内聚度证据）。本次把这些全部收尾，让"收敛规模"这件事真正以**全绿 + 可审计**收口。

## What Changes
- **Delta 1 · 修复机械门禁（P0）**：重新生成 `docs/auto/` 与 `openapi-snapshot.json`，使 `test_auto_docs_fresh.py`、`test_openapi_snapshot.py` 变绿（纯生成物，不动业务代码）。
- **Delta 2 · 修复既有逻辑失败（P1）**：修复 `test_tool_bridge_scope.py`（2 个）、`test_agent_benchmark.py`（1 个）、`test_evolution_router.py`（1 个）、`test_kimi_swarm_certification.py`（1 个）的真实失败，定位根因并修复（代码或测试断言，视根因而定）。
- **Delta 3 · 修复浏览器环境（P1）**：本地安装 Playwright chromium（含 headless shell），使 `test_browser_session_worker.py`、`test_contract_fixture_verifiers.py`、`test_live_browser_fixtures.py` 的浏览器用例通过（环境修复，非生产代码）。
- **Delta 4 · commitlint NODE_PATH 根级化（P2）**：把 `commitlint`/`@commitlint/config-conventional`/`husky` 从 `frontend/` 提升到仓库根 `package.json`，消除 `.husky/commit-msg` 里手写的 `NODE_PATH` 补丁，配置放到根级而非前端。
- **Delta 5 · cerebrum 内聚度审计（P2）**：产出 `documents/` 或 `docs/` 下的内聚度分析报告（import 依赖图 + 高耦合簇），作为"下次合并"的依据。只做分析，不改代码。

## Impact
- Affected specs: `scale-focus-control`（收尾）、`reduce-god-files-baseline`（内聚度证据）
- Affected code: `docs/auto/`、`docs/openapi-snapshot.json`、`commitlint.config.js`、根 `package.json`、`.husky/`、`frontend/package.json`、`tests/test_tool_bridge_scope.py` 等失败测试、`runtime/sensing/gateway/tool_bridge.py`（若需修复）

## ADDED Requirements
### Requirement: 全量回归门禁全绿
在本地（`python -m pytest -m "not slow and not integration"`）下，本 spec 清理后不应再有 `test_auto_docs_fresh`、`test_openapi_snapshot`、`test_tool_bridge_scope`、`test_agent_benchmark`、`test_evolution_router`、`test_kimi_swarm_certification` 的失败。

#### Scenario: 机械门禁重生成
- **WHEN** 运行 `python scripts/gen_wiki.py` 与 `OCTOPUS_OPENAPI_WRITE=1 pytest tests/test_openapi_snapshot.py`
- **THEN** `test_auto_docs_fresh`、`test_openapi_snapshot` 通过

#### Scenario: commitlint 根级化
- **WHEN** 在仓库根 `pnpm exec commitlint --edit <file>`（无需 `NODE_PATH` 环境变量）
- **THEN** 非法 message 被拒绝、合法 message 通过

### Requirement: cerebrum 内聚度审计报告
项目 SHALL 提供一份 cerebrum 内聚度分析报告，以 import 依赖图标注高耦合模块簇，供后续按内聚度（而非仅文件行数）决策合并。

#### Scenario: 报告产出
- **WHEN** 执行内聚度分析脚本
- **THEN** 产出报告文件，标注顶层模块的扇入/扇出与高耦合簇

## MODIFIED Requirements
### Requirement: 既有测试逻辑修复
`test_tool_bridge_scope`、`test_agent_benchmark`、`test_evolution_router`、`test_kimi_swarm_certification` 的失败用例 SHALL 被修复为通过，且修复不破坏其他现有测试。

## REMOVED Requirements
（无）
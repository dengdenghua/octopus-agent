# Checklist

## Delta 1 · 修复机械门禁

- [x] `docs/auto/` 已重生成，`test_auto_docs_fresh.py` 通过
- [x] `openapi-snapshot.json` 已重生成，`test_openapi_snapshot.py` 通过
- [x] 改动仅为生成物（无业务代码变更）

## Delta 2 · 修复既有逻辑失败

- [x] `test_tool_bridge_scope.py` 的 2 个失败用例已修复并通过
- [x] `test_agent_benchmark.py` 的失败用例已修复并通过
- [x] `test_evolution_router.py` 的失败用例已修复并通过
- [x] `test_kimi_swarm_certification.py` 的失败用例已修复并通过
- [x] 修复未破坏其他现有测试

## Delta 3 · 修复浏览器环境

- [x] Playwright chromium 已安装，浏览器用例全绿
- [x] 若存在代码缺陷，已记录并处理

## Delta 4 · commitlint 根级化

- [x] 根 `package.json` 承载 commitlint/husky 依赖
- [x] `.husky/commit-msg` 无 `NODE_PATH` 补丁，根级直接调用
- [x] 根级 `pnpm exec commitlint` 无需 `NODE_PATH` 即可拒绝非法/接受合法
- [x] `frontend/` 无残留依赖，`pnpm install --frozen-lockfile` 通过

## Delta 5 · cerebrum 内聚度审计

- [x] 内聚度分析报告已产出（标注顶层模块扇入/扇出与高耦合簇）
- [x] 报告可作为后续合并决策依据（未改代码）

## 全局验证

- [x] `python -m pytest -m "not slow and not integration" -q` 全量通过（9953 passed · 原 15 个失败清零）
- [x] 变更文件 ruff 无新增错误
- [x] 根级 commitlint 验证通过
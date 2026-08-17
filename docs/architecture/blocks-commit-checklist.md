# 组合层提交清单 · Blocks Commit Checklist

> 日期：2026-08-18 · 关联：[blocks.md](./blocks.md)（设计）· [ADR-012](../adr/012-composition-layer.md)（决策记录，Accepted）

## 目的

把组合层（P0–P4）以**可独立验证的提交**落地到 `main`，并与工作区里
**既有的未提交改动（frontend/runtime/tests 文件）严格隔离**。

## ✅ 已全部落地（2026-08-18 · 12 个提交在 main）

| # | commit | 内容 |
|---|---|---|
| C1 | `30eb459e` | BlockManifest + ServiceBus 拓扑加载 |
| C2 | `1c56edca` | memory + model-router 内核服务 |
| C3 | `e5efdccc` | PluginHub 消费 ServiceBus |
| C4 | `c338af52` | 参考 arm 加载真实 memory 技能族 |
| C5 | `7dd8e9ee` | 声明式 workflow DSL |
| C6 | `445a756b` | PanelManifest registry + usePanels + PanelHost |
| C7 | `e53eb6c8` | 设计文档 + ADR-012 + 本清单 |
| C8 | `9fe4af8e` | P4 · manifest schema 版本化 |
| C9 | `0fe6ed4a` | P4 · 事件信封版本化 |
| C10 | `c1fc1e89` | P3 · intelligence 页经 PanelHost 渲染面板 |
| C11 | `35801811` | docs · P3 页面接入 |
| C12 | `34dd5c40` | P4 · BlockWatcher 开发期热重载 |

**执行铁律（当时遵守）**：每次只 `git add <显式路径>`、每组先跑验证、按依赖方向排序。
下方 C1–C7 为原计划（已执行），C8–C12 为后续追加。

---

## C1 · 组合层核心（P0）

```bash
git add runtime/platform/process/block_manifest.py \
        runtime/platform/process/service_bus.py \
        tests/test_block_manifest.py tests/test_service_bus.py
.venv/bin/python -m pytest tests/test_block_manifest.py tests/test_service_bus.py -q   # 25 passed
```
消息：`feat(composition): BlockManifest schema + ServiceBus with topological load order`

## C2 · 内核服务（P1b）

```bash
git add runtime/memory/provider.py \
        runtime/platform/models/selector.py runtime/sensing/model_router/selector.py \
        runtime/platform/models/__init__.py runtime/sensing/model_router/__init__.py \
        runtime/platform/process/composition.py \
        runtime/platform/ui/_app_routers_extra.py \
        tests/test_memory_provider.py tests/test_composition.py tests/test_model_selector.py
.venv/bin/python -m pytest tests/test_memory_provider.py tests/test_composition.py tests/test_model_selector.py -q  # 20 passed
```
消息：`feat(composition): memory + model-router kernel services (MemoryProvider / ModelSelector)`

## C3 · PluginHub 集成（P1）

```bash
git add runtime/platform/plugins/plugin_hub.py runtime/platform/plugins/plugin_base.py \
        tests/test_plugin_hub_service_bus.py
.venv/bin/python -m pytest tests/test_plugin_hub_service_bus.py tests/test_plugin_hub_coverage.py tests/test_plugin_registry.py tests/test_plugin_lifecycle.py -q  # 6 + 存量全绿
```
消息：`feat(composition): PluginHub consumes ServiceBus (topo load / blocked / unload unbind)`

## C4 · 执行臂抽取（P2）

```bash
git add runtime/execution/suckers/_memory_skills_handlers.py \
        demos/arms/ \
        tests/test_arm_plugin.py
.venv/bin/python -m pytest tests/test_arm_plugin.py tests/test_history_skill.py -q  # 4 + 19 passed
```
消息：`feat(composition): reference arm loads the real memory skill family (idempotent register)`

## C5 · 声明式编排 DSL（P2）

```bash
git add runtime/execution/parallel_agents/workflow_dsl.py \
        runtime/execution/parallel_agents/__init__.py \
        demos/workflows/ \
        tests/test_workflow_dsl.py
.venv/bin/python -m pytest tests/test_workflow_dsl.py tests/test_parallel_agents.py -q  # 9 + 44 passed
```
消息：`feat(orchestration): declarative workflow DSL (YAML -> ParallelAgentOrchestrator)`

## C6 · 前端面板契约层（P3）

```bash
git add frontend/src/core/panels/
cd frontend && pnpm vitest run src/core/panels && pnpm typecheck && pnpm exec eslint src/core/panels --ext .ts,.tsx
# 14 passed · typecheck ok · eslint 0 warnings
```
消息：`feat(ui): PanelManifest registry + usePanels + PanelHost (register-and-render)`

## C7 · 文档与 ADR

```bash
git add docs/architecture/blocks.md docs/architecture/blocks-commit-checklist.md \
        docs/adr/012-composition-layer.md \
        mkdocs.yml docs/adr/README.md docs/architecture/README.md
```
消息：`docs(architecture): composition layer design (Accepted ADR-012) + commit checklist`

---

## 不包含（用户既有未提交工作）

以下 **不属于本清单**，提交时不要 `git add`：
- 首轮审计的 ~80 个已修改文件（`frontend/src/**`、`runtime/core/cerebrum/**`、
  `runtime/execution/subagents/**`、`runtime/sensing/gateway/**`、大量 `tests/test_*` 等）；
- 其他未跟踪文件（`AUDIT_REPORT_2026-08-17.md`、`DEEP_EVALUATION_2026-08-17.md`、
  `frontend/src/components/workspace/evolution-dashboard/**`、`frontend/tests/`、
  `runtime/execution/suckers/role_delegation_guidance.py` 等）。

如需一次性查看差异：`git diff --stat HEAD`（应只显示用户既有改动 + 本清单已跟踪文件的改动）。

## 验证汇总（落地后）

| 组 | 测试 | 状态 |
|---|---|---|
| C1 | 25 | ✅ 已执行 |
| C2 | 20 | ✅ 已执行 |
| C3 | 6 + 存量插件 | ✅ 已执行 |
| C4 | 4 + 19 | ✅ 已执行 |
| C5 | 9 + 44 | ✅ 已执行 |
| C6 | 14 + typecheck + eslint | ✅ 已执行 |
| C8/C9 | 6（event protocol）+ 3（schema） | ✅ 已执行 |
| C10 | 15（panels + intelligence 页） | ✅ 已执行 |
| C12 | 6（BlockWatcher） | ✅ 已执行 |
| 全量回归 | 后端 12526+ passed · 前端 2035 passed | ✅ 零确定性回归 |

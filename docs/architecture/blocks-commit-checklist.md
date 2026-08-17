# 组合层提交清单 · Blocks Commit Checklist

> 日期：2026-08-18 · 关联：[blocks.md](./blocks.md)（设计）· [ADR-012](../adr/012-composition-layer.md)（决策记录，Accepted）

## 目的

把组合层（P0–P3）分 **7 个可独立验证的提交** 落地，并与工作区里
**既有的未提交改动（约 80 个 frontend/runtime/tests 文件）严格隔离**。

## 铁律

- 每次只 `git add <显式路径>`，**绝不 `git add -A` / `git add .`**；
- 每个提交组先跑验证命令，全绿再提交；
- 建议按 C1 → C7 顺序提交（依赖方向：核心 → 服务 → 集成 → 抽取 → DSL → 前端 → 文档）。

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

## 验证汇总

| 组 | 测试 | 状态 |
|---|---|---|
| C1 | 25 | ✅ 本清单编制时全绿 |
| C2 | 20 | ✅ |
| C3 | 6 + 存量插件 | ✅ |
| C4 | 4 + 19 | ✅ |
| C5 | 9 + 44 | ✅ |
| C6 | 14 + typecheck + eslint | ✅ |

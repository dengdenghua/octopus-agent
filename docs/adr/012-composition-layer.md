# ADR-012 · 组合层（BlockManifest + ServiceBus）

Status: Accepted | Date: 2026-08-18

## Context

Octopus 已经拥有多个"块"体系——`agents/`（Agent 定义）、`skills/public/`
（技能包）、`runtime/platform/plugins/`（插件，三层渐进注册）、
`runtime/platform/extensions.py`（环境变量扩展钩子）。但这些块之间只有
**注册式**卡扣：插件把技能/通道/路由注册进 registry，却**不声明依赖谁、
提供谁、卸载顺序、靠什么通信**。结果：

- 插件之间只能靠"约定"耦合，无法组合、替换、热重载；
- 新功能（evolution 面板、递归委托）只能硬塞进大页面/大循环；
- 与 DSH（DeepSeek Harness）对比，差距集中在"可组合性"：DSH 的 Cordis
  提供依赖注入 + 生命周期 + 热重载，而我们的 `ServiceProvider` 只是
  无类型 string 键定位器（`dsh-advantages-absorption-status.md` 评估：
  插件系统 70% 吸收、Cordis 0%）。

## Decision

建立**组合层**：以 `BlockManifest`（块的"身份证 + 卡扣"）声明
`provides / consumes / emits / subscribes / capabilities / sandbox`，
以 `ServiceBus`（类型化服务总线）负责**依赖校验、拓扑加载、逆序卸载、
事件耦合**。设计全文见 `docs/architecture/blocks.md`。

### 已落地（P0 + P1 + P1b + P2 全部 + P3 契约层）

- `runtime/platform/process/block_manifest.py` — `BlockManifest` Pydantic
  模型（含 `from_yaml` / `from_plugin_manifest` 兼容入口）；
- `runtime/platform/process/service_bus.py` — `ServiceBus` + 纯函数
  `resolve_load_order`（Kahn 拓扑排序，缺依赖 → blocked 不崩溃，
  循环 → `BlockDependencyCycleError`）；
- `runtime/platform/plugins/plugin_hub.py` — `PluginHub(service_bus=…)`
  可选注入：`load_all` 按拓扑序加载、blocked 插件跳过不致命、
  `unload` 从总线解绑、`ModuleContext.service_bus` 供插件运行时消费；
  未注入时行为与旧版完全一致（`plugin_base.ModuleContext` 增补 `service_bus`）；
- `runtime/memory/provider.py` + `runtime/platform/process/composition.py` —
  `MemoryProvider` 协议（store/recall/forget/reflect/health）+ `JournalMemoryProvider`
  默认实现；`build_default_service_bus(journal=…)` 绑定 `journal`/`memory` 服务；
  `mount_routers_b` 在应用侧接线 `app.state.service_bus`（P1b）；
- `runtime/platform/models/selector.py` + `runtime/sensing/model_router/selector.py` —
  `ModelSelector` 协议（接口放 `platform.models` 遵循 `ModelRouter` 同款分层）+
  `DefaultModelSelector` 默认实现（显式覆盖 > 角色声明 > cheap > 默认）；
  `build_default_service_bus` 注册为 `model_router` 服务（P1b）；
- `demos/arms/memory_arm/` — 参考 arm 插件（P2）：`kind: arm` +
  提供技能 + 消费 `memory`，端到端加载**真实 432 行 memory 技能族**；
  `resolve_load_order` 支持内核服务种子（`available_services`），消费
  kernel 服务的块不再被误判 blocked；
- `runtime/execution/suckers/_memory_skills_handlers.py` — 12 处注册改为
  幂等 `_register(registry, skill)`（`replace=True`），默认装配与 arm 插件
  重复加载同一技能族不再崩溃（「默认仍注册、可被插件覆盖」兼容层）；
- `runtime/execution/parallel_agents/workflow_dsl.py` + `demos/workflows/
  research-report.yaml` — 声明式 workflow DSL（P2）：YAML 解析/校验/
  映射/调度，关闭 DSH「缺少声明式 DSL」差距；
- `runtime/platform/process/block_manifest.py` — `schema_version` 字段 + 兼容校验（P4，镜像 journal 模式）；
- `runtime/platform/process/eventbus.py` — `DomainEvent.protocol_version`（`CURRENT_EVENT_PROTOCOL_VERSION=1`，事件信封版本化 + 新版本拒绝，P4）；
- `runtime/platform/process/block_watcher.py` — 开发期热重载（P4）：新增/变更/移除块自动加载/重载/卸载；
- `frontend/src/app/workspace/intelligence/page.tsx` — 「面板」tab 经 `PanelHost` 渲染注册面板（P3 真实接入）；
- `frontend/src/core/panels/` — PanelManifest 契约层 + 消费原语（P3）：
  类型 + 注册表（重复 id 拒绝 / zone/permission 过滤 / 版本号订阅）+
  `usePanels`/`usePanel`（`useSyncExternalStore`）+ `PanelHost`（按 zone
  渲染注册面板）+ 参考面板 `workbench.system-status`；14 vitest +
  typecheck + eslint 全绿；
- `tests/test_block_manifest.py` + `tests/test_service_bus.py` +
  `tests/test_plugin_hub_service_bus.py` + `tests/test_memory_provider.py` +
  `tests/test_composition.py` + `tests/test_model_selector.py` +
  `tests/test_arm_plugin.py` + `tests/test_workflow_dsl.py` — 64 个测试（含 arm 端到端加载 + workflow DSL +
  真实 `JSONLJournal` 持久化往返 + `ModelSelector` 优先级链）。

### 约束

1. **块之间只通过总线通信**（服务调用 + 事件），禁止跨块直接 import 实现；
2. 内核（cerebrum 循环 + registry + event bus + safety）是唯一被所有块
   依赖的稳定层；
3. 不迁移 Cordis（TypeScript 框架），只借鉴理念；保留市场 + 信任 +
   仿生架构护城河。

## Alternatives considered

- **直接迁移 Cordis**：拒绝。TypeScript 框架，Python 无直接对应，且
  `dsh-advantages-absorption-status.md` P3 已有"借鉴理念、不走 Cordis 风格"
  的结论。
- **只升级 `ServiceProvider` 不加 manifest**：拒绝。没有声明式
  provides/consumes，就无法做拓扑加载与可替换性校验，"卡扣"仍然缺失。
- **推倒重写插件体系**：拒绝。现有 `PluginManifest`（`requires/provides/
  subscribes`）词汇已存在，`from_plugin_manifest` 保证向后兼容，旧插件零改动。

## Consequences

- 新块 = 目录 + `block.yaml` + 注册，不再改内核；
- 后续 Phase：执行臂按技能族抽 `arm` 插件、前端 `PanelManifest`、
  网关事件 schema 版本化、开发期热重载（见 `docs/architecture/blocks.md` §7）；
- 本 ADR 已于 2026-08-18 转 Accepted；`docs/architecture/blocks.md`
  状态已同步为 Accepted（P0/P1/P1b/P2 已落地并经一致性审计）。

# 对标 Codex 的桌面端 / ReAct 稳定性 / 前端性能优化

## Why

架构对比显示 octopus-agent 在 **ReAct 循环、Item 模型、安全治理** 上已显著领先 Codex，但在 **桌面端原生集成、长任务不中断、前端构建体积** 三处存在可落地的增量提升空间。本 spec 聚焦这三处最小可行的优化，不追求 Codex 完整复刻，只解决真实痛点。

## What Changes

### Delta 1 · 桌面端原生集成（对标 Codex 桌面壳）
- 配置 electron-builder 打包（`packaging/desktop/build.yml`），让 `frontend/electron/main.cjs` 从"仅开发模式"升级为可产出 `.dmg/.exe/.AppImage`
- 打包模式下由 Electron 主进程 spawn 后端 Python 子进程，并实现 `backend.restart`（当前为 stub 返回 `{ok:false}`）
- 接入 electron-updater 自动更新，打通 `app:update-downloaded` 事件（当前"无触发源"）
- 前置条件：`installContextMenu` / `backend.restart` 两个 stub 由诚实降级改为真实实现（`frontend/electron/README.md` 已标注）

### Delta 2 · ReAct 长任务稳定性（对标 Codex 收敛调优）
- 普通模式强制收敛 `max_tokens` 从 400 提升到 2000（`react_terminal.py:146`），避免迭代用尽时收敛回答过短
- 预算默认值放宽：`max_tokens` 50000→100000、`max_usd` 0.50→1.00（`config.example.yaml`），降低复杂任务触发 `budget_near_limit` 暂停率
- 将模型迭代超时（默认 120s）与收敛 token 上限提升为可配置项，并在 `config.example.yaml` 文档化

### Delta 3 · 前端构建体积与加载性能
- 建立构建体积基线：用 `vite build --report`（或 `rollup-plugin-visualizer`）输出当前各 chunk 体积，对比 Codex 的 14.9MB 主 bundle 痛点
- 实现路由级懒加载（`React.lazy`）覆盖重量级页面（mermaid/xyflow/three 等重型依赖只在对应路由加载）
- 将覆盖率 ratchet 阈值按当前实际值小幅上抬（`vite.config.ts` test.coverage.thresholds），持续推进

## Impact
- Affected specs: 桌面端（electron）、ReAct 收敛（cerebrum）、预算（budget）、前端构建（vite）
- Affected code:
  - `frontend/electron/main.cjs`、`frontend/electron/README.md`、`packaging/desktop/`
  - `runtime/core/cerebrum/react_terminal.py`、`runtime/core/cerebrum/react_model_deadlines.py`
  - `config.example.yaml`、`runtime/platform/budget/`
  - `frontend/vite.config.ts`、`frontend/src/router.tsx`、重量级页面

## ADDED Requirements

### Requirement: 桌面端可打包分发
系统 SHALL 支持通过 electron-builder 产出当前平台安装包，且打包模式下后端由主进程托管。

#### Scenario: 打包模式启动
- **WHEN** 用户运行 `pnpm electron:build:mac`（or win/linux）
- **THEN** 产出对应平台安装包，启动后主进程 spawn 后端并加载本地 `dist/index.html`

#### Scenario: 后端重启
- **WHEN** 用户触发 `backend.restart`
- **THEN** 打包模式下主进程重启后端子进程并返回 `{ok:true}`

### Requirement: ReAct 长任务不中断
系统 SHALL 在迭代用尽或预算逼近时提供足够长的收敛输出，避免"看似被中断"的短回答。

#### Scenario: 迭代用尽强制收敛
- **WHEN** 普通模式 `max_iterations` 用尽且无 final answer
- **THEN** 强制收敛调用使用 ≥2000 token 上限，产出完整结论而非截断

#### Scenario: 预算逼近
- **WHEN** 复杂任务 token/成本逼近预算
- **THEN** 默认预算应足以完成典型长报告，避免频繁触发 `budget_near_limit` 暂停

### Requirement: 前端构建体积可观测
系统 SHALL 提供构建体积分析，并对重型依赖路由做懒加载。

#### Scenario: 序列化
- **WHEN** 运行构建体积分析
- **THEN** 输出各 chunk 体积报告，定位超过合理阈值的 chunk

#### Scenario: 重型路由懒加载
- **WHEN** 用户访问非重量级页面
- **THEN** 不加载 mermaid/xyflow/three 等重型依赖，仅在对应路由加载

## MODIFIED Requirements

### Requirement: 现有桌面 stub 补全
`frontend/electron/main.cjs` 的 `backend.restart` 与 `installContextMenu` 由诚实降级改为真实实现（或明确标注为平台受限并保留降级）。

## REMOVED Requirements
无
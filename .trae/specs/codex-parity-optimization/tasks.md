# Tasks

## Delta 1 · 桌面端原生集成（对标 Codex 桌面壳）

- [x] Task 1.1: 配置 electron-builder 打包
  - [x] 创建 `packaging/desktop/build.yml`（electron-builder 配置：appId、productName、mac dmg / win nsis / linux AppImage、files 含 dist + 后端）
  - [x] 在 `frontend/package.json` 增加 `electron:build:mac/win/linux` 脚本（指向 electron-builder）
  - [x] 验证打包产物可启动并加载本地 `dist/index.html`

- [x] Task 1.2: 打包模式后端托管 + `backend.restart` 真实实现
  - [x] 在 `frontend/electron/main.cjs` 增加打包模式检测（`app.isPackaged`）
  - [x] 打包模式下主进程 spawn 后端 Python 子进程（`python -m runtime serve`），记录 child 引用
  - [x] 将 `backend.restart` 从 stub 改为：kill 旧子进程 → respawn → 返回 `{ok:true}`
  - [x] dev 模式保持现有行为（后端外部运行，返回 `{ok:false, reason}`）

- [x] Task 1.3: 接入 electron-updater 自动更新
  - [x] 在 `frontend/electron/main.cjs` 接入 `electron-updater` 的 `autoUpdater`
  - [x] 配置更新源（GitHub Releases / 自托管），注册 `check-for-update` 与 `update-downloaded`
  - [x] 打通 `app:update-downloaded` 事件（当前 README 标注"无触发源"）

- [x] Task 1.4: 桌面 stub 补全/标注
  - [x] `installContextMenu`：Windows 平台实现真实右键菜单，非 Windows 保留诚实降级
  - [x] 更新 `frontend/electron/README.md` 的"实现状态"表，反映上述变更

## Delta 2 · ReAct 长任务稳定性（对标 Codex 收敛调优）

- [x] Task 2.1: 普通模式强制收敛 max_tokens 提升
  - [x] 修改 `runtime/core/cerebrum/react_terminal.py:146`：普通模式 `max_tokens` 从 400 → 2000
  - [x] 保留 research/swarm 模式 5000 不变
  - [x] 补充/更新单测验证收敛调用带上限值

- [x] Task 2.2: 预算默认值放宽
  - [x] 修改 `config.example.yaml`：`budget.max_tokens` 50000→100000、`max_usd` 0.50→1.00
  - [x] 同步检查 `runtime/platform/budget/` 默认值（如 `pause_control.py` 中的默认），保持一致
  - [x] 确认 `max_latency_ms` 是否需相应放宽（600000 现为 10 分钟）

- [x] Task 2.3: 模型迭代超时 + 收敛 token 可配置化
  - [x] 将 `react_model_deadlines.py` 的 `_model_iteration_timeout_s`（默认 120s）改为可配置项
  - [x] 将收敛 `max_tokens` 提升为可配置项
  - [x] 在 `config.example.yaml` 文档化这两个配置项

## Delta 3 · 前端构建体积与加载性能

- [x] Task 3.1: 建立构建体积基线
  - [x] 引入 `rollup-plugin-visualizer`（或 `vite build --report`）
  - [x] 运行一次构建，输出各 chunk 体积报告，标出超过 `chunkSizeWarningLimit(1400)` 的 chunk
  - [x] 记录基线数值到 `docs/` 或 spec 的 checklist（用于对比 Codex 14.9MB 主 bundle）

- [x] Task 3.2: 路由级懒加载（重型依赖仅按需加载）
  - [x] 分析 `frontend/src/router.tsx` 找出重量级路由（mermaid / xyflow / three 相关页面）
  - [x] 用 `React.lazy` + `Suspense` 包裹这些路由
  - [x] 验证非重量级页面不再加载对应重型 chunk

- [x] Task 3.3: 覆盖率 ratchet 上抬
  - [x] 跑一次 `pnpm test:coverage` 获取当前实际覆盖率
  - [x] 在 `vite.config.ts` test.coverage.thresholds 小幅上抬（lines/branches/functions/statements）

# Task Dependencies
- Task 1.2 依赖 Task 1.1（打包配置就绪后才能验证打包模式后端托管）
- Task 1.3 依赖 Task 1.1（更新需打包产物）
- Task 2.1 / 2.2 / 2.3 相互独立，可并行；2.3 依赖 2.1 的收敛 token 逻辑
- Task 3.2 / 3.1 相互独立，可并行；3.3 独立
- Delta 1 / Delta 2 / Delta 3 三个 Delta 相互独立，可并行处理
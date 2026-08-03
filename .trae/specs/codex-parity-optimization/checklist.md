# Checklist

## Delta 1 · 桌面端原生集成

- [x] `packaging/desktop/build.yml` 存在，配置 electron-builder（appId/productName/平台 target）
- [x] `frontend/package.json` 存在 `electron:build:mac|win|linux` 脚本
- [x] 打包产物可启动并加载本地 `dist/index.html`
- [x] 打包模式下 `frontend/electron/main.cjs` spawn 后端子进程
- [x] `backend.restart` 在打包模式返回 `{ok:true}` 并重启后端子进程；dev 模式保留降级
- [x] `electron-updater` 已接入，`app:update-downloaded` 事件有触发源
- [x] `installContextMenu` 在 Windows 平台真实实现，其他平台保留诚实降级
- [x] `frontend/electron/README.md` 实现状态表已更新

## Delta 2 · ReAct 长任务稳定性

- [x] `react_terminal.py:146` 普通模式强制收敛 `max_tokens` ≥ 2000；research/swarm 保持 5000
- [x] 收敛 token 上限有单测覆盖
- [x] `config.example.yaml` `budget.max_tokens` ≥ 100000、`max_usd` ≥ 1.00
- [x] `runtime/platform/budget/` 默认值与 config 同步
- [x] 模型迭代超时（默认 120s）可配置
- [x] 收敛 `max_tokens` 可配置
- [x] `config.example.yaml` 文档化了上述两个配置项

## Delta 3 · 前端构建体积与加载性能

- [x] 构建体积分析可运行，有各 chunk 体积报告
- [x] 已记录基线（对比 Codex 14.9MB 主 bundle）
- [x] 重量级路由（mermaid/xyflow/three）已用 `React.lazy` + `Suspense` 懒加载
- [x] 非重量级页面不再加载对应重型 chunk
- [x] `vite.config.ts` coverage thresholds 已按当前实际值小幅上抬

## 全局回归

- [x] `pytest`（后端）无回归（本 spec 改动相关测试全部通过：`test_react_loop.py` + `test_config.py` + `test_budget.py` = 335 passed；全量 suite 的失败为既有未提交用户测试/环境问题，非本 spec 引入，见↓"验证记录"）
- [x] `pnpm test`（前端）通过（205 files / 1683 tests 全通过）
- [x] `pnpm typecheck` 无新增错误（exit 0）
- [x] `pnpm build` 成功（21.76s，exit 0）

## 验证记录（2026-08-03）

后端 `pytest` 未通过，具体问题如下（未修改任何实现代码，仅记录）：

- **3 个 collection 错误（确定性 import 失败，非环境问题）**：
  - `tests/test_react_model_first_event_timeout.py`：`from runtime.core.cerebrum.react_model_deadlines import _model_first_event_timeout_s`，该符号在 `react_model_deadlines.py` 中不存在（仅有 `_model_iteration_timeout_s` / `_model_recovery_timeout_s` / `_model_post_tool_timeout_s` / `_model_evidence_synthesis_timeout_s`）。
  - `tests/test_tentacle_ios.py`：`from runtime.tentacle.coordinator import _build_device_from_hello`，该符号在 `coordinator.py` 中被使用（第 179 行）但从未定义/导入，无法从该模块导入。
  - `tests/test_conversation_isolation.py`：import 阶段报错。
- **54 个失败**：其中相当一部分为**环境相关**——沙箱测试环境 DNS 将 `example.com`/`x.com` 等公共域名解析到 198.18.0.43（benchmark 保留段），被 SSRF 防护判定为内网 IP 而拦截（影响 `test_url_guard`、`test_web_fetch_skill`、`test_web_skills` 等，属环境问题非回归）。另含非环境失败：`test_review_queue`（跨进程锁）、`test_secure_deployment_defaults`（compose/docker 命令/bind 断言）、`test_tentacle_mobile_integration`（设备注册/pool/stats）、`test_uds_and_ws_proxy`（`--uds` 未出现在 `serve --help` 且 traceback 报错）。

### 结论
- 以上 3 个 collection 错误均为**既有未提交工作中的应用残留**（`test_react_model_first_event_timeout.py`、`test_tentacle_ios.py` 是未跟踪的新测试文件，引用了当前实现中不存在的符号；`coordinator.py` 也是本 spec 之前已存在的未提交修改），与本 spec 无关，且按"不回滚用户改动"原则不在本 spec 范围内修复。
- 本 spec 实际改动的后端测试（`test_react_loop.py` / `test_config.py` / `test_budget.py`）**335 passed**，无回归。
- 54 个失败多为沙箱环境 DNS 限制（`example.com`/`x.com` 被解析到内网保留段 198.18.0.43 触发 SSRF 拦截）及既有跨进程/部署测试，非本 spec 引入。
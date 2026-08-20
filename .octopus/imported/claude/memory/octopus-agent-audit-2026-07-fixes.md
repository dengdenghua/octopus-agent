---
name: octopus-agent-audit-2026-07-fixes
description: 2026-07-03 六代理深度审计后落地的7项修复+MCP OAuth接线；含journal redactor破坏JSON的真根因
metadata:
  type: project
  originSessionId: 9df8e53d-89ea-443c-83a6-4e5e696bb0f6
---

2026-07-03 对 octopus-agent 跑了 6 个并行子代理深度审计（安全/WIP diff/前端/架构/测试/网关），然后逐条实证核实 + 全部落地修复，最后又追加接通了 MCP OAuth。全程零回归（全量 pytest 从 22 failed 收敛到 18 failed 且清单固定，前端 1046/1046 全绿）。

**两个安全 HIGH（已修，各带回归测试证明修复前会失败）**：
1. `runtime/sensing/gateway/control_sessions_router.py` 挂载时完全没鉴权（`app.py` 用裸 `create_control_sessions_router()`，而兄弟 router 都传了 `require_auth`）。修法：镜像 `browser_router.py` 的 `_auth_dep` 模式。owner 越权（takeover 可覆盖任意 owner_id）未修——store 里 `owner_id` 只是调用方自报的标签，不是认证身份，加真授权是产品决策不是 bug 修复。
2. 兼容网关 `/v1/chat/completions`(deep) 走 `stack.runtime.run()` 从不绑定 `session_scope`，导致 executor.py 的 scope/sandbox/plan-mode 写拦截+审批+任务清单闸门（全部键在 `current_session() is not None`）在这条路径上全是空转。修法：`_run_chat`（同步）和 `_stream_chat` 的 worker 线程（流式，**必须在线程内部绑**，因为 contextvars 不会自动跨 `threading.Thread` 传播）都包一层 `session_scope`，默认 chat 模式把写限制在该 turn 的 thread-artifact 根目录。

**journal 破坏 JSON 的真根因（不是我最初怀疑的锁重构 `efd586cf1`）**：`runtime/memory/journal/journal.py` 的 `write()` 对**已序列化的整行 JSON 文本**跑 Redactor，`phone` 正则本质是"9-15个连续数字不需要分隔符"，会命中 `latency_ms` 等浮点数值里的数字串，把 `[REDACTED:phone]` 文本拼进 JSON 数值字面量——语法坏了之后 `read_all()` 对整份文件全部解析失败，静默丢光事件。修法：redact 后校验仍是合法 JSON，不合法就回退未脱敏行（电话号码永远不会是裸 JSON 数字，破坏语法的匹配必是误报）。这个 bug 是 baseline-import 就有的老 bug，只是最近 latency 数值的精度/长度变化后才稳定复现——**这类"redact 已序列化文本"的模式要警惕**，`structured_logging.py` 的 `StructuredFormatter` 是对照组（redact 字段值后再 `json.dumps`，天然安全）。

**测试回归簇不是一个根因**：22→20个失败里，只有 `test_reflex_integration`+`test_resume` 是 journal 那个 bug 导致，其余全是互不相关的独立问题（`test_rules_persistence` 是 `StaticPlanner.apply_rewrite_proposals` 被 `gene_locks blocked`；`test_react_guards_surface` 是误报"Inline assigned credential"；`test_workflow_applier`/`test_production_readiness_gate`/`test_realtime_cerebrum` 各自独立）——都未 triage，留给以后。**教训**：一批测试同时失败不代表同一个根因，逐个 stash 对照才知道。

**CI 全绿闸门**：29 处新增 silent `except: pass` 全部加了 justification 注释（唯一真 bug 是 `tool_spec_builder.py` 的 `filter_allowed_names` 失败时 fail-open 成全量工具列表，改成 fail-closed 到空列表+日志）；god-file 基线批量收割（45 条，2 条指向已删除文件的条目一起清掉）；orphan-module 基线原本 13 条，`oauth_discovery.py` 被我接线后自动从基线里摘掉验证是真接通了。**`ruff format --check` 故意没动**——1134 个文件要重排，但 `pyproject.toml` 的 `ruff>=0.5.0,<1.0` 是宽范围，CI 用 `pip install` 不吃 `uv.lock`，本地 0.15.12 跟 CI 实际解析到的版本可能不一致，见 [[octopus-agent-generated-artifact-drift]]。

**P2 修复**：octopus-mix 代理阶段加了总时长上限（`concurrent.futures.wait(timeout=)` 而非逐个 `fut.result(timeout=)`循环——后者在最坏情况下等待时间是 N×timeout 不是 timeout，因为每次循环重新等一次即使所有线程已经在并发跑）+ 单代理 token 上限（`OCTOPUS_MIX_PROPOSER_MAX_TOKENS`，草稿不需要 131K 全量上限）。前端 `computer/page.tsx` 的 `getStopped` 闭包过期 bug 用 ref+effect 修（镜像 `copilot-panel.tsx` 已验证过的模式）；`use-pc-screen-stream.ts` 的 frameCount/fps 节流到 ~1Hz 但**首帧必须立即 flush**（否则"等待信号"遮罩会在画面已经渲染出来后还多挡 1 秒）。

**MCP OAuth 接线**（用户在审计报告基础上追加要求）：`runtime/adapters/mcp_client/oauth.py`(PKCE+token store) 和 `oauth_discovery.py`(RFC9728/8414/7591发现+DCR) 两个模块写好测试齐全但零生产调用方。新增 `runtime/sensing/gateway/mcp_router.py` 三个端点（`POST /api/mcp/oauth/authorize`、`GET /api/mcp/oauth/callback`、`GET /api/mcp/oauth/status` + `DELETE`），自动继承该 router 已有的 `_auth_dep` 鉴权；`HttpMCPClient._transport()`（client.py）在每次连接时从 `bearer_for_server(config.name)` 取 token 注入 `Authorization` 头，显式 header 优先于自动 OAuth。CSRF 靠 `MCPOAuthStore.pop_pending()` 的一次性 state 白嫖，没另造。16 个新测试全过。**加密静态存储仍是 TODO**（oauth.py 自己的文档已承认，只是 chmod 0600，不是我这轮该扩大的范围）。

**方法论确认**（跟 [[octopus-agent-audit-verification-lesson]] 一致）：全程每个修复都先复现失败→定位真根因→写回归测试证明"修复前失败、修复后通过"→跑受影响测试套件→git stash 对照排除"是不是我的改动导致"。后台长跑 pytest 的 harness 输出会截断（只保留尾部一截），**必须重定向到真实文件再 grep**，不能信 tail 截断后的 FAILED 计数——这个坑在本轮踩了两次。

**同日追加：两个 god-file 拆分**（用户在审计报告基础上追加要求，逐个真实执行验证，非纸面计划）：
1. `runtime/safety/evolution/kimi_swarm_load_test.py`(1960→776 行)拆成 6 个模块（types/failure_taxonomy/proof_lookup/resume_planner/load_run + 瘦身后的主文件）。先画完整调用图才敢动——实际耦合比"清晰边界"描述的深得多（几乎每层都调别的层）。踩到并修复了一个自证陷阱：`kimi_swarm_certification.py`/`agent_benchmark.py` 靠 grep 本文件字面内容找 required_terms，拆完直接用 `compute_kimi_swarm_certification()`/`compute_agent_benchmark()` 跑了一遍确认 0 条 missing（不只信测试绿）。顺手还补了 MCP OAuth callback 鉴权豁免的回归测试缺口（之前那轮漏测，靠一次 flaky 复测意外发现）。
2. `runtime/sensing/gateway/computer_router.py`(1994→948 行)拆成 8 个模块。这个文件形状跟 kimi_swarm 完全不同——是一个大工厂函数里 ~50 个嵌套闭包共享 5 个可变状态（pending/lease/activity/screenshot_root/control_sessions），不能简单剪切粘贴。设计成 `ComputerRouterState` dataclass 显式传参（不是按状态分子路由器），过程中发现 lease 和 activity/replay 两组之间有真实循环依赖（lease 报错需要 replay_evidence，activity 记录默认值需要 lease 状态），拆出一个中立的 `computer_replay_evidence.py` 打破环。改写主文件时留了 3 处毛边（错误的 import 来源、一行死代码占位、2 处不必要的局部 import）——靠 `.venv/bin/python -c "from ... import create_computer_router; create_computer_router()"` 直接构造 router 验证 14 条路由完整不少，才发现并修掉。

两次都验证了：`god_file_check --strict` 拆前拆后对照、`orphan_module_check`（拆分中间态会正确报"4个新文件没人 import"，接线完就自动消失）、受影响测试套件全绿、全量 pytest 全跑（每次都独立确认无新增失败，不只信局部套件）、`docs/auto`+`openapi-snapshot` 因新增/变动文件过期后重新生成。`tools/lint/god_files_baseline.txt` 从 45 条降到 43 条（company/api/router.py 等 2 条指向已删除文件的条目一起收割）。`computer_router.py` 后续还有 17 条低优先级文件 + `react_loop.py`（明确不碰，见 [[octopus-agent-react-loop-refactor]]）留作后续。

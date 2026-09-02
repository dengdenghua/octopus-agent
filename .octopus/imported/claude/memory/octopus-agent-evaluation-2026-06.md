---
name: octopus-agent-evaluation-2026-06
description: "2026-06-26 全项目审计评价(55代理/对抗核查),总分6.0,P0四项安全缺口已定位未修"
metadata: 
  node_type: memory
  type: project
  originSessionId: ef9bb8cb-4174-4afe-936b-cf2605f6370f
---

2026-06-26 跑了一次 55 代理工作流(map 8 子系统 → 7 维度评分 → 每条发现独立对抗核查 → 综合)，总分 6.0/10（单用户本地 7+，多租户/对外不及格）。报告在 `tmp/octopus-eval-report.md`。维度分：架构5.5/代码质量6.5/正确性6.0/安全5.0/测试7.0/成熟度6.5/文档运维6.0。

**进度（2026-06-26，全部 commit 在 main;2026-07-03 main 已整体 push 至 origin）：3/4 P0 已修。**
- SEC-1 = `f814b2e6`：新增 `runtime/safety/auth/arg_guard.py::strip_model_controlled_overrides()`，`execute_step` 顶部剥离 `allow_sensitive`/`allow_private`（execute_step 是 text/native/graph/gateway 统一闸；native 经 `_parse_action` 回流同一 dispatch）。`tests/test_arg_guard_sec1.py` 6 绿 + 既有 95 绿。
- SEC-2 = `77c1aaaa`：`ephemeral_runner._execute_tool_in_subagent` 改走 `gate_inner_dispatch`（capability+immunity(需引擎绑定)+check_file_write）+ 就地 pop 特权参数（call 是 frozen `llm.ToolCall`，**只能就地改 input dict 不能重绑属性**——我第一版重绑炸了 5 个测试）。注：ephemeral 在新线程，executor 的 contextvar 引擎不传播→完整 TrustEngine 异常/可信源校验仍需把引擎穿进 runner factory(后续)。`tests/test_ephemeral_runner_sec2.py` + 既有 31 绿。
- C2 = `674f97c3`：`react_loop` 重试加 `_retry_safe_affinity` 闸（仅幂等可重试；写/编辑/exec/delete/dangerous 不重试；affinity 未知 fail-closed）。`tests/test_react_loop_c2_retry.py` + 既有 react_loop 143 绿。
- **SEC-3 仍未修——卡在 WIP 依赖**：`_LEGACY_CONTROL_PLANE_PREFIXES`/`_install_legacy_control_plane_auth` 整套控制面鉴权中间件**只在未提交 WIP 里、HEAD 上根本没有**。审计跑在工作树(HEAD+WIP)才看到"缺 reflex/gene-locks 前缀"。所以 SEC-3 没法独立提进 main：要么进 WIP(那套中间件落地时一起)、要么在 HEAD 上另造鉴权(会跟 WIP 撞)。等用户定。
**分支动作：** `refactor/react-loop-pure-helpers`(领先 main 3 提交) FF 进 main；149+52 WIP 与 stash 全程未动。
**隔离法（工作树坏：WIP `arms/__init__.py` import 不存在的 `make_enterprise_arm`→pytest 收集全 ImportError）：** 改 WIP 文件时 checkout-clean→重打我的 hunk→`git diff --cached` 验零 WIP 泄漏→提交→`cp` 还原；验证一律在 `git worktree add HEAD` + `git diff --cached | git -C wt apply` 的干净树里跑。clean 文件(ephemeral_runner/react_loop/safety.auth)直接编辑提交，仅验证需 worktree。

**核查为真的 P0（上线前必关，均经追链确认、缺动态验证）：**
- SEC-1 ✅已修 `executor.py:656` + `react_native.py:133-139`：模型自带 `allow_sensitive`/`allow_private` 参数因 `additionalProperties:True` 仍合法，native tool-use 原样 `handler(**args)` → 可读 `~/.ssh/id_rsa`、SSRF 内网。
- SEC-2 (high) `ephemeral_runner.py:978`：唯一真实子代理 runner 直接 `skill.handler`，**不调 `check_file_write`/`immunity.check`**，与主 executor(285/629) 策略不一致 → 可写 `.env`/`id_rsa`/跑禁用工具。修复走 `gate_inner_dispatch`。
- SEC-3 (high) `reflex_admin_router.py` + `app.py:1039`：`/api/reflex/*`、`/api/gene-locks/*` 裸挂载无鉴权、不在 `_LEGACY_CONTROL_PLANE_PREFIXES` → auto-pr 推送/panic 改安全门。
- C2 (high) `react_loop.py:2347`：`not tool_ok` 自动重试用相同 action 重跑非幂等 write/exec → 双重副作用。

**P1 进度（commit 均在 main，未 push）：**
- 路由 model 透传 ✅ = `d8a23578`：`validated.model` → `_drive_react` 方法(realtime_cerebrum,clean)+模块函数(realtime_react_stream,WIP→隔离)→`stream_react_loop(model=)`。`tests/test_routing_model_threading_p1.py` + test_turn_complexity 51 绿。
- SEC-5 redactor 接线 ✅ = `a8ecf75a`：`build_from_config`(clean)+`AppState`(state.py,WIP→隔离) 的 `JSONLJournal` 加 `redactor=Redactor()`(默认开)。`tests/test_journal_redactor_wiring_sec5.py` + 既有 16 绿。
- **SEC-4 也卡 WIP（同 SEC-3）**：HEAD config_router `router = APIRouter(tags=["config"])` 裸挂，**整套 `_auth_dep`/`_resolve_actor`/require_auth 是 WIP**(HEAD 0 引用)。审计看 HEAD+WIP 才说"只 _auth_dep 没 admin"。admin 角色机制 HEAD 有(`Identity.roles` + system_router/meta_router/channels_router 都 `"admin" in roles`)，但 SEC-4 修复必须叠在 WIP 的 config 鉴权上→等 WIP 落地后给 path-denylist POST/DELETE 加 `_require_admin`(抄 system_router:73)。
- **SSE `?token=` 可在 HEAD 修(不卡 WIP)**：`web_auth._resolve_actor` 只读 Authorization 头(HEAD 0 处读 query_params)；EventSource 不能设头→deploy 模式 SSE 全 401。修复=后端 `_resolve_actor` 读 `?token=` query(web_auth.py clean)+前端 7 处 `new EventSource` 加 `?token=`(5 文件全 clean:background/observability api.ts、observability/page.tsx、run-review-panel、quest-panel)。跨栈+前端无法在此流程构建验证+设计选择(URL token vs cookie)→已向用户 checkpoint。
- C1 ✅ = `88ac10e5`：react_loop deny/reject 分支抽 `_record_rejected_step`(append step + assistant action + observation 进 messages)，消除活锁到 max_iter + 审计盲点。`tests/test_react_loop_c1_reject.py` + 既有 143 绿。
- C4 ✅ 两部分：`d91c7e69` resume-request CAS(confirm `WHERE status='pending'`、consume `WHERE status!='consumed'` + rowcount，输家得 None，trace_store WIP→隔离) + `efd586cf` journal 轮转跨进程锁(新 `_interprocess_lock` flock 稳定 `<path>.lock` sidecar，`with self._lock, self._interprocess_lock():` 一行包住 append+rotate；因 rotate 的 tmp.replace 换 inode，per-fd flock 救不了)。测试 test_resume_request_toctou_c4(4)+test_journal_rotation_lock_c4(3)+既有全绿。
- SSE ✅ = `29cadbe3`：后端 `web_auth._resolve_actor` 无 header 时读 `?token=` query(header 优先)；前端新增 `core/auth/api.ts::authedEventSource()`，7 处 EventSource 全改走它(observability/background api.ts、observability/page.tsx、run-review-panel、quest-panel)。后端 `tests/test_sse_query_token_auth.py` 5 绿 + 前端 `tsc --noEmit` 0 错(前端文件本就 clean,直接提交)。
**续(同会话后段)：** 用户把整坨 WIP 提交为 `8ef476b7`(503 文件)→ 树干净、控制面鉴权层上 HEAD → **解锁并完成 SEC-3/SEC-4**：
- SEC-3 ✅ `3f2aee1e`：`app.py` 的 `_LEGACY_CONTROL_PLANE_PREFIXES` 加 `/api/reflex`+`/api/gene-locks`。`tests/test_control_plane_auth_sec3.py`(7 绿,含 `_install_legacy_control_plane_auth` 中间件 401 集成测)。
- SEC-4 ✅ `ddbc5ed6`：`config_router` 加 `_resolve_identity`+`_require_admin`(抄 system_router),挂 path-denylist POST/DELETE。`tests/test_config_admin_gate_sec4.py`(4 绿)。树干净后直接 live tree 验证。
- docsops-1 ✅ `f830da5b`：GOLDEN_PATH/getting-started 安装行 `.[dev]`→`.[dev,serve,web]`(实证:dev extra 只 pytest/ruff,fastapi/uvicorn 在 serve extra;`.[dev]` 会让 `runtime ui`/status 挂)。
- docsops-2 ✅ `9a3c3dad`：`module-map.md` 12 行映射指向不存在目录(项目改用功能名)。已重映可核实的(ganglia→graph_runtime、spinal_cord→nerves/reflex、beak→tool_engine、siphon→gateway、immunity→auth、regeneration→recovery)、列真实 sensing 同级(model_router/normalize/server)、删无包退役名(eyes/skin/mantle/genome/ink/camouflage)、修 nav/diagram 路径(含 platform/scope→process/scope);全部 runtime/ 路径已验证存在 + doc_claims_check 绿。
**剩余：** audit.ultracode 总线(设计已定,待"能跑 app 里边建边验",真实编排需 LLM key+前端);MAT-1(stub 默认=产品决策);CQ-1(executor god-method=大重构);ARCH-6(naming.md/six-modules 同 docsops-2 类、更广、需 owner 意图)。
**预算驱动 max_spawns ✅ 已做 = `e80f0d24`**(用户先说暂缓、后又说"优化"→做了)。`delegation_budget.max_spawns_for_token_budget(token)`(token→spawns,floor2/ceiling256)+ `delegation_skills._resolve_max_spawns`(纯函数,可测)+ `_run_orchestration` 只从**可信 `session.metadata["orchestration_token_budget"]`** 读预算(绝不从模型 call args,否则模型自抬上限=SEC-1 类洞);新增 `_ORCH_MAX_SPAWNS_BUDGET_CEILING=256`。**默认 n*rounds/48 字节不变**,仅 opt-in 高预算路径放大。`tests/test_orchestration_budget_scaling.py`(9)+ 既有 delegation/orchestration 137 绿。**audit.ultracode 完整总线(drive+dispatch+streaming)仍暂缓**(需 app+LLM key 验);这次只落了它的预算地基。设计全记录,别主动推剩余总线;用户提再做。多代理限额实证:`call_agent_parallel` 并发 `min(len,8)`(delegation_skills:1119)、orchestration `max_spawns` 封顶 48(`_ORCH_MAX_SPAWNS_CEILING`:1599)、临时委派每轮 5(delegation_budget:28)、SwarmRuntime 默认 4 workers(swarm/runtime.py:159)。Codex 在打磨 loops+task_supervisor(租约/takeover/跨进程锁,质量高、72 测绿;executor +340 经核与 SEC-1/SEC-2 门禁顺序无冲突——strip 仍第一、check_file_write/immunity 仍在 handler 前、loop 走 run_react_loop→execute_step 不旁路)。
**⚠ 有并发 Claude/Codex 会话在编辑本仓 + 本记忆文件**(SSE `29cadbe3`、make_enterprise_arm 修复、本文件部分条目均出自它);改共享文件/记忆前先核当前状态,别 clobber。

**已驳回(勿再报)：** ARCH-1/2/3(无加载期真循环;`import_direction_check.py` 存在;sensing 非纯 ingress)；CQ-1 圈复杂度数字高估 1.5-2x(god-method 结构问题为真)；SEC-6 config auth(local_auth.enabled=false)。

**真优势：** safety 执行叶子零向上依赖;`react_guards.py` 注册表式 ~40 guard;自带架构适应度函数 LINT-01..10 + ~20 ratchet CI;红队测试(`test_react_loop.py:3531` 投毒网页拦 exec_shell)。

延续 [[octopus-agent-integration-debt-audit]] 与 [[octopus-agent-audit-verification-lesson]]；测试假信心见 [[octopus-agent-subagent-model-routing]]。

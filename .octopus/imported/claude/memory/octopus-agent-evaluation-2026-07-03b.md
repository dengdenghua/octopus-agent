---
name: octopus-agent-evaluation-2026-07-03b
description: 2026-07-03 第二次深度评价(7.4/B+)+新增确证的控制会话 IDOR + CI/ruff 根因
metadata: 
  node_type: memory
  type: project
  originSessionId: debfcffe-05ba-4119-9603-e57bf3a207db
---

2026-07-03 又做了一次深度评价(29 代理工作流 + 我本人 4 处独立追链核查)。总分 **7.4/B+**,轨迹 6.0(6月)→7.0(7月)→7.4。规模:~290K 行 Python(871 文件)、731 前端、580 测试文件;main 领先 origin **122** 未推。全量 pytest = **17 failed / 8437 passed**,与既有基线同簇(production_readiness_gate×4/workflow_applier×3/organizations×3 等陈旧契约漂移),**非回归**。

**我独立追链确证的 4 条(其中 #1 是自动化 sweep 漏掉的、最高价值)**:
1. **控制会话 BOLA/IDOR(P1)** — `runtime/sensing/gateway/control_sessions_router.py`:`_auth_dep` 只在 router 依赖里 `_resolve_actor` **校验存在即丢弃**,handler 不拿 actor;`list_sessions` 只按 `surface/limit` 过滤**无 owner 过滤**;`GET /{id}`、`/evidence/{id}/detail`、`/actions`、`/takeover`、`/stop` 全按 id 取、**不比对 session.owner_id vs 调用者**。→ auth-on 多租户下任意登录用户可枚举+读取+驱动+接管他人实时桌控会话与截图证据。**正是记忆里 anthropic_compat 已用 `_owned_or_404` 修过的 S3 类,在新 router 复现**。工作流 synthesis 把"补了 auth"当亮点,**误判为无此洞**(印证 [[octopus-agent-audit-verification-lesson]] — 必须实证交叉核查)。修法:handler 注入 actor + `_owned_or_404` + list 按 owner 过滤。
2. **computer lease 仅"协作锁"非安全边界(P2)→ 已修** — `computer_lease.py` 的 `owner_id` 与 `/lease/release` 的 `force` 都来自 **body 非 actor** → 任意调用者可冒名 claim / force-steal 他人租约。**2026-07-18 补全**:独立分支 `fix/computer-lease-actor-binding`(`f7a6933f7`)加 `_effective_owner(body, actor)`——auth-on 时 owner 强绑认证 actor、忽略 body owner_id;dev(actor=None)回退 body 协作行为不变;接进 `/actions/preview`+`/actions/execute`+`/lease/release`(`_auth_dep` 改为 return actor)。22 测绿含"伪造 body owner 被忽略"集成测试。**根因同 IDOR:`_resolve_actor` 返回值算了却丢弃**(与 [[octopus-agent-evaluation-2026-07-09]] 记的终端 WS `_resolve_ws_actor` 丢返回值是同一 bug 类)。分支领先 feat/behavioral-suite-runtime-fixes 1 commit,待 churn 平息后合。
3. **lease 线程池数据竞争(P2)** — computer 端点全是同步 `def`(FastAPI 丢线程池并发跑),`state.lease` 是**无锁 plain dict**,`_claim_lease` check(L77)-then-act(L100)间无原子性 → 并发两线程可同时 claim,击穿"串行化桌控"这一租约存在的唯一目的。
4. **CI 发布可信度(P1,最高杠杆)** — ruff 未 pin(`pyproject.toml:29` `ruff>=0.5.0,<1.0`),CI `pip install` 抓最新(本机 0.15.12 会重排 **689/873** 文件含稳定的 cli.py/react_loop.py = **工具版本漂移非真乱**);`ci.yml` `lint-and-test` job 里 `ruff format --check`(L92)在 pytest(L94)/production-readiness(L97)/golden-path(L112)**之前**且 fail-fast → 格式检查一红,这几步**静默跳过**。**注**:`pytest-cross-platform` 是独立 job(无 needs)仍跑 fast-subset,所以不是"测试完全不跑",而是**带覆盖率的全量+就绪门跳过**。记忆里"exception_audit 挡住 pytest"的说法**已过时**:本机 `exception_audit --strict` 现 exit=0 通过;真凶是 ruff format 门。

**校准点(别误报)**:`runtime/memory/control_sessions.py`(741~996 行 ControlSessionStore)是**优秀工程**:SQLite 参数化查询、RLock、TTL 过期、size cap、内容寻址 blob + SHA256 + `relative_to(blob_dir)` 防穿越(L705)、WAL、游标分页。缺陷全在 HTTP router 边界(上面 #1-#3),**不在 store**。computer_router 1994 行拆 5 模块(computer_lease/control_session/diagnostics/replay_evidence/router_state)是**教科书级 god-file 拆分**,每模块 docstring 解释循环依赖边界,state 收进 `ComputerRouterState` dataclass。这 5 个文件当时**未提交**(untracked)+带 3 个 F401 未用导入。

**剩余 P2/P3**:4 个 >2500 行巨файл(react_loop.py 3440/delegation_skills.py 3378/react_guards.py 2632/app.py 2540)被 god-file ratchet grandfather,应拿 computer_router 拆分模板处理;122 未推积压;文档死链;17 条陈旧契约测试该 xfail 标注或修契约。取代不了 [[octopus-agent-evaluation-2026-07]],是其后续增量。

**当轮(同日晚)按用户指示落地了 2/3 修复(工作树未提交)**:
1. **IDOR 修复(完成+回归测试绿)**:`control_sessions.py` 加 `creator_actor` 列(schema+idempotent `_migrate_locked` ALTER)、`upsert_session(creator_actor=)`(DO UPDATE 不含它=创建时设一次、后续保留)、`list_sessions(creator_actor=)` 按 actor 过滤;`control_sessions_router.py` `_auth_dep` 改返回 actor、加 `_owned_or_404`(404 非 403)+ `_require_owned`,接进全部 12 个 per-session 端点(get/actions/evidence/detail/pause/resume/stop/takeover/replay/timeline/events SSE/create-takeover);测试 `test_control_sessions_object_level_ownership_isolates_actors`(alice/bob 两租户,bob 全 404+list count=0,alice 通)。**残留**:computer_router 经 `_ensure_control_session` 建的会话 creator_actor=None(owner_id 是 project 概念非 auth 主体,故意不误 gate),属更小面。
2. **lease 竞争(完成+回归测试绿)**:`ComputerRouterState` 加 `lease_lock: RLock`(compare/repr=False);`computer_lease.py` 的 `_claim_lease/_release_lease/_cleanup_lease/_public_lease` 全体 `with state.lease_lock:`(RLock 可重入解决嵌套);测试 `test_lease_claim_is_race_free_under_concurrency`(16 线程 barrier×40 轮,恰 1 winner)。**注**:lease owner 仍来自 body(product 协调概念,router 级 require_auth 才是边界),没盲改 owner 流。
3. **CI/ruff pin —— 并发会话已修(非我)**:同日另一活跃 Claude 会话在 CI 硬化战役里连提 `b50fd4891`(count_tests pin/playwright importorskip/httpx2)、`ee8f0602f`(style: ruff format 全仓)、`107f60aa4`(ratchet 全绿)。**关键**:pyproject `ruff` 从 `>=0.5.0,<1.0` 收紧到 **`>=0.15.12,<0.16`** + 全树 reformat → 我那条"ruff 未 pin→format 门不可复现→pytest 被跳"根因**已闭环**(现全树 1474 文件 format-clean、ruff check 全过、门变绿 pytest 能跑)。可选 nit:exact `==0.15.12` 比 `<0.16` 更稳。

**结局与踩坑(重要)**:三项全部落地并 **push 到 origin/main**。但并发会话的 `ee8f0602f "style: ruff format (mechanical, no logic changes)"` 用宽 `git add` **吞并了我未提交的 lease 修复(computer_lease.py/computer_router_state.py/test_computer_router.py)和 IDOR 测试(test_control_sessions.py)** —— 那个"无逻辑改动"提交其实含我的逻辑,**标签错**。我的 IDOR store+router 逻辑单独进了干净的 `f0d9559c6`(恰 2 文件,我按显式 pathspec 提交没 add -A)。**没去 rewrite 历史修标签**(共享且已 push,动它会砸并发会话)。教训:多会话共享工作树时,未提交改动随时会被对方 `git add -A` 卷走——要么尽快按显式路径自提交,要么接受被并入。29+68 测试对 clean committed 树全绿,功能完整无丢失。

---
name: octopus-agent-evaluation-2026-07-09
description: 2026-07-09 六维评估;新确证终端两洞(IDOR+env透传secrets)/octopus-lint名实不符/无mypy门禁/model-drop真伪
metadata: 
  node_type: memory
  type: project
  originSessionId: 7515e253-50ff-4836-a231-b704e6f32e06
---

2026-07-09 六代理并行评估(agent能力/运行框架/架构/工程质量/前端diff/安全),我逐条实证核实。总分约 7.8/10(B+~A-)。

**新确证需修项(我亲自追链路核实):**
- **终端 WS 跨租户 IDOR [高]**:`runtime/sensing/gateway/terminal_router.py:408` `_resolve_ws_actor(ws)` 认证了但**返回值丢弃**;`ShellSession.__init__`(:70-95)无 owner 字段;session_id=前端 `agent-workbench-${threadId}`(可枚举/协作可共享)。auth-on 多租户下用户B知道A的threadId即可劫持A的shell(读输出+注入命令)。同类于已修的 control-session IDOR。修法:ShellSession 记首个 actor_id,`terminal_ws` 比对不符则 4403。
- **终端 shell 透传全量 os.environ 含 secrets [中高]**:`terminal_router.py:116` `env={**os.environ,...}`,未 scrub。与非沙箱 exec 路径(已修,`_scrub_unconfined_env`)平行但**不同 surface**(人驱动交互终端)。auth-on 下任一用户开 terminal 读服务端 ANTHROPIC_API_KEY 等。修法:scrub 或 admin-only RBAC。**这两条同文件,一次改。**

**model-drop 真伪核实(架构代理报 high,我下调为低中危潜伏)**:`load_agent`(`runtime/execution/agents/loader.py:513`)构造 `Agent(...)` 确实不传 `model=`,`agent.model` 恒 None,profile.jsonc 的 `model` 字段是死字段——**事实成立**。但 `agent.model` 在 `runtime/platform/process/turn_model.py:63-70` 是**最低优先级兜底**(第6档,仅高于None);`stack_runner.py:190-193` 同样兜底。正常 React/OpenAI 客户端总送 `ctx.model_name`,走不到 agent.model,**bug 被掩盖**。仅在"客户端+thread 都不指定 model+agent声明了偏好"时咬人。修复=一行 `model=profile.get("model")`,顺手删 shadow `_memory_tier_paths`(loader.py:245 被 :287 覆盖)。教训再验证:先追链路再定severity。

**工程治理两个真缺口:**
- **无 mypy/pyright 门禁**:全仓无 mypy.ini/pyrightconfig/[tool.mypy],CI 无类型 job,返回类型注解~70%(7006/9976)。29.5万行 Python 最大单点缺口。
- **octopus-lint 名不副实**:`tools/lint/invariant_check.py:394` `ALL_RULES` 只 7 条(缺 LINT-06/07/08,README 标未实现);LINT-01 打 `beak.bite()`/`immunity.check()`——这些生物学包已删=0目标空转;真护栏其实在其它 ratchet(exception_audit/import_direction/god_file 等),不在 octopus-lint。别再当"18道门禁全有效"。与 [[octopus-agent-verification-guards]] 说的 react_guards 硬门控是两码事(那个真有37条)。

**前端未提交 diff 提交阻断**:`agent-workbench-panel.test.tsx:185-192` 断言 `活动轨迹`/`0条过程记录`,但重写后 `RosterComputerPlaceholder` 不再渲染(grep `活动轨迹` 全空);processRecords 只在运行dock分支。测试必挂。附死key(collaboratorPresentDescription/noIndependentProcessActivityDescription 零消费)+死变量 selectedRosterSeatRoleLabel。提交前必修。

**其余确证缓修项**:per-thread map 无界增长(_turn_locks/_compaction_locks/_known_threads + openai 限流 dict 从不清)、WS 无 per-actor 限速(realtime+team_rooms_ws)、terminal reaper 是连接触发式懒回收(断开后 subprocess>30min 存活)、MCP OAuth token 明文落盘+0644→0600 TOCTOU、god-file(react_loop 2768行单函数/3421行文件)、research/chat turn 无确定性门控(能力面最不对称处)、Windows UIA 接地未接线(桌面结构化接地仅 macOS)、browser extension/Electron 两轨未 E2E 验证。

**本轮已落地(2026-07-09,未提交,全门禁绿+48新测试)**:
- P0 终端两洞:`terminal_router.py` 加 `owner_actor` 绑定+`_bind_or_check_owner`(WS 4403/kill 404,auth-off 不强制);shell env 改 `scrub_credential_env`。把 `_scrub_unconfined_env` 从 write_skills 提取到新公共模块 `runtime/safety/env_scrub.py`(write_skills 净减46行)。
- P1 terminal reaper 后台巡检:`_reaper_loop`/`_start_reaper`/`_stop_reaper` 挂 startup/shutdown,60s cadence(此前只连接触发)。
- P1 `_known_threads` 有界化:新建 `runtime/platform/process/bounded_set.py` `BoundedSet`(FIFO cap=8192),替换 cerebrum+echo 两处 set。
- P1 OAuth token TOCTOU:`atomic_write_json/text/bytes` 加 `mode` 参数(fchmod 绕 umask),oauth `_save` 用 `mode=0o600`、删 chmod-after。
- P1 openai 限流 dict 泄漏(anon:ip):`_evict_idle_rate_buckets`(模块级可测)+摊销 gate(≥1s floor,防 flood 下 O(N)/req)。
新测试文件:test_env_scrub/test_bounded_set/test_openai_rate_bucket_eviction + 扩 test_terminal_ws_auth/test_terminal_reaper/test_atomic_io。
- P1 锁 map 泄漏(_turn_locks/_compaction_locks):新建 `runtime/platform/process/keyed_lock.py` `KeyedLock`(引用计数,`async with kl.hold(key)`,refs 归零+未 locked 才删,消除 acquire-window 竞争)。替换 realtime_gateway `_turn_locks`+`_lock_for_thread`、realtime_cerebrum `_compaction_locks`+`_compaction_lock_for`、realtime_thread_ops 两处 `_maybe_compact`/compact。删掉旧 dict+guard+wrapper。7 个并发正确性测试(含共享锁对象/异常清理/1000 key 零残留)+896 realtime 回归绿。
- P1 WS per-actor 限速(用户要求"并发不要卡得太死"):新建 `runtime/platform/process/sliding_window_limiter.py` `SlidingWindowLimiter`(滑窗+摊销自清理桶)。realtime_gateway 加两个宽松 ceiling:连接上限默认 64/actor(`_admit/_release_connection` 计数,4429 close)、turn 速率默认 120/分钟(SERVER_BUSY)。**只对 actor_id 非 None(auth-on)生效,本地单用户完全不限**;0=禁用;不加并发 turn 数限制(不串行化用户并行工作)。5+7 测试。生产 app.py 用默认值(与既有 max_in_flight 一致,未接配置)。

**全 P1 完成(共7修)。结构债已做 2 项(2026-07-09):**
- loader 小赢:删死代码 shadow `_memory_tier_paths`(loader.py:245 被 :287 遮蔽);加 `_resolve_profile_model`(auto→None,处理 string 与 `{provider,name}`)并接进 `Agent(model=...)`。**model-drop 重新定性**:全 19 agent 都是 `{"auto","auto"}`=无偏好,`model=None` 本就正确;naive 传 dict 会污染 stack_runner(dict 当 model id)——所以正确修法是 auto→None,字段现在只在声明具体 model 时激活。13 测试。
- octopus-lint 名实相符:删 2 条死规则 LINT-01(beak/immunity 包已删)、LINT-10(dna/genome 已删)+其专属 helper(_iter_functions/_is_attr_call/_is_method_call/_is_dna_field_assignment);ALL_RULES 现 5 条诚实规则(02/03/04/05/09)。同步更新 README/invariants.md/invariants-cheatsheet.md/CLAUDE.md("LINT-01..10"→实际集)。test_lint 7 测绿。**注意:LINT-03 永久禁生物名,故 01/10 永不会再触发,删除是安全的。**

**结构债又做 2 项(2026-07-10):**
- **loader parse/instantiate 拆分完成**(capability-plane P0 基石):新增 `AgentTemplate` frozen dataclass + `parse_template(agent_dir,shared_dir)→AgentTemplate`(纯,零 runtime)+ `instantiate(template,runtime)→Agent`;`load_agent`=组合两者,行为不变。19 个 agent 实测可零 runtime 解析。6 个拆分测试(test_loader_parse_template)+ 895 广回归绿。
- **react_loop 拆分:核实后决定不拆**(见 [[octopus-agent-react-loop-refactor]])。函数 617–3388 行是**有真实技术理由的有意单体**(闭包状态+交错 yield+resume 耦合),安全的纯 helper 早已抽完,剩余为耦合核心。注释里 "See ADR-008" 是假引用(ADR-008=constitution-profiles)——已改成自足内联理由。**别再把 react_loop 当 god-function 报。**

**结构债又做 1 项(2026-07-10):mypy 增量门禁落地**——评估里最后一项大结构债。
- 新建 `tools/lint/mypy_ratchet.py`(跟既有 ratchet 范式一致):跑 mypy on 热点 3 包(`safety/auth`+`core/cerebrum`+`sensing/gateway`),存量 215 错误冻结在 `tools/lint/mypy_baseline.txt`,只 FAIL 新增。**baseline key=`path\tcode\tmessage` 无行号**(行号漂移会churn),多重集比对(加第二个同错也 trip);修复的错误只提示不 FAIL。
- pyproject 加 `[tool.mypy]`(lenient:ignore_missing_imports/follow_imports=silent/exclude agent_market_sources 那些重名 bundled 脚本)+ dev dep `mypy>=2.1,<2.2`(钉版,baseline 版本敏感)。
- 接线:Makefile `lint-mypy`(纳入 `lint`)+ CI 加 step(主 lint job 已装 .[dev])。4 个逻辑测试(test_mypy_ratchet)。
- **注意**:baseline 里有些是真 bug(realtime_cerebrum.py None.get、completion_router 引用不存在的 get_app_state、url_guard str|int)——将来可逐个修+`--write-baseline` 棘轮下降。widen 范围只需往 `_CHECK_PATHS` 加路径。

**评估里的大结构债现已全部处理:loader 拆分✅ / react_loop 判定不拆✅ / mypy 门禁✅。** 剩下都是可选增量(widen mypy 范围、基于 parse_template 建注册表)。前端 P0-2 测试挂仍在用户未提交 diff 里,没碰。
本会话累计新公共模块 4 个(env_scrub/bounded_set/keyed_lock/sliding_window_limiter),全在 platform/safety 基础层;新测试文件 6 个;所有改动在非脏后端文件,全门禁绿(ruff/import/invariant/god_file/exception_audit),1198 广回归通过。

关联:[[octopus-agent-evaluation-2026-07]] [[octopus-agent-subagent-model-routing]] [[octopus-audit-false-positives]] [[octopus-agent-react-loop-refactor]]

**mypy 门禁深挖(2026-07-11,已提交推送 main):** 用户"全部修"→ 派 triage 子代理逐条读源码+运行时验证 137 个真-bug-候选码,结论**只有 4 个真 bug**,其余 ~133 是 mypy 保守误报。已落地三批:
- (4142ee66a) 修 4 真 bug + 启用 `pydantic.mypy` 插件(pyproject `plugins=["pydantic.mypy"]`,一次消 44 个 populate_by_name 别名误报;插件独立 import 报 ExpandTypeVisitor 错但 mypy 内加载正常、CI 安全、确定性)。4 真 bug:meta_skill_router `MetaEdge.src/.dst`→`from_node/to_node`(500)、channels_router `QQBotChannel(channel_id=)`→`channel_id_param`(TypeError)、completion_router `get_app_state` 从不存在(死端点,穿 stack 修)、realtime_event_bridge `CommandExecutionItem()` 缺必填 command(ValidationError)。
- (19235cfdd) 生成器返回类型:`_dispatch_parallel_actions`/`stream_react_loop` 的 `Iterator`→`Generator[...,R]`(纯注解,连带消 6+ has-type)。
- **baseline 208→150**。**剩余 150 全是确证误报**(union-attr 跨重复 .get() 的 isinstance 收窄 ~60、executor 的 tools_active 门控、动态实例属性、生成器 yield-from)——**别再啃,留 baseline 是正确增量实践**。若要清到 0 只能加噪音 ignore(不推荐)。triage 完整分类见本会话。

**会话续（2026-07-11/12，全提交推送 main，与远端同步）：** 在前述 mypy 基础上继续多方向：
- (bcc222bdb) planner 重推理模型预算：`_PLAN_MAX_TOKENS 1024→4096` + custom model 可配 `timeout`(agnes 180s)。agnes graph-planner 仍慢到不实用(大提示词诱发 180s+ 推理，reasoning_effort 压不下)；**UI 走 stream_react_loop(4096-8000 token)可用，CLI graph-planner 不可用**。
- (f8dc8242b) safety/auth mypy 7→0（真 bug：tool_guardrails `_LOG=logging.getLogger` 忘调用，被第二定义遮蔽）。
- (6b664dee8) team_rooms_ws 反 flood：64KB 包上限 + 30msg/s 滑窗（复用 SlidingWindowLimiter，handler 本地不泄漏）。
- (2b7e91246) MCP OAuth token **opt-in 静态加密**：`OCTOPUS_MCP_TOKEN_KEY`(Fernet)env 存在则加密落盘，否则现状明文；向后兼容+错key优雅空store。keyring 不可用故没做同盘"加密表演"。
- (6b0501f36) mypy 扩到 platform/process 18→1：task_supervisor `list()` 方法遮蔽内建 list（13错，模块级别名修）；**真契约 bug** state.py handler 首参该 `StateEntry|None`（delete 传 None）；streaming `suppress(元组)`（实测运行时正常,惯用性修）；service_provider `require->T`→`Any`。
- (da3301cd3) adapters channel：基类一处 `_bare_client: Any = None` 声明清掉 184→47（`_bare_client` 未在 __init__ 声明→首个 `=None` 被 mypy 当字面类型）；teams TypedDict 补键；google_chat RSA 收窄。**adapters 不加 ratchet**（剩 47 是 TypedDict-vs-开放metadata 设计失配）。
- (4b6164f93) **research/chat 引用接地 guard**（首个纯能力改进，补评估点名的最大能力缺口）：非code+跑了fetch工具+markdown链接+URL不在任何观察→nudge（带"移除链接"逃生口防循环）。新 "research" guard category。

**mypy 挖矿已耗尽（别重复挖）：** 真 bug 分布 safety/auth(1)+cerebrum/gateway(4)+platform/process(1)=**6 个**；**adapters(0)+execution/suckers(0) 连续 0 真 bug**，逐条核实全是误报(object-typed返回/float→int收窄/关联-None收窄/dict值联合/os.name守卫的WinDLL)。baseline 215→151，覆盖 4 包。再扩包只会给误报加噪音。**剩余候选都非高确定性**：Windows UIA(本机macOS难验)、god-file拆分(delegation/executor安全敏感需盯)、第二个research guard(精度低)。

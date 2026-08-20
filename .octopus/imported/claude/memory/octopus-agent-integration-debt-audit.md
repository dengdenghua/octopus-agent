---
name: octopus-agent-integration-debt-audit
description: 多代理集成债审计结果(51条已核验/12驳回)+ 首批已修(b54bbb8)+ 剩余高价值簇
metadata:
  node_type: memory
  type: project
  originSessionId: 73dba696-f7dc-4ee6-899f-63f46a601f05
---

**来源**:用户"看看那些集成债还能优化的"。用 Workflow 多代理穷尽审计(7 维 finder × Explore + 每条对抗核验 + 完整性 critic + 第二轮 + 综合):**85 代理 / 4M token / 51 条已核验 / 12 条证伪驳回**。本会话纪律:审计结论必先第一手复核(子代理结论本会话失准 6+ 次,见 [[octopus-agent-audit-verification-lesson]])——我亲手复核 top 3,#1/#8 坐实,code_edit_diff"安全洞"被**推翻**(实为 fail-closed 拦截,非逃逸)。

**已修首批(commit `b54bbb8`,Top 高杠杆低风险 S 类,100 测试绿,ruff/import/orphan 棍轮净)**:
1. **SkillForge 每 tick 崩**(live!):`promote_to_public`→`registry.register()` 抛**裸 `ValueError('duplicate skill name')`,而 `run()` except 只接 `(SkillTestsFailed, UnsafeSkillPromotionError)`——后者虽是 ValueError 子类但裸 ValueError 不被子类捕获 → 整 tick 崩。修:promote 前 `if registry.has(cand.name): skip`(止 churn)+ except 改 `(SkillTestsFailed, ValueError)`。`skill_forge.py:~226`。
2. **ephemeral 空 allowlist 越权**:docstring 说"空→仅 ATOMIC_SKILL_NAMES",代码 `:377` 给 `all_specs`=**全 catalog**(含 exec_shell/写盘)。修:抽 `select_tool_specs()` 到 `layers.py`,空→`is_atomic()` 过滤(bb_* 本身 atomic 自动保留)。**附带**:ephemeral_runner.py 1029→1015 行(挪函数顺手缩小这个既存 god-file,HEAD 本就 >1000、god_file_check 非阻断 exit 0)。
3. **BackgroundRunner ContextVar 泄漏**:`_invoke` 没 `copy_context()` 跑 callback → `_current_session/_current_agent_id` 跨复用线程泄漏。修:`contextvars.copy_context().run(task.callback)`。`runner.py:~245`。(注:审计说的 `_on_future_done` 不取 result 是**误报**——`_invoke` 自己 except+log 了,future 不携异常。)
4. scheduler:SkillForge summary 带 `err:{type}` 而非裸 `"err"`(`scheduler.py:324`)。
5. auto_trigger:`applied=0`(judge 全拒)与真失败分开 log(`auto_trigger.py:219`)。**降级为可观测性**——审计自己的 refuted 段证 applied=0 是预期语义,不动进化重试。

**已修第二批(commit `12fedcf`,anthropic_compat 网关簇)**:keystone 是 emitter 无 session 句柄→入站 POST 够不到在飞 turn。修:`SessionState.active_emitter` 钉住在飞 emitter;stub `_SseEmitter`(notify=pass/approval=auto-accept/interrupt=False)换成模块级真 EventEmitter——notify 映射 `item/agentMessage/delta`+`item/reasoning/textDelta`→agent.message/thinking 并 publish(token 流;item 级 tool 事件留 follow-up);request_approval 发 custom_tool_use+requires_action 后阻塞 Future,**超时 fail-closed→decline**(原 stub 静默 auto-accept=安全洞);interrupt 注册表('*' 默认,抗 register_turn 竞争);入站 user.interrupt→request_interrupt、user.tool_confirmation→resolve_approval;turn_completed_event(interrupted=) 真生效。**全经 `realtime_turn_lifecycle._start_turn` 的 `GatewayApprovalProvider(emitter)`/register_turn/notify 路由——已验非死接线**。14 测(10 新)。**残留 follow-up**:`user.custom_tool_result`(需 custom-tool 往返)、item 级 tool 事件流(需 item 模型映射)。

**已修第三批(commit `ba72b33`,"安全档"——二次甄别工作流 56 代理分档 safe9/doc1/behavior12/live1/drop5,每项第一手核实默认保持+测试)**:F1 gepa flag 改走 `feature_flags.is_on`(scheduler.py,默认仍 disabled);F5/F6 `sessions.dated_layout/index_enabled` 真传给 ThreadStateStore(app.py,flag 默认 off/on=store 默认);C1 加 `unbind_thread_session`(session.py,bind 返回 tokens,补全文档承诺的对称 API);C2 `SchedulerConfig.max_workers` 接线 BackgroundRunner(schema+cli_serve,默认 1=原行为);PL3 plugin_hub 加载期 warn manifest.provides 漂移(纯诊断);P3 修说反的注释(HUNK_DELTA 确实发射、OUTPUT_DELTA 才是 reserved);P4 给 MODEL_REROUTED 加 reserved 文档;O1 删死代码 scaffold.py(零引用、被 agents_router.create_agent 取代,git 可恢复)。11 新测;ruff/orphan/import-direction 净。

**第三批的诚实 triage(behavior_change 12 + live 1 + drop 5,逐个第一手复检后 NOT 盲改)**:
- **跳过(加门控=死代码,与 F3 同型)**:F3 federation、F4 strategy_engine —— 子系统仅工厂内实例化、无 runtime 驱动,加 flag gate 是 inert。
- **defer(需产品决策/行为翻转)**:F8 team_cowork(flag 默认 False 但 router 当前无条件挂载=改默认会禁用在用功能)、F2 identity_lock(identity_filter 走 OCTOPUS_IDENTITY_ env 并行机制)、F7 poll_interval 孤儿 flag、O4 EvolveConfig.api_key_env(读它=换 key 行为)、PL2 webhook 校验时机(load 期=可能拒当前能加载的插件)。
- **defer(特性开发)**:P1 ITEM_MCP_TOOL_CALL_PROGRESS、W1 ToolCallGuardrailController 接线(可能触发 halt)。
- **defer(安全需 live 逃逸测试)**:E1 code_edit_diff 加 sandbox_dir(让受限可用)。
- **defer(大重构低收益)**:M1 CLI close_mcp_clients(3 函数多早 return 全包 try/finally;短命进程 OS 已回收)。
- **第一手推翻 verifier 的两项**:O3 openapi snapshot —— verifier 称 runtime.company 已删,但 `runtime/company/` 目录仍在,盲目重生危险;W2 token budget 回调 —— budget_tracker.py:23 已有带 logging 回调的工厂,"从不注册"不准。
- **drop(确认非债)**:P2(reserved 常量本意)、E3 code_mode_unlock(ADR-005 设计)、M3、O5 adaptive predicted_cost(commit 5ae081e 已接、cold-start 本意)、O6 ExtensionBackend(文档已准确标 pending)。

**已补:feature-flag 消费棍轮(commit `72be258`,治本)**:`tools/lint/feature_flag_consumption_check.py` —— AST 抽 feature_flags.py 注册的 flag 名,regex 扫 runtime/ 的 `is_on()/value()` 消费者,注册但无消费=报警;`--strict`/`--write-baseline` 同其他 ratchet;CI 接入 + pytest 镜像不变量。baseline 豁免当前 6 个死 flag(`evolution.auto_trigger/federation/strategy_engine`、`intelligence.poll_interval_sec`、`safety.identity_lock`、`ui.team_cowork`——各需 wire-or-remove 产品决策,defer),棍轮拦**新增**。这治了 F2/F3/F4/F7/F8 那一类的根(止血),而非逐个追。

**已修(2026-06-25,工作树未提交;外部审查触发的控制面鉴权硬化)**:外部审查(用户转述)点名"控制面默认无鉴权"——**实证后基本属实**,非过去那种满屏假阳性,且工作树本就在按其清单修(`_install_legacy_control_plane_auth` 中间件已在 HEAD~。本会话核验:他的后端失败清单多为**陈旧**——openapi/delegation/swarm/team-room/base-prompt 在当前 main 全已绿,只剩 docs/main-path-audit 缺失 + repo 卫生 .bak/.lock 真红)。本会话补全:
- **补 android**:`/api/android` 加入中间件前缀名单(HTTP 5 端点);**WS `/api/android/ws/{id}` 中间件够不到——`@app.middleware("http")` 不见 websocket scope**,故仿 `realtime_gateway._resolve_ws_actor` 在 `android_router` 内自闸(header/subproto/`?token=`,鉴权关时 degrade-open)。`create_android_router` 加 identity/jwt 形参,app.py 接线。
- `mcp serve --host` 默认 `0.0.0.0`→`127.0.0.1`(cli.py:496,opt-in 暴露)。
- **顺手修真 bug**:`DeviceOnlineEvent/OfflineEvent/HeartbeatEvent` 在 `__init__` 里 `self.x=` 给 **frozen 的 `NervesEvent(BaseModel, frozen=True)`** 赋值 → 每次 device register/heartbeat 抛 ValidationError(**android 设备注册一直是坏的**)。改成字段式声明(同 SkillRegistered 兄弟)。教训:NervesEvent 子类别写 `__init__`,声明字段即可。3 个构造点全在 devices/__init__.py 且都 kwargs,隔离。
- docs/main-path-audit.md + docs/engineering-hygiene-plan.md 补齐(core 必需文档,各缺失致 test_docs_encoding 红);`git rm --cached` 10 个 agents/*/agent-core 的 `.bak/.lock`(test_repository_hygiene 红)+ .gitignore 加 `agents/**/*.{lock,bak}`。
- **遗留缺口**:鉴权仍**默认关**(require_ui_auth 仅在配了 molili/local_auth 时为真;裸 serve 无配置=控制面全开,仅 loopback 兜底)。"默认开 / 非 loopback 强制"仍未做。
- test_audit_authz_fixes(含新 android HTTP+WS 用例)/docs_encoding/repository_hygiene/openapi_snapshot 全绿,ruff 净。**并发会话同时在改 test_audit_authz_fixes.py**(印证多会话并行,见 [[octopus-agent-generated-artifact-drift]])。
- **加固副作用 + 修复(2026-06-28)**:`computer_observe/plan/preview/execute` 这组技能(`suckers/computer_api_skills.py`)是**进程内经 loopback HTTP 调自己的 `/api/computer`**(为拿 server 端 preview/token 状态机),鉴权开启后它们没带 token→401。修:`create_app` 鉴权开时铸一个 `service:computer-loop` 身份(随机 api key 进 identity store)+ `set_internal_api_token()` 把 key 注入到 `_call`(发 `Authorization: Bearer`)。**token 只在内存、不走 env**(否则会被 exec_shell 子进程继承泄漏)。鉴权关=不铸、端点本就开放。教训:**任何"进程内技能→本机自有 API"的调用,鉴权开后都会撞同样的 401,用同一招(内存 service token)**。test_computer_loop_auth.py。

**剩余高价值簇(未修,带 file:line,给后续"继续")**:
- **注册≠路由(最普遍根因)**:十余 feature flag 注册却 `os.environ` 直读或不读——`scheduler.py:282`(gepa_auto_apply)、`feature_flags.py:319-451`(identity_lock/federation/strategy_engine/dated_layout/index_enabled/team_cowork…)。`events.py` 多个协议 enum 单边接线(`:104-117`:ITEM_MCP_TOOL_CALL_PROGRESS 后端不发、FILE_CHANGE_*、MODEL_REROUTED;契约测试 `test_realtime_protocol_contract.py:89` 只验前端 handler 不验后端发射)。
- **告警≠强制**:`tool_guardrails.py:114` ToolCallGuardrailController 全套决策但从不实例化(孤儿);`budget_tracker.py:203-238` 阈值回调从不注册。
- **ephemeral 绕过 executor(写域不对称)**:`resolve_write_scope` 仅 executor 路径(`executor.py:477`);`code_mode_unlock` 无运行时启用路径(`scope.py:319`);`code_edit_diff` 缺 sandbox_dir 参数→受限时被 fail-closed 拦(不可用,**非逃逸**,`code_intelligence_skills.py:753`)。
- **MCP 生命周期**:`close_mcp_clients()` 仅 cli_serve 调,CLI/测试/demo 漏(`builder.py:55`,`cli_run.py:263`);conftest 不清 MCP 致测试套累积泄漏。
- **孤儿/漂移**:`AdaptiveImmunity.predicted_cost` 从不填充(永远 cold_start 0.5)。(已解决/勿再报:scaffold.py 已删=batch3;`android_router` 已注册+HTTP/WS 鉴权=2026-06-25;OpenAPI snapshot 已重生且绿。)

**审计驳回的(打假,别再当债)**:浏览器三轨 adapter(有意分阶段,implementation-status 标注)、Constitution 默认关(文档一致 opt-in)、fs_router 写域(经 `_assert_in_scope` 等价强制)、ruff/pre-commit 错配(pre-commit 根本没装)、编排预算后置超额(数学正确有测)、SkillForge propose 重名(确定性聚类不可能、风险全在 promote=已修 #1)。

相关:[[octopus-agent-improvement-roadmap]]、[[octopus-agent-multiagent-gap]]、[[octopus-agent-audit-verification-lesson]]

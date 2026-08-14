# DeepSeek Harness 移植笔记

**日期**: 2026-08-14
**来源**: [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) (2026-08-13 开源, MIT)
**状态**: 四十五个差距点已落地为可测试代码(1-45 节)

---

## 背景

对比 dsh 与 Octopus-Agent 后确认的三个真实差距:

1. **会话日志推导式架构** — dsh 的不变式是「模型可见即入日志」,模型历史、转录、resume 全部从 append-only 会话日志推导。
2. **OS 级沙箱档位与报告** — dsh 有 read-only / workspace-write / danger-full-access 三档文件效应策略,并如实报告 enforcement 完整度 (full/partial);我们已有 bwrap/Seatbelt 后端但没有档位与报告。
3. **快照测试文化** — dsh 用 keyless snapshot(真实可运行示例的转录)做回归,我们只有 OpenAPI 快照。

---

## 1. 会话日志推导式 (`runtime/memory/journal/derive.py`)

- `derive_model_messages(journal, *, task_id, user_intent, max_steps)` — 从 `StepEvent` 重建 assistant `tool_use` + user `tool_result` 消息序列,工具结果按 anthropic router 的语义扁平化。
- `assert_logged_history_reconstructs(...)` — round-trip 断言:写入日志的 step 能推导回相同的 tool_use id / name / input。
- 用途:审计、resume、测试"模型看到的就是日志记的"。
- 已知限制:user intent 尚无日志事件类型,由调用方传入;后续新增 `user_message` 事件后可完全自洽。

## 2. 沙箱档位与 enforcement (`runtime/safety/sandboxing/sandbox.py`)

- `SandboxPolicy.mode`: `read-only` | `workspace-write` | `danger-full-access`(默认保持 workspace-write,兼容现有调用)。
- `Backend.enforcement(policy) -> "full" | "partial" | "none"`:
  - DirectBackend → none;BubblewrapBackend → full;SeatbeltBackend → partial(读不限制);LandlockBackend → full。
- read-only 档:bwrap 工作区改 `--ro-bind`;Seatbelt 只保留 `/dev/null` 写;Landlock 无写路径。
- **LandlockBackend**(新增,Linux 内核 ≥ 5.13):ctypes 直调 landlock syscalls,deny-by-default 文件效应规则,无需 bwrap/setuid;`OCTOPUS_PROCESS_SANDBOX=landlock` 或 auto 回退链 bwrap → landlock → seatbelt。
- macOS 无法执行 Landlock,transform 逻辑已单测;真实内核执行留待 Linux CI。

## 3. 快照测试基建 (`tests/snapshot_utils.py` + `tests/conftest.py`)

- fixture `snapshot.match(name, data, *, scrub_keys, rebase_map)`:
  - 默认 compare:`tests/snapshots/<nodeid>.<name>.json`,漂移时报告首个差异路径。
  - record:`pytest --snapshot-update` 或 `OCTOPUS_SNAPSHOT=record`。
- 稳定化:ISO 时间戳 / UUID / git SHA → 占位符;耗时与哈希类字段默认剔除;路径前缀可 rebase 为 `{workdir}`。
- 首个示例:`tests/test_snapshot_bugfix_demo.py` — 确定性 bugfix demo 的 journal 转录 + step 序列快照。


---

## 4. DeepSeek 原生 thinking 适配 (`runtime/sensing/model_router/`)

把 dsh 的 DeepSeek 一等公民支持搬进 OpenAI 兼容层,不再走通用降级:

- deepseek profile 标记 `thinking_request_style="deepseek"`,兼容分不再按"非 OpenAI 风格"扣分(94,与 generic 持平;原生风格之前的扣分已移除)。
- **请求归一化**(`openai_compat_providers._normalize_deepseek_thinking`):
  - `reasoning_effort: off` → `thinking: {type: disabled}`(DeepSeek 拒绝 `off` 作为 effort 值,必须显式关闭);
  - `high` / `max` → `thinking: {type: enabled}` + 原值保留;
  - OpenAI 风格 effort(minimal/low/medium/xhigh)自动映射进 DeepSeek 词汇(低档升到 high、xhigh 升到 max),不会 400;
  - 未知 effort 丢弃,显式 thinking 优先。
- **响应侧**(已有,复用):`reasoning_content` 提取 + `<think>` 标签分割 + 流式 reasoning 通道。
- 配置:自定义入口 `thinking_request_style: deepseek` 可选。
- 用法:调用方照常传 `reasoning_effort`(任意风格),DeepSeek 路由自动归一化;想关 thinking 传 `reasoning_effort: off`。

### 默认 effort 选择器(已落地)

- `default_reasoning_effort(model)`(`runtime/platform/models/llm.py`):内置名称模式给
  `deepseek-v4*` / `deepseek-reasoner` 默认 `high`(V4 默认思考),其余模型无默认。
- 配置覆盖:`custom_models.json` 条目可声明 `default_reasoning_effort: off|high|max`,
  `none` 表示禁用注入(连内置默认一起关)。
- 注入点:`/v1/chat/completions` gateway 与 realtime 流式驱动,调用方不传时自动补默认;
  显式传入(包括 `off`)永远优先。
- `off` 保真链路:gateway 放行 `off` → react bootstrap 保留 → openai_router 对 deepseek
  profile 直发 `off`(normalize 转 `thinking:{type:disabled}`),对非 deepseek profile
  不发任何 thinking 字段,避免把 `off` 误映射成 `high` 或 400。

## 5. 工具输出契约 + 四阶段管线 (`runtime/execution/arms/tool_registry.py`)

把 dsh 的 ToolDefinition 契约搬进 MCP 风格注册表,全部字段可选、向后兼容:

- **canonical 输出契约**:`output_schema`(JSON Schema,成功值强制校验,含 required /
  标量类型 / 字符串数组)+ `render(args, value)` 纯投影——宿主始终拿到规范值,
  模型侧通过 `materialize(result, args)` 拿到投影;`get_tool_schema()` 是显式白名单,
  output/timeout/并发/render/finalize 等宿主字段绝不泄漏进模型请求,
  `get_tool_metadata()` 单独暴露宿主元数据。
- **四阶段管线**:`on_pre_execute`(allow/deny/ask 决策链,deny 短路,ask 无审批回调
  转拒绝)→ `on_execute`(around-dispatch wrapper 链 + `timeout_ms` 协作超时,
  `asyncio.wait_for` 取消,超时标记 `` timed out ``)→ `on_post_execute`
  (accept/replace/block,block 短路)→ `on_result`(最终观察)。
  旧 `on_will_call_tool` / `on_did_call_tool` emit 钩子原样保留。
- **最后一英里**:`finalize_content(result)` 每个归一化结果(含失败路径)恰好执行一次,
  返回 `None` 保留原内容。
- **显式并发**:`is_concurrency_safe(args)` 纯分类器,`concurrency_safe_tools()` 供批处理
  层枚举;同步/异步回调都支持(`_maybe_await`)。
- 测试:`tests/test_tool_registry_pipeline.py`(25 用例:白名单、决策链、超时、改写/阻止、
  契约校验、投影、finalize、并发声明、旧钩子兼容)。

## 6. Per-agent Scope 隔离 (`tool_registry.py` + `capability_catalog.py`)

dsh `scope.md` 的「全局层 + scope 层 shadow」语义:

- `register_tool(..., scope=...)` 把工具注册进命名 scope 层;同 scope 重名拒绝,
  与全局同名允许(shadow 是特性)。
- 解析(`_resolve_tool`)/ 可见集(`tool_names_for`)/ schema 白名单
  (`get_tool_schema`/`get_all_tool_schemas`)/ 调用(`call_tool`)/ 投影/并发查询
  全部接受 `scope`;scope 层 shadow 全局层,合并序 = 全局插入序 + scope 层。
- `dispose_scope(scope)` 整层回收,全局不受影响;无 scope 时行为与旧契约完全一致。
- 能力目录接入:`build_capability_catalog(..., tool_scope=...)` 按 agent 过滤工具,
  UI 可按 agent 查看其能力集。
- 测试:scope 6 用例(可见性、shadow、合并序、回收、重名)+ catalog 1 用例。

## 7. Prompt section 有序组装 (`runtime/platform/prompts/registry.py`)

dsh `system-prompt.md` 的组装语义,加在既有文件模板注册表之上(additive):

- `register_section(name, order, text|provider, complete=False, scope=...)`:
  有序注册(约定 -100 身份 / 0 persona / 100-199 工具),`complete` 整段覆盖
  (多个 effective complete 使组装失败, fail loud);provider 按 scope 求值。
- `register_context(...)`:动态运行时上下文,拼接在 sections 之后;
  `suppress_runtime_context(scope=...)` 抑制(全局抑制对所有 scope 生效,scoped 只对本 scope),
  sections 永不被抑制。
- `register_variable(name, provider, scope=...)`:`{{variable}}` 插值,
  未注册或求值为 None → 组装失败;scoped 变量 shadow 全局。
- `assemble(scope=...)`:全局 + scope 层合并(scoped shadow 全局),
  order 升序拼接;`sections(scope=...)` 枚举有效集合。
- 文件模板 API(`get`/`set`/`list`/热重载)完全不动。
- 测试:`tests/test_prompt_registry_assembly.py`(19 用例:排序、complete、变量、
  抑制、scope shadow、兼容性)。

### 尚未覆盖(dsh 有而这里没有)

- "会话标题等用途强制 off"的部署锁——需要调用方 purpose 概念,后续可加。
- executor 主路径(`ToolExecutor.execute_step`)尚未接入 render/materialize 投影——
  先落在注册表层,skill 引擎侧复用 `_validate_output` 语义即可。

## 8. Subagent fail-loud 能力检查 (`subagents/registry.py` + `subagents/bridge.py`)

dsh 的 subagent 声明式能力模型(前端在规划 subagent 时按能力路由,后端对不满足
能力要求的调用立即报错,而不是把子代理放进场后再失败):

- `SubagentDefinition.capabilities: tuple[str, ...]`:frontmatter `capabilities:`
  声明(逗号字符串或 YAML 列表,小写去重保序),`to_wire()` 透出给前端可见。
- `SubagentRegistry.supports(name, capability)` / `capabilities_of(name)`;
  未注册名字 `supports` 返回 False(fail closed)。
- `call_subagent(..., requires_capabilities=...)`:校验时机在 prompt 非空检查之后、
  任何 runner 工作之前——缺能力直接返回
  `{success: False, capability_error: "missing_required_capability", ...}`,
  错误信息带「声明了哪些 / 缺哪些」,不触发 runner、不产生副作用。
- 仅对 registry 后端的定义检查;ephemeral roles(临时角色)不检查,保持低摩擦。
- HTTP 层:`SubagentDispatchRequest.requires_capabilities` 透传到 dispatch 与
  dispatch/stream 两个端点。
- 测试:`tests/test_subagent_capabilities.py`(9 用例:frontmatter 解析/归一化、
  registry 查询、缺能力 fail-loud 不触发 runner、声明能力放行、未注册 agent 跳过、
  无要求 noop)。

## 9. 会话标题原语 (`runtime/memory/threads/session_title.py`)

dsh `ctx.sessionTitle` 的「fallback → provider → user 钉住」阶梯语义:

- `normalize_title()`:空白折叠为单空格,空/纯空白标题抛 `TitleInvalidError`
  (dsh `title-invalid`);`derive_fallback_title()`:首条 human 消息截 60 字
  作为 fallback(与既有 realtime 侧 57+… 约定一致)。
- `SessionTitleService(store)`:状态落在线程记录上
  (`values.title` 展示 + `metadata.title_source/title_pinned/title_provider/
  title_model/title_updated_at` 持久事实),重启不丢,search/sort 可用。
  `get()` 对老线程惰性推导;未记录 source 但已有 `values.title` 的旧数据
  视为 fallback,失败的 refresh 不会把它冲掉。
- `rename(thread_id, title)`:用户改名 = 钉住(source=user, pinned=True),
  自动再生停止调度,直到 `force` refresh。
- `refresh(..., provider=, model=, force=)`:provider 词汇表
  (`register_provider(name, fn, model=)`,重名 fail loud);未指定时取首个
  注册 provider;无 provider 退化为 fallback;provider 返回 None/空/抛异常
  一律保留当前标题(latest-wins + failure keep)。provenance 记录
  provider id + model id(dsh `SessionTitleModelProvenance`)。
- 模型可见面:`register_session_title_variable(registry, store_getter=)`
  把 `{{ session_title }}` 注册进 prompt registry(取 ambient session 的
  thread_id;无环境时渲染 "New chat",绝不让组装失败);在
  `_app_routers_extra.py` 装配 PromptRegistry 后挂载。
- HTTP:`POST /api/threads/{id}/title/rename`(400 空标题 / 404 未知线程)与
  `POST /api/threads/{id}/title/refresh`(body 可选 `provider`/`force`);
  `create_thread_state_router` 新增可选 `session_titles=` 注入。
- 测试:`tests/test_session_title.py`(25 用例:规范化、fallback 推导与截断、
  rename 钉住与持久化、refresh 走 provider/指定 provider/未知 provider、
  failure keep、pin 尊重与 force、provider 注册表、prompt 变量渲染与兜底)
  + `tests/test_thread_state_router.py` 新增 4 个端点用例。

## 10. 活会话 fork (`ThreadStateStore.fork_thread` + 消息级入口)

dsh `sessions.fork` 的「已完成回合前缀」语义:

- 回合边界:每条 human 消息开启一个回合;回合「完成」= 其后存在 assistant
  快照(我们的 store 只在回合完成后写快照,天然对应 dsh 的 `turn/end`)。
- `fork_thread(thread_id, *, at_message_index=, title=)`:锚点落在该回合
  内即包含整个回合;锚点越界/缺省回退到最后已完成回合;锚点命中未完成
  回合抛 `ForkUnavailableError`(HTTP 409 `fork-unavailable`),绝不静默
  裁剪;无任何已完成回合时种子为空(等价 fresh spawn)。
- 子线程继承源 metadata(agent/team/owner/tenant)与源标题,记录血缘
  `metadata.parent_thread_id` + `parent_message_index`(最后包含的源消息
  下标,-1 为空种子);只转移会话历史,不复制 artifacts(dsh:"seed
  transfers conversation history only");消息深拷贝,子线程改动不污染源。
- HTTP:`POST /api/threads/{thread_id}/fork`(body 可选
  `at_message_index`),返回 `{thread_id, seeded_messages}`。
- 前端闭环:消息操作栏新增「从这里派生新会话」按钮
  (`message-list-item.tsx` + `message-list.tsx` 传 `messageIndex`),
  `api.client.ts` 增 `forkThread`/`renameTitle`/`refreshTitle`;
  `useForkThread` hook;`useRenameThread` 从裸 `updateState` 切换到
  `/title/rename`(获得钉住语义,与第 9 节闭环);4 语言 i18n。
- 测试:`tests/test_thread_fork.py`(17 用例:切分边界、空种子、锚点越界
  回退、open 回合 409、血缘/title/深拷贝、持久化重载、端点 200/400/404/409)
  + 前端 vitest 97 过、tsc 干净。

## 11. Subagent 多 provider 后端 (`registry.backend` + `bridge._dispatch_partner`)

dsh 的 subagent provider 词表(spawn / fork / acp / claude-code / codex ...
换 provider 只换传输、执行契约不变):

- `SubagentDefinition.backend`:frontmatter `backend:` 声明(如
  `claude-code` / `codex-cli` / `openclaw` / `trae-cli`,或 `agent_id` 别名
  `local_claude_code`),`to_wire()` 透出。
- `_dispatch_partner()`:registry 后端定义带 backend 时走外部 CLI 驱动
  (`run_local_partner` + `which_command` 解析本机可执行文件),结果映射为
  call_subagent 统一结构 `{success, output, error, backend, command,
  failure_kind, timed_out}`;未知 backend / 可执行文件缺失 → 结构化失败;
  partner 无稳定 headless 调用(`unsupported`)→ 返回 None 回退到进程内
  ephemeral 环(dsh:unsupported provider 降级默认传输)。全程不抛异常。
- 分层修正:本地伙伴 specs(`local_partner_specs.py`)与命令解析
  (`local_partner_discovery.which_command`)下沉到 execution 层,
  sensing.gateway 保留兼容再导出——subagent 派发不再依赖上层网关,
  import-direction ratchet 保持绿色。
- 模型透传:`definition.model` 作为 CLI 模型覆盖参数。
- 测试:`tests/test_subagent_backend.py`(10 用例:frontmatter 解析、
  to_wire、成功/失败/超时映射、agent_id 别名、unsupported 回退、未知
  backend、缺可执行文件、call_subagent 端到端路由)。

## 12. Subagent continuable 会话 (`subagents/sessions.py`)

dsh ``continuable`` 子代理的存储半场:durable child transcript + 继续投喂:

- `SubagentSessionStore`:每会话一个 JSONL 文件(原子写 tmp+rename),
  惰性建目录;目录不可用/不可写自动降级内存,调用方永不因持久化失败
  崩溃;会话 id 为 32 位 hex,非法 id 查询返回 None(路径穿越安全)。
- `create(agent_id, thread_id)` / `get(session_id)` / `append_turn(...)`
  / `transcript_prompt(session)`:transcript 渲染为受限 markdown 前缀
  (6 回合 / ~6KB,大输出截断),供续聊调用注入。
- `call_subagent(..., continue_session_id=)`:已知会话把前文注入 prompt、
  新回合追加同一会话;未知会话在**任何 runner 工作前** fail-loud
  (`session_error: "unknown_session"`);未传时最佳努力创建新会话并把
  `session_id` 附到结果,rejected(未真正运行)的调用不写回合。
- HTTP:`SubagentDispatchRequest.continue_session_id` 透传 dispatch /
  dispatch/stream 两个端点。
- 测试隔离:`tests/conftest.py` 新增 autouse fixture,每个测试私有
  session store(tmp_path),不污染真实 `data/subagent_sessions/`。
- 测试:`tests/test_subagent_sessions.py`(12 用例:create/get 往返、跨实例
  持久化、transcript 边界/截断、非法 id、目录降级、创建+记录回合、续聊
  注入前文、未知会话 fail-loud 不触发 runner)。

### 尚未覆盖(dsh 有而这里没有)

- 子代理**进程内真实回合级 transcript**(我们只记 Q/A 对,不捕获中间
  tool 步骤)——需要动 ephemeral runner 的消息构造,风险高,暂缓。
- 后台 continuable 的 settlement 通知(子代理结束时通知父代理)——需要
  事件桥接层配合,列为后续。

## 13. Tool-result 中段修剪 (`tool_engine/tool_output_pruner.py`)

dsh ``compaction-tool-result-pruner`` 的确定性 head/middle/tail 修剪:
超预算工具结果改写为「有界 head + 固定标记 + 有界 tail」,而不是只留头部。
头部与尾部都保留(错误和最终答案通常在尾部),原始完整内容仍留在
append-only 日志里,剪的只是渲染面。

- `ToolResultPrunePolicy`(frozen dataclass):`threshold_chars=8192 /
  head_chars=4096 / tail_chars=1024`,marker 与 dsh 逐字一致
  `\n\n[... tool result middle pruned ...]\n\n`;构造时校验
  head+marker+tail ≤ threshold(同 dsh resolveConfig)。
- `prune_tool_result_text(text, *, policy=None, ...)`:预算内返回
  **None**(调用方保留原文);超预算返回 head+marker+tail。不变量:
  结果严格小于输入、剪后 ≤ threshold(因此二次 pass 是 no-op)、按
  Unicode code point 计数/切片(emoji 不会被劈开)。
- 接线(默认关,行为零变化):`render_tool_output(..., prune_middle=True,
  prune_policy=)` → `normalize_tool_result` / `normalize_step_tool_result`
  透传同一开关;先中段剪、再走既有 max_chars 头部兜底。
- 测试:`tests/test_tool_output_pruner.py`(11 用例:预算内 no-op、精确
  预算、head+marker+tail 精确构成、严格更小、二次 pass no-op、emoji
  边界、自定义预算、tail=0、非法预算拒绝、render/normalize 开关接线)。

### 尚未覆盖(dsh 有而这里没有)

- 主循环默认开启:`_tool_bridge_exec` 仍用旧的头部截断,prune 开关
  未点亮(避免动主路径的高风险面);接入点已备好,`prune_middle=True`
  一行即可开启,留给性能/上下文预算实测后决定默认值。
- dsh 的 shadow-price 记账(每次修剪在日志里补一条定价事件,消费方可
  无状态扣除)——已落地,见第 22 节。
## 14. 会话标题自动再生接线 (auto-title)

第 9 节的标题原语只有端点与变量,缺 dsh ``ctx.sessionTitle`` 的
「首回合完成后自动生成」闭环。本轮补上触发链路:

- `SessionTitleService.maybe_auto_refresh(thread_id)`:每个线程**至多自动
  尝试一次**——用户钉住(title_source=user)、已 provider 生成、无注册
  provider、或已尝试过(无论成败)一律不动;尝试前先持久化
  `metadata.title_auto_attempted=True`,所以失败的 provider 不会在之后
  每个回合被反复调用,成功/失败都只付一次代价。
- realtime 接线:`CerebrumRuntime(..., session_titles=)` 可选注入;
  `_snapshot_to_thread_store`(每回合结束统一落点,completed/failed/
  interrupted 都走这里)在快照写完后调用 `maybe_auto_refresh`,仍在
  同一个 swallowed try 块内——标题生成失败绝不影响回合生命周期。
- 装配:`thread_state_router.build_auto_title_service(store, model_router=)`
  可测试 helper——有 thread_store + model router 时注册 ``llm`` 标题
  provider(首条 human 消息前 400 字 + 60 token 短标题生成,复用
  projectos 的默认小模型),无 router 返回无 provider 的 service;
  `_app_routers_extra.py` 在构造 realtime runtime 时调用它并注入,
  任何异常都优雅降级为 fallback,装配失败只记 warning。
- 测试:`tests/test_session_title_auto.py`(7 用例:快照触发一次、无
  service 保持旧行为、runtime wrapper 透传、helper 无 store/无 router、
  llm provider 生成与首条消息取材、无 human 消息不调 router)+
  `tests/test_session_title.py` 新增 5 个 maybe_auto_refresh 用例
  (成功一次、钉住尊重、无 provider no-op、失败不重试、显式 refresh
  仍可强制)。

### 尚未覆盖(dsh 有而这里没有)

- 标题 provider 的**优先级/模型选择**(dsh 允许每个 provider 声明自己的
  model 与强度;我们目前只注册一个 ``llm`` provider,模型复用 projectos
  默认值)——有真实多模型配置后可扩展 register_provider 词汇表。
- 回合中途的标题热更新(我们只在回合结束时刷新,回合内标题保持
  fallback)——dsh 是「首回合完成后」语义,当前实现与其一致,无需追平。
## 15. Goal 域 — CAS 守卫的 durable 目标生命周期 (`runtime/memory/goals/`)

dsh ``@deepseek-ai/dsh-goal`` 的完整移植:目标是一等公民的持久化对象,
严格 phase 状态机(``active / paused / blocked / complete``),每一次变更
必须把当前 revision **精确 +1**(compare-and-swap 守卫),回放 append-only
变更日志推导当前投影;stale 或畸形变更在 fold 时 fail-loud,绝不静默。

- `domain.py`:``GoalSnapshot``(id/revision/objective/phase/maxGoalRounds/
  blockedReason,构造时全量校验)、``GoalRef``、``GoalSnapshotChange``/
  ``GoalClearChange``(to_dict 输出 dsh 原样字段,可无损落盘)、``FoldedGoal``;
  错误码与 dsh 一致(GOAL_NOT_FOUND / GOAL_ALREADY_EXISTS /
  GOAL_STALE_REVISION / GOAL_INVALID_OBJECTIVE / GOAL_INVALID_MAX_ROUNDS /
  GOAL_INVALID_BLOCK_REASON / GOAL_INVALID_EDIT / GOAL_INVALID_TRANSITION)。
- `fold.py`(纯函数,零 IO):``decode_goal_change`` 严格解码(精确字段集合、
  schema 版本、updatedAt ≥ createdAt、blockedReason code 必须
  lower-kebab-case、message 必须 normalized);``apply_goal_change`` 实现
  CAS + 转移表——create 仅允许「无当前目标或当前已 complete、revision=1、
  active、0 轮、goal id 不可复用」;edit 不得改 phase/blocked reason;
  pause 仅 active→paused;resume 仅 paused/blocked→active 且
  roundsStarted < maxGoalRounds;block 仅 active→blocked(必带 reason);
  complete 不得重复;clear 留 tombstone 且 clearedAt ≥ updatedAt;
  ``apply_goal_event`` 还校验 goal 来源的 user/message 必须是 active 目标
  当前 revision 的「下一个轮次」且不超 maxGoalRounds;``fold_goal`` 从
  事件序列重建投影。
- `service.py`:``GoalService(journal)`` 提供 create/edit/pause/resume/
  complete/block/clear 动词,每个操作写一条 ``goal_change`` 事件并返回
  新鲜投影;进程内 RLock 串行,跨进程并发冲突由 fold 的 revision 守卫兜底
  (第二个 stale 变更在下一次 fold 时 GOAL_STALE_REVISION)。
- journal 接线:``GoalChangeEvent``(event_type="goal_change",change 原样
  dict)+ ``JournalEventType``/``_EVENT_CLASSES``/``write_goal_change``,
  JSONL 读写无损,重启重放可重建当前目标。
- 测试:`tests/test_goal_domain.py`(31 用例:create 约束、CAS stale/
  skip/wrong-id、转移表全分支、edit 边界、clear tombstone、严格解码、
  blockedReason 校验、轮次记账、全序列 fold 重建、service 端到端、
  JSONL 重放)。
- 与既有目标的映射:本项目的 curriculum goal(``curriculum_goal_decision``
  事件)仍是扁平决策流,没有 revision 生命周期;新 goal 域可作为
  其升级路径——目标从「决策事件」变成「可暂停/阻塞/恢复/完成的
  durable 对象」,后续可把 curriculum 决策接到 ``GoalService`` 上。

### 已收口

- dsh 的 ``goal/changed`` 实时事件广播(scope-filtered)——第 19/23 节
  已落地(``GoalChanged`` 事件桥 + 按 agent/会话过滤的分发)。
- 轮次记账接真实 human 消息事件——第 26 节已落地
  (``user/message`` journal 事件 + fold 轮次校验打通)。
## 16. Subagent report 闭环 (`subagents/sessions.py` + `bridge.py`)

dsh ``tool-subagent-report`` 的「子→父」投递通道:continuable 子代理共享
工作区,但父代理**不会自动收到** transcript/tool output/reasoning,所以
结果必须显式 report(dsh 指引:结束前调用一次 report 携带 self-contained
答案;部分发现改变父下一步时也可提前报;report 不结束子代理回合)。

- `SubagentReport`(content / delivery / timestamp):delivery 对齐 dsh
  ``reportDelivery``——``wakeup``(默认)触发父代理一次新回合,``quiet``
  只加上下文等父下次醒来;空 content 拒绝(dsh 要求 self-contained)。
- `SubagentSessionStore.append_report(session_id, *, content, delivery=)`:
  追加到会话 JSONL 的 ``reports`` 列表(原子写),与 turns 并列;
  ``on_report`` 可选构造回调 = wakeup 通知钩子,异常吞掉不破坏投递。
- 投递指针:``reports_delivered_up_to`` 持久化在会话文件;``pending_reports``
  返回未读 ``(index, report)``;``mark_reports_delivered`` 推进指针(默认
  到最新、可指定 index、绝不倒退);``reports_prompt(session)`` 渲染未读
  report 为受限 markdown 区块(≤4KB),供父代理上下文注入。
- bridge 接线:`call_subagent` 的 durable 会话统一出口把未读 report 附到
  结果(``pending_reports`` 列表 + ``reports_prompt`` 文本)并立即 ack,
  下一次继续调用不再重复看到;老会话文件(无 reports 字段)兼容加载。
- 测试:`tests/test_subagent_report.py`(10 用例:跨实例持久化、空 content
  拒绝、pending/ack 指针、ack 不倒退、prompt 只渲染未读、长内容截断、
  wakeup 回调与异常吞掉、legacy 兼容、bridge 附加与 ack)。

### 尚未覆盖(dsh 有而这里没有)

- 进程内子代理 runner 注册真正的 ``report`` **工具**(子代理回合中主动
  调用,而不是父代理在下次 call 时拉取)——需要动 ephemeral runner 的
  消息构造,风险高,暂缓;当前实现是等价的「拉取 + ack」闭环。
- ``quiet``/``wakeup`` 的调度器(父代理离线时 wakeup 排队)——需要
  事件桥接层配合,列为后续。
## 17. Tool-result pruner 接入主路径 (`core/cerebrum/_react_execution_dispatch.py`)

第 13 点的 pruner 只有词汇表与 `_tool_bridge_exec` 的可选参数,主 loop
(react 回合的工具观察)仍是旧的头部截断。本轮把 pruner 点亮到主路径:

- `_execute_action_via_beak` 的两处渲染(`normalize_step_tool_result` 与
  command_failed 分支的 `normalize_tool_result`)都传
  ``prune_middle=TOOL_RESULT_PRUNE_MIDDLE``:工具输出超 8192 字符时,
  模型看到的从「只留头部 16K」变成「头部 4096 + marker + 尾部 1024」,
  错误与最终答案(通常在尾部)不再丢失;先中段剪、再走 16K 头部兜底。
- 开关:`OCTOPUS_TOOL_PRUNE_MIDDLE=0` 恢复旧头部截断(env 在模块导入时
  读取一次);默认开,对齐 dsh 的 compaction 默认值。
- 测试:`tests/test_react_loop.py` 更新 truncation 用例为 dsh 语义
  (head+marker+tail 精确构成),新增「开关关闭恢复旧行为」用例;主路径
  450 项相关回归全绿。

### 尚未覆盖(dsh 有而这里没有)

- `_tool_bridge_exec`(realtime native tool 路径)仍未默认点亮——接入点
  已备好(`prune_middle=True` 一行),与主路径同一开关可后续统一。
- dsh 的 shadow-price 记账(每次修剪在日志里补定价事件)——已落地,
  见第 22 节。
## 18. Pruner 开关统一 + native tool bridge 点亮

第 17 点只点亮了 react 主路径;realtime native 路径(`_tool_bridge_exec`)
仍是旧头部截断,且两处开关逻辑重复。本轮收口:

- 主开关下沉到 `tool_output_pruner.TOOL_RESULT_PRUNE_ENABLED`(env
  ``OCTOPUS_TOOL_PRUNE_MIDDLE`` 模块导入时读取一次,默认开);
  react 主路径改名引用同一开关(保留本地别名
  ``TOOL_RESULT_PRUNE_MIDDLE``,调用点与测试零改动)。
- `_tool_bridge_exec` 两处渲染(`normalize_step_tool_result` +
  `normalize_tool_result`)点亮 ``prune_middle=TOOL_RESULT_PRUNE_ENABLED``,
  与 react 主路径同一开关:两条模型可见路径行为一致,超 8192 字符的
  工具结果都变成 head+marker+tail。
- 测试:`tests/test_tool_bridge_prune.py`(3 用例:bridge 默认走 pruner
  head+marker+tail、开关关闭恢复头部截断、短输出原样);回归
  react/golden-path/bridge 351 项全绿。

### 尚未覆盖(dsh 有而这里没有)

- shadow-price 记账(每次修剪在日志里补定价事件)——尚无 token meter
  事件桥,列为后续。
## 19. goal/changed 实时广播 (`goals/service.py`)

dsh 的 ``goal/changed`` 事件桥:目标变更提交后广播给订阅者(scope-filtered,
listener 失败被包含)。第 15 点的 GoalService 只有持久化与 fold,缺实时
通知;本轮补上第一块事件桥:

- `GoalChanged`(operation / ref / goal?):clear tombstone 只带 ref 不带
  snapshot,与 dsh 载荷一致;ref 始终携带刚提交的 revision 身份。
- `GoalService.subscribe(callback) -> unsubscribe`:每个成功提交的变更
  (create/edit/pause/resume/complete/block/clear)在 journal 写入后通知
  全部订阅者;退订按身份移除;listener 抛异常被记录并跳过,绝不影响
  写入与其他订阅者(dsh「listener failures are contained」)。
- 测试:`tests/test_goal_domain.py` 新增 2 用例(各操作载荷与 clear
  tombstone 形状、退订生效、失败 listener 隔离)+ 既有 31 用例全绿。

### 尚未覆盖(dsh 有而这里没有)

- scope-filtered 分发(按 agent/会话过滤广播目标)——订阅粒度现在是
  全局的,过滤留给调用方;dsh 的 scope 路由层复杂度高,暂缓。
- journal 订阅桥(跨实例/重启后补发)——当前广播是进程内、仅
  service 实例内;StreamingJournal 的 live fan-out 可后续接上。
## 20. Tool-result spill 落盘取回 (`tool_engine/tool_output_spill.py`)

dsh 的 spill 能力家族(`@deepseek-ai/dsh-spill` / `spill-local` /
`spill-policy`):pruner 只剪中段,中段内容模型永远看不到;spill 把
超限纯文本结果的**全文**存到会话私有 spill 文件,模型看到的是
「有界 head/tail 预览 + 定位符 + 取回提示」,可随时用
``read_file`` 按 offset/limit 读全文。第 13/17/18 点的 pruner 是
「截断」,这一层是「落盘 + 可检索」,两者互补。

- `encode_segment`:注入式安全段名编码(``~XXXX`` 转义,``.``/``..``
  整体转义,空串 ``~``),防穿越;``save_text_spill`` 写入
  ``<root>/session-<sha256前缀>/<随机hex>-<safeName>``,目录 0700、
  ``O_EXCL`` + 0600 独占写,随机前缀防符号链接植入;缺省 root 为进程
  私有 ``mkdtemp``(dsh ``privateRoot``)。
- `maybe_spill_text`:策略层。跳过 ``read_file``(防
  read→spill→read 循环);notice 字节成本**在 cap 内预留**(以最坏
  省略计数定价),替换结果(预览 + 空行 + notice)永不超过
  ``max_inline_bytes``;UTF-8 边界在两端裁剪处保留;notice 单独放不下
  时保持内联,绝不发出超 cap 的替换。
- 尽力而为:无会话 owner、存储失败(权限/ENOSPC)一律告警并保持
  内联,spill 失败绝不把成功调用变成 isError。
- 接入:`render_tool_output` 统一漏斗(spill 先于 pruner,替换后
  ≤ cap 所以 pruner 变 no-op),react 主路径与 native tool bridge
  两个调用点共用 ``TOOL_RESULT_SPILL_ENABLED`` 开关。
- 默认关(对齐 dsh:`maxInlineBytes` 未配置时 policy 不注册);
  ``OCTOPUS_TOOL_SPILL=1`` 开启,``OCTOPUS_TOOL_SPILL_MAX_INLINE_BYTES``
  调 cap(默认 8192,与 pruner 阈值同),``OCTOPUS_TOOL_SPILL_ROOT``
  指定落盘根目录。
- 测试:`tests/test_tool_output_spill.py` 27 用例(段名编码防穿越、
  私有会话目录、UTF-8 边界预览、notice 预算预留、read_file 跳过、
  失败保持内联、两个调用点接线);回归 bridge/pruner/react 382 项全绿,
  ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- dispatch-log 臂:对 durable 日志副本的同 cap 裁剪——我们没有
  ``code-dispatch-log`` 事件,跳过。
- 远端/云端 SpillStore 后端:当前只有本地文件系统实现,定位符对
  同机消费方才有意义;e2b 等可移植执行世界列为后续。
- 会话生命周期清理:spill 文件持久留存直到外部清理(与 dsh 相同,
  续会话/分支会话仍可能引用)。
## 21. report 工具进进程内 runner (`suckers/ephemeral_runner.py`)

dsh 的 ``tool-subagent-report``:续会话子代理的回合内主动上报,而不是
父代理在下次 call 时被动拉取。第 16 点的 report 闭环是「回合结束后
bridge 附加 pending_reports」;本轮把 ``report`` 做成子代理回合中
可调用的真工具,部分发现可立即送达父代理。

- 注入面与 dsh 一致:**只在续会话进程内子代理**可见——bridge 在
  ``_do_call`` 里把 ``subagent_session_id`` 盖进 dispatch context,
  runner 检测到才暴露工具;一次性子代理、外部 CLI backend、无会话
  执行永远看不到。
- ``report`` 工具规格与 dsh 相同:唯一参数 ``output``(必填,自包含
  结论),返回 messageId;系统提示追加 dsh 引导段(「用 report 交付
  结果、报告不结束回合、父代理不会自动拿到 transcript、失败可能已
  送达不要盲目重试」)。
- 执行:``_handle_report_tool`` 调 ``append_report``(delivery 策略
  默认 ``wakeup``,可从 context ``subagent_report_delivery`` 覆盖为
  ``quiet``);失败(无 store/无会话/空内容)返回 is_error 结果但不
  中断子代理回合——与 dsh 的 at-least-once 语义一致。
- 测试:`tests/test_ephemeral_report_tool.py` 8 用例(无会话不暴露、
  有会话暴露 + 引导段、回合中送达 + ack 回灌、quiet 策略、失败隔离、
  空 output 拒绝、bridge 盖 session id、端到端 pending_reports);
  回归 ephemeral/subagent 295 项全绿,ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- 后台 continuable settlement 通知(事件桥):报告送达后的
  wakeup 排队目前只在 ``on_report`` 钩子里,没有独立的调度器
  事件桥接层;``quiet``/``wakeup`` 的父代理离线排队列为后续。
- 回合级真实 transcript 订阅:子代理回合内事件流
  (``sub_tool_start``/``sub_text_delta``)尚未落到 session 日志的
  逐事件桥,父代理拿到的仍是摘要级 report。
## 22. shadow-price 修剪记账 (`tool_engine/tool_shadow_price.py`)

dsh 的 ``compaction/prune`` shadow-price 协议:每次修剪替换时,在替换
前同步追加一条 log-only 定价事件,声明被遮蔽 span 的启发式 token 价,
纯消费方可无状态扣除。第 13/17/18 点的 pruner 剪掉中段后,模型少看了
多少 token 一直没被计量;本轮补上事件桥:

- `estimate_shadowed_tokens(chars)` — dsh 固定密度估算器
  (``CHARS_PER_TOKEN = 4``,``ceil(chars/4)``),与 dsh
  ``token-meter/estimate.ts`` 同源。
- `PruneShadowPrice` 记录:tool_name / call_id / chars_before / chars_after
  / chars_removed / tokens_shadowed;`prune_tool_result_text` 每次真正
  剪中段时发射一条(预算内、invariant 短路不发)。
- `set_shadow_price_sink(sink)` 注册面(默认进进程级
  ``ShadowPriceLedger`` 计数器,``None`` 关闭);sink 抛异常只告警、
  绝不影响修剪。**Shadow price 是观测不是账单**:模型没看到的上下文
  绝不能混入 ``UsagePricing`` 真实记账,ledger 快照只用于报
  「修剪节省的估算 token」。
- 归因:`render_tool_output` 的 ``spill_tool_name`` 泛化为 ``tool_name``
  (spill 命名与 shadow-price 归因共用),``normalize_tool_result``
  自动带出调用 id;react 主路径与 native bridge 两个调用点自动获得
  归因。
- 测试:`tests/test_tool_shadow_price.py` 11 用例(估算器、发射载荷与
  归因、预算内/短路不发射、sink 关闭、sink 失败隔离、ledger 累计与
  reset、render/normalize 归因);回归 pruner/bridge/react/spill 393 项
  全绿,ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- 日志内 adjacency 协议:我们无 dsh 的 session 日志 surface fold,
  「定价事件紧跟替换事件」的时序约束不适用;ledger 计数器是等价但
  更松的桥,将来若引入 priced surface 可把 sink 换成 fold。
- 角色/块级结构开销(dsh ``BLOCK_OVERHEAD`` / ``ROLE_OVERHEAD``):
  我们按纯文本 span 计价,整条消息框架开销不适用。
## 23. goal scope-filtered 分发 + journal 事件桥 (`goals/service.py`)

收口第 19 节「尚未覆盖」的两块:dsh 把 ``goal/changed`` 定向路由给目标
agent(`agentEvents(ctx, agent).emit('goal/changed', ...)`),并让目标状态
对同 journal 上的其他 writer 可读(事件桥)。本轮补上:

- `GoalChanged` 增 ``agent_id`` / ``conversation_id`` 字段:载荷携带
  owning scope,与 dsh 一致;服务构造时传入自身 scope,并镜像到每条
  写入的 ``goal_change`` 事件与每条广播。
- `GoalService.subscribe(callback, *, agent_id, conversation_id, replay)`
  :``_GoalFilter``(frozen dataclass)按 scope 过滤,命中才投递;
  无过滤的订阅者是 wildcard,仍收全量事件。``replay=True`` 时对新订阅
  者按 journal 顺序补发已提交的 ``goal_change``(晚订阅/重启后追平)。
- journal 事件桥:构造时用 ``type(journal).subscribe is not Journal.subscribe``
  判断 live fan-out(``StreamingJournal`` 覆写了 ``subscribe``,基类是
  no-op);live 时经 ``journal.subscribe(self._on_journal_event)`` 订阅,
  ``_write`` 不再自行 notify(靠广播,避免重复),同一 journal 上任何
  writer 的 goal 变更都广播到本服务订阅者;基类 journal 回退到进程内
  直接 notify。malformed 的 ``goal_change`` 由 ``_decode_journal_change``
  捕获跳过,绝不影响桥或后续事件。
- `current()`(CAS 守卫)改用 ``_scoped_goal_events()``:按服务自身
  scope 过滤事件后再 fold,共享 journal 上其他 writer 的目标不与该服务
  的 CAS 冲突;无 scope 服务保留原全局 fold。
- 测试:`tests/test_goal_domain.py` 新增 8 用例(scope 过滤命中/跳过的
  create/edit/clear 载荷、跨 writer 定向分发、跨 writer scope 隔离、
  自身写入不重复通知、replay 追平顺序、replay 尊重 scope 过滤、桥容忍
  malformed 事件)+ 既有 33 用例全绿;ruff/invariant 干净;``-k "goal or
  journal"`` 回归 268 项通过。

### 尚未覆盖(dsh 有而这里没有)

- 分页/流式 goal surface:dsh 的目标在 session surface 上有 fold 与
  时间线视图;我们目前只有单目标 fold + 广播,多目标历史归档未接。
  (流式 surface 已由第 42 节收口:增量投影缓存 + as-of 水位;多目标
  历史归档仍留作后续。)
- ``replay`` 无跨 writer wildcard 语义:回放仍读全量事件再按订阅过滤,
  与 live 桥的 wildcard 行为一致;若将来要把服务绑定死单 agent,可把
  回放也切到 ``_scoped_goal_events``。
## 24. executor render/materialize 投影 (`tool_engine/session_projection.py`)

dsh 的 ``@dsh-session-reference`` 在把**别的会话**的上下文注入当前模型
请求前,先把目标会话的会话面 materialize 成一个只读快照,并精确压进
字节预算(dsh ``retainReferencedSession`` + ``stringifyTagSafeJson``)。
我们此前对「跨会话引用」只有 subagent 续会话的逐轮 head 截断;本轮
把 dsh 投影算法整体移植:

- `project_session_conversation(events)` — 会话面投影:只保留直接
  user(或 compaction checkpoint)与 assistant 文本消息,跳过
  tool/result、推理、注入上下文与空文本,非文本块忽略。
- `retain_session_reference(...)` — 两阶段保留:先整条丢弃非
  checkpoint 消息(最旧先丢、保最新),再对最长保留消息做 head/tail
  二分截断 + 精确 ``[… omitted N UTF-8 bytes …]`` 通知;固定字段单独
  放不下返回 ``None``(dsh 预算契约,绝不返回半截上下文)。
- `truncate_with_notice(text, max_bytes)` — 二分 head/tail 预览,
  检索候选 ``{preview}\n[… omitted N …]`` 不超过预算时取最优;
  `head_tail_preview_bytes` 从 spill 模块抽出复用(整数字节对齐)。
- `stringify_tag_safe_json` — 每个 ``<`` 转义为 ``\u003c``,源文本
  永远无法拼出 framing 标签(dsh 防注入)。
- `is_compact_checkpoint_source` — ``{kind:'plugin',plugin:'compact'}``
  判定 compaction checkpoint(dsh ``isCompactCheckpointSource``)。
- 集成:subagent 续会话 ``transcript_prompt(..., bounded=...)`` 新增
  bounded 分支,把 dsh 投影渲染为续接前缀;``bridge.py`` 注入 transcript
  的调用点通过 ``OCTOPUS_SESSION_REFERENCE_BOUNDED=1`` 开关启用,
  默认关(保持旧行为,host 按需 opt-in,与 dsh 一样是显式服务)。
- 测试:`tests/test_session_projection.py` 14 用例(投影过滤、checkpoint
  保最新、丢弃计数、截断通知、固定字段预算、tag-safe 转义、空输入)
  + `tests/test_subagent_sessions.py` 3 个 bounded 用例,均绿;回归
  subagent/ephemeral/tool_output/pruner 539 项通过,ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- 跨会话引用解析层:dsh 有 ``@dsh-session-reference`` 服务、URI 解码、
  候选限制(candidateLimit)与 reference 包裹前缀/后缀,我们只落地了
  投影算法与 subagent 续会话集成,没有通用的「任意 session URI → 投影
  注入」解析面;如需完整跨会话引用可再补 resolver。
- checkpoint 事件源:当前只把 subagent turn 拍成 dsh surface 事件形状;
  若 executor 主路径也走会话面,应把真实 session journal 事件直接喂给
  投影,而非从 turn 重建。(已由第 45 节收口:journal 有该会话行时
  bounded 投影直接吃真实日志事件。)
## 25. report 唤醒预算 (`subagents/sessions.py` + `suckers/ephemeral_runner.py`)

第 21 节把 ``report`` 工具接进了进程内 runner,但每次 ``wakeup`` 报告都会
无条件触发父进程唤醒钩子 —— 一个爱汇报的子代理可以在两条人工输入之间
无限地撬起父回合,形成失控链。dsh 的 ``tool-jobs`` 调度器用
``maxConsecutiveWakes``(默认 3)约束「每 owner 在最近一次人工输入后由
插件撬起的连续回合数」,本轮把预算搬过来:

- ``SubagentSessionStore(max_consecutive_wakes=...)``:新增连续唤醒预算
  (默认 ``DEFAULT_MAX_CONSECUTIVE_WAKES = 3``,``0`` 表示永不唤醒;
  负值/小数/bool 在构造时报错 —— 坏配置该在启动失败,而不是把每次
  报告变成错误)。
- ``append_report(delivery="wakeup")`` 在预算内才真正唤醒:决定唤醒的
  那一刻(持锁、原子)就把预算扣掉(dsh ``spentWakes.set`` 语义),
  预算耗尽后该报告降级持久化为 ``quiet``,只排队、不撬父回合;
  ``quiet`` 报告从不消耗预算。
- ``refill_wake_budget(session_id)``:父进程认领到人工输入后重置预算
  (dsh ``agent/inbox/claimed`` + ``source.kind==='user'`` 语义),未知
  session 为 no-op;``create`` 建新会话时预算也是全新的。
- runner 反馈闭环:``_handle_report_tool`` 现在把**实际生效**的 delivery
  告诉子代理 —— 被降级为 quiet 时明确提示「父进程未被唤醒、别继续
  重复汇报,父进程会在下一回合读到」,避免子代理盲重复。
- 测试:``tests/test_subagent_report.py`` 新增 7 用例(默认值、连续预算
  上限与降级、quiet 不耗预算、refill 重置、未知 session no-op、非法
  预算拒绝、零预算永不唤醒);既有 18 用例与
  ``tests/test_ephemeral_report_tool.py`` 全部保持绿;回归
  subagent/ephemeral/session/projection/spill 752 项通过,ruff/invariant
  干净。

### 尚未覆盖(dsh 有而这里没有)

- 忙碌 owner 语义已由第 34 节收口;当时缺的「owner 忙碌判定」现在是
  ``mark_owner_busy/mark_owner_idle`` 显式状态。
- 弱引用生命周期:dsh 的 ``spentWakes`` 是 ``WeakMap``(session 替换即
  满预算);我们用 ``dict`` 按 session_id 记,会话结束由调用方决定是否
  清除。
## 26. durable ``user/message`` journal 事件 (`runtime/memory/journal/`)

第 15 节留下的最后一块缺环:fold 早就能校验「goal 来源消息必须是当前
revision 的下一个轮次」,但 journal 一直没有 dsh 的 ``user/message``
事件类型,轮次记账无从写入。本轮补上事件模型与写入路径,goal 回合
计数从「理论校验」变成「真实可审计的事件流」:

- ``_journal_models.py``:``JournalEventType`` 新增 ``"user/message"``;
  ``UserMessageEvent(event_type="user/message", text="", goal_source=None)``
  ——``goal_source`` 承载 dsh ``GoalMessageSource`` 形状
  (``{"kind":"goal","goalId":...,"revision":...,"round":...}``),无归属的
  普通消息 fold 忽略、只当转录条目。
- ``_journal_parse.py``:``_EVENT_CLASSES["user/message"]`` 注册,JSONL
  写入→读回无损,重启重放可重建轮次。
- ``_journal_base.py``:``Journal.write_user_message(text, *,
  goal_source=None)``,仿 ``write_goal_change`` 带
  ``agent_id/conversation_id`` 自动填充。
- ``fold.py``:``apply_goal_event`` 的 ``user/message`` 分支在
  ``data.source`` 缺失时回退读 ``getattr(event, "goal_source", None)``,
  同时兼容带类型事件对象与裸 dict 两种入参。
- 测试:``tests/test_user_message_event.py`` 7 用例(事件类注册、JSONL
  回环、轮次记账 1→2→3、乱序第 3 轮拒绝 GOAL_INVALID_TRANSITION、
  无归属忽略、非 goal source 忽略、超 maxGoalRounds 拒绝)。

### 已收口

- 回合级 transcript 逐事件桥:sub_tool_start/sub_text_delta 等回合内
  子事件喂 session 日志——第 27 节已落地(``sub_text_delta`` journal
  事件 + 逐 chunk 镜像 + 逐事件重建)。
## 27. session-reference resolver (`tool_engine/session_reference.py`)

第 24 节落地了 dsh 的投影算法,但只有 subagent 续会话一个调用点,没有
「引用解析面」。本轮把 dsh 的 ``@dsh-session-reference`` 服务层整体搬
过来,在投影之上加一层:

- `SessionReferenceResolver`:``list_candidates`` 按工作目录亲和度排序
  (dsh ``candidateRank``:同 cwd 0、无 cwd 1、异 cwd 2),并按大小写
  不敏感的 session-id / cwd / label 子串过滤、限长;``prepare`` 做
  引用标准化 → 逐源读 surface → 逐源投影(``retain_session_reference``,
  预算不够抛 ``SESSION_REFERENCE_BUDGET_EXCEEDED``)→ 渲染聚合 frame。
- 标准化与错误码:``normalize_references`` 拒绝自引用、去重、封顶
  (``max_references``,默认 3);``SessionReferenceError`` 携带 dsh 稳定
  错误码(INVALID_CONFIG / INVALID_REFERENCE / SELF_REFERENCE /
  TOO_MANY / READ_FAILED / BUDGET_EXCEEDED)。
- 渲染契约:``render_reference_prompt`` 输出
  ``## Referenced sessions ... <referenced-sessions> JSON </referenced-sessions>``
  frame,JSON 经 ``stringify_tag_safe_json``(每个 ``<`` 转义),源文本
  永远拼不出 framing 标签;``prepare`` 返回 detached content +
  ``additional_context``(source 溯源 + content)。
- 配置:``max_references``(≤3)、``candidate_limit``(默认 50)、
  ``max_reference_bytes``(默认 64KiB);非法配置构造即报错,坏配置在
  启动失败而非每次引用变错误。
- 适配器:``SubagentSessionStore.surface_events(session_id)`` 暴露 dsh
  surface 形状、``list_reference_candidates(...)`` 用 resolver 排候选,
  让 subagent 会话可被 resolver 消费(resolver 本身 store 无关,任何
  持久会话面都能接)。
- 测试:``tests/test_session_reference.py`` 19 用例(候选排序/过滤/限长、
  标准化去重/自引用/超限/非法、prepare 无引用/frame 渲染/tag 转义/
  自引用/预算超限/读失败、非法配置、render 形状、subagent store 适配);
  回归 reference/subagent/session/projection/spill/report 744 项通过,
  ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- host 自动补全接线:我们实现了 ``list_candidates`` 与 subagent store
  适配,但没有把 resolver 接到宿主端的提及自动补全/mention 解析管线
  (dsh 由 host 解析 mentions 后调 ``prepare``)。
- 取消信号:我们省略了 dsh 的 ``AbortSignal`` 取消边界;长读 surface
  时如需可中断再补。
## 28. 回合级 transcript 逐事件桥 (`sub_text_delta` → journal)

dsh session 日志的不变式是「模型可见即入日志」:回合内流式细节也逐
事件落盘,transcript 可从日志逐事件重建。我们此前 sub_tool_start/end
已入日志,但角色流式文本(``sub_text_delta``)只走内存 emitter,父
进程拼 prompt 后日志里没有原文。本轮补上最后一环:

- ``_journal_models.py``:``JournalEventType`` 新增 ``"sub_text_delta"``;
  ``SubTextDeltaEvent(event_type="sub_text_delta", role_id, round, delta,
  parent_tool_use_id)``——镜像 SSE pump 的 ``sub_text_delta`` 形状
  (dsh 对应 ``assistant/chunk``),字段与 ``sub_tool_*`` 事件一致。
- ``_journal_parse.py`` 注册 + JSONL 回环,重启重放可重建流式文本。
- ``_ephemeral_events.py``:``_emit_sub_text_delta(role_id, round, delta,
  *, emitter=None)``——先 ``_safe_ctx_emit`` 转发父网关渲染路径,再按
  ``_emit_sub_tool_event`` 同一查找模式镜像 journal(带 task_id /
  parent_tool_use_id);无 session/journal 时静默 no-op,telemetry 损失
  绝不打断 runner。
- ``ephemeral_runner.py`` 三处发射点全部切换:单发流式、agentic 循环
  流式、截断通知——每 chunk 都落盘,不只最终文本。
- ``derive.py``:``derive_subagent_streams(journal, *, role_id=None)``
  按 ``(role_id, round)`` 分组、按 journal 顺序拼接重建每轮 prose
  (``SubagentRoundStream``,带 ``chunk_count`` 证明逐 chunk 保真);
  ``assert_logged_stream_reconstructs`` 提供 round-trip 断言——与
  ``assert_logged_history_reconstructs`` 对应,审计路径可证明「角色
  流过的文本日志里全有」。
- 测试:``tests/test_sub_text_delta_event.py`` 9 用例(事件注册、JSONL
  回环、emitter+journal 双写、无 session no-op、多轮重建、按角色
  过滤、空日志、跳过非 delta 事件、round-trip 断言),全部绿。

### 已收口

- 父级 assistant 流式文本逐 chunk 入日志——第 28 节已落地
  (``assistant/chunk`` 事件 + react loop 全部 ``text_delta`` 发射点
  接线);父泳道与 subagent 泳道现在都有逐 chunk 保真。
## 29. 父级 ``assistant/chunk`` 流式入日志 (`runtime/core/cerebrum/`)

第 27 节闭合了 subagent 泳道,父泳道仍只有 ``react_checkpoint`` 快照
(按迭代)与 ``step`` 事件,回合内流式文本不进日志。dsh 的
``assistant/chunk`` 是「模型可见即入日志」在主回合的对应物:模型
流出的每个可见 fragment 都是 session 事件。本轮把 react loop 的全部
``text_delta`` 发射点接到 journal:

- ``_journal_models.py``:``JournalEventType`` 新增 ``"assistant/chunk"``;
  ``AssistantChunkEvent(iteration, kind="text-delta", delta)``——
  ``kind`` 镜像 dsh ``StreamChunk`` 泳道,未来
  ``reasoning-delta`` / ``tool-call-delta`` 无需改 schema。
- ``_journal_parse.py`` 注册 + JSONL 回环。
- ``_journal_base.py``:``Journal.write_assistant_chunk(*, iteration,
  delta, kind="text-delta", task_id=None)``,agent/conversation id 走
  contextvars(与 checkpoint 帮手一致)。
- ``react_loop_controls.py``:``_emit_assistant_chunk(stack, *,
  iteration, delta, task_id)``——best-effort,无 journal 或写入失败
  静默 no-op,telemetry 损失绝不打断 loop。
- 接线 9 个发射点(4 模块):``react_model_stream`` 的 4 处 post-anchor
  增量、``react_phase_6c`` 的 fall-through/截断/受守卫 prose 3 处、
  ``react_terminal`` 收尾补发、``react_final_answer_guards`` 延迟
  emit——全部先落 journal 再 yield,用户看到的每段文本日志里都有。
- ``derive.py``:``derive_assistant_stream(journal, *, iteration=None)``
  按迭代分组、按日志顺序拼接重建(``AssistantChunkStream`` 带
  ``chunk_count``);``assert_logged_assistant_reconstructs`` 提供
  round-trip 断言,审计路径可证明「回合流过的文本日志里全有」。
- 测试:``tests/test_assistant_chunk_event.py`` 11 用例(事件注册、
  JSONL 回环、write 帮手、无 journal no-op、空 delta 跳过、多迭代
  重建、按迭代过滤、空日志、跳过非 chunk 事件、round-trip 断言),
  全部绿;react 全量回归 1360 项通过,ruff/invariant 干净。

### 已收口

- 存储压缩:第 29 节已落地(``_chunk_rows`` 打包,连续 delta 合并为
  一行存储、token 边界仍是数据、展开无损)。
- ``reasoning-delta`` / ``tool-call-delta`` 泳道:目前只 journal 可见
  ``text-delta``;dsh 连推理块与工具参数流也逐块落盘(仍待补)。
## 30. host 侧 session mention 接线 (`tool_engine/session_reference.py`)

第 27 节落地了 resolver 的 ``list_candidates`` / ``prepare``,但 dsh 由
宿主端先解析 mention 再调 ``prepare`` 的那段「接线」没搬——这是第 27 节
「尚未覆盖」清单里明说缺的那一环。本轮补上:宿主在 user prompt 里用
``@session:<id>`` / ``@subagent:<id>`` 提及历史子代理会话,解析器自动
解析→投影→聚合 frame,替换进本轮请求,源文本永远拼不出 framing 标签。

- ``extract_session_mentions(prompt)``:按首现顺序去重提取被引用的
  session id,只认 ``[0-9a-f]{32}`` 全小写十六进制 id + 词边界,无效
  token(``@session:nothex``、超长 id)一律忽略——陈旧/拼错的提及绝不
  hard-fail 整轮。
- ``SessionReferenceResolver.resolve_mentions(prompt, *, target_id,
  read_surface, sessions=None, strip_mentions=True)``:dsh 的 host
  mention-parse → ``prepare`` 一键通路。引用按首现顺序封顶到
  ``max_references``(取前 N,超出静默丢弃,mention 是便利面不是硬契约);
  自引用与 ``sessions`` 里查不到的陈旧 id 跳过;读到/预算不足仍抛
  ``SessionReferenceError``。返回 ``PreparedReferencedMessage``:
  ``content`` 为剥掉 mention 的 prompt(内联提及留下的连续空格被折叠,
  不再留双空格),``additional_context`` 承载渲染好的 frame 与
  ``session-reference`` 溯源,宿主自行决定注入时机。
- 适配器:``SubagentSessionStore.resolve_session_mentions(prompt, *,
  target_id, ...)`` 把内存 store 当 session 源、``surface_events`` 当
  read_surface,store 调用方一条语句完成「提及→上下文」。
- 测试:``tests/test_session_reference.py`` 新增 7 用例(提取去重/别名/
  无效 id 忽略、空 prompt 与无提及原样返回、投影+剥提及、陈旧+自引用
  跳过、max_references 封顶、store 适配器命中原样解析、store 陈旧
  mention 静默降级);``tests/test_session_reference.py`` 全套 25 用例
  通过,reference/projection/spill/report/subagent 回归 106 项通过,
  ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- 前端自动补全弹层:解析/注入面已接好,但宿主 UI 的「键入
  ``@session:`` 时弹出候选」没有做——那属于前端 host 侧,需要的话再搬
  dsh 的 candidate autocomplete 交互。
- 取消信号:沿用的 ``AbortSignal`` 取消边界仍未移植;长读 surface 如需
  可中断再补。

## 31. chunk 存储压缩 (`runtime/memory/journal/_chunk_rows.py`)

第 28 节把可见文本逐 chunk 入日志,代价是长答案产生数百行近似雷同的
JSONL——dsh 实测过 ~56 倍信封开销,并用 ``chunk-rows`` 把连续同块
delta 打包成一行存储、读时无损展开。本轮把这套存储编码搬过来:

- ``_chunk_rows.py``(纯编解码,零 IO):
  - ``classify_chunk``:结构化白名单——只有 ``assistant/chunk`` 与
    ``sub_text_delta`` 且 envelope/extra 字段形状精确匹配才可打包;
    未知字段或变体一律退回逐行存储(丢压缩不丢数据)。
  - ``continues_chunk_run``:同事件类型 + 同 envelope(common/extra
    字典相等)+ 时间严格递增——对应 dsh 的 seq/block 连续性检查。
  - ``pack_chunk_row``:一行存储 ``{__chunk_row__: 1, event_type,
    count, ts0_us, dt_us[], common, extra, members[{event_id,
    delta}]}``——token 边界是数据,只存增量不拼接。
  - ``expand_chunk_row``:按 ``dt`` 间隙精确还原每个事件的
    event_id/ts/delta;畸形行 fail-loud(dsh 语义:静默丢半条 run
    会重建出错误的会话)。
  - ``MIN_RUN = 3``(同 dsh):短 run 保持逐行,信封开销不值得打包。
- ``journal.py`` 接线:
  - ``write``:可打包事件先入内存 run(``_pending_chunk_run``),非
    chunk 事件 / 读 / run 断开时 ``_flush_pending_chunks_locked``
    落盘——所以任意时刻至多缓冲尾部一条 chunk run;SIGKILL 窗口与
    dsh 的 write-behind 同级。
  - 落盘:``>= MIN_RUN`` 写一行打包行,否则逐事件原样写;redactor
    对打包行走同一 JSON 合法性守卫;audit chain + trace store 在
    flush 时逐成员镜像,顺序与文件一致。
  - ``read_all``:先 flush 再看文件;``__chunk_row__`` 行展开成 N 个
    事件入缓存(``_parse_event_data`` 与普通行同一条校验路径)。
  - ``__len__`` 改为事件数(不再按行数);跨进程写入的行各自自洽,
    交错无害。
  - 逃生阀:``OCTOPUS_JOURNAL_CHUNK_PACKING=0`` 关闭写侧打包
    (读侧两种编码都支持,纯回滚旋钮)。
- 测试:``tests/test_chunk_rows.py`` 19 用例(classify 白名单、
  continues 边界、byte-identical 无损回环、畸形行 fail-loud、长 run
  一行、短 run 原样、run 断开续打、env 旋钮、双 journal 互读、
  sub_text_delta 打包、InMemory 不打包),全部绿;回归
  journal/sse/resume/subagent/audit/realtime/checkpoint 1522 项通过,
  ruff/invariant 干净。

### 已收口

- ``reasoning-delta`` 泳道:第 30 节已落地(thinking_delta 逐块落盘,
  打包层直接复用);``tool-call-delta`` 暂无生产者——我们的模型路由
  器不流式工具参数,工具调用以完整块到达,无增量可记。
- goal 分页/流式 surface、title provider 优先级链、远端 SpillStore
  (e2b)——仍待补。
## 32. reasoning-delta 泳道 (`thinking_delta` → journal)

第 28/29 节闭合了可见文本泳道;dsh 的 ``assistant/chunk`` 还有
``reasoning-delta``(推理块)与 ``tool-call-delta``(工具参数流)两条
泳道。我们确实流式产出推理文本(react loop 的 ``thinking_delta``),
但从未落盘;工具参数则没有增量流(路由器以完整块到达),无增量可记。
本轮把推理泳道接上:

- ``react_loop_controls._emit_assistant_chunk`` 新增 ``kind`` 参数
  (默认 ``"text-delta"``),透传给 ``write_assistant_chunk``。
- ``react_model_stream`` 两处 ``thinking_delta`` 发射点(thought 区域
  提取流、provider thinking 透传流)先落 journal
  ``kind="reasoning-delta"`` 再 yield——私密推理与可见文本同属
  ``assistant/chunk``,靠 ``kind`` 区分泳道(dsh ``StreamChunk``
  语义)。
- ``derive_assistant_stream`` 新增 ``kind`` 过滤(默认
  ``"text-delta"`` 保持「用户可见回复」语义;``"reasoning-delta"``
  取推理泳道;``None`` 取全部)——审计可按泳道重建。
- 打包层零改动复用:``classify_chunk`` 的 ``assistant/chunk`` 白名单
  已含 ``kind``,uniform kind 的 run 自动打包、混合 kind 自动断 run。
- 测试:``test_assistant_chunk_event.py`` 新增 3 用例(kind 写入、
  推导按泳道分离、kind=None 全量);``test_chunk_rows.py`` 新增 2
  用例(reasoning run 打包、混合 kind 断 run);react 全量回归 1360
  项通过,ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- ``tool-call-delta`` 泳道:无生产者(工具调用完整块到达,不流式参数
  片段);若未来接入增量工具参数流,事件模型与打包层已就绪。
- goal 分页/流式 surface、title provider 优先级链、远端 SpillStore
  (e2b)。
## 33. journal sub-agent 流式事件加会话关联键 + journal→投影桥

第 30 节落地 host mention 接线时,「真实 journal 喂投影」被判为被关联键
问题阻塞:``sub_text_delta`` 事件只有 ``role_id``(= agent/角色 id,同
角色的每个会话都共享),journal 里无法按 subagent 会话区分。本轮补根因
——给流式事件加 ``session_id`` 关联键,并让投影吃真实 journal 散文:

- ``_journal_models.py``:``SubTextDeltaEvent`` 新增 ``session_id: str =
  ""``(纯 schema 追加,JSONL 回环无损,旧事件按空串兼容,无需迁移)。
- ``_ephemeral_events.py``:``_emit_sub_text_delta(role_id, round, delta,
  *, session_id="", emitter=None)``——journal 镜像写入 ``session_id``;
  SSE emitter payload 保持不变,不把 session_id 泄给前端。
- ``ephemeral_runner.py`` 三处发射点从 ``call.context["subagent_session_id"]``
  取 ``session_id`` 传入(单发、agentic 循环、截断通知);一次性/远端
  子进程无该 key 则为空串,telemetry 损失绝不打断 runner。
- ``derive.py``:``derive_subagent_streams(journal, *, session_id=None,
  role_id=None)`` 可按会话过滤——``role_id`` 不再歧义;
  ``SubagentRoundStream`` 携带 ``session_id``(默认空串,旧构造兼容);
  ``assert_logged_stream_reconstructs`` 同步支持 ``session_id``。
- ``derive.py``:新增 ``surface_events_from_journal(journal, *,
  session_id, prompts=None)``——把真实 journal 散文桥成 dsh surface 形状
  (assistant 泳道从日志逐 chunk 重建、user 泳道由调用方提供,journal
  目前没有 per-session ``user/message`` 行),输出可直接喂
  ``retain_session_reference``。第 24/28 节留的「journal 喂投影」缺口
  由此闭合。
- 测试:``tests/test_sub_text_delta_event.py`` 新增 4 用例(emitter 不泄
  session_id、按 session 过滤、prompt/round 交错、桥→投影端到端),全套
  13 用例通过;journal/ephemeral/session/reference 回归 92 项通过,
  ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- per-session ``user/message``:subagent 的 prompt 仍不在 journal 里
  (``user/message`` 写的是父会话/goal 维度),所以投影的 user 泳道仍由
  turn 提供,纯 journal 表面尚缺 user 侧;后续可让桥在 subagent 会话
  生命周期里补齐。
## 34. 忙碌 owner 语义(`subagents/sessions.py` + `suckers/ephemeral_runner.py`)

第 25 节留的缺口:dsh 的 ``tool-jobs`` 调度器在通知完成时先看 owner
状态——空闲(``followup`` 唤醒开回合)与忙碌(``inject`` 排进当前回合
的下一步队列)是两条不同路径,且 ``inject`` 不消耗唤醒预算;我们只有
report 泳道,「父回合是否在跑」由调度器外部决定,预算只管连续唤醒次数。
本轮把 owner 忙碌判定搬进 store:

- ``mark_owner_busy(session_id)`` / ``mark_owner_idle(session_id)``:新增
  owner 生命周期状态(dsh ``agent.status === 'running'/'idle'``)。纯内存
  状态、不落盘——store 重启一律从 idle 开始(dsh 重启即 idle),未知
  session 为 no-op。
- ``append_report(delivery="wakeup")`` 决策表与 dsh ``onJobDone`` 对齐:
  owner 忙碌 → 持久化为 ``queued``(dsh ``inject``:不唤醒、不扣预算,
  等当前回合的下一次读/续会话消费);owner 空闲且预算未花完 → 唤醒 +
  扣预算(dsh ``followup``);预算耗尽 → 降级 ``quiet``。``quiet`` 输入
  在忙碌时也保持 ``quiet``,不升级。
- ``SubagentReport.delivery`` 新增 ``"queued"`` 字面量,``from_dict``
  兼容旧 JSON(wakeup/quiet 原样,未知值回退 wakeup),跨实例重载无损。
- runner 反馈闭环:``_handle_report_tool`` 现在区分三种生效 delivery——
  ``queued`` 明确告诉子代理「父进程正在跑、没被唤醒,会在下一次续会话
  或新回合读到」,避免它以为父进程已被撬起而重复汇报。
- 测试:``tests/test_subagent_report.py`` 新增 8 用例(忙碌时排队不唤醒、
  不扣预算、quiet 不升级、idle 恢复唤醒、忙碌态不落盘、未知 session
  no-op、queued 跨实例重载、prompt 标注 queued);
  ``tests/test_ephemeral_report_tool.py`` 新增 1 用例(忙碌时子代理收到
  「父进程忙」反馈);既有 48 项全绿,ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- 回合内「下一步」注入:dsh 的 ``inject`` 会被正在跑的回合在最近的
  step 边界直接消费;我们没有 per-step inbox,``queued`` 报告实际靠
  ``pending_reports``/``reports_prompt`` 在父进程下一次续会话或新回合
  读到(近似、不保证同回合可见)。
- 生产接线已由第 35 节收口:线程级 busy/idle 与人工输入 refill 已接进
  父回合生命周期;``on_report`` 唤醒钩子仍未接——「空闲 owner 开新回合」
  需要网关在持有连接/emitter 时才可安全实现,当前 wakeup 只落盘不真撬
  回合,待接入回合调度器。
## 35. 调度器生产接线:线程级 owner 状态 + 人工输入 refill

第 34 节把 busy/idle 语义搬进 store,但生产没人调用:``wakeup`` 报告只
落盘不真撬回合,预算 refill 只有测试在调。本轮把 owner 状态接进父回合
生命周期——busy/idle 由 react 驱动标记,refill 由网关在人工回合开始时
触发,store 增加线程级 API 支撑:

- ``mark_thread_busy(thread_id)`` / ``mark_thread_idle(thread_id)``:
  线程级 owner 状态(``_busy_threads``,纯内存、空 id no-op)。与
  session 级 ``mark_owner_busy`` 并存,``append_report`` 任一命中即按
  ``queued`` 处理;线程级对「回合中新建的会话」同样生效(dsh owner 是
  生命周期对象,不是某一具体子会话)。
- ``stream_react_loop`` 改为薄包装器:原实现改名
  ``_stream_react_loop_impl``,公开入口进入时
  ``mark_thread_busy(thread_id)``,退出时(正常/异常/生成器提前 close)
  ``mark_thread_idle(thread_id)``——``return (yield from ...)`` 保住
  ``ReActResult``,``try/finally`` 保证任何退出路径都清 busy。所有父
  回合驱动(CLI/controller/realtime gateway)都经此入口。
- 网关 ``_start_turn`` 在解析出 ``thread_id`` 后 best-effort 调用
  ``refill_thread_wake_budget(thread_id)``(dsh ``agent/inbox/claimed`` +
  ``source.kind==='user'``:人工输入进回合即重置该线程全部会话的唤醒
  预算),懒加载 + 异常吞掉,存储缺失绝不阻塞回合。
- ``refill_thread_wake_budget(thread_id)``:重置该线程名下所有在内存
  会话的 ``_spent_wakes``(有预算的会话必然已被加载进内存,无需扫盘)。
- 测试:``tests/test_subagent_report.py`` 新增 9 用例(线程 busy 全会话
  排队、回合中新建会话也排队、线程 idle 恢复、空线程 no-op、线程 refill
  全会话重置、未知线程 no-op、react 包装器忙/闲转换、生成器提前 close
  清 busy);``tests/test_realtime_cerebrum.py`` 新增 1 用例(网关人工
  回合 refill 预算,ws 端到端);react 全量 358 项 + 网关 95 项 +
  report/ephemeral/session 183 项回归全绿,ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- ``on_report`` 唤醒钩子生产接线:空闲 owner 开新回合需要网关持有该
  线程的活动连接/emitter 才能安全实现;当前 wakeup 报告在存储层语义
  正确(预算、忙碌判定、queued 排队),但不会主动撬起新回合,待回合
  调度器接入。
- 回合内「下一步」注入(同第 34 节):``queued`` 报告等下一次续会话/
  新回合读取,不保证同回合可见;steering 通道(``_turn_steering`` 队列)
  是现成的注入位——已由第 38 节落地:``queued`` 报告会直接进正在跑的
  父回合下一步,不再等新回合。

## 36. per-session ``user/message`` 进 journal + 纯 journal 投影

第 33 节的 ``surface_events_from_journal`` 里,user 泳道仍靠调用方
传 ``prompts``——因为 journal 的 ``user/message`` 只写父会话/goal
维度,没有 subagent 会话关联。本轮补上最后一环,让投影的 user 泳道也
来自日志,表面真正「纯 journal」:

- ``_journal_models.py``:``UserMessageEvent`` 新增 ``session_id: str =
  ""``(纯 schema 追加,旧事件按空串兼容);无 ``goal_source`` 的行 fold
  依旧忽略,不会污染 goal 轮次记账。
- ``_journal_base.py``:``write_user_message(text, *, goal_source=None,
  session_id="")`` 透传 ``session_id``。
- ``_ephemeral_events.py``:新增 ``_emit_sub_user_message(session_id,
  text)``——best-effort 把会话的 user prompt 作为 ``user/message`` 行
  落盘(带 ``session_id``),沿用 current_session→journal 查找;空
  session_id(一次性/远端子进程)直接跳过,telemetry 损失绝不打断 runner。
- ``ephemeral_runner.py``:单发与 agentic 两条路径在 ``call.role.id``
  解析处各调用一次 ``_emit_sub_user_message(session_id, call.user_prompt)``
  ——每个可续会话的每轮 turn 先落 user prompt,再逐 chunk 落散文。
- ``derive.py``:重写 ``surface_events_from_journal``——按日志写入顺序
  逐事件把该会话的 ``user/message`` 与 ``sub_text_delta`` 交错成 dsh
  surface(一轮 turn 自然呈现「prompt → 散文」);只有当日志里没有该会话
  的 ``user/message`` 行(旧会话/一次性)才回退到 ``prompts`` 参数 +
  按 round 交错。
- 测试:``tests/test_sub_text_delta_event.py`` 新增 5 用例(emit helper
  落带 session_id 的 user/message 行、``write_user_message`` 透传
  session_id、纯 journal user 泳道优先于 prompts、多轮交错且不泄其它
  会话、纯 journal 桥→投影端到端),全套 18 用例通过;journal/ephemeral/
  session/reference/goal 回归 179+ 项通过,ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- 会话关闭/汇总事件:dsh 还会落 session 级生命周期与 token 汇总行,
  我们只有 user prompt 与流式散文;如需 resume 时给出「该会话此前用了
  多少 token / 是否 close」可再补。

## 37. 会话级 turn 汇总行进 journal + resume 汇总派生

第 33/36 节把 subagent 会话的散文(user/message + sub_text_delta)落进了
journal,但结构化「这轮用了多少轮次、成没成功、报了什么错」仍只存在
turn store。本轮补上 dsh 的会话结果面:每完成一轮 turn 落一条
``sub_session_summary`` 行,resume 不必逐 chunk 重放也能给出会话的努力/
结果概览:

- ``_journal_models.py``:``SubSessionSummaryEvent``(event_type
  ``sub_session_summary``,字段 ``session_id`` / ``agent_id`` / ``rounds`` /
  ``success`` / ``error``),``JournalEventType`` 同步登记;JSONL 回环无损。
- ``_journal_parse.py`` 注册;``__init__.py`` / ``journal.py`` 导出。
- ``_ephemeral_events.py``:新增 ``_emit_sub_session_summary(session_id,
  *, agent_id, rounds, success, error)``——沿用 current_session→journal
  查找,空 session_id(一次性/远端子进程)跳过,best-effort 不打断。
- ``bridge.py``:在 ``append_turn`` 之后(``status != "rejected"`` 分支内)
  以懒导入调用一次,携带 ``agent_id`` / ``max_round`` / ``ok`` /
  ``error``——与用户消息、流式散文同一会话日志,三行合成一个会话的完整
  故事。
- ``derive.py``:``derive_session_summaries(journal, *, session_id=None)``
  按日志顺序重建每轮完成记录(``SessionSummary``),可按会话过滤,与
  ``derive_subagent_streams`` / ``surface_events_from_journal`` 互补。
- 测试:``tests/test_sub_text_delta_event.py`` 新增 3 用例(事件注册+JSONL
  回环、emit helper 落带字段行、按会话过滤派生),全套 21 用例通过;
  journal/ephemeral/session/reference/goal 回归 183 项通过,ruff/invariant
  干净。

### 尚未覆盖(dsh 有而这里没有)

- token/cost 汇总:目前汇总行只有轮次与成败,没有实际 token/成本——
  dsh 会在会话日志里带 usage 行;若 resume 要报「此前花了多少 token」,
  需从模型响应/成本记账里取数再补一列。(已由第 41 节收口。)

## 38. 回合内注入:``queued`` 报告直进正在跑的父回合(steering 通道)

第 34/35 节把「忙碌 owner → ``queued`` 排队」接进了生产,但排队报告仍
要等父进程下一次续会话/新回合才被读到——dsh 的 ``inject`` 是排进正在
跑的回合下一步,同回合可见。本轮用现成的 steering 队列补上这条 live
通道:

- 网关注册表(``_realtime_cerebrum_steering.py``):新增线程级
  ``thread_id → (runtime, turn_id)`` 映射(``_THREAD_TURN_REGISTRY`` +
  锁),``_register_active_turn`` 注册、``_unregister_active_turn`` 注销
  (按 (runtime, turn_id) 精确匹配,不误删新回合)。
- ``_inject_thread_steering(thread_id, text)``:把文本作为
  ``SteeringUserMessageItem`` 塞进该线程活跃回合的 ``_turn_steering``
  SimpleQueue(``put`` 线程安全,子代理报告落在 worker 线程也能投),
  并 append 到 ``turn.items`` 让最终快照可见;``_turn_steering_accepting
  = False``(回合收尾中)或无线程活跃回合时返回 False 不投。react loop
  的 ``steering_drain`` 在最近的 step 边界取走——正是 dsh inject 的
  「下一次 step 消费」。
- store 桥接(``sessions.py``):``append_report`` 判定为 ``queued`` 时
  落盘后 best-effort 调 ``_try_inject_queued_report(thread_id, content)``
  ——内容截断到 1500 字符并加 ``[子代理报告]`` 前缀,懒加载网关模块、
  异常吞掉;无网关/无活跃回合/回合已收尾一律 no-op。持久副本仍在
  ``pending_reports``,回合没来得及消费也不丢(不是「要么注入要么丢」,
  而是「live 加速 + durable 兜底」)。
- 测试:``tests/test_realtime_cerebrum.py`` 新增 4 用例(注册→注入→
  drain 取回、非 accepting/未知线程不投、空线程 no-op、注入→
  ``_drain_turn_steering`` 配对);``tests/test_subagent_report.py`` 新增
  4 用例(queued 触发注入、wakeup/quiet 不注入、截断、注入失败不破坏
  落盘);回归 react 358 + gateway 99 + report/session 134 全绿,
  ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- 注入上限:每次 queued 报告都会注入(与 dsh 每个完成通知都 inject
  一致),靠报告工具引导与单条截断防刷屏,没有 per-turn 注入次数预算。
  (已由第 44 节收口;注入持久化可见性已由第 40 节收口。)

## 39. host 会话候选 API 端点(subagent mention 自动补全后端面)

第 30 节落地了 resolver 的 ``list_candidates`` 与 host ``resolve_mentions``,
但「前端键入 ``@session:`` 时弹候选」那条路还没接——缺一个后端候选源。
本轮把 dsh 的 host candidate seam 以 REST 端点补上(纯后端 + 测试,前端
后续可直接消费,不碰并行进程在改的 UI 组件):

- ``subagents_router.py``:新增 ``GET /api/subagents/sessions``——返回
  ``{"candidates": [{sessionId, label, createdAt}, ...]}``,由
  ``SubagentSessionStore.list_reference_candidates`` 按工作目录亲和度
  排名,支持可选 ``query`` 子串过滤与 ``target`` 排除;``limit`` 钳制到
  [1, 200];store 不可用返回空列表(200)。路由注册在
  ``/api/subagents/{name}`` 之前,避免被 path 参数吞掉。
- 复用现有鉴权(_auth),与 ``list_subagents`` 同为 actor-agnostic 候选
  发现。
- 测试:``tests/test_subagents_router.py`` 新增 2 用例(候选列出、
  query/target 过滤 + store 缺失降级),router 全套 7 用例通过;
  ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- 前端交互层:弹候选/选后插入 ``@session:<id>`` token 的 UI 还没做
  (dsh 的 host autocomplete);端点已就绪,前端可接。

## 40. 回合启动浮现全部待读报告 + 注入持久化(EventLog 可见)

第 38 节的 live 注入只覆盖「回合正在跑」的窗口:报告排队时若父回合
不活跃,要等父进程续会话才读;且注入只进 ``turn.items``,重放客户端
看不到。本轮把 dsh 的「下次唤醒即消费」补全到这两个缺口:

- 回合启动浮现(``realtime_turn_lifecycle._start_turn``):新回合在
  ``_register_active_turn`` 之后、``turn_started`` 之前,枚举
  ``store.pending_thread_reports(thread_id)``——该线程名下所有子代理
  会话的未投递报告——逐个 ``inject_report_into_thread`` 注入;注入
  成功即 ``mark_reports_delivered(up_to_index=index)``,同一条报告不会
  在多次回合反复浮现;store 缺失/任何异常一律吞掉,永不阻塞回合。
- 注入持久化(``_realtime_cerebrum_steering._inject_thread_steering``):
  注入入队后同步把 ``item_completed`` 写进该线程 EventLog(append 有
  锁保护,worker 线程可写),重放/重连客户端能看到这条注入;同时把
  item.id 提前塞进 ``_turn_steering_seen``/``_turn_steering_notified``,
  防止 steering sync 从日志行再投一次(双投防护);日志写失败
  best-effort 吞掉,live 队列投递不受影响。
- store 面(``sessions.py``):``_try_inject_queued_report`` 改名公开为
  ``inject_report_into_thread``(返回是否真的入队);新增
  ``pending_thread_reports(thread_id)`` 跨会话汇总未投递报告(按
  ``reports_delivered_up_to`` 过滤,每会话由旧到新)。
- 测试:``tests/test_realtime_cerebrum.py`` 新增 2 用例(注入写 durable
  日志且不双投、ws 端到端回合启动浮现待读报告且 ack 后 pending 清空);
  ``tests/test_subagent_report.py`` 新增 2 用例(跨会话 pending 汇总、
  公开 seam);回归 report/realtime 139 + react 337 全绿,ruff/invariant
  干净。

### 尚未覆盖(dsh 有而这里没有)

- 注入上限:与第 38 节同一限制,per-turn 注入次数预算仍无。(已由第 44 节收口。)

## 41. 会话级 token/cost 归因与汇总行 (`_ambient` + journal)

第 37 节汇总行只有轮次与成败,resume 报不出「该会话此前花了多少
token」;同时子代理的模型消耗虽然进了进程级 ``UsagePricing``(cost
ceiling 可 gate),但会话日志里没有任何 usage 行。本轮把 dsh 的
「会话日志带 usage」补齐到整条链路:

- 环境归因(``runtime/execution/subagents/_ambient.py``):新增
  ``subagent_session_scope(session_id)`` ContextVar——bridge 在
  ``_do_call`` 里把 durable 会话 id 包在子代理运行外(worker 线程
  各自持有 context,并发子代理互不串);未设置时(父回合/一次性/
  远端子进程)取 ``""``,usage 行不带归因,优雅降级。
- 生产侧(``react_model_stream._phase_6b_model_stream``):子代理的
  react loop 每次模型调用写 ``token_usage`` 行时带上
  ``session_id=_ambient_subagent_session_id()``——同一行事件模型
  新增字段(纯 schema 追加,旧事件按空串兼容);进程级 ledger 记账
  不变(cost ceiling 照旧 gate)。
- 汇总侧(``_ephemeral_events._emit_sub_session_summary``):写
  ``sub_session_summary`` 行前扫日志中该 ``session_id`` 的
  ``token_usage`` 行,累加 input/output/cost 进汇总行——resume
  从日志一行拿到「该会话累计 token/成本」,无需逐 chunk 重放;
  无归因行(父回合/一次性)永不匹配。
- 派生面(``derive.derive_session_summaries``):``SessionSummary``
  新增 ``input_tokens`` / ``output_tokens`` / ``cost_usd`` 字段,
  旧汇总行(无 usage 字段)按 0/0/0.0 兼容。
- 测试:``tests/test_subagent_usage_attribution.py`` 新增 11 用例
  (ambient 设置/复位、线程隔离、core stream helper 读 scope、
  ``write_token_usage`` 归因 JSONL 回环、零 token no-op、无归因
  保持空、汇总只累加本会话行、无会话 no-op、derive 带 usage +
  legacy 零值、汇总行 JSONL 回环、无 journal best-effort)。

### 尚未覆盖(dsh 有而这里没有)

- 回合内逐行 usage 事件:我们只落回合结束的汇总行,不落每次模型
  调用的独立 usage 事件行(token_usage 行带归因但消费方只看汇总);
  dsh 的 token-meter 逐次事件流若要精确到调用粒度可再补。

## 42. goal 流式 surface:增量投影缓存 + as-of 水位
    (`goals/projection.py`)

dsh 把当前目标作为 session projection 提供:last-wins fold 由
``goal/change`` 行增量维护,消费方通过 ``useProjection('goal')`` 拿到
带 ``asOfSeq`` 水位的视图,不需要每次全量重放。我们此前
``GoalService.current()`` 每次读都 O(n) fold(正确的 CAS 真相源,但
作为读面太贵)。本轮把 dsh 的 projection 读面搬过来:

- ``GoalProjectionCache``(``goals/projection.py``):seed-once 缓存——
  构造时从 journal 全量播种一次(跳过 malformed 行,绝不让坏行破坏
  读面),之后 ``current()`` O(1) 返回 ``GoalProjection``
  (``folded`` + ``as_of`` 水位 = 已应用的 scope 内 goal_change 行数,
  消费方可按水位排序帧);live journal(``StreamingJournal``)经事件桥
  订阅增量推进,base journal 由 service 自身写入 push 推进(不双推,
  双推会触发严格转移校验失败)。
- ``GoalService.surface()``:service 构造时自动建缓存并接入——每个
  verb 提交后缓存同步推进,``surface()`` 读 O(1);``current()`` 保持
  全量 fold 作为 CAS 权威(缓存只做读面,永不当写入真相)。
- 顺带修掉一个与 dsh 对齐的真实 bug:``_transition`` 之前把当前
  ``blocked_reason`` 复制进 pause/resume/complete 的下一快照,而严格
  解码器要求非 blocked 快照不得携带 reason(dsh ``withPhase`` 只在
  ``block`` 附加 reason),导致 blocked→complete 触发
  ``GOAL_INVALID_BLOCK_REASON``;现在转移快照一律不带 reason,
  blocked→complete 可正常完成且回放严格解码通过。
- 测试:``tests/test_goal_projection.py`` 新增 11 用例(播种与
  current 一致、base journal 不重读的 O(1) 读面、水位只计 scope 内
  goal_change、共享 journal 的 scope 隔离、live 订阅同步推进且跨
  writer 隔离、malformed 行跳过、全生命周期 parity、close 停止更新、
  非法 push 静默拒绝、blocked→complete 无 reason + 严格解码回放);
  goal 域回归 40 项 + 关联 158 项全绿,ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- 多目标历史归档:目前 fold 只投影当前目标,已 complete/clear 的目标
  时间线视图未接(可后续从 goal_change 行派生历史列表)。(已由
  第 43 节收口。)

## 43. goal 历史归档时间线 (`goals/projection.derive_goal_timeline`)

第 42 节补了「流式 surface」,但历史归档仍缺:dsh 在 clear 后保留
durable tombstone 与 history。本轮从 append-only ``goal_change`` 行
派生时间线视图——一个目标一条档案,resume/审计可回答「此前完成过
哪些目标、各花了多少轮」:

- ``derive_goal_timeline(journal, *, agent_id=None, conversation_id=None)``:
  按日志顺序逐行解码 scope 内 ``goal_change``,按 goal id 归组——create
  建档(objective/created_at/phase),后续变更推进最终 objective/phase/
  updated_at/rounds/revision,clear tombstone 标记 ``final_phase="cleared"``
  + ``cleared_at``(只见过 tombstone 的部分日志也归档该 ref,绝不 crash);
  malformed 行跳过;返回按建档顺序的 ``GoalTimelineEntry`` 列表。
- 与第 42 节的投影缓存互补:缓存是「当前目标 O(1) 读面」,时间线是
  「历史目标只读归档」;两者都 scope-aware、都容忍坏行、都不改写入面。
- 测试:``tests/test_goal_projection.py`` 新增 3 用例(全生命周期三目标
  归档顺序与 final_phase/revision/cleared_at、跨 writer scope 隔离、
  malformed/无关事件跳过、无 create 的 tombstone 仍归档);goal 全套
  55 用例通过,ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- 目标历史的分页读取:时间线目前全量派生,大日志多目标时无分页游标;
  单会话目标数量天然有限,列为后续。

## 44. 回合内注入 per-turn 预算(防报告刷屏的生产收口)

第 38/40 节把 ``queued`` 报告直进正在跑的父回合,但每次报告都会注入,
没有次数上限——子代理多/吵时会把单个回合的上下文与模型调用次数打爆。
本轮补上 dsh 语义的生产防刷闸:每个活跃回合给子代理报告注入一个
per-turn 预算,超出部分留在 durable ``pending_reports``,下次唤醒/
续会话再投,而不是一次性淹没当前回合。

- 预算面(``_realtime_cerebrum_steering.py``):新增
  ``_max_turn_steering_injections()``(``OCTOPUS_MAX_TURN_STEERING_
  INJECTIONS`` 环境可覆盖,默认 20);``_register_active_turn`` 为该回合
  初始化 ``runtime._turn_steering_budget[turn.id]``,
  ``_unregister_active_turn`` 注销。
- 闸口(``_inject_thread_steering``):报告专用注入入口在入队前检查预算,
  剩余 ≤ 0 直接返回 False——报告仍在 ``pending_reports`` 持久副本,不
  会丢;每次成功注入递减。只作用于子代理报告注入:用户的显式
  ``turn/steer`` 走另一路径(``_realtime_cerebrum_requests``),不受报告
  预算约束,手动指令永远即时注入。
- 兼容:无预算字典的运行时(旧代码/手搓测试 harness)走 legacy 无上限
  路径,回归不受影响。
- 测试:``tests/test_realtime_steering.py`` 新增 1 用例(预算=2 时第 3 条
  注入被拒、drain 只取回预算内两条、预算耗尽后用户 steer 仍即时注入);
  steering/realtime_cerebrum/subagent_report/sessions/react_loop/goal 共
  539 项通过,ruff/invariant 干净。

## 45. bounded 投影吃真实 journal 事件(checkpoint 事件源)

第 24 节落地投影算法时,``transcript_prompt(bounded=True)`` 仍从 turn
store 重建表面事件(Q/A 对)——而第 36/41 节已经把会话的真实故事
(``user/message`` + 逐 chunk ``sub_text_delta``)写进 journal。本轮把
投影源切到真实日志,收口「checkpoint 事件源」:

- ``sessions._surface_events_prefer_journal(session)``:有当前进程
  session 的 journal 且其中存在该会话的 ``user/message`` 或
  ``sub_text_delta`` 行时,调 ``surface_events_from_journal`` 直接喂
  ``retain_session_reference``——模型续会话看到的是它真正流式产出
  过的散文(round 交错),不是压缩后的 Q/A;journal 不可达/无该会话
  行(legacy/一次性)回退 turn-store 重建,行为零变化。
- ``_current_journal()`` / ``_journal_has_session_rows()``:沿用
  ``_ephemeral_events`` 的 current_session→metadata/stack 取 journal
  模式;读失败/坏行一律回退,绝不把转录路径变成错误来源。
- 测试:``tests/test_transcript_journal_projection.py`` 新增 5 用例
  (journal 行优先且 turn 文案不泄漏、无 journal 回退、journal 无本会话
  行回退且不串别会话、journal 路径尊重投影预算、多轮交错);subagent/
  projection/reference/journal 关联 119 项全绿,ruff/invariant 干净。

### 尚未覆盖(dsh 有而这里没有)

- 通用 ``@session-reference`` resolver 面(任意 session URI → 投影注入,
  非 subagent 专用):第 27/30 节已建 resolver + host mention 接线,
  通用 URI 解码仍留作后续。

## 用法速查

```bash
# 快照
./.venv/bin/python -m pytest tests/test_snapshot_bugfix_demo.py --snapshot-update  # 记录
./.venv/bin/python -m pytest tests/test_snapshot_bugfix_demo.py                     # 回放

# 沙箱
OCTOPUS_PROCESS_SANDBOX=landlock python -m runtime ...   # Linux
OCTOPUS_PROCESS_SANDBOX=strict python -m runtime ...     # 无后端则拒绝执行
```

---
name: octopus-mix-virtual-model
description: /v1/chat/completions 的 octopus-mix 虚拟模型(Mixture-of-Agents;**用户要求产品名叫 Mix 不叫 moa**);proposers 无工具并行+aggregator 持工具综合;已接进 ModelPicker
metadata:
  node_type: memory
  type: project
  originSessionId: ff25d56e-cd25-4c88-9ed5-a162bd9c628b
  modified: 2026-08-12T05:29:33.779Z
---

**背景**:对标 Nous **Hermes MoA** / 日本 **Sakana Fugu**(编排>单模型趋势)。octopus 本就是完整 runtime + 早有 `/v1/chat/completions` + `call_agent_parallel`/`run_orchestration` 原语,只差把多模型 propose→aggregate 接成一个虚拟模型。**产品名定为 Mix(id `octopus-mix`),用户明确不要叫 moa。** 见 [[octopus-agent-multiagent-gap]]。

**后端 `runtime/sensing/gateway/openai_gateway/mix.py`**:
- proposers:N 个**并行、无工具**(复用 `_direct_llm_fallback_with_usage`,天然不走 planner/tools);不同 model(池)+ 不同 reasoning lens(单模型部署也成 ensemble);`ThreadPoolExecutor` + **per-task `contextvars.copy_context().run`** 传 actor/session ContextVar 进线程。
- aggregator:草稿格式化成 **trailing `system` 消息**注入 `user_context["conversation_messages"]`(+ `mix_proposals`),复用**注入进来的** `_run_chat` 跑**完整 turn=持工具**。
- 降级:0 草稿→普通 turn,不报错。`mix_sse_frames` 出标准 OpenAI SSE(stream=true 也可用)。
- 循环 import:`_run_chat` 在 router 文件→**依赖注入**(`run_mix_chat` 收 `run_chat` 参数)。
- 常量/函数:`MIX_MODEL_ID="octopus-mix"`;`is_mix_model`/`mix_model_ids`/`run_mix_chat`/`mix_sse_frames`。result["octopus"]["mix"] 带 provenance。
- **env**:`OCTOPUS_MIX_PROPOSERS`(逗号池)/ `OCTOPUS_MIX_AGGREGATOR` / `OCTOPUS_MIX_N`(默认3,上限6)。
- router 接 3 处:import / `_list_openai_models` 露出 / `_chat_completions_impl` **reflex 之前**分流(molili `current_actor` + `journal_context` 包裹)。

**前端 ModelPicker 露出**:
- `config_router.py` 的 `/api/llm-models`(ModelPicker 实际读的端点,**不是** /api/models)加 `octopus-mix` preset(`provider:"octopus"`、置顶、持工具)。
- `model-picker.tsx`:给 `officialMetas` **条件注入** `MIX_META`(仅当 models 含 octopus-mix 时)→ 归入 **Official tab**(语义对,非 Custom);保住"无 official→落 Custom""推荐 badge 计数"原语义。

**验证全绿**:`test_mix.py` 7 + `test_llm_models_mix.py` 1 + `test_openai_gateway.py::TestMixVirtualModel` 3(端到端 TestClient)+ `model-picker.test.tsx` 15(含正向用例)+ 93 gateway 回归 + 36 config 回归 + ruff/invariant/typecheck/eslint 净。**openapi 快照无变**(没加路由,只改运行时返回值)。`ParsedIntent` frozen→`model_copy(update=)`;`make lint-invariants` 用裸 python 坏,走 `.venv/bin/python -m tools.lint.invariant_check`(见 [[octopus-agent-dev-environment]])。

**已提交三 commit(分支 `feat/octopus-mix-virtual-model`,基于 feat/tool-migration,未 push)**:
- `24b35477` — 编排 mix.py + /v1 接线 + ModelPicker 露出 + moa→mix 改名(6 文件)。
- `2a4a9f42` — **UI 可配池**(7 文件):mix.py `load/save_mix_config` 持久化 `~/.octopus/mix_config.json`(优先级 **config>env>默认**);`GET/PUT /api/mix-config` 鉴权端点(在 openai_gateway_router,非 config_router);设置页 `MixSettingsSection`(多选 proposer + aggregator + 数量,挂在 model-settings-page 的 ModelCookbook 后)。

- `831b2b3e` — **/api/llm-models 露出 octopus-mix**(让 ModelPicker 显示)+ test_llm_models_mix.py。config_router 同文件混了并发会话的 omit_system_messages/thinking_wire_format,故用 **HEAD-swap 法**只 stage mix preset:`cp` 工作树备份 → `git show HEAD:config_router.py >` 覆盖工作树 → python 注入 mix preset → `git add`(index=HEAD+mix,纯净)→ `cp` 备份还原工作树 → commit。绕开并发(它们留工作树未 staged)。**`git apply --cached` 那条 hunk 因 whitespace/上下文匹配失败,HEAD-swap 才是可靠解法。**

**红线守住**:三个 commit 都没卷入并发会话的在途改动(config_router 的 omit/thinking 仍在工作树未 staged,待其 owner 自提)。至此 **Mix 全链路落地**:后端编排 + UI 可配池 + ModelPicker 显示。

**已开 PR [#3](https://github.com/dengdenghua/octopus-agent/pull/3)**(base=main,2026-06-28):`git push -u origin` 分支 + `gh pr create`,**不直接动公开 main**(用户选「开 PR」让其 review 后自合)。**重要**:本地 `main` 比 `origin/main`(42cd37c0)**领先 8 个未 push commit**(cookbook/searxng/storage),Mix 分支基于它们 + migration(05e72ec7),故 PR diff 连带这 8+migration(Mix 依赖 cookbook 等无法剥离,已在 PR 描述说明)。`gh` 已认证(repo/workflow scope)。

**下一步(未做)**:① learned conductor(像 Fugu 训练,重投入暂缓);② 把 Fugu/Hermes 当后端模型接进池。子代理常规路由仍 cheap/primary 二档,见 [[octopus-agent-subagent-model-routing]]。

**坑**:`model-settings-page.test.tsx` 有 2 个 **pre-existing 失败**(custom-model 渲染:My OpenAI/Single 找不到)——根因是 ModelCookbook 等 on-mount fetch 打乱了顺序依赖的 `mockResolvedValueOnce`,**与 Mix 无关**(已用 pathspec-scoped `git stash` 还原到 HEAD 验证同样失败)。我的 test 里 `vi.mock("./mix-settings-section")` 是防御性隔离。

**Mix 池与三档成本标签协同(2026-08-12, 未提交)**:`_proposer_pool`/`_aggregator_model` 在无显式配置(预设/UI 的 mix_config.json > env `OCTOPUS_MIX_*`)时,从 custom_models.json 的三档标签兜底推断(见 [[octopus-agent-subagent-model-routing]])。**proposer 只取 economy+balanced 标签**(草稿要便宜,performance 明确排除);**aggregator 取 performance 优先、balanced 兜底**(综合要强),sorted 确定性。实现:`mix._read_tagged_catalog` 按 tier 分组 + `_tagged_proposer_pool`/`_tagged_aggregator_model`;复用 `custom_model_flags.read_custom_models`。**显式配置永远优先**,标签只是兜底。测试 `test_mix.py` 21 绿(新增 8 个标签推断测试 + autouse `_no_custom_models` fixture 隔离真实目录)。**注意**:dangbei 真实 `~/.octopus/mix_config.json` 有显式 proposers=[agnes, deepseek, kimi-k3](用户 UI 配的,performance 的 kimi 也在草稿池里,用户自己的选择)但 aggregator 留空——旧代码 aggregator 空→planner 默认,新代码 aggregator 空→标签推断 **ark-code-latest**(行为变化点,已告知用户可显式配 aggregator 覆盖)。docs/auto gateway.md 采集 mix.py docstring,改动后需 gen_wiki。

**执行意图跳过 proposer(2026-08-12, 已提交 55b6cff9,分支 codex/local-cli-partner-polish)**:用户质疑「Mix 三个人都不执行工具不工作」。实证确认 proposers 无工具(纯起草,只进 `_direct_llm_fallback` 不碰 planner/tools)、aggregator 持完整工具(`_run_chat`)。**最优解=意图感知降级**:`_skip_proposers_reason(intent)` 命中执行动词(中文动作动词表 + 英文 word-boundary 正则表,见 mix.py `_EXECUTION_VERBS_ZH/EN`)→ `run_mix_chat` 跳过 proposer 阶段,直接在 aggregator 模型上跑单个完整工具 turn(meta 记 `skipped_proposers:"execution_intent"`/`proposers:0`)。分析/综合类请求保留完整 MoA,且 `_format_proposals` 强化提示词(草稿是起点 **NOT** 交付物,必须用工具真正完成,别复述)。**保守设计**:漏匹配退回原 MoA(旧行为),误匹配只是少一轮提案。测试 +6,mix 27 绿 + gateway 54 绿;全量 10685 passed(16 failed 为并发会话删 replay/page.tsx 等页面导致的 evolution/parity pre-existing)。

**aggregator 复杂度选档(2026-08-12, 已提交 6049696b)**:用户「要」让自动档 aggregator 吃复杂度信号。`_aggregator_model(intent)` 接 intent,未显式配置时 `_complexity_flag(intent)` 用 `estimate_turn_complexity(goal)`(与 stream_handler fast-path 同一判定,惰性 import)判定档位 → `_tagged_aggregator_model(complex_turn)`:**performance 判定 → 只选 performance 档绝不降级**(无则回 planner default,同 never-demote 契约);**local/value 判定 → 优先 balanced、无才升 performance**;聚合器永不取 economy(须强于起草者)。intent None → 历史 performance→balanced 兜底。显式配置/env 永远优先。两处调用点(skip 路径 + 常规 MoA 路径)都传 intent。测试 +6,既有端到端 tagged-flow 测试扩展为简单+复杂双断言。mix 33 绿 + gateway 27 绿;全量 10688 passed(19 failed 均并发会话 pre-existing)。

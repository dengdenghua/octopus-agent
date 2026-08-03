# Tasks

## 第一批：最低风险（纯函数/数据/配方）—— ✅ 已完成

- [x] Task 1: 拆分 `browser_desktop_repair_recipes.py` (1321→522)
- [x] Task 2: 拆分 `llm_planner.py` (1122→720)
- [x] Task 3: 拆分 `realtime_event_bridge.py` (1228→965)
- [x] Task 4: 拆分 `realtime_team_stream.py` (1359→234)
- [x] Task 5: 拆分 `openai_compat_providers.py` (1428→950)
- [x] Task 6: 第一批验证与基线更新

## 第二批：低风险（路由器/桥接/技能，14 文件）

- [x] Task 7: 拆分 `agents_local_partner.py`（已不在基线）
- [x] Task 8: 拆分 `runtime/execution/subagents/bridge.py` (1099→991)
- [x] Task 9: 拆分 `runtime/sensing/gateway/agent_world_router.py` (1048→579)
- [x] Task 10: 拆分 `runtime/sensing/gateway/evolution_router.py` (1310→964)
- [x] Task 11: 拆分 `runtime/safety/recovery/gepa_bridge.py` (1281→885)
- [x] Task 12: 拆分 `fs_router.py`（已不在基线）
- [x] Task 13: 拆分 `runtime/execution/suckers/browser_skills.py` (1124→965)
- [x] Task 14: 拆分 `runtime/sensing/gateway/channels_router.py` (1653→670)
- [x] Task 14b: 拆分 `runtime/execution/suckers/code_intelligence_skills.py` (1105→563)
- [x] Task 14c: 拆分 `runtime/execution/suckers/ephemeral_runner.py` (1037→691)
- [x] Task 14d: 拆分 `runtime/execution/suckers/memory_skills.py` (1091→713)
- [x] Task 14e: 拆分 `runtime/execution/swarm/runtime.py` (1080→677)
- [x] Task 14f: 拆分 `runtime/memory/cowork/store.py` (1036→853)
- [x] Task 14g: 拆分 `runtime/research/deep_research.py` (1166→367)
- [x] Task 14h: 拆分 `runtime/tentacle/dashboard.py` (1065→742)
- [x] Task 14i: 拆分 `runtime/tentacle/mobile/mcp_server.py` (1109→722)
- [x] Task 15: 第二批验证与基线更新（25 项）

## 第三批：中风险（核心执行/记忆，8 文件）

- [x] Task 16: 拆分 `runtime/platform/process/task_supervisor.py` (1285→578)
- [x] Task 17: 拆分 `runtime/core/cerebrum/react_context.py` (1210→81)
- [x] Task 18: 拆分 `react_prompt_assembly.py`（已不在基线）
- [x] Task 19: 拆分 `runtime/execution/loops/controller.py` (1517→381)
- [x] Task 20: 拆分 `mount_backend.py`（已不在基线）
- [x] Task 21: 拆分 `runtime/platform/ui/health_router.py` (1591→398)
- [x] Task 22: 拆分 `runtime/execution/parallel_agents/orchestrator.py` (1249→521)
- [x] Task 23: 拆分 `runtime/memory/journal/journal.py` (1555→567)
- [x] Task 24: 拆分 `runtime/sensing/gateway/config_router.py` (1662→449)
- [x] Task 25: 拆分 `runtime/cli.py` (1601→400)
- [x] Task 26: 第三批验证与基线更新（17 项）

## 第四批：中高风险（大路由器/UI）—— ✅ 已完成（此前会话）

- [x] Task 27: 拆分 `runtime/sensing/gateway/team_tasks_router.py` (1744→<1000)
- [x] Task 28: 拆分 `runtime/sensing/gateway/observability_router.py` (1583→<1000)
- [x] Task 29: 拆分 `runtime/platform/ui/browser_router.py` (1767→<1000)
- [x] Task 30: 拆分 `runtime/sensing/gateway/meta_router.py` (1717→<1000)
- [x] Task 31: 拆分 `runtime/platform/ui/chat_page.py` (1930→<1000)
- [x] Task 32: 拆分 `runtime/sensing/gateway/agents_router.py` (1797→<1000)
- [x] Task 33: 拆分 `runtime/sensing/gateway/realtime_cerebrum.py` (1433→<1000)
- [x] Task 34: 拆分 `runtime/execution/tool_engine/executor.py` (1714→<1000)
- [x] Task 35: 拆分 `runtime/platform/ui/reflex_admin_router.py` (2021→<1000)
- [x] Task 36: 第四批验证与基线更新

## 第五批：高风险（核心 cerebrum/执行引擎）—— ✅ 已完成

- [x] Task 37: 拆分 `react_execution.py`（2304→107）
- [x] Task 38: 拆分 `runtime/core/cerebrum/react_guards.py` (2316→603)
- [x] Task 39: 拆分 `runtime/execution/suckers/write_skills.py` (2396→696)
- [x] Task 41: 拆分 `runtime/platform/ui/app.py` (2612→146)
- [x] Task 42: 拆分 `runtime/core/cerebrum/react_parsing.py` (3388→317)
- [x] Task 43: 拆分 `runtime/execution/suckers/delegation_skills.py` (3465→758)
- [x] Task 44: 拆分 `runtime/sensing/gateway/tool_bridge.py` (3883→235)
- [x] Task 45: 第五批验证与基线更新

## 最终状态（本次会话）

- [x] Wave 2 拆分 7 文件：`browser_desktop_repair_recipes`(1321→537)、`agents_local_partner`(1283→549)、`realtime_team_stream`(1359→30)、`fs_router`(1417→190)、`mount_backend`(1523→65)、`_chat_page_html`(1924→22)、`react_prompt_assembly`(1511→166)
- [x] Wave 3 拆分 7 文件：`react_execution`(2304→107)、`react_guards`(2316→603)、`write_skills`(2396→696)、`app`(2612→146)、`react_parsing`(3388→317)、`delegation_skills`(3465→758)、`tool_bridge`(3883→235)
- [x] 全量测试通过（9856 passed，仅并发工作相关的 skill_catalog 测试除外）
- [x] 文档已重生成（`scripts/gen_wiki.py`）
- [x] `god_file_check --strict` 与 `orphan_module_check --strict` 均通过
- [x] 基线从 14 项降至 **1 项**：`runtime/sensing/gateway/_tool_bridge_loop.py`（2216 行，单个 2090 行 `stream_agentic_fallback` generator，经用户确认保留在基线，视为不可分割）

# Task Dependencies

- 每批内的 Task 可并行执行
- 每批的验证 Task（15/26/36/45）依赖该批所有拆分 Task 完成
- 批次间顺序执行：第二批完成后再开始第三批

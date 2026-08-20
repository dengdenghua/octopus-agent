---
name: fleet-group-control
description: 母体 octopus-agent 的多设备群控架构盘点 + 新增的 broadcast 群发 MVP（POST /api/tentacle/broadcast）
metadata: 
  node_type: memory
  type: project
  originSessionId: 4b7f74ae-59f7-4bf4-af69-e3bd239ec3fb
---

**多手机群控（一人驱动 N 台）的现状**——2026-06-27 摸清整个 octopus 生态（mobile/agent/enterprise 都在 `/Users/dangbei/Public/octopus/` 下）：

**绝大部分已存在于母体 `octopus-agent`**（不在 mobile 仓）：
- 触手接口：`runtime/tentacle/transport/ws_server.py` `TentacleWebSocketServer`(:8765)，按 tentacle_id 维护连接表，端到端验证过（见 [[tentacle-mother-control]]）。
- 设备池/协调器：`pool.py` `TentaclePool`（all_online/get/select_for_affinity/锁）+ `coordinator.py` `TentacleCoordinator`（决策引擎集成）。
- 云端控制台：`dashboard.py` `create_tentacle_router(coordinator)` = FastAPI :8766，已有设备列表、屏幕流(WS)、remote-input、`POST /api/tentacle/task`(单设备自然语言任务)、VLM分析、MCP SSE。**这就是"控制手机的控制台"，要放到 octoapk 域名下是部署/接入问题，不是从零造。**
- **团队模式 = 可复用的并行编排引擎**：`runtime/execution/parallel_agents/orchestrator.py` `ParallelAgentOrchestrator`（DAG 拓扑排序 `helpers.build_plan` + 并发池 + 聚合 + SSE 事件流，**与执行单元无关**）；高层 `safety/organization/{topology,team_runner}.py`（角色编排）；`team_mode` 标签 chat(VOTE 广播)/cowork(plan-work-synthesize)。复用关键改造点=执行单元接口（agent → 触手 `device.execute(ToolCall)`）。

**唯一真缺口（当时）= 一对多群发扇出**。已补 MVP（2026-06-27，octopus-agent）：
- `runtime/tentacle/fleet.py` `async broadcast(coordinator, task, tentacle_ids=None, *, max_concurrency=8)` —— 复用 `team_bridge.run_device_task`（单设备 runner，永不抛、失败隔离），用 `asyncio.gather`+Semaphore 扇出到选中设备（None=所有在线）+ 聚合 `{ok,total,succeeded,failed,results}`。
- 端点：`POST /api/tentacle/broadcast {task, tentacle_ids?, max_concurrency?}`（dashboard.py，挨着 /task）。
- 测试：`tests/test_tentacle_fleet.py`(7 例) 全绿；回归 team_bridge+coordinator 共 44 passed。跑测试：`cd octopus-agent && .venv/bin/python -m pytest tests/test_tentacle_fleet.py -q`。

**未做（群控的生产级后续）**：DAG 依赖编排（直接复用 ParallelAgentOrchestrator 把执行单元换成设备，~6–10 周分 3 阶段）、设备亲和路由、触手锁集成、故障转移备用机、异构结果聚合(截图/JSON)、web 群控 DAG UI、octoapk 托管控制台 + 配对码绑定。

`octopus-enterprise` ≠ octoapk：是独立的 AI 项目管理 full-stack（React+FastAPI+多租户），仅 HTTP 调母体 LLM 网关；若要做云端控制台，其脚手架可复用但是另一个产品。`api.octoapk.com` 目前=积分中转网关（见 [[account-relay-billing]]）。

Related: [[tentacle-mother-control]], [[mcp-server]], [[account-relay-billing]]。

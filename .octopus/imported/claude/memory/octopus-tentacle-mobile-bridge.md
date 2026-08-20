---
name: octopus-tentacle-mobile-bridge
description: "手机↔agent 的桥早就存在(runtime/tentacle + mobile 的 OctopusMobileClient),别另造"
metadata: 
  node_type: memory
  type: project
  originSessionId: b8b0b7d7-d991-4ccd-bcb4-8f35ce397b1a
---

octopus-agent ↔ octopus-mobile 的设备桥**早已完整存在**,动手前必查 `runtime/tentacle/`:

- **agent 侧**:`runtime/tentacle/` 独立子系统 —— `transport/ws_server.py`(WS JSON-RPC,收 `device/hello`/`device/heartbeat`/`tool/execute`/`tool/result`)、`TentacleCoordinator`(`coordinator.py`,`.pool` 持设备)、`dashboard.py` 的 `create_tentacle_router(coordinator)` 是 **FastAPI APIRouter**,前缀 `/api/tentacle`,暴露 `GET /devices`、`POST /task`(需 `coordinator._decision_engine`,默认没配→400)、screenshot、VLM、屏幕流。独立跑:`python -m runtime.tentacle.mobile.run_server`(WS :8765 / dashboard :8766);**默认不挂主网关(:8000)**。有 `tests/test_tentacle_*.py`。
- **mobile 侧**:`app/.../octopus_mobile/OctopusMobileClient.kt` 用 **WebSocket** 连 agent(同协议);配套 DeviceRegistry/HeartbeatReporter/RemoteControl/ConnectionStateMachine/ToolCallDispatcher + cerebrum/nerves/memory 一整套。MMKV 有 `KEY_OCTOPUS_RPC_URL`/`BRAIN_MODE`/`AUTO_CONNECT`。所以"手机连 agent"**无需新写 Kotlin channel**。

**"手机进群"做法**(commit de8a5b3b):in-process 把 tentacle 挂进主网关 —— `TentacleCoordinator(dashboard_port=None)` + `include_router(create_tentacle_router(c))` + startup hook `await c.start()`,全程 try-guard;前端 `useMobileDevices` 查 `GET /api/tentacle/devices` 合成成员进 [[octopus-family-architecture]] 的群 roster/picker。**剩**:给 coordinator 接 decision engine(`mobile/cerebrum_adapter.CerebrumDecisionAdapter`)才能从群里派任务到手机(`run_server` 自己也没接)。

**教训**(呼应 [[octopus-agent-audit-verification-lesson]]):我没查就在主网关另造了 `/api/mobile/*` HTTP 注册表,跟 tentacle 重复且真手机根本不连它,白写一版又回退。跨仓/跨子系统动手前先 grep 既有实现。

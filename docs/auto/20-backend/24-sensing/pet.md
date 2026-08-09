---
type: "SensingSubsystem"
title: "Sensing · Pet 事件桥"
description: "桌面宠物物理在场事件语义 · agent 状态 / 情绪 / 疲劳 / 在场 / tentacle 事件的权威映射（best-effort）。"
tags: ["backend", "sensing"]
tier: "standard"
---
# Sensing · Pet 事件桥

> 桌面宠物物理在场事件语义 · agent 状态 / 情绪 / 疲劳 / 在场 / tentacle 事件的权威映射（best-effort）。

**Source**: `runtime/pet/`

## Package summary

桌面宠物相关：事件语义映射（Agent 状态 / 情绪 / 疲劳 / 跨设备在场）。

## Exports

- `VALID_EMOTIONS`
- `PetEvent`
- `PetUdpBridge`
- `emotion_event`
- `map_agent_state`
- `map_tentacle_event`
- `presence_event`
- `tired_event`

## Modules

| Module | Summary |
| --- | --- |
| `pet_state_map.py` | 桌面宠物事件映射：Agent 状态 / 情绪 / 疲劳 / 跨设备在场 → 宠物事件。 |
| `udp_bridge.py` | Send mapped pet events to the local Godot sidecar. |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `pet_state_map.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class PetEvent` | 一条宠物事件：事件类型 + 可选负载（JSON-safe，可直接 UDP 发送）。 |
| func | `def map_agent_state(state)` | Agent 运行时状态 → 宠物事件；未知状态返回 None（no-op）。 |
| func | `def emotion_event(emotion, intensity)` | 情绪事件；非白名单情绪返回 None。强度钳制在 [0, 1]。 |
| func | `def tired_event(intensity)` | 疲劳事件；强度钳制在 [0, 1]（默认 0.5 = 中度疲劳）。 |
| func | `def presence_event(online, device_id)` | 在场事件：主人 / 设备上线或离线。 |
| func | `def map_tentacle_event(event_type, data)` | 跨设备在场的桥：TentaclePool 的注册事件 → 宠物在场事件。 |

### `udp_bridge.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class PetUdpBridge` | Best-effort UDP adapter for TentaclePool lifecycle events. |


## Who imports this

**1** file(s) reference this package:

- **`runtime/tentacle/`** · 1 file(s)
  - `runtime/tentacle/coordinator.py`


# Octopus Mobile · 协议规范

> **JSON-RPC 2.0 over WebSocket · 三方架构（client / server / device）**

## 1. 协议基线

- **基线协议**：JSON-RPC 2.0
- **传输**：WebSocket（`wss://` 生产环境 / `ws://` 开发）
- **编码**：UTF-8
- **消息大小**：≤ 4MB（截图 / 文件用二进制帧，不计入此限）

### 1.1 端点

| 端 | URL | 角色 |
|---|---|---|
| Client (Web/IM) | `wss://runtime/api/realtime/client` | 用户接口 |
| Device (Octopus Mobile) | `wss://runtime/api/realtime/device` | 设备接入 |
| Server | 内部（监听上述两个端口）| 中枢协调 |

### 1.2 协议版本

```json
{
  "jsonrpc": "2.0",
  "method": "device/hello",
  "params": {
    "protocol_version": "1.0",
    "client_type": "android_tentacle",
    "client_version": "0.1.0"
  }
}
```

- `protocol_version`：当前 `1.0`
- 客户端在 hello 中声明支持的最高版本
- 服务端选择双方都支持的最高版本协商

---

## 2. 命名空间

Octopus Mobile 复用 octopus-agent 现有 envelope（`item/*`, `cocoloop/*`），
新增 `device/*` 和 `tool/*` 两个 namespace。

| Namespace | 方向 | 说明 |
|---|---|---|
| `device/register` | 设备→Server | 设备注册 |
| `device/hello` | 设备→Server | 协议握手 |
| `device/heartbeat` | 设备→Server | 心跳（30s/次）|
| `device/screen_changed` | 设备→Server | 屏幕状态变化（增量）|
| `device/state_changed` | Server→Client | 设备在线状态广播 |
| `device/lock_acquire` | Server→设备 | 设备锁（多 Arm 互斥）|
| `device/lock_release` | Server→设备 | 释放设备锁 |
| `tool/execute` | Server→设备 | 工具执行请求 |
| `tool/result` | 设备→Server | 工具执行结果（reply to `tool/execute`）|
| `skill/install` | Server→设备 | 远程安装新技能（自进化）|
| `skill/uninstall` | Server→设备 | 远程卸载技能 |
| `skill/list` | Server→设备 | 拉取已安装技能清单 |
| `config/sync_pull` | 设备→Server | 拉取远程最新配置 |
| `config/sync_push` | 设备→Server | 推送本地配置变更 |

---

## 3. 详细消息格式

### 3.1 `device/hello` · 协议握手

**设备 → Server**：
```json
{
  "jsonrpc": "2.0",
  "id": "hello-uuid-001",
  "method": "device/hello",
  "params": {
    "protocol_version": "1.0",
    "client_type": "android_tentacle",
    "client_version": "0.1.0",
    "tentacle_id": "android-abc123",
    "device_meta": {
      "brand": "Xiaomi",
      "model": "Mi 14 Pro",
      "android_version": "14",
      "sdk": 34,
      "abi": ["arm64-v8a"],
      "screen_size": [1440, 3200],
      "screen_density": 480,
      "is_rooted": false
    },
    "capabilities": [
      "android.tap", "android.swipe", "android.input_text",
      "android.get_screen_info", "android.take_screenshot",
      "android.open_app", "android.wait", "android.system_key",
      "android.browser.navigate", "android.browser.get_dom"
    ],
    "auth_token": "JWT-or-psk"
  }
}
```

**Server → 设备**：
```json
{
  "jsonrpc": "2.0",
  "id": "hello-uuid-001",
  "result": {
    "negotiated_version": "1.0",
    "server_version": "octopus-agent/0.9.0",
    "session_id": "sess-uuid-xxx",
    "config_sync_interval_s": 300,
    "heartbeat_interval_s": 30,
    "capabilities_acknowledged": ["..."]
  }
}
```

### 3.2 `device/heartbeat` · 心跳

**设备 → Server**（每 30s）：
```json
{
  "jsonrpc": "2.0",
  "method": "device/heartbeat",
  "params": {
    "tentacle_id": "android-abc123",
    "ts": 1717700000000,
    "online": true,
    "current_app": "com.tencent.mm",
    "screen_on": true,
    "battery": 78,
    "is_charging": false,
    "last_screen_tree_hash": "a1b2c3d4",
    "running_tasks": 0
  }
}
```

### 3.3 `device/screen_changed` · 屏幕变化

**设备 → Server**（按需 + 节流 5s）：
```json
{
  "jsonrpc": "2.0",
  "method": "device/screen_changed",
  "params": {
    "tentacle_id": "android-abc123",
    "ts": 1717700005000,
    "screen_tree_hash": "a1b2c3d4",
    "current_app": "com.taobao.taobao",
    "current_activity": "com.taobao.taobao.TBMainActivity",
    "tree_delta": {
      "added": [{"ref": "e123", "class": "TextView", "text": "立即购买", "bounds": [100, 200, 300, 260]}],
      "removed": [],
      "changed": [{"ref": "e087", "text": "已售 1234 → 已售 1567"}]
    },
    "screenshot_available": true,
    "screenshot_ref": "screenshot://abc123/2024-06-06T10:00:00Z.png"
  }
}
```

**关键设计**：
- **增量上报**（`tree_delta`）：只传变化的部分，不传全量
- **引用追踪**（`ref`）：每节点一个稳定 ID，跨多次上报可追踪
- **延迟拉取**（`screenshot_ref`）：需要时再拉，节省带宽
- **结构化**（非图片 OCR）：让 LLM 看到的是结构化数据，不是噪声

### 3.4 `tool/execute` · 工具执行

**Server → 设备**：
```json
{
  "jsonrpc": "2.0",
  "id": "tool-call-uuid-xxx",
  "method": "tool/execute",
  "params": {
    "tentacle_id": "android-abc123",
    "tool": "android_tap",
    "args": {
      "x": 540,
      "y": 1200,
      "wait_after": 1000
    },
    "timeout_ms": 15000,
    "trace_id": "trace-task-123-step-4"
  }
}
```

**设备 → Server**：
```json
{
  "jsonrpc": "2.0",
  "id": "tool-call-uuid-xxx",
  "result": {
    "success": true,
    "data": "Tapped at (540, 1200)",
    "duration_ms": 234,
    "screenshot_after": "screenshot://abc123/2024-06-06T10:00:01Z.png",
    "screen_hash_after": "b2c3d4e5"
  }
}
```

**错误情况**：
```json
{
  "jsonrpc": "2.0",
  "id": "tool-call-uuid-xxx",
  "error": {
    "code": -32001,
    "message": "Coordinates out of screen bounds",
    "data": {
      "requested": {"x": 540, "y": 1200},
      "screen_size": [1440, 3200],
      "valid_range": {"x": [0, 1440], "y": [0, 3200]}
    }
  }
}
```

### 3.5 `device/lock_*` · 设备锁

**Server → 设备 A**（成功）：
```json
{
  "jsonrpc": "2.0",
  "id": "lock-uuid-001",
  "method": "device/lock_acquire",
  "params": {
    "tentacle_id": "android-abc123",
    "owner_arm_id": "mobile_operator_arm",
    "task_id": "task-abc-001",
    "timeout_s": 300
  }
}
```

**Server → 设备 A**（失败，被占用）：
```json
{
  "jsonrpc": "2.0",
  "id": "lock-uuid-002",
  "error": {
    "code": -32010,
    "message": "Device is locked by another arm",
    "data": {
      "current_owner": "mobile_operator_arm",
      "current_task": "task-xyz-002"
    }
  }
}
```

**Server → 设备 A**（释放）：
```json
{
  "jsonrpc": "2.0",
  "id": "lock-uuid-005",
  "method": "device/lock_release",
  "params": {
    "tentacle_id": "android-abc123",
    "owner_arm_id": "mobile_operator_arm",
    "task_id": "task-abc-001"
  }
}
```

### 3.6 `skill/install` · 远程装新技能（自进化）

**Server → 设备**：
```json
{
  "jsonrpc": "2.0",
  "id": "skill-install-uuid-003",
  "method": "skill/install",
  "params": {
    "tentacle_id": "android-abc123",
    "skill_id": "android_taobao_add_to_cart_v1",
    "skill_manifest": {
      "name": "android_taobao_add_to_cart",
      "version": "1.0.0",
      "description": "在淘宝商品页一键加购（专用技能）",
      "parameters": {
        "type": "object",
        "properties": {
          "product_url": {"type": "string"},
          "quantity": {"type": "integer", "default": 1}
        }
      },
      "implementation": {
        "type": "deeplink",
        "deeplink": "taobao://item.htm?id={product_id}"
      },
      "origin": "regeneration_2024-06-06",
      "sign_by": "self_hosted_master"
    }
  }
}
```

### 3.7 `config/sync_*` · 配置双写同步

**设备 → Server**（推送本地变更）：
```json
{
  "jsonrpc": "2.0",
  "id": "cfg-push-uuid-004",
  "method": "config/sync_push",
  "params": {
    "tentacle_id": "android-abc123",
    "changes": [
      {
        "key": "channel.dingtalk.webhook",
        "value": "https://oapi.dingtalk.com/robot/send?access_token=xxx",
        "version": 7,
        "ts": 1717700005000
      }
    ]
  }
}
```

**设备 → Server**（拉取远程最新）：
```json
{
  "jsonrpc": "2.0",
  "id": "cfg-pull-uuid-005",
  "method": "config/sync_pull",
  "params": {
    "tentacle_id": "android-abc123",
    "keys": ["channel.wechat.bot_id", "llm.openai.api_key"],
    "since_version": 6
  }
}
```

---

## 4. 错误码

| Code | 含义 |
|---|---|
| `-32700` | JSON 解析错误（标准 JSON-RPC）|
| `-32600` | 无效 Request（标准 JSON-RPC）|
| `-32601` | 方法不存在（标准 JSON-RPC）|
| `-32602` | 无效参数（标准 JSON-RPC）|
| `-32603` | 内部错误（标准 JSON-RPC）|
| `-32001` | 坐标越界 |
| `-32002` | 工具超时 |
| `-32003` | 工具不存在 |
| `-32004` | App 未找到 |
| `-32005` | 权限被拒（无障碍/通知）|
| `-32010` | 设备被锁 |
| `-32011` | 设备离线 |
| `-32020` | 技能安装失败 |
| `-32030` | 配置冲突（需解决）|

---

## 5. 心跳与超时

| 项目 | 阈值 | 处理 |
|---|---|---|
| 心跳 | 30s/次 | 90s 没收到 → 标记 offline |
| 工具执行 | `timeout_ms` | 超时 → 强制 kill + error -32002 |
| 设备锁 | `timeout_s` | 超时 → 强制释放 |
| WebSocket | ping/pong 30s | 60s 没响应 → 断连 |

---

## 6. 二进制帧（截图、文件）

截图和文件传输用 **WebSocket 二进制帧**，不在 JSON envelope 内：

| 路径 | 格式 | 用途 |
|---|---|---|
| `GET /api/screenshots/{screenshot_ref}` | PNG / WebP | 截图拉取 |
| `POST /api/files/{tentacle_id}` | multipart | 文件上传 |
| `GET /api/files/{file_id}` | octet-stream | 文件下载 |

> JSON envelope 中的 `screenshot_ref` 是个"指针"，需要时再 GET 拉取，节省带宽。

---

## 7. 安全

### 7.1 鉴权

- 首次连接用 PSK（pre-shared key）或 JWT
- TLS 1.3 强制（生产环境）
- 设备注册后颁发长期 session token

### 7.2 隔离

- 每台设备的 session token 与 tentacle_id 绑定
- 跨设备操作必须显式声明（不能 A 设备控制 B 设备）
- 后台进程白名单

### 7.3 审计

- 所有 tool_call 记录到 trace_store
- 关键操作（支付、登录）触发额外认证
- 重放攻击防护：每条 envelope 带 nonce + ts

---

## 8. 版本演进

| 版本 | 状态 | 关键变化 |
|---|---|---|
| v1.0 | ✅ 当前 | JSON-RPC 2.0，device/* + tool/* |
| v1.1 | ⏳ 计划 | 远程 skill_install + 二进制流优化 |
| v1.2 | ⏳ 计划 | 多 Arm 协同下的乐观并发 |
| v2.0 | 🔮 远期 | gRPC 二进制（性能优化） |

兼容性策略：
- v1.x 内部：服务端同时支持多个 minor version
- v1 → v2：双协议并行 6 个月
- 旧设备：永远支持 v1.0

---

## 9. 调试与观测

### 9.1 调试端点

```
GET  /api/debug/devices           # 列出所有已注册设备
GET  /api/debug/devices/{id}      # 设备详情
GET  /api/debug/envelopes         # 实时 envelope 流量
POST /api/debug/inject            # 注入测试 envelope
GET  /api/debug/tentacles/mobile  # 移动触手状态
```

### 9.2 观测指标（Prometheus）

- `octopus_mobile_devices_online` - 在线设备数
- `octopus_mobile_tool_calls_total` - 工具调用总数（按 tool 分桶）
- `octopus_mobile_tool_call_duration_seconds` - 工具调用耗时
- `octopus_mobile_screen_changes_total` - 屏幕变化事件数
- `octopus_mobile_locks_active` - 当前持有设备锁数
- `octopus_mobile_locks_conflict_total` - 设备锁冲突次数

---

## 10. 完整示例：一次端到端交互

```json
// 1. 用户在 IM 发消息
{ "text": "帮我在小米 14 上点开微信" }

// 2. Client → Server (item/* 事件流)
{"method": "item/started", "params": {"item_id": "task-001", "type": "agent"}}

// 3. Cerebrum 规划
{"method": "item/delta", "params": {"item_id": "task-001", "text": "我需要打开微信..."}}

// 4. Server → 小米 14 (tool/execute)
{"method": "tool/execute", "id": "tc-1", "params": {"tool": "android_open_app", "args": {"app_name": "微信"}}}

// 5. 小米 14 → Server (tool/result)
{"id": "tc-1", "result": {"success": true, "data": "Opened WeChat"}}

// 6. 小米 14 → Server (device/screen_changed)
{"method": "device/screen_changed", "params": {"current_app": "com.tencent.mm"}}

// 7. Cerebrum 推理完成
{"method": "item/completed", "params": {"item_id": "task-001", "status": "ok"}}

// 8. Server → Client (item/delta)
{"method": "item/delta", "params": {"item_id": "task-001", "text": "✅ 已为您打开微信"}}
```

---

> 🐙 **协议是章鱼的神经脉冲 —— 简单、稳定、可观测。**

# 客户端全量 Replay 设计方案

> 从事件日志在前端重建 `Conversation`，使 reducer 成为唯一事实合成器。
>
> 状态：**P1、P2、P3 + coalesce 已落地**（2026-07-28）· 设计稿 2026-07-28
> P1 实现：`frontend/src/core/realtime/replay.ts`、reducer 的 `turn/finalized` +
> `turn/compacted` + replay mode、golden 对拍（TS replay ≡ Python `EventLog.replay()`）。
> P2 实现：服务端 `thread/events` 只读端点（同前缀不变量 + requiresReset + 分页 +
> 漂移校验元数据）；全部持久化事件的通知加盖 `eventId`（`EventLog.append` 返回值贯穿
> 15 处发射点）；compaction 新增 live `turn/compacted` 通知（此前只有 resume 能恢复）；
> 客户端增量恢复改走事件模式：eventId 去重台账 + 折叠前漂移探针 + 快照回退。
> P3 实现：`replay-cache.ts`（接口 + 内存 + IndexedDB 双后端，按 sequence 幂等合并、
> 2 万事件截断并推进 `partialFrom`）；hook 冷启动先水合缓存（秒开/离线只读），初始
> resume 自动走事件模式增量；全量快照 resume 后后台分页回填缓存；stream 重置时清缓存。
> coalesce 实现：`event_log.coalesce_events()` 纯函数（切片内已完成 item 的
> `item_started`+delta 全丢弃——`item_completed` 快照自带全文；未完成 item 的文本 delta
> 按 (turnId,itemId,kind) 合并；`mcpToolProgress` 只留最新；`turn_updated` 按 turnId 合并）。
> `thread/events` 接受 `mode=coalesce`，分页按 raw 事件切片、响应 `cursor` 恒为本页
> 最后一条**原始**事件的 sequence（合并丢弃尾部时不回退）；客户端缓存回填启用该模式，
> 增量恢复保持 raw（去重台账非空时禁用 coalesce——合并事件与首个 delta 共享 eventId）。
> 等价性由 `test_event_coalesce.py` 锁定：`replay(coalesced slice) ≡ replay(raw slice)`。
> 测试：前端 279（realtime/threads 全套）+ 服务端 128 全绿；`tsc --noEmit` 干净。
> 与设计的偏差：批量折叠（§2.6）未实现，当前为逐事件折叠，语义已被对拍锁定，
> 批量优化作为后续纯性能项跟进。
> 涉及模块：`frontend/src/core/realtime/`、`runtime/memory/threads/event_log.py`、`runtime/sensing/gateway/realtime_cerebrum.py`

---

## 1. 背景与现状

### 1.1 服务端（已具备完整 replay）

`runtime/memory/threads/event_log.py` 中每个 thread 对应一个 append-only JSONL 日志：

- `LoggedEvent{ event, eventId, threadId, ts, turnId, payload }`
  - `eventId` 保证 at-least-once 投递、复制、崩溃恢复下的幂等；旧行缺失时用 `legacy:<sha256>` 内容指纹补齐。
- `EventLogSnapshot{ events, cursor, streamId }`
  - `cursor` 与 `events` 描述**同一文件前缀**，消除 replay/cursor 竞态。
- `_apply_event()` 已覆盖全部事件类型的语义：
  `thread_started / turn_started / turn_completed / turn_updated / turn_compacted / item_started / item_delta / item_completed`。
- `cursor_delta(after_sequence)` 返回 `(changed_turn_ids, requires_reset)`；
  `turn_compacted` 会重写可见 turn 集，强制 `requires_reset=True`。

### 1.2 前端（只有实时路径，没有 replay 路径）

`frontend/src/core/realtime/reducer.ts` 的 `reduce()` 处理 WS 推送的通知：

- item 粒度 delta 经 `mergeDelta()` 进 WeakMap chunk 缓冲，按帧 join；
- `item/started|completed` 走 `upsertItem()` 快照 upsert，并把缓冲 chunk 物化进 item 的 wire 字段；
- `interruptTimestamps` 5s 宽限窗只服务于**实时**迟到 delta。

`use-realtime-thread.ts` 的 `thread/resume` 是**快照模式**：服务端 replay 后 `model_dump` 整棵 `Turn[]`，客户端 `mergeTurnSnapshots()` 整棵替换。断线重连时用 `resumeCursorRef`（1-based 物理行号）+ `resumeStreamIdRef` 增量拉取受影响 turn 的**完整快照**。

### 1.3 差距（本方案要解决的问题）

| 问题 | 现状 | 目标 |
|---|---|---|
| 冷启动依赖服务端 replay | 客户端无法从原始事件重建 | 前端可独立 replay |
| 大 turn 重传成本 | 增量 resume 也整棵换 turn，长 `aggregatedOutput` 每次都全量走网络 | 断线只拉 delta 事件 |
| 离线/分享/导出 | 无本地事件缓存 | IndexedDB 缓存日志，秒开+离线只读 |
| 双实现漂移风险 | replay 语义只在 Python `_apply_event` | TS/Python 共享 golden 对拍 |
| 时间旅行 | 不支持 | 任意 sequence 截断重建（后续阶段） |

---

## 2. 总体设计

### 2.1 核心原则：单一合成器

**禁止**在 TS 里再写一套 `_apply_event` 的平行实现。所有状态合成必须汇聚到现有 `reduce()`，实时流与 replay 流只是事件来源不同：

```
实时: WS notification ──────────────┐
                                    ├─► normalizeEvent() ─► reduce() ─► Conversation
replay: JSONL / thread/events ──────┘
```

新增一个纯函数模块 `frontend/src/core/realtime/replay.ts`，职责只有两个：

1. `normalizeEvent(LoggedEvent) → ReducerEvent | ReducerEvent[]` —— 把持久化事件翻译成 reducer 已支持的通知形状；
2. `replayEvents(events, base?) → { conversation, cursor, stats }` —— 折叠 + 收尾物化。

### 2.2 事件映射表

| `LoggedEvent.event` | reducer case | 说明 |
|---|---|---|
| `thread_started` | `thread/started` | 直接映射 |
| `turn_started` | `turn/started` | payload 需组装成 reducer 期望的 Turn 形状（`id/status/startedAt/params`） |
| `turn_completed` | `turn/completed` | `status` 字符串→枚举的容错与 Python 侧保持一致 |
| `turn_updated` | 按 payload 字段分发 | 服务端 `_apply_turn_update` 只消费四个字段：`grounding`→`turn/grounding`、`workbenchSnapshot`→`workbench/snapshot`、`workspaceFocus`→随 workbench 路径折叠、`phases`→**reducer 目前无独立 case**（实时路径里 phases 经由 `workbench/snapshot` 到达）——replay 时若日志里出现独立 phases 更新需补 case 或并入 workbench 处理 |
| `turn_compacted` | **新增** `turn/compacted` | 见 §2.3 |
| `item_started` | `item/started` | `payload.item` 直接可用 |
| `item_completed` | `item/completed` | 自动触发 chunk 物化 |
| `item_delta` | 按 `payload.kind` 分发 | 以 `_merge_delta`（`event_log.py:929`）的六个 kind 为准：`agentMessage→item/agentMessage/delta`、`reasoning→item/reasoning/textDelta`、`plan→item/plan/delta`、`commandOutput→item/commandExecution/outputDelta`、`fileChangeHunk→item/fileChange/hunkDelta`、`mcpToolProgress→item/mcpToolCall/progress`；未知 kind 丢弃并记 diagnostic（与服务端 "Unknown kinds are ignored" 一致） |

### 2.3 `turn/compacted`：reducer 必须补的语义

当前 reducer 没有 compaction 分支，这是 replay 模式特有的状态重写。新增 case，语义逐字对齐 Python（`event_log.py:803-831`）：

- 按 `supersededTurnIds` 删除被取代 turn；
- `summaryTurn` 插入到**最旧被取代 turn 的原位**（保持排序），找不到则追加到末尾；
- 返回的 `changedTurnIds` 需包含全部受影响 id，驱动 UI 重排。

同时把 `Conversation` 增加一个可选字段 `compactedAt?: string`，供 UI 在摘要 turn 顶部渲染"历史已折叠"分隔条（可后置到 UI 阶段）。

### 2.4 收尾物化（materialize）

折叠结束后，所有仍挂在 WeakMap 缓冲里的 chunk（典型场景：日志末尾是一个未完成的活跃 turn）必须物化进 item 的 `text/content/aggregatedOutput`，使返回的 `Conversation` **自包含**——不依赖缓冲对象也能被持久化、被 `realtime-adapter` 之外的读者消费。

复用 `reducer.ts` 已有的 `STREAM_TEXT_FIELDS` 物化路径，导出一个内部 helper `materializeStreamChunks(turn)`，`replayEvents` 对每个 touched turn 调用一次。

### 2.5 实时语义的显式关闭

replay 是权威日志回放，以下实时-only 行为要显式旁路：

- `interruptTimestamps` 宽限窗：replay 中 `turn/interrupted` 之后的事件**无条件接受**（日志即事实），不能套 5s 窗口；
- `error` 事件的 `err_${Date.now()}` 合成 id：replay 中改用 `err_${sequence}`，保证两次 replay 结果逐字节一致（确定性是 golden 对拍的前提）；
- vitals/telemetry 标记不触发。

实现方式：`reduce(state, event, { mode: "replay" | "live" })` 增加一个可选 mode 参数，默认 `"live"`，行为差异只在这三处。

### 2.6 性能：批量折叠

逐事件走 `reduce()` 会产生 O(事件数) 个中间 `Conversation` 对象。大日志（数万 delta）下不可接受。方案：

- `replayEvents` 内部按 turn 分组，**组内**对可变草稿折叠（复用 `mergeDelta`/apply 函数的逻辑，但作用于 draft），**组间**才产出不可变 `Turn`；
- 对外契约不变：返回普通 `Conversation`；
- golden 对拍测试必须同时跑「逐事件 reduce」和「批量 replay」两条路径，断言深度相等——防止批量优化引入语义分叉。

预期量级：10k 事件的 thread，逐事件路径 O(n²) 字符串拷贝已被 chunk 缓冲消除，剩余成本是对象分配；批量路径把不可变拷贝从 n 次降到 turn 数次。

---

## 3. 服务端接口

### 3.1 新增 `thread/events`

```json
{
  "method": "thread/events",
  "params": {
    "threadId": "...",
    "afterSequence": 0,
    "limit": 5000
  }
}
```

响应：

```json
{
  "events": [{ "sequence": 1, "event": "turn_started", "eventId": "...", "ts": "...", "turnId": "...", "payload": {} }],
  "cursor": 1234,
  "streamId": "st_...",
  "hasMore": false,
  "requiresReset": false
}
```

硬性约束（沿用 `EventLogSnapshot` 的既有不变量）：

- `events` 与 `cursor` 必须描述**同一文件前缀**——在 `snapshot()` 内一次性捕获，禁止先读事件再读 cursor；
- `streamId` 与客户端持有的不一致时，`requiresReset=true` 且返回全量（等价于现有 resume 的 replace 语义）；
- `turn_compacted` 出现在增量窗口内时同样 `requiresReset=true`（复用 `cursor_delta` 的判定逻辑，不新写规则）。

### 3.2 `thread/resume` 保持快照模式

不改动现有字段。快照模式继续作为**兜底与纠偏**路径存在（见 §4.3）。两种模式共享同一个 `EventLog.snapshot()`，天然一致。

---

## 4. 客户端恢复流程

### 4.1 三层恢复策略

```
打开 thread
  ├─ IndexedDB 有缓存日志？
  │    ├─ 是 → 立即 replayEvents(cached) 渲染（首屏 <100ms，离线可用）
  │    └─ 否 → 渲染 loading
  ├─ WS 连接成功
  │    ├─ 有 cursor + streamId 匹配 → thread/events(afterSequence=cursor) 增量
  │    └─ 无 cursor / streamId 失配 / requiresReset → thread/resume 快照（现状路径）
  └─ 增量事件 fold 进当前 state → resumed
```

### 4.2 与实时流的衔接（关键竞态）

`thread/events` 响应在途期间，WS 上可能已有新通知到达。沿用 resume 现有的纪律：

- 增量响应携带的 `cursor` 是服务端捕获时刻的前缀边界；
- 响应回来之后到达的实时事件直接 fold；
- **在途期间**到达的实时事件进入 pending 队列，等增量 fold 完成后按序 fold；
- 由于 `eventId` 幂等 + item upsert 幂等 + delta 只追加，偶发的边界重叠是安全的（chunk 缓冲对重复 delta 需要去重：以 `eventId` 为键做一次短窗 dedupe，窗口只需覆盖「在途」时长）。

### 4.3 漂移检测与纠偏

事件模式是优化路径，快照模式是权威路径。每次增量恢复后做一次廉价校验：

- turn 数、每个 turn 的 status、活跃 turn 的 item 数 —— 与 `thread/resume` 响应头级别的摘要比对（可让 `thread/events` 响应附带 `turnCount/lastTurnStatus`，成本为零）；
- 不一致 → 丢弃本地状态，走一次快照 resume，并向 `stream-telemetry` 上报 `replay_divergence` 计数。这个指标上线初期必须盯，它直接度量双路径一致性。

### 4.4 IndexedDB 缓存

- 每 thread 一个 store，key 为 `sequence`，append-only；
- 每次 WS 通知落盘前写缓存（批量 transaction，按帧 flush，避免每个 delta 一次 IO）；
- 容量策略：默认每 thread 保留最近 ~5MB 或 2 万事件，超出按 sequence 截断最旧前缀，截断后本地 cursor 标记 `partialFrom`，冷启动时截断点之前改走快照分页（`loadOlderTurns` 已有此语义，复用）；
- `streamId` 变更 → 清空该 thread 缓存重写。

---

## 5. 测试方案

### 5.1 Golden 对拍（最重要）

一个 JSONL fixture（手工构造，覆盖全部 8 种事件 + compaction + interrupted 后迟到 delta + 未完成 turn 结尾）：

1. Python：`EventLog.replay() → model_dump(mode="json")` 导出 `expected.turns.json`；
2. TS：`replayEvents(fixture)` 输出，断言与 `expected.turns.json` 深度相等（字段级白名单，剔除两端已知差异字段）；
3. TS 内部再断言：`replayEvents` 批量路径 ≡ 逐事件 `reduce()` 路径。

fixture 放 `tests/fixtures/replay/`（Python 侧）与 `frontend/src/core/realtime/__fixtures__/`（软链或拷贝），CI 两侧都跑。

### 5.2 单元测试

- `normalizeEvent` 每个映射分支 + 未知 kind 丢弃；
- `turn/compacted` 的插入位置语义（中间/头部/未知 id）；
- materialize 后 `itemStreamText(item) === item.text`；
- 中断后事件无宽限窗限制；
- 确定性：同一 fixture replay 两次深相等。

### 5.3 集成测试

- 模拟「增量响应在途 + 实时事件到达」的交错序列；
- `requiresReset` 触发快照回退；
- IndexedDB 截断后的混合加载（事件模式 + 快照分页）。

---

## 6. 分阶段实施

| 阶段 | 内容 | 服务端改动 | 风险 |
|---|---|---|---|
| **P1** | `replay.ts`（normalize + 批量折叠 + materialize）+ reducer 的 `turn/compacted` 与 replay mode + golden 对拍 | 无（可先用导出的 JSONL 验证） | 低，纯新增 |
| **P2** | `thread/events` 端点 + 增量恢复走事件模式 + 漂移检测 | 新增一个只读 RPC | 中，重点盯 `replay_divergence` |
| **P3** | IndexedDB 缓存 + 冷启动秒开 + 离线只读 | 无 | 中，容量与截断策略 |
| **P4**（可选） | 时间旅行（按 sequence 截断 replay 出任意时刻 UI）、分享链接导出事件包 | 导出端点 | 低 |

建议 P1 先行独立合入：即使 P2/P3 缓议，golden 对拍本身就把「replay 语义只在 Python」这个隐性风险消掉了。

---

## 7. 风险与开放问题

1. **`turn_updated` 的 phases 通道**：服务端 `_apply_turn_update` 消费 `grounding/phases/workspaceFocus/workbenchSnapshot` 四个字段，但 reducer 没有独立的 phases case（实时路径靠 `workbench/snapshot` 携带）。若历史日志里存在不带 workbenchSnapshot 的 phases 更新，replay 会丢 phases——P1 开工先扫一遍真实日志确认该形状是否实际出现。
2. **文本上限截断**：服务端 `_merge_delta` 对文本追加有 `MAX_STREAM_ITEM_CONTENT` / `MAX_AGGREGATED_OUTPUT` 上限并写截断标记，前端 `mergeDelta` 无对应逻辑。golden 对拍前必须对齐这个 cap（TS 侧补同样的 cap，或对拍时豁免超限 fixture），否则长输出 fixture 必然发散。
3. **delta 去重窗口**：`eventId` 短窗 dedupe 放在 reducer 入口还是 replay 层？倾向 reducer 入口（实时路径也能受益），但需要确认旧事件缺 `eventId` 时 `legacy:` 指纹在 TS 侧可复算（sha256 of raw line——raw line 在 WS 路径不存在，只限 replay 路径可用）。
4. **大日志首屏**（已实现）：`thread/events` 已支持 `mode=coalesce`（见头部状态块），兼具事件游标语义与快照体积。限制：合并事件与首个 delta 共享 `eventId`，因此**去重台账非空的客户端禁用**（只用于冷启动空状态与缓存回填）；增量恢复保持 raw 模式。跨页边界的 delta 不做合并（每页独立 coalesce），体积非最优但语义安全。
5. **WorkBench/phases 快照**：`workbench/snapshot` 事件频率高但只有最后一个有意义，coalesce 模式同理只保留每 turn 最新一个。

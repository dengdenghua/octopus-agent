# 流式 UX 架构差距闭环备忘

> 2026-07-28 · 关联文档：`docs/client-replay-design.md`（实现设计）、
> `docs/design/kimi-replay-ux-teardown.md`（Kimi 回放 UX 走查）
>
> 起因问题：Octopus 前端流式 UX 与 Codex CLI、Kimi（含 Kimi Work 运行时架构）
> 在**事件架构层面**有何差距。本文是该问题的结论备忘——差距清单里由本次
> 「客户端 Replay」工作补齐的部分逐条销账，并如实列出仍未追平的项。

## 一句话结论

Codex 与 Kimi 的流式体验之所以「断线不慌、冷启动快、可回放」，根基是
**append-only 事件日志 + 客户端可独立重建状态**；Octopus 服务端早有完整事件溯源，
缺口全部在客户端侧。本次工作（P1–P3 + coalesce + 批量折叠，5 个 commit）已把
这套根基补齐到与 Codex 同档，部分维度（冷启动缓存、传输体积）反超；剩余差距
集中在**产品化回放**（时间旅行、分享页）而非事件架构本身。

## 能力对比

| 能力 | Codex CLI | Kimi / Kimi Work | Octopus（之前） | Octopus（现在） |
|---|---|---|---|---|
| 持久化事件日志 | rollout JSONL（`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`，首行 `session_meta`，其后逐行 turn/item 事件）¹ | 会话落盘、可跨进程重启 resume | ✅ 服务端 `EventLog` JSONL + `eventId` 幂等 | 同左（不变） |
| 客户端从事件重建状态 | ✅ rollout 即 durable replayable thread state，`thread/resume` 从此读取¹ | ✅ Kimi Work 会话可跨重启恢复 | ❌ 只有服务端 replay，客户端整棵快照替换 | ✅ `replay.ts` + golden 对拍（TS ≡ Python） |
| 断线增量恢复 | ✅ `codex resume` / SDK `resumeThread`² | ✅ | ⚠️ 增量也整棵换 turn 快照，长输出全量重传 | ✅ 事件模式增量：只拉错过的 delta + eventId 去重 + 漂移探针 |
| 冷启动大日志优化 | ⚠️ resume 选择器在大 rollout 下明显变慢（open issue）³ | — | ❌ 无 | ✅ IndexedDB 缓存秒开/离线只读 + `mode=coalesce` 服务端合并 + 客户端批量折叠 |
| 双端语义一致性 | 单语言（Rust），无此问题 | — | ❌ replay 语义只在 Python，漂移无护栏 | ✅ golden fixture 对拍 + coalesce 等价性测试 |
| 回放/分享 | TUI 内 resume，无产品化回放 | ✅ 分享页可点击事件时间线回放、「做同款」⁴ | ⚠️ 仅有自包含 HTML 导出 | 同左（本次未动，见剩余差距） |
| 时间旅行（任意 sequence 截断重建） | 无 | 无 | ❌ | ❌（P4，架构已就绪） |

¹ [Building on codex app-server（§6 Where state lives on disk）](https://gist.github.com/oneryalcin/ee2c27e2d8aa040da8fbe7eebcc2ecea)：
rollout JSONL「*is* the durable, replayable representation of a thread. `thread/resume` reads from there.」
² [Codex CLI Guide（Session Resume and Review / SDK `resumeThread`）](https://blakecrosley.com/guides/codex)
³ [openai/codex#20103：resume picker 在大 rollout 文件下变慢](https://github.com/openai/codex/issues/20103)——
Octopus 的 IndexedDB 缓存 + coalesce 正好规避了这一类问题，可视为局部反超点。
⁴ 见 `docs/design/kimi-replay-ux-teardown.md`（素材为分享/回放页录屏）。

## 本次补齐清单（5 个 commit，全部测试锁定）

| Commit | 内容 | 验证 |
|---|---|---|
| `253d0fc68` | 设计文档 | — |
| `53dea40d9` | 服务端：`thread/events` 端点（同前缀快照不变量 + requiresReset + 分页 + 漂移元数据）、15 处发射点 eventId 盖章、`turn/compacted` live 通知、`mode=coalesce` | 服务端 128 全绿（含 coalesce ≡ raw 等价性） |
| `132ec7eee` | 前端 replay 核心：`replay.ts`、reducer replay 模式 + `turn/finalized` + `turn/compacted`、golden 对拍 | golden fixture：TS replay ≡ Python `EventLog.replay()` |
| `ece422641` | hook：事件模式增量恢复（eventId 去重台账 + 折叠前漂移探针 + 快照回退）、IndexedDB replay 缓存（冷启动秒开、快照 resume 后 coalesce 回填） | 前端 279 全绿 |
| `57b626981` | §2.6 批量折叠：连续 delta 合并进单次 `reduce()`，O(事件数)→~O(item 数) | 双路径 `toEqual` 对拍；283 全绿 + `tsc` 干净 |

关键设计决策（详见 `docs/client-replay-design.md` 头部状态块）：

- **单一合成器**：不在 TS 重写 `_apply_event`，实时流与 replay 流共用 `reduce()`。
- **coalesce 限制**：合并事件与首个 delta 共享 eventId，去重台账非空的客户端禁用
  （增量恢复保持 raw，仅冷启动/缓存回填用 coalesce）。
- **批量折叠不复制 reducer 逻辑**：只重写事件流，双路径对拍防分叉。

## 仍未追平的差距（如实清单）

1. **产品化回放（最大项）**：Kimi 分享页是「可点击的事件时间线 + 做同款」，Octopus
   只有自包含 HTML 导出（`buildReplayHtml`）。事件架构现已就绪（缓存 + coalesce +
   批量折叠正是回放播放器的数据管线），缺的是播放器 UI 与分享页本身。
2. **时间旅行（P4）**：任意 sequence 截断重建在设计上预留（replay 支持 `base` +
   cursor），无 UI 入口。Codex/Kimi 同样没有——这是超车项而非追平项。
3. **planner 必出计划**：Kimi 一开跑就有 Phase 1..7，Octopus 的 phases 是
   `todo_write` 副产品（见 teardown P0 节末注）——产品/模型决策，非事件架构。
4. **完成卡内「查看回放」入口**：`makeSimilar`（做同款）已有，回放入口只挂在
   分享菜单里（teardown P1 节）。
5. **回放/分享页 `bottomBar`**：teardown 结论为「有意不做」，若做回放页再启用。
6. **coalesce 跨页边界 delta 不合并**：每页独立合并，体积非最优但语义安全（已知取舍）。

## 证据索引

- 设计：`docs/client-replay-design.md`（§1.3 差距表为本次销账的基准）
- Kimi 侧走查：`docs/design/kimi-replay-ux-teardown.md`
- 前端：`frontend/src/core/realtime/{replay.ts,replay-cache.ts,reducer.ts,use-realtime-thread.ts}`
- 服务端：`runtime/memory/threads/event_log.py`、`runtime/sensing/gateway/realtime_cerebrum.py`
- 测试：`frontend/src/core/realtime/replay.test.ts`（golden 对拍 + 双路径）、
  `tests/test_event_coalesce.py`（coalesce 等价性）、`tests/test_thread_events.py`

# Realtime 流式诊断 · thread `ty_MrdI4Psbkf_M5_jGhQj`

> 诊断时间：2026-08-25 03:11 (GMT+8) · 前后端均在跑（前端 :3000 PID 59295 / 后端 :8000 PID 7348）

## 结论
**流式渲染机制本身没坏。** 看到"一直流式/转圈"是数据层两个真实状态造成的，不是前端 bug。

## 数据实况（直接 parse `data/threads/ty_MrdI4Psbkf_M5_jGhQj.jsonl`，285 事件）

### Turn 1 — "继续"（trn_782805d65d034600，主导，326 事件）
- **没有 `turn_completed` 事件**（只有 `turn_started`）→ 后端 realtime 仍判定 turn 为 active
- 67 个 `commandExecution` item，命令**几乎全部不重复**：系统性的**代码安全审计扫描**
  - 探查模式：`rg -n FastAPI(|add_middleware|include_router|CORS`、`subprocess.run|Popen|call`、`shell\s*=\s*True|os.system|eval|exec`、`dangerouslySetInnerHTML|innerHTML`
  - 读文件：`sed -n '1,260p' pyproject.toml`、`rg --files AGENTS.md`、`find runtime/octopus_runtime -type d`
- 时间跨度：createdAt 19:06:30Z → 19:11:29Z（≈ 北京时间 03:06–03:11，约 5 分钟）
- 全部 exec 都是 `completed`（3 个 `failed`），**无 inProgress 残留** → 不会单条命令永久转圈
- 文件 mtime 03:10:51，距查询 13s 仍在写 → turn 刚结束/即将结束边界

### Turn 2 — "审计项目"（trn_3edbaf39c89a4645，25 事件）
- `turn_completed | status=failed`，output=None
- 失败内容：`agentMessage kind=commentary` → "Codex 遇到暂时性错误，正在自动重试。"
- `error` item status=failed 但 **text 为空**（失败根因未透传）
- 判定：调用了 **Codex 外部引擎**，Codex 暂时性错误触发自动重试后最终失败 → 外部依赖故障，非前端流式 bug

## 根因判定
| 现象 | 根因 | 性质 |
|------|------|------|
| Turn 1 一直"流式/转圈" | turn 仍 active 跑 67 命令审计扫描，无 turn_completed | 正常 active 状态，非 bug；但体量过大(~5min)体验像卡死 |
| Turn 2 红条失败 | Codex 外部引擎暂时性错误，且 error 透传为空 | 外部依赖故障 + 失败原因未透传(UX 缺陷) |

## 前端流式判定路径（确认无误）
- `use-thread-stream-realtime.ts` → `conversationIsLoading(state)` 决定 `isLoading` → 驱动 `runningTurnId` 与 onStart/onFinish 生命周期
- 事件映射有 WeakMap 作用域缓存（`conversationEventCache`/`lastTurnEventCache`），reducer 仅重建 delta 触及的 item → 大量 item 不会全量重算，**无渲染性能 bug**
- turn 无 completed → `isLoading=true` → UI 如实显示"运行中"

## 值得修的（非阻塞）
1. **Turn 2 失败原因未透传**：`error` item text 为空，用户只见红条不知为何失败。建议把 Codex 的 error envelope 透传到 error item。
2. **Turn 1 审计扫描体量过大**：一次"继续"触发 67 exec 全量 rg 整个 repo，属任务规划问题（可分批/用 grep 一次多模式），不是流式 bug。

## 复现诊断命令
```bash
python3 - <<'PY'  # parse jsonl events
import json
events=[json.loads(l) for l in open("data/threads/<tid>.jsonl") if l.strip()]
from collections import Counter
print(Counter(e.get("event") for e in events))
# turn 维度：看有无 turn_completed、item status 分布、inProgress 残留
PY
```

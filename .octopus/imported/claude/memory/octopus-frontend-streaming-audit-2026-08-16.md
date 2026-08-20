---
name: octopus-frontend-streaming-audit-2026-08-16
description: "2026-08-16 前端流式/排版/编排/生命周期审计：三条\"看着修好其实是死代码\"的同类根因 + reduce 非幂等丢字 P1"
metadata: 
  node_type: memory
  type: project
  originSessionId: 61a315f7-1be7-498c-8157-ea1ae4ec56a9
  modified: 2026-08-15T19:29:39.680Z
---

2026-08-16 对 main 前端做四域审计（流式管线 / 对话排版 / 多智能体编排 / 任务生命周期），4 路子代理 + 我用活应用（dev server 连真后端 :8000）实证。基线全绿：tsc 绿、eslint 0 error（35 存量 warning）、vitest 232 文件 1937 测试全过。

**贯穿全场的根因模式："提交了修复，但修复路径不可达"**——三处独立出现，都是绿测试掩护下的假完成：
1. **CSS 层序倒置**：`.chat-markdown` 想改 Streamdown 样式却写在 `@layer components`，而 Streamdown 给每个元素挂 utility class（heading 是 `mt-6 mb-2 font-semibold text-{3xl,2xl,xl,lg,base,sm}`），`@layer utilities` 排在后面必胜。我在浏览器实测 h2=22.5px/600（新规则要求 1.3em/700=19.5px）→ **本次未提交的 h1–h6 规则整块是死代码**。同因连带作废：`prose-sm|base|lg :where(...){font-size:inherit}`（在 `@layer base`，更弱）→ **聊天字号设置只缩放段落，heading/inline code/th/td 全钉死**；h6 的 `text-sm`(13.1px) 真的小于正文(15px)，正是注释声称要修的现象。inline-code 背景/hr 色/blockquote 边宽/th-td 内边距同样失效。仅 `color` 系与 `!important`（table border-width，低层 !important 仍胜高层普通声明）存活。**正确修法**：markdown-content.tsx 已有 `components` 覆盖通道（已自定义 a/code），在那剥掉 utility class。
2. **142c0501 "keep code fences block-level" 不可达**：`publicProcessText`（message-group.tsx:281）先调 `normalizePublicTimelineChunk`，后者仍 `.replace(/\s+/g," ")` 且仅在结果为空时返回 null → `??` 短路，带修复的 fallback（:304-317）永不执行。进度行里 ```json 仍塌成一行、列表塌成 "- a - b"、表格渲染成字面竖线。该提交的回归测试只测了邻居函数 `stripInternalToolProtocol`。
3. **子任务状态契约是死的**（message-list.tsx:1452-1474）：前端按前缀匹配 `"Task Succeeded. Result:"` / `"Task failed."` / `"Task timed out"`，**`runtime/` 全仓 grep 零匹配** → 一律落 `else` → `in_progress`。子代理成功/失败/取消后卡片永久转圈；`cancelled` 分支（subtask-card.tsx:298）不可达。测试 message-list.test.ts:211 自造字面量所以绿。

**真 P1（我亲自复核代码）**：
- **reduce() 非幂等 → 断线重连丢已收到的正文**：`appendStreamText`（reducer.ts:82）用 `streamChunks.delete(item)` 做缓冲交接，所以同一 base 折叠两次第二次拿不到 chunks。而 use-realtime-thread.ts:568 的 drift 探针注释自称 "pure — the real fold below re-runs inside the setState updater"，实际先偷走缓冲，:626 真折叠只剩残段。子代理实测 "d1d2d3"→"d2d3"。drift 检查只比 turnId/status/count，结构上抓不到。放大器：`closeRun`（client.ts:489-498）合并 delta 只保 seed 的 eventId，去重账本缺 N-1 个 id，导致几乎每次回合中重连 `fresh` 非空。
- **Stop 的 RPC 被拒时静默无操作**：`void interrupt()` 无 `.catch`（use-thread-stream-realtime.ts:1090），且 `applyEvent("turn/interrupted")` 在 await 之后（use-realtime-thread.ts:1145）→ socket 恰好在点 Stop 时断开 → `failPending` 拒绝 → 无终态无提示无 sendError，Stop 看着失灵、连点同样被吞。
- **异常终止不扇出给兄弟标签页（(d) 确认仍未修）**：扇出只在 `_emit_turn_completed`（realtime_gateway.py:716-720），只被正常返回路径调用（:667/:784）。CancelledError 处理器（realtime_turn_lifecycle.py:1288-1331）与通用异常处理器都是 `emitter.notify` 单连接后 `raise`，绕开扇出。它自己的注释还写着"没这个 handler 客户端永远看不到终态"——只修了 emitter 那一条连接。测试无扇出断言。

**我用活应用独立抓到（子代理覆盖不到的）**：
- **97 个真实线程全在终态**（idle 76 / failed 16 / cancelled 3 / disconnected 2），**非终态 0** → 2026-07 那轮生命周期修复（pre-driver FAILED 兜底 + CancelledError 终结）在真数据上成立，无悬挂转圈。(a)(b)(c) 复验仍修好。
- **子代理线程泄漏进用户会话列表**：`/api/threads/search` 97 条里 2 条带 `metadata.subagent_role="researcher"`、5 条带 `parent_thread_id`，与用户会话混存；`core/threads/sidebar.ts` 只按 mode 过滤（`isConversationThreadMode`/`isProjectThreadMode`），从不看子代理元数据（元数据在 payload 里就有）。点进去是空态配一个误导性的"重试"按钮。截图实拍到两行 "subagent · researcher"。
- **单次线程切换 17 个 API 请求**，其中 `/outputs` 四联各发 2 次。根因：`listWorkspaceArtifactRefs`（core/artifacts/workspace-outputs.ts:49）对 4 个 area 扇出裸 `fetch`（非 react-query，无去重无缓存），且**两个不共享缓存的调用方**——chat-box.tsx:41 走 react-query、artifacts/context.tsx:77 是手写 useEffect。活跃回合期 3s 轮询 × 4 ≈ 1.33 req/s。:40 `if (!response.ok) return []` 把 403/500 静默降级成"无产物"。（轮询本身有意设计：空闲即停且有测试断言，别报为缺陷。）
- **跨栈 i18n 泄漏**：后端硬编码中文中断原因（`"连接断开或后端重启"` realtime_turn_lifecycle.py:1306、`"任务被取消"` _realtime_react_stream_apply.py:182），前端用中文全角括号原样拼（message-list-item.tsx:778 `${t.conversation.interruptedMessage}（原因：${interruptReason}）`）→ en/ja/ko 看到"译好的标签（原因：中文）"。
- **本次未提交改动的正确/错误分离**：`color-mix` 三处替换是**真修 bug**（`var(--muted-foreground) / 20` 这种 Tailwind 透明度简写在原生 CSS 里是无效值，滚动条/骨架屏渐变本来就是坏的）；两个 `.chat-markdown :where(h1)` 块**不冲突**（属性不重叠，同层同特异性）；heading 块是死代码（见上）；CJK 回退在 macOS 上是 no-op（`system-ui`/`-apple-system` 先接住 CJK，实测三种 lang 汉字宽度均 192px），但栈里**无任何 JP/KR 字体**且无 `:lang()` 分流，Windows/Linux 上 ja/ko 用户会拿到简中字形（Han 统一问题；`document.documentElement.lang` 已正确接线 main.tsx:115）；**prettier --check 红是本次引入**（globals.css 一行缩进，HEAD 干净）。

**streamdown-host.tsx 的 rAF 改动是对的应该留**：`[]` 依赖数组无 stale closure（container 是生命周期稳定的 ref、`localizeStreamdownDom` 是模块级无 props 捕获），一帧一补丁不会漏最后一次变更（`raf=0` 在扫描前置位、扫描总读活 DOM），且它把改前的**同步自触发硬挂死**（>5000 次同步遍历）降级为有界循环。**但同文件 :26-27 的 `"CSV":"CSV"` / `"Markdown":"Markdown"` 恒等替换是真 bug**：写回相同 textContent 仍会入队 characterData 记录 → 观察者自触发 → 任何含 "CSV"/"Markdown" 纯文本节点的消息会钉住 60fps 全子树 TreeWalker，回合结束后仍在烧。

**假进度残留**：`subtaskProgress`（subtask-status-ui.ts:29）`task.progress || 0.45`，而 `progress` 只在终态写入（message-list.tsx:1431-1433 注释明说活跃态故意不写）→ 运行中子代理点阵恒 45% 不动；同文件 `subtaskProgressPercent` 的 docstring 却明说"不编造百分比"并返回 null → 同一张卡点阵显示 45%、数字不显示，自相矛盾。用 `||` 而非 `??`，真实进度 0 也被吞成 0.45。测试从不覆盖 progress 缺失路径。（另 `agentProgressPercent` agent-workbench-utils.ts:402 硬编码 48% 但是死代码，无人调用。）

**教训**：判定 CSS 规则是否生效必须查 `@layer` 归属而非只算特异性——层序压过特异性；而验证"某提交是否真修好"要跑到实际符号路径，不能信提交信息或邻近测试（本轮三条假完成全是这么漏的）。子代理转录静止但完成通知可能丢失，`SendMessage` 重发可从转录恢复并索取精简结论。

关联：[[octopus-agent-frontend-ux-streaming-audit]]（2026-07 那轮，流式底座已加固项别重审）[[octopus-agent-evaluation-2026-08-15]]（上次一体审计 7.2）[[octopus-audit-false-positives]]

# Octopus 流式 UX / 状态机 / 排版交互 深度评审

日期:2026-08-16 · 范围:`frontend/src` 流式渲染、实时状态模型、Markdown/组件排版、输入与全局交互

---

## 总评

**底层链路(传输 → 缓冲 → 渲染)已经是第一梯队水准**,优化痕迹明显且成体系;
**可感知的剩余问题集中在三个点**:streamdown 汉化的 MutationObserver 全 DOM 扫描、正文打字机速度上限、以及若干"小但高频"的交互缺失(草稿持久化、时间戳、代码块横向滚动)。

一句话:地基很硬,天花板卡在几个局部热点和交互欠账上。

---

## 1. 流式渲染链路 — 现状与问题

### 已经做得好的(不建议动)

| 机制 | 位置 | 说明 |
|---|---|---|
| WebSocket JSON-RPC 主通道 | `core/realtime/client.ts:155` | bearer 走 subprotocol,token 不进 URL;ping 25s/pong 超时 70s 强重连 |
| 帧内 coalesce | `client.ts:476-545` | 同 item 连续 delta 一帧合并,`item/started|completed` 同 rAF buffer 保序;隐藏 tab 降级 setTimeout |
| chunk 缓冲(抗二次方) | `core/realtime/reducer.ts:30-152` | delta 不拼字符串,WeakMap 累积 chunk,React 读取时才 join 且 memo |
| identity cache 全链路 | `realtime-adapter.ts:209-246`、`use-thread-stream-realtime.ts:651-792` | 未变 item 引用相等,下游 memo 全跳 |
| 组级冻结 | `message-list.tsx:651-726` | MemoizedGroup 自定义 comparator |
| 未闭合语法兜底 | streamdown `parseIncompleteMarkdown` + 自研表格管道符修复 | `markdown-content.tsx:87-103` |
| 滚动 | `use-stick-to-bottom` + `resize="instant"` + 上翻 escape + 回底按钮/new-updates 徽标 | `conversation.tsx:92-155` |
| 放弃虚拟化改 `content-visibility:auto` | `message-list.tsx:728-742` | 正确决策:流式增高下 translateY 抖动无解 |
| 代码块零几何跳变 | `code-block.tsx:75-97` | 高亮/纯文本 PRE 类一致,shiki 150ms debounce |

### 值得修的问题(按收益排序)

**P0 — LocalizedStreamdown MutationObserver 全 DOM 扫描**(`ai-elements/streamdown-host.tsx:66-94`)
- 现状:每个流式消息容器挂 `subtree+characterData` observer,每个 delta 帧 TreeWalker 遍历全部文本节点 + `querySelectorAll("button[title]")`,O(全文)/帧/消息;effect 无依赖数组每次渲染重跑。为汉化 6 个字符串付出全 DOM 扫描,作者注释都自承 "fragile"。
- 修法:streamdown 若支持传 components/labels prop 就传死值;不支持则把 observer 限流到只在 `item/completed` 后跑一次,或直接 fork 掉这 6 个字符串。预期收益:长回答流式期间主线程占用显著下降。

**P1 — 正文打字机速率钳死**(`hooks/use-streaming-text-buffer.ts:151-157`)
- 现状:`step = min(step, 4)`,40ms/tick → 上限 100 字符/s。CJK 快模型 200+ 字符/s 时积压不可见,流结束后 240ms 倾倒一大段,用户看到"答案突然跳完"。
- 旁证:`LiveThinkingWindow` 已放宽到 10 字符/tick(`message-group.tsx:448-457`),作者意识到了,但正文没跟进。
- 修法:积压自适应(积 >500 字符时提速),或直接把正文 maxCharsPerTick 提到 8-12。

**P1 — 每帧全文正则链**(`message-list-item.tsx:512-527`;`markdown-content.tsx:64-103`)
- stripLeakedControlMarkup / stripInternalToolProtocol / stabilizeMarkdownTableCodePipes 每帧对全文 split/map/正则,O(n)/帧 且无增量缓存。短回答无所谓,长回答与 observer 热点叠加。
- 修法:对"上一次清洗结果 + 新增 delta"做增量处理,或仅每 N 帧/长度跨越阈值时跑。

**P2 — thinking 手动折叠被强制重新展开**(`ai-elements/reasoning.tsx:85-89`)
- effect 依赖含 `isOpen`,流式中用户折叠 → isOpen=false → effect 又 setIsOpen(true),剥夺选择权。
- 修法:effect 只在 `isStreaming` 由 false→true 边沿展开一次,不盯 isOpen。

**P2 — 代码块结束闪烁**(`code-block.tsx:153-159`)
- settled 时先 `setHtml("")` 再异步高亮,中间一帧回退无高亮占位 → plain→highlight 闪变。
- 修法:settled 后保留最后一帧已高亮 html 直到新 html 就绪。

---

## 2. 状态机 — 现状与问题

### 模型(镜像 `runtime/protocol/items.py`)

```
ItemStatus: inProgress | completed | failed | interrupted | declined
TurnStatus: inProgress | completed | paused | cancelled | interrupted | failed
ItemType:   userMessage / agentMessage / reasoning / plan / commandExecution /
            fileChange / mcpToolCall / subagent / approval / error / …(16 种)
```

设计是健康的:item 粒度、稳定 id、`turn/completed` 携带整 Turn 做权威终态(reducer 不自己推 turn.status,`reducer.ts:786` 注释明确)、中断有 5s 宽限窗吸收迟到 delta(`reducer.ts:27-28`)、reducer 是纯函数可单测。

### 风险点

1. **竞态白名单靠注释维系**。`reducer.ts:664` "race against turn/started 时 silently drop"、`:927` 中断窗口的说明都写在注释里,迁移合法性没有集中断言。建议在 reducer 层加一张显式的"合法迁移表"(或在测试里穷举 事件乱序矩阵:delta 晚于 completed、completed 晚于 interrupted、replay 与 live 交错)。
2. **paused 态的恢复路径依赖服务器主动 request**(审批走 JSON-RPC request/reply,`client.ts:311-322`)。断线重连在 `paused` 期间发生时的重放行为值得专项测一次(审批卡是否会重现?会不会卡在无人可答的 turn?)。
3. **前后端状态枚举靠人肉同步**(items.ts 头注 "mirrors runtime/protocol/items.py")。协议已版本化(`protocol-versioning.ts`),但枚举本身没有生成/校验机制,后端加状态前端不感知时会静默落进默认分支。建议加个 CI 断言或 codegen。

---

## 3. 排版与交互 — 现状与问题

### 排版体系

- streamdown 1.4.0 懒加载;remark-gfm/math + rehype-raw/katex 静态加载(刻意,避免首帧转义);人类消息单独插件集防注入(`core/streamdown/plugins.ts:49-56`)。
- shiki 双主题代码块、mermaid 懒加载、`file path:行号` → FileReferenceChip、外链自动 _blank。
- prose 样式手写复刻(`globals.css:1201-1235`,未装 @tailwindcss/typography)。

### 交互欠账(按用户可感知度排序)

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| 1 | **草稿无持久化**:仅存 useState,切会话/刷新即丢 | `ChatComposer.tsx:130` | per-thread localStorage 草稿,发送/切会话时落盘 |
| 2 | **代码块软换行无横向滚动选项**:`whitespace-pre-wrap` 写死,对齐类代码难看 | `code-block.tsx:84,92` | 头部加换行/滚动切换钮,记住偏好 |
| 3 | **消息无时间戳**:长会话无法回溯时点 | 全消息目录无时间渲染 | hover 或 detail=high 时显示 HH:mm |
| 4 | DiffLines 超 400 行截断无提示 | `collapsible-activity-group.tsx:112` | 尾部加"已截断,查看完整 diff" |
| 5 | 折叠组 emoji 与 lucide 图标混用 | `collapsible-activity-group.tsx:156-174` | 统一 lucide |
| 6 | **双输入体系并存**:prompt-input.tsx(1496 行)与 ChatComposer(1206 行) | 仅旧页面引用 | 排期删除 prompt-input,防腐化 |
| 7 | 手写 prose 长期漂移风险 | `globals.css:1201` | 评估引入官方 typography 或加视觉回归 |

### 已经对的交互(保持)

- 反馈条只在最后一条 AI 消息出现一次(产品决策已落地);错误分类着色(blocked/network/guard…)且已 settled 答案不挂迟到错误;斜杠命令/@提及/粘贴图片/拖拽/isComposing 保护齐全;⌘K/⌘B/⌘J/⌘⇧N 快捷键完整;暗色主题 shiki/CodeMirror 联动。

---

## 4. 行动清单(按 ROI 排序)

| 优先级 | 事项 | 预估收益 |
|---|---|---|
| P0 | 干掉 streamdown-host 的 MutationObserver 全 DOM 扫描(汉化改 prop/fork/限流) | 长回答流式卡顿直接缓解 |
| P1 | 正文打字机积压自适应提速(对齐 thinking 窗口的 10/tick) | 消除"答案突然跳完" |
| P1 | ChatComposer 草稿 per-thread 持久化 | 高频痛点,半天工作量 |
| P1 | 全文正则清洗改增量/降频 | 与 P0 叠加收益 |
| P2 | thinking 折叠尊重用户选择;代码块 settled 闪烁修复 | 细节打磨 |
| P2 | 代码块横向滚动切换;消息时间戳;diff 截断提示 | 各半天 |
| P3 | reducer 事件乱序矩阵测试;paused 断线重连专项;前后端枚举 CI 同步 | 防回归,状态机长治久安 |
| P3 | 删除 prompt-input 旧输入体系;emoji→lucide 统一 | 减腐 |

---

*证据行号以 2026-08-16 工作区为准;流式/排版两份探查报告原文见会话记录。*

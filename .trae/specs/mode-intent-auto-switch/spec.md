# 模式动态切换：按对话意图自动切换 develop / audit / uxui

## Why

当前工作区模式（`AgentModeName`: develop / audit / uxui，经 `projectAgentMode` 注入后端 `agent_mode`）**只按工作区类型决定**，从不看对话内容：

- [page.tsx](../../../frontend/src/app/workspace/realtime/[thread_id]/page.tsx) 的 `projectAgentMode` 默认 `"develop"`，仅在 [mode-selector.tsx](../../../frontend/src/components/workspace/mode-selector.tsx#L190-L232) 加载时按项目类型（builder/coder/architect）映射一次。
- 换句话说：在编程工作区里问"帮我把这个界面改好看一点"，它不会切到 `uxui`；问"审查一下这段代码的安全性"，也不会切到 `audit`。

用户目标：**主对话区像真人对话一样，根据用户正在说什么，自动把工作策略切到合适的模式**。已确认的三条决策：

1. **切换方式**：高置信自动切 + 低置信建议（置信度 `>= HIGH` 直接切；`MEDIUM <= conf < HIGH` 弹轻量建议条）。
2. **检测依据**：整段对话上下文（取最近一段用户消息做平滑，避免单条抖动误判）。
3. **覆盖优先级**：用户手动选定过模式后，自动切换降级为"仅建议"，绝不自动覆盖用户选择。

不做的事（边界）：
- **不改后端协议**：意图分类在前端纯函数完成（关键词词表 + 启发式评分），不新增 LLM 调用、不加网络/Token 延迟。
- **不引入新 UI 库**：建议条用现有 shadcn Button + i18n + lucide。
- **不碰 ReasoningMode 路由**（chat/react/deep/code/team 那套）：本 spec 只作用于 `AgentModeName`（develop/audit/uxui），二者正交。
- **不编造分类**：无命中或置信度不足时不动作，保持原模式。

## What Changes

### 1. 纯函数意图分类器 `intent-classifier.ts`

新增 `frontend/src/core/modes/intent-classifier.ts`：

```ts
export type IntentClassification = {
  mode: AgentModeName;      // develop | audit | uxui
  confidence: number;       // 0..1
  signals: string[];        // 命中的信号词（用于透明度/调试）
  handle: "none" | "suggest" | "auto"; // 决策结果
};

export function classifyModeIntent(
  messages: string[],
  opts?: { weights?: number[]; highThreshold?: number; mediumThreshold?: number },
): IntentClassification;
```

- **词表**（中英双语，`develop` / `audit` / `uxui` 三组），覆盖本项目高频话术：
  - `develop`：写/实现/编写/开发/创建/修复/重构/添加/功能/函数/组件/接口/api/后端/前端/算法/调试/报错/错误/bug/实现/加一个/改一下代码 / implement/code/build/fix/refactor/create/add/api/backend/frontend/debug/bug
  - `audit`：审查/审计/检查/代码质量/安全/风险/评估/漏洞/越权/注入/性能问题/规范/最佳实践/review/audit/security/risk/assess/vulnerability/injection
  - `uxui`：界面/ui/ux/样式/外观/设计/布局/美化/视觉/交互/配色/字体/间距/圆角/阴影/动效/好看/漂亮/美观/主题/interface/design/layout/theme/style/appearance
- **评分**：对每条消息统计各模式命中信号数 × 时间权重（最近一条 `1.0`，往前递减 `0.8/0.6/0.45/0.3`，默认最多取 5 条）；`score(mode) = Σ`。
- **置信度**：`top = max score`，`runner = 次高`；`confidence = top > 0 ? (top - runner) / top : 0`（完全主导 → 1，势均力敌 → 0）。
- **决策**：
  - `top == 0` → `{ mode: 当前模式占位, handle: "none", confidence: 0 }`
  - `confidence >= highThreshold(0.7)` → `handle: "auto"`
  - `confidence >= mediumThreshold(0.45)` → `handle: "suggest"`
  - 否则 → `handle: "none"`
- 纯函数、无 React/网络依赖，便于单测。

### 2. 手动覆盖信号外露

[mode-selector.tsx](../../../frontend/src/components/workspace/mode-selector.tsx) 内部已有 `manualOverride` 状态，但未外露。新增 prop：

```ts
onManualOverrideChange?: (isManual: boolean) => void;
```

- 在 `handleToggle`（用户手动切换）时回调 `true`。
- 在 `useEffect` 检测到工作区变化并重置、或自动检测应用推荐模式时回调 `false`。
- 页面据此记录 `const [modeManualOverride, setModeManualOverride] = useState(false)`。

### 3. 页面集成（提交时触发）

在 [page.tsx](../../../frontend/src/app/workspace/realtime/[thread_id]/page.tsx) 的提交路径（`handleSubmit` 开头）插入意图分类：

- 收集最近用户消息：当前消息 + 前一~四条 `human` 消息文本（`messages` 状态里取）。
- 调 `classifyModeIntent(最近用户消息)`。
- 决策应用（`modeManualOverride` 优先）：
  - **手动优先**：`modeManualOverride === true` → 仅在 `handle === "auto"` 时弹建议条（不自动切）。
  - **无手动覆盖**：
    - `handle === "auto"` → `setProjectAgentMode(分类 mode)` + 清除建议条 + `toast` 提示"已自动切换到「X」模式"。
    - `handle === "suggest"` → 弹建议条（不自动切）。
    - `handle === "none"` → 无动作。
- 限制：仅当 `isProjectCodeMode` / 项目模式可用时生效；`isOctopusAssistant` 或非项目场景跳过。

### 4. 轻量建议条 `mode-intent-suggestion.tsx`

新增 `frontend/src/components/workspace/messages/mode-intent-suggestion.tsx`（或 `chat-input-box` 目录）：

```
🛠  建议切换到「审查」模式？        [切换] [忽略]
```

- 弱显示：小字、`text-muted-foreground`、无气泡无阴影，置于输入框上方。
- `[切换]` → `setProjectAgentMode(mode)` + 记录手动覆盖（`modeManualOverride=true`）+ 关闭建议条。
- `[忽略]` → 关闭建议条（`sessionStorage` 记忽略，避免每轮重弹）。
- 换一轮新消息重新评估时，若信号仍强可再次出现。

### 5. i18n

4 语言（zh-CN / en-US / ja-JP / ko-KR）新增：
- 建议条文案："建议切换到「{mode}」模式？" + 切换 / 忽略。
- 自动切换 toast："已自动切换到「{mode}」模式"。
- 模式名（复用现有 `t.modes.*` 的 develop/audit/uxui 显示名）。

## Impact

- Affected code：
  - 新增：`frontend/src/core/modes/intent-classifier.ts` + `intent-classifier.test.ts`
  - 新增：`frontend/src/components/workspace/chat-input-box/mode-intent-suggestion.tsx` + 测试
  - 改：`frontend/src/components/workspace/mode-selector.tsx`（外露 `onManualOverrideChange`）
  - 改：`frontend/src/app/workspace/realtime/[thread_id]/page.tsx`（提交时意图分类 + 决策应用 + 建议条状态）
  - 改：`frontend/src/components/workspace/chat-input-box.tsx`（透传 `onManualOverrideChange`，渲染建议条）
  - 改：4 语言 i18n 文件
- Tests：
  - intent-classifier：词表命中、中英、时间权重、置信度阈值、无命中 no-op
  - mode-selector：`onManualOverrideChange` 回调
  - page/chat-input-box：手动优先、自动切、建议条交互

## Non-goals / Regression

- 不改 `effectiveMode`（ReasoningMode 路由）逻辑。
- 不改后端 `agent_modes` 协议。
- 无意图时不动作，现有模式与行为完全不变。
- 弱显示原则贯穿：建议条小字、无装饰动画。
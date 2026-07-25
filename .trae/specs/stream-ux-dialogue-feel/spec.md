# 主对话流式 UX 优化：GPT 对话感 + 三优融合

## Why

经过对 ChatGPT 桌面版（Codex）解包分析、Kimi 回放走查、Coze 桌面版逆向报告三份竞品材料的综合对比，结合我们刚交付的 `stream-ux-timeline-narrative` 现状，核心问题归结为一句话：

> **主对话区现在是"时间线日志"，不是"人在对话"。**

ChatGPT 桌面版（9536 条 i18n 反推）的核心设计哲学是：**主对话区要像人和人说话一样——agent 用自然语言跟你说它在干什么、发现了什么、接下来要做什么；机器细节（终端输出、diff、原始日志）收到右侧工作台。** Kimi 教会我们"双轨叙事"（左叙事+右证据），Coze 教会我们"当前帧聚焦"和"术语翻译成人话"，ChatGPT 教会我们"主对话区就是对话，不是日志"。

我们之前的 timeline 叙事优化解决了"角色分层"和"联动"问题，但主对话区还是充满了工具名、参数、日志感的行——这和 GPT 那种"agent 在跟你说话"的感觉有本质差距。

## 设计原则（非妥协项）

1. **主对话区 = 对话感**：agent 在对话区只说人话——"我先看一下你的代码结构"、"找到了问题，在 `auth.ts` 第 20 行"、"修好了，跑一下测试"。不出现 `edit_file`、`run_command` 这类工具名。
2. **工具细节去右侧**：终端输出、diff、文件变更、命令行参数——全部在右侧 Workbench 面板查看，主对话区只保留"做了什么"的人类可读描述。
3. **默认聚合，展开看详情**：长任务默认显示一句话摘要（ChatGPT 的 "Ran 3 commands · edited 2 files"），点击展开看每条动作的详情，再点跳右侧证据。
4. **思考不消失，但不抢戏**：深度思考块默认折叠（有耗时标签，如"思考了 8s"），展开看完整推理；浅层意图直接用自然语言说出来。
5. **当前帧聚焦**（Coze 经验）：流式进行中，主对话区只展示当前轮的当前阶段；已完成的历史轮次自动收敛为摘要。
6. **双轨联动保留并增强**（Kimi 经验）：主对话区的每条动作都能点到右侧对应证据；右侧 Workbench 的事件也能点回对话区对应位置。联动目标从"大纲 item"升级到"具体证据 tab + 具体事件"。
7. **弱显示原则保持**：不搞气泡、不搞阴影、不搞装饰动画；折叠态小字 muted、展开态正常字重。

## 竞品优势吸收矩阵

| 能力 | ChatGPT Desktop | Kimi 回放 | Coze Desktop | 本方案吸收策略 |
|---|---|---|---|---|
| **主对话对话感** | ✅ 人话动作描述 + 聚合摘要 | ❌ 偏日志 | ⚠️ 有人话标签但偏设备 | **核心目标**：工具行→人话行 |
| **动作结构化** | ✅ action + detail（Running npm install） | ⚠️ typed blocks 但偏图标 | ✅ 人话标签（正在查看文件） | 工具调用→displayAction + displayDetail |
| **聚合摘要** | ✅ "Ran 3 commands · edited 2 files" | ❌ 逐条展开 | ❌ 逐条 | 同类动作聚合成一行摘要，展开看详情 |
| **右侧摘要面板** | ✅ Progress/Subagents/Inputs/Outputs/Sources/Files | ⚠️ 右侧是证据面板不是摘要 | ❌ 无独立摘要 | Workbench 新增"概要"tab 增强（补 Inputs/Outputs/Sources） |
| **思考耗时** | ✅ "Thought for 8s" | ❌ 无耗时 | ❌ 无 | 思考块标题显示实时耗时 |
| **当前帧聚焦** | ⚠️ 部分（进行中折叠） | ❌ 全量展示 | ✅ 当前帧+历史收进回放 | 进行中只显当前阶段，历史轮自动收敛 |
| **双轨叙事** | ⚠️ 右面板偏摘要非证据 | ✅ 左叙事+右证据台 | ⚠️ 设备状态面板 | 保留双轨，联动目标从大纲升级到具体证据 |
| **业务 Phase** | ⚠️ 只 X/Y tasks 数字 | ✅ 业务阶段名（读取需求/脚手架…） | ❌ 技术阶段 | 大纲用业务 phase 分组（接后端 phases 数据） |
| **完成态 receipt** | ⚠️ 偏简单 | ✅ 结构化验收表 | ❌ 无 | 已有的 message-output-summary 保留并接入 timeline |
| **术语翻译** | ✅ 全量人话 | ⚠️ 部分 | ✅ 见动作不 API 名 | displayLabel 映射表全覆盖 |

## What Changes

### P0 主对话对话感重构（核心）

#### 1. 工具调用行 → 人话动作行（Action Row）

**现状**：toolCall 行显示 `edit_file {"path": "src/auth.ts", "old_str": "...", "new_str": "..."}`，是日志不是对话。

**改为**：
```
✎  编辑 auth.ts                        [点击展开详情 →]
    └ 改了 token 验证逻辑，加了过期检查
▶  运行测试: npm test                  [点击展开详情 →]
    └ 3 个测试文件通过
🔍 搜索代码: "auth middleware"         [点击展开详情 →]
    └ 在 5 个文件里找到 12 处引用
```

- 每行结构：**图标 + 动作动词（人话）+ 对象（文件名/查询/命令名）**
- 下方弱显示一行事实摘要（已有 `fact-summary.ts`，升级从 result 提取更丰富信息）
- 右侧"展开详情"按钮点击 → 打开右侧 Workbench 对应 tab 和对应事件
- 工具名到 displayAction 的映射（`action-display.ts`）：
  - `edit_file`/`write_file`/`apply_patch` → "编辑" / "创建" / "修改"
  - `run_command`/`shell_command`/`exec_shell` → "运行"
  - `read_file`/`list_dir` → "读取" / "查看"
  - `web_search`/`web_fetch` → "搜索网页" / "浏览网页"
  - `web_navigate`/`browser_*` → "操作浏览器"
  - `todo_write` → "更新计划"
  - 其他工具 → 取工具名的 camelCase 拆词翻译

- 图标映射：
  - 写/改/创建文件 → PencilLineIcon
  - 运行命令 → SquareTerminalIcon
  - 读/查看文件 → FileTextIcon
  - 搜索 → SearchIcon
  - 浏览器 → GlobeIcon
  - 网络请求 → NetworkIcon
  - 审批/确认 → UserCheckIcon
  - 其他工具 → WrenchIcon

#### 2. 同类动作聚合（Activity Summary Row）

**现状**：连续 5 个 edit_file 就是 5 行，信息密度低。

**改为**：连续同类动作（同一工具类型 + 同一 phase）聚合成一行摘要：

```
✎  编辑了 3 个文件  ▼
    ├ auth.ts ─ 改了 token 验证逻辑
    ├ middleware.ts ─ 加了过期拦截
    └ config.ts ─ 更新 JWT 配置
```

- 聚合条件：同一 phase 内连续的同类型工具调用（读写类分开聚合、命令类单独聚合）
- 聚合行显示：图标 + "编辑了 N 个文件" / "运行了 N 条命令" / "搜索了 N 次"
- 默认折叠，点击展开看每个动作的详情
- 进行中时实时更新计数（"编辑了 2 个文件…" → 数字跳动）
- 聚合规则：
  - 文件写操作（edit/write/apply_patch）→ "编辑了 N 个文件"
  - 文件读操作（read/list/grep/glob）→ "查看了 N 个文件"
  - 命令执行 → "运行了 N 条命令"
  - 搜索类（web_search/code_search）→ "搜索了 N 次"
  - 混合操作 → 不聚合，逐条显示

#### 3. 意图行改为自然语言

**现状**：`intent` 角色从 content 里截取首段，可能是技术描述甚至工具提示词。

**改为**：从 `public_progress`/`phase` 结构化字段取意图时，用业务 phase 的人话标签；从 content 推断时，取第一段有意义的自然语言描述，过滤掉内部指令文本。

- phase 标签映射（与后端 phases 对齐，fallback 用通用标签）：
  - planning → "分析需求中…"
  - exploring → "了解代码结构…"
  - implementing → "开始修改代码…"
  - testing → "验证修改…"
  - deploying → "部署中…"
  - 无 phase 时从 content 推断

#### 4. 思考块加耗时 + 友好标题

**现状**：思考块标题是"思考中"或静态文字，无耗时。

**改为**：
- 进行中："思考中…"（带 spinner）
- 完成后："思考了 N 秒"（显示实际耗时）
- 深度思考 vs 普通思考用不同图标（BrainIcon vs SparklesIcon）
- 默认折叠，展开看完整思考内容

### P1 右侧 Workbench 增强 + 联动升级

#### 5. Workbench "概要" tab 增强为摘要面板

**现状**：Workbench 有终端/预览/diff/计划/产物等 tab，"概要"tab 信息较薄。

**增强为** ChatGPT 式的六区摘要：
- **Progress**：当前 phase + 进度（X/Y 任务完成）
- **Subagents**：子 agent 状态（已有 parallel-subtasks-grid，增强到概要里）
- **Inputs**：用户原始请求 + 上传文件列表
- **Outputs**：产物清单（artifacts + 生成文件）
- **Files Changed**：变更文件列表（已有 diff 数据）
- **Sources**：引用来源（如果有 RAG citation 数据）

#### 6. 联动目标从大纲升级到具体证据

**现状**：T3 联动只在对话区↔侧边栏大纲之间滚动高亮。

**升级为**：
- 点对话区的动作行 → Workbench 打开对应 tab（edit→Files/diff，命令→Terminal，搜索→Files）+ 定位到对应事件 + 2s 高亮
- 点右侧 Workbench 事件 → 对话区滚动到对应动作行 + 2s 高亮
- 大纲 item 点击 → 对话区滚动到对应轮次起始位置

### P2 流式体验打磨

#### 7. 当前帧聚焦（进行中只显当前阶段）

**现状**：长任务过程中所有历史步骤全部展开，对话区越堆越长。

**改为**：
- 流式进行中：当前 phase 的动作行可见，已完成 phase 自动收敛为一行摘要（"✓ 了解代码结构 · 查看了 12 个文件"）
- 已完成的历史轮次（非当前流式轮）：默认收敛为"✓ 完成了 X 件事 · 最终回答在上方"，点击展开看完整过程
- 用户手动展开的收敛块保持展开状态（不强制收回）
- 流式结束后：所有 phase 展开，用户可自由折叠

#### 8. 完成态与最终回答自然衔接

**现状**：T6 加了分界线，但过程和最终回答还是割裂的。

**改为**：
- 流式接近完成时，最后一个动作行的事实摘要自然过渡到最终回答
- 最终回答不是"另起一段"，而是在最后一个确认事实之后自然开始
- 完成后显示轻量完成标记（✓ "完成" 标签，不大张旗鼓）
- message-output-summary（产物receipt）接在最终回答后面，作为"交付清单"

## 不改的东西（边界）

- **不改后端协议**：所有改动在前端层完成，结构化字段优先、启发式兜底
- **不拆 message-group.tsx**：在现有渲染管线中改造，不做大重构
- **弱显示原则**：不加气泡、阴影、渐变、装饰动画
- **不引入新 UI 库**：只用已有的 shadcn 组件 + Tailwind + lucide
- **不改 Workbench 的终端/diff/预览核心功能**：只增强"概要"tab 和联动
- **不把机器细节搬到主对话区**：终端输出、完整 diff、命令 stdout 永远在右侧

## Impact

- Affected code：
  - 新增：`frontend/src/components/workspace/messages/action-display.ts`（工具→人话映射）
  - 新增：`frontend/src/components/workspace/messages/activity-aggregator.ts`（同类动作聚合逻辑）
  - 改：`frontend/src/components/workspace/messages/message-group.tsx`（工具行渲染重构为 Action Row + 聚合逻辑）
  - 改：`frontend/src/components/workspace/messages/fact-summary.ts`（升级提取更丰富的事实信息）
  - 改：`frontend/src/components/workspace/messages/process-trace.tsx`（思考块加耗时、动作行用人话）
  - 改：`frontend/src/components/workspace/messages/collapsible-activity-group.tsx`（适配新的聚合行格式）
  - 改：`frontend/src/core/threads/timeline-linkage.ts`（联动目标扩展到 Workbench tab+event）
  - 改：`frontend/src/components/workspace/agent-workbench-panel.tsx`（概要tab增强）
  - 改：`frontend/src/core/threads/progress-outline.ts`（大纲接业务phase标签）
  - 改：`frontend/src/components/workspace/messages/timeline-role.ts`（role层加displayAction/displayDetail字段）
  - i18n：4 语言文件加动作动词、聚合文案、思考耗时文案

- Tests：
  - action-display 映射单测
  - activity-aggregator 聚合逻辑单测
  - message-group 新 Action Row 渲染测试
  - fact-summary 升级测试
  - timeline-linkage 扩展联动测试

## ADDED Requirements

### Requirement: 工具调用渲染为人话动作行

系统 SHALL 将每个工具调用渲染为"人话动作行"，结构为：图标 + 动作动词 + 对象 + 弱显示事实摘要 + 展开详情按钮，不得出现原始工具名（如 `edit_file`、`run_command`）。

#### Scenario: 文件编辑工具
- **WHEN** 工具为 edit_file/write_file/apply_patch
- **THEN** 动作行显示 ✎ "编辑 {文件名}"，下方显示事实摘要（如"改了 X 行，Y 处新增"）

#### Scenario: 命令执行工具
- **WHEN** 工具为 run_command/shell_command
- **THEN** 动作行显示 ▶ "运行 {命令摘要}"，命令摘要取命令的第一个词+关键参数（如 "npm test"、"git status"），不显示完整命令行

#### Scenario: 未映射的工具
- **WHEN** 工具名不在映射表中
- **THEN** 用 wrench 图标 + 工具名的 camelCase 拆词作为动作描述（如 `web_fetch` → "Web Fetch"），不报错

### Requirement: 同类动作聚合

系统 SHALL 将同一 phase 内连续的同类型工具调用聚合成一行摘要行（如"编辑了 3 个文件"），点击展开显示每个动作的详情。

#### Scenario: 连续文件编辑
- **WHEN** 同一 phase 内出现 3 个 edit_file 调用
- **THEN** 显示一行 "✎ 编辑了 3 个文件 ▼"，点击展开显示 3 个文件各自的编辑详情

#### Scenario: 进行中聚合
- **WHEN** 流式正在进行，聚合计数实时更新
- **THEN** 摘要行数字跳动更新（"编辑了 2 个文件…"），不闪烁、不重建 DOM

#### Scenario: 不同类型混合
- **WHEN** 文件编辑后紧跟一条命令执行
- **THEN** 不聚合，显示两行（一个文件编辑摘要行 + 一个命令行）

### Requirement: 思考块显示耗时

系统 SHALL 在思考块完成后显示思考耗时（如"思考了 8 秒"），进行中显示"思考中…"。

#### Scenario: 思考进行中
- **WHEN** 推理步骤正在流式输出
- **THEN** 思考块标题显示 spinner + "思考中…"

#### Scenario: 思考完成
- **WHEN** 推理步骤结束
- **THEN** 思考块标题显示大脑图标 + "思考了 N 秒"（N 为实际耗时，取整秒）

### Requirement: 当前帧聚焦

系统 SHALL 在流式进行中只展开当前 phase 的动作行，已完成 phase 收敛为摘要行；历史轮次默认收敛。

#### Scenario: 流式进行中
- **WHEN** agent 正在执行 phase 3（implementing）
- **THEN** phase 1、phase 2 的动作收敛为单行摘要（如"✓ 分析需求 · 查看了 12 个文件"），phase 3 的动作行展开可见

#### Scenario: 用户展开历史
- **WHEN** 用户手动点击已收敛的历史 phase 摘要
- **THEN** 展开显示该 phase 的完整动作行，且后续流式不自动收回用户展开的块

#### Scenario: 流式结束
- **WHEN** agent 完成本轮任务（最终回答输出完毕）
- **THEN** 所有 phase 自动展开（用户手动折叠的保持折叠）

### Requirement: 动作行与右侧 Workbench 联动

系统 SHALL 在用户点击对话区动作行时，打开右侧 Workbench 对应 tab 并定位到对应事件；反之亦然。

#### Scenario: 点文件编辑行
- **WHEN** 用户点击编辑 auth.ts 的动作行
- **THEN** Workbench 打开 Files/diff tab，定位到 auth.ts 的变更项，2s 高亮

#### Scenario: 点命令行
- **WHEN** 用户点击运行 npm test 的动作行
- **THEN** Workbench 打开 Terminal tab，定位到对应命令输出，2s 高亮

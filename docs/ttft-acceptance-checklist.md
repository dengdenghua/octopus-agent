# TTFT 修复实测验收清单

> 2026-07-28 · 对应 5 项首帧延迟修复 + 1 项思考通道扩展。
> 每项给出：修复内容 → 实测步骤 → 预期事件时序 / UI 表现 → 快速证伪点。
> 事件可从前端 devtools WS 帧、`thread/events` 端点或服务端日志观察；
> 时序断言的自动化锚点已固化在对应测试里（见每项末尾）。

## 前置条件

1. **思考通道**：配置一个 `model_supports_thinking` 覆盖的模型（如
   `kimi-k2-thinking`、`qwen3-235b`、`glm-4.6`、`gemini-2.5-pro`），或在
   `custom_models.json` 给自定义端点声明 `"supports_thinking": true`。
   判定的正/负例清单见 `tests/test_model_supports_thinking.py`。
2. **对照基线**：验收前记录一次现状 TTFT（从发送消息到首个可见字符的
   墙钟时间），每项验收后对比。

## 1. ReAct Thought 提前流式（`97d02ecdb`，最大项）

**修复**：锚点缓冲期间把 Thought 散文以 `thinking_delta` 实时流进思考块。

- **步骤**：发起一个多轮工具任务，如「调研 X 的近期进展，交叉验证两个
  来源」（ReAct 文本协议路径）。
- **预期时序**：`react_started` → **`thinking_delta`（思考块逐字增长）** →
  `tool_start` → `tool_end` → … → `text_delta`（最终回答）。
  TTFT ≈ 首个 LLM token 解码时间，不再等于整个 Thought/Action 循环。
- **UI**：回答气泡上方出现可折叠思考块，工具执行期间持续更新。
- **证伪点**：思考块内容**不得**出现 `Action:`、`<tool_call>`、JSON 工具
  参数；答案正文中引用的 "Thought:" 不得回显进思考块。
- **自动化锚点**：`tests/test_react_thought_streaming.py`（10 例，含
  `thinking_delta` 先于 `tool_start`）。

## 2. 首帧前 git 并行化（`ac9598f85`）

**修复**：`_git_status_summary` 的 4 次 git 子进程改 ThreadPoolExecutor
并行，最坏 ~6s → ~1.5s。

- **步骤**：在一个**大型/慢盘** git 仓库（或 WSL/网络盘挂载路径）发起新
  会话首条消息。
- **预期**：从发起到 `react_started` 的间隔 ≤ ~2s（原最坏 6s+）。
- **证伪点**：git 不可用的目录（非仓库）不应产生额外延迟或错误。

## 3. 工具规格签名缓存（`ac9598f85`）

**修复**：`_input_schema_from_handler` 加 `lru_cache(512)`，50 个工具的
`inspect.signature` 反射每进程只做一次。

- **步骤**：同一会话连续发 2+ 条消息，对比第 1 条与第 2 条的
  `react_started` 前延迟；第 2 条起应减少数十毫秒级开销。
- **证伪点**：修改某个 skill 后**新进程**应拿到新签名（缓存按 handler
  对象键控，进程内对象不变即安全）。

## 4. Native 循环工具后轮次文本 live 流式（`eb3843bbb`）

**修复**：native 协议下，工具执行后的轮次文本实时流出（此前 final
synthesis 整轮解码完才一次性倒出）。

- **步骤**：用 native tool 协议的模型跑同一调研任务，观察**最后一轮**
  （长综合回答）。
- **预期时序**：最后一个 `tool_end` → **`text_delta` 逐段流出（边解码边
  显示）** → `stats` → `done`；不再是长时间静默后整段瞬现。
- **UI**：工具间的中继叙述以独立散文气泡出现（Kimi 式
  散文→工具→回答交错），不再只有浓缩 checkpoint 一行。
- **证伪点**：文本含 `<tool_call` / `<function=` 时回退缓冲模式（单条
  完整送达）；首轮 preamble 仍是浓缩 checkpoint（过滤协议回声）。
- **已知接缝（稀有）**：工具后轮次超时/转向时，已流出的前缀会留在
  时间线里，恢复回答会重复该内容（恢复提示词有意不假设用户见过它）。
- **自动化锚点**：`tests/test_tool_bridge_text_streaming.py`（4 例）。

## 5. Chat 快路径装饰性节奏删除（`08df60625`）

**修复**：删除 live 路径 18 字符拆分 + 每片 12ms sleep（1KB 批量 delta
白睡 ~660ms）与伪流式 4ms  pacing。

- **步骤**：用**批量型 provider**（单次 delta 送整句/整段的兼容端点）
  在 chat 模式发消息。
- **预期**：文本按 provider 到达节奏即时渲染，无逐片段卡顿；非流式
  模型响应到达后一次性完整渲染（不再假打字机）。
- **证伪点**：无——内容为到达即渲染；若 UI 出现渲染压力（markdown
  频繁重排），说明前端按帧 join 未生效，应查前端而非恢复 sleep。

## 6. 思考模型覆盖面（`00d0c4fc8`）

**修复**：`model_supports_thinking` 新增 Kimi/Qwen3/GLM/Gemini 窄模式。

- **步骤**：用支持的模型跑任意任务，确认思考块出现**原生**思考内容
  （不是 ReAct Thought 散文，而是模型 thinking 通道的元推理）。
- **证伪点**：普通 `kimi-k2-instruct`、`qwen3-*-instruct-2507` 不应收到
  thinking 参数（负例已 pin）；这些型号下思考块由 #1 的 Thought 流式
  填充，依然可见。

## 总体回归基线

- 服务端：react 核心 341、守卫+实时网关 135、tool_bridge 187、
  网关/stream 353、模型判定 33——全绿。
- 既有失败（与本次无关，HEAD 可复现）：
  `tests/test_evolution_router.py` 3 例；
  `tests/test_realtime_cerebrum.py::test_background_tool_item_completes_after_turn_response`（flake）。

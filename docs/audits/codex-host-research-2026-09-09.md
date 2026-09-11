# CodexHost 源码研究与 Echo 借鉴清单

研究日期：2026-09-09。上游基线：`0b76b9de8c6f551506287d9a12905f9fdc860da2`，根 package.json 版本 0.6.1；OpenCode Adapter 使用 SDK 1.18.25。对照对象为本地 Echo 当前工作区（含未提交修改），不是一个干净发布版本。

实施进展：下文保留研究时的状态；后续已实现与验证的范围见 [SSE 与停止处理](opencode-sse-2026-09-09.md) 和 [模型控件与历史恢复](engine-capabilities-recovery-2026-09-09.md)。

## 结论

保留 Echo 自有界面和宿主权限体系，借鉴 CodexHost 的原生事件适配、终态核对、配置能力声明和历史派生校验。优先改进 OpenCode 内层运行链路；无需为此引入整个 TypeScript Host、Rust Launcher 或官方 Desktop 注入层。

这次完成了关键实现与相关测试断言的静态研究，没有安装或启动 CodexHost，没有运行上游测试，也没有修改 Echo 生产代码。本文中的缺口是源码观察或待验证风险，不是运行故障的复现报告；不声称读完全部仓库或验证全部 Harness。

## 1. 原生壳究竟复用了什么

CodexHost 依赖已安装的官方 Codex Desktop。Launcher 开启本机 CDP 端口，Shim 识别并代理 app-server 调用；Renderer Extension 增强原生界面。外部 Harness 先输出公共 HostEvent，再由 CodexTurnProjector 映射到 Desktop 接受的协议。

因此“使用原生壳”准确；“所有新增控件都来自官方原生组件”不准确。模型选择器、触发按钮样式等有项目自己的 DOM/CSS 实现。源码专门说明：过去复制官方生成的类名会被 Desktop 更新破坏，现改为自己维护小型样式表。

证据：
- [Launcher CDP 参数](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/crates/launcher/src/desktop_attachment.rs#L42)
- [Shim 调用识别](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/crates/shim/src/lib.rs#L275)
- [公共事件投影器](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/protocol-core/src/codex-ui-projector.ts#L757)
- [自有按钮样式及原因](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/renderer-extension/src/renderer-trigger-chip-style.ts#L1)

对 Echo 的启示：复现交互行为、状态和视觉规范即可，不依赖官方私有 DOM/类名，也不需要引入 Desktop 注入机制。

## 2. 最值得移植：OpenCode 事件订阅和状态核对（P0）

### 上游实现

SdkOpenCodeTransport 使用 SDK 的 event.subscribe 消费 SSE，处理断开、重连和 server.connected 边界。OpenCodeHarnessSession 按 sessionID、assistant messageID、parentID 关联当前回合，处理 message.part.delta / updated、session.status、question、permission 等。

断线恢复时查询状态及待处理交互；结束时读取完整 transcript 校正遗漏的 Part。仅收到 idle 不足以完成回合，还检查本回合的 busy/重连/取消证据和最终 assistant 信息，避免旧 idle 误结束新请求。

证据：
- [SSE 与有界重连](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/adapters/opencode/src/sdk-transport.ts#L399)
- [事件归属与增量处理](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/adapters/opencode/src/opencode-adapter.ts#L807)
- [重连与终态核对](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/adapters/opencode/src/opencode-adapter.ts#L1114)
- [旧 idle 与早到事件测试断言](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/adapters/opencode/test/opencode-adapter.test.ts#L1029)

### Echo 当前状态与建议

Echo 的 runtime/execution/opencode_backend.py:stream_prompt 仍每轮 GET 完整 /session/{id}/message；poll_s=0.1。MessageEvents 通过 baseline 和 Part 前缀去重，目前主要处理 text/tool。对话越长，重复传输、反序列化和扫描工作越多。前端 WebSocket 已有恢复机制，但不等于 OpenCode 内层也有 SSE 恢复。

建议在现有 Python/httpx 适配层接入 OpenCode 事件流；正常时处理增量，重连和终态才做完整核对，保留低频轮询作为兼容回退。复用现有 Echo 事件日志/reducer，不增加第二份对话正文数据库。

预期改善：流式到达及时性、长会话开销、错误定位。SSE 不能消除模型排队、推理或进程冷启动；不能承诺首字固定快几秒。

## 3. 取消必须等待原生执行停止（P0）

上游 turn.cancel 返回 cancellationRequested，而非完成。收到 abort error 时若 native session 仍 busy，后续 turn.start 被拒绝；idle 后才发布 cancelled 终态。关闭 session 也有等待和失败收尾。

Echo 前端已经区分 interrupt RPC 确认与回合终态，这是应保留的设计。OpenCode 内层 stream_prompt 在 interrupted 时先 yield react_cancelled，再在 finally 中调用 abort（2 秒超时，异常被抑制）并取消 HTTP 请求；未看到 native idle 确认。对热复用的纯文本进程，不能把“HTTP 客户端任务结束”直接当成“原生引擎停止”。

建议：增加 cancelling 阶段，先请求 abort，再核对 idle/原生终态；超时则将该连接标记不可复用并清理，不能立即归还热进程。不要通过重新发送用户任务恢复取消。

证据：
- [取消请求](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/adapters/opencode/src/opencode-adapter.ts#L581)
- [busy 时拒绝新回合的测试](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/adapters/opencode/test/opencode-adapter.test.ts#L1677)
- Echo：runtime/execution/opencode_backend.py:stream_prompt；
  frontend/src/core/realtime/use-realtime-thread.ts:interrupt。

这是从代码发现的竞争风险，本次没有实机复现取消后串回合。

## 4. 能力和实际配置决定 UI（P1）

上游契约区分 Harness、Model、Provider、Account；Session 提供 effectiveModel、effectiveThinkingOptionId、effectivePermissionModeId。能力描述声明是否支持模型选择、思考选项、权限切换、Fork/回退，以及权限只在创建时设定还是可以实时改变。

OpenCode 将 providerID/modelID 编成有版本的唯一引用，Thinking 来自模型实际 variants。UI 只提供当前模型支持的选项；加载、选择中、空目录、错误都有明确状态。测试要求：配置持久化失败时不能对界面宣告选择成功。

Echo 已有模型能力字段、reasoning_efforts 和免费标记规则，不能说“完全没有能力驱动 UI”。差别是信息分散在模型目录、引擎状态与控件中，缺少一个完整的引擎会话能力契约。

建议：
1. 先定义小型 EngineCapabilities 和 EffectiveExecutionConfig，沿用当前协议与状态存储。
2. 控件显示以确认后的实际配置为准；区分用户请求值和最终生效值。
3. 模型不支持 Thinking 就隐藏入口；未知能力不要默认当作全部支持。
4. 输入框常驻引擎图标、简短模型名；完整 provider、费用、能力说明放入菜单。
5. “仅讨论”有明确执行语义才保留，不能只切一个图标或提示词就宣称阻止工具执行。

证据：
- [会话状态与公开接口](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/harness-adapter/src/text-session.ts#L117)
- [能力与模型契约](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/shared-contracts/src/harness-models.ts#L143)
- [OpenCode 模型与 variants](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/adapters/opencode/src/model-catalog.ts#L122)
- [模型控件状态和选项过滤](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/renderer-extension/src/renderer-model-picker.ts#L118)
- [配置失败不发布成功的测试](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/adapters/opencode/test/opencode-adapter.test.ts#L926)

## 5. 文件 Diff、历史派生要有证据（P1）

上游仅将完整 native patch/diff 转为可靠文件修改记录。对派生历史，校验工作区归属、保留回合的语义、源 session 未被并发改变，以及模型/权限继承。原生摘要有写入延迟时有界重试；证据不完整则拒绝声称得到完整历史。

“编辑上一条消息”通过 native Fork 得到候选 session，成功校验后再采用；文档明确聊天历史移除不等于磁盘文件撤销。

Echo Codex 侧已有 fileChanges 转换，宿主也已有工具结果和执行证据机制；OpenCode 的 MessageEvents 不能独立承担所有文件证据转换。由于 Echo 禁用 OpenCode 内置工具、通过 HostToolBroker 执行文件操作，应该优先取宿主真实执行结果和前后 diff，不能原样套用只面向 OpenCode 内置 Patch Part 的方案。

建议保持两个边界：历史派生与文件回滚分开；工具“调用成功”与“实际产生哪些文件修改”分开。跨引擎聊天历史投递仍使用 Echo 现有 journal 机制。

证据：
- [完整 Diff 过滤](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/adapters/opencode/src/history.ts#L249)
- [文件身份校验](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/adapters/opencode/src/file-change-verification.ts#L51)
- [派生前后语义验证](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/adapters/opencode/src/history-derivation.ts#L42)
- [消息编辑语义说明](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/docs/opencode-edit-recovery.md)
- Echo：runtime/execution/codex_backend/events.py；
  runtime/sensing/gateway/realtime_engine_history.py。

## 6. 跨引擎协作的可观察性（P1/P2）

上游将委派创建与观察分开：start 返回 child thread、turn、状态和 read/wait 入口；read/wait 用 cursor 分页，结果可用性与任务状态分别表达。requestId 和任务摘要用于避免重复创建。

Echo 已有宿主委派、成员执行器和执行绑定，建议借鉴结果契约与幂等机制，不替换整个协作系统。验收重点是重复请求不重复创建任务，进度和最终结果不混淆，重连后可继续查看子任务。

不能照搬权限默认值：本次读到上游委派 open 使用 unattended-full-access，Echo 仍须按当前账号、线程、工作区和批准范围生成子任务权限。

证据：
- [委派读写契约](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/host-runtime/src/delegation-types.ts#L32)
- [创建、去重和委派执行策略](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/host-runtime/src/harness-delegation-coordinator.ts#L183)
- Echo：runtime/execution/engines.py；runtime/execution/opencode_roles.py。

## 7. 有价值，但不应整套搬运的部分

- **插件边界**：名称/图标/入口的 Manifest 和运行时能力分离值得借鉴。Echo 只有两个主要外部引擎，先规范接口，不急着扩展成插件市场。
- **插件化完成度**：上游文档明确 Renderer Picker、图标、偏好等仍未全部动态化；加载新插件不等于它自动出现在现有 Picker。
- **队列控制**：上游 HarnessOutputChannel 在消费者慢时往数组追加，本模块未设置容量上限。Echo Codex 客户端已有有界队列及背压处理，应保留并用于新增 SSE 通路。
- **运行模型**：CodexHost 主要保留各 Harness 自有工具语义；Echo 采用宿主共享工具与权限。接口思想可迁移，实际权限与工具执行路径不能混用。
- **技术栈**：学习行为契约即可，无需为了使用其 TS SDK 给 Python 后端再加常驻 Node 中间层。

证据：
- [插件化已完成范围和限制](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/docs/harness-plugin-runtime.md#L1)
- [输出通道实现](https://github.com/BytePioneer-AI/codex-host/blob/0b76b9de8c6f551506287d9a12905f9fdc860da2/packages/harness-adapter/src/output-channel.ts#L1)
- Echo：runtime/execution/codex_backend/client.py。

## 8. 建议实施顺序及验收

| 次序 | 改动 | 最小验收 |
| --- | --- | --- |
| 1 | OpenCode 取消确认与热进程回收 | busy 状态拒绝新回合；abort 超时不复用；保留取消前实际输出 |
| 2 | SSE 主通路、低频回退、终态核对 | 乱序/重复/遗漏事件不重字、不串回合；断线恢复不重发任务；慢消费者有界 |
| 3 | 实际配置与会话能力契约 | 切引擎后模型合法；失败不显示成功；不支持 Thinking 时无入口；重启可恢复 |
| 4 | 文件证据与派生历史验收 | Diff 与实际执行一致；证据缺失有明确状态；编辑消息不自动回滚文件 |
| 5 | 委派结果与幂等语义 | requestId 重试无重复任务；cursor 连续；失败/取消可区别；权限不扩大 |

性能验收按同一机器、模型和输入长度，分别测冷启动、热复用与长会话。记录：点击→宿主受理、引擎就绪、请求发出→首个引擎事件、首段可见文本、完成、取消请求→原生停止。报告样本数及 p50/p95；以前少量短回复的时间只能算探测，不能据此推导普遍提速比例。

本次未运行这些验收。研究产出是实施依据，不是这些能力已经移植完成的声明。

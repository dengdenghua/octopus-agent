# 多 Agent 协作竞争基线（2026-09-05）

本基线只比较已公开、可核查、当前主分支存在的能力，不把路线图当作已交付功能。参考来源：

- [OpenClaw multi-agent routing](https://github.com/openclaw/openclaw/blob/main/docs/concepts/multi-agent.md)
- [OpenClaw sub-agents](https://github.com/openclaw/openclaw/blob/main/docs/tools/subagents.md)
- [OpenClaw session management](https://github.com/openclaw/openclaw/blob/main/docs/concepts/session.md)
- [Hermes Agent README](https://github.com/NousResearch/hermes-agent/blob/main/README.md)
- [Hermes context engine](https://github.com/NousResearch/hermes-agent/blob/main/agent/context_engine.py)
- [Hermes context compressor](https://github.com/NousResearch/hermes-agent/blob/main/agent/context_compressor.py)

## 结论

Octopus 不是“所有维度都领先”。当前优势集中在**真实群聊协作语义、逐成员最小上下文、共享项目黑板、证据化交付和双向 A2A 互操作**；本轮已补齐可靠投递 Outbox、A2A 入站服务、按真实 usage 的跨进程子树熔断和可复现发布门槛。OpenClaw 在**渠道路由、会话运维和成熟度**上仍有优势；Hermes 在**可插拔上下文引擎、零上下文成本的工具流水线和云执行后端产品化**上仍有优势。

本轮完成后，Octopus 已从“界面像多人、执行仍偏单轮”进入“上下文、运行、质量、可靠交付、跨系统任务都有持久控制面”的阶段。最准确的定位是：**核心多人协作与 A2A 双向互操作有差异化领先，平台渠道、自学习和多后端生态仍在追赶。**

## 能力矩阵

| 维度 | Octopus | OpenClaw | Hermes | 判断 |
|---|---|---|---|---|
| 多角色群聊与角色可见性 | 主头像、独立消息、执行画面、显式成员路由 | 以渠道绑定和独立 session 为主 | 以主 Agent + 子 Agent 为主 | Octopus 领先 |
| 逐成员上下文 | `isolated/selective/fork`，授权交集、角色检索、预算与 Manifest 审计 | `isolated/fork`，默认隔离，fork 有父上下文上限 | 可插拔 context engine、压缩与请求级 select_context | Octopus 在多人选择性上下文领先 |
| 长项目记忆 | 事件日志 + 持久黑板 + 引用式产物 | 每 Agent SQLite session + bounded/redacted history + Memory Wiki | 记忆插件、会话搜索、自学习记忆 | 各有侧重，未形成绝对领先 |
| 运行生命周期 | SQLite run ledger、lease、恢复、终态幂等；交付 Outbox、退避/截止、重启恢复、右侧执行面人工 retry/dismiss、稳定消息 ID 去重 | durable child delivery、队列、重试、blocked retention、可人工 retry/dismiss | 子 Agent 生命周期与后台委派 | 核心可靠投递能力已对齐；OpenClaw 运维成熟度仍强 |
| 交付质量 | 相关性/证据/具体性/独立性矩阵；语义验证 fail-closed | 父 Agent 被要求复核子结果 | 主要由主 Agent 汇总 | Octopus 领先 |
| 跨系统协作 | A2A v1 双向：客户端发现/发送/持久任务/事件/刷新/取消/SSE；服务端 Agent Card、JSON-RPC、REST、流式、按调用者持久任务 | ACP、渠道与 Agent-to-Agent 工具成熟 | RPC 工具流水线、多运行后端 | Octopus 在标准 A2A 双向与桌面控制面结合上领先；渠道数量仍落后 |
| 自我学习 | 子 Agent 结果进入 trace-linked review queue，经人工晋升可写入经验账本、策略或 forged skill；有回放证据和 holdout 门槛 | 有技能与 Memory Wiki | 闭环技能生成与持续改进是核心能力 | Octopus 治理与审计更强，Hermes 自动化程度更高，尚无同任务实测胜负 |
| 生态与运维 | 桌面群聊体验强，已有 Local/Docker/K8s/SSH 与远程 backend；渠道产品化较少 | 渠道、绑定、诊断、清理、投递运维非常完整 | 本地/Docker/SSH/Modal/Daytona 等后端广 | OpenClaw 渠道领先；Hermes 云后端产品化领先 |

## 已建立的不可退化门槛

1. 状态询问不唤醒所有模型；显式 @mention 不扩大响应者集合。
2. 每位成员只收到其授权且相关的上下文；失败时降级为当前请求，不泄露全历史。
3. 长项目事实保存在事件日志和黑板中，Token 预算只裁剪本轮工作集。
4. 多人交付必须保留成员身份、证据与失败项；证据敏感任务不能仅凭文风评分宣布成功。
5. 本地协作运行与远程 A2A 任务均有持久编号、状态、事件与幂等终态。
6. 相同远程幂等编号在多 Worker 竞争下只有一个调用方获得派发权。
7. 五成员、两百条历史的长项目基准必须减少至少 60% 的重复上下文，并保证每位成员不超过自身预算；当前固定样本实测约 70%。
8. Agent 完成不等于送达：每条群聊结果必须先进入 Outbox，只有耐久日志落盘后才能标记送达；重放按固定消息 ID 收敛为一条。
9. A2A 入站任务必须通过官方 v1 JSON-RPC/REST 契约，并在进程重启后仍可 `GetTask`。
10. 子 Agent 树同时受全局并发、每根子树并发和显式嵌套深度限制；只读/工作区权限只能继承收窄，不能由子 Agent 放宽。
11. 每个子树的并发租约和 provider 实测 input/output tokens、cost 都进入共享 SQLite 账本；多 Worker 共用熔断判断，进程崩溃后过期租约自动回收。熔断范围是当前人类回合，不截断长期项目记忆。
12. `python -m runtime.evals.multi_agent_benchmark` 固定验证地址精度、上下文压缩、成员预算、回复成功率、证据覆盖、语义复核、恢复、去重、跨进程并发和实际 usage 熔断；任一门槛失败即发布失败。

## 下一阶段领先线

按影响优先级继续推进：

1. **渠道与运维面**：补齐类似 OpenClaw 的渠道绑定、诊断、滞留投递批量处理和保留策略。
2. **云执行后端产品化**：现有 Local/Docker/K8s/SSH 已具备底层能力，继续补 Modal/Daytona 类托管沙箱的一键配置与统一可观测面。
3. **跨项目外部基准**：在锁定版本和同模型/同预算条件下运行真实任务集；没有可复现结果，不宣称“所有维度领先”。

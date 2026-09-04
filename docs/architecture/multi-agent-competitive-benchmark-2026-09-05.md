# 多 Agent 协作竞争基线（2026-09-05）

本基线只比较已公开、可核查、当前主分支存在的能力，不把路线图当作已交付功能。参考来源：

- [OpenClaw multi-agent routing](https://github.com/openclaw/openclaw/blob/main/docs/concepts/multi-agent.md)
- [OpenClaw sub-agents](https://github.com/openclaw/openclaw/blob/main/docs/tools/subagents.md)
- [OpenClaw Swarm](https://github.com/openclaw/openclaw/blob/main/docs/tools/swarm.md)
- [OpenClaw session management](https://github.com/openclaw/openclaw/blob/main/docs/concepts/session.md)
- [OpenClaw channel catalog](https://github.com/openclaw/openclaw/blob/main/docs/channels/index.md)
- [Hermes Agent README](https://github.com/NousResearch/hermes-agent/blob/main/README.md)
- [Hermes context engine](https://github.com/NousResearch/hermes-agent/blob/main/agent/context_engine.py)
- [Hermes context compressor](https://github.com/NousResearch/hermes-agent/blob/main/agent/context_compressor.py)

## 结论

Octopus 不是“所有维度都领先”。当前优势集中在**真实群聊协作语义、逐成员最小上下文、共享项目黑板、证据化交付、实测成本熔断和外部渠道直达原生 AI 团队**；本轮已补齐可靠投递 Outbox、A2A 入站服务、按真实 usage 的跨进程子树熔断、可复现发布门槛、外部渠道到单 Agent / AI 团队的真实运行时路由、渠道持久运维面，以及跨 Worker / 跨重启的成员结果 collector。OpenClaw 近期增加的 Code Mode Swarm 已具备 Promise 并发、结构化结果、决策门、首完成返回、持久 collector、分组限流和实时进度，在**任意代码控制流、渠道覆盖和长期运维成熟度**上仍有明确优势；Hermes 在**可插拔上下文引擎、零上下文成本的工具流水线和云执行后端产品化**上仍有优势。

本轮完成后，Octopus 已从“界面像多人、执行仍偏单轮”进入“上下文、运行、质量、可靠交付、跨系统任务和外部消息入口都有持久控制面”的阶段。最准确的定位是：**面向人的原生群聊体验、逐成员选择性上下文、证据质量与实测成本治理有差异化领先；OpenClaw 的程序化 Swarm、渠道运维，Hermes 的自动学习和托管云后端仍领先。A2A 已形成双向完整控制面，但在没有同版本互测前只判断为强项，不宣称绝对领先。**

## 能力矩阵

| 维度 | Octopus | OpenClaw | Hermes | 判断 |
|---|---|---|---|---|
| 多角色群聊与角色可见性 | 主头像、独立消息、执行画面、显式成员路由 | 以渠道绑定和独立 session 为主 | 以主 Agent + 子 Agent 为主 | Octopus 领先 |
| 编排表达力 | `chat/cluster/swarm` 自动规划；JSON Schema 强制结果与一次纠错；声明式 DAG 扇入；多数投票；有限发现循环；`all/first_completed/first_success/quorum` 收敛，并协作取消多余执行；四种策略共用持久 collector | Code Mode Swarm：`Promise.all/race`、JSON Schema 结果、决策循环、持久 collector、分组并发/总量上限、阶段与日志 | Python 工具 RPC 可把多步工具流水线折叠为零上下文成本执行 | Octopus 在零脚本群聊编排、共识与取消后的成本治理领先；OpenClaw 在任意程序控制流领先；collector 核心能力已对齐，尚缺同任务压力互测 |
| 逐成员上下文 | `isolated/selective/fork`，授权交集、角色检索、预算与 Manifest 审计 | `isolated/fork`，默认隔离，fork 有父上下文上限 | 可插拔 context engine、压缩与请求级 select_context | Octopus 在多人选择性上下文领先 |
| 长项目记忆 | 事件日志 + 持久黑板 + 引用式产物 | 每 Agent SQLite session + bounded/redacted history + Memory Wiki | 记忆插件、会话搜索、自学习记忆 | 各有侧重，未形成绝对领先 |
| 运行生命周期 | SQLite run ledger、lease、恢复、终态幂等；逐成员 collector 事务写入、结果哈希、重复幂等、冲突拒绝、revision 长轮询、跨重启查询、提前结算取消清单；失败成员按新 generation 原位重试，旧 attempt 永久保留；交付 Outbox、退避/截止、人工 retry/dismiss、稳定消息 ID 去重 | durable child/collector result、队列、稳定幂等键、重试、blocked retention、积压反压、级联停止、可人工 retry/dismiss | 子 Agent 生命周期与后台委派 | Octopus 已对齐持久 collector、等待和失败历史核心语义；OpenClaw 在自动重派、积压运维和 UI 操作闭环更成熟 |
| 交付质量 | 相关性/证据/具体性/独立性矩阵；语义验证 fail-closed | 父 Agent 被要求复核子结果 | 主要由主 Agent 汇总 | Octopus 领先 |
| 成本与失控治理 | 每棵子树的真实 provider input/output tokens、cost、并发租约写入共享 SQLite；跨 Worker 熔断 | 每次子任务报告 usage/cost；全局/每父/每 Swarm 分组并发与总量限制，但公开文档未显示基于实际 token/cost 的共享熔断 | 依赖模型选择、压缩与零上下文 RPC 降低成本 | Octopus 在可审计的实测成本熔断领先；OpenClaw 在分组 fan-out 上限更完整 |
| 跨系统协作 | A2A v1 双向：客户端发现/发送/持久任务/事件/刷新/取消/SSE；服务端 Agent Card、JSON-RPC、REST、流式、按调用者持久任务 | A2A、ACP、渠道与 Agent-to-Agent 工具成熟 | RPC 工具流水线、多运行后端 | Octopus 双向控制面完整；缺少同版本互测，不判绝对领先 |
| 自我学习 | 子 Agent 结果进入 trace-linked review queue，经人工晋升可写入经验账本、策略或 forged skill；有回放证据和 holdout 门槛 | 有技能与 Memory Wiki | 闭环技能生成与持续改进是核心能力 | Octopus 治理与审计更强，Hermes 自动化程度更高，尚无同任务实测胜负 |
| 外部消息渠道 | 26 个适配器；新增 IRC/IRCv3 与 Twitch 长连接、断线重连、UTF-8 协议分片和热替换回滚；可绑定单 Agent 或持久 AI 团队；统一保存真实健康探测、延迟、最近收发/错误、失败计数、线程绑定数和能力矩阵；跨重启按事件摘要幂等去重，避免团队重复执行；未实现主动探测的适配器明确显示“不支持”，不造假绿灯 | 当前公开目录约 32 个入口（含内置、官方和外部插件），账户/线程绑定、诊断、清理和投递运维成熟 | Telegram、Discord、Slack、WhatsApp、Signal、CLI | OpenClaw 仍在覆盖和长期运维成熟度领先；Octopus 在原生团队路由、持久幂等、长连接生命周期及“配置/运行”状态分离上有差异化 |
| 执行后端生态 | 桌面群聊体验强，已有 Local/Docker/K8s/SSH 与远程 backend；远端 Bearer 凭据已加密保存并贯通 HTTP/WS，但执行后端尚未统一接线 | 本地 Gateway、云 Worker 与节点体系成熟 | 本地/Docker/SSH/Singularity/Modal/Daytona/Vercel Sandbox 等七类后端 | Hermes 云后端产品化领先；Octopus 仍在补生产接线 |

## 已建立的不可退化门槛

1. 状态询问不唤醒所有模型；显式 @mention 不扩大响应者集合。
2. 每位成员只收到其授权且相关的上下文；失败时降级为当前请求，不泄露全历史。
3. 长项目事实保存在事件日志和黑板中，Token 预算只裁剪本轮工作集。
4. 多人交付必须保留成员身份、证据与失败项；证据敏感任务不能仅凭文风评分宣布成功。
5. 本地协作运行与远程 A2A 任务均有持久编号、状态、事件与幂等终态。
6. 相同远程幂等编号在多 Worker 竞争下只有一个调用方获得派发权。
7. 五成员、两百条历史的长项目基准必须减少至少 60% 的重复上下文，并保证每位成员不超过自身预算；当前固定样本实测减少 97.81%，只选择 425 tokens，成员预算违规为 0。
8. Agent 完成不等于送达：每条群聊结果必须先进入 Outbox，只有耐久日志落盘后才能标记送达；重放按固定消息 ID 收敛为一条。
9. A2A 入站任务必须通过官方 v1 JSON-RPC/REST 契约，并在进程重启后仍可 `GetTask`。
10. 子 Agent 树同时受全局并发、每根子树并发和显式嵌套深度限制；只读/工作区权限只能继承收窄，不能由子 Agent 放宽。
11. 每个子树的并发租约和 provider 实测 input/output tokens、cost 都进入共享 SQLite 账本；多 Worker 共用熔断判断，进程崩溃后过期租约自动回收。熔断范围是当前人类回合，不截断长期项目记忆。
12. `python -m runtime.evals.multi_agent_benchmark` 固定验证地址精度、上下文压缩、成员预算、回复成功率、证据覆盖、语义复核、恢复、结果去重、持久 collector、失败重试历史保留、渠道入站跨 Worker 幂等、跨进程并发和实际 usage 熔断；任一门槛失败即发布失败。
13. 渠道设置保存的 Agent 必须进入真实消息分发路径；团队绑定必须按成员隔离执行、受控并发并携带成员与主回复元数据，不能只是界面标签。
14. Agent 团队定义与渠道绑定都必须跨服务重启恢复；陈旧的历史绑定应降级到默认路由，不能让整个外部渠道失声。
15. 渠道“已配置”不能冒充“运行正常”：健康状态必须来自适配器真实探测或成功送达；异常立即降级，诊断跨重启保留，且错误持久化前必须移除 Token、密钥与 Bearer 凭证。
16. 外部平台重试同一事件不得让 Agent 或 AI 团队重复执行；事件指纹只保存 SHA-256 摘要、跨重启生效并采用有界窗口，拦截次数进入运维诊断。
17. 远程 Octopus 凭据不得写入 backend 清单、响应或日志；必须进入 AES-256-GCM 凭据库，并在健康检查、HTTP 代理和 WebSocket 实时代理上保持同一认证边界。
18. 并行协作必须支持等待全部、首个完成、首个成功和法定人数四种收敛策略；一旦策略满足或已不可能满足，未再需要的成员必须收到协作取消信号，不能继续隐性消耗 Token。
19. 每位成员的首轮结果必须在完成时独立写入持久 collector；跨 Worker 并发写入必须事务收敛，重复结果幂等、冲突结果拒绝、终态不可追加，协调器重启后仍可按 revision 长轮询已完成与待取消成员。失败成员重试必须进入新 generation，旧 attempt 不得覆盖或删除。

## 下一阶段领先线

按影响优先级继续推进：

1. **渠道覆盖与运维深度**：在现有 26 渠道、单 Agent / AI 团队绑定、统一诊断和 IRC/Twitch 长连接生命周期之上，继续补齐 OpenClaw 已覆盖的 Nextcloud Talk、Nostr、Zalo 等入口，并完善滞留投递批量处理、线程绑定明细和保留策略。
2. **通用控制流与 collector 运维**：持久 collector 已进入统一协作运行账本，支持跨重启查询、revision 长轮询及失败 attempt 保留；下一步把原位 reopen 接到自动/人工重新派发和执行画面，再补积压反压/批处理，然后决定是否暴露受限代码控制流，避免形成第二套运行时。
3. **云执行后端产品化**：现有 Local/Docker/K8s/SSH 已具备底层能力，远端认证链已贯通；下一步统一生产执行协议、真正启用 SSH tunnel，再补 Modal/Daytona 类托管沙箱的一键配置与可观测面。
4. **跨项目外部基准**：在锁定版本和同模型/同预算条件下运行真实任务集；没有可复现结果，不宣称“所有维度领先”。

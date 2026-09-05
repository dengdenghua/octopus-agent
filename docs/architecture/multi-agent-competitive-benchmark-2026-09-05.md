# 多 Agent 协作竞争基线（2026-09-05）

本基线只比较已公开、可核查、当前主分支存在的能力，不把路线图当作已交付功能。参考来源：

- [OpenClaw multi-agent routing](https://github.com/openclaw/openclaw/blob/main/docs/concepts/multi-agent.md)
- [OpenClaw sub-agents](https://github.com/openclaw/openclaw/blob/main/docs/tools/subagents.md)
- [OpenClaw Swarm](https://github.com/openclaw/openclaw/blob/main/docs/tools/swarm.md)
- [OpenClaw session management](https://github.com/openclaw/openclaw/blob/main/docs/concepts/session.md)
- [OpenClaw context engine](https://github.com/openclaw/openclaw/blob/main/docs/concepts/context-engine.md)
- [OpenClaw active memory](https://github.com/openclaw/openclaw/blob/main/docs/concepts/active-memory.md)
- [OpenClaw channel catalog](https://github.com/openclaw/openclaw/blob/main/docs/channels/index.md)
- [Hermes Agent README](https://github.com/NousResearch/hermes-agent/blob/main/README.md)
- [Hermes Agent v2026.8.31（Bot Mode / live subagent steering）](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.31)
- [Hermes Bot Mode group rounds（核验提交 `f159e581`）](https://github.com/NousResearch/hermes-agent/blob/f159e581c7afd22a5c94652c569e3859f1b994d2/apps/desktop/src/plugins/hermes-bots/group-rounds.ts)
- [Hermes context engine](https://github.com/NousResearch/hermes-agent/blob/main/agent/context_engine.py)
- [Hermes context compressor](https://github.com/NousResearch/hermes-agent/blob/main/agent/context_compressor.py)
- [Octopus Cowork Context Engine v1](./cowork-context-engine-v1.md)

本次核验锁定 OpenClaw [`c748cd57`](https://github.com/openclaw/openclaw/commit/c748cd5714b8160f0ce0a895071f039877082f08)（2026-09-04，美国西部时间）和 Hermes [`79445a49`](https://github.com/NousResearch/hermes-agent/commit/79445a496c86a19332ad786494b8384d2167e2d0)（2026-09-04）。OpenClaw 当前已经公开可插拔 ContextEngine 的 `assemble/compact/commitTurn` 契约、子 Agent 创建/结束钩子、持久后端线程投影，以及按意图升级的 Active Memory 深度召回；最新提交还强化了任务进度恢复、历史投影预算和流压缩。这些能力会改变上下文与长期记忆维度的判断，不能再只按固定窗口或普通摘要评估。上游仍在快速变化；“领先”判断必须同时写明能力维度与核验版本，不能永久化为品牌结论。

## 结论

Octopus 不是“所有维度都领先”。当前优势集中在**并行群体执行、逐成员可审计的最小上下文、共享项目黑板、证据化交付、实测成本熔断和外部渠道直达原生 AI 团队**；本轮已补齐可靠投递 Outbox、A2A 入站服务、按真实 usage 的跨进程子树熔断、可复现发布门槛、外部渠道到单 Agent / AI 团队的真实运行时路由、渠道持久运维面、跨 Worker / 跨重启的成员结果 collector、运行中按成员定向纠偏、逐成员持久私有会话与授权感知的增量上下文、按 contract hash 划分 epoch 的持久后端线程投影、默认 Adaptive Recall MMR 上下文选择、带来源校验和原文审计的子 Agent 压缩检查点、按会话/回合原子登记的上下文生命周期账本，以及进入真实群聊路径的 versioned Context Engine v1 宿主。该宿主覆盖 `bootstrap/ingest/assemble/compact/commit_turn/maintain/member-start/member-end`，兼容旧选择器，并具有超时、连续失败隔离、版本拒绝和正文外审计。OpenClaw 的 Code Mode Swarm 已具备 Promise 并发、结构化结果、决策门、首完成返回、持久 collector、分组限流和实时进度；其 ContextEngine 仍允许更自由的 transcript rewrite 与 compaction ownership，Active Memory 的跨会话召回也更产品化，因此在**任意代码控制流、上下文插件生态、渠道覆盖和长期运维成熟度**上仍有明确优势。Hermes 已交付默认开启的 Bot Mode、具名头像群聊、`@` 路由、持久 peer 私信和运行中子 Agent 纠偏，因此 Octopus 已不能把“像真人的群聊”单独列为绝对领先；Hermes 还在**模型驱动记忆生态、云执行后端产品化和消费级群聊打磨**上有优势。

本轮完成后，Octopus 已从“界面像多人、执行仍偏单轮”进入“上下文、运行、质量、可靠交付、跨系统任务和外部消息入口都有持久控制面”的阶段。最准确的定位是：**Octopus 在并行群体执行、逐成员选择性上下文的授权与审计、证据质量、实测成本治理，以及可恢复、可审计的成员纠偏上有差异化领先；Hermes 已追平真人式群聊的核心交互，并在自动学习和托管云后端领先；OpenClaw 的程序化 Swarm、渠道运维仍领先。A2A 已形成双向完整控制面，但在没有同版本互测前只判断为强项，不宣称绝对领先。**

## 能力矩阵

| 维度 | Octopus | OpenClaw | Hermes | 判断 |
|---|---|---|---|---|
| 多角色群聊与角色可见性 | 主头像、独立消息、执行画面、显式成员路由；面向并行任务协作 | 以渠道绑定、独立 session 与 Swarm 进度卡为主 | Bot Mode 默认开启：具名头像、群名/群图、`@` 成员、持久房间；最多 6 人，最多 3 轮，成员串行轮询 | Octopus 的执行型群协作更强；Hermes 的消费级群聊成熟度已追平或局部领先，不判绝对胜负 |
| 编排表达力 | `chat/cluster/swarm` 自动规划；JSON Schema 强制结果与一次纠错；声明式 DAG 扇入；DAG 节点支持基于上游结构化结果的 `when` 分支，以及 `all/any/not` 组合和 11 类比较操作；条件仅能读取显式依赖且有深度/节点上限，不执行任意代码；多数投票；有限发现循环；`all/first_completed/first_success/quorum` 收敛并取消多余执行 | Code Mode Swarm：`Promise.all/race`、JSON Schema 结果、决策循环、持久 collector、分组并发/总量上限、阶段与日志 | Python 工具 RPC 可把多步工具流水线折叠为零上下文成本执行 | Octopus 在零脚本群聊编排、安全可审计分支、共识与取消后的成本治理领先；OpenClaw 在任意程序控制流的自由度领先，但相应攻击面更大；尚缺同任务压力互测 |
| 逐成员上下文 | `isolated/selective/fork`，授权交集、角色检索、预算与 Manifest 审计；`summary` 授权会生成服务器侧的结构化里程碑流，只保留目标/约束/决定/风险/进展并隐藏凭据和闲聊，不再退化为空历史；每成员私有 subagent session 跨轮持久续接，以匿名事实游标只发送新增或变化的工作记忆；每成员投影使用稳定 contract hash 作为 `thread_bootstrap` epoch，普通事实追加复用后端线程并只发 delta，授权范围、职责或上下文模式变化则切换 epoch 和干净 session；正常追加可续接，但已授权历史被删除、修改、重排或项目事实被撤回时同样轮换，底层 session 丢失自动全量恢复；续接时旧历史按只读数据编码并置于前部，当前纠偏固定在最后，持久层只记录本轮原始请求而非展开后的嵌套历史；同成员重叠回合以跨 Worker 租约串行化，不同成员保持并行；默认 Adaptive Recall MMR 在普通请求中保持快速 Hybrid-MMR，只有历史/因果追溯意图才扫描完整授权历史并提高旧决定、约束、风险及时间覆盖的权重；每轮装配以 `(session_id, turn_id)` 作为原子 advancement key，持久记录正文外的计划/授权/来源集合哈希，逐成员提交成功或中止，支持相同重放幂等、冲突拒绝、部分提交、跨重启恢复和首次成功前回滚；Context Engine v1 覆盖八个生命周期钩子，具备 API 版本协商、超时/隔离和正文外诊断；也支持具名注册、环境配置与 `octopus.cowork_context_engines` entry point；`assemble` 只能返回已授权 source id，未知 id 丢弃、异常回退、预算再次强制 | 子 Agent 默认隔离、按需 `fork`；可插拔 ContextEngine 具备预算装配、压缩、原子提交、持久线程投影和子 Agent 创建/结束生命周期钩子，但公开文档未显示团队 fan-out 中按角色、授权清单和事实差量为每个成员生成不同工作集 | 可插拔 context engine、压缩与请求级 `select_context`；Bot Mode 每成员持久 session，每轮只投递其未读房间增量 | Octopus 在“同一团队任务内逐成员差异化、授权可审计、按意图升级、原子推进、逐成员持久投影和安全插件隔离”领先；OpenClaw 在允许 transcript rewrite/compaction ownership 的插件自由度及生态成熟度上领先；Hermes 的模型驱动压缩质量仍需同任务实测后判断胜负 |
| 长项目记忆 | 事件日志 + 持久黑板 + 引用式产物；主线程支持追加式、双触发自动压缩和模型/确定性摘要；子 Agent 私有 session 达到阈值后生成带源摘要哈希的持久检查点，保留最初目标与最新进展，刷新后仍保留全部原始轮次供审计；损坏/过期检查点验证失败即退回原始历史，重启后可继续使用有效检查点 | 每 Agent SQLite session、bounded/redacted history、Memory Wiki、带来源谱系的删除，以及只在普通召回不足时升级的 Active Memory 深度召回 | 记忆插件、会话搜索、自学习记忆 | Octopus 在可验证检查点、原文审计链和团队共享黑板上更强；OpenClaw 在跨会话召回产品化、记忆来源治理和插件生态上更强；Hermes 的模型驱动记忆与自动学习也有优势，必须用长任务召回基准实测，不判绝对领先 |
| 运行生命周期 | SQLite run ledger、lease、恢复、终态幂等；逐成员 collector 事务写入、结果哈希、重复幂等、冲突拒绝、revision 长轮询、跨重启查询、提前结算取消清单；运行中可对仍活跃的单个成员追加纠偏或单独停止，单成员停止先冻结其后台任务、结算其取消状态，其他成员继续执行；纠偏按成员/代际/序号持久化、进入事件审计并在安全模型边界读取，直接单轮调用收到中途纠偏时废弃旧答复后重启；成员结果提交与最新纠偏序号在同一事务中校验，竞态下纠偏获胜、过期答复不会落库；归档时删除正文但保留长度与哈希；失败成员按新 generation 定向重派到持久后台队列，旧 attempt 永久保留，成功成员不重跑，入队后立即唤醒执行器；执行画面按成员显示等待/完成/失败/重试、失败原因和 attempt 历史，并可仅重试失败成员；跨运行运维接口可集中查看全部 collector，并对多个失败运行整批预留、预绑定、激活、停止或归档；停止会取消尚未执行的成员、冻结后台任务终态并丢弃晚到结果；自动保留策略按期限和每会话数量批量归档，保留成员/状态/attempt/哈希/时间等审计摘要，同时清除大正文与旧队列绑定；队列按线程/全局双限额反压，异常预留会释放并回写 collector；后台执行跨群轮转、按积压自适应并行且有单轮上限；交付 Outbox、退避/截止、人工 retry/dismiss、稳定消息 ID 去重 | durable child/collector result、队列、稳定幂等键、重试、blocked retention、积压反压、级联停止、可人工 retry/dismiss | 持久 group session、晚到回复回收、停止/hold、peer 私信；子 Agent 可运行中 steer/stop 并保留部分结果，支持 Schema 与单次成本 | Octopus 的纠偏多了持久序列、重启回放、结果竞态栅栏与归档审计；Hermes 已具备成熟实时 steer/stop。Octopus 在 collector 运维、并行公平调度和审计保留上更完整；尚缺同任务长期压力互测，不宣称绝对领先 |
| 交付质量 | 相关性/证据/具体性/独立性矩阵；语义验证 fail-closed | 父 Agent 被要求复核子结果 | 主要由主 Agent 汇总 | Octopus 领先 |
| 成本与失控治理 | 每棵子树的真实 provider input/output tokens、cost、并发租约写入共享 SQLite；跨 Worker 熔断 | 每次子任务报告 usage/cost；全局/每父/每 Swarm 分组并发与总量限制，但公开文档未显示基于实际 token/cost 的共享熔断 | 依赖模型选择、压缩与零上下文 RPC 降低成本 | Octopus 在可审计的实测成本熔断领先；OpenClaw 在分组 fan-out 上限更完整 |
| 跨系统协作 | A2A v1 双向：客户端发现/发送/持久任务/事件/刷新/取消/SSE；服务端 Agent Card、JSON-RPC、REST、流式、按调用者持久任务 | A2A、ACP、渠道与 Agent-to-Agent 工具成熟 | RPC 工具流水线、多运行后端 | Octopus 双向控制面完整；缺少同版本互测，不判绝对领先 |
| 自我学习 | 子 Agent 结果进入 trace-linked review queue，经人工晋升可写入经验账本、策略或 forged skill；有回放证据和 holdout 门槛 | 有技能与 Memory Wiki | 闭环技能生成与持续改进是核心能力 | Octopus 治理与审计更强，Hermes 自动化程度更高，尚无同任务实测胜负 |
| 外部消息渠道 | 26 个适配器；新增 IRC/IRCv3 与 Twitch 长连接、断线重连、UTF-8 协议分片和热替换回滚；可绑定单 Agent 或持久 AI 团队；统一保存真实健康探测、延迟、最近收发/错误、失败计数、线程绑定数和能力矩阵；跨重启按事件摘要幂等去重，避免团队重复执行；未实现主动探测的适配器明确显示“不支持”，不造假绿灯 | 当前公开目录约 32 个入口（含内置、官方和外部插件），账户/线程绑定、诊断、清理和投递运维成熟 | Telegram、Discord、Slack、WhatsApp、Signal、CLI | OpenClaw 仍在覆盖和长期运维成熟度领先；Octopus 在原生团队路由、持久幂等、长连接生命周期及“配置/运行”状态分离上有差异化 |
| 执行后端生态 | 已有 Local/Docker/K8s/SSH 与远程 backend；远端 Bearer 凭据加密保存并贯通 HTTP/WS；私网运行时可经逐请求 OpenSSH 隧道访问，健康检查、HTTP 与实时群聊共用同一链路，隧道失败不允许静默直连；管理面声明直连/SSH 能力并可配置主机、用户、端口和密钥文件 | 本地 Gateway、云 Worker 与节点体系成熟 | 本地/Docker/SSH/Singularity/Modal/Daytona/Vercel Sandbox 等七类后端 | Octopus 已补齐安全 SSH 私网链路；Hermes 在托管云沙箱种类和一键产品化上仍领先 |

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
12. `python -m runtime.evals.multi_agent_benchmark` 固定验证地址精度、上下文压缩、成员预算、逐成员增量上下文与授权轮换、按 epoch 的持久后端线程投影、可插拔选择器的权限/预算/故障回退、上下文装配 advancement key 的幂等/冲突拒绝/逐成员提交/跨重启恢复/正文零复制、回复成功率、证据覆盖、语义复核、恢复、结果去重、持久 collector、成员纠偏的定向/顺序/重启恢复、单成员停止不影响其他成员、失败重试历史保留、批量重试/停止、归档保留、安全决策分支、SSH 隧道失败关闭、渠道入站跨 Worker 幂等、跨进程并发和实际 usage 熔断；任一门槛失败即发布失败。
13. 渠道设置保存的 Agent 必须进入真实消息分发路径；团队绑定必须按成员隔离执行、受控并发并携带成员与主回复元数据，不能只是界面标签。
14. Agent 团队定义与渠道绑定都必须跨服务重启恢复；陈旧的历史绑定应降级到默认路由，不能让整个外部渠道失声。
15. 渠道“已配置”不能冒充“运行正常”：健康状态必须来自适配器真实探测或成功送达；异常立即降级，诊断跨重启保留，且错误持久化前必须移除 Token、密钥与 Bearer 凭证。
16. 外部平台重试同一事件不得让 Agent 或 AI 团队重复执行；事件指纹只保存 SHA-256 摘要、跨重启生效并采用有界窗口，拦截次数进入运维诊断。
17. 远程 Octopus 凭据不得写入 backend 清单、响应或日志；必须进入 AES-256-GCM 凭据库，并在健康检查、HTTP 代理和 WebSocket 实时代理上保持同一认证边界。配置 SSH 的私网运行时必须对三条路径都建立真实隧道，隧道失败即失败，不得回退直连。
18. 并行协作必须支持等待全部、首个完成、首个成功和法定人数四种收敛策略；一旦策略满足或已不可能满足，未再需要的成员必须收到协作取消信号，不能继续隐性消耗 Token。
19. 每位成员的首轮结果必须在完成时独立写入持久 collector；跨 Worker 并发写入必须事务收敛，重复结果幂等、冲突结果拒绝、终态不可追加，协调器重启后仍可按 revision 长轮询已完成与待取消成员。失败成员重试必须进入新 generation 和持久后台队列，旧 attempt 不得覆盖或删除，既有成功成员不得被整组重跑。
20. 后台协作队列必须同时受线程级和全局容量约束；多人重试必须整批预留、完成 collector 绑定后整体激活，容量不足不得部分入队或提前改变 collector，崩溃遗留的未激活预留必须自动释放并进入可诊断终态。
21. 后台执行器必须跨群轮转取任务，按实际积压自适应并行，并限制单轮处理量；任何一个大群都不得让其他群长期饥饿，调度并行度必须进入健康状态和发布基准。
22. 同一协作运行、成员和重试代际只能绑定一个后台任务；并发点击或多 Worker 竞争必须只有一个事务赢家，失败请求要释放自己的队列预留，不能重复调用模型。
23. 长项目必须能跨运行集中列出 collector，并对多个失败运行一次性重试；整批任务必须共同预留和激活，容量不足时所有 collector 保持原代际，中途失败时已重开的运行必须明确结算。
24. 用户停止多人协作后，未开始的成员不得再调用模型，后台任务必须进入持久 `cancelled` 终态；已经进入不可中断 provider 调用的线程允许协作式收尾，但其晚到成功或失败结果均不得写入共享黑板、collector 或群聊。跨运行停止必须幂等，并保留既有终态父运行的历史。
25. Collector 保留策略必须同时支持时间上限和每会话数量上限，活动运行永不归档；归档要在单个事务中保留成员、状态、attempt、结果哈希和时间摘要，清除模型正文与旧重试绑定，并从默认运维列表隐藏。归档后不得使用残缺正文重试。
26. DAG 条件分支只能读取该节点显式声明的上游依赖；条件语言必须是有深度和节点数量上限的数据表达式，未知字段、未知操作符、类型不兼容和越权引用全部 fail-closed，条件为假不得产生模型调用。任何调用方文本都不能借此执行 Python、JavaScript 或 shell。
27. 远程运行时清单必须公开声明直连或 SSH 隧道能力；只有显式 SSH 配置才能访问私网/回环运行时地址。OpenSSH 转发必须启用主机密钥校验、批处理模式和 `ExitOnForwardFailure`，并在请求结束时回收进程；不得把“已保存 SSH 配置”显示成“链路已启用”。
28. 对运行中成员的纠偏必须只进入指定成员的当前代际，按单调序号持久化并唤醒 collector 长轮询；多 Worker 并发追加必须生成唯一、连续的序号，不得覆盖或丢失。执行器在每个安全模型边界读取新要求，无法原地修改的单轮调用必须丢弃旧答复并有界重启。结果落库必须在事务中校验执行器已见的纠偏序号，纠偏与完成竞态时不得发布过期答复。进程重启后纠偏可从游标重放，运行已结算或成员已完成时必须拒绝晚到纠偏；归档不得保留纠偏正文。
29. 停止某个成员必须先冻结其已绑定的后台任务，再以 `cancelled` 结果事务结算该成员；其他成员继续运行，父协作不能被误停。已经结算的成员必须拒绝晚到停止，重复停止同一成员必须幂等，无法中断的 provider 晚到结果不得覆盖取消终态。
30. 每位成员的私有 subagent session 与上下文游标必须按协作会话和成员持久隔离；续接时按匿名事实游标只投递新增或变化的授权工作记忆，不能因为一条事实变化就重发整个章节，暂时离开相关性窗口的既有事实再次命中时也不得重复发送。授权范围、角色职责或上下文模式变化时 contract hash 必须变化并清除旧续接；正常追加只扩展授权历史前缀，但已授权历史被删除、修改、重排或项目事实被撤回时必须识别为非追加变更并轮换 session，防止撤回内容继续残留。底层 session 丢失时必须删除坏游标并以完整授权上下文恢复，不能返回伪成功。同一成员的重叠回合必须通过跨进程、可过期接管的租约串行化，任意时刻只有一个 Worker 能修改其私有 session；不同成员不得受该锁影响。
31. 多人上下文选择插件只能看到完成 ContextGrant 裁剪后的候选事实，并只能返回候选的匿名 source id；宿主必须丢弃未知/重复 id、重新实施 Token 预算并按原时间顺序渲染，插件不能注入任意 prompt 文本。插件异常必须回退确定性选择，审计只记录引擎名、调用/回退/拒绝计数与异常类型，不能记录异常正文。未显式配置时不得加载第三方代码；具名注册、环境配置和 entry-point 发现必须进入真实群聊与聚焦成员路径。
32. 子 Agent 会话续接必须把旧历史作为只读数据放在当前请求之前，并对可能伪造历史边界的内容编码；用户最新请求必须保持为最终且权威的 prompt 段。会话和角色记忆只能持久化本轮原始请求，禁止把已展开的旧 transcript 再次写回，否则会导致递归 Token 膨胀并可能让过期任务在纠偏后重新激活。
33. 默认多人上下文选择必须在硬 Token 预算内联合考虑当前任务/职责相关性、事实类型优先级、时间和信息多样性；高度相似的重复记录不得挤掉独立事实。默认实现必须是宿主内置且确定性的，不得因为启用智能选择就自动加载第三方代码；宿主仍需实施授权边界、未知 ID 拒绝和二次预算校验。
34. 长期子 Agent 会话必须在固定阈值后建立持久压缩检查点，并以原始轮次摘要哈希验证检查点来源；检查点必须保留早期目标和最新结果，定期随新轮次刷新，进程重启后仍可继续。成员 Prompt 过长时必须首尾保留，避免上下文清单占满头部后把末尾真实任务裁掉。原始轮次不得因压缩而删除，确保审计与恢复；历史被修改导致哈希失配时不得继续使用旧检查点。压缩统计只能公开轮次数、策略和有效性，不能复制私有正文。
35. `summary` 历史授权不得实现为空上下文，也不得把完整聊天原文伪装成摘要。服务器必须只投递有界的目标、约束、决定、风险和进展里程碑，过滤闲聊并在进入模型上下文前隐藏凭据/长不透明值；单人实时、多成员扇出、后台任务和新成员 catch-up 必须使用同一授权投影。摘要事实仍受角色检索、硬 Token 预算和撤回检测约束。
36. 未完成任务只能被明确的短续接、状态追问、指代纠正或追加要求恢复；一条完整的新请求必须建立新执行合同，即使旧回复曾预告后续动作，也不得复活旧目标。协调执行的自动修复提示必须以不可歧义的当前目标锚定，不能只依赖冻结的历史快照；“用于界面验收”等说明性文字不得把本应逐成员短答的群聊误判为重型编排。
37. 普通请求不得无条件扫描或重发完整历史；只有明确的历史、回顾或因果追溯意图才能升级为深度回溯。升级候选仍必须来自该成员已经授权的上下文，选择器返回的未知或越权 source id 必须丢弃，宿主必须再次实施 Token 预算，并在审计中记录 `deep_recall_escalated`，不得记录私有正文。
38. 多人执行画面必须把上下文调度结果显示为普通状态信息，而不是隐藏在调试日志里：至少区分“按需选取”和“长期回溯”，显示本轮已选/原始 Token 与节省比例；不得展示候选正文、授权内容或内部异常文本，也不得用额外气泡挤占群聊主时间线。
39. 每轮多人上下文装配必须以 `(session_id, turn_id)` 原子登记，登记内容只能包含引擎、Token 统计、授权与来源集合哈希，禁止复制请求、候选或结果正文。同一 advancement key 的相同重放必须幂等，不同请求或计划必须拒绝；成员成功和中止须在同一事务内独立结算，允许保留部分成功。尚无成员成功时允许回滚并保留墓碑；已有成功提交后禁止伪回滚。账本必须跨进程重启可读，并进入真实 WebSocket 群聊路径和固定发布基准。
40. 每位成员的持久模型线程投影必须公开稳定、正文外的 epoch。角色、授权或有效上下文模式不变时，普通事实追加不得重建线程或重发完整工作记忆，只补发变化 delta；上述合同任一项变化时 epoch 必须变化并强制完整 bootstrap。底层线程丢失必须自动清除旧游标并完整恢复。`thread_bootstrap` 模式、epoch、是否首次注入、是否增量和是否真正复用后端线程必须进入结果审计与固定发布基准。
41. 第三方多人上下文引擎必须经过版本化宿主，支持 `bootstrap/ingest/assemble/compact/commit_turn/maintain/on_member_start/on_member_end` 生命周期，并保留 legacy `select_context` 兼容适配。未支持的 API 版本必须在进入实时任务前拒绝；每次调用必须有硬超时，连续失败达到阈值后隔离。只有 `assemble` 可影响选择，且输出仍受授权 ID、去重、顺序与二次 Token 预算约束；其他钩子返回值不得进入 Prompt。审计只允许方法名、状态、耗时、错误类型和聚合计数，不得复制请求、候选、结果或异常正文。该协议必须进入真实 WebSocket 群聊测试和固定发布基准。

后台协作队列与调度器可用以下环境变量按部署规模调整，健康接口会返回最终生效值：

- `OCTOPUS_COWORK_QUEUE_PER_THREAD_LIMIT`：单个群聊的活动任务上限，默认 512。
- `OCTOPUS_COWORK_QUEUE_TOTAL_LIMIT`：当前实例共享队列的活动任务上限，默认 4096；若低于单群上限，单群上限会自动收窄到该值。
- `OCTOPUS_COWORK_RUNNER_MAX_CONCURRENCY`：后台执行器自适应并行的硬上限，默认 4。
- `OCTOPUS_COWORK_RUNNER_MAX_TASKS_PER_TICK`：一次调度循环最多处理的任务数，默认 64。
- `OCTOPUS_COWORK_COLLECTOR_RETENTION_SECONDS`：终态 collector 完整结果的保留时长，默认 90 天；设为 `0` 关闭时间归档。
- `OCTOPUS_COWORK_COLLECTOR_RETENTION_COUNT`：每个协作会话最多保留的未归档终态 collector 数，默认 1000；设为 `0` 关闭数量归档。
- `OCTOPUS_COWORK_CONTEXT_ENGINE`：多人上下文选择器名称；未设置或使用 `default` 时启用内置 `adaptive`（Adaptive Recall MMR），可选 `hybrid`、`recency`；使用 `deterministic` 或 `none` 可退回宿主基础排序。第三方实现仅在通过 `octopus.cowork_context_engines` entry point 显式点名时加载。
- `OCTOPUS_SUBAGENT_COMPACTION_TRIGGER_TURNS`：子 Agent 私有会话建立/刷新压缩检查点的轮次阈值，默认 12。
- `OCTOPUS_SUBAGENT_COMPACTION_KEEP_RECENT`：压缩检查点之外继续保留在热上下文中的最近轮次，默认 4；原始轮次始终保留在持久审计记录中。
- `OCTOPUS_SUBAGENT_CHECKPOINT_CHARS`：持久检查点摘要字符上限，默认 1600，宿主还会再次实施总 Prompt 预算。

## 下一阶段领先线

按影响优先级继续推进：

1. **运行中控制与增量上下文的压力互测**：按成员定向纠偏、停止、已完成结果保留和授权感知的私有 session 续接已形成产品闭环，并纳入固定发布基准。下一步与 Hermes v2026.8.31 在相同模型、相同并发、长历史和纠偏频率下互测延迟、额外 Token、重启恢复、权限收窄和竞态收敛，不靠功能清单宣布胜负。
2. **渠道覆盖与运维深度**：在现有 26 渠道、单 Agent / AI 团队绑定、统一诊断和 IRC/Twitch 长连接生命周期之上，继续补齐 OpenClaw 已覆盖的 Nextcloud Talk、Nostr、Zalo 等入口，并完善滞留投递批量处理、线程绑定明细和保留策略。
3. **通用控制流与 collector 运维**：持久 collector 已进入统一协作运行账本，支持跨重启查询、revision 长轮询、失败 attempt 保留、定向后台重派、跨运行集中查看与批量重试/停止/归档、晚到结果隔离、自动期限/数量保留、双层积压反压、原子批量入队、跨群公平轮转和积压自适应并行；DAG 已加入受限、可审计、零任意代码执行的条件控制流。下一步以同任务基准决定是否还需要更自由的代码模式，而不是仅为对齐名称引入第二套运行时。
4. **云执行后端产品化**：现有 Local/Docker/K8s/SSH 已具备底层能力，远端认证链和 SSH 私网隧道已贯通且纳入 fail-closed 基准；下一步统一生产执行协议与能力探测，再补 Modal/Daytona 类托管沙箱的一键配置、租期/成本治理和可观测面。
5. **跨项目外部基准与来源新鲜度**：在锁定版本和同模型/同预算条件下运行真实任务集；每次发布复核上游提交与正式版能力。没有可复现结果，或来源版本已漂移，就不宣称“所有维度领先”。
6. **上下文插件生态与更强隔离**：Context Engine v1 已覆盖八个生命周期钩子、版本协商、超时、连续失败隔离和正文外审计，并进入真实群聊与发布基准。下一步提供独立进程插件沙箱、迁移/升级工具、官方示例包和兼容性认证；在此之前，OpenClaw 的插件生态及 transcript rewrite/compaction ownership 自由度仍更成熟。

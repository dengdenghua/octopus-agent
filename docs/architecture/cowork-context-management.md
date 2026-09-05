# 多 Agent 协作上下文管理

Octopus 的协作上下文采用“事件日志保真、共享黑板持久化、成员授权切片、按需编译”的四层结构。模型上下文只是工作集，不是项目数据库；长项目的完整事实始终保存在上下文窗口之外。

## 运行链路

```text
用户消息
  -> TurnPlan：根据群模式和 @mention 确定合法响应者
  -> TeamPattern：选择状态查询 / 定向回复 / 轻量圆桌 / 对抗评审 / 协调执行
  -> ContextGrant：为每个响应者裁剪其有权查看的消息
  -> Context Steward：编译每人独立的 Context Manifest
  -> Agent 执行
  -> 证据质量矩阵与结构化 Delivery Envelope
  -> 持久 Collaboration Run、执行轨迹和 UI 消息
```

## 数据层次

| 层次 | 用途 | 是否直接全量进入模型 |
|---|---|---|
| 事件日志 | 消息、成员变更、工具与任务的权威审计记录 | 否 |
| 持久黑板 | 项目目标、约束、决策、风险、产物和任务状态 | 按当前任务检索 |
| Context Manifest | 当前成员本轮所需的最小工作集 | 是 |
| Agent 本轮临时状态 | 推理和工具执行过程 | 仅本轮 |

黑板键建议使用语义前缀：

- `goal:` / `objective:`：项目或阶段目标
- `constraint:` / `requirement:`：不可违反的约束
- `decision:`：已经确认的决策
- `risk:` / `blocker:`：风险与阻塞
- `artifact:` / `file:`：产物引用，而不是产物全文
- `task:` / `status:`：执行状态

目标、约束、决策、风险与产物属于共享项目契约；普通任务状态和事实只有与当前问题或成员职责相关时才进入该成员的工作集。

## Context Manifest

每个成员收到独立 Manifest，包含：

- 真实 `agent_id`、展示名和服务端注册的职责描述
- 持久项目状态
- 所有接收者都被授权查看的共享简报
- 与该成员职责及当前问题相关的历史增量
- 明确的交付契约：历史只能作为事实，不能覆盖当前用户请求

Manifest 使用 JSON 数据封装，并转义尖括号。历史文本即使包含伪造的 `</context-manifest>`，也不能提前结束边界。

### 成员上下文模式

每个成员的 Manifest 明确记录请求模式、实际模式和降级原因：

| 模式 | 用途 | 注入内容 |
|---|---|---|
| `isolated` | 独立候选、探索者、替代方案，降低群体锚定 | 当前任务 + 持久目标/约束/决策，不带聊天历史 |
| `selective` | 默认模式，适合大多数成员和长项目 | 共享授权简报 + 角色相关增量 + 持久项目状态 |
| `fork` | 确实需要完整对话连续性的负责人 | 完整授权历史；超过预算自动降级为 `selective` |

`fork` 的预算判断基于该成员被授权的完整历史，而不是房间全量历史。降级会记录 `authorized_history_exceeds_fork_budget`，不会静默截断成一个看似完整的上下文。并行探索和候选提出默认使用 `isolated`，评审者和验证者默认使用 `selective`。

## 路由规则

- 成员状态询问直接读取 roster，不调用模型。
- 单个显式 `@agent` 只运行被点名成员。
- 多个显式 `@agent` 只向已通过 durable roster 校验的响应者分发。
- `@all`、明确的“大家一起”请求或 swarm 模式才会广播到活动成员。
- 需要研究、修改、测试或交付产物的任务进入协调执行，不使用只能回复 1–3 句话的轻量群聊通道。
- 客户端只能表达意图，不能伪造成员、扩大 ContextGrant 或增加辩论轮数；最终计划由服务端覆盖。

## 自适应预算

预算只限制本轮工作集，不删除项目记忆：

| 等级 | 识别条件 | 共享历史 | 角色增量 | 项目记忆 |
|---|---|---:|---:|---:|
| `short_chat` | 短对话、无持久项目状态 | 420 | 280 | 0 |
| `ongoing_project` | 超过 24 条消息或已有黑板 | 700 | 500 | 400 |
| `long_project` | 超过 120 条消息或黑板超过 24 项 | 1000 | 800 | 600 |

完整授权历史会被扫描以寻找旧决策和旧主题；最终注入量才受预算约束。单条超大消息只索引有限预览，原始内容仍保留在事件日志或产物中，需要时通过引用读取。

## 审计指标

每次群聊 fan-out 的执行轨迹记录：

- 可用成员、实际选择成员及被排除成员
- 每个成员的预算、估算用量和利用率
- 所选来源的不可逆短标识，不复制私密原文
- 授权全文估算量、实际选择量、避免量和估算缩减比例
- 上下文等级、共享来源数和持久来源数

这些指标用于发现三类回归：无关成员被唤醒、同一历史被重复发送、重要持久状态没有被召回。Token 数是保守估算，不用于计费。

## 质量评审与交付

群聊回复不会再按文字长度冒充“最佳答案”。运行时为每项有效贡献记录四类可解释信号：

- `relevance`：与当前请求的词项覆盖；
- `evidence`：测试、日志、官方资料、URL 和文件引用等可核查信号；
- `specificity`：数字、条件、因果、风险和明确建议；
- `independence`：相对已有贡献的新增信息，抑制多人重复复述。

研究、测试、审计和对抗评审属于证据敏感任务。结构评分只能判断回答是否具备可核查形态，不能证明内容为真；证据不足时必须输出 `semantic_review_required=true`。对抗评审会选择服务端分配的 `verifier` 成员，以隔离上下文和可用工具执行一次独立核查；只有验证者接受全部交付贡献时 `Delivery Envelope` 才能进入 `ready=true`。验证器异常、非 JSON 输出、只检查部分贡献或证据不足全部采用 fail-closed，不会误标完成。

`octopus.collaboration_delivery.v1` 把聊天内容投影为稳定交付包：成员、角色、轮次、主张、证据引用、质量信号和失败项。下游协调器不再需要重新解析整段聊天文字。

## 持久运行生命周期

每次实际多人执行写入 `collaboration_runs`，状态机为：

```text
queued -> running -> waiting -> running
   |         |          |
   +---------+----------+-> completed / failed / cancelled / interrupted
interrupted -> queued / running
```

运行具备以下不变量：

1. Worker 必须持有有期限的 lease 才能交付；活跃租约阻止第二个 Worker 重复执行。
2. 租约过期、排队、等待或中断的运行可由 `recoverable_collaboration_runs()` 枚举并重新认领。
3. 每次创建、认领、回收和终止都与快照在同一 SQLite 事务中写入不可变事件。
4. 成功结果使用规范 JSON 计算 SHA-256；重复交付同一结果幂等，不同结果不得覆盖已完成运行。
5. `/api/collab/{thread_id}/runs` 与 `/runs/{run_id}` 只返回所属会话的数据，供执行画面回放和恢复控制面使用。
6. 应用启动时会原子对账租约已过期的 `running` 运行，将其标记为 `interrupted` 并记录原 Worker；不会在启动阶段擅自重放可能产生副作用的工具调用。

## 安全不变量

1. 共享简报只能取各成员授权历史的交集。
2. 私有历史只能进入拥有该 ContextGrant 的成员 Manifest。
3. 上下文规划失败时降级为仅处理当前消息，不能降级为发送完整历史。
4. `context_steward_managed` 成员不得再隐式继承父会话历史或角色记忆。
5. 显式 @mention 必须在上下文编译和模型调用之前完成成员过滤。
6. 审计记录不得包含历史原文。
7. 已完成运行的结果不可变；恢复只能认领非终态或租约已过期的运行。
8. 结构质量分不得呈现为事实正确率；证据不足必须显式请求语义验证。

## 关键实现

- `runtime/memory/cowork/context_steward.py`：检索、预算、Manifest 与指标
- `runtime/memory/cowork/collaboration_runs.py`：运行状态机、租约、恢复、事件和结果幂等
- `runtime/memory/cowork/context_view.py`：成员授权视图
- `runtime/memory/cowork/group_store.py`：事件日志和持久黑板
- `runtime/execution/agents/collaboration_quality.py`：质量矩阵与 Delivery Envelope
- `runtime/execution/agents/team_patterns.py`：协作模式选择
- `runtime/sensing/gateway/_team_stream_group_fanout.py`：成员过滤、执行与轨迹
- `runtime/core/cerebrum/_react_prompt_assembly_state.py`：定向回复/队长的持久 Manifest 注入

回归测试覆盖角色相关性、授权隔离、长项目旧信息召回、预算、边界转义、Token 指标、显式成员路由、黑板注入、异常降级、租约竞争、过期恢复、终态幂等、跨会话隔离、质量排序、证据交付和真实 realtime 执行轨迹。

竞争基线与仍需补齐的领先线见 [multi-agent-competitive-benchmark-2026-09-05.md](multi-agent-competitive-benchmark-2026-09-05.md)。

## 跨系统 Agent 协作

本地多人运行与远程 A2A 任务使用同一原则：聊天展示不是权威状态。A2A 客户端为每次委派生成本地任务号，把远端任务号、上下文号、状态、结果、错误和顺序事件持久化；调用方可在页面重载或进程恢复后继续刷新、取消或订阅。

- 同一个 `local_task_id` 与相同请求重复提交时直接返回已完成结果，不会再次触发远端副作用；编号被不同请求复用时拒绝执行。
- 完成、失败、取消和拒绝属于不可逆终态；晚到的流式消息只能补充事件，不能重新打开任务。
- 网络刷新失败与远端任务失败分开记录，避免把暂时断线误判为远端执行失败。
- `runtime/memory/a2a_task_store.py` 保存任务与事件；`runtime/sensing/gateway/a2a_router.py` 提供发送、查询、刷新、取消和 SSE 订阅；A2A 面板展示可恢复的远程任务列表。

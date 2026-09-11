# OpenCode 多人对话路由修复

日期：2026-09-08（Asia/Shanghai）

## 问题与根因

对话 `tcrw3P5HRdDAXtWW7Aoi5P` 中，单人使用 OpenCode 正常，加入 Zero 后发送“大家好”被阻止：

> 项目和团队协作请使用自动或 Echo 引擎；独立成员任务可使用外部引擎。

`runtime/execution/engines.py` 在选择宿主调度器之前，仍按旧规则拒绝显式 Codex / OpenCode 与 `project_command`、`group_fanout` 的组合。现有外部引擎适配器已经支持先运行宿主调度、再用绑定引擎处理后续模型调用，这条入口限制与实现不一致。

前端 `useExecutionEngine` 同时把所有协作场景的外部引擎标记为不可用，导致 OpenCode 旁出现错误提示。

## 修改

- 项目调度和普通多人回复可以保留显式外部引擎选择，继续由 Echo 调度成员；成员自身的引擎策略保持原样。
- 继续保留尚依赖原生图规划器的集群拓扑限制，使用单独的 `topology_requires_native` 原因。前端只在这一模式禁用外部引擎，不再禁用普通多人对话。
- 引擎就绪检查、宿主审批对象、子任务权限上限、模型选择与取消机制不变。
- 增加显式选择、调度优先级、成员执行、后续调用以及前端加入第二位成员的回归覆盖。

## 验证

- Python：`test_execution_engines`、`test_external_coordinator`、`test_realtime_execution`、`test_opencode_backend`、`test_member_engine_policy`、`test_auto_external_engine`，共 **141 项通过**。
- 前端：引擎选择 hook 和 picker，共 **24 项通过**；TypeScript 检查通过。
- Python Ruff 检查及格式检查通过。前端 ESLint 无错误，实时页面仍有原有 `useMemo` 缺少 `executionSelection` 依赖的警告。
- 多人集成测试使用真实网关、宿主调度器、子任务桥接和角色执行入口，模型流使用测试替身；真实模型验收见下。

## 原对话真实验收

完整重启后端（PID 37400，22:03:43 启动），恢复已有本地账号 123，点击原失败消息的“重试”。前端 3310、后端 8310 健康检查均为 HTTP 200。

- 重试 turn：`trn_28a25e2dd1aa4335`。
- 执行时间：22:05:25 至 22:06:04，持久化状态 `completed`。
- 持久化引擎：`opencode`；调度器：`group_fanout`。
- 保留模型 big-pickle、工作区 `D:\echo agent` 和原两位成员。
- Eve（general）和 Zero（aoi）均真实完成 OpenCode 调用；界面显示 **2/2 已返回**，各自回复带 OpenCode 标识。
- 原失败消息显示“先前尝试失败，后续已恢复”；引擎入口不再提示团队不可用。
- 本次耗时约 39 秒，现有协作质量检查对两位成员各追加了一次自动返工；这不是引擎切换或原生模型兜底。

证据：`recovered.png`。
